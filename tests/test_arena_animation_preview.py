"""Arena tools use native skills, real action fixtures and the playable canvas."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools/acceptance'), str(ROOT/'tools/mockups'), str(ROOT/'sim')]
import animation_preview as preview
import arena
import arena_skills
from action_preview import PREVIEW_ACTIONS, describe_clip
from arena_preview_scene import make_preview_scene
from presentation_modes import make_renderer, mode_info
from web_battle import normalize_visual_overrides


class ArenaFixtureContracts(unittest.TestCase):
    def test_all_species_and_six_actions_have_real_and_deterministic_fixtures(self):
        self.assertEqual(len(arena.ROSTER),62)
        for sid in arena.ROSTER:
            for kind in PREVIEW_ACTIONS:
                with self.subTest(species=sid,kind=kind):
                    anim=make_preview_scene(sid,kind)
                    clip=describe_clip(anim,kind)
                    self.assertTrue(anim.is_arena)
                    self.assertEqual(anim.battle_rows,6)
                    self.assertLessEqual(round((clip['clip_end']-clip['clip_start'])/preview.DT)+1,100)
                    if kind=='cast':
                        self.assertEqual(anim.events[clip['source_index']][4],
                                         'arena_'+arena_skills.SKILLS[sid]['id'])
                        event=anim.events[clip['source_index']]
                        targeting=arena_skills.SKILLS[sid]['targeting']
                        self.assertEqual(clip['targeting'],targeting)
                        if targeting=='enemy':
                            self.assertGreater(event[6],0)
                            self.assertNotEqual(anim.by_idx[event[2]].team,anim.by_idx[event[3]].team)
                        else:
                            self.assertEqual(event[6],0)
                            self.assertEqual(clip['phases'][2]['label'],'生效')
                            if targeting in ('ally','self'):
                                self.assertEqual(anim.by_idx[event[2]].team,anim.by_idx[event[3]].team)
                            self.assertEqual(event[3],anim.preview_fixture['primary_target'])
                    elif kind=='idle':
                        self.assertFalse([event for event in anim.timeline.events
                                          if .4<=event[0]<=1.6 and event[1] in ('move','attack','cast')])
                    elif kind=='death':
                        self.assertIsNone(anim.presentation_state(clip['snapshot_before'])[0]['die_t'])
                        self.assertIsNotNone(anim.presentation_state(clip['snapshot_at'])[0]['die_t'])
        first=make_preview_scene(212,'cast',17)
        again=make_preview_scene(212,'cast',17)
        self.assertEqual(first.events,again.events)

    def test_training_scenes_change_real_recipient_range_and_movement_deployment(self):
        hit=[make_preview_scene(212,'hit',scene=scene) for scene in ('dummy','melee','ranged')]
        self.assertEqual([anim.by_idx[1].piece.species_id for anim in hit],[9,68,121])
        ranges=[abs(anim.by_idx[0].pos[1]-anim.by_idx[1].pos[1]) for anim in hit]
        self.assertEqual(ranges,[1,1,2])
        moves=[make_preview_scene(68,'move',scene=scene).events for scene in ('dummy','melee','ranged')]
        self.assertEqual(len({json.dumps(events) for events in moves}),3)

    def test_each_web_control_changes_pixels_without_changing_phase_or_simulation(self):
        for sid in (68,212,3,154):
            base=make_preview_scene(sid,'cast')
            clip=describe_clip(base,'cast')
            event_state=copy.deepcopy(base.events)
            action=clip['action']
            times=(action['start']+.07,action['release']-.02,action['impact']+.08)
            renderer=make_renderer(base)
            original=b''.join(renderer.frame(t).tobytes() for t in times)
            settings=(('palette','vivid'),('effect_scale',1.3),('particle_density',.5),('motion_scale',.5))
            for key,value in settings:
                with self.subTest(species=sid,control=key):
                    edited=make_preview_scene(sid,'cast',visual_overrides={sid:{key:value}})
                    new_clip=describe_clip(edited,'cast')
                    new_renderer=make_renderer(edited)
                    frames=b''.join(new_renderer.frame(t).tobytes() for t in times)
                    self.assertNotEqual(hashlib.sha256(original).digest(),hashlib.sha256(frames).digest())
                    self.assertEqual(edited.events,event_state)
                    self.assertEqual(clip,new_clip)
                    self.assertEqual(base.presentation_state(action['impact']),
                                     edited.presentation_state(action['impact']))
                    new_renderer.frame(edited.presentation_duration)
                    self.assertEqual(new_renderer.frame(times[0]).tobytes(),
                                     make_renderer(make_preview_scene(sid,'cast',
                                       visual_overrides={sid:{key:value}})).frame(times[0]).tobytes())

    def test_visual_overrides_do_not_mutate_or_accept_classic_only_species(self):
        config={212:{'motion_scale':.7}}
        normalized=normalize_visual_overrides(config)
        normalized[212]['motion_scale']=1.5
        self.assertEqual(config[212]['motion_scale'],.7)
        for value in ({143:{}},{68:{'foo':1}},{True:{}},{68:{'motion_scale':10**400}}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                normalize_visual_overrides(value)


class ArenaPreviewContracts(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        patcher=patch.object(preview,'CACHE_ROOT',self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_new_request_defaults_to_arena_and_old_presets_roundtrip_as_classic(self):
        self.assertEqual(preview.normalize_preview({'species':212})['mode'],'arena')
        old={'schema_version':1,'species':65,'settings':{'motion_scale':.8}}
        loaded=preview.normalize_preset(old)
        self.assertEqual(loaded['mode'],'classic')
        self.assertEqual(preview.normalize_preset(json.loads(json.dumps(loaded))),loaded)
        self.assertEqual(preview.normalize_preset({**old,'mode':'arena'})['mode'],'arena')
        for mode in ('unknown',None,True,[]):
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                preview.normalize_preview({'mode':mode,'species':212})
        with self.assertRaises(ValueError):
            preview.normalize_preview({'species':19})
        self.assertEqual(preview.normalize_preview({'mode':'classic','species':19})['species'],19)
        for sid in arena.ROSTER:
            loaded=preview.normalize_preset({'schema_version':1,'mode':'arena','species':sid,
                                             'settings':{'motion_scale':.7,'effect_scale':1.1}})
            self.assertEqual(loaded['settings']['motion_scale'],.7)

    def test_web_preview_metadata_dimensions_ownership_and_cache_are_mode_specific(self):
        arena_clip=preview.preview({'species':26,'kind':'cast'})
        classic_clip=preview.preview({'mode':'classic','species':26,'kind':'cast'})
        self.assertNotEqual(arena_clip['key'],classic_clip['key'])
        for clip,width,height in ((arena_clip,960,640),(classic_clip,240,320)):
            self.assertEqual(clip['dimensions'],{'width':width,'height':height})
            self.assertEqual(clip['render_revision'],mode_info(clip['mode'])['render_revision'])
            self.assertEqual(clip['presentation'],clip['render_revision'])
            with Image.open(self.root/clip['key']/'0.png') as frame:
                self.assertEqual(frame.size,(width,height))
            self.assertEqual(clip['source_revision'],clip['revision'])
            self.assertLessEqual(clip['metrics']['particle_peak'],clip['metrics']['particle_limit'])
        self.assertEqual(arena_clip['ruleset'],'arena_v1')
        self.assertEqual(arena_clip['stat_mode'],'budget_v1')
        self.assertEqual(arena_clip['native_skill']['id'],'spark_chain')
        self.assertEqual(arena_clip['source_action']['move'],'arena_spark_chain')
        self.assertEqual(len(arena_clip['skill_effects']),2)
        for effect in arena_clip['skill_effects']:
            self.assertEqual(effect['payload']['cast_index'],arena_clip['source_index'])
            self.assertGreaterEqual(effect['at'],arena_clip['action']['impact'])
        self.assertGreater(arena_clip['target_before_impact']['hp'],arena_clip['target_at_impact']['hp'])
        self.assertIsNone(classic_clip['native_skill'])
        with patch('arena_preview_scene.make_preview_scene',side_effect=AssertionError('cache miss')):
            self.assertEqual(preview.preview({'species':26})['frame_sha256'],arena_clip['frame_sha256'])

    def test_native_terrain_packets_remain_owned_by_their_real_cast(self):
        clip=preview.preview({'species':95,'kind':'cast'})
        self.assertEqual(clip['native_skill']['id'],'rock_spikes')
        fields=[effect for effect in clip['skill_effects'] if effect['kind']=='field_effect']
        self.assertTrue(fields)
        for effect in fields:
            self.assertEqual(effect['payload']['cast_index'],clip['source_index'])
            self.assertEqual(effect['arch'],'rock_spikes')
            self.assertGreaterEqual(effect['at'],clip['action']['impact'])
            self.assertTrue(effect['payload']['cells'])

    def test_gen2_png_changes_invalidate_the_source_revision(self):
        png=self.root/'gen2'/'normal'/'212.png'
        png.parent.mkdir(parents=True)
        png.write_bytes(b'asset-version-one')
        with patch.object(preview,'ROOT',self.root),patch('decoders.GEN2_FRONT',self.root/'gen2'):
            before=preview.source_revision()
            png.write_bytes(b'asset-version-two')
            self.assertNotEqual(before,preview.source_revision())

    def test_articulated_species_have_six_bounded_web_action_clips(self):
        for sid in (68,212):
            for kind in PREVIEW_ACTIONS:
                with self.subTest(species=sid,kind=kind):
                    clip=preview.preview({'species':sid,'kind':kind})
                    self.assertEqual(clip['mode'],'arena')
                    self.assertEqual(clip['selected_actor']['species'],sid)
                    self.assertTrue(clip['phases'])
                    self.assertLessEqual(clip['n'],100)
                    self.assertEqual(clip['frame_sha256'],clip['base_frame_sha256'])
                    self.assertEqual(len(clip['frames']),clip['n'])


if __name__=='__main__':
    unittest.main()
