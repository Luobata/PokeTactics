"""Full-run smoke of real tactics Sessions, without game save/profile IO.

The seat-0 pilot copies the existing L2 Bot decision policy, as the previous
pacing audit did: ordinary gold, shops, pool, items and evolution are unchanged.
Rewards, teaching and UID selections use the actual demo action router. Only PNG
rendering is replaced; Battle keeps production layout='back' and all options.
R6/R11 schema-4 checkpoints use the real codec and exact payload equality.
This is workflow/exception coverage, not a balance or human-duration estimate.

Example: python3 tools/acceptance/tactical_run_probe.py --games 32 --seed-base
2026100500 --output .build/tactics/full-run-probe.json
"""
import argparse
from collections import Counter
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
import demo
import expedition
from bots import Bot, PERSONALITIES
from combat import Battle
import rng
import techniques
from session_save import SessionCodec, rules_fingerprint

CONTEXT = {'row': None, 'player_battle': False}
CODEC = SessionCodec()


class ObservedBattle(Battle):
    def run(self):
        result = super().run()
        row = CONTEXT['row']
        if row is not None:
            row['battle_count'] += 1
            if CONTEXT['player_battle']:
                row['player_battle_count'] += 1
            for event in self.events:
                if event[1] != 'tactical_effect':
                    continue
                effect = event[4]
                row['tactical_events'][effect] += 1
                if CONTEXT['player_battle']:
                    row['player_battle_tactical_events'][effect] += 1
                if len(row['sample_events']) < 12:
                    row['sample_events'].append({'round': row['current_round'],
                                                 'player_battle': CONTEXT['player_battle'],
                                                 'event': event})
        return result


def headless(a, b, battle_rng, weather, path, positions_a=None, hud_snapshot=None, **options):
    CONTEXT['player_battle'] = True
    try:
        battle = ObservedBattle(a, b, battle_rng, layout='back', weather_name=weather,
                                positions_a=positions_a, **options)
        result = battle.run()
        return {'n': 0, 'winner': result['winner'], 'survivors': result['survivors'],
                'duration': result['duration'], 'events': []}
    finally:
        CONTEXT['player_battle'] = False


def action(session, cmd, **params):
    result = demo._apply_action({'sid': session.sid, 'cmd': cmd, **params})
    CONTEXT['row']['actions'][cmd] += 1
    if not result['ok']:
        CONTEXT['row']['blocked_actions'].append({'round': session.round_no, 'cmd': cmd,
                                                 'params': params, 'error': result.get('error')})
        raise RuntimeError(f'{cmd}: {result.get("error")}')
    return result


def pilot_prep(session, pilot):
    player = session.player
    for key, value in vars(player).items():
        if key not in ('grid', 'name'):
            setattr(pilot, key, value)
    pilot.board = player.board
    pilot.decide(session.round_no, [pilot, *session.bots],
                 rng.derive(session.seed, session.round_no, 'bots', 0))
    for key, value in vars(pilot).items():
        if key not in ('grid', 'board', 'seat', 'name'):
            setattr(player, key, value)
    player.grid = dict(zip(demo._GRID_ORDER, pilot.board))
    session.ensure_unit_ids()
    notices = session.refresh_tactics()
    CONTEXT['row']['invalidated_configuration_notices'].extend(
        {'round': session.round_no, 'reason': note} for note in notices)

    # Same board-aware finite reward preference as the bot helper, while claiming
    # through the actual player action. No inventory or currency is injected.
    for reward in list(session.rewards):
        if reward['seat'] != 0 or reward['status'] != 'pending':
            continue
        def score(key):
            eligible = [o for o in player.board if o.technique is None and
                        techniques.compatible_species(o.piece.species_id, key)]
            if not eligible:
                return (0, 0)
            if key in ('sunny_day', 'rain_dance'):
                types = {'FIRE', 'GRASS'} if key == 'sunny_day' else {'WATER'}
                return (1, 2 * sum(bool(types.intersection(o.piece.types)) for o in player.board))
            return (1, 3 if key == 'guard' and len(player.board) > 1 else 1)
        choice = max(reward['options'], key=score)
        action(session, 'claim_reward', reward_id=reward['id'], choice=choice)
        CONTEXT['row']['claimed_techniques'][choice] += 1
    for technique in techniques.ids_for(session.ruleset):
        for owned in list(player.board):
            if player.inventory.techniques[technique] <= 0:
                break
            if owned.technique is None and techniques.compatible_species(owned.piece.species_id, technique):
                action(session, 'learn', uid=owned.uid, technique=technique)
    positions = session._positions(player)
    guard = None
    for i, owned in enumerate(player.board):
        if owned.technique != 'guard':
            continue
        adjacent = [o for j, o in enumerate(player.board) if i != j and
                    abs(positions[i][0] - positions[j][0]) + abs(positions[i][1] - positions[j][1]) == 1]
        if adjacent:
            target = max(adjacent, key=lambda o: (o.piece.tier, o.piece.species_id))
            guard = {'uid': owned.uid, 'target_uid': target.uid}
            break
    if guard != session.tactical[0]['guard']:
        action(session, 'set_guard', **(guard or {'uid': ''}))
    weather = next(({'uid': o.uid} for o in player.board if o.technique in ('sunny_day', 'rain_dance')), None)
    if weather != session.tactical[0]['weather']:
        action(session, 'set_weather', **(weather or {'uid': ''}))
    if guard:
        CONTEXT['row']['guard_configured_rounds'] += 1
    if weather:
        CONTEXT['row']['weather_configured_rounds'] += 1


def invariant(session):
    held = Counter()
    for seat in session.seats:
        held.update(sid for sid in seat.shop.slots if sid is not None)
        for owned in seat.all_pieces():
            held.update(owned.sources)
        if seat.alive:
            claimed = sum(row['seat'] == seat.seat and row['status'] == 'claimed' for row in session.rewards)
            machines = sum(seat.inventory.techniques.values()) + sum(o.technique is not None for o in seat.all_pieces())
            assert machines == claimed, ('machine conservation', session.round_no, seat.seat, machines, claimed)
    for sid, piece in session.templates.items():
        assert held[sid] + session.pool.remaining[sid] == demo.shop_mod.POOL_COPIES[piece.tier], ('pool', sid)
    assert all(row['status'] != 'pending' for row in session.rewards if not session.seats[row['seat']].alive)
    if session.phase == 'over':
        assert all(row['status'] != 'pending' for row in session.rewards)


def game(seed, personality, ruleset):
    row = {'seed': seed, 'personality': personality, 'status': 'running', 'current_round': 1,
           'battle_count': 0, 'player_battle_count': 0, 'tactical_events': Counter(),
           'player_battle_tactical_events': Counter(), 'actions': Counter(),
           'claimed_techniques': Counter(), 'blocked_actions': [], 'sample_events': [],
           'invalidated_configuration_notices': [], 'guard_configured_rounds': 0,
           'weather_configured_rounds': 0, 'checkpoints': [], 'rounds': []}
    CONTEXT['row'] = row
    session = demo.Session(seed, ruleset=ruleset)
    session.sid = f'{seed:012x}'
    session.run_id = hashlib.sha256(f'tactics-smoke:{seed}'.encode()).hexdigest()[:32]
    # Identical new-account expedition loadout, with the usual paid starter.
    session.expedition = {'partner': 6, 'technique': None, 'item': None}
    session.begin_round(1)
    expedition.deploy_starter(session)
    session.observe()
    demo.SESSIONS[session.sid] = session
    pilot = Bot(0, 2, personality, session.pool, session.templates)
    checkpoint_rounds = random.Random(seed).choice(((6,), (11,), (6, 11)))
    def checkpoint(current, stage):
        before = CODEC.encode(current)
        restored = CODEC.decode(before, 4)
        assert CODEC.encode(restored) == before, ('unstable round-trip', current.round_no)
        restored.sid = current.sid
        demo.SESSIONS[current.sid] = restored
        pilot.pool, pilot.templates = restored.pool, restored.templates
        row['checkpoints'].append({'round': current.round_no, 'stage': stage,
                                   'exact_state_equal': True,
                                   'pending': sum(r['status'] == 'pending' for r in restored.rewards)})
        return restored
    try:
        for _ in range(demo.MAX_ROUNDS):
            if session.phase == 'over':
                break
            row['current_round'] = session.round_no
            before_rewards = (seed + session.round_no) % 2 == 0
            if session.round_no in checkpoint_rounds and before_rewards:
                session = checkpoint(session, 'before_player_rewards')
            if session.player.alive:
                pilot_prep(session, pilot)
            if session.round_no in checkpoint_rounds and not before_rewards:
                session = checkpoint(session, 'after_player_rewards')
            invariant(session)
            action(session, 'end_prep')
            invariant(session)
            row['rounds'].append({'round': session.round_no, 'alive': len(session._alive()),
                                  'player_alive': session.player.alive, 'hp': session.player.hp,
                                  'level': session.player.level, 'gold': session.player.gold,
                                  'pending_rewards': sum(r['status'] == 'pending' for r in session.rewards)})
            if not session.player.alive and 'player_eliminated_round' not in row:
                row['player_eliminated_round'] = session.round_no
            if session.phase != 'over':
                action(session, 'next')
        assert session.phase == 'over', ('never reached terminal', session.round_no, session.phase)
        row.update(status='complete', player_rank=session.player.rank,
                   player_rounds=session.eliminated_round or session.round_no,
                   table_rounds=session.round_no, final_alive=len(session._alive()),
                   natural_terminal=len(session._alive()) == 1,
                   forced_ranking=session.round_no == demo.MAX_ROUNDS and len(session._alive()) > 1,
                   final_pending=sum(r['status'] == 'pending' for r in session.rewards),
                   rewarded_machines=sum(r['status'] == 'claimed' for r in session.rewards),
                   closed_rewards=sum(r['status'] == 'closed' for r in session.rewards))
    except Exception as exc:
        row.update(status='error', error=repr(exc), traceback=traceback.format_exc(),
                   failed_round=session.round_no, failed_phase=session.phase)
        print(f'ERROR seed={seed} personality={personality} round={session.round_no}: {exc}', flush=True)
    finally:
        demo.SESSIONS.pop(session.sid, None)
        CONTEXT['row'] = None
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=32, help='Independent games, 1–4096 (default: 32).')
    parser.add_argument('--seed-base', type=int, default=2026100500,
                        help='First nonnegative signed-64-bit seed; subsequent games use consecutive seeds.')
    parser.add_argument('--ruleset', choices=('tactics_v1', 'tactics_v2', 'tactics_v3', 'tactics_v4'), default='tactics_v4',
                        help='Explicit battle version; defaults to the current tactical mode.')
    parser.add_argument('--output', type=Path, default=ROOT / '.build/tactics/full-run-probe.json',
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
    games = []
    with patch.object(demo, 'SESSIONS', {}), patch.object(demo, 'Battle', ObservedBattle), \
            patch.object(demo, '_render_battle_frames', side_effect=headless):
        for index in range(args.games):
            games.append(game(args.seed_base + index, sorted(PERSONALITIES)[index % 4], args.ruleset))
            if index % 4 == 3:
                print(f'Completed {index + 1}/{args.games}', flush=True)
    completed = [row for row in games if row['status'] == 'complete']
    events = Counter()
    player_events = Counter()
    claims = Counter()
    for row in games:
        events.update(row['tactical_events'])
        player_events.update(row['player_battle_tactical_events'])
        claims.update(row['claimed_techniques'])
    summary = {'games': len(games), 'independent_seeds': len({row['seed'] for row in games}),
               'complete': len(completed), 'errors': len(games) - len(completed),
               'personalities': dict(Counter(row['personality'] for row in games)),
               'battles': sum(row['battle_count'] for row in games),
               'player_battles': sum(row['player_battle_count'] for row in games),
               'tactical_events': dict(events), 'player_battle_tactical_events': dict(player_events),
               'player_claimed_techniques': dict(claims),
               'roundtrip_checkpoints': sum(len(row['checkpoints']) for row in games),
               'checkpoint_rounds': dict(Counter(c['round'] for row in games for c in row['checkpoints'])),
               'checkpoint_stages': dict(Counter(c['stage'] for row in games for c in row['checkpoints'])),
               'restored_pending_rewards': sum(c['pending'] for row in games for c in row['checkpoints']),
               'blocked_actions': sum(len(row['blocked_actions']) for row in games),
               'invalidated_configurations': sum(len(row['invalidated_configuration_notices']) for row in games),
               'natural_terminal': sum(row['natural_terminal'] for row in completed),
               'forced_ranking': sum(row['forced_ranking'] for row in completed),
               'final_pending': sum(row['final_pending'] for row in completed),
               'table_rounds_mean': statistics.mean(row['table_rounds'] for row in completed) if completed else None,
               'player_rank_counts': dict(Counter(row['player_rank'] for row in completed))}
    payload = {'method': __doc__, 'ruleset': args.ruleset, 'rules_fingerprint': rules_fingerprint(),
               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'seed_base': args.seed_base, 'summary': summary, 'games': games,
               'limits': ['L2 pilot is not a human player.', 'Sample validates whole-run workflow, not balance.',
                          'No PNG, disk save or profile IO; checkpointing exercises the real schema-4 codec.',
                          'Invalid configurations are deliberately closed and legally reselected, never silently retargeted by the game.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f'Written: {args.output}', flush=True)
    return 0 if not summary['errors'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
