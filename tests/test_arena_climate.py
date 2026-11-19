"""arena_v2 stage weather: forecast, battle effects, teaching-machine override, swap, save, view."""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / 'sim', ROOT / 'tools' / 'acceptance', ROOT / 'tools' / 'mockups'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import arena  # noqa: E402
import arena_climate as climate  # noqa: E402
import arena_families as families  # noqa: E402
import arena_session  # noqa: E402
import arena_weather  # noqa: E402
import combat  # noqa: E402


def piece(fid, star=2):
    return families.make_piece(fid, star, families.FAMILIES[fid][1][0][-1])


TEAM_A = lambda: [piece(1), piece(4), piece(7), piece(74), piece(92), piece(10)]  # noqa: E731
TEAM_B = lambda: [piece(66), piece(29), piece(43), piece(123), piece(58), piece(120)]  # noqa: E731


def fight(schedule, seed=3, ruleset='arena_v2', a=None, b=None, until=None):
    a, b = a or TEAM_A(), b or TEAM_B()
    battle = combat.Battle(a, b, random.Random(seed), layout='back', ruleset=ruleset, stat_mode='budget_v1',
                           arena_teams=[[], []], arena_climate=schedule,
                           positions_a=[(c, 3) for c in range(len(a))],
                           positions_b=[(c, 2) for c in range(len(b))])
    battle.run(until=until)
    return battle


class ForecastTest(unittest.TestCase):
    def test_forecast_is_deterministic_calm_first_and_varied(self):
        rows = [climate.forecast(77, n) for n in range(1, 32)]
        self.assertEqual(rows, [climate.forecast(77, n) for n in range(1, 32)])
        self.assertEqual({r['id'] for r in rows[:climate.CALM_ROUNDS]}, {'calm'})
        later = [r['id'] for r in rows[climate.CALM_ROUNDS:]]
        self.assertGreaterEqual(len(set(later)), 7)
        for i in range(len(later) - 1):
            stage_i = (i + climate.CALM_ROUNDS) // len(climate.ROTATION)
            stage_j = (i + 1 + climate.CALM_ROUNDS) // len(climate.ROTATION)
            if stage_i == stage_j:
                self.assertNotEqual(later[i], later[i + 1])
        for n, row in enumerate(rows, 1):
            self.assertNotEqual(row['alt'], row['id']) if n > climate.CALM_ROUNDS else None
            if row['shift']:
                self.assertGreaterEqual(n, 6)
                self.assertNotIn(row['shift']['id'], (row['id'], row['alt']))
        self.assertTrue(any(r['shift'] for r in rows))

    def test_arena_v1_rejects_climate(self):
        with self.assertRaises(ValueError):
            fight((('sun', 0.),), ruleset='arena_v1')


class BattleTest(unittest.TestCase):
    def test_every_weather_does_something_visible(self):
        expect = {'sun': '光合', 'rain': '雨润', 'storm': '落雷', 'gale': '顺风', 'aurora': '星辉'}
        for key in climate.ROTATION:
            with self.subTest(weather=key):
                labels, ledger = set(), 0
                for seed in range(4):
                    battle = fight(((key, 0.),), seed=seed)
                    self.assertEqual(battle.weather_track[0], [0.0, key])
                    labels |= {e[5]['label'] for e in battle.events if e[1] == 'effect'
                               and e[5].get('source') == 'weather'}
                    ledger += sum(r['triggers'] + r['estimated'] + r['prevented'] + r['damage']
                                  for team in (0, 1) for r in battle.fx.ledger.view(team)
                                  if r['source'] == 'weather')
                if key in expect:
                    self.assertIn(expect[key], labels)
                self.assertGreater(ledger, 0)

    def test_fog_shortens_long_range_and_snow_freezes(self):
        battle = fight((('fog', 0.),), until=.2)
        shortened = [u for u in battle.units if battle._climate_base[u.idx][0] >= 3]
        self.assertTrue(shortened)
        for unit in shortened:
            self.assertEqual(unit.range, battle._climate_base[unit.idx][0] - 1)
        frozen = 0
        for seed in range(4):
            battle = fight((('snow', 0.),), a=[piece(215), piece(90), piece(4)], seed=seed)
            frozen += sum(1 for e in battle.events if e[1] == 'effect' and e[5].get('label') == '冻结')
        self.assertGreater(frozen, 0)

    def test_mid_battle_shift_and_teaching_override_revert(self):
        battle = fight((('sun', 0.), ('storm', 15.)), seed=1)
        if battle.duration > 15.:
            self.assertEqual([row[1] for row in battle.weather_track[:2]], ['sun', 'storm'])
        battle = fight((('sand', 0.),), until=.1)
        battle.arena_weather_name, battle.arena_weather_started_at, battle.arena_weather_until = 'rain', 0., 5.
        self.assertEqual(arena_weather.active(battle, 3.), 'rain')
        self.assertEqual(arena_weather.active(battle, 6.), 'sand')
        self.assertEqual(arena_weather.damage_multiplier(battle, {'type': 'FIRE'}, 6.), 1.)

    def test_deterministic(self):
        run = lambda: repr(fight((('storm', 0.), ('gale', 15.)), seed=5).events)  # noqa: E731
        self.assertEqual(run(), run())


class SessionTest(unittest.TestCase):
    def setUp(self):
        import demo
        self.demo = demo
        self.s = demo._new_session(515, {'mode': 'arena'})
        for reward in list(self.s.arena_augments_pending):
            arena.claim_augment(self.s, reward['id'], reward['options'][0]['id'])

    def test_view_swap_battle_options_and_save(self):
        s, p = self.s, self.s.player
        view = self.demo.state_json(s, lite=True)['depth']['climate']
        self.assertEqual(len(view['forecast']), 3)
        self.assertEqual(view['forecast'][0]['round'], s.round_no)
        while s.round_no < 3:
            if s.phase == 'battle':
                s.next_round()
            s.arena_augments_pending = []
            s.end_prep()
        if s.phase == 'battle':
            s.next_round()
        row = climate.forecast(s.seed, s.round_no)
        opts = arena.battle_options(s, p, s.bots[0])
        self.assertEqual(opts['arena_climate'][0][0], row['id'])
        gold = p.gold
        self.demo.act_climate_swap(s)
        self.assertEqual(p.gold, gold - climate.SWAP_COST)
        with self.assertRaises(self.demo.DemoError):
            self.demo.act_climate_swap(s)
        self.assertEqual(arena.battle_options(s, p, s.bots[0])['arena_climate'], ((row['alt'], 0.),))
        self.assertEqual(arena.battle_options(s, s.bots[1], s.bots[2])['arena_climate'][0][0], row['id'])
        view = self.demo.state_json(s, lite=True)['depth']['climate']
        self.assertTrue(view['swap']['used'])
        self.assertEqual(view['forecast'][0]['id'], row['alt'])
        from session_save import SessionCodec
        codec = SessionCodec()
        restored = codec.decode(codec.encode(s), codec.schema_version)
        self.assertEqual(arena_session.seat_state(restored.player)['climate_swap'], s.round_no)


if __name__ == '__main__':
    unittest.main()
