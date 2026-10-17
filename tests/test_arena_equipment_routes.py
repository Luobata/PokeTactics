"""New recipes must produce real, bounded combat choices without recursive aid."""
import copy
import random
import sys
import unittest
from itertools import combinations_with_replacement
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sim'))
import arena
import arena_combinations as combinations
import arena_equipment as equipment
import arena_fields as fields
import arena_families as families
import arena_skills
import items
import status
from combat import Battle
from data import ENERGY_MAX
from bots import Bot
from shop import OwnedPiece, SharedPool


class ArenaEquipmentRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = arena.build_templates()

    def battle(self, friends=(127,), enemies=(128,), equipped=(), enemy_items=()):
        own, hostile = dict(equipped), dict(enemy_items)
        def comp(ids, mapping):
            return [(copy.copy(self.templates[sid]), mapping[i]) if i in mapping
                    else copy.copy(self.templates[sid]) for i, sid in enumerate(ids)]
        battle = Battle(comp(friends, own), comp(enemies, hostile), random.Random(651),
                        ruleset='arena_v1', stat_mode='budget_v1', arena_teams=[[], []],
                        positions_a=[(2, 3), (1, 3), (3, 3), (2, 4)][:len(friends)],
                        positions_b=[(2, 2), (3, 2), (1, 2)][:len(enemies)])
        for unit in battle.units:
            unit.max_hp = unit.hp = 1000
            unit.energy = 0
        return battle

    @staticmethod
    def effects(battle, key, effect=None):
        return [row for row in battle.events if row[1] == 'combo_effect' and row[4] == key
                and (effect is None or row[5] == effect)]

    def basic(self, battle, unit, target, t, raw=100):
        battle.duration, unit.energy = t, 0
        with patch('combat._damage', return_value=raw), patch.object(status, 'on_hit'), \
                patch.object(battle, '_final_damage', side_effect=lambda a, b, m, damage: damage):
            battle._strike(unit, target, t)

    def cast(self, battle, unit, t):
        battle.duration, unit.energy = t, ENERGY_MAX
        target = next(u for u in battle.units if u.team != unit.team and u.alive)
        with patch('combat._damage', return_value=50), patch.object(status, 'on_hit'):
            return arena_skills.cast(battle, unit, target, t)

    def test_recipes_expand_both_sparse_components_without_changing_classic(self):
        catalog = items.catalog('arena_v1')
        self.assertEqual(len(catalog), 30)
        valid = [(a, b, items.craft_result(a, b, 'arena_v1'))
                 for a, b in combinations_with_replacement(items.COMPONENT_ORDER, 2)
                 if items.craft_result(a, b, 'arena_v1') in catalog]
        self.assertEqual(len(valid), 32)
        for component, expected in (('mysticwater', 7), ('spark', 6)):
            self.assertEqual(len({key for a, b, key in valid if component in (a, b)}), expected)
        new = {'drain_fang', 'tide_shell', 'dew_charm', 'torrent_orb', 'pulse_band',
               'relay_coil', 'grounding_cloak', 'storm_chime',
               'life_orb', 'damp_rock', 'heat_rock', 'heart_bell', 'ward_bracer',
               'clarity_charm', 'contagion_orb', 'metronome', 'heavy_boots',
               'trap_lens'}
        self.assertTrue(new <= catalog.keys())
        self.assertTrue(new.isdisjoint(items.catalog()))
        for key in new:
            inv = items.Inventory('arena_v1')
            for component in catalog[key]['pairs'][0]:
                inv.add_component(component)
            pair = inv.craftable(key)
            self.assertIsNotNone(pair)
            inv.craft(key, pair)
            self.assertEqual(inv.total_components(), 0)
            self.assertEqual(inv.finished, [key])
            self.assertIsNone(items.Inventory().craftable(key))

    def test_conditional_energy_items_do_not_add_passive_energy_multiplier(self):
        for key in ('torrent_orb', 'pulse_band', 'storm_chime'):
            unit = self.battle(equipped=[(0, key)]).units[0]
            self.assertEqual(unit.item_energy, 0)

    def test_bot_assigns_native_equipment_only_to_a_capable_free_carrier(self):
        attacker = OwnedPiece(copy.copy(self.templates[127]), 2)
        healer = OwnedPiece(copy.copy(self.templates[40]), 1)
        battery = OwnedPiece(copy.copy(self.templates[171]), 1)
        dummy = SimpleNamespace(inventory=items.Inventory('arena_v1'),
                                all_pieces=lambda: [attacker, healer, battery])
        self.assertIs(Bot._item_target(dummy, 'relay_coil'), battery)
        self.assertIs(Bot._item_target(dummy, 'dew_charm'), healer)
        self.assertIs(Bot._item_target(dummy, 'torrent_orb'), attacker)
        self.assertIsNone(Bot._item_target(dummy, 'storm_chime'))
        attacker.technique = 'roar'
        self.assertIs(Bot._item_target(dummy, 'storm_chime'), attacker)
        battery.item = 'focus_lens'
        self.assertIsNone(Bot._item_target(dummy, 'relay_coil'))

    def test_craft_order_covers_every_arena_only_equipment(self):
        catalog = items.catalog('arena_v1')
        expected = {key for key, spec in catalog.items() if spec.get('arena_only')}
        self.assertEqual(set(equipment.CRAFT_ORDER), expected)
        self.assertEqual(len(equipment.CRAFT_ORDER), len(expected))

    def test_bot_assigns_early_arena_equipment_to_capable_carriers(self):
        healer = OwnedPiece(copy.copy(self.templates[40]), 1)
        defender = OwnedPiece(copy.copy(self.templates[128]), 2)
        cleanser = OwnedPiece(copy.copy(self.templates[12]), 1)
        poisoner = OwnedPiece(copy.copy(self.templates[34]), 2)
        attacker = OwnedPiece(copy.copy(self.templates[127]), 2)
        rocker = OwnedPiece(copy.copy(self.templates[95]), 2)
        toxic_learner = OwnedPiece(copy.copy(self.templates[127]), 1)
        toxic_learner.technique = 'toxic'
        trap_learner = OwnedPiece(copy.copy(self.templates[34]), 1)
        trap_learner.technique = 'stealth_rock'
        dummy = SimpleNamespace(inventory=items.Inventory('arena_v1'),
                                all_pieces=lambda: [healer, defender, cleanser,
                                                     poisoner, attacker, rocker,
                                                     toxic_learner, trap_learner])
        assignments = {
            'heart_bell': healer,
            'ward_bracer': defender,
            'clarity_charm': cleanser,
            'contagion_orb': poisoner,
            'metronome': attacker,
            'heavy_boots': defender,
            'trap_lens': rocker,
        }
        for key, expected_target in assignments.items():
            self.assertIs(Bot._item_target(dummy, key), expected_target, key)
        self.assertEqual(equipment.carrier_rank(toxic_learner, 'contagion_orb'), 2)
        self.assertEqual(equipment.carrier_rank(trap_learner, 'trap_lens'), 2)
        sheer_force = OwnedPiece(copy.copy(self.templates[34]), 2)
        sheer_force.arena_trait = 'trait_sheer_force'
        flareon = OwnedPiece(families.make_piece(133, 2, 136), 2)
        self.assertIsNone(equipment.carrier_rank(sheer_force, 'contagion_orb'))
        self.assertEqual(equipment.carrier_rank(flareon, 'contagion_orb'), 2)
        dummy.all_pieces = lambda: [sheer_force, flareon, poisoner]
        self.assertIs(Bot._item_target(dummy, 'contagion_orb'), poisoner)
        dummy.all_pieces = lambda: [sheer_force, flareon]
        self.assertIs(Bot._item_target(dummy, 'contagion_orb'), flareon)

    def test_contagion_orb_spreads_flareon_owned_burn(self):
        self.templates[136] = families.make_piece(133, 2, 136)
        b = self.battle(friends=(136,), enemies=(128, 40),
                        equipped=[(0, 'contagion_orb')])
        source, patient, recipient = b.units
        self.assertTrue(self.cast(b, source, 0))
        self.assertEqual(patient._st.debuff, 'burn')
        self.assertEqual(patient._st.debuff_source_idx, source.idx)
        for t in (1., 2., 3.):
            b.duration = t
            status.tick(b, t)
        spread, = self.effects(b, 'contagion_orb', 'spread')
        self.assertEqual((spread[2], spread[3]), (source.idx, recipient.idx))
        self.assertEqual((recipient._st.debuff, recipient._st.debuff_source_idx),
                         ('burn', source.idx))
        self.assertFalse(recipient._st.debuff_spreadable)

    def test_bot_crafts_and_equips_every_early_arena_recipe(self):
        bot = Bot(0, 3, 'balanced', SharedPool(self.templates), self.templates)
        bot.inventory = items.Inventory('arena_v1')
        bot.board = [
            OwnedPiece(copy.copy(self.templates[40]), 1),
            OwnedPiece(copy.copy(self.templates[31]), 2),
            OwnedPiece(copy.copy(self.templates[12]), 1),
            OwnedPiece(copy.copy(self.templates[34]), 2),
            OwnedPiece(copy.copy(self.templates[127]), 2),
            OwnedPiece(copy.copy(self.templates[128]), 2),
            OwnedPiece(copy.copy(self.templates[95]), 2),
        ]
        expected = {
            'heart_bell': 40, 'ward_bracer': 31, 'clarity_charm': 12,
            'contagion_orb': 34, 'metronome': 127, 'heavy_boots': 128,
            'trap_lens': 95,
        }
        for key, carrier_sid in expected.items():
            for component in items.catalog('arena_v1')[key]['pairs'][0]:
                bot.inventory.add_component(component)

            bot._items_pass(1, [])

            carrier = next(owned for owned in bot.board
                           if owned.piece.species_id == carrier_sid)
            self.assertEqual(carrier.item, key)
        self.assertEqual(bot.inventory.finished, [])
        self.assertEqual(bot.inventory.total_components(), 0)
        self.assertEqual({owned.item: owned.piece.species_id for owned in bot.board},
                         expected)
        self.assertEqual(bot.item_crafts, len(expected))
        self.assertEqual(bot.item_equips, len(expected))

    def test_lifesteal_uses_actual_hp_loss_and_records_one_real_heal(self):
        b = self.battle(equipped=[(0, 'drain_fang')])
        source, target = b.units
        source.hp = 500
        self.basic(b, source, target, 1, 100)
        self.assertEqual((source.hp, source.healing_done, source.self_healing), (515, 15, 15))
        row = self.effects(b, 'drain_fang', 'heal')[0]
        self.assertEqual(row[6]['amount'], 15)
        nested = b.events[b.events.index(row) + 1:b.events.index(row) + 1 + row[6]['event_count']]
        self.assertEqual(sum(e[3] for e in nested if e[1] == 'regen'), 15)
        self.basic(b, source, target, 1.5, 100)
        self.assertEqual(source.hp, 515)
        target.hp = 10
        self.basic(b, source, target, 2, 100)
        self.assertEqual(source.hp, 516)  # overkill is not lifesteal damage

    def test_lifesteal_rejects_full_absorption_full_health_and_respects_antiheal(self):
        b = self.battle(equipped=[(0, 'drain_fang')])
        source, target = b.units
        self.basic(b, source, target, 0, 100)
        self.assertEqual(source.combo_uses.get('drain_fang', 0), 0)
        source.hp = 500
        combinations.grant_shield(b, target, target, 100, 1, None)
        self.basic(b, source, target, 1, 100)
        self.assertEqual(source.hp, 500)
        source.healing_blocks.append({'source': target.idx, 'fraction': .5, 'expires_at': 9.})
        self.basic(b, source, target, 2, 100)
        self.assertEqual(source.hp, 507)
        self.assertEqual(self.effects(b, 'drain_fang', 'heal')[-1][6]['amount'], 7)

    def test_pulse_counts_actual_basics_across_targets_and_stops_at_cap(self):
        b = self.battle(enemies=(128, 195), equipped=[(0, 'pulse_band')])
        source, first, second = b.units
        source.range = 3
        for i in range(24):
            self.basic(b, source, first if i % 2 else second, i * 2., 1)
        rows = self.effects(b, 'pulse_band', 'energy')
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row[6]['amount'] == 10 for row in rows))
        self.assertEqual(source.combo_uses['pulse_band'], 6)

    def test_pulse_full_energy_defers_receipt_until_another_real_basic(self):
        b = self.battle(equipped=[(0, 'pulse_band')])
        source, target = b.units
        source.pulse_hits = 2
        source.energy = ENERGY_MAX - 1
        with patch('combat._damage', return_value=10), patch.object(status, 'on_hit'):
            b._strike(source, target, 1)
        self.assertEqual(source.energy, ENERGY_MAX)
        self.assertEqual(source.pulse_hits, 3)
        self.assertFalse(self.effects(b, 'pulse_band'))
        self.basic(b, source, target, 2, 1)
        self.assertEqual(self.effects(b, 'pulse_band', 'energy')[-1][6]['amount'], 10)
        self.assertEqual(source.pulse_hits, 0)

    def test_torrent_refunds_only_native_primary_damage_and_caps(self):
        b = self.battle(friends=(26,), equipped=[(0, 'torrent_orb')])
        source, target = b.units
        for t in (1., 6., 11., 16., 21.):
            self.assertTrue(self.cast(b, source, t))
        rows = self.effects(b, 'torrent_orb', 'energy')
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row[6]['amount'] == 16 for row in rows))
        self.assertEqual(source.energy, 0)
        for row in rows:
            self.assertEqual(b.events[row[6]['cast_index']][4], 'arena_' + source.ult_arch)

    def test_torrent_does_not_refund_native_hit_fully_absorbed_by_shield(self):
        b = self.battle(friends=(26,), equipped=[(0, 'torrent_orb')])
        source, target = b.units
        combinations.grant_shield(b, target, target, 999, 1, None)
        self.cast(b, source, 1)
        self.assertFalse(self.effects(b, 'torrent_orb'))
        self.assertEqual(source.energy, 0)

    def test_dew_heals_a_different_wounded_ally_and_does_not_recurse(self):
        b = self.battle(friends=(40, 128, 195), equipped=[(0, 'dew_charm')])
        source, patient, other, enemy = b.units
        patient.hp, other.hp = 100, 400
        self.assertTrue(self.cast(b, source, 1))
        rows = self.effects(b, 'dew_charm', 'heal')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][3], rows[0][6]['origin_idx'], rows[0][6]['amount']),
                         (other.idx, patient.idx, 60))
        self.assertEqual(source.combo_uses['dew_charm'], 1)
        self.assertEqual(source.healing_done, sum(e[3] for e in b.events if e[1] == 'regen'))
        self.assertEqual(source.self_healing, 0)

    def test_dew_needs_another_patient_and_real_threshold(self):
        b = self.battle(friends=(40, 128), equipped=[(0, 'dew_charm')])
        source, patient, enemy = b.units
        source.hp, patient.hp = 100, 200
        self.cast(b, source, 1)
        self.assertFalse(self.effects(b, 'dew_charm'))
        self.assertEqual(source.combo_uses.get('dew_charm', 0), 0)

    def test_relay_shield_requires_actual_other_native_energy_and_preserves_stronger(self):
        b = self.battle(friends=(121, 128), equipped=[(0, 'relay_coil')])
        source, patient, enemy = b.units
        self.cast(b, source, 1)
        self.assertEqual(patient.shield, 80)
        self.assertEqual(len(self.effects(b, 'relay_coil', 'shield')), 1)
        combinations.grant_shield(b, patient, patient, 200, 6, None)
        patient.energy = 0
        self.cast(b, source, 6)
        self.assertEqual(patient.shield, 200)
        self.assertEqual(source.combo_uses['relay_coil'], 1)
        patient.energy = ENERGY_MAX
        self.assertFalse(self.cast(b, source, 11))
        self.assertEqual(source.combo_uses['relay_coil'], 1)

    def test_knockback_items_use_real_motion_and_distinct_owner_ledgers(self):
        b = self.battle(friends=(127, 195), equipped=[(0, 'storm_chime')],
                        enemy_items=[(0, 'tide_shell')])
        source, ally, target = b.units
        self.assertTrue(fields.move_unit(b, target, (2, 1), 1, source=source, reason='knockback'))
        self.assertEqual((ally.energy, target.shield), (8, 100))
        self.assertFalse(fields.move_unit(b, target, (2, 1), 7, source=source, reason='knockback'))
        self.assertEqual((source.combo_uses['storm_chime'], target.combo_uses['tide_shell']), (1, 1))
        self.assertTrue(fields.move_unit(b, target, (2, 0), 7, source=source, reason='move'))
        self.assertEqual(source.combo_uses['storm_chime'], 1)

    def test_displacement_shield_cannot_save_a_terrain_death(self):
        b = self.battle(friends=(127, 195), equipped=[(0, 'storm_chime')],
                        enemy_items=[(0, 'tide_shell')])
        source, ally, target = b.units
        field = fields.place_rocks(b, source, target, 1)
        destination = next(cell for cell in field['cells'] if cell != target.pos)
        target.hp = 1
        self.assertTrue(fields.move_unit(b, target, destination, 1, source=source, reason='knockback'))
        self.assertFalse(target.alive)
        self.assertFalse(self.effects(b, 'tide_shell'))
        self.assertFalse(self.effects(b, 'storm_chime'))

    def test_cloak_cleanses_only_first_real_control_and_keeps_dr_and_flinch(self):
        b = self.battle(equipped=[(0, 'grounding_cloak')])
        wearer, enemy = b.units
        self.assertTrue(status.apply_flinch(b, wearer, 1))
        self.assertTrue(status.apply_debuff(b, wearer, 'sleep', 1, source=enemy))
        self.assertIsNone(wearer._st.debuff)
        self.assertTrue(status.stunned(wearer, 1.1))
        self.assertFalse(status.stunned(wearer, 1.4))
        self.assertGreater(wearer._st.ctrl_until, 1)
        self.assertFalse(status.apply_debuff(b, wearer, 'freeze', 2, source=enemy))
        self.assertEqual(wearer.combo_uses['grounding_cloak'], 1)
        self.assertTrue(status.apply_debuff(b, wearer, 'sleep', 7, source=enemy))
        self.assertEqual(wearer._st.debuff, 'sleep')
        self.assertEqual(len(self.effects(b, 'grounding_cloak', 'cleanse')), 1)

    def test_cloak_does_not_consume_on_poison_or_type_immunity(self):
        b = self.battle(friends=(26,), equipped=[(0, 'grounding_cloak')])
        wearer, enemy = b.units
        self.assertFalse(status.apply_debuff(b, wearer, 'para', 1, source=enemy))
        self.assertTrue(status.apply_debuff(b, wearer, 'poison', 2, source=enemy))
        self.assertEqual(wearer._st.debuff, 'poison')
        self.assertEqual(wearer.combo_uses.get('grounding_cloak', 0), 0)


if __name__ == '__main__':
    unittest.main()
