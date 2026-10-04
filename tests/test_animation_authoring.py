"""Content failures, real roster action coverage, and a future species fixture."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools/mockups'), str(ROOT/'tools/acceptance'), str(ROOT/'sim')]
from esp32_runtime.animation import sample_track, validate_track
import character_rigs as rigs
import motion
import profile_range
import profiles
import render_battle_gif as renderer
import skill_vfx
from action_preview import PREVIEW_ACTIONS, describe_clip
from animation_acceptance import check_action
from character_catalog import character_catalog
from data import pokedex
from decoders import Front, Palettes, Font16
from move_effects import draw_skill_effect


class AnimationAuthoringContracts(unittest.TestCase):
    def test_portable_track_clamps_seeks_and_switches_visibility_on_key(self):
        keys = [[0, 0, 0, 0, 100, 100, 0], [.5, -4, 2, 30, 110, 90, 1],
                [1, 0, 0, 0, 100, 100, 0]]
        original = copy.deepcopy(keys)
        self.assertTrue(validate_track(keys))
        self.assertEqual(sample_track(keys, -1), tuple(keys[0][1:]))
        self.assertEqual(sample_track(keys, 10**400), tuple(keys[-1][1:]))
        self.assertEqual(sample_track(keys, .25), (-2, 1, 15, 105, 95, 0))
        self.assertEqual(sample_track(keys, .5)[-1], 1)
        self.assertEqual(sample_track(keys, 1)[-1], 0)
        for value in (float('nan'), float('inf'), True, '1'):
            with self.assertRaises(ValueError):
                sample_track(keys, value)
        self.assertEqual(keys, original)

    def test_malformed_tracks_are_rejected_before_render(self):
        good = [[0, 0, 0, 0, 100, 100, 1], [1, 0, 0, 0, 100, 100, 1]]
        invalid = [[], [good[0]], good[::-1], [good[0], good[0], good[1]]]
        for field, value in ((0, .9), (0, float('nan')), (1, 49), (2, True),
                              (3, 181), (4, 0), (5, 151), (6, 2)):
            keys = copy.deepcopy(good)
            keys[-1][field] = value
            invalid.append(keys)
        for keys in invalid:
            with self.subTest(keys=keys), self.assertRaisesRegex(ValueError, 'test/arm'):
                validate_track(keys, path='test/arm')

    def test_rig_rejects_missing_parts_phases_bad_pivots_and_false_readiness(self):
        good = rigs.catalog()['6']
        invalid = []
        for case in range(7):
            rig = copy.deepcopy(good)
            if case == 0: rig['parts'][1]['name'] = 'body'
            if case == 1: rig['anchors']['claw']['part'] = 'missing'
            if case == 2: del rig['actions']['attack']['near_arm']['recover']
            if case == 3: rig['parts'][1]['pivot_percent'] = [float('nan'), 1]
            if case == 4: rig['parts'][1]['source']['bounds_percent'] = [10, 10, 10, 20]
            if case == 5: rig['implemented'] = False
            if case == 6: rig['actions']['attack']['body'] = rig['actions']['attack']['near_arm']
            invalid.append(rig)
        for rig in invalid:
            with self.assertRaisesRegex(ValueError, 'rig/212'):
                rigs.validate_rig(rig, species=212)

    def test_hidden_source_slice_and_its_joint_are_not_painted(self):
        anim = profile_range.make_preview_scene(6, 'attack')
        sprite = anim._board_sprite(6, 3)
        visible = rigs.render_rig(sprite, 6, 'attack', 'strike', .5)
        edited = rigs.catalog()['6']
        for key in edited['actions']['attack']['near_arm']['strike']:
            key[-1] = 0
        rigs.validate_rig(edited, species=6)
        with patch.dict(rigs._RIGS, {6: edited}):
            hidden = rigs.render_rig(sprite, 6, 'attack', 'strike', .5)
        self.assertNotEqual(visible.tobytes(), hidden.tobytes())
        self.assertLess(sum(hidden.getchannel('A').tobytes()), sum(visible.getchannel('A').tobytes()))
        self.assertEqual(visible.info['foot_anchor'], hidden.info['foot_anchor'])

    def test_incomplete_body_cannot_be_published_as_a_complete_part_rig(self):
        broken = copy.deepcopy(motion.species_motion[6])
        del broken['death']
        with patch.dict(motion.species_motion, {6: broken}), self.assertRaisesRegex(ValueError, 'motion/6'):
            character_catalog()
        # A rig for a formerly procedural actor must not be silently ignored by
        # the runtime while the catalog reports it as delivered.
        with patch.dict(rigs._RIGS, {19: rigs.catalog()['6']}), self.assertRaisesRegex(ValueError, 'rig/19'):
            character_catalog()

    def test_subpixel_slice_fails_with_its_part_name_instead_of_dividing_by_zero(self):
        rig = rigs.catalog()['6']
        rig['parts'][1]['source']['bounds_percent'] = [0, 0, .01, 100]
        rigs.validate_rig(rig, species=6)
        sprite = profile_range.make_preview_scene(6, 'attack')._board_sprite(6, 3)
        with patch.dict(rigs._RIGS, {6: rig}), self.assertRaisesRegex(ValueError, 'rig/6/far_wing.*empty'):
            rigs.render_rig(sprite, 6, 'attack', 'strike', .5)

    def test_capability_matrix_does_not_confuse_shared_and_bespoke_actions(self):
        data = character_catalog()
        for entry in data.values():
            self.assertEqual(set(entry['capabilities']['actions']), set(PREVIEW_ACTIONS))
            matrix = entry['capabilities']['action_matrix']
            self.assertFalse(matrix['victory']['supported'])
            self.assertEqual(matrix['status']['body'], 'shared_overlay')
            self.assertFalse(matrix['status']['preview'])
            self.assertEqual(matrix['death']['parts'], 'none')
        self.assertEqual(data['6']['capabilities']['action_matrix']['attack']['parts'], 'authored')
        self.assertEqual(data['19']['capabilities']['action_matrix']['attack']['parts'], 'none')

    def test_all_84_species_six_actions_use_real_events_and_rewind_identically(self):
        for sid in map(int, character_catalog()):
            for kind in PREVIEW_ACTIONS:
                with self.subTest(species=sid, kind=kind):
                    record = check_action(sid, kind)
                    self.assertTrue(record['events_unchanged'])

    def test_new_species_reuses_ordinary_and_special_paths_without_core_allowlist(self):
        # Borrowed test art and a copied rig prove mechanics, not new final art.
        dex = pokedex()
        species = {**copy.deepcopy(dex.species[123]), 'id': 212, 'lineage': [212, 123]}
        front, pal, font = Front(), Palettes(), Font16()
        front.blob_of[212], front.size_of[212] = front.blob_of[6], front.size_of[6]
        pal._map += bytes([pal._map[5]])*(212-len(pal._map))
        with patch.dict(dex.species, {212: species}), patch.object(profile_range, '_assets', return_value=(front, pal, font)):
            # Generic body/skill remains executable without any rig or VFX table.
            self.assertNotIn(212, motion.species_motion)
            for kind in PREVIEW_ACTIONS:
                check_action(212, kind)
            # Upgrade independent layers: actual chain mechanic, authored poses,
            # and optional local parts. No frontend list or core VFX entry added.
            rig = rigs.catalog()['6']
            with patch.dict(profiles.PROFILE, {212: {'ult': {'arch': 'chain_lightning'}}}), \
                 patch.dict(rigs._RIGS, {212: rig}), \
                 patch.dict(motion.species_motion, {212: motion.species_motion[6]}), \
                 patch.dict(motion.KEYFRAMES, {212: motion.KEYFRAMES[6]}), \
                 patch.dict(motion.RIG_PHASES, {212: motion.RIG_PHASES[6]}):
                self.assertEqual(skill_vfx.skill_profile(212)['arch'], 'chain_lightning')
                for kind in PREVIEW_ACTIONS:
                    check_action(212, kind)
                anim = profile_range.make_preview_scene(212, 'cast')
                clip = describe_clip(anim, 'cast')
                self.assertTrue(any(ev[1] == 'skill_effect' and ev[4] == 'chain_lightning' for ev in anim.events))
                with patch.object(renderer, 'draw_skill_effect', wraps=renderer.draw_skill_effect) as draw:
                    anim.playback_frame(clip['snapshot_at']+.05, show_cutins=False)
                    self.assertTrue(any(call.args[1] == 212 and call.kwargs['arch'] == 'chain_lightning' for call in draw.call_args_list))

    def test_new_species_secondary_effects_follow_arch_and_actual_payload(self):
        for arch, effect, payload in [('chain_lightning', 'side_hit', {'damage': 20}),
                                     ('line_push', 'side_hit', {'damage': 20}),
                                     ('quake_break', 'side_hit', {'damage': 20}),
                                     ('solar_siphon', 'heal', {'amount': 20}),
                                     ('energy_drain', 'energy_drain', {'stolen': 20})]:
            with self.subTest(arch=arch):
                frame = Image.new('RGBA', (240, 320))
                budget = renderer.ParticleBudget()
                draw_skill_effect(frame, 212, effect, (50, 80), (170, 160), .1, budget, payload=payload, arch=arch)
                self.assertIsNotNone(frame.getbbox())
                self.assertGreater(budget.used, 0)
                empty = Image.new('RGBA', frame.size)
                draw_skill_effect(empty, 212, effect, (50, 80), (170, 160), .1,
                                  renderer.ParticleBudget(), payload={}, arch=arch)
                self.assertIsNone(empty.getbbox())


if __name__ == '__main__':
    unittest.main()
