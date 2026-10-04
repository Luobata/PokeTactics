"""Roster-wide presentation fallbacks, real action fixtures and asset failures."""
import copy
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))
sys.path.insert(0, str(ROOT / "tools/mockups"))

from decoders import AssetError, Front, Palettes
import motion
import profile_range
import render_battle_gif as renderer
from roster import build_roster


class AssetFallbackContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.front_path, self.palette_path = root / "front.bin", root / "palettes.bin"
        # A valid species beyond Gen 1 proves decoding has no hard-coded ID cap.
        self.front_path.write_bytes(struct.pack("<4sHHHHIIH", b"FRNT", 1, 1,
                                               40, 400, 1, 0, 152) + bytes(400))
        self.palette_path.write_bytes(struct.pack("<4sHHHH", b"PALS", 1, 1, 4, 152)
                                      + struct.pack("<8H", *(0, 0x7BEF, 0xFFFF, 0) * 2)
                                      + bytes(152))
        self.front, self.palette = Front(self.front_path), Palettes(self.palette_path)

    def test_new_id_decodes_without_a_generation_limit(self):
        self.assertEqual(self.front.image(152, self.palette).getbbox(), (0, 0, 40, 40))

    def test_missing_transparent_and_truncated_sprites_identify_species_and_file(self):
        with self.assertRaisesRegex(AssetError, r"species 19: missing front sprite.*front.bin"):
            self.front.image(19, self.palette)
        self.front.blob_of[152] = bytes([255]) * 400
        with self.assertRaisesRegex(AssetError, r"species 152:.*no visible pixels.*front.bin"):
            self.front.image(152, self.palette)
        self.front.blob_of[152] = bytes(399)
        with self.assertRaisesRegex(AssetError, r"species 152: truncated.*front.bin"):
            self.front.image(152, self.palette)

    def test_missing_palette_and_resource_have_localizable_errors(self):
        for sid in (0, 153):
            with self.assertRaisesRegex(AssetError, rf"species {sid}: missing palette.*palettes.bin"):
                self.palette.for_species(sid)
        with self.assertRaisesRegex(AssetError, "cannot read art resource.*missing.bin"):
            Front(self.front_path.with_name("missing.bin"))

    def test_authored_body_can_render_without_a_part_rig(self):
        sprite = self.front.image(152, self.palette)
        with patch.dict(motion.species_motion, {152: motion.species_motion[6]}), \
             patch.dict(motion.KEYFRAMES, {152: motion.KEYFRAMES[6]}), \
             patch.dict(motion.RIG_PHASES, {152: motion.RIG_PHASES[6]}):
            pose = motion.Pose("strike", 1, motion.species_motion[152]["strike"][1])
            self.assertNotIn(152, motion.RIGS)
            result = motion.transform(sprite, 152, pose)
            self.assertIsNotNone(result.getbbox())
            self.assertEqual(result.tobytes(), motion.transform(sprite, 152, pose).tobytes())


class RosterPreviewContracts(unittest.TestCase):
    def test_every_roster_member_has_a_real_precharged_cast_and_visible_frames(self):
        ids = sorted({p.species_id for group in build_roster().values() for p in group})
        for sid in ids:
            with self.subTest(species=sid):
                anim = profile_range.make_preview_scene(sid, "cast", 7)
                source = copy.deepcopy(anim.events)
                cast = next(a for a in anim.timeline.actions if a.kind == "cast" and a.attacker == 0)
                self.assertTrue(any(e[1] == "cast" and e[2] == 0 for e in source))
                for t in (cast.start, cast.release, cast.impact, cast.recover_end + .2):
                    frame = anim.playback_frame(t, show_cutins=False)
                    self.assertEqual(frame.size, (240, 320))
                self.assertEqual(source, anim.events)
                first = anim.playback_frame(cast.impact, show_cutins=False).tobytes()
                again = profile_range.make_preview_scene(sid, "cast", 7)
                self.assertEqual(first, again.playback_frame(cast.impact, show_cutins=False).tobytes())

    def test_previously_truncated_ranged_attacks_include_impact_and_settle(self):
        affected = (37, 38, 43, 44, 45, 54, 55, 63, 64, 80, 81, 82,
                    92, 93, 116, 117, 120, 121, 129, 134, 135)
        for sid in affected:
            with self.subTest(species=sid):
                frames, meta = profile_range._clip(sid, "ranged", 7, "attack")
                timing = meta["action_timing"]
                self.assertLess(meta["frame_times"][0], timing["release"])
                self.assertGreaterEqual(meta["frame_times"][-1] + 1e-8, timing["impact"] + .4)
                self.assertGreater(meta["frame_times"][-1], timing["recover_end"])
                self.assertEqual(len(frames), len(meta["frame_times"]))
                self.assertEqual(meta["time_domain"], "presentation")

    def test_generic_body_prepares_until_release_and_recovers_with_timeline(self):
        anim = profile_range.make_preview_scene(19, "attack", 7)
        action = next(a for a in anim.timeline.actions if a.kind == "attack" and a.attacker == 0)
        view = anim._presentation_view()
        view._ensure(action.release - .01)
        self.assertLess(view._attack_motion(view.units[0], action.release - .01)[0], 0)
        view._ensure(action.release)
        self.assertGreater(view._attack_motion(view.units[0], action.release)[0], 0)
        view._ensure(action.recover_end)
        self.assertEqual(view._attack_motion(view.units[0], action.recover_end), (0., 0., 0))

    def test_missing_sprite_fails_before_any_bbox_or_style_lookup(self):
        anim = profile_range.make_preview_scene(19, "attack", 7)
        anim.front = Front()
        del anim.front.size_of[19]
        with self.assertRaisesRegex(AssetError, r"species 19: missing front sprite"):
            anim.playback_frame(.5, show_cutins=False)

    def test_move_hit_and_death_preview_keep_real_events(self):
        for kind in ("move", "hit", "death"):
            with self.subTest(kind=kind):
                anim = profile_range.make_preview_scene(19, kind, 7)
                expected = "attack" if kind == "hit" else "die" if kind == "death" else kind
                self.assertTrue(any(e[1] == expected and e[3 if kind == "hit" else 2] == 0
                                    for e in anim.events))
        frames, meta = profile_range._clip(19, "dummy", 7, "move")
        self.assertTrue(frames)
        self.assertIsNone(meta["action_timing"])


if __name__ == "__main__":
    unittest.main()
