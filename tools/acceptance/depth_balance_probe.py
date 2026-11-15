#!/usr/bin/env python3
"""arena_v2 balance probe: bot-only full games, placement by augment / breakpoint / order.

    python3 tools/acceptance/depth_balance_probe.py --seeds 1-24 --workers 4 --output probe.json

Each seed plays a whole arena_v2 game with the human seat empty. For every bot
we record its final placement (1 = champion) and what it used: augments, depth
breakpoints active on its final board, its tactical order, peak star counts.
The report lists average placement (lower is better) and top-4 rate per item,
so outliers stand out. Small samples are noisy; read directions, not decimals.
"""
import argparse
import json
import statistics
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for _path in (ROOT / 'sim', ROOT / 'tools' / 'acceptance', ROOT / 'tools' / 'mockups'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def play(seed):
    import arena_bonds
    import arena_depth
    import arena_session
    import demo
    s = demo._new_session(seed, {'mode': 'arena'})
    snapshots = {}

    def snapshot():
        for bot in s.bots:
            if bot.alive and bot.board:
                counts = arena_bonds.count([o.piece for o in bot.board])
                rules = sorted(rule[1] for element, rule in arena_depth.BOND_RULES.items()
                               if counts.get(element, 0) >= rule[0])
                snapshots[bot.seat] = {
                    'rules': rules, 'order': arena_session.order_of(s, bot),
                    'stars': [o.piece.star for o in bot.board],
                    'costs': [o.piece.tier for o in bot.board], 'level': bot.level,
                    'round': s.round_no}

    while s.phase != 'over':
        if s.phase == 'battle':
            s.next_round()
        s.arena_augments_pending = []
        for row in s.arena_component_choices:
            if row['status'] == 'pending' and row['seat'] == 0:
                row.update(status='closed', closed_reason='probe_skip')
        snapshot()
        s.end_prep()
    rows = []
    for bot in s.bots:
        snap = snapshots.get(bot.seat, {})
        rows.append({'seed': seed, 'seat': bot.seat, 'rank': bot.rank,
                     'augments': arena_session.augment_keys(bot),
                     'quests_done': list(arena_session.seat_state(bot)['quests_done']), **snap})
    return {'seed': seed, 'rounds': s.round_no, 'bots': rows}


def summarize(games):
    by = defaultdict(lambda: defaultdict(list))
    for game in games:
        for row in game['bots']:
            if row['rank'] is None:
                continue
            for key in row.get('augments', []):
                by['augment'][key].append(row['rank'])
            for key in row.get('rules', []):
                by['breakpoint'][key].append(row['rank'])
            by['order'][row.get('order', 'none')].append(row['rank'])
            for key in row.get('quests_done', []):
                by['quest_done'][key].append(row['rank'])
    report = {}
    for group, table in by.items():
        report[group] = sorted(({'id': key, 'n': len(ranks), 'avg_rank': round(statistics.mean(ranks), 2),
                                 'top4': round(sum(r <= 4 for r in ranks) / len(ranks), 2)}
                                for key, ranks in table.items()), key=lambda row: row['avg_rank'])
    champions = [min((r for r in g['bots'] if r['rank']), key=lambda r: r['rank']) for g in games]
    report['games'] = {
        'n': len(games), 'rounds': statistics.mean(g['rounds'] for g in games),
        'champion_avg_cost': round(statistics.mean(statistics.mean(c['costs']) for c in champions
                                                  if c.get('costs')), 2),
        'champion_avg_star': round(statistics.mean(statistics.mean(c['stars']) for c in champions
                                                  if c.get('stars')), 2),
        'three_star_units_on_final_boards': sum(r.get('stars', []).count(3) for g in games for r in g['bots'])}
    return report


def parse_seeds(text):
    seeds = []
    for part in text.split(','):
        if '-' in part:
            lo, hi = part.split('-')
            seeds.extend(range(int(lo), int(hi) + 1))
        elif part:
            seeds.append(int(part))
    return seeds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', default='1-12')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--output')
    args = parser.parse_args(argv)
    with Pool(args.workers) as pool:
        games = pool.map(play, parse_seeds(args.seeds))
    report = summarize(games)
    if args.output:
        Path(args.output).write_text(json.dumps({'report': report, 'games': games},
                                                ensure_ascii=False, indent=1))
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
