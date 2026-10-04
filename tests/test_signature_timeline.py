"""Real skill effects retain cast ownership through presentation and seeking."""
import copy
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sim'))
sys.path.insert(0, str(ROOT / 'tools' / 'mockups'))
import profiles
import status
import render_battle_gif as renderer
from combat import Battle
from data import ENERGY_MAX
from roster import build_roster

ROSTER = {p.species_id: p for pieces in build_roster().values() for p in pieces}


class SignatureTimelineContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = renderer.Front(), renderer.Palettes(), renderer.Font16()

    def setUp(self):
        for module, setting in ((profiles, 'PROFILES_ON'), (status, 'STATUS_ON')):
            flag = patch.object(module, setting, True)
            flag.start()
            self.addCleanup(flag.stop)

    def fixture(self, allies, enemies, positions):
        battle = Battle([ROSTER[sid] for sid in allies], [ROSTER[sid] for sid in enemies],
                        random.Random(7413))
        for unit, pos in zip(battle.units, positions):
            unit.pos = pos
            unit.hp = unit.max_hp = 1000
            unit.energy = 0
        # Deployment and initial resources are fixture inputs. All effects below
        # come from the actual combat resolver, not hand-authored replay tuples.
        battle.events = [(0., 'deploy', unit.idx, unit.pos) for unit in battle.units]
        return battle

    def record_initial_state(self, battle):
        for unit in battle.units:
            battle._emit_state(unit, 0.)

    def strike(self, battle, attacker, target, t=.1):
        move = battle.dex.moves[attacker.piece.move_id]
        with patch.dict(move, accuracy=100), patch.object(battle.rng, 'uniform', return_value=1.), \
                patch.object(status, 'on_hit'):
            battle._strike(attacker, target, t)

    def animate(self, battle):
        return renderer.BattleAnimation([], [], 7413, *self.assets, battle=battle)

    def assert_state_order(self, battle, animation):
        for unit in battle.units:
            self.assertEqual(
                [e[2:] for e in battle.events if e[1] == 'unit_state' and e[2] == unit.idx],
                [e[2:] for e in animation.timeline.events
                 if e[1] == 'unit_state' and e[2] == unit.idx])

    def test_solar_third_party_healing_waits_for_impact_and_survives_rewind(self):
        battle = self.fixture((3, 143), (143,), ((1, 2), (1, 3), (1, 1)))
        caster, patient, target = battle.units
        caster.energy = ENERGY_MAX
        patient.hp = 30
        self.record_initial_state(battle)
        self.strike(battle, caster, target)
        original = copy.deepcopy(battle.events)
        animation = self.animate(battle)
        action = next(a for a in animation.timeline.actions if a.kind == 'cast')
        self.assertGreater(patient.hp, 30)
        self.assertEqual(animation.presentation_state(action.impact - .001)[patient.idx]['hp'], 30)
        self.assertEqual(animation.presentation_state(action.impact)[patient.idx]['hp'], patient.hp)
        heals = [e for e in animation.timeline.events if e[1] == 'regen']
        self.assertEqual([e[0] for e in heals], [action.impact])
        animation.presentation_state(animation.presentation_duration)
        self.assertEqual(animation.presentation_state(action.impact - .001)[patient.idx]['hp'], 30)
        self.assertEqual(animation.presentation_state(action.impact)[patient.idx]['hp'], patient.hp)
        self.assertEqual(battle.events, original)
        self.assert_state_order(battle, animation)

    def test_healing_fences_the_patients_previous_independent_action(self):
        battle = self.fixture((3, 6), (143, 143), ((1, 2), (0, 3), (1, 1), (5, 0)))
        caster, patient, target, far_target = battle.units
        caster.energy = ENERGY_MAX
        patient.hp = 30
        patient.range = 20  # Expose a long in-flight preceding action.
        self.record_initial_state(battle)
        self.strike(battle, patient, far_target)
        self.strike(battle, caster, target)
        animation = self.animate(battle)
        previous, cast = animation.timeline.actions[:2]
        self.assertGreater(previous.impact, 1.)
        self.assertGreaterEqual(cast.impact, previous.impact)
        self.assertEqual(animation.presentation_state(cast.impact - .001)[patient.idx]['hp'], 30)
        self.assertEqual(animation.presentation_state(cast.impact)[patient.idx]['hp'], patient.hp)
        self.assert_state_order(battle, animation)

    def test_knockback_starts_on_hit_while_victim_is_still_recovering(self):
        battle = self.fixture((9, 143), (143,), ((1, 2), (2, 1), (1, 1)))
        caster, friend, victim = battle.units
        caster.energy = ENERGY_MAX
        self.record_initial_state(battle)
        self.strike(battle, victim, friend)
        self.strike(battle, caster, victim)
        animation = self.animate(battle)
        previous = next(a for a in animation.timeline.actions if a.attacker == victim.idx)
        cast = next(a for a in animation.timeline.actions if a.kind == 'cast')
        movement = next(e for e in animation.timeline.events if e[1] == 'move')
        self.assertLess(cast.impact, previous.recover_end)
        self.assertEqual(movement[0], cast.impact)
        view = animation._presentation_view()
        view._ensure(cast.impact - .001)
        before = view.units[victim.idx].render_px(cast.impact - .001)
        self.assertEqual(before, view.units[victim.idx].cell_px((1, 1)))
        view._ensure(cast.impact)
        self.assertEqual(view.units[victim.idx].hp, victim.hp)
        self.assertEqual(view.units[victim.idx].move_t0, cast.impact)
        self.assertEqual(view.units[victim.idx].render_px(cast.impact), before)
        view._ensure(cast.impact + .05)
        self.assertNotEqual(view.units[victim.idx].render_px(cast.impact + .05), before)
        view._ensure(animation.presentation_duration)
        self.assertEqual(view.units[victim.idx].render_px(animation.presentation_duration),
                         view.units[victim.idx].cell_px(victim.pos))
        view._ensure(cast.impact - .001)
        self.assertEqual(view.units[victim.idx].render_px(cast.impact - .001), before)
        self.assert_state_order(battle, animation)

    def test_drain_updates_both_energy_bars_only_at_the_owned_cast_impact(self):
        battle = self.fixture((94,), (3,), ((2, 2), (2, 1)))
        caster, target = battle.units
        caster.energy, target.energy = ENERGY_MAX, 53
        self.record_initial_state(battle)
        self.strike(battle, caster, target)
        animation = self.animate(battle)
        cast = next(a for a in animation.timeline.actions if a.kind == 'cast')
        before = animation.presentation_state(cast.impact - .001)
        self.assertEqual((before[caster.idx]['energy'], before[target.idx]['energy']), (ENERGY_MAX, 53))
        landed = animation.presentation_state(cast.impact)
        self.assertEqual((landed[caster.idx]['energy'], landed[target.idx]['energy']),
                         (caster.energy, target.energy))
        self.assertGreater(caster.energy, 0)
        self.assertLess(target.energy, 53)
        self.assert_state_order(battle, animation)

    def test_quake_side_hit_and_control_share_the_main_cast_impact(self):
        battle = self.fixture((76,), (143, 143), ((2, 2), (2, 1), (3, 2)))
        caster, target, side = battle.units
        caster.energy = ENERGY_MAX
        self.record_initial_state(battle)
        self.strike(battle, caster, target)
        animation = self.animate(battle)
        cast = next(a for a in animation.timeline.actions if a.kind == 'cast')
        statuses = [e for e in animation.timeline.events if e[1] == 'status']
        self.assertEqual({e[2] for e in statuses}, {target.idx, side.idx})
        self.assertTrue(all(e[0] == cast.impact for e in statuses))
        self.assertEqual(animation.presentation_state(cast.impact - .001)[side.idx]['hp'], 1000)
        self.assertNotIn('flinch', animation._presentation_view().units[side.idx].statuses)
        self.assertEqual(animation.presentation_state(cast.impact)[side.idx]['hp'], side.hp)
        self.assertEqual(animation._presentation_view().units[side.idx].statuses['flinch'], cast.impact)
        self.assert_state_order(battle, animation)

    def test_chain_side_hits_bind_to_cast_but_same_tick_new_attack_does_not(self):
        battle = self.fixture((26,), (143, 143, 143), ((2, 2), (2, 1), (3, 1), (4, 1)))
        caster, target, first, second = battle.units
        caster.energy = ENERGY_MAX
        self.record_initial_state(battle)
        self.strike(battle, caster, target)
        independent_index = len(battle.events)
        self.strike(battle, caster, target)  # Ordinary attack; same caster and raw t.
        animation = self.animate(battle)
        cast = next(a for a in animation.timeline.actions if a.kind == 'cast')
        independent = next(a for a in animation.timeline.actions if a.source_index == independent_index)
        sides = [a for a in animation.timeline.actions if a.secondary]
        self.assertEqual({a.target for a in sides}, {first.idx, second.idx})
        self.assertTrue(all(a.impact == cast.impact for a in sides))
        self.assertFalse(independent.secondary)
        self.assertGreaterEqual(independent.start, cast.recover_end)
        self.assertGreater(independent.impact, cast.impact)
        self.assertEqual(animation.presentation_state(cast.impact - .001)[second.idx]['hp'], 1000)
        self.assertEqual(animation.presentation_state(cast.impact)[second.idx]['hp'], second.hp)
        self.assert_state_order(battle, animation)


if __name__ == '__main__':
    unittest.main()
