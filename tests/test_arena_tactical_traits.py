"""Eevee branch and Darkness tactical identities use settled battle facts."""
import copy
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim')]
import arena
import arena_combinations as combinations
import arena_families as families
import arena_skills
import arena_traits as traits
import status
from combat import Battle
from data import ENERGY_MAX


class TacticalEeveeAndDarknessTraits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = {**arena.build_templates()}
        for branch in (134, 135, 136):
            cls.templates[branch] = families.make_piece(133, 2, branch)

    def battle(self, friends=(134,), enemies=(128,)):
        own = [(copy.copy(self.templates[sid]) if sid in self.templates
                else families.make_piece(133, 2, sid)) for sid in friends]
        hostile = [copy.copy(self.templates[sid]) for sid in enemies]
        b = Battle(own, hostile, random.Random(718), ruleset='arena_v1',
                   stat_mode='budget_v1', arena_teams=[[], []],
                   positions_a=[(2, 3), (1, 3), (3, 3), (2, 4)][:len(friends)],
                   positions_b=[(2, 2), (3, 2), (1, 2)][:len(enemies)])
        for unit in b.units:
            unit.max_hp = unit.hp = 1000
            unit.energy = 0
        return b

    @staticmethod
    def effects(b, key, effect=None):
        return [event for event in b.events if event[1] == 'combo_effect'
                and event[4] == key and (effect is None or event[5] == effect)]

    def cast(self, b, source, t, raw=50):
        b.duration, source.energy = t, ENERGY_MAX
        target = next(unit for unit in b.units
                      if unit.team != source.team and unit.alive)
        with patch.object(status, 'on_hit'), \
                patch.object(b, '_move_damage', return_value=raw):
            return arena_skills.cast(b, source, target, t)

    def hit(self, b, source, target, damage, t, move_type='NORMAL'):
        b.duration = t
        move = {'name': 'test', 'type': move_type, 'power': 40}
        with patch.object(status, 'on_hit'):
            return b._land_hit(source, target, damage, t, move=move, direct=True)

    def test_branch_specs_explain_playstyles_without_expanding_legacy_catalog(self):
        expected = {
            134: ('trait_tidal_renewal', '潮汐续疗'),
            135: ('trait_charge_relay', '雷霆接力'),
            136: ('trait_ignite_pursuit', '引火追猎'),
            196: ('trait_weakness_read', '破绽洞悉'),
            197: ('trait_moonlight', '月光庇护'),
            198: ('trait_night_feed', '趁隙掠能'),
        }
        for sid, (key, name) in expected.items():
            with self.subTest(sid=sid):
                row = traits.for_species(sid)
                self.assertEqual((row['id'], row['name']), (key, name))
                self.assertEqual(row['source_label'], '竞技战术设计')
                self.assertTrue(row['playstyle'])
                self.assertIsInstance(row['synergy'], list)
                self.assertTrue(row['synergy'])
                self.assertTrue(row['counterplay'])
                if sid in (136, 196):
                    self.assertEqual(row['limit_scope'], '铺垫')
        legacy_sids = {row['sid'] for row in traits.catalog()}
        self.assertFalse({134, 135, 136} & legacy_sids)
        family_sids = {row['sid'] for row in traits.catalog(include_families=True)}
        self.assertTrue(set(expected) <= family_sids)

    def test_tidal_renewal_heals_low_other_ally_with_cooldown_and_limit(self):
        b = self.battle((134, 127), (128,))
        source, ally, enemy = b.units
        ally.hp = 400
        self.assertTrue(self.cast(b, source, 1))
        self.assertEqual(ally.hp, 480)
        self.assertEqual(source.combo_uses['trait_tidal_renewal'], 1)
        self.assertEqual(self.effects(b, 'trait_tidal_renewal', 'heal')[0][6]['amount'], 80)
        ally.hp = 400
        self.assertTrue(self.cast(b, source, 5))  # cooldown ends at 6
        self.assertEqual((ally.hp, source.combo_uses['trait_tidal_renewal']), (400, 1))
        for t in (6, 11):
            source.temp_dr_until = 0
            ally.hp = 400
            self.assertTrue(self.cast(b, source, t))
        self.assertEqual(source.combo_uses['trait_tidal_renewal'], 3)
        ally.hp = 400
        self.assertTrue(self.cast(b, source, 16))
        self.assertEqual(ally.hp, 400)  # limit reached
        ally.hp = 1000
        self.assertTrue(self.cast(b, source, 21))
        self.assertEqual(len(self.effects(b, 'trait_tidal_renewal', 'heal')), 3)

    def test_charge_relay_energizes_another_ally_with_cooldown_and_limit(self):
        b = self.battle((135, 127), (128,))
        source, ally, enemy = b.units
        ally.energy = 70
        self.assertTrue(self.cast(b, source, 1))
        self.assertEqual(ally.energy, ENERGY_MAX)
        self.assertEqual(source.combo_uses['trait_charge_relay'], 1)
        self.assertEqual(self.effects(b, 'trait_charge_relay', 'energy')[0][6]['amount'], 10)
        ally.energy = 70
        self.assertTrue(self.cast(b, source, 5))
        self.assertEqual((ally.energy, source.combo_uses['trait_charge_relay']), (70, 1))
        for t in (6, 11):
            ally.energy = 70
            self.assertTrue(self.cast(b, source, t))
            self.assertEqual(ally.energy, ENERGY_MAX)
        self.assertEqual(source.combo_uses['trait_charge_relay'], 3)
        ally.energy = ENERGY_MAX
        self.assertTrue(self.cast(b, source, 16))
        self.assertEqual(len(self.effects(b, 'trait_charge_relay', 'energy')), 3)

    def test_ignite_pursuit_sets_burn_and_rewards_condition_without_double_spending(self):
        b = self.battle((136,), (128,))
        source, enemy = b.units
        self.assertTrue(self.cast(b, source, 1))
        self.assertEqual(enemy._st.debuff, 'burn')
        self.assertEqual(source.combo_uses['trait_ignite_pursuit'], 1)
        self.assertEqual(self.effects(b, 'trait_ignite_pursuit', 'status')[0][6]['applied'], True)
        enemy.hp = 1000
        self.assertEqual(self.hit(b, source, enemy, 100, 1.1, 'FIRE'), 125)
        self.assertEqual(source.combo_uses['trait_ignite_pursuit'], 1)
        self.assertEqual(self.effects(b, 'trait_ignite_pursuit', 'empowered_hit')[0][6]['extra_damage'], 25)

        status.cleanse(b, enemy, 7)
        self.assertTrue(self.cast(b, source, 7))
        self.assertEqual(source.combo_uses['trait_ignite_pursuit'], 2)
        status.cleanse(b, enemy, 13)
        self.assertTrue(self.cast(b, source, 13))
        self.assertEqual(source.combo_uses['trait_ignite_pursuit'], 2)

        immune = self.battle((136,), (6,))
        source, enemy = immune.units
        self.assertTrue(self.cast(immune, source, 1))
        self.assertIsNone(enemy._st.debuff)
        self.assertEqual(source.combo_uses.get('trait_ignite_pursuit', 0), 0)
        self.assertFalse(self.effects(immune, 'trait_ignite_pursuit', 'status'))

    def test_weakness_read_sets_vulnerability_then_adds_actual_condition_damage(self):
        b = self.battle((196,), (128,))
        source, enemy = b.units
        self.assertTrue(self.cast(b, source, 1))
        self.assertGreater(enemy.vulnerable_until, 1)
        self.assertEqual(source.combo_uses['trait_weakness_read'], 1)
        enemy.hp = 1000
        self.assertEqual(self.hit(b, source, enemy, 100, 1.1), 114)
        self.assertEqual(source.combo_uses['trait_weakness_read'], 1)
        self.assertEqual(self.effects(b, 'trait_weakness_read', 'empowered_hit')[0][6]['extra_damage'], 14)
        enemy.vulnerable_until = 0
        enemy.hp = 1000
        self.assertEqual(self.hit(b, source, enemy, 100, 5.1), 100)
        self.assertTrue(self.cast(b, source, 6))
        self.assertEqual(source.combo_uses['trait_weakness_read'], 2)
        enemy.vulnerable_until = 0
        self.assertTrue(self.cast(b, source, 11))
        self.assertEqual(source.combo_uses['trait_weakness_read'], 2)

    def test_moonlight_shields_low_other_ally_with_cooldown_and_limit(self):
        b = self.battle((197, 127), (128,))
        source, ally, enemy = b.units
        ally.hp = 500
        self.assertTrue(self.cast(b, source, 1))
        self.assertEqual((ally.shield, ally.shield_until), (100, 4))
        self.assertEqual(source.combo_uses['trait_moonlight'], 1)
        row = self.effects(b, 'trait_moonlight', 'shield')[0]
        self.assertEqual((row[3], row[6]['amount'], row[6]['source_kind']), (ally.idx, 100, 'trait'))

        combinations.grant_shield(b, source, ally, 200, 5, None)
        self.assertTrue(self.cast(b, source, 5))
        self.assertEqual((ally.shield, source.combo_uses['trait_moonlight']), (200, 1))
        for t in (6, 11):
            combinations.clear(ally)
            ally.hp = 500
            self.assertTrue(self.cast(b, source, t))
            self.assertEqual(ally.shield, 100)
        self.assertEqual(source.combo_uses['trait_moonlight'], 3)
        combinations.clear(ally)
        ally.hp = 500
        self.assertTrue(self.cast(b, source, 16))
        self.assertEqual(ally.shield, 0)

    def test_night_feed_uses_high_energy_fallback_and_conditioned_full_plunder(self):
        b = self.battle((198,), (128,))
        source, enemy = b.units
        source.energy, enemy.energy = 70, 0
        self.assertEqual(self.hit(b, source, enemy, 20, 1, 'DARK'), 20)
        self.assertEqual((enemy.energy, source.energy), (0, 70))
        self.assertEqual(source.combo_uses.get('trait_night_feed', 0), 0)

        source.combo_ready_at['trait_night_feed'] = 0
        enemy.energy = 11
        self.assertEqual(self.hit(b, source, enemy, 20, 1.1, 'DARK'), 20)
        self.assertEqual((enemy.energy, source.energy), (11, 70))
        self.assertEqual(source.combo_uses.get('trait_night_feed', 0), 0)

        source.combo_ready_at['trait_night_feed'] = 0
        enemy.energy = 30
        status.apply_debuff(b, enemy, 'poison', 1, source=source)
        self.assertEqual(self.hit(b, source, enemy, 20, 2, 'DARK'), 20)
        self.assertEqual((enemy.energy, source.energy), (22, 74))
        self.assertEqual(source.combo_uses['trait_night_feed'], 1)
        row = self.effects(b, 'trait_night_feed', 'energy_drain')[0]
        self.assertEqual((row[6]['stolen'], row[6]['gained'], row[6]['conditioned']), (8, 4, True))
        self.assertEqual(len([event for event in b.events if event[1] == 'attack']), 3)

        # Cooldown, total cap, and no extra recursive attacks.
        self.assertEqual(self.hit(b, source, enemy, 20, 5.9, 'DARK'), 20)
        self.assertEqual(source.combo_uses['trait_night_feed'], 1)
        for t in (6, 10):
            self.assertEqual(self.hit(b, source, enemy, 20, t, 'DARK'), 20)
        self.assertEqual(source.combo_uses['trait_night_feed'], 3)
        before = (enemy.energy, source.energy)
        self.assertEqual(self.hit(b, source, enemy, 20, 14, 'DARK'), 20)
        self.assertEqual((enemy.energy, source.energy), before)
        self.assertEqual(len([event for event in b.events if event[1] == 'attack']), 7)

    def test_night_feed_fallback_threshold_uses_pre_hit_primary_energy(self):
        move = {'name': 'test', 'type': 'DARK', 'power': 40}
        for initial_energy, expected_trigger in ((11, False), (12, True)):
            with self.subTest(initial_energy=initial_energy):
                b = self.battle((198,), (128,))
                source, enemy = b.units
                source.energy, enemy.energy = 70, initial_energy
                with patch.object(status, 'on_hit'):
                    b._land_hit(source, enemy, 20, 1., move=move,
                                primary=True, direct=True)
                rows = self.effects(b, 'trait_night_feed', 'energy_drain')
                self.assertEqual(bool(rows), expected_trigger)
                if expected_trigger:
                    self.assertEqual((rows[0][6]['stolen'], rows[0][6]['gained'],
                                      rows[0][6]['conditioned']), (4, 2, False))
                    self.assertEqual((enemy.energy, source.energy,
                                      source.combo_uses['trait_night_feed']), (18, 72, 1))
                else:
                    self.assertEqual((enemy.energy, source.energy,
                                      source.combo_uses.get('trait_night_feed', 0)),
                                     (initial_energy + 10, 70, 0))

    def test_night_feed_fallback_threshold_and_native_order_are_settled(self):
        b = self.battle((198,), (128,))
        source, enemy = b.units
        source.energy, enemy.energy = 70, 12
        self.assertEqual(self.hit(b, source, enemy, 20, 1, 'DARK'), 20)
        self.assertEqual((enemy.energy, source.energy), (8, 72))
        self.assertEqual(source.combo_uses['trait_night_feed'], 1)
        row = self.effects(b, 'trait_night_feed', 'energy_drain')[0]
        self.assertEqual((row[6]['stolen'], row[6]['gained'], row[6]['conditioned']), (4, 2, False))

        b = self.battle((198,), (128,))
        source, enemy = b.units
        enemy.energy = 30
        status.apply_debuff(b, enemy, 'poison', 0, source=source)
        self.assertTrue(self.cast(b, source, 1))
        trait_rows = self.effects(b, 'trait_night_feed', 'energy_drain')
        native_rows = [event for event in b.events if event[1] == 'skill_effect'
                       and event[4] == 'night_plunder' and event[5] == 'energy_drain']
        self.assertEqual(len(trait_rows), 1)
        self.assertEqual((trait_rows[0][6]['stolen'], trait_rows[0][6]['gained']), (8, 4))
        self.assertTrue(native_rows)
        self.assertLess(b.events.index(trait_rows[0]), b.events.index(native_rows[0]))

    def test_night_feed_counts_shield_absorption_and_survives_target_death(self):
        b = self.battle((198,), (128,))
        source, enemy = b.units
        combinations.grant_shield(b, enemy, enemy, 100, 0, None)
        status.apply_debuff(b, enemy, 'poison', 1, source=source)
        source.energy, enemy.energy = 70, 30
        self.assertEqual(self.hit(b, source, enemy, 50, 1, 'DARK'), 0)
        self.assertEqual(enemy.shield, 50)
        self.assertEqual((enemy.energy, source.energy), (22, 74))
        self.assertEqual(source.combo_uses['trait_night_feed'], 1)

        b = self.battle((198,), (128,))
        source, enemy = b.units
        source.energy, enemy.energy = 70, 30
        status.apply_debuff(b, enemy, 'poison', 1, source=source)
        self.assertEqual(self.hit(b, source, enemy, 1000, 2, 'DARK'), 1000)
        self.assertFalse(enemy.alive)
        self.assertEqual((enemy.energy, source.energy), (22, 74))
        self.assertEqual(source.combo_uses['trait_night_feed'], 1)

        b = self.battle((198,), (128,))
        source, enemy = b.units
        source.energy, enemy.energy = ENERGY_MAX, 30
        status.apply_debuff(b, enemy, 'poison', 1, source=source)
        self.assertEqual(self.hit(b, source, enemy, 20, 1, 'DARK'), 20)
        self.assertEqual(enemy.energy, 30)
        self.assertEqual(source.combo_uses.get('trait_night_feed', 0), 0)


if __name__ == '__main__':
    unittest.main()
