import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sim'))
import items
import techniques
from arena_rewards import roll_rewards, grant_rewards, reward_view


class RoundLoot(unittest.TestCase):
    def test_deterministic_rewards_cover_all_usable_kinds_and_actual_inventory(self):
        seen = set()
        seat = SimpleNamespace(inventory=items.Inventory('arena_v1'), item_drops=0)
        for seed in range(120):
            for result in ('win', 'loss', 'draw'):
                grants = roll_rewards(random.Random(seed), result)
                self.assertEqual(grants, roll_rewards(random.Random(seed), result))
                self.assertEqual(len(grants), 2 if result == 'win' else 1)
                before = sum(seat.inventory.components.values()) + len(seat.inventory.finished) + sum(seat.inventory.techniques.values())
                grant_rewards(seat, grants)
                after = sum(seat.inventory.components.values()) + len(seat.inventory.finished) + sum(seat.inventory.techniques.values())
                self.assertEqual(after - before, len(grants))
                for grant in grants:
                    reward_view(grant)
                    seen.add(grant['kind'])
                    self.assertNotIn(grant['key'], ('evo_stone', 'lucky_egg'))
        self.assertEqual(seen, {'component', 'item', 'technique'})
        self.assertTrue(all(seat.inventory.techniques[key] for key in techniques.ids_for('arena_v1')))

    def test_invalid_packet_is_atomic(self):
        seat = SimpleNamespace(inventory=items.Inventory('arena_v1'), item_drops=0)
        before = list(seat.inventory.finished)
        with self.assertRaises(ValueError):
            grant_rewards(seat, [{'kind': 'item', 'key': 'sash'}, {'kind': 'item', 'key': 'evo_stone'}])
        self.assertEqual(seat.inventory.finished, before)


if __name__ == '__main__': unittest.main()
