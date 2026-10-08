"""New machines change authoritative HP, obey immunities, and are finite."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sim'))
import arena
import techniques
from combat import Battle
from arena_teaching import after_basic


class ArenaTeaching(unittest.TestCase):
    @staticmethod
    def sides(battle):
        return tuple(next(u for u in battle.units if u.team == team) for team in (0, 1))

    def battle(self, source, target, key):
        templates = arena.build_templates()
        return Battle([templates[source]], [templates[target]], random.Random(8),
                      ruleset='arena_v1', stat_mode='budget_v1', learned_a=[key])

    def test_electric_followup_deals_real_damage_once_and_ground_is_immune(self):
        for target, immune in ((9, False), (76, True)):
            b = self.battle(26, target, 'thunderbolt')
            source, enemy = self.sides(b)
            old_hp = enemy.hp
            after_basic(b, source, enemy, 0.5)
            self.assertEqual(enemy.hp, old_hp) if immune else self.assertLess(enemy.hp, old_hp)
            once = list(b.events)
            after_basic(b, source, enemy, 1.0)
            self.assertEqual(b.events, once)
            self.assertTrue(source.technique_used)
            cast = next(e for e in b.events if e[1] == 'cast')
            self.assertEqual(cast[4], 'thunderbolt')
            self.assertEqual(cast[6], 0) if immune else self.assertGreater(cast[6], 0)

    def test_ground_followup_cannot_damage_flying(self):
        b = self.battle(76, 12, 'earthquake')
        source, enemy = self.sides(b)
        before = enemy.hp
        after_basic(b, source, enemy, 0.5)
        self.assertEqual(enemy.hp, before)
        self.assertEqual(next(e[6] for e in b.events if e[1] == 'cast'), 0)

    def test_new_catalog_is_arena_only_and_machine_learning_spends_no_gold(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/acceptance'))
        import demo
        s = demo.Session(7, 'arena_v1'); s.begin_round(1)
        s.pool.take(26)
        s.player.bench.append(demo.shop_mod.OwnedPiece(s.templates[26], 1))
        s.player.gold = 0
        s.player.inventory.techniques['thunderbolt'] = 1
        arena.learn(s, 'b0', 'thunderbolt')
        self.assertEqual(s.player.gold, 0)
        self.assertEqual(s.player.inventory.techniques['thunderbolt'], 0)
        self.assertEqual(s.player.bench[0].technique, 'thunderbolt')
        with self.assertRaises(ValueError): arena.learn(s, 'b0', 'ice_beam')
        self.assertEqual(len(techniques.ids_for('arena_v1')), 12)
        self.assertNotIn('ice_beam', techniques.ids_for('base_v1'))

    def test_real_battle_hook_uses_ice_machine_and_lethal_targets_get_no_extra_hit(self):
        b = self.battle(9, 59, 'ice_beam')
        b.run()
        source, _ = self.sides(b)
        self.assertTrue(source.technique_used)
        self.assertTrue(any(e[1] == 'cast' and e[2] == source.idx and e[4] == 'ice_beam' for e in b.events))
        dead = self.battle(9, 59, 'ice_beam')
        source, enemy = self.sides(dead)
        enemy.hp = 0
        before = list(dead.events)
        after_basic(dead, source, enemy, 1.0)
        self.assertEqual(dead.events, before)
        self.assertFalse(source.technique_used)


if __name__ == '__main__': unittest.main()
