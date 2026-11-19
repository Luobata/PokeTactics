"""arena_v2 mechanic items: recipes, retirement, battle effects and the item advisor."""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / 'sim', ROOT / 'tools' / 'acceptance', ROOT / 'tools' / 'mockups'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import arena  # noqa: E402
import arena_families as families  # noqa: E402
import arena_mech_items as mech  # noqa: E402
import combat  # noqa: E402
import items  # noqa: E402


def piece(fid, star=2, **extra):
    p = families.make_piece(fid, star, families.FAMILIES[fid][1][0][-1])
    for key, value in extra.items():
        setattr(p, key, value)
    return p


def fight(a, b, seed=3, pa=None, pb=None, until=None, teams=None):
    battle = combat.Battle(a, b, random.Random(seed), layout='back', ruleset='arena_v2',
                           stat_mode='budget_v1', arena_teams=teams or [[], []],
                           positions_a=pa or [(c, 3) for c in range(len(a))],
                           positions_b=pb or [(c, 2) for c in range(len(b))])
    battle.run(until=until)
    return battle


def effects(battle, key):
    return [e for e in battle.events if e[1] == 'effect' and e[4] == key]


class RecipeTest(unittest.TestCase):
    def test_numeric_pairs_craft_mechanic_items_only_in_v2(self):
        pairs = {('band', 'magnet'): 'boomerang', ('shoes', 'shoes'): 'impact_gauntlet',
                 ('magnet', 'bell'): 'echo_bell', ('charcoal', 'magnet'): 'flame_orb',
                 ('mysticwater', 'magnet'): 'toxic_orb', ('spark', 'spark'): 'static_glove',
                 ('hardstone', 'hardstone'): 'taunt_bell', ('hardstone', 'shoes'): 'red_card'}
        for pair, key in pairs.items():
            self.assertEqual(items.craft_result(*pair, ruleset='arena_v2'), key)
            self.assertNotIn(key, items.catalog('arena_v1'))
        self.assertEqual(items.craft_result('band', 'magnet', ruleset='arena_v1'), 'choice_band')

    def test_retired_items_stay_loadable_but_never_drop_or_craft(self):
        inventory = items.Inventory('arena_v2')
        inventory.add_component('band')
        inventory.add_component('magnet')
        self.assertIsNone(inventory.craftable('choice_band'))
        self.assertEqual(inventory.craftable('boomerang'), ('band', 'magnet'))
        self.assertIn('choice_band', items.catalog('arena_v2'))
        self.assertNotIn('choice_band', items.obtainable('arena_v2'))
        for key in mech.TREASURES:
            self.assertIn(key, items.obtainable('arena_v2'))
            self.assertIsNone(inventory.craftable(key))


class EffectTest(unittest.TestCase):
    def test_orbs_apply_their_status(self):
        b = fight([(piece(66), 'flame_orb')], [piece(74)], until=12)
        self.assertTrue(effects(b, 'flame_orb'))
        b = fight([(piece(66), 'toxic_orb')], [piece(74)], until=12)
        self.assertTrue(effects(b, 'toxic_orb'))

    def test_impact_gauntlet_knocks_back(self):
        b = fight([(piece(66), 'impact_gauntlet')], [piece(74, 3)], until=15, pa=[(2, 3)], pb=[(2, 2)])
        self.assertTrue(effects(b, 'impact_gauntlet'))

    def test_taunt_bell_taunts_nearby_enemies_at_start(self):
        b = fight([(piece(74), 'taunt_bell'), piece(4)], [piece(66), piece(29)], until=.5)
        rows = effects(b, 'taunt_bell')
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(rows[0][5]['value'], 1)

    def test_boomerang_hits_a_second_target(self):
        b = fight([(piece(4), 'boomerang')], [piece(66), piece(29)], until=12, pa=[(2, 3)], pb=[(2, 2), (3, 2)])
        self.assertTrue(effects(b, 'boomerang'))

    def test_revival_seed_saves_an_adjacent_ally_once(self):
        b = fight([(piece(1), 'revival_seed'), piece(10, 1)], [piece(147, 3), piece(4, 3)], pa=[(2, 3), (3, 3)])
        self.assertLessEqual(len(effects(b, 'revival_seed')), 1)

    def test_depth_battles_with_mech_items_are_deterministic(self):
        def run():
            b = fight([(piece(66), 'impact_gauntlet'), (piece(4), 'boomerang'), (piece(74), 'taunt_bell')],
                      [(piece(29), 'red_card'), (piece(92), 'echo_bell'), (piece(43), 'rally_whistle')], seed=9)
            return repr(b.events)
        self.assertEqual(run(), run())


class AdvisorTest(unittest.TestCase):
    def test_advice_lists_actionable_suggestions_and_every_item_has_a_guide(self):
        import demo
        s = demo._new_session(77, {'mode': 'arena'})
        for reward in list(s.arena_augments_pending):
            arena.claim_augment(s, reward['id'], reward['options'][0]['id'])
        p = s.player
        for i in range(5):
            if p.shop.slots[i] is not None and p.gold >= p.shop.price(i):
                demo.act_buy(s, i)
        demo.act_move(s, 'b0', 'g0,0')
        p.inventory.finished.append('flame_orb')
        advice = demo.state_json(s, lite=True)['interactions']['item_advice']
        self.assertTrue(advice['suggestions'])
        self.assertTrue(any(row['action'] == 'equip' and row['item'] == 'flame_orb' for row in advice['suggestions']))
        for row in advice['suggestions']:
            self.assertIn(row['action'], ('equip', 'craft', 'chase'))
            self.assertTrue(row['why'])
        for key in items.obtainable('arena_v2'):
            self.assertIn(key, advice['guides'])
            self.assertIn(advice['guides'][key]['archetype'], mech.ARCHETYPES)
        self.assertNotIn('choice_band', advice['guides'])


if __name__ == '__main__':
    unittest.main()
