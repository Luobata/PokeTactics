"""Editor presets must change visible pixels without changing game outcomes."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools/acceptance"), str(ROOT / "tools/mockups"), str(ROOT / "sim")]
import animation_preview as preview


class AnimationPreviewContracts(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        change = patch.object(preview, "CACHE_ROOT", self.root)
        change.start()
        self.addCleanup(change.stop)

    def test_presets_reject_unknown_fields_nonfinite_types_and_future_versions(self):
        good = {"schema_version": 1, "species": 6, "settings": {}}
        self.assertEqual(preview.normalize_preset(good)["settings"]["palette"], "classic")
        invalid = [{**good, "schema_version": 2}, {**good, "schema_version": True},
                   {**good, "species": 25}, {**good, "species": "6"},
                   {**good, "url": "file:///tmp/a"},
                   {**good, "settings": {"unknown": 1}},
                   {**good, "settings": {"palette": "unknown"}}]
        for key, value in (("effect_scale", True), ("effect_scale", .69),
                           ("effect_scale", 1.31), ("motion_scale", "1"),
                           ("motion_scale", float("nan")), ("particle_density", 1.1)):
            invalid.append({**good, "settings": {key: value}})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                preview.normalize_preset(value)
        for key in ("effect_scale", "particle_density", "motion_scale"):
            for huge in (10**400, -(10**400)):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    preview.normalize_preset({**good, "settings": {key: huge}})

    def test_json_and_request_limits(self):
        for raw in (b"", b"x"*8193, b'{"x":1,"x":2}', b'{"x":NaN}', b'\xff', b"["*4000):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                preview.parse_request(raw)
        for extra in ({"kind": "death"}, {"seed": -1}, {"seed": 2**32},
                      {"seed": True}, {"frames": 100000}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                preview.normalize_preview({"species": 6, **extra})
        self.assertEqual(list(self.root.iterdir()), [])

    def test_visual_edit_changes_pixels_but_preserves_timing_hp_and_base(self):
        base = preview.preview({"species": 6, "kind": "cast", "seed": 7})
        edited = preview.preview({"species": 6, "kind": "cast", "seed": 7,
                                  "settings": {"palette": "vivid", "effect_scale": 1.3,
                                               "motion_scale": .5, "particle_density": .5}})
        self.assertNotEqual(base["key"], edited["key"])
        self.assertNotEqual(base["frame_sha256"], edited["frame_sha256"])
        self.assertEqual(base["base_key"], edited["base_key"])
        for key in ("action", "target_before_impact", "target_at_impact", "n", "dt"):
            self.assertEqual(base[key], edited[key], key)
        self.assertLessEqual(edited["metrics"]["particle_peak"], 192)
        self.assertEqual(len(edited["frames"]), len(edited["base_frames"]))
        with patch("profile_range.make_signature_scene", side_effect=AssertionError("cache miss")):
            self.assertEqual(preview.preview({"species": 6, "kind": "cast", "seed": 7})["frame_sha256"],
                             base["frame_sha256"])

    def test_preset_roundtrip_and_input_do_not_leak_between_instances(self):
        raw = {"schema_version": 1, "species": 65, "settings": {"motion_scale": .8}}
        normalized = preview.normalize_preset(raw)
        normalized["settings"]["motion_scale"] = 1.5
        self.assertEqual(raw["settings"]["motion_scale"], .8)
        loaded = preview.normalize_preset(preview.parse_request(json.dumps(raw).encode()))
        self.assertEqual(loaded["settings"]["motion_scale"], .8)
        self.assertEqual(preview.normalize_preset({**raw, "settings": {}})["settings"]["motion_scale"], 1.)

    def test_failed_render_preserves_existing_cache_and_cleans_partial_frames(self):
        existing = preview.preview({"species": 65})
        before = sorted(p.name for p in self.root.iterdir())
        from render_battle_gif import BattleAnimation
        with patch.object(BattleAnimation, "playback_frame", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                preview.preview({"species": 65, "settings": {"effect_scale": 1.2}})
        self.assertEqual(before, sorted(p.name for p in self.root.iterdir()))
        self.assertTrue((self.root / existing["key"] / "0.png").is_file())

    def test_source_revision_invalidates_cache(self):
        request = preview.normalize_preview({"species": 9})
        self.assertNotEqual(preview._key(request, "source-a"), preview._key(request, "source-b"))

    def test_failed_pairs_cannot_fill_cache_or_evict_the_last_success(self):
        with patch.object(preview, "MAX_CACHE_ENTRIES", 2):
            previous = preview.preview({"species": 6, "seed": 7,
                                        "settings": {"effect_scale": 1.2}})
            original = preview._render
            def fail_edited(request, revision):
                if request["settings"]["effect_scale"] == .8:
                    raise OSError("edited render failed")
                return original(request, revision)
            with patch.object(preview, "_render", side_effect=fail_edited):
                for seed in (11, 12, 13):
                    with self.assertRaises(OSError):
                        preview.preview({"species": 6, "seed": seed, "settings": {"effect_scale": .8}})
                    self.assertLessEqual(len(list(self.root.iterdir())), 2)
                    self.assertTrue((self.root / previous["key"] / "0.png").is_file())
                    self.assertTrue((self.root / previous["base_key"] / "0.png").is_file())

    def test_cache_pruning_is_bounded_and_preserves_current_pair_and_unowned_files(self):
        for i in range(30):
            (self.root / f"{i:032x}").mkdir()
        (self.root / "unrelated").mkdir()
        pair = (f"{0:032x}", f"{1:032x}")
        preview._prune(pair)
        self.assertEqual(len([p for p in self.root.iterdir() if len(p.name) == 32]), 24)
        self.assertTrue(all((self.root / key).exists() for key in pair))
        self.assertTrue((self.root / "unrelated").exists())


class AnimationPreviewHTTPContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from server import Handler
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def post(self, data, headers=None):
        request = urllib.request.Request(self.url + "/api/animation/preset/validate", data=data,
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def test_character_catalog_distinguishes_real_mechanisms_and_planned_parts(self):
        from data import pokedex
        with urllib.request.urlopen(self.url + "/api/animation/characters", timeout=10) as response:
            body = json.load(response)
        self.assertTrue(body["ok"])
        characters = body["characters"]
        self.assertEqual(len(characters), 8)
        for sid, character in characters.items():
            self.assertEqual(character["skill"]["move_id"], pokedex().signature_move(int(sid))["id"])
        self.assertTrue(characters["3"]["rig"]["implemented"])
        self.assertIn("藤鞭", characters["3"]["motion_notes"]["attack"])
        self.assertIn("日光束", characters["3"]["skill"]["name"])
        self.assertFalse(characters["26"]["rig"]["implemented"])
        import profiles
        with patch.object(profiles, "PROFILES_ON", False):
            with urllib.request.urlopen(self.url + "/api/animation/characters", timeout=10) as response:
                off = json.load(response)
        self.assertEqual(off["characters"]["26"]["role"], "通用技能")

    def test_http_preset_validation_requires_marker_and_same_origin(self):
        raw = b'{"schema_version":1,"species":6,"settings":{}}'
        self.assertEqual(self.post(raw)[0], 400)
        headers = {"X-PokeTactics-Preview": "1"}
        self.assertEqual(self.post(raw, {**headers, "Origin": "https://elsewhere.invalid"})[0], 403)
        status, body = self.post(raw, {**headers, "Origin": self.url})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["preset"]["species"], 6)
        self.assertEqual(self.post(b"x"*8193, headers)[0], 413)
        self.assertEqual(self.post(b'{"schema_version":2}', headers)[0], 400)
        self.assertEqual(self.post(b'{"schema_version":2,"schema_version":1,"species":6}', headers)[0], 400)
        for key in ("effect_scale", "particle_density", "motion_scale"):
            for value in (10**400, -(10**400)):
                raw = json.dumps({"schema_version": 1, "species": 6, "settings": {key: value}}).encode()
                self.assertEqual(self.post(raw, headers)[0], 400)
        self.assertTrue(self.post(b'{"schema_version":1,"species":6}', headers)[1]["ok"])


if __name__ == "__main__":
    unittest.main()
