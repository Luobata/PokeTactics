"""Fixed species passives use actual combat facts and bounded arena effects."""
import copy
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sim'))
import arena
import arena_combinations as combinations
import arena_fields as fields
import arena_offense as offense
import arena_skills
import arena_teaching
import arena_traits as traits
import status
from combat import Battle
from data import ENERGY_MAX


class ArenaSpeciesTraits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = arena.build_templates()

    def battle(self, friends=(127,), enemies=(128,), *, equipped=(), enemy_items=(),
               ruleset='arena_v1', normalize=True):
        own, hostile = dict(equipped), dict(enemy_items)
        def comp(ids, mapping):
            return [(copy.copy(self.templates[sid]), mapping[i]) if i in mapping
                    else copy.copy(self.templates[sid]) for i, sid in enumerate(ids)]
        rows = 3 if ruleset == 'arena_v1' else 2
        b = Battle(comp(friends, own), comp(enemies, hostile), random.Random(718),
                   ruleset=ruleset, stat_mode='budget_v1',
                   arena_teams=[[], []] if ruleset == 'arena_v1' else None,
                   positions_a=[(2, rows), (1, rows), (3, rows), (2, rows + 1)][:len(friends)],
                   positions_b=[(2, rows - 1), (3, rows - 1), (1, rows - 1)][:len(enemies)])
        if normalize:
            for u in b.units:
                u.max_hp = u.hp = 1000
                u.energy = 0
        return b

    @staticmethod
    def effects(b, key, effect=None):
        return [e for e in b.events if e[1] == 'combo_effect' and e[4] == key
                and (effect is None or e[5] == effect)]

    def basic(self, b, source, patient, t, raw=100):
        b.duration, source.energy = t, 0
        with patch('combat._damage', return_value=raw), patch.object(status, 'on_hit'), \
                patch.object(b, '_final_damage', side_effect=lambda a, p, m, raw: raw):
            b._strike(source, patient, t)

    def hit(self, b, source, patient, damage, t, move_type=None, *, primary=False, direct=True):
        b.duration = t
        move = {'name': 'test', 'type': move_type, 'power': 40} if move_type else None
        with patch.object(status, 'on_hit'):
            return b._land_hit(source, patient, damage, t, move=move,
                               primary=primary, cast=primary and move is not None, direct=direct)

    def cast(self, b, source, t, raw=50):
        b.duration, source.energy = t, ENERGY_MAX
        target = next(u for u in b.units if u.team != source.team and u.alive)
        with patch.object(status, 'on_hit'), patch.object(b, '_move_damage', return_value=raw):
            return arena_skills.cast(b, source, target, t)

    def test_full_roster_passives_are_defensive_copies_with_strict_species_options(self):
        rows = traits.catalog()
        self.assertEqual({row['sid'] for row in rows}, set(arena.ROSTER))
        self.assertEqual(len({row['id'] for row in rows}), 65)
        self.assertEqual({row['category'] for row in rows}, {'attack', 'defense', 'support'})
        tactical = {196, 197, 198}
        for row in rows:
            self.assertTrue(row['arena_only'])
            self.assertEqual(row['fixed'], row['sid'] not in (9, 34, 154))
            self.assertEqual(row['selectable'], row['sid'] in (9, 34, 154))
            self.assertTrue(row['limit'] is None or row['limit'] > 0)
            self.assertTrue(row['description'])
            self.assertEqual(row['source_label'],
                             '竞技战术设计' if row['sid'] in tactical else '原作特性改编')
        rows[0]['tags'].clear()
        self.assertTrue(traits.catalog()[0]['tags'])
        self.assertIsNone(traits.for_species(16))
        self.assertIsNone(traits.for_species('26'))
        with patch.object(traits, 'TRAITS_ON', False):
            self.assertEqual(len(traits.catalog()), 65)

    def test_static_uses_real_adjacent_basics_cooldown_cap_without_retaliatory_hits(self):
        b = self.battle((26,), (128,))
        wearer, enemy = b.units
        before_rng = b.rng.getstate()
        for t in (1, 2, 6, 11):
            enemy._st.ctrl_until = 0
            status.cleanse(b, enemy, t)
            self.hit(b, enemy, wearer, 5, t, primary=True)
        self.assertEqual(wearer.combo_uses['trait_static'], 2)
        self.assertEqual(len(self.effects(b, 'trait_static', 'status')), 2)
        self.assertEqual(enemy.damage_dealt, 20)
        self.assertEqual(wearer.damage_dealt, 0)
        self.assertEqual(len([e for e in b.events if e[1] == 'attack']), 4)
        self.assertEqual(b.rng.getstate(), before_rng)
        self.assertTrue(all(e[2:4] == (wearer.idx, enemy.idx)
                            for e in self.effects(b, 'trait_static')))

    def test_static_does_not_spend_on_absorbed_or_ranged_cast_secondary_immunity_dr_slot(self):
        for reason in ('shield', 'far', 'cast', 'side', 'immune', 'dr', 'slot'):
            with self.subTest(reason=reason):
                b = self.battle((26,), (181 if reason == 'immune' else 128,))
                wearer, enemy = b.units
                if reason == 'shield':
                    combinations.grant_shield(b, wearer, wearer, 100, 0, None)
                elif reason == 'far':
                    enemy.pos = (2, 1)
                elif reason == 'dr':
                    enemy._st.ctrl_until = 9
                elif reason == 'slot':
                    status.apply_debuff(b, enemy, 'poison', 0, source=wearer)
                self.hit(b, enemy, wearer, 5, 1,
                         'NORMAL' if reason == 'cast' else None, primary=reason != 'side')
                self.assertEqual(wearer.combo_uses.get('trait_static', 0), 0)
                self.assertFalse(self.effects(b, 'trait_static'))

    def test_poison_point_apply_has_no_bonus_damage_and_respects_type_slot_immunity(self):
        for sid in (128, 212):
            with self.subTest(sid=sid):
                b = self.battle((34,), (sid,))
                wearer, enemy = b.units
                self.hit(b, enemy, wearer, 10, 1, primary=True)
                self.assertEqual(enemy.hp, 1000)
                self.assertEqual(enemy._st.debuff, 'poison' if sid == 128 else None)
                self.assertEqual(wearer.combo_uses.get('trait_poison_point', 0), 1 if sid == 128 else 0)
                self.assertEqual(wearer.damage_dealt, 0)

    def test_guts_is_new_slot_physical_window_not_refresh_or_special_or_terrain(self):
        b = self.battle((68,), (128,))
        source, patient = b.units
        attack_before = source.attack
        self.assertTrue(status.apply_debuff(b, source, 'burn', 1, source=patient))
        self.assertLess(source.attack, attack_before)
        self.assertEqual(source.combo_uses['trait_guts'], 1)
        self.assertEqual(self.hit(b, source, patient, 100, 1.1, 'FIGHTING'), 120)
        self.assertEqual(self.hit(b, source, patient, 100, 1.2, 'FIRE'), 100)
        self.assertEqual(self.hit(b, source, patient, 100, 1.3, 'FIGHTING', direct=False), 100)
        self.assertTrue(status.apply_debuff(b, source, 'burn', 2, source=patient))
        self.assertEqual(source.trait_guts_until, 4)
        self.assertEqual(source.combo_uses['trait_guts'], 1)
        self.assertEqual(self.hit(b, source, patient, 100, 4, 'FIGHTING'), 100)
        rows = self.effects(b, 'trait_guts', 'empowered_hit')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][6]['extra_damage'], 20)
        self.assertEqual(source.damage_dealt, 420)

    def test_guts_cleansed_or_ended_window_reverts_without_restoring_the_status(self):
        for ending in ('cleanse', 'expire'):
            with self.subTest(ending=ending):
                b = self.battle((68,), (128,))
                source, enemy = b.units
                status.apply_debuff(b, source, 'poison', 1, source=enemy)
                if ending == 'cleanse':
                    self.assertTrue(status.cleanse(b, source, 2))
                else:
                    source._st.expire = 2
                    source._st.next_dot = 100
                    status.tick(b, 2)
                self.assertEqual(source.trait_guts_fraction, 0)
                self.assertEqual(source.trait_guts_until, 0)
                self.assertEqual(self.hit(b, source, enemy, 100, 2, 'FIGHTING'), 100)
                self.assertEqual(len(self.effects(b, 'trait_guts', 'expire')), 1)

    def test_guts_equipment_cleanse_happens_first_and_an_immune_or_existing_status_never_spends(self):
        b = self.battle((68,), (128,), equipped=[(0, 'grounding_cloak')])
        source, enemy = b.units
        status.apply_debuff(b, source, 'sleep', 1, source=enemy)
        self.assertIsNone(source._st.debuff)
        self.assertEqual(source.combo_uses.get('trait_guts', 0), 0)
        status.apply_debuff(b, source, 'poison', 2, source=enemy)
        self.assertEqual(source.combo_uses['trait_guts'], 1)
        self.assertFalse(status.apply_debuff(b, source, 'burn', 3, source=enemy))
        self.assertEqual(source.combo_uses['trait_guts'], 1)

    def test_guts_cooldown_and_cap_require_new_statuses(self):
        b = self.battle((68,), (128,))
        source, enemy = b.units
        for t in (1, 2, 6, 11):
            status.cleanse(b, source, t)
            status.apply_debuff(b, source, 'poison', t, source=enemy)
        self.assertEqual(source.combo_uses['trait_guts'], 2)
        self.assertEqual(len(self.effects(b, 'trait_guts', 'offense_buff')), 2)

    def test_low_hp_elemental_boosts_require_matching_direct_actual_benefit_and_have_caps(self):
        for sid, kind, hp, expected, key in (
                (6, 'FIRE', 333, 125, 'trait_blaze'), (9, 'WATER', 500, 114, 'trait_torrent')):
            with self.subTest(sid=sid):
                b = self.battle((sid,), (128,))
                source, patient = b.units
                source.hp = hp + 1
                self.assertEqual(self.hit(b, source, patient, 100, 1, kind), 100)
                source.hp = hp
                self.assertEqual(self.hit(b, source, patient, 100, 2, 'NORMAL'), 100)
                self.assertEqual(self.hit(b, source, patient, 100, 2, kind, direct=False), 100)
                for i, t in enumerate((3, 3.5, 6, 9, 12)):
                    patient.hp = 1000
                    actual = self.hit(b, source, patient, 100, t, kind)
                    self.assertEqual(actual, expected if i in (0, 2, 3) else 100)
                self.assertEqual(source.combo_uses[key], 3)
                for event in self.effects(b, key, 'empowered_hit'):
                    self.assertEqual(event[6]['amount'], expected - 100)
                    self.assertEqual(event[6]['absorbed'], 0)
                    self.assertEqual(b.events[event[6]['action_index']][1], 'attack')

    def test_low_hp_overkill_and_zero_do_not_consume_but_extra_shield_absorption_does(self):
        b = self.battle((6,), (128,))
        source, patient = b.units
        source.hp, patient.hp = 300, 20
        self.assertEqual(self.hit(b, source, patient, 100, 1, 'FIRE'), 20)
        self.assertEqual(source.combo_uses.get('trait_blaze', 0), 0)
        b = self.battle((6,), (128,))
        source, patient = b.units
        source.hp = 300
        self.assertEqual(self.hit(b, source, patient, 0, 1, 'FIRE'), 0)
        self.assertEqual(source.combo_uses.get('trait_blaze', 0), 0)
        combinations.grant_shield(b, patient, patient, 200, 1, None)
        self.assertEqual(self.hit(b, source, patient, 100, 1.1, 'FIRE'), 0)
        self.assertEqual(patient.shield, 75)
        self.assertEqual(source.combo_uses['trait_blaze'], 1)
        payload = self.effects(b, 'trait_blaze', 'empowered_hit')[0][6]
        self.assertEqual((payload['amount'], payload['absorbed']), (0, 25))
        self.assertEqual(source.damage_dealt, 0)

    def test_sturdy_direct_full_hp_lethal_uses_shield_first_and_preserves_sash(self):
        b = self.battle((127,), (76,), enemy_items=[(0, 'sash')])
        source, patient = b.units
        combinations.grant_shield(b, patient, patient, 150, 0, None)
        self.assertEqual(self.hit(b, source, patient, 10000, 1), 999)
        self.assertEqual((patient.hp, patient.shield, patient.shield_absorbed), (1, 0, 150))
        self.assertFalse(patient.item_sash_used)
        self.assertEqual(source.damage_dealt, 999)
        payload = self.effects(b, 'trait_sturdy', 'guard')[0][6]
        self.assertEqual(payload['amount'], 1)
        self.assertEqual(payload['prevented'], 8851)
        self.hit(b, source, patient, 10, 2)
        self.assertTrue(patient.item_sash_used)
        self.assertEqual(patient.hp, 1)
        self.assertEqual(patient.combo_uses['trait_sturdy'], 1)
        self.hit(b, source, patient, 10, 3)
        self.assertFalse(patient.alive)
        self.assertEqual(len([e for e in b.events if e[1] == 'die']), 1)

    def test_sturdy_never_triggers_wounded_nonlethal_full_shield_or_indirect(self):
        for kind in ('wounded', 'nonlethal', 'shielded', 'indirect'):
            with self.subTest(kind=kind):
                b = self.battle((127,), (76,))
                source, patient = b.units
                if kind == 'wounded':
                    patient.hp = 999
                if kind == 'shielded':
                    combinations.grant_shield(b, patient, patient, 2000, 0, None)
                self.hit(b, source, patient, 100 if kind == 'nonlethal' else 1000,
                         1, direct=kind != 'indirect')
                self.assertEqual(patient.combo_uses.get('trait_sturdy', 0), 0)

    def test_intimidate_opening_nearest_two_weakens_physical_only_once_then_expires(self):
        b = self.battle((59,), (128, 127, 195))
        source, first, second, third = b.units
        rows = self.effects(b, 'trait_intimidate', 'weaken')
        self.assertEqual(len(rows), 2)
        self.assertEqual({e[3] for e in rows}, {first.idx, third.idx})
        self.assertEqual(source.combo_uses['trait_intimidate'], 1)
        self.assertEqual(second.trait_weaken_fraction, 0)
        self.assertEqual(self.hit(b, first, source, 100, 1, 'NORMAL'), 90)
        self.assertEqual(self.hit(b, first, source, 100, 1.1, 'FIRE'), 100)
        self.assertEqual(self.hit(b, first, source, 100, 1.2, 'NORMAL', direct=False), 100)
        packet = self.effects(b, 'trait_intimidate', 'guard')[0]
        self.assertEqual(packet[2:4], (source.idx, first.idx))
        self.assertEqual(packet[6]['amount'], 10)
        self.assertEqual(packet[6]['origin_idx'], source.idx)
        panel = first.attack
        traits.expire(b, first, 5)
        self.assertEqual(first.attack, panel)
        self.assertEqual(self.hit(b, first, source, 100, 5, 'NORMAL'), 100)
        self.assertEqual(len(self.effects(b, 'trait_intimidate', 'expire')), 1)

    def test_same_intimidate_effect_does_not_stack_or_change_the_panel(self):
        b = self.battle((59, 59), (128,))
        first, second, enemy = b.units
        self.assertEqual(enemy.trait_weaken_fraction, .10)
        self.assertEqual(len(self.effects(b, 'trait_intimidate', 'weaken')), 1)
        self.assertEqual(sum(u.combo_uses.get('trait_intimidate', 0) for u in (first, second)), 1)
        self.assertEqual(self.hit(b, enemy, first, 100, 1, 'NORMAL'), 90)

    def test_compound_eyes_reuses_dodge_roll_second_half_without_extra_randomness(self):
        for roll, count in ((.1, 0), (.3, 1), (.7, 0)):
            with self.subTest(roll=roll):
                b = self.battle((12,), (128,))
                source, target = b.units
                target.item_dodge = .5
                with patch.object(b.rng, 'random', return_value=roll) as rng:
                    self.basic(b, source, target, 1, 100)
                self.assertEqual(rng.call_count, 1)
                self.assertEqual(source.combo_uses.get('trait_compound_eyes', 0), count)
                self.assertEqual(target.hp, 1000 if roll == .1 else 900)
                if count:
                    self.assertEqual(self.effects(b, 'trait_compound_eyes')[0][6]['amount'], 0)

    def test_compound_eyes_has_cd_cap_and_never_checks_support_dodge(self):
        b = self.battle((12, 127), (128,))
        source, friend, target = b.units
        target.item_dodge = .5
        with patch.object(b.rng, 'random', return_value=.3) as rng:
            for t in (1, 1.5, 4, 7, 10):
                self.basic(b, source, target, t, 1)
            self.assertEqual(rng.call_count, 5)
        self.assertEqual(source.combo_uses['trait_compound_eyes'], 3)
        friend.hp, friend.item_dodge = 100, 1
        before_rng = b.rng.getstate()
        self.assertTrue(self.cast(b, source, 11))
        self.assertEqual(b.rng.getstate(), before_rng)
        self.assertEqual(source.combo_uses['trait_compound_eyes'], 3)

    def test_volt_actual_hp_snapshot_survives_self_heal_and_native_equipment(self):
        b = self.battle((26,), (171,), equipped=[(0, 'torrent_orb')])
        source, patient = b.units
        patient.hp, patient.energy = 500, ENERGY_MAX - 3
        with patch.object(arena_skills, '_side_hit', wraps=arena_skills._side_hit) as secondary:
            self.assertTrue(self.cast(b, source, 1, raw=3))
        self.assertEqual(patient.hp, 537)
        self.assertEqual(source.damage_dealt, 3)
        self.assertEqual(patient.damage_taken, 3)
        self.assertEqual(patient.healing_done, 40)
        self.assertEqual(patient.energy, ENERGY_MAX)
        self.assertEqual(source.combo_uses['torrent_orb'], 1)
        self.assertEqual(patient.combo_uses['trait_volt_absorb'], 1)
        self.assertEqual(secondary.call_count, 0)
        cast = next(e for e in b.events if e[1] == 'cast')
        self.assertEqual(cast[6], 3)
        heal = self.effects(b, 'trait_volt_absorb', 'heal')[0]
        self.assertEqual(heal[6]['amount'], 40)
        self.assertFalse(self.effects(b, 'trait_volt_absorb', 'energy'))  # Defender energy already capped.

    def test_volt_energy_and_heal_have_actual_capped_ledgers_and_one_use_per_hit(self):
        b = self.battle((127,), (171,))
        source, patient = b.units
        patient.hp, patient.energy = 990, ENERGY_MAX - 2
        self.assertEqual(self.hit(b, source, patient, 1, 1, 'ELECTRIC'), 1)
        self.assertEqual(patient.hp, 1000)
        self.assertEqual(patient.energy, ENERGY_MAX)
        self.assertEqual((patient.healing_done, patient.self_healing), (11, 11))
        self.assertEqual(patient.combo_uses['trait_volt_absorb'], 1)
        self.assertEqual(self.effects(b, 'trait_volt_absorb', 'energy')[0][6]['amount'], 2)
        self.assertEqual(self.effects(b, 'trait_volt_absorb', 'heal')[0][6]['amount'], 11)
        for t in (1.5, 5, 9, 13):
            self.hit(b, source, patient, 50, t, 'ELECTRIC')
        self.assertEqual(patient.combo_uses['trait_volt_absorb'], 3)
        self.assertEqual(len(self.effects(b, 'trait_volt_absorb', 'heal')), 3)

    def test_volt_cannot_react_to_zero_absorption_indirect_nonelectric_lethal_or_no_benefit(self):
        for reason in ('zero', 'shield', 'indirect', 'type', 'dead', 'antiheal'):
            with self.subTest(reason=reason):
                b = self.battle((127,), (171,))
                source, patient = b.units
                if reason == 'shield':
                    combinations.grant_shield(b, patient, patient, 100, 0, None)
                if reason == 'antiheal':
                    patient.energy = ENERGY_MAX
                    patient.healing_blocks = [{'source': source.idx, 'fraction': 1., 'expires_at': 9.}]
                self.hit(b, source, patient, 0 if reason == 'zero' else
                         1000 if reason == 'dead' else 10,
                         1, 'NORMAL' if reason == 'type' else 'ELECTRIC', direct=reason != 'indirect')
                self.assertEqual(patient.combo_uses.get('trait_volt_absorb', 0), 0)
                self.assertFalse(self.effects(b, 'trait_volt_absorb'))

    def test_magic_guard_dot_first_three_positive_packets_cd_no_shield_consumption(self):
        b = self.battle((127,), (36,))
        source, patient = b.units
        status.apply_debuff(b, patient, 'poison', 0, source=source)
        combinations.grant_shield(b, patient, patient, 300, 0, None)
        patient.shield_until = 10  # Keep the test's shield alive through all four DOT packets.
        for t in (1, 2, 3):
            b.duration = t
            status.tick(b, t)
            self.assertEqual(patient.hp, 1000)
            self.assertEqual(patient.shield, 300)
        self.assertEqual(patient.combo_uses['trait_magic_guard'], 3)
        rows = self.effects(b, 'trait_magic_guard', 'guard')
        self.assertTrue(all(row[6]['amount'] == 0 for row in rows))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row[6]['avoided_shield_absorption'] > 0 for row in rows))
        b.duration = 4
        status.tick(b, 4)
        self.assertLess(patient.shield, 300)
        self.assertEqual(patient.hp, 1000)
        self.assertEqual(patient.shield_absorbed, 11)
        self.assertEqual(source.damage_dealt, 0)
        self.assertEqual(b.status_stats['dot_damage'], 0)

    def test_magic_guard_is_not_a_direct_shield_and_zero_indirect_does_not_consume(self):
        b = self.battle((127,), (36,))
        source, patient = b.units
        self.hit(b, source, patient, 0, 1, direct=False)
        self.assertEqual(patient.combo_uses.get('trait_magic_guard', 0), 0)
        self.hit(b, source, patient, 100, 1)
        self.assertEqual(patient.hp, 900)
        self.assertEqual(patient.combo_uses.get('trait_magic_guard', 0), 0)
        self.hit(b, source, patient, 100, 1.1, direct=False)
        self.assertEqual(patient.hp, 900)
        self.hit(b, source, patient, 100, 1.5, direct=False)
        self.assertEqual(patient.hp, 800)
        self.assertEqual(patient.combo_uses['trait_magic_guard'], 1)

    def test_magic_guard_rock_entry_has_zero_hp_and_absorbed_payload(self):
        b = self.battle((95,), (36,))
        source, patient = b.units
        field = fields.place_rocks(b, source, patient, 0)
        destination = next(cell for cell in field['cells'] if cell != patient.pos)
        combinations.grant_shield(b, patient, patient, 100, 0, None)
        fields.move_unit(b, patient, destination, 1, source=source, reason='knockback')
        self.assertEqual((patient.hp, patient.shield, patient.shield_absorbed), (1000, 100, 0))
        row = next(e for e in b.events if e[1] == 'field_effect' and e[5] == 'enter')
        self.assertEqual((row[6]['actual'], row[6]['absorbed']), (0, 0))
        self.assertEqual(patient.combo_uses['trait_magic_guard'], 1)

    def test_natural_cure_only_completed_native_and_preserves_flinch_dr(self):
        b = self.battle((121, 127), (128,))
        source, friend, enemy = b.units
        status.apply_debuff(b, source, 'poison', 0, source=enemy)
        friend.energy = 10
        self.assertTrue(self.cast(b, source, 1))
        self.assertIsNone(source._st.debuff)
        self.assertEqual(source.combo_uses['trait_natural_cure'], 1)
        self.assertEqual(source.damage_dealt, 0)
        self.assertEqual(len(self.effects(b, 'trait_natural_cure', 'cleanse')), 1)
        # No legal native patient means no cast, energy spend or self-cleanse.
        status.apply_debuff(b, source, 'poison', 2, source=enemy)
        friend.energy = ENERGY_MAX
        source.energy = ENERGY_MAX
        self.assertFalse(arena_skills.cast(b, source, enemy, 6))
        self.assertEqual(source._st.debuff, 'poison')
        self.assertEqual(source.combo_uses['trait_natural_cure'], 1)
        for index in (-1, 999, None, True):
            self.assertFalse(traits.after_native_cast(b, source, 6, index))

    def test_natural_cure_cannot_turn_a_blocked_cast_or_tm_into_a_cleanse(self):
        b = self.battle((121, 127), (128,))
        source, friend, enemy = b.units
        status.apply_debuff(b, source, 'sleep', 1, source=enemy)
        source.energy = ENERGY_MAX
        self.assertFalse(arena_skills.cast(b, source, enemy, 1.1))
        self.assertEqual(source._st.debuff, 'sleep')
        self.assertEqual(source.combo_uses.get('trait_natural_cure', 0), 0)
        status.cleanse(b, source, 7)
        status.apply_debuff(b, source, 'poison', 7, source=enemy)
        source.technique, source.technique_used = 'thunderbolt', False
        with patch.object(status, 'on_hit'):
            arena_teaching.after_basic(b, source, enemy, 7.1)
        self.assertEqual(source._st.debuff, 'poison')
        self.assertFalse(self.effects(b, 'trait_natural_cure'))

    def test_native_cure_cooldown_cap_and_empty_cleanses_are_not_spent(self):
        b = self.battle((121, 127), (128,))
        source, friend, enemy = b.units
        self.cast(b, source, 0)
        self.assertEqual(source.combo_uses.get('trait_natural_cure', 0), 0)
        for t in (1, 2, 5, 9):
            status.apply_debuff(b, source, 'poison', t, source=enemy)
            friend.energy = 0
            self.cast(b, source, t)
        self.assertEqual(source.combo_uses['trait_natural_cure'], 2)
        self.assertEqual(len(self.effects(b, 'trait_natural_cure', 'cleanse')), 2)

    def test_healer_true_other_native_heal_cleanses_status_and_preserves_flinch_and_dr(self):
        b = self.battle((242, 127), (128,))
        source, patient, enemy = b.units
        patient.hp = 400
        status.apply_debuff(b, patient, 'para', 0, source=enemy)
        status.apply_flinch(b, patient, 1)  # DR blocks new flinch, preserve an existing one.
        patient._st.flinch_until = patient._st.stun_until = 1.3
        self.assertTrue(self.cast(b, source, 1))
        self.assertIsNone(patient._st.debuff)
        self.assertTrue(status.stunned(patient, 1.1))
        self.assertGreater(patient._st.ctrl_until, 1)
        self.assertEqual(source.combo_uses['trait_healer'], 1)
        self.assertEqual(source.self_healing, 0)
        self.assertEqual(source.healing_done, 180)
        row = self.effects(b, 'trait_healer', 'cleanse')[0]
        self.assertEqual(row[2:4], (source.idx, patient.idx))
        self.assertEqual(row[6]['status_kind'], 'para')

    def test_healer_threshold_empty_self_heal_and_antiheal_cannot_spend(self):
        for reason in ('threshold', 'empty', 'self', 'antiheal'):
            with self.subTest(reason=reason):
                b = self.battle((242, 127), (128,))
                source, patient, enemy = b.units
                source.hp = 500 if reason == 'self' else 1000
                patient.hp = 960 if reason == 'threshold' else 1000 if reason == 'self' else 400
                if reason != 'empty':
                    status.apply_debuff(b, source if reason == 'self' else patient,
                                        'poison', 0, source=enemy)
                if reason == 'antiheal':
                    patient.healing_blocks = [{'source': enemy.idx, 'fraction': 1., 'expires_at': 9.}]
                self.cast(b, source, 1)
                self.assertEqual(source.combo_uses.get('trait_healer', 0), 0)
                self.assertFalse(self.effects(b, 'trait_healer'))

    def test_healer_cd_cap_and_no_recursive_gear_trigger(self):
        b = self.battle((242, 127, 195), (128,), equipped=[(0, 'dew_charm')])
        source, patient, second, enemy = b.units
        for t in (1, 2, 5, 9, 13):
            patient.hp, second.hp = 100, 200
            status.apply_debuff(b, patient, 'poison', t, source=enemy)
            self.cast(b, source, t)
        self.assertEqual(source.combo_uses['trait_healer'], 3)
        self.assertEqual(len(self.effects(b, 'trait_healer', 'cleanse')), 3)
        self.assertEqual(source.combo_uses['dew_charm'], 3)
        self.assertEqual(len([e for e in b.events if e[1] == 'cast']), 5)
        self.assertFalse(any(e[1] == 'attack' for e in b.events))

    def test_ward_and_guts_partition_true_extra_hp_and_absorption_from_one_basic(self):
        # Shield consumption produces a real charge; the basic must never
        # credit the same trait increment to both ward and Guts annotations.
        for kind, shield, raw, expected_ward, expected_guts in (
                ('plain', 0, 10, (10, 0), (4, 0)),
                ('shield', 15, 10, (5, 5), (4, 0)),
                ('shield_full', 30, 10, (0, 10), (0, 4)),
                ('sturdy', 0, 600, (399, 0), (0, 0)),
                ('sash', 0, 600, (399, 0), (0, 0))):
            with self.subTest(kind=kind):
                b = self.battle((68,), (76 if kind == 'sturdy' else 128,),
                                equipped=[(0, 'ward_bracer')],
                                enemy_items=[(0, 'sash')] if kind == 'sash' else [])
                source, target = b.units
                combinations.grant_shield(b, source, source, 200, 0, None)
                self.hit(b, target, source, 100, .1)
                self.assertGreater(source.ward_charge_until, 1)
                status.apply_debuff(b, source, 'poison', .2, source=target)
                if shield:
                    combinations.grant_shield(b, target, target, shield, .2, None)
                before = len([e for e in b.events if e[1] == 'attack'])
                self.basic(b, source, target, 1, raw)
                ward = self.effects(b, 'ward_bracer', 'empowered_basic')[-1][6]
                guts = self.effects(b, 'trait_guts', 'empowered_hit')
                self.assertEqual((ward['amount'], ward['absorbed']), expected_ward)
                reported = (guts[-1][6]['amount'], guts[-1][6]['absorbed']) if guts else (0, 0)
                self.assertEqual(reported, expected_guts)
                self.assertEqual(len([e for e in b.events if e[1] == 'attack']), before + 1)
                self.assertEqual(source.damage_dealt, 1000 - target.hp)
                if kind in ('sturdy', 'sash'):
                    self.assertEqual(target.hp, 1)

    def test_ward_guts_and_intimidate_share_rounding_and_do_not_double_count(self):
        for shield, expected_ward, expected_guts in (
                (0, (9, 0), (3, 0)), (16, (2, 7), (3, 0)), (30, (0, 9), (0, 3))):
            with self.subTest(shield=shield):
                b = self.battle((68,), (59,), equipped=[(0, 'ward_bracer')])
                source, target = b.units
                self.assertEqual(source.trait_weaken_fraction, .10)
                combinations.grant_shield(b, source, source, 200, 0, None)
                self.hit(b, target, source, 100, .1)
                status.apply_debuff(b, source, 'poison', .2, source=target)
                if shield:
                    combinations.grant_shield(b, target, target, shield, .2, None)
                self.basic(b, source, target, 1, 10)
                ward = self.effects(b, 'ward_bracer', 'empowered_basic')[-1][6]
                guts = self.effects(b, 'trait_guts', 'empowered_hit')[-1][6]
                self.assertEqual((ward['amount'], ward['absorbed']), expected_ward)
                self.assertEqual((guts['amount'], guts['absorbed']), expected_guts)
                self.assertEqual(ward['amount'] + guts['amount'] +
                                 ward['absorbed'] + guts['absorbed'], 12)
                self.assertEqual(source.damage_dealt, max(0, 21 - shield))

    def test_classic_basic_preserves_subclass_original_hit_signature(self):
        class LegacyHitBattle(Battle):
            def _land_hit(self, attacker, target, damage, t, move=None, primary=False, cast=False):
                self.captured_hit = (attacker.idx, target.idx, damage)
                return super()._land_hit(attacker, target, damage, t,
                                         move=move, primary=primary, cast=cast)
        b = LegacyHitBattle([copy.copy(self.templates[68])], [copy.copy(self.templates[59])],
                            random.Random(17), ruleset='base_v1', stat_mode='budget_v1',
                            positions_a=[(2, 2)], positions_b=[(2, 1)])
        source, target = b.units
        source.hp = source.max_hp = target.hp = target.max_hp = 1000
        self.basic(b, source, target, 1, 10)
        self.assertEqual(b.captured_hit, (source.idx, target.idx, 10))
        self.assertEqual((source.damage_dealt, target.hp), (10, 990))

    def prototype(self, sid, enemy_sid, item=None):
        sys.path.insert(0, str(ROOT / 'tools/acceptance'))
        from teaching_skill_prototype import PrototypeBattle
        source = copy.copy(self.templates[sid])
        b = PrototypeBattle([(source, item) if item else source],
                            [copy.copy(self.templates[enemy_sid])], random.Random(19),
                            ruleset='arena_v1', stat_mode='budget_v1',
                            positions_a=[(2, 3)], positions_b=[(2, 2)])
        for unit in b.units:
            unit.hp = unit.max_hp = 1000
            unit.energy = 0
        return b

    def test_arena_prototype_preserves_charge_context_and_guts_partition(self):
        b = self.prototype(68, 128, 'ward_bracer')
        source, target = b.units
        combinations.grant_shield(b, source, source, 200, 0, None)
        self.hit(b, target, source, 100, .1)
        status.apply_debuff(b, source, 'poison', .2, source=target)
        self.basic(b, source, target, 1, 10)
        self.assertEqual((target.hp, source.damage_dealt), (976, 24))
        self.assertEqual(self.effects(b, 'ward_bracer', 'empowered_basic')[-1][6]['amount'], 10)
        self.assertEqual(self.effects(b, 'trait_guts', 'empowered_hit')[-1][6]['amount'], 4)
        self.assertFalse(any(e[1] == 'teaching_effect' for e in b.events))

    def test_arena_prototype_returns_settled_hp_and_forwards_indirect_damage(self):
        b = self.prototype(26, 171, 'torrent_orb')
        source, target = b.units
        target.hp = 500
        self.assertTrue(self.cast(b, source, 1, raw=3))
        self.assertEqual((source.damage_dealt, target.hp), (3, 537))
        self.assertEqual(source.combo_uses['torrent_orb'], 1)
        b = self.prototype(127, 36)
        source, target = b.units
        self.assertEqual(self.hit(b, source, target, 10, 1, direct=False), 0)
        self.assertEqual((target.hp, target.damage_taken), (1000, 0))
        self.assertEqual(target.combo_uses['trait_magic_guard'], 1)

    def test_classic_does_not_apply_opening_guts_sturdy_magic_or_any_trait(self):
        b = self.battle((59, 68), (76, 36), ruleset='base_v1')
        source, fighter, sturdy, magic = b.units
        self.assertFalse(self.effects(b, 'trait_intimidate'))
        status.apply_debuff(b, fighter, 'poison', 0, source=source)
        self.assertEqual(fighter.trait_guts_fraction, 0)
        self.assertEqual(self.hit(b, source, sturdy, 1000, 1), 1000)
        self.assertFalse(sturdy.alive)
        self.assertEqual(self.hit(b, source, magic, 100, 1, direct=False), 100)
        self.assertFalse(any(e[1] == 'combo_effect' and e[4].startswith('trait_') for e in b.events))

    def test_expanded_contact_statuses_apply_sleep_and_respect_immunity_and_caps(self):
        b = self.battle((45,), (128,))
        wearer, enemy = b.units
        for t in (1, 2, 7, 13):
            enemy._st.ctrl_until = 0
            status.cleanse(b, enemy, t)
            self.hit(b, enemy, wearer, 5, t, primary=True)
        self.assertEqual(wearer.combo_uses['trait_effect_spore'], 2)
        self.assertEqual(len(self.effects(b, 'trait_effect_spore', 'status')), 2)
        self.assertEqual(wearer.damage_dealt, 0)
        b = self.battle((31,), (212,))  # 钢属性免疫中毒
        wearer, enemy = b.units
        self.hit(b, enemy, wearer, 10, 1, primary=True)
        self.assertIsNone(enemy._st.debuff)
        self.assertEqual(wearer.combo_uses.get('trait_venom_scales', 0), 0)
        b = self.battle((181,), (128,))
        wearer, enemy = b.units
        self.hit(b, enemy, wearer, 10, 1, primary=True)
        self.assertEqual(enemy._st.debuff, 'para')
        self.assertEqual(wearer.combo_uses['trait_static_fleece'], 1)

    def test_contact_root_traits_root_adjacent_basics_without_status_slot_or_damage(self):
        for sid, key in ((94, 'trait_cursed_body'), (114, 'trait_tangling_vines'),
                         (195, 'trait_mud_wrap')):
            with self.subTest(sid=sid):
                b = self.battle((sid,), (128,))
                wearer, enemy = b.units
                self.hit(b, enemy, wearer, 5, 1, primary=True)
                self.assertEqual(enemy.root_until, 2.2)
                self.assertEqual(enemy.root_source, wearer.idx)
                self.assertIsNone(enemy._st.debuff)
                self.assertEqual(wearer.combo_uses[key], 1)
                self.assertEqual(wearer.hp, 995)
                enemy.pos = (0, 1)  # 非邻格普攻不触发
                self.hit(b, enemy, wearer, 5, 6, primary=True)
                self.assertEqual(wearer.combo_uses[key], 1)
                enemy.pos = (2, 2)
                self.hit(b, enemy, wearer, 5, 6.5, primary=True)
                self.assertEqual(wearer.combo_uses[key], 2)
                self.assertEqual(enemy.root_until, 7.7)

    def test_spin_guard_shields_self_after_adjacent_actual_basic_with_cd_and_cap(self):
        b = self.battle((237,), (128,))
        wearer, enemy = b.units
        self.hit(b, enemy, wearer, 50, 1, primary=True)
        self.assertEqual((wearer.shield, wearer.shield_until), (60, 4))
        self.assertEqual(wearer.combo_uses['trait_spin_guard'], 1)
        enemy.pos = (0, 1)
        self.hit(b, enemy, wearer, 50, 5, primary=True)  # 非邻格不触发
        self.assertEqual(wearer.combo_uses['trait_spin_guard'], 1)
        enemy.pos = (2, 2)
        for t in (5.5, 9.5, 13.5):
            self.hit(b, enemy, wearer, 50, t, primary=True)
        self.assertEqual(wearer.combo_uses['trait_spin_guard'], 3)
        self.assertEqual(len(self.effects(b, 'trait_spin_guard', 'shield')), 3)

    def test_typed_absorb_variants_heal_or_energize_only_on_matching_actual_type(self):
        b = self.battle((127,), (131,))
        source, patient = b.units
        patient.hp, patient.energy = 900, ENERGY_MAX - 10
        self.assertEqual(self.hit(b, source, patient, 50, 1, 'WATER'), 50)
        self.assertEqual((patient.hp, patient.energy), (890, ENERGY_MAX - 6))
        self.assertEqual(patient.combo_uses['trait_water_absorb'], 1)
        self.hit(b, source, patient, 50, 2, 'NORMAL')  # 属性不符不触发
        self.assertEqual(patient.combo_uses['trait_water_absorb'], 1)
        b = self.battle((127,), (125,))
        source, patient = b.units
        patient.hp, patient.energy = 900, ENERGY_MAX - 6
        self.hit(b, source, patient, 50, 1, 'ELECTRIC')
        self.assertEqual((patient.hp, patient.energy), (850, ENERGY_MAX))  # 导电只回能
        self.assertEqual(patient.combo_uses['trait_galvanize'], 1)
        self.assertFalse(self.effects(b, 'trait_galvanize', 'heal'))
        b = self.battle((127,), (157,))
        source, patient = b.units
        patient.hp, patient.energy = 900, 0
        for t in (1, 2, 5, 9, 13):
            patient.hp = 900
            self.hit(b, source, patient, 50, t, 'FIRE')
        self.assertEqual(patient.combo_uses['trait_flash_fire'], 3)
        self.assertEqual(len(self.effects(b, 'trait_flash_fire', 'heal')), 3)

    def test_competitive_window_boosts_special_only_and_ends_with_the_status(self):
        b = self.battle((40,), (128,))
        source, enemy = b.units
        status.apply_debuff(b, source, 'poison', 1, source=enemy)
        self.assertEqual(source.combo_uses['trait_competitive'], 1)
        self.assertEqual(self.hit(b, source, enemy, 100, 1.1, 'PSYCHIC'), 120)
        self.assertEqual(self.hit(b, source, enemy, 100, 1.2, 'FIGHTING'), 100)
        self.assertEqual(source.combo_uses['trait_competitive'], 1)  # 开窗耗次数，命中不再耗
        status.cleanse(b, source, 2)
        self.assertEqual(self.hit(b, source, enemy, 100, 2.1, 'PSYCHIC'), 100)
        self.assertEqual(len(self.effects(b, 'trait_competitive', 'expire')), 1)

    def test_anger_point_window_boosts_physical_only(self):
        b = self.battle((128,), (127,))
        source, enemy = b.units
        status.apply_debuff(b, source, 'poison', 1, source=enemy)
        self.assertEqual(source.combo_uses['trait_anger_point'], 1)
        self.assertEqual(self.hit(b, source, enemy, 100, 1.1, 'FIGHTING'), 125)
        self.assertEqual(self.hit(b, source, enemy, 100, 1.2, 'PSYCHIC'), 100)

    def test_synchronize_mirrors_new_major_status_only_to_a_legal_enemy_source(self):
        b = self.battle((65,), (128,))
        source, enemy = b.units
        status.apply_debuff(b, source, 'poison', 1, source=enemy)
        self.assertEqual(enemy._st.debuff, 'poison')
        self.assertEqual(source.combo_uses['trait_synchronize'], 1)
        self.assertEqual(len(self.effects(b, 'trait_synchronize', 'status')), 1)
        for reason in ('immune', 'slot', 'anonymous'):
            with self.subTest(reason=reason):
                b = self.battle((65,), (212 if reason == 'immune' else 128,))
                source, enemy = b.units
                if reason == 'slot':
                    status.apply_debuff(b, enemy, 'burn', 0, source=source)
                status.apply_debuff(b, source, 'poison', 1,
                                    source=None if reason == 'anonymous' else enemy)
                self.assertEqual(source._st.debuff, 'poison')
                self.assertEqual(source.combo_uses.get('trait_synchronize', 0), 0)

    def test_insomnia_immediately_cleanses_sleep_only_with_cap(self):
        b = self.battle((164,), (128,))
        source, enemy = b.units
        status.apply_debuff(b, source, 'sleep', 1, source=enemy)
        self.assertIsNone(source._st.debuff)
        self.assertEqual(source.combo_uses['trait_insomnia'], 1)
        self.assertEqual(len(self.effects(b, 'trait_insomnia', 'cleanse')), 1)
        status.apply_debuff(b, source, 'poison', 2, source=enemy)
        self.assertEqual(source._st.debuff, 'poison')
        self.assertEqual(source.combo_uses['trait_insomnia'], 1)
        status.cleanse(b, source, 7)
        for t in (7, 12, 17):
            status.cleanse(b, source, t)
            status.apply_debuff(b, source, 'sleep', t, source=enemy)
        self.assertEqual(source.combo_uses['trait_insomnia'], 2)

    def test_unnerve_shares_intimidate_strongest_wins_and_clear_body_blocks_once(self):
        b = self.battle((59, 248), (128,))
        first, second, enemy = b.units
        self.assertEqual(enemy.trait_weaken_fraction, .10)
        self.assertEqual(len(self.effects(b, 'trait_intimidate', 'weaken')) +
                         len(self.effects(b, 'trait_unnerve', 'weaken')), 1)
        self.assertEqual(sum(u.combo_uses.get(k, 0) for u in (first, second)
                             for k in ('trait_intimidate', 'trait_unnerve')), 1)
        self.assertEqual(self.hit(b, enemy, first, 100, 1, 'NORMAL'), 90)
        b = self.battle((59,), (73,))
        source, patient = b.units
        self.assertEqual(patient.trait_weaken_fraction, 0)
        self.assertEqual(patient.combo_uses['trait_clear_body'], 1)
        self.assertEqual(len(self.effects(b, 'trait_clear_body', 'guard')), 1)
        self.assertEqual(source.combo_uses.get('trait_intimidate', 0), 0)
        self.assertEqual(self.hit(b, source, patient, 100, 1, 'NORMAL'), 100)

    def test_opening_barrier_shields_weakest_ally_once(self):
        b = self.battle((122, 127), (128,))
        source, friend, enemy = b.units
        rows = self.effects(b, 'trait_opening_barrier', 'shield')
        self.assertEqual(len(rows), 1)
        self.assertEqual(source.combo_uses['trait_opening_barrier'], 1)
        shielded = b.units[rows[0][3]]
        self.assertEqual(shielded.team, source.team)
        self.assertGreater(shielded.shield, 0)

    def test_pressure_drains_opening_energy_once(self):
        b = self.battle((142,), (128, 127))
        source, first, second = b.units
        self.assertEqual(source.combo_uses.get('trait_pressure', 0), 0)  # 开战时无人有能量
        first.energy, second.energy = 10, 3
        traits.opening(b)
        self.assertEqual((first.energy, second.energy), (4, 0))
        self.assertEqual(source.combo_uses['trait_pressure'], 1)
        self.assertEqual(len(self.effects(b, 'trait_pressure', 'energy_drain')), 2)

    def test_stone_core_saves_from_half_health_but_not_below(self):
        for sid, key in ((95, 'trait_stone_core'), (208, 'trait_steel_core')):
            with self.subTest(sid=sid):
                b = self.battle((127,), (sid,))
                source, patient = b.units
                patient.hp = 600
                self.assertEqual(self.hit(b, source, patient, 1000, 1), 599)
                self.assertEqual((patient.hp, patient.alive), (1, True))
                self.assertEqual(patient.combo_uses[key], 1)
                self.assertEqual(self.effects(b, key, 'guard')[0][6]['reason'],
                                 'half_health_direct_lethal')
                b = self.battle((127,), (sid,))
                source, patient = b.units
                patient.hp = 499
                self.hit(b, source, patient, 1000, 1)
                self.assertFalse(patient.alive)
                self.assertEqual(patient.combo_uses.get(key, 0), 0)

    def test_expanded_low_hp_boosts_follow_blaze_template(self):
        for sid, kind, key in ((123, 'BUG', 'trait_swarm'), (214, 'FIGHTING', 'trait_cornered'),
                               (160, 'WATER', 'trait_raging_tide')):
            with self.subTest(sid=sid):
                b = self.battle((sid,), (128,))
                source, patient = b.units
                source.hp = 334
                self.assertEqual(self.hit(b, source, patient, 100, 1, kind), 100)
                source.hp = 333
                self.assertEqual(self.hit(b, source, patient, 100, 2, kind), 125)
                self.assertEqual(self.hit(b, source, patient, 100, 2.1, 'NORMAL'), 100)
                self.assertEqual(source.combo_uses[key], 1)
                event = self.effects(b, key, 'empowered_hit')[0]
                self.assertEqual(event[6]['amount'], 25)

    def test_vulnerable_boosts_require_an_active_vulnerability_window(self):
        for sid, key, expected in ((127, 'trait_crushing_grip', 112),
                                   (196, 'trait_weakness_read', 114)):  # int(100*1.15)
            with self.subTest(sid=sid):
                b = self.battle((sid,), (128,))
                source, patient = b.units
                self.assertEqual(self.hit(b, source, patient, 100, 1, 'NORMAL'), 100)
                self.assertEqual(source.combo_uses.get(key, 0), 0)
                fields.apply_vulnerability(b, patient, patient, 1)
                self.assertEqual(self.hit(b, source, patient, 100, 2, 'NORMAL'), expected)
                # 196 now spends its charge on cast-time vulnerability setup;
                # the conditional damage reward itself does not spend again.
                self.assertEqual(source.combo_uses.get(key, 0), 0 if sid == 196 else 1)
                patient.hp = 1000
                self.assertEqual(self.hit(b, source, patient, 100, 6, 'NORMAL'), 100)
                self.assertEqual(source.combo_uses.get(key, 0), 0 if sid == 196 else 1)

    def test_cast_window_opens_after_completed_native_cast_and_expires(self):
        for sid, key in ((106, 'trait_rising_kick'), (212, 'trait_sharpened_blades')):
            with self.subTest(sid=sid):
                b = self.battle((sid,), (128,))
                source, enemy = b.units
                self.assertTrue(self.cast(b, source, 1))
                self.assertEqual(source.combo_uses[key], 1)
                self.assertEqual(self.hit(b, source, enemy, 100, 1.5, 'NORMAL'), 114)
                self.assertEqual(source.combo_uses[key], 1)
                self.assertEqual(self.hit(b, source, enemy, 100, 4.5, 'NORMAL'), 100)
                rows = self.effects(b, key, 'offense_buff')
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][6]['damage_scope'], 'all')

    def test_cadence_self_heal_pulses_every_four_seconds_with_cap(self):
        for sid, key in ((80, 'trait_regenerator'),):
            with self.subTest(sid=sid):
                b = self.battle((sid,), (128,))
                source, enemy = b.units
                source.hp = 500
                traits.weather_tick(b, 3.9)
                self.assertEqual(source.hp, 500)
                traits.weather_tick(b, 4)
                self.assertEqual(source.hp, 530)
                self.assertEqual(source.combo_uses[key], 1)
                for t in (8, 12, 16, 20):
                    source.hp = 500
                    traits.weather_tick(b, t)
                self.assertEqual(source.combo_uses[key], 4)
                self.assertEqual(len(self.effects(b, key, 'heal')), 4)
                self.assertEqual(source.healing_done, 120)

    def test_native_heal_relays_shield_self_heal_or_guard_the_patient(self):
        b = self.battle((108, 127), (128,))
        source, patient, enemy = b.units
        patient.hp = 400
        self.assertTrue(self.cast(b, source, 1))
        self.assertEqual(patient.shield, 80)
        self.assertEqual(source.combo_uses['trait_soothing_lick'], 1)
        b = self.battle((113, 127), (128,))
        source, patient, enemy = b.units
        source.hp, patient.hp = 900, 400
        self.assertTrue(self.cast(b, source, 1))
        self.assertEqual(source.hp, 940)
        self.assertEqual(source.combo_uses['trait_benevolence'], 1)
        b = self.battle((154, 127), (128,))
        source, patient, enemy = b.units
        patient.hp = 400
        self.assertTrue(self.cast(b, source, 1))
        self.assertEqual((patient.temp_dr, patient.temp_dr_until), (.15, 4))
        self.assertEqual(source.combo_uses['trait_lingering_aroma'], 1)
        self.assertFalse(self.effects(b, 'trait_healer'))

    def test_keen_eye_reuses_compound_eyes_dodge_roll(self):
        b = self.battle((162,), (128,))
        source, target = b.units
        target.item_dodge = .5
        with patch.object(b.rng, 'random', return_value=.3):
            self.basic(b, source, target, 1, 100)
        self.assertEqual(target.hp, 900)
        self.assertEqual(source.combo_uses['trait_keen_eye'], 1)
        target.item_dodge = .5
        with patch.object(b.rng, 'random', return_value=.1):
            self.basic(b, source, target, 4, 100)
        self.assertEqual(target.hp, 900)
        self.assertEqual(source.combo_uses['trait_keen_eye'], 1)

    def test_classic_battle_ignores_expanded_traits(self):
        b = self.battle((123, 80), (95, 248), ruleset='base_v1')
        source, regenerator, core, unnerve = b.units
        self.assertFalse(any(e[1] == 'combo_effect' and e[4].startswith('trait_')
                             for e in b.events))
        self.assertEqual(unnerve.trait_weaken_fraction, 0)
        source.hp = 300
        self.assertEqual(self.hit(b, source, core, 100, 1, 'BUG'), 100)
        traits.weather_tick(b, 4)
        self.assertEqual(regenerator.hp, 1000)
        self.assertFalse(any(u.combo_uses for u in b.units))


if __name__ == '__main__':
    unittest.main()
