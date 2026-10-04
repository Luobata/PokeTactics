"""Save/restore real games, including economic accounting and write failures."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/acceptance"))
import demo
from session_save import SessionCodec
from esp32_runtime import StorageIOError


def fast_render(a, b, rng, weather, path, positions_a=None, hud_snapshot=None):
    result = demo.Battle(a, b, rng, layout="back", weather_name=weather,
                         positions_a=positions_a).run()
    return {"n": 0, "winner": result["winner"], "survivors": result["survivors"],
            "duration": result["duration"], "events": []}


class SessionSaveContracts(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for patcher in (patch.object(demo, "SAVE_ROOT", Path(directory.name)),
                        patch.object(demo, "SESSIONS", {}),
                        patch.object(demo, "_render_battle_frames", side_effect=fast_render)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.codec = SessionCodec()
        created = demo.api_action({"cmd": "new", "seed": "7"})
        self.assertTrue(created["ok"], created)
        self.sid = created["sid"]

    @property
    def state(self):
        return demo.SESSIONS[self.sid]

    def act(self, cmd, **params):
        result = demo.api_action({"cmd": cmd, "sid": self.sid, **params})
        self.assertTrue(result["ok"], result)
        return result

    def test_process_restart_restores_grid_inventory_shop_and_cursor_without_income(self):
        self.act("buy", i=0)
        self.act("move", **{"from": "b0", "to": "g0,5"})
        self.act("refresh")
        self.act("lock")
        before = self.codec.encode(self.state)
        demo.SESSIONS.clear()  # exactly what a service restart loses
        self.act("resume")
        self.assertEqual(self.codec.encode(self.state), before)
        self.assertEqual(self.state.player.battle_positions(), [(5, 2)])
        self.assertTrue(self.state.player.shop_locked)
        self.assertEqual(self.state.player.refresh_j, 1)

    def test_restored_and_uninterrupted_games_match_through_pve_and_weather(self):
        self.act("buy", i=0)
        self.act("buy", i=1)
        self.act("move", **{"from": "b0", "to": "g0,5"})
        self.act("move", **{"from": "b0", "to": "g1,0"})
        uninterrupted = copy.deepcopy(self.state)
        self.act("resume")
        restored = self.state
        for round_no in range(1, 7):
            uninterrupted.end_prep()
            restored.end_prep()
            self.assertEqual(self.codec.encode(restored), self.codec.encode(uninterrupted), round_no)
            # Also restore a settled round. Advancing must not repeat its reward.
            restored = self.codec.decode(self.codec.encode(restored), 1)
            if uninterrupted.phase == "over":
                break
            uninterrupted.next_round()
            restored.next_round()
            self.assertEqual(self.codec.encode(restored), self.codec.encode(uninterrupted), round_no)

    def test_merge_history_and_stone_sources_are_not_reconstructed_from_species(self):
        s = self.state
        p = s.player
        for sid in (1, 1, 1, 64):
            s.pool.take(sid)
            p.bench.append(demo.shop_mod.OwnedPiece(s.templates[sid], s.templates[sid].tier))
        s.combine_player()
        p.inventory.finished.append("evo_stone")
        location = next(i for i, owned in enumerate(p.bench) if owned.piece.species_id == 64)
        demo.act_equip(s, "evo_stone", f"b{location}")
        data = self.codec.encode(s)
        restored = self.codec.decode(data, 1)
        self.assertEqual(self.codec.encode(restored), data)
        evolved = {o.piece.species_id: o for o in restored.player.bench}
        self.assertEqual(evolved[2].sources, [1, 1, 1, 2])
        self.assertEqual(evolved[2].invested, 3)
        self.assertEqual(evolved[65].sources, [64, 65])

    def test_failed_purchase_persistence_rolls_back_memory_and_disk(self):
        before = self.codec.encode(self.state)
        store = demo._save_store(self.sid)
        raw = store.export_backup()
        with patch("esp32_runtime.FileBackend.write_atomic", side_effect=StorageIOError("disk full")):
            result = demo.api_action({"cmd": "buy", "sid": self.sid, "i": 0})
        self.assertFalse(result["ok"])
        self.assertEqual(self.codec.encode(self.state), before)
        self.assertEqual(store.export_backup(), raw)

    def test_uncertain_commit_blocks_actions_until_disk_is_reloaded(self):
        with patch("esp32_runtime.SaveStore.save", side_effect=StorageIOError("fsync failed", commit_uncertain=True)):
            result = demo.api_action({"cmd": "buy", "sid": self.sid, "i": 0})
        self.assertFalse(result["ok"])
        self.assertIn("未确认", result["error"])
        rejected = demo.api_action({"cmd": "refresh", "sid": self.sid})
        self.assertFalse(rejected["ok"])
        self.act("resume")
        self.assertEqual(len(self.state.player.bench), 0)
        self.act("buy", i=0)

    def test_export_import_and_undo_preserve_both_versions(self):
        original = self.codec.encode(self.state)
        raw = demo.backup_bytes(self.sid)
        self.act("buy", i=0)
        changed = self.codec.encode(self.state)
        preview = demo.import_backup(raw, self.sid, inspect_only=True)
        self.assertTrue(preview["ok"], preview)
        self.assertEqual(self.codec.encode(self.state), changed)
        result = demo.import_backup(raw, self.sid)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.codec.encode(self.state), original)
        self.act("restore_checkpoint")
        self.assertEqual(self.codec.encode(self.state), changed)

    def test_corrupt_import_cannot_change_current_save_or_memory(self):
        raw = demo.backup_bytes(self.sid)
        before = self.codec.encode(self.state)
        result = demo.import_backup(raw[:-7], self.sid)
        self.assertFalse(result["ok"])
        self.assertEqual(self.codec.encode(self.state), before)
        self.assertEqual(demo.backup_bytes(self.sid), raw)

    def test_first_import_and_import_after_restart_do_not_encode_none(self):
        raw = demo.backup_bytes(self.sid)
        first = demo.import_backup(raw)
        self.assertTrue(first["ok"], first)
        self.assertNotEqual(first["sid"], self.sid)
        self.act("buy", i=0)
        changed = self.codec.encode(self.state)
        demo.SESSIONS.clear()
        imported = demo.import_backup(raw, self.sid)
        self.assertTrue(imported["ok"], imported)
        demo.SESSIONS.clear()
        self.act("restore_checkpoint")
        self.assertEqual(self.codec.encode(self.state), changed)

    def test_unknown_rule_fingerprint_is_rejected_without_silent_rule_change(self):
        data = self.codec.encode(self.state)
        data["rules"] = "previous-build"
        with self.assertRaisesRegex(ValueError, '规则指纹'):
            self.codec.decode(data, 1)

    def test_semantically_invalid_snapshots_are_rejected(self):
        changes = [lambda p: p["pool"].__setitem__("1", p["pool"]["1"] - 1),
                   lambda p: p.__setitem__("last_battle", {"winner": 0, "duration": "broken"}),
                   lambda p: p.__setitem__("last_battle", {"winner": 0, "survivors": {"0": -1, "1": 2}}),
                   lambda p: p.__setitem__("last_battle", {"winner": 0, "injected": True}),
                   lambda p: p["seats"][0].__setitem__("gold", -1),
                   lambda p: p.__setitem__("phase", "combat-in-progress"),
                   lambda p: p.__setitem__("pairs", [[0, 0]]),
                   lambda p: p["seats"][1]["stats"].__setitem__("gold_curve", None),
                   lambda p: p["seats"][1]["stats"]["craft_stats"].__setitem__("made", []),
                   lambda p: p["seats"][1].__setitem__("personality", "unknown")]
        for change in changes:
            with self.subTest(change=change):
                data = self.codec.encode(self.state)
                change(data)
                with self.assertRaises(ValueError):
                    self.codec.decode(data, 1)

    def test_new_game_never_overwrites_previous_game_slot(self):
        raw = demo.backup_bytes(self.sid)
        other = demo.api_action({"cmd": "new", "seed": "42"})
        self.assertTrue(other["ok"], other)
        self.assertNotEqual(other["sid"], self.sid)
        self.assertEqual(demo.backup_bytes(self.sid), raw)

    def test_uncertain_first_save_returns_a_recovery_handle(self):
        with patch("esp32_runtime.SaveStore.save", side_effect=StorageIOError("fsync", commit_uncertain=True)):
            result = demo.api_action({"cmd": "new", "seed": "42"})
        self.assertFalse(result["ok"])
        self.assertRegex(result["recovery_sid"], r"^[a-f0-9]{12}$")
        with patch("esp32_runtime.SaveStore.import_backup", side_effect=StorageIOError("fsync", commit_uncertain=True)):
            result = demo.import_backup(demo.backup_bytes(self.sid))
        self.assertFalse(result["ok"])
        self.assertRegex(result["recovery_sid"], r"^[a-f0-9]{12}$")


if __name__ == "__main__":
    unittest.main()
