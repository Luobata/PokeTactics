"""Headless full-game arena (ruleset='arena_v1') probe with pluggable collectors.

The driver (run_game) plays complete arena sessions through the real demo
action router: seat 0 is piloted by the same L2 Bot policy as the AI seats
(tactical_run_probe.mirror_decision), augments and component supplies are
claimed with real claim actions, and only PNG rendering is replaced by a
headless Battle. Metrics live in Collector subclasses — PoolCollector powers
the pool-scarcity report; TechniqueCollector is the reserved hook for the
planned technique-machine balance report (learned-machine counts always on,
raw player-battle event streams behind capture_events, default off). New
reports add a collector; the driver does not change.

Example: python3 tools/acceptance/arena_probe.py --games 100 --seed-base
2026101100 --output .build/arena-probe/pool-n100.json
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/acceptance'), str(ROOT / 'sim'), str(ROOT)]
import arena as arena_mod
from arena_teaching import technique_limit
from bots import Bot, PERSONALITIES
from combat import Battle
from combination_view import direct_damage, technique_summary
import demo
import rng
import shop as shop_mod
import tactical_run_probe
import techniques
from session_save import rules_fingerprint

CONTEXT = {'row': None, 'player_battle': False, 'capture_events': False}

REAL_DRAW_SLOT = shop_mod.draw_slot

TECH_BATTLE_COUNTERS = ('triggers', 'casts', 'damage', 'control_hits', 'control_misses',
                        'healing', 'cleanses', 'marks', 'windows', 'charges',
                        'empowered_hits', 'empower_damage', 'knockbacks',
                        'weather_requests', 'caps', 'carriers')


def observe_techniques(row, battle):
    """Fold one arena battle's technique telemetry into the game accumulators.

    Bot-vs-bot battles resolve through the same patched in-process Battle
    (Session._fight), so their event streams are observable here even though
    production never persists them; the 'player' bucket keeps the subset
    whose events used to be the only available口径.
    """
    stats = row['technique_stats']
    teams = {unit.idx: unit.team for unit in battle.units}
    buckets = [stats['all'], stats['player']] if CONTEXT['player_battle'] else [stats['all']]
    for bucket in buckets:
        bucket['battles'] += 1
    for team in (0, 1):
        summary = technique_summary(battle.events, teams, team)
        caps = Counter()
        carriers = Counter()
        for unit in battle.units:
            if unit.team == team and unit.technique:
                caps[unit.technique] += technique_limit(unit)
                carriers[unit.technique] += 1
        for bucket in buckets:
            bucket['direct_damage'] += direct_damage(battle.events, teams, team)
            per_key = bucket['per_key']
            for entry in summary['by_key']:
                key = entry['id']
                for field in TECH_BATTLE_COUNTERS:
                    if entry.get(field):
                        per_key[key][field] += entry[field]
                if caps.get(key):
                    per_key[key]['caps'] += caps[key]
                    per_key[key]['carriers'] += carriers[key]


class ObservedBattle(Battle):
    def run(self):
        result = super().run()
        row = CONTEXT['row']
        if row is not None:
            row['battle_count'] += 1
            if CONTEXT['player_battle']:
                row['player_battle_count'] += 1
                if CONTEXT['capture_events']:
                    row['player_battle_events'].append(
                        {'round': row['current_round'], 'events': list(self.events)})
            if getattr(self, '_arena_on', False):
                observe_techniques(row, self)
        return result


def headless(a, b, battle_rng, weather, path, positions_a=None, hud_snapshot=None, **options):
    """Player battle without PNG I/O; keeps the arena statistics/effect ledger."""
    CONTEXT['player_battle'] = True
    try:
        battle = ObservedBattle(a, b, battle_rng, layout='back', weather_name=weather,
                                positions_a=positions_a, **options)
        result = battle.run()
        meta = {'n': 0, 'winner': result['winner'], 'survivors': result['survivors'],
                'duration': result['duration'], 'events': [],
                'statistics': battle.statistics()}
        meta.update(demo._battle_effects(battle.events, {u.idx: u.team for u in battle.units}))
        return meta
    finally:
        CONTEXT['player_battle'] = False


def counting_draw_slot(rng_, level, pool, templates):
    """Wrap shop.draw_slot: a None slot means the whole shared pool was empty."""
    sid = REAL_DRAW_SLOT(rng_, level, pool, templates)
    row = CONTEXT['row']
    if row is not None:
        row['shop_slots_drawn'] += 1
        if sid is None:
            row['shop_slots_empty'] += 1
    return sid


def action(session, cmd, fatal=True, **params):
    result = demo._apply_action({'sid': session.sid, 'cmd': cmd, **params})
    row = CONTEXT['row']
    row['actions'][cmd] += 1
    if not result['ok']:
        row['blocked_actions'].append({'round': session.round_no, 'cmd': cmd,
                                       'params': {k: v for k, v in params.items()},
                                       'error': result.get('error')})
        if fatal:
            raise RuntimeError(f'{cmd}: {result.get("error")}')
    return result


class Collector:
    """Per-game metrics hook point; the driver calls, the collector computes."""

    def on_round_end(self, session):
        pass

    def on_game_over(self, session):
        pass

    def result(self):
        return {}


class PoolCollector(Collector):
    """W0 pool-scarcity metrics: per-round remaining, contention, 3★, crashes.

    Acquisitions are approximated by positive deltas of per-seat per-species
    held copies between consecutive round-end snapshots (a sell-and-rebuy
    inside one round is invisible); holdings are pool-conserved, so this
    undercounts churn but never invents copies.
    """

    def __init__(self, templates):
        self.caps = arena_mod.pool_caps()
        self.tier_of = {sid: templates[sid].tier for sid in self.caps}
        self.total_cap = sum(self.caps.values())
        self.timeline = {sid: [] for sid in self.caps}
        self.holders_timeline = {sid: [] for sid in self.caps}
        self.taken_per_round = []
        self.star3_timeline = []        # per round: {tier: count} over alive seats
        self.acquired = defaultdict(Counter)    # seat -> sid -> cumulative takes
        self.prev_held = {}
        self.player_death_taken = None

    def on_round_end(self, session):
        held = {}
        star3 = Counter()
        for seat in session.seats:
            if not seat.alive:
                continue
            counts = Counter()
            for owned in seat.all_pieces():
                counts.update(owned.sources)
                if owned.piece.star == 3:
                    star3[owned.piece.tier] += 1
            held[seat.seat] = counts
        for sid, remaining in session.pool.remaining.items():
            self.timeline[sid].append(remaining)
            self.holders_timeline[sid].append(
                sum(1 for counts in held.values() if counts[sid] > 0))
        self.taken_per_round.append(self.total_cap - sum(session.pool.remaining.values()))
        self.star3_timeline.append(dict(star3))
        for seat_id, counts in held.items():
            for sid, n in counts.items():
                prev = self.prev_held.get((seat_id, sid), 0)
                if n > prev:
                    self.acquired[seat_id][sid] += n - prev
        self.prev_held = {(seat_id, sid): n
                          for seat_id, counts in held.items() for sid, n in counts.items()}
        if not session.player.alive and self.player_death_taken is None:
            self.player_death_taken = self.taken_per_round[-1]

    def result(self):
        species = {}
        for sid, cap in self.caps.items():
            timeline = self.timeline[sid]
            species[str(sid)] = {
                'tier': self.tier_of[sid], 'cap': cap,
                'min_remaining': min(timeline),
                'depleted_round': next((i + 1 for i, n in enumerate(timeline) if n == 0), None),
                'peak_taken': cap - min(timeline),
                'final_taken': cap - timeline[-1],
                'peak_holders': max(self.holders_timeline[sid]),
            }
        crashes = []
        for sid, cap in self.caps.items():
            racers = {seat: n for seat, counts in self.acquired.items()
                      if (n := counts.get(sid, 0)) >= 6}
            if len(racers) >= 2:
                crashes.append({'sid': sid, 'tier': self.tier_of[sid],
                                'seats': sorted(racers), 'acquired': [racers[s] for s in sorted(racers)]})
        star3_peak, star3_final = Counter(), Counter()
        for snap in self.star3_timeline:
            for tier, n in snap.items():
                star3_peak[tier] = max(star3_peak[tier], n)
        for tier, n in self.star3_timeline[-1].items():
            star3_final[tier] = n
        star3_peak = {str(k): v for k, v in star3_peak.items()}
        star3_final = {str(k): v for k, v in star3_final.items()}
        return {
            'total_cap': self.total_cap,
            'rounds': len(self.taken_per_round),
            'species': species,
            'gross_taken_by_seat': {str(seat): {str(sid): n for sid, n in counts.items()}
                                    for seat, counts in self.acquired.items()},
            'three_star_peak_by_tier': dict(star3_peak),
            'three_star_final_by_tier': dict(star3_final),
            'crashes': crashes,
            'taken_per_round': self.taken_per_round,
            'peak_taken_total': max(self.taken_per_round),
            'final_taken_total': self.taken_per_round[-1],
            'player_death_taken_total': self.player_death_taken,
            'remaining_timeline': {str(sid): tl for sid, tl in self.timeline.items()},
        }


class TechniqueCollector(Collector):
    """Technique-machine balance telemetry: adoption, battle output, outcomes.

    - learned_by_seat: any owned piece (board or bench) ever carried the key
      while the seat was alive — covers bot free teaching, loot machines and
      the pilot's learn actions alike.
    - board_carry: keys on the seat's board at its last alive round; paired
      with final ranks this gives per-key win/top-4 rates.
    - battle_stats: per-battle technique_summary fold maintained by
      ObservedBattle (all battles, plus the player-battle subset).
    Raw player-battle event streams are retained only with capture_events=True
    (memory-heavy, off by default).
    """

    def __init__(self, capture_events=False):
        self.capture_events = capture_events
        self.granted = Counter()
        self.learned = Counter()            # pilot's own learn actions (seat 0)
        self.player_battle_events = []
        self.learned_by_seat = defaultdict(set)
        self.board_carry = {}
        self.ranks = {}
        self.battle_stats = None

    def on_round_end(self, session):
        for seat in session.seats:
            if not seat.alive:
                continue
            self.learned_by_seat[seat.seat] |= {owned.technique
                                                for owned in seat.all_pieces()
                                                if owned.technique}
            self.board_carry[seat.seat] = sorted({owned.technique
                                                  for owned in seat.board
                                                  if owned.technique})

    def on_game_over(self, session):
        for entry in session.arena_loot:
            if entry['seat'] != 0:
                continue
            for grant in entry['grants']:
                if grant['kind'] == 'technique':
                    self.granted[grant['key']] += 1
        self.ranks = {seat.seat: seat.rank for seat in session.seats}
        row = CONTEXT['row']
        if row is not None:
            self.learned.update(row['claimed_techniques'])
            stats = row['technique_stats']
            self.battle_stats = {
                'all': {'battles': stats['all']['battles'],
                        'direct_damage': stats['all']['direct_damage'],
                        'per_key': {key: dict(counts)
                                    for key, counts in stats['all']['per_key'].items()}},
                'player': {'battles': stats['player']['battles'],
                           'direct_damage': stats['player']['direct_damage'],
                           'per_key': {key: dict(counts)
                                       for key, counts in stats['player']['per_key'].items()}},
            }
            if self.capture_events:
                self.player_battle_events = row['player_battle_events']

    def result(self):
        out = {'granted': dict(self.granted), 'learned': dict(self.learned),
               'learned_total': sum(self.learned.values()),
               'granted_total': sum(self.granted.values()),
               'learned_by_seat': {str(seat): sorted(keys)
                                   for seat, keys in self.learned_by_seat.items()},
               'board_carry_final': {str(seat): keys
                                     for seat, keys in self.board_carry.items()},
               'ranks': {str(seat): rank for seat, rank in self.ranks.items()},
               'battle_stats': self.battle_stats}
        if self.capture_events:
            out['player_battle_events'] = self.player_battle_events
        return out


def pilot_prep(session, pilot):
    """Seat-0 prep: bot-policy buy/sell/deploy, then spend machines from loot.

    Arena has no tactical reward/guard/weather flow (session.rewards stays
    empty), so the tactical pilot_prep tail does not apply; machines are
    learned through the arena loc-based learn action, only when a machine is
    actually in inventory (never the gold-paid fallback).
    """
    tactical_run_probe.mirror_decision(session, pilot)
    row = CONTEXT['row']
    player = session.player
    loc_of = {id(owned): f'g{r},{c}' for (r, c), owned in player.grid.items()}
    loc_of.update({id(owned): f'b{i}' for i, owned in enumerate(player.bench)})
    for technique in techniques.ids_for(session.ruleset):
        for owned in list(player.board):
            if player.inventory.techniques.get(technique, 0) <= 0:
                break
            if owned.technique is None and techniques.compatible_species(
                    owned.piece.species_id, technique, session.ruleset):
                result = action(session, 'learn', fatal=False,
                                loc=loc_of[id(owned)], technique=technique)
                if result['ok']:
                    row['claimed_techniques'][technique] += 1


def run_game(seed, personality, collectors, capture_events=False):
    row = {'seed': seed, 'personality': personality, 'status': 'running',
           'current_round': 1, 'battle_count': 0, 'player_battle_count': 0,
           'actions': Counter(), 'blocked_actions': [],
           'claimed_augments': Counter(), 'claimed_techniques': Counter(),
           'player_battle_events': [], 'shop_slots_drawn': 0, 'shop_slots_empty': 0,
           'technique_stats': {'all': {'battles': 0, 'direct_damage': 0,
                                       'per_key': defaultdict(Counter)},
                               'player': {'battles': 0, 'direct_damage': 0,
                                          'per_key': defaultdict(Counter)}},
           'rounds': []}
    CONTEXT['row'] = row
    CONTEXT['capture_events'] = capture_events
    session = demo.Session(seed, ruleset='arena_v1')
    session.sid = f'{seed:012x}'
    session.run_id = hashlib.sha256(f'arena-probe:{seed}'.encode()).hexdigest()[:32]
    session.begin_round(1)
    session.observe()
    demo.SESSIONS[session.sid] = session
    pilot = Bot(0, 2, personality, session.pool, session.templates)
    choice_rng = random.Random(seed)
    try:
        for _ in range(demo.MAX_ROUNDS):
            if session.phase == 'over':
                break
            row['current_round'] = session.round_no
            if session.player.alive:
                for pending in list(session.arena_augments_pending):
                    choice = choice_rng.choice(pending['options'])['id']
                    action(session, 'claim_augment', id=pending['id'], choice=choice)
                    row['claimed_augments'][choice] += 1
                for reward in list(session.arena_component_choices):
                    if reward['seat'] == 0 and reward['status'] == 'pending':
                        action(session, 'claim_component', reward_id=reward['id'],
                               choice=choice_rng.choice(reward['options']))
                pilot_prep(session, pilot)
            action(session, 'end_prep')
            for collector in collectors:
                collector.on_round_end(session)
            row['rounds'].append({'round': session.round_no, 'alive': len(session._alive()),
                                  'player_alive': session.player.alive,
                                  'hp': session.player.hp, 'level': session.player.level,
                                  'gold': session.player.gold})
            if not session.player.alive and 'player_eliminated_round' not in row:
                row['player_eliminated_round'] = session.round_no
            if session.phase != 'over':
                action(session, 'next')
        assert session.phase == 'over', ('never reached terminal', session.round_no, session.phase)
        for collector in collectors:
            collector.on_game_over(session)
        row.update(status='complete', player_rank=session.player.rank,
                   player_rounds=session.eliminated_round or session.round_no,
                   table_rounds=session.round_no, final_alive=len(session._alive()),
                   natural_terminal=len(session._alive()) == 1)
        row['collectors'] = {type(c).__name__: c.result() for c in collectors}
    except Exception as exc:
        row.update(status='error', error=repr(exc), traceback=traceback.format_exc(),
                   failed_round=session.round_no, failed_phase=session.phase)
        print(f'ERROR seed={seed} personality={personality} round={session.round_no}: {exc}',
              flush=True)
    finally:
        demo.SESSIONS.pop(session.sid, None)
        CONTEXT['row'] = None
        CONTEXT['capture_events'] = False
    return row


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, max(0, round(q * (len(values) - 1))))]


def summarize_pool(games):
    """Cross-game aggregation of PoolCollector results, grouped by cost tier."""
    complete = [g for g in games if g['status'] == 'complete' and 'collectors' in g]
    pools = [g['collectors']['PoolCollector'] for g in complete]
    tiers = sorted({row['tier'] for pool in pools for row in pool['species'].values()})
    by_tier = {}
    for tier in tiers:
        rows = [dict(row, sid=sid) for pool in pools for sid, row in pool['species'].items()
                if row['tier'] == tier]
        per_game = []
        for pool in pools:
            own = [row for row in pool['species'].values() if row['tier'] == tier]
            per_game.append({
                'depleted': sum(row['depleted_round'] is not None for row in own),
                'multi_holder': sum(row['peak_holders'] >= 2 for row in own),
                'crashes': sum(c['tier'] == tier for c in pool['crashes']),
                'star3_peak': pool['three_star_peak_by_tier'].get(str(tier), 0),
                'star3_final': pool['three_star_final_by_tier'].get(str(tier), 0),
            })
        by_tier[str(tier)] = {
            'species': len(rows) // max(1, len(pools)),
            'cap_per_species': rows[0]['cap'] if rows else None,
            'min_remaining_mean': round(statistics.mean(r['min_remaining'] for r in rows), 2),
            'min_remaining_min': min(r['min_remaining'] for r in rows),
            'depleted_species_per_game_mean': round(statistics.mean(g['depleted'] for g in per_game), 2),
            'games_with_depletion': sum(g['depleted'] > 0 for g in per_game),
            'peak_taken_mean': round(statistics.mean(r['peak_taken'] for r in rows), 2),
            'peak_taken_p90': percentile([r['peak_taken'] for r in rows], 0.9),
            'peak_taken_max': max(r['peak_taken'] for r in rows),
            'pct_species_peak_taken_ge9': round(100 * sum(r['peak_taken'] >= 9 for r in rows) / len(rows), 1),
            'pct_species_peak_taken_ge18': round(100 * sum(r['peak_taken'] >= 18 for r in rows) / len(rows), 1),
            'final_taken_mean': round(statistics.mean(r['final_taken'] for r in rows), 2),
            'peak_holders_mean': round(statistics.mean(r['peak_holders'] for r in rows), 2),
            'peak_holders_max': max(r['peak_holders'] for r in rows),
            'pct_species_multi_holder': round(100 * sum(r['peak_holders'] >= 2 for r in rows) / len(rows), 1),
            'games_with_2seat_hold': round(100 * sum(g['multi_holder'] > 0 for g in per_game) / len(per_game), 1),
            'star3_peak_mean': round(statistics.mean(g['star3_peak'] for g in per_game), 2),
            'star3_peak_max': max(g['star3_peak'] for g in per_game),
            'star3_final_mean': round(statistics.mean(g['star3_final'] for g in per_game), 2),
            'crashes_per_game_mean': round(statistics.mean(g['crashes'] for g in per_game), 2),
            'games_with_crash': sum(g['crashes'] > 0 for g in per_game),
        }
    drawn = sum(g['shop_slots_drawn'] for g in games)
    claims = Counter()
    for g in games:
        claims.update(g['claimed_augments'])
    summary = {
        'games': len(games), 'complete': len(complete), 'errors': len(games) - len(complete),
        'personalities': dict(Counter(g['personality'] for g in games)),
        'battles': sum(g['battle_count'] for g in games),
        'player_battles': sum(g['player_battle_count'] for g in games),
        'blocked_actions': sum(len(g['blocked_actions']) for g in games),
        'table_rounds_mean': round(statistics.mean(
            g['table_rounds'] for g in complete), 2) if complete else None,
        'player_rank_counts': dict(Counter(g['player_rank'] for g in complete)),
        'shop_slots_drawn': drawn,
        'shop_slots_empty': sum(g['shop_slots_empty'] for g in games),
        'shop_empty_rate': (sum(g['shop_slots_empty'] for g in games) / drawn) if drawn else 0,
        'claimed_augments': dict(claims),
        'techniques_learned_total': sum(
            g['collectors']['TechniqueCollector']['learned_total']
            for g in complete if 'TechniqueCollector' in g.get('collectors', {})),
        'utilization': {
            'total_cap': pools[0]['total_cap'] if pools else None,
            'peak_taken_mean': round(statistics.mean(p['peak_taken_total'] for p in pools), 1) if pools else None,
            'peak_taken_max': max((p['peak_taken_total'] for p in pools), default=None),
            'final_taken_mean': round(statistics.mean(p['final_taken_total'] for p in pools), 1) if pools else None,
            'player_death_taken_mean': round(statistics.mean(
                p['player_death_taken_total'] for p in pools
                if p['player_death_taken_total'] is not None), 1) if any(
                    p['player_death_taken_total'] is not None for p in pools) else None,
        },
        'by_tier': by_tier,
    }
    return summary


def wilson(k, n, z=1.96):
    """Wilson score interval for a binomial rate; returns (rate, low, high)."""
    if not n:
        return (None, None, None)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (round(p, 4), round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


def summarize_techniques(games):
    """Cross-game per-machine report: adoption, battle output, outcomes.

    Battle counters fold every in-process arena battle (bot-bot included —
    their event streams exist in memory, only persistence drops them); the
    'player' block repeats the same metrics for seat-0 battles only. Outcome
    rates attribute the machine a seat had on board at its last alive round.
    """
    complete = [g for g in games
                if g['status'] == 'complete' and 'TechniqueCollector' in g.get('collectors', {})]
    techs = [g['collectors']['TechniqueCollector'] for g in complete]
    n_games = len(complete)
    per_key = {}
    for key in techniques.ids_for('arena_v1'):
        learned_games = [t for t in techs
                         if any(key in keys for keys in t['learned_by_seat'].values())]
        seats_learned = sum(key in keys for t in techs for keys in t['learned_by_seat'].values())
        carried = [(int(seat), t['ranks'].get(seat))
                   for t in techs for seat, keys in t['board_carry_final'].items()
                   if key in keys]
        wins = sum(rank == 1 for _, rank in carried)
        top4 = sum(rank is not None and rank <= 4 for _, rank in carried)
        battle = Counter()
        player_battle = Counter()
        for t in techs:
            stats = t.get('battle_stats') or {}
            battle.update((stats.get('all') or {}).get('per_key', {}).get(key, {}))
            player_battle.update((stats.get('player') or {}).get('per_key', {}).get(key, {}))
        win_rate, win_lo, win_hi = wilson(wins, len(carried))
        top4_rate, top4_lo, top4_hi = wilson(top4, len(carried))
        per_key[key] = {
            'games_learned_any': len(learned_games),
            'learn_rate': round(len(learned_games) / n_games, 4) if n_games else None,
            'games_learned_player': sum(key in t['learned_by_seat'].get(0, ())
                                        or key in t['learned_by_seat'].get('0', ())
                                        for t in techs),
            'games_learned_bots': sum(any(key in keys for seat, keys in
                                          t['learned_by_seat'].items() if str(seat) != '0')
                                      for t in techs),
            'seats_learned': seats_learned,
            'triggers': battle['triggers'],
            'triggers_per_game': round(battle['triggers'] / n_games, 3) if n_games else None,
            'triggers_per_learned_game': (round(battle['triggers'] / len(learned_games), 3)
                                          if learned_games else None),
            'cap_utilization': (round(battle['triggers'] / battle['caps'], 4)
                                if battle['caps'] else None),
            'damage': battle['damage'],
            'damage_per_game': round(battle['damage'] / n_games, 1) if n_games else None,
            'control_hits': battle['control_hits'],
            'control_misses': battle['control_misses'],
            'healing': battle['healing'], 'cleanses': battle['cleanses'],
            'empower_damage': battle['empower_damage'],
            'windows': battle['windows'], 'charges': battle['charges'],
            'marks': battle['marks'], 'knockbacks': battle['knockbacks'],
            'weather_requests': battle['weather_requests'],
            'player_battle_triggers': player_battle['triggers'],
            'player_battle_damage': player_battle['damage'],
            'carried_seats': len(carried),
            'wins': wins, 'win_rate': win_rate, 'win_ci95': [win_lo, win_hi],
            'top4': top4, 'top4_rate': top4_rate, 'top4_ci95': [top4_lo, top4_hi],
        }
    direct = sum((t.get('battle_stats') or {}).get('all', {}).get('direct_damage', 0)
                 for t in techs)
    player_direct = sum((t.get('battle_stats') or {}).get('player', {}).get('direct_damage', 0)
                        for t in techs)
    battles = sum((t.get('battle_stats') or {}).get('all', {}).get('battles', 0)
                  for t in techs)
    player_battles = sum((t.get('battle_stats') or {}).get('player', {}).get('battles', 0)
                         for t in techs)
    for key, row in per_key.items():
        row['damage_share'] = round(row['damage'] / direct, 4) if direct else None
    return {'games': n_games, 'battles': battles, 'player_battles': player_battles,
            'direct_damage_total': direct, 'player_direct_damage_total': player_direct,
            'per_key': per_key}


def run_games(games, seed_base, capture_events=False, progress=False):
    rows = []
    with patch.object(demo, 'SESSIONS', {}), patch.object(demo, 'Battle', ObservedBattle), \
            patch.object(demo, '_render_battle_frames', side_effect=headless), \
            patch.object(shop_mod, 'draw_slot', counting_draw_slot):
        for index in range(games):
            collectors = [PoolCollector(arena_mod.build_templates()),
                          TechniqueCollector(capture_events=capture_events)]
            rows.append(run_game(seed_base + index, sorted(PERSONALITIES)[index % 4],
                                 collectors, capture_events=capture_events))
            if progress and index % 4 == 3:
                print(f'Completed {index + 1}/{games}', flush=True)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=100,
                        help='Independent games, 1–4096 (default: 100).')
    parser.add_argument('--seed-base', type=int, default=2026101100,
                        help='First nonnegative signed-64-bit seed; subsequent games use consecutive seeds.')
    parser.add_argument('--capture-events', action='store_true',
                        help='Retain raw player-battle event streams (memory-heavy; for technique reports).')
    parser.add_argument('--output', type=Path, default=ROOT / '.build/arena-probe/pool-n100.json',
                        help='Evidence JSON path; a game save directory is never allowed.')
    args = parser.parse_args(argv)
    if not 1 <= args.games <= 4096:
        parser.error('--games must be between 1 and 4096')
    if not 0 <= args.seed_base <= 2 ** 63 - args.games:
        parser.error('--seed-base and the final consecutive seed must fit nonnegative signed-64-bit integers')
    args.output = args.output.resolve()
    if args.output.is_relative_to(demo.SAVE_ROOT.resolve()):
        parser.error('--output must not point into the game save directory')
    if args.output.is_dir():
        parser.error('--output must name a JSON file, not a directory')
    rows = run_games(args.games, args.seed_base, capture_events=args.capture_events,
                     progress=True)
    summary = summarize_pool(rows)
    payload = {'method': __doc__, 'ruleset': arena_mod.RULESET,
               'rules_fingerprint': rules_fingerprint(),
               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'seed_base': args.seed_base, 'capture_events': args.capture_events,
               'summary': summary, 'techniques': summarize_techniques(rows),
               'games': rows,
               'limits': ['L2 pilot is not a human player; contention patterns come from bot policy.',
                          'Per-seat acquisitions are positive deltas between round-end snapshots; '
                          'sell-and-rebuy inside one round is invisible.',
                          'Technique battle counters fold every in-process arena battle '
                          '(bot-bot event streams are observable via the patched Battle but '
                          'are never persisted in production); sleep_powder/toxic status '
                          'applications carry no caster attribution and are counted as casts only.',
                          'Outcome rates credit the machine on board at the seat\'s last alive '
                          'round; mid-game carries that were sold or combined away are not credited.',
                          'No PNG, disk save or profile IO; pool conservation is checked by construction '
                          'of the snapshots, not asserted per round.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f'Written: {args.output}', flush=True)
    return 0 if not summary['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
