"""Manifest integrity and coverage using synthetic assets, not copied game art."""

import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/mockups"))
import art_manifest as art


def synthetic_assets(path):
    # Valid tiny-content FRNT: 151 flat 40x40 records, authored here for tests.
    payload = b"".join(struct.pack("<H", sid) + bytes([sid % 256]) * 400
                       for sid in range(1, 152))
    (path / "gen1_front.bin").write_bytes(struct.pack("<4sHHHHII", b"FRNT", 1, 1, 40, 400, 151, 0) + payload)
    (path / "palettes.bin").write_bytes(struct.pack("<4sHHHH", b"PALS", 1, 1, 4, 151)
                                       + struct.pack("<8H", *(0, 0x7BEF, 0xFFFF, 0) * 2) + bytes(151))
    (path / "font16.bin").write_bytes(struct.pack("<4sHHHI2H", b"FNT1", 1, 16, 32, 2,
                                               ord("妙"), ord("蛙")) + bytes(64))
    (path / "pokemon_art_sources.json").write_text(json.dumps({
        "repository": "synthetic-test-fixture", "commit": "test", "source_mode": "generated flat pixels",
        "palette_rule": "generated test colors"}))


class ArtManifestContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.assets = Path(self.temp.name)
        synthetic_assets(self.assets)
        self.manifest = art.build_manifest(asset_root=self.assets)

    def validate(self, manifest):
        return art.validate_manifest(manifest, asset_root=self.assets)

    def test_real_byte_ranges_hashes_and_declared_coverage_match_inputs(self):
        self.assertTrue(self.validate(self.manifest))
        front = (self.assets / "gen1_front.bin").read_bytes()
        self.assertEqual(self.manifest["assets"]["front"]["bytes"], len(front))
        self.assertEqual(self.manifest["assets"]["front"]["sha256"], hashlib.sha256(front).hexdigest())
        entry = self.manifest["atlas"]["front/6"]
        self.assertEqual(front[entry["offset"]:entry["offset"] + entry["bytes"]], bytes([6]) * 400)
        actors = self.manifest["actors"]
        self.assertEqual(self.manifest["coverage"]["roster_species"], len(actors))
        self.assertTrue(all(a["atlas_key"] in self.manifest["atlas"] for a in actors.values()))
        self.assertTrue(actors["species.63"]["skill"]["can_cast"])
        self.assertEqual(actors["species.63"]["skill"]["animation_key"], "vfx.volley_shot")
        self.assertEqual(self.manifest["budget"]["measurements"]["pc_render"]["status"], "not_measured")

    def test_missing_asset_is_a_hard_failure(self):
        (self.assets / "font16.bin").unlink()
        with self.assertRaisesRegex(art.ManifestError, "missing/unreadable resource"):
            self.validate(self.manifest)
        with self.assertRaises(art.ManifestError):
            art.build_manifest(asset_root=self.assets)

    def test_core_pixel_cels_are_exported_and_tampering_cannot_fake_provenance(self):
        cels = self.manifest["animation_data"]["effect_cels"]
        self.assertEqual(len(cels), 8)
        for family, entry in cels.items():
            self.assertEqual(len(entry["pixels"]), 3, family)
            self.assertEqual(len(entry["palettes_rgb888"]["classic"]), 4)
        self.assertEqual(self.manifest["actors"]["species.9"]["skill"]["animation_key"], "vfx.core.9")
        from PIL import Image
        import move_effects
        from render_battle_gif import ParticleBudget
        for sid in move_effects.SUPPORTED_SPECIES:
            clip = self.manifest["animation_data"]["clips"][f"vfx.core.{sid}"]
            for phase in clip["phases"]:
                frame = Image.new("RGBA", (240, 200))
                move_effects.draw_move_effect(frame, sid, (50, 80), (180, 100),
                                             phase, .5, ParticleBudget())
                self.assertIsNotNone(frame.getbbox(), (sid, phase))
        bad = copy.deepcopy(self.manifest)
        bad["animation_data"]["effect_cels"]["water"]["pixels"][0][0] = "444444444"
        bad["revision"] = art.content_revision(bad)
        with self.assertRaisesRegex(art.ManifestError, "effect cels"):
            self.validate(bad)

    def test_modified_asset_and_forged_hash_are_rejected(self):
        bad = copy.deepcopy(self.manifest)
        bad["assets"]["front"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(art.ManifestError, "size/hash mismatch"):
            self.validate(bad)
        raw = bytearray((self.assets / "palettes.bin").read_bytes())
        raw[12] ^= 1
        (self.assets / "palettes.bin").write_bytes(raw)
        with self.assertRaisesRegex(art.ManifestError, "size/hash mismatch"):
            self.validate(self.manifest)

    def test_planned_rigs_cannot_be_reported_as_implemented(self):
        self.assertEqual(self.manifest["coverage"]["part_rig_species"], [3, 6, 9])
        self.assertEqual(self.manifest["coverage"]["gameplay_signature_species"], 8)
        for edit in ("definition", "coverage"):
            bad = copy.deepcopy(self.manifest)
            if edit == "definition":
                bad["animation_data"]["character_rigs"]["species"]["26"]["implemented"] = True
            else:
                bad["coverage"]["part_rig_species"].append(26)
            bad["revision"] = art.content_revision(bad)
            with self.subTest(edit=edit), self.assertRaisesRegex(art.ManifestError, "character rig"):
                self.validate(bad)

    def test_missing_animation_reference_is_not_hidden_by_revision(self):
        bad = copy.deepcopy(self.manifest)
        bad["actors"]["species.6"]["animations"]["idle"] = "motion.6.nonexistent"
        bad["revision"] = art.content_revision(bad)
        with self.assertRaisesRegex(art.ManifestError, "missing animation reference"):
            self.validate(bad)

    def test_inventing_an_animation_catalog_entry_cannot_fake_coverage(self):
        bad = copy.deepcopy(self.manifest)
        bad["animation_data"]["clips"]["motion.6.nonexistent"] = {
            "kind": "procedural_python", "frames_exported": False,
            "source": "tools/mockups/motion.py"}
        bad["revision"] = art.content_revision(bad)
        with self.assertRaisesRegex(art.ManifestError, "animation catalog"):
            self.validate(bad)

    def test_atlas_metadata_cannot_point_at_different_species_pixels(self):
        bad = copy.deepcopy(self.manifest)
        bad["atlas"]["front/6"]["offset"] = bad["atlas"]["front/9"]["offset"]
        bad["revision"] = art.content_revision(bad)
        with self.assertRaisesRegex(art.ManifestError, "atlas records"):
            self.validate(bad)

    def test_malformed_binary_layout_and_palette_index_are_rejected(self):
        path = self.assets / "gen1_front.bin"
        original = path.read_bytes()
        path.write_bytes(original[:-1])
        with self.assertRaisesRegex(art.ManifestError, "truncated FRNT"):
            art.build_manifest(asset_root=self.assets)
        path.write_bytes(original)
        pal = self.assets / "palettes.bin"
        raw = bytearray(pal.read_bytes())
        raw[-1] = 9
        pal.write_bytes(raw)
        with self.assertRaisesRegex(art.ManifestError, "missing palette"):
            art.build_manifest(asset_root=self.assets)

    def test_integer_export_matches_python_samples_at_clip_boundaries(self):
        import motion
        for key, clip in self.manifest["animation_data"]["clips"].items():
            if clip["kind"] != "integer_pose_table":
                continue
            sid, name = clip["species_id"], clip["state"]
            count, dt = len(clip["frames"]), clip["sample_ms"]
            for age_ms in (0, dt - 1, dt, dt * count - 1, dt * count, dt * (count + 1)):
                index = max(0, age_ms // dt)
                index = index % count if clip["loop"] else min(index, count - 1)
                self.assertEqual(list(motion.sample(sid, name, age_ms / 1000)[1]), clip["frames"][index], (key, age_ms))
            self.assertTrue(all(len(frame) == 6 for frame in clip["presentation_frames"]))

    def test_export_is_stable_across_fresh_processes_and_has_no_host_path(self):
        paths = [self.assets / "manifest-a.json", self.assets / "manifest-b.json"]
        for output in paths:
            result = subprocess.run([sys.executable, str(ROOT / "tools/mockups/art_manifest.py"),
                                     "--asset-root", str(self.assets), "--output", str(output)],
                                    cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
        self.assertNotIn(str(self.assets).encode(), paths[0].read_bytes())
        self.assertNotIn(str(ROOT).encode(), paths[0].read_bytes())

    def test_pc_evidence_is_separate_from_configuration_and_esp32_claims(self):
        metrics = self.assets / "pc-metrics.json"
        metrics.write_text('{"fixture":"four-units","frame_ms_p95":5.5}')
        manifest = art.build_manifest(asset_root=self.assets, pc_metrics=metrics)
        measured = manifest["budget"]["measurements"]
        self.assertEqual(measured["pc_render"]["evidence"]["frame_ms_p95"], 5.5)
        self.assertEqual(measured["pc_render"]["evidence_sha256"], hashlib.sha256(metrics.read_bytes()).hexdigest())
        self.assertEqual(measured["esp32"]["status"], "pending_port_and_device_measurement")
        self.assertEqual(manifest["budget"]["configured_pc_contract"], self.manifest["budget"]["configured_pc_contract"])

    def test_traversal_in_resource_reference_is_rejected(self):
        bad = copy.deepcopy(self.manifest)
        bad["assets"]["font16"]["path"] = "../font16.bin"
        with self.assertRaisesRegex(art.ManifestError, "escapes"):
            self.validate(bad)


if __name__ == "__main__":
    unittest.main()
