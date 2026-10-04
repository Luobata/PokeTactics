"""Growth preserves ancestry, pool ownership, investment and equipment."""

import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
from data import pokedex
from items import Inventory
from shop import OwnedPiece, SharedPool, build_templates, sell_owned, try_combine


class GrowthContracts(unittest.TestCase):
    def setUp(self):
        self.dex = pokedex()
        self.templates = build_templates()
        self.pool = SharedPool(self.templates)
        self.initial_pool = dict(self.pool.remaining)
        self.inventory = Inventory()

    def own(self, sid, item=None):
        self.pool.take(sid)
        owned = OwnedPiece(self.templates[sid], self.templates[sid].tier)
        owned.item = item
        return owned

    def assert_pool_conserved(self, owned):
        held = Counter(sid for piece in owned for sid in piece.sources)
        self.assertEqual({sid: n + held[sid] for sid, n in self.pool.remaining.items()},
                         self.initial_pool)

    def test_only_direct_children_are_evolutions(self):
        for sid, species in self.dex.species.items():
            expected = sorted(child for child, entry in self.dex.species.items()
                              if entry["lineage"][1:] == species["lineage"])
            with self.subTest(species=sid):
                self.assertEqual(self.dex.next_evolution(sid), expected[0] if expected else None)
        self.assertEqual(self.dex.next_evolution(25), 26)  # 外部宝宝祖先仍兼容

    def test_eevee_branch_choice_is_stable(self):
        self.assertEqual(self.dex.next_evolution(133), 134)
        reversed_species = dict(reversed(list(self.dex.species.items())))
        with patch.object(self.dex, "species", reversed_species):
            self.assertEqual(self.dex.next_evolution(133), 134)
        bench = [self.own(133) for _ in range(3)]
        try_combine([], bench, self.pool, self.templates, self.inventory)
        self.assertEqual([o.piece.species_id for o in bench], [134])
        self.assert_pool_conserved(bench)

    def test_branch_leaves_do_not_merge_or_change_equipment(self):
        for sid in (134, 135, 136):
            with self.subTest(species=sid):
                bench = [self.own(sid, "choice_band") for _ in range(3)]
                before = dict(self.pool.remaining)
                self.assertEqual(try_combine([], bench, self.pool, self.templates,
                                            self.inventory), [])
                self.assertEqual(len(bench), 3)
                self.assertEqual([o.item for o in bench], ["choice_band"] * 3)
                self.assertEqual(self.pool.remaining, before)
                for piece in bench:
                    sell_owned(piece, self.pool)
        self.assertEqual(self.pool.remaining, self.initial_pool)

    def test_merge_keeps_investment_sources_and_every_item(self):
        board = [self.own(1, "choice_band")]
        bench = [self.own(1, "sash"), self.own(1, "leftovers")]
        logs = try_combine(board, bench, self.pool, self.templates, self.inventory)
        self.assertEqual(len(logs), 1)
        self.assertEqual(board, [])
        self.assertEqual(len(bench), 1)
        merged = bench[0]
        self.assertEqual(merged.piece.species_id, 2)
        self.assertEqual(merged.invested, 3)
        self.assertEqual(Counter(merged.sources), Counter({1: 3, 2: 1}))
        self.assertEqual(merged.item, "choice_band")
        self.assertCountEqual(self.inventory.finished, ["sash", "leftovers"])
        self.assert_pool_conserved(bench)
        self.assertEqual(sell_owned(merged, self.pool), 2)
        self.assertEqual(self.pool.remaining, self.initial_pool)

    def test_recursive_merge_keeps_all_nine_base_copies(self):
        bench = [self.own(1) for _ in range(9)]
        logs = try_combine([], bench, self.pool, self.templates, self.inventory)
        self.assertEqual(len(logs), 4)
        self.assertEqual(len(bench), 1)
        self.assertEqual(bench[0].piece.species_id, 3)
        self.assertEqual(bench[0].invested, 9)
        self.assertEqual(Counter(bench[0].sources), Counter({1: 9, 2: 3, 3: 1}))
        self.assert_pool_conserved(bench)

    def test_missing_destination_stock_does_not_consume_anything(self):
        bench = [self.own(1, "sash") for _ in range(3)]
        self.pool.remaining[2] = 0
        before = dict(self.pool.remaining)
        self.assertEqual(try_combine([], bench, self.pool, self.templates,
                                    self.inventory), [])
        self.assertEqual(self.pool.remaining, before)
        self.assertEqual([o.item for o in bench], ["sash"] * 3)
        self.assertEqual(self.inventory.finished, [])

    def test_no_inventory_does_not_discard_extra_items(self):
        bench = [self.own(1, "sash"), self.own(1, "leftovers"), self.own(1)]
        before = dict(self.pool.remaining)
        self.assertEqual(try_combine([], bench, self.pool, self.templates), [])
        self.assertEqual(self.pool.remaining, before)
        self.assertEqual([o.item for o in bench], ["sash", "leftovers", None])

    def test_single_item_can_merge_without_inventory(self):
        bench = [self.own(1, "sash"), self.own(1), self.own(1)]
        self.assertEqual(len(try_combine([], bench, self.pool, self.templates)), 1)
        self.assertEqual(bench[0].item, "sash")
        self.assert_pool_conserved(bench)

    def test_trade_forms_still_require_stone(self):
        bench = [self.own(64) for _ in range(3)]
        self.assertEqual(try_combine([], bench, self.pool, self.templates,
                                    self.inventory), [])
        self.assertEqual(len(bench), 3)
        self.assert_pool_conserved(bench)


if __name__ == "__main__":
    unittest.main()
