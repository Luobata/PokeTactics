"""arena_v2 depth edition: rules, determinism, session actions and save round trips."""
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / 'sim', ROOT / 'tools' / 'acceptance', ROOT / 'tools' / 'mockups'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import arena  # noqa: E402
import arena_depth  # noqa: E402
import arena_families as families  # noqa: E402
import arena_session  # noqa: E402
import combat  # noqa: E402
import items  # noqa: E402


def piece(fid, star=1, **extra):
    p = families.make_piece(fid, star, families.FAMILIES[fid][1][0][-1])
    for key, value in extra.items():
        setattr(p, key, value)
    return p


def battle(a, b, seed=1, teams=None, terrain=None, pa=None, pb=None):
    return combat.Battle(a, b, random.Random(seed), layout='back', ruleset='arena_v2',
                         stat_mode='budget_v1', arena_teams=teams or [[], []],
                         arena_terrain=terrain,
                         positions_a=pa or [(c, 4) for c in range(len(a))],
                         positions_b=pb or [(c, 1) for c in range(len(b))])


def effects(b, key=None):
    return [e for e in b.events if e[1] == 'effect' and (key is None or e[4] == key)]


class StatCurveTest(unittest.TestCase):
    def test_two_star_low_cost_beats_one_star_high_cost_panel(self):
        low = battle([piece(66, 2)], [piece(1)]).units[0]
        high = battle([piece(63, 1)], [piece(1)]).units[0]
        self.assertGreater(low.max_hp, high.max_hp)

    def test_v1_ruleset_rejects_terrain(self):
        with self.assertRaises(ValueError):
            combat.Battle([piece(66)], [piece(1)], random.Random(1), ruleset='arena_v1',
                          stat_mode='budget_v1', arena_terrain='swamp')


class EffectTest(unittest.TestCase):
    def test_charge_horn_moves_melee_and_shields(self):
        b = battle([piece(66, 2), piece(66, 1)], [piece(1), piece(1)],
                   teams=[['charge_horn'], []])
        start = [u.pos for u in b.units if u.team == 0]
        b.run()
        rows = [e for e in effects(b, 'charge_horn') if e[5]['kind'] != 'move']
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0][5]['value'], 0)
        leaps = [e for e in effects(b, 'charge_horn') if e[5]['kind'] == 'move']
        self.assertTrue(leaps)
        self.assertEqual(leaps[0][0], 0.0)

    def test_undying_saves_first_lethal_once(self):
        b = battle([piece(10)], [piece(147, 3), piece(4, 3)], teams=[['undying'], []])
        b.run()
        self.assertEqual(len(effects(b, 'undying')), 1)

    def test_skill_mod_fortify_shields_after_cast(self):
        b = battle([piece(74, 2, skill_mods=('fortify',))], [piece(7)], teams=[['mana_flow'], []])
        b.run()
        self.assertTrue(effects(b, 'fortify'))

    def test_core_and_resonance_raise_bond_counts(self):
        b = battle([piece(74, 2, is_core=True), piece(246, 2)], [piece(1)],
                   teams=[['bond_resonance'], []])
        counts = b.depth_bond_counts[0]
        self.assertGreaterEqual(counts.get('ROCK', 0), 4)
        self.assertIn('rock_bulwark', b.units[0].depth_rules)

    def test_terrain_spring_grants_energy_and_ledger(self):
        b = battle([piece(1, 2), piece(7, 2)], [piece(66, 2)], terrain='mana_spring',
                   pa=[(2, 3), (3, 3)], pb=[(2, 2)])
        b.run()
        rows = {(r['source'], r['id']): r for r in b.fx.ledger.view(0)}
        self.assertGreater(rows[('terrain', 'mana_spring')]['energy'], 0)

    def test_second_item_stacks_with_primary(self):
        b = battle([(piece(4, 2, is_core=True, extra_item='swift_feather'), 'choice_band')], [piece(1)])
        unit = b.units[0]
        self.assertEqual((unit.item_key, unit.extra_item_key), ('choice_band', 'swift_feather'))

    def test_depth_battles_are_deterministic(self):
        def run():
            b = battle([piece(4, 3, skill_mods=('spread', 'execute')), piece(74, 2, skill_mods=('quake',))],
                       [piece(66, 2), piece(29, 3, skill_mods=('fortify', 'retaliate'))],
                       seed=7, teams=[['executioner', 'chain_reaction'], ['vanguard']], terrain='embers')
            b.run()
            return repr(b.events)
        self.assertEqual(run(), run())


class EarlyFormKitTest(unittest.TestCase):
    def test_generic_strike_forms_borrow_final_kit_in_v2_only(self):
        import arena_skills
        charmander = piece(4)
        self.assertTrue(arena_skills.skill_of(4)['id'].startswith('family_strike_'))
        v2 = battle([charmander], [piece(1)]).units[0]
        self.assertEqual(v2.ult_arch, arena_skills.skill_of(6)['arch'])
        v1 = combat.Battle([charmander], [piece(1)], random.Random(1), ruleset='arena_v1',
                           stat_mode='budget_v1').units[0]
        self.assertTrue(v1.ult_arch.startswith('family_strike_'))


class CatalogTest(unittest.TestCase):
    def test_dead_component_pairs_craft_only_in_v2(self):
        for pair, key in ((('magnet', 'magnet'), 'mind_crystal'), (('magnet', 'shoes'), 'quick_claw'),
                          (('mysticwater', 'shoes'), 'escape_pack'), (('charcoal', 'spark'), 'blast_core')):
            self.assertEqual(items.craft_result(*pair, ruleset='arena_v2'), key)
            self.assertNotIn(key, items.catalog('arena_v1'))

    def test_finished_items_carry_component_stats(self):
        self.assertEqual(arena_depth.item_stats('choice_band'), {'atk': .08, 'ult': .10})

    def test_v2_pool_drops_flat_panels_and_adds_rules(self):
        class S:
            ruleset = 'arena_v2'
            player = object()
        class Seat:
            arena_augments_selected = []
        pool = arena.augment_pool(S, Seat)
        self.assertNotIn('sharp_focus', pool)
        self.assertIn('dual_wield', pool)

    def test_mod_choices_are_role_specific(self):
        self.assertEqual(arena_depth.mod_options('defense', 2), ('fortify', 'quake'))
        self.assertEqual(arena_depth.mod_options('support', 3), ('sanctify', 'amplify'))


class SessionTest(unittest.TestCase):
    def setUp(self):
        import demo
        self.demo = demo
        self.patches = [patch.object(demo, 'DEFER_RENDER', False),
                        patch.object(demo, '_render_battle_frames',
                                     side_effect=lambda *a, **k: demo._prepare_battle_frames(*a, **k)[0])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def new(self, seed=4242):
        s = self.demo._new_session(seed, {'mode': 'arena'})
        self.assertEqual(s.ruleset, 'arena_v2')
        for reward in list(s.arena_augments_pending):
            arena.claim_augment(s, reward['id'], reward['options'][0]['id'])
        return s

    def test_new_arena_defaults_to_v2_and_v1_is_opt_in(self):
        self.assertEqual(self.demo._new_session(1, {'mode': 'arena', 'edition': 'v1'}).ruleset, 'arena_v1')
        state = self.demo.state_json(self.new())
        self.assertIn('terrain', state['depth'])
        self.assertEqual(state['arena']['version'], 'arena_v2')

    def test_merge_keeps_the_deployed_cell(self):
        s = self.new()
        p = s.player
        from shop import OwnedPiece
        copies = [OwnedPiece(piece(66), 1) for _ in range(3)]
        for owned in copies:
            s.pool.take(66)
        p.grid[(0, 2)] = copies[0]
        p.bench.extend(copies[1:])
        s.combine_player()
        self.assertIn((0, 2), p.grid)
        self.assertEqual(p.grid[(0, 2)].piece.star, 2)

    def test_dismantle_sell_core_and_mod_actions(self):
        s = self.new()
        p = s.player
        p.gold = 20
        p.inventory.finished.extend(['choice_band', 'leftovers'])
        self.assertIn('取回', self.demo.act_dismantle(s, 'choice_band'))
        self.assertEqual((p.inventory.components['band'], p.inventory.components['magnet']), (2, 2))
        self.assertIn('+2', self.demo.act_sell_item(s, 'leftovers'))
        from shop import OwnedPiece
        owned = OwnedPiece(piece(66, 2), 3)
        owned.sources = [66] * 3
        for _ in range(3):
            s.pool.take(66)
        p.grid[(0, 0)] = owned
        self.assertIn('核心', self.demo.act_core(s, 'g0,0'))
        option = arena_session.pending_mod_options(owned)[0]['id']
        self.demo.act_choose_mod(s, 'g0,0', option)
        self.assertEqual(owned.skill_mods, [option])
        with self.assertRaises(self.demo.DemoError):
            self.demo.act_equip(s, 'band', 'g0,0')

    def test_save_round_trip_through_draft_round(self):
        from session_save import SessionCodec
        codec = SessionCodec()
        s = self.new(77)
        for _ in range(3):
            s.end_prep()
            s.next_round()
            for reward in list(s.arena_augments_pending):
                arena.claim_augment(s, reward['id'], reward['options'][0]['id'])
        self.assertEqual(s.round_no, 4)
        self.assertEqual(s.arena_draft['status'], 'pending')
        encoded = codec.encode(s)
        self.assertEqual(codec.encode(codec.decode(encoded, 5)), encoded)
        option = next(o for o in s.arena_draft['options'] if o['taken_by'] is None)
        self.demo.act_draft(s, option['index'])
        self.assertEqual(s.arena_draft['status'], 'done')
        encoded = codec.encode(s)
        self.assertEqual(codec.encode(codec.decode(encoded, 5)), encoded)

    def test_simulation_is_bounded_and_side_effect_free(self):
        s = self.new(77)
        p = s.player
        for i in range(5):
            if p.shop.slots[i] is not None and p.gold >= p.shop.price(i):
                self.demo.act_buy(s, i)
        self.demo.act_move(s, 'b0', 'g0,0')
        gold, pool = p.gold, dict(s.pool.remaining)
        first = self.demo.act_simulate(s)
        self.assertEqual(first, self.demo.act_simulate(s))
        with self.assertRaises(self.demo.DemoError):
            self.demo.act_simulate(s)
        self.assertEqual((p.gold, s.pool.remaining), (gold, pool))

    def test_pve_waves_scale_with_stage(self):
        wave = arena_depth.scale_pve([piece(66), piece(66)], 20)
        self.assertEqual([p.star for p in wave], [3, 2])


if __name__ == '__main__':
    unittest.main()
