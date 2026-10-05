"""Healing denial follows actual hits/heals; playback cannot invent HP."""
import copy
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/mockups')]
from combat import Battle
from experiment_build_diversity import BUILDS, PIECES, rotate
import render_battle_gif as renderer


def natural_battle(seed=202610055000):
    source = next(b for b in BUILDS if b.key == 'disrupt')
    target = next(b for b in BUILDS if b.key == 'garden')
    a = [(PIECES[s], 'healing_needle' if i == 2 else item) if item or i == 2 else PIECES[s]
         for i, (s, item) in enumerate(zip(source.species, source.items))]
    b = [(PIECES[s], item) if item else PIECES[s] for s, item in zip(target.species, target.items)]
    battle = Battle(a, b, random.Random(seed), stat_mode='budget_v1', ruleset='tactics_v4',
                    positions_a=list(source.positions), positions_b=rotate(target.positions),
                    learned_a=list(source.learned), learned_b=list(target.learned),
                    team_options=({'partner': source.partner}, {'partner': target.partner}))
    battle.run()
    return battle


def directed_battle():
    battle = Battle([(PIECES[6], 'healing_needle')], [PIECES[143]], random.Random(741),
                    positions_a=[(2, 2)], positions_b=[(2, 1)], ruleset='tactics_v4')
    for unit in battle.units:
        unit.max_hp = unit.hp = 10000
        battle._emit_state(unit, 0.)
    attacker, target = battle.units
    attacker.energy = 80
    with patch.object(battle.rng, 'randrange', return_value=0):
        battle._strike(attacker, target, 1.)
    battle._heal(target, 100, 2.)
    battle._heal(target, 100, 9.)
    target.hp = 0
    battle._death_check(target, 10.)
    battle.events.append((11., 'end', None))
    return battle


class CounterPresentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = renderer.Front(), renderer.Palettes(), renderer.Font16()

    def animation(self, battle):
        return renderer.BattleAnimation([], [], 741, *self.assets, battle=battle)

    def test_hit_badge_heal_payload_hp_and_exclusive_expiry(self):
        battle = directed_battle(); original = copy.deepcopy(battle.events)
        anim = self.animation(battle); view = anim._presentation_view()
        event = next(e for e in view.events if e[1] == 'tactical_effect' and e[4] == 'healing_block')
        cast = next(a for a in anim.timeline.actions if a.kind == 'cast')
        self.assertEqual(event[0], cast.impact)
        view._ensure(event[0]-.001)
        self.assertFalse(view._active_healing_blocks(event[0]-.001))
        view._ensure(event[0])
        row, = view._active_healing_blocks(event[0])
        self.assertAlmostEqual(row['expires_at']-row['started'], 8.)
        badge = renderer.Image.new('RGBA', (240, 320))
        view._draw_healing_block_badge(badge, event[0], renderer.ParticleBudget())
        self.assertIsNotNone(badge.getbbox())
        prevented = next(e for e in view.events if e[1] == 'tactical_effect' and e[4] == 'healing_prevented')
        view._ensure(prevented[0])
        self.assertTrue(any(f[3] == f"X{prevented[5]['amount']}" for f in view.floats))
        self.assertIn(f"回复+{prevented[5]['healed']}", view.msg[1])
        view._ensure(row['expires_at']-.001)
        self.assertTrue(view._active_healing_blocks(row['expires_at']-.001))
        view._ensure(row['expires_at'])
        self.assertFalse(view._active_healing_blocks(row['expires_at']))
        for idx in view.units:
            self.assertEqual([e[2:] for e in battle.events if e[1] == 'unit_state' and e[2] == idx],
                             [e[2:] for e in view.events if e[1] == 'unit_state' and e[2] == idx])
        self.assertEqual(original, battle.events)

    def test_natural_energy_mixed_team_rewind_speed_and_no_future_badge(self):
        battle = natural_battle(); original = copy.deepcopy(battle.events)
        anim = self.animation(battle); view = anim._presentation_view()
        initial = [e for e in battle.events if e[1] == 'unit_state' and e[0] == 0]
        self.assertTrue(initial)
        # Item/synergy opening energy remains production behavior; no unit was
        # manually precharged, especially the needle caster who sacrificed lens.
        self.assertEqual(next(e[4] for e in initial if e[2] == 2), 0)
        self.assertTrue(all(e[4] < 80 for e in initial))
        block = next(e for e in view.events if e[1] == 'tactical_effect' and e[4] == 'healing_block')
        self.assertGreater(block[5]['simulation_time'], 0.)
        self.assertTrue(any(e[1] == 'tactical_effect' and e[4] == 'healing_prevented' for e in battle.events))
        raw_results = [i for i, e in enumerate(battle.events)
                       if e[1] == 'tactical_effect' and e[4] == 'healing_prevented']
        shown = [e for e in view.events if e[1] == 'tactical_effect' and e[4] == 'healing_prevented']
        for index, event in zip(raw_results, shown):
            regen = battle.events[index+1]
            self.assertEqual(regen[1], 'regen')
            # Mapping by source index is explicit even when a later cast shares
            # the same tick or the original needle source has died.
            self.assertEqual(anim.timeline.source_times[index][1], event[0])
            self.assertEqual(anim.timeline.source_times[index+1][1], event[0])
        moment = block[0]+.1
        pixels = anim.playback_frame(moment).tobytes()
        anim.playback_frame(0., skip=True)
        self.assertEqual(pixels, anim.playback_frame(moment).tobytes())
        self.assertEqual(pixels, anim.playback_frame(moment/2, speed=2).tobytes())
        view._ensure(block[0]-.001)
        self.assertFalse(view._active_healing_blocks(block[0]-.001))
        # The renderer never substitutes final simulation HP into its current view.
        for event in view.events:
            if event[1] == 'unit_state':
                view._ensure(event[0])
                latest = {e[2]: e for e in view.events if e[1] == 'unit_state' and e[0] <= event[0]}
                for idx, state in latest.items():
                    self.assertEqual(view.units[idx].hp, state[3])
        self.assertEqual(original, battle.events)

    def test_independent_deadlines_hide_dead_target_and_respect_budget(self):
        anim = self.animation(directed_battle()); view = anim._presentation_view(); view._ensure(0.)
        view.healing_blocks = [dict(source=0, target=1, started=0., expires_at=3., fraction=.6),
                               dict(source=0, target=1, started=1., expires_at=7., fraction=.6)]
        self.assertEqual(view._active_healing_blocks(2.)[0]['expires_at'], 3.)
        self.assertEqual(view._active_healing_blocks(3.)[0]['expires_at'], 7.)
        blank = renderer.Image.new('RGBA', (240, 320)); budget = renderer.ParticleBudget(limit=1)
        view._draw_healing_block_badge(blank, 2., budget)
        self.assertIsNone(blank.getbbox()); self.assertLessEqual(budget.used, 1)
        view.units[1].die_t = 2.
        self.assertFalse(view._active_healing_blocks(2.))
        for ch in set('封锁回复少秒命中'):
            self.assertIsNotNone(self.assets[2].text(ch).getbbox(), ch)
        percent = renderer.Image.new('RGBA', (16, 16))
        renderer.draw_text(percent, (0, 0), '%', self.assets[2])
        self.assertIsNotNone(percent.getbbox())


if __name__ == '__main__':
    unittest.main()
