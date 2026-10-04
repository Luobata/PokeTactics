"""A new roster member must not require a UI allowlist or a species rig."""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "sim"), str(ROOT / "tools/mockups"), str(ROOT / "tools/acceptance")]
from character_catalog import character_catalog
from data import pokedex
from shop import make_piece
import animation_preview
import art_manifest


class CharacterCatalogContracts(unittest.TestCase):
    def test_all_roster_has_honest_independent_capabilities(self):
        entries = character_catalog()
        self.assertEqual(len(entries), 84)
        self.assertEqual(sum(c["skill"]["tier"] == "signature" for c in entries.values()), 8)
        self.assertEqual(sum(c["skill"]["tier"] == "generic" for c in entries.values()), 76)
        self.assertTrue(all(c["capabilities"]["resource_ready"] for c in entries.values()))
        self.assertTrue(all(c["skill"]["can_cast"] for c in entries.values()))
        self.assertEqual(entries["19"]["capabilities"]["body"], "procedural")
        self.assertEqual(entries["18"]["capabilities"]["body"], "authored_pose")
        self.assertEqual(entries["3"]["capabilities"]["body"], "part_rig")
        self.assertEqual(entries["63"]["skill"]["move_id"], None)
        self.assertTrue(entries["63"]["skill"]["fallback_payload"])
        self.assertEqual(entries["63"]["capabilities"]["effect"], "archetype")
        json.dumps(entries, allow_nan=False)

    def test_new_family_member_automatically_appears_but_missing_art_is_explicit(self):
        dex = pokedex()
        future = copy.deepcopy(dex.species[123])
        future.update(id=212, name_zh="扩展测试", lineage=[212, 123])
        with patch.dict(dex.species, {212: future}):
            entries = character_catalog()
            self.assertIn("212", entries)
            cap = entries["212"]["capabilities"]
            self.assertEqual(cap["body"], "procedural")
            self.assertFalse(cap["resource_ready"])
            self.assertIn("front/212", " ".join(cap["resource_errors"]))
            with self.assertRaisesRegex(ValueError, "资源"):
                animation_preview.normalize_preset({"schema_version": 1, "species": 212})
        self.assertNotIn("212", character_catalog())

    def test_existing_dex_member_is_not_in_shop_until_selected(self):
        self.assertNotIn("151", character_catalog())
        entry = character_catalog(pieces=[make_piece(151, {})])["151"]
        self.assertTrue(entry["capabilities"]["resource_ready"])
        self.assertEqual(entry["capabilities"]["body"], "procedural")

    def test_minimal_signature_profile_does_not_require_presentation_prose(self):
        import profiles
        import demo
        piece = make_piece(1, {})
        with patch.dict(profiles.PROFILE, {1: {"ult": {"arch": "splash"}}}):
            self.assertEqual(character_catalog(pieces=[piece])["1"]["skill"]["tier"], "signature")
            self.assertTrue(demo._piece_view(piece)["skill_description"])

    def test_noncore_default_preview_is_valid_but_unsupported_edits_are_rejected(self):
        preset = {"schema_version": 1, "species": 19, "settings": {}}
        self.assertEqual(animation_preview.normalize_preset(preset)["species"], 19)
        for settings in ({"palette": "vivid"}, {"motion_scale": .5}, {"effect_scale": 1.2}):
            with self.subTest(settings=settings), self.assertRaisesRegex(ValueError, "尚未接入"):
                animation_preview.normalize_preset({**preset, "settings": settings})

    def test_manifest_supports_uint16_species_ids_beyond_first_generation(self):
        data = struct.pack("<4sHHHHIIH", b"FRNT", 1, 1, 40, 400, 1, 0, 212) + bytes(400)
        meta, atlas = art_manifest._front(data)
        self.assertIn("front/212", atlas)
        self.assertEqual(meta["record_count"], 1)

    def test_catalog_does_not_mark_a_truncated_sprite_as_previewable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.joinpath("gen1_front.bin").write_bytes(
                struct.pack("<4sHHHHIIH", b"FRNT", 1, 1, 40, 400, 1, 0, 19) + bytes(399))
            root.joinpath("palettes.bin").write_bytes(
                struct.pack("<4sHHHH", b"PALS", 1, 1, 4, 19) + bytes(16 + 19))
            entry = character_catalog(pieces=[make_piece(19, {})], asset_root=root)["19"]
            self.assertFalse(entry["capabilities"]["resource_ready"])
            self.assertIn("长度错误", " ".join(entry["capabilities"]["resource_errors"]))


if __name__ == "__main__":
    unittest.main()
