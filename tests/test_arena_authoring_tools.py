"""Trial and classic authoring select honest catalogs, actual scenes and one renderer."""
import copy
import json
import inspect
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/mockups'), str(ROOT/'tools/acceptance')]
import arena
import arena_families
import arena_skills
from action_preview import PREVIEW_ACTIONS
from animation_acceptance import check_action
from animation_showcase import export
from character_catalog import character_catalog
from combat import Unit
from presentation_modes import make_renderer, mode_info
from profile_range import _clip, make_preview_scene, render_species_scene
from web_battle import EDITABLE_CONTROLS
import roster_showcase


class ArenaAuthoringContracts(unittest.TestCase):
    def test_catalog_matches_all_actual_trial_templates_native_skills_and_ranges(self):
        entries = character_catalog(mode='arena')
        templates = arena_families.build_templates(arena_families.VERSION)
        self.assertEqual(set(map(int,entries)),set(templates))
        self.assertEqual(len(entries),151)
        for sid,piece in templates.items():
            row = entries[str(sid)]
            skill = arena_skills.skill_of(sid)
            with self.subTest(species=sid):
                self.assertEqual(row['range'],Unit(piece,0,(2,3),stat_mode='budget_v1').range)
                self.assertEqual(row['role_key'],piece.role_key)
                self.assertEqual(row['cost'],piece.tier)
                self.assertEqual(row['skill']['native_id'],skill['id'])
                self.assertEqual(row['skill']['description'],skill['description'])
                self.assertEqual(row['skill']['tier'],'native')
                if not row['capabilities']['resource_ready']:
                    self.assertTrue(row['capabilities']['resource_errors'])
                self.assertEqual(row['capabilities']['editable_controls'],list(EDITABLE_CONTROLS))
                self.assertEqual(row['capabilities']['actions'],list(PREVIEW_ACTIONS))
                self.assertEqual((row['width'],row['height'],row['revision']),(960,640,mode_info('arena')['revision']))
        self.assertEqual(entries['212']['resources']['source'],'gen2_png')
        self.assertTrue(Path(entries['212']['resources']['normal']).is_file())
        self.assertEqual(entries['68']['resources']['source'],'gen1_front')
        json.dumps(entries,allow_nan=False)

    def test_joint_capabilities_do_not_claim_bespoke_whole_body_or_death_actions(self):
        entries = character_catalog(mode='arena')
        self.assertEqual({int(sid) for sid,row in entries.items()
                          if row['capabilities']['body']=='web_part_rig'},{26,68,212})
        self.assertEqual({int(sid) for sid,row in entries.items()
                          if row['capabilities']['body']=='part_rig'},{3,6,9})
        row = entries['68']['capabilities']
        self.assertEqual(row['whole_body'],'procedural')
        self.assertEqual(row['action_matrix']['cast']['parts'],'authored')
        self.assertEqual(row['action_matrix']['death']['parts'],'none')
        self.assertEqual(entries['242']['capabilities']['parts'],'none')
        entries['68']['rig']['parts'][1]['label']='edited'
        self.assertNotEqual(character_catalog(mode='arena')['68']['rig']['parts'][1]['label'],'edited')

    def test_classic_catalog_and_helpers_keep_the_old_default_contract(self):
        entries = character_catalog()
        self.assertEqual(len(entries),84)
        self.assertNotIn('212',entries)
        self.assertEqual(entries['26']['capabilities']['body'],'authored_pose')
        self.assertEqual(entries['6']['revision'],'device-v1')
        anim = make_preview_scene(19,'attack')
        renderer = make_renderer(anim,'classic')
        self.assertFalse(anim.is_arena)
        action=next(row for row in anim.timeline.actions if row.attacker==0 and row.kind=='attack')
        self.assertEqual(renderer.frame(action.impact,show_cutins=False).tobytes(),
                         anim.playback_frame(action.impact,show_cutins=False).tobytes())
        self.assertEqual(check_action(19,'move')['mode'],'classic')

    def test_native_scene_and_adapter_use_the_actual_trial_rules_and_pixels(self):
        anim = make_preview_scene(212,'cast',mode='arena')
        source = copy.deepcopy(anim.events)
        renderer = make_renderer(anim,'arena')
        self.assertEqual((anim.is_arena,anim.battle_rows),(True,6))
        action=next(row for row in anim.timeline.actions if row.attacker==0 and row.kind=='cast')
        event=anim.events[action.source_index]
        self.assertEqual(event[4],'arena_'+arena_skills.skill_of(212)['id'])
        frame = renderer.frame(action.release)
        self.assertEqual(frame.size,(960,640))
        first=frame.tobytes()
        renderer.frame(anim.presentation_duration)
        self.assertEqual(first,renderer.frame(action.release).tobytes())
        self.assertEqual(source,anim.events)
        self.assertIn('active_actions',renderer.metrics)

    def test_real_action_acceptance_covers_ordinary_joint_and_gen2_actors(self):
        for sid in (68,212,242):
            for kind in PREVIEW_ACTIONS:
                with self.subTest(species=sid,kind=kind):
                    record=check_action(sid,kind,mode='arena')
                    self.assertEqual((record['mode'],record['width'],record['height']),('arena',960,640))
                    self.assertTrue(record['rewind_equal'])
                    self.assertTrue(record['events_unchanged'])
                    self.assertIn('visible_units',record['metrics'])

    def test_training_scenes_have_real_different_opponents_and_native_cast_only_once(self):
        streams=[]
        for scene,opponent in (('dummy',9),('melee',68),('ranged',121)):
            anim=make_preview_scene(212,'hit',mode='arena',scene=scene)
            self.assertEqual(anim.by_idx[1].piece.species_id,opponent)
            streams.append(anim.events)
        self.assertEqual(len({json.dumps(stream) for stream in streams}),3)
        frames,meta=_clip(68,'ranged',7,'attack',mode='arena')
        self.assertEqual(len(frames),len(meta['frame_times']))
        self.assertEqual(meta['frame_duration_ms'],50)
        self.assertEqual(meta['fixture']['scene'],'ranged')
        self.assertTrue(all(frame.size==(960,640) for frame in frames))
        again=render_species_scene(68,'ranged/attack',7,mode='arena')
        self.assertEqual([frame.tobytes() for frame in frames],[frame.tobytes() for frame in again])

    def test_showcase_arena_export_keeps_full_trial_frames_and_mode_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest=export(folder,species=(68,212),mode='arena')
            self.assertEqual(manifest['frame_size'],[960,640])
            self.assertEqual(len(manifest['clips']),4)
            self.assertEqual(manifest['render_revision'],mode_info('arena')['revision'])
            for record in manifest['clips']:
                if record['kind']=='cast':
                    self.assertTrue(record['skill_effects'])
                    self.assertEqual(record['skill_effects'][0][1],'skill_effect')
                self.assertEqual(record['mode'],'arena')
                with Image.open(Path(folder)/record['gif']) as image:
                    self.assertEqual(image.size,(960,640))
                with Image.open(Path(folder)/record['contact']) as image:
                    self.assertEqual(image.size,(4800,664))
            self.assertEqual(json.loads((Path(folder)/'manifest.json').read_text())['mode'],'arena')

    def test_public_acceptance_cli_defaults_to_arena_and_explicit_classic_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode,species,count,size in ((None,'212',6,(960,640)),('classic','19',6,(240,320))):
                destination=Path(folder)/f'{mode}.json'
                command=[sys.executable,str(ROOT/'tools/acceptance/animation_acceptance.py'),
                         '--species',species,'--output',str(destination)]
                if mode:
                    command.extend(['--mode',mode])
                result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,check=True)
                payload=json.loads(destination.read_text())
                self.assertTrue(payload['ok'],result.stdout)
                self.assertEqual(payload['checks'],count)
                self.assertEqual((payload['width'],payload['height']),size)

    def test_roster_showcase_uses_actual_six_versus_six_and_preserves_classic_helper(self):
        from skills import skill_of
        self.assertEqual(inspect.signature(roster_showcase.export).parameters['mode'].default,'classic')
        for mode,dimensions in (('arena',(960,640)),('classic',(240,320))):
            anim,result,teams=roster_showcase._scene(7,mode)
            source=copy.deepcopy(anim.events)
            self.assertEqual(tuple(len(team) for team in teams),(6,6))
            self.assertEqual(len(anim.by_idx),12)
            self.assertEqual(result['winner'],anim.events[-1][2])
            self.assertEqual(result['duration'],anim.events[-1][0])
            casts=[action for action in anim.timeline.actions if action.kind=='cast' and not action.secondary]
            self.assertTrue(casts)
            if mode=='arena':
                self.assertTrue(anim.is_arena)
                self.assertEqual(anim.battle_rows,6)
                for action in casts:
                    sid=anim.by_idx[action.attacker].piece.species_id
                    self.assertEqual(anim.events[action.source_index][4],'arena_'+arena_skills.skill_of(sid)['id'])
            else:
                self.assertFalse(anim.is_arena)
                self.assertEqual({skill_of(anim.by_idx[action.attacker].piece.species_id)['tier']
                                  for action in casts},{'signature','generic'})
            renderer=make_renderer(anim,mode)
            for seconds in (0.,casts[0].release,casts[0].impact,anim.presentation_duration,0.):
                self.assertEqual(renderer.frame(seconds).size,dimensions)
            self.assertEqual(anim.events,source)

    def test_invalid_mode_fails_at_the_public_boundary(self):
        for call in (lambda:character_catalog(mode='trial'),
                     lambda:make_preview_scene(68,'attack',mode='trial'),
                     lambda:check_action(68,'attack',mode='trial')):
            with self.assertRaisesRegex(ValueError,'mode'):
                call()


if __name__=='__main__':
    unittest.main()
