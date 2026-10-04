"""Player actions preserve resources and complete the manual game journey."""

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/acceptance"))
import demo


class DemoContracts(unittest.TestCase):
    def setUp(self):
        saves = tempfile.TemporaryDirectory()
        self.addCleanup(saves.cleanup)
        save_patch = patch.object(demo, "SAVE_ROOT", Path(saves.name))
        save_patch.start()
        self.addCleanup(save_patch.stop)
        self.session = demo.Session(7)
        self.session.round_no = 1
        self.player = self.session.player
        self.player.gold = 50

    def own(self, sid, item=None):
        self.session.pool.take(sid)
        owned = demo.shop_mod.OwnedPiece(self.session.templates[sid],
                                        self.session.templates[sid].tier)
        owned.item = item
        return owned

    def offer(self, sid):
        self.player.shop.return_all()
        self.session.pool.take(sid)
        self.player.shop.slots[0] = sid

    def snapshot(self):
        p = self.player
        return copy.deepcopy((p.gold, p.shop.slots, self.session.pool.remaining,
                              [(o.piece.species_id, o.invested, o.sources, o.item)
                               for o in p.all_pieces()],
                              p.inventory.finished, p.stone_used))

    def test_all_four_corners_reach_authoritative_renderer(self):
        for row, col in ((0, 0), (0, 5), (1, 0), (1, 5)):
            with self.subTest(row=row, col=col):
                self.player.grid = {(row, col): self.own(81)}
                with patch.object(demo, "_render_battle_frames", return_value={
                        "winner": 0, "survivors": [1, 0], "n": 1}) as render:
                    self.session._fight_rendered(1, 0, self.player, None, None,
                                                 wave=[self.session.templates[1]])
                self.assertEqual(render.call_args.kwargs["positions_a"], [(col, row + 2)])
                self.assertEqual(render.call_args.kwargs["hud_snapshot"],
                                 {"hp": 100, "gold": 50, "level": 1, "round": 1})

    def test_position_order_matches_piece_order_after_swap(self):
        a, b = self.own(81), self.own(1)
        self.player.grid = {(0, 5): a, (1, 0): b}
        demo.act_move(self.session, "g0,5", "g1,0")
        self.assertEqual(self.player.board, [a, b])
        self.assertEqual(self.player.battle_positions(), [(0, 3), (5, 2)])

    def test_enemy_and_pve_preview_use_rotated_back_formation(self):
        board = [self.own(1), self.own(4)]
        rows = self.session._enemy_rows(board)
        self.assertIs(rows[0][5], board[0])
        self.assertIs(rows[0][4], board[1])
        self.assertEqual(rows[1], [None] * 6)
        view = self.session._pve_view(5)
        self.assertEqual(view["rows"][0][5]["sid"], demo.PVE_WAVES[0][0])

    def test_l3_and_ghost_opponent_keep_the_advertised_preparation_order(self):
        sess = self.session
        opponent = sess.bots[-1]
        opponent.board = [self.own(sid) for sid in (6, 65, 143, 3, 9, 68)]
        self.player.grid = {(0, 5): self.own(81)}
        sess.pairs = [(self.player, opponent)]
        view = sess._opponent_view()
        expected = [v["sid"] for row in view["rows"] for v in reversed(row) if v]
        # 鬼影源在自己的战斗中被其他对手重新对位，也不影响已展示的快照。
        opponent.board.reverse()
        with patch.object(demo, "_render_battle_frames", return_value={
                "winner": 0, "survivors": [1, 0], "n": 1}) as render:
            sess._resolve_pvp(1, None)
        self.assertEqual([p.species_id for p in render.call_args.args[1]], expected)

    def test_human_as_bot_ghost_preserves_rotated_grid(self):
        sess = self.session
        self.player.grid = {(0, 5): self.own(81)}
        sess.pairs = []
        sess.ghost_seat, sess.ghost_src = sess.bots[0], self.player
        sess.ghost_seat.board = [self.own(1)]
        with patch.object(demo, "Battle") as battle:
            battle.return_value.run.return_value = {"winner": 0, "survivors": [1, 0]}
            sess._resolve_pvp(1, "rain")
        self.assertEqual(battle.call_args.kwargs["positions_b"], [(0, 1)])
        self.assertEqual(battle.call_args.kwargs["weather_name"], "rain")

    def test_stone_rejection_keeps_equipment_and_resources_unchanged(self):
        self.player.bench = [self.own(64, "choice_band")]
        self.player.inventory.finished = ["evo_stone"]
        before = self.snapshot()
        with self.assertRaisesRegex(demo.DemoError, "先卸下"):
            demo.act_equip(self.session, "evo_stone", "b0")
        self.assertEqual(self.snapshot(), before)
        demo.act_unequip(self.session, "b0")
        demo.act_equip(self.session, "evo_stone", "b0")
        self.assertEqual(self.player.bench[0].piece.species_id, 65)
        self.assertIn("choice_band", self.player.inventory.finished)
        self.assertTrue(self.player.stone_used)

    def test_full_bench_allows_immediate_merge(self):
        self.player.bench = [self.own(sid) for sid in (1, 1, 4, 7, 25, 81)]
        self.offer(1)
        gold = self.player.gold
        demo.act_buy(self.session, 0)
        self.assertEqual(len(self.player.bench), 5)
        self.assertEqual(self.player.gold, gold - 1)
        self.assertEqual(self.player.combines, 1)
        self.assertEqual(sum(o.piece.species_id == 2 for o in self.player.bench), 1)

    def test_full_bench_denial_is_atomic_even_when_target_pool_is_empty(self):
        self.player.bench = [self.own(sid) for sid in (1, 1, 4, 7, 25, 81)]
        self.offer(1)
        self.session.pool.remaining[2] = 0
        before = self.snapshot()
        with self.assertRaisesRegex(demo.DemoError, "备战席已满"):
            demo.act_buy(self.session, 0)
        self.assertEqual(self.snapshot(), before)

    def test_board_only_merge_cannot_overflow_full_bench(self):
        self.player.bench = [self.own(sid) for sid in (4, 7, 25, 81, 19, 10)]
        self.player.grid = {(0, 0): self.own(1), (0, 1): self.own(1)}
        self.offer(1)
        before = self.snapshot()
        with self.assertRaises(demo.DemoError):
            demo.act_buy(self.session, 0)
        self.assertEqual(self.snapshot(), before)

    def test_pool_recovery_cannot_overflow_previously_nonfull_bench(self):
        self.player.bench = [self.own(sid) for sid in (7, 25, 81, 19, 10)]
        self.player.grid = {(0, col): self.own(1) for col in range(3)}
        self.session.pool.remaining[2] = 0
        self.assertEqual(self.session.combine_player(), [])
        self.session.pool.put(2)
        self.offer(4)
        before = self.snapshot()
        with self.assertRaises(demo.DemoError):
            demo.act_buy(self.session, 0)
        self.assertEqual(self.snapshot(), before)

    def test_lock_retains_reserved_slots_and_refresh_unlocks(self):
        self.session.begin_round(1)
        self.player.shop_locked = True
        slots = list(self.player.shop.slots)
        with patch.object(self.player.shop, "roll", wraps=self.player.shop.roll) as roll:
            self.session.begin_round(2)
            roll.assert_not_called()
            self.assertEqual(self.player.shop.slots, slots)
            demo.act_refresh(self.session)
            roll.assert_called_once()
            self.assertFalse(self.player.shop_locked)

    def test_manual_elimination_can_advance_and_finish_with_persistent_result(self):
        sess = self.session
        sess.begin_round(1)
        self.player.grid = {(1, 5): self.own(81)}
        self.player.hp = 0
        sess._eliminate(self.player)
        sess.phase = "battle"
        demo.SESSIONS[sess.sid] = sess
        self.addCleanup(demo.SESSIONS.pop, sess.sid, None)
        result = demo.api_action({"cmd": "next", "sid": sess.sid})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"]["phase"], "prep")
        result = demo.api_action({"cmd": "finish", "sid": sess.sid})
        self.assertTrue(result["ok"], result)
        state = result["state"]
        self.assertEqual(state["phase"], "over")
        self.assertEqual(sorted(r["rank"] for r in state["over"]["ranking"]), list(range(1, 9)))
        self.assertEqual(state["player_result"]["team"][0]["sid"], 81)
        self.assertEqual(state["player_result"]["round"], 1)
        self.assertEqual(self.player.grid, {})

    def test_alive_player_cannot_skip_entire_game(self):
        before = self.snapshot()
        with self.assertRaises(demo.DemoError):
            self.session.finish_spectating()
        self.assertEqual(self.snapshot(), before)

    def test_new_game_accepts_reproducible_seed_or_generates_one(self):
        self.session.begin_round(1)
        self.addCleanup(demo.SESSIONS.pop, self.session.sid, None)
        created = []
        def create(seed):
            self.session.seed = seed
            created.append(seed)
            demo.SESSIONS[self.session.sid] = self.session
            return self.session
        with patch.object(demo, "_new_session", side_effect=create), \
                patch.object(demo.secrets, "randbits", return_value=123456):
            a = demo.api_action({"cmd": "new", "seed": "7"})
            b = demo.api_action({"cmd": "new", "seed": ""})
        self.assertTrue(a["ok"] and b["ok"])
        self.assertEqual(created, [7, 123456])

    def test_role_card_uses_effective_profile_range_and_skill(self):
        view = demo._piece_view(self.session.templates[65])
        self.assertEqual(view["range"], 3)
        self.assertEqual(view["role"], "瞬移刺客")
        self.assertIn("闪现", view["skill_description"])
        abra = demo._piece_view(self.session.templates[63])
        self.assertEqual(abra["skill_name"], "普通攻击")
        self.assertIn("没有可释放", abra["skill_description"])


if __name__ == "__main__":
    unittest.main()
