"""Real pixels, attachment tracks and event isolation for the three part rigs."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

from PIL import ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/mockups'))
from character_rigs import catalog, manifest_data, sample_rig, render_rig, PADDING
from motion import MotionSystem, Pose, REST, species_motion, transform
from profile_range import make_scene


class CharacterRigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenes = {sid:make_scene(sid,'dummy',7) for sid in (6,9,3)}

    def source(self,sid):
        return self.scenes[sid]._board_sprite(sid,3)

    def test_catalog_distinguishes_delivered_parts_from_plans(self):
        data = catalog()
        self.assertEqual({int(sid) for sid,rig in data.items() if rig['implemented']},{6,9,3})
        self.assertEqual(len(data),8)
        structures = set()
        for sid,rig in data.items():
            names = tuple(part['name'] for part in rig['parts'])
            structures.add(names)
            self.assertEqual(len(names),len(set(names)))
            self.assertTrue(all(part['label'] and len(part['pivot_percent'])==2 for part in rig['parts']))
            self.assertTrue(rig['anchors'])
            self.assertLessEqual(len(names),rig['limits']['parts'])
            self.assertEqual(bool(rig['actions']['attack']),rig['implemented'])
        self.assertEqual(len(structures),8)
        self.assertEqual(json.loads(json.dumps(manifest_data()))['species'],data)
        data['6']['parts'][0]['label']='changed'
        self.assertEqual(catalog()['6']['parts'][0]['label'],'身体')

    def test_each_delivered_rig_has_distinct_attack_and_cast_pixels(self):
        for sid in (6,9,3):
            attack=render_rig(self.source(sid),sid,'attack','strike',.5)
            cast=render_rig(self.source(sid),sid,'cast','strike',.5)
            self.assertNotEqual(attack.tobytes(),cast.tobytes(),sid)
            self.assertNotEqual(sample_rig(sid,'attack','strike',.5),sample_rig(sid,'cast','strike',.5),sid)
            poses=[render_rig(self.source(sid),sid,'attack',state,p).tobytes()
                   for state,p in [('windup',0),('windup',1),('strike',.5),('recover',1)]]
            self.assertGreaterEqual(len(set(poses)),3,sid)

    def test_real_claw_cannons_and_vine_anchors_move(self):
        for sid,names in ((6,('claw',)),(9,('left_muzzle','right_muzzle')),
                          (3,('left_vine_tip','right_vine_tip'))):
            before=render_rig(self.source(sid),sid,'attack','windup',0)
            after=render_rig(self.source(sid),sid,'attack','strike',.5)
            for name in names:
                self.assertNotEqual(before.info['rig_anchors'][name],after.info['rig_anchors'][name],(sid,name))
            self.assertEqual(before.info['foot_anchor'],after.info['foot_anchor'])
        flower=render_rig(self.source(3),3,'cast','windup',1)
        rest=render_rig(self.source(3),3,'cast','windup',0)
        self.assertLess(flower.info['rig_anchors']['flower_focus'][1],rest.info['rig_anchors']['flower_focus'][1])

    def test_extended_vines_survive_source_rectangle_without_clipping(self):
        source=self.source(3)
        image=render_rig(source,3,'attack','strike',.5,facing=-1)
        self.assertLess(image.getbbox()[0],PADDING+source.getbbox()[0])
        self.assertIsNotNone(image.crop((0,0,PADDING,image.height)).getbbox())
        box=image.getbbox()
        self.assertGreater(box[0],0)
        self.assertGreater(box[1],0)
        self.assertLess(box[2],image.width)
        self.assertLess(box[3],image.height)
        self.assertEqual(image.size,(source.width+2*PADDING,source.height+2*PADDING))

    def test_mirror_is_exact_and_attachment_coordinates_follow_it(self):
        for sid in (6,9,3):
            left=render_rig(self.source(sid),sid,'attack','strike',.5,facing=-1)
            right=render_rig(self.source(sid),sid,'attack','strike',.5,facing=1)
            self.assertEqual(ImageOps.mirror(left).tobytes(),right.tobytes())
            for name,xy in left.info['rig_anchors'].items():
                self.assertEqual(right.info['rig_anchors'][name],[right.width-xy[0],xy[1]])
            poses=sample_rig(sid,'attack','strike',.5,-1)
            mirrored=sample_rig(sid,'attack','strike',.5,1)
            for name,p in poses.items():
                self.assertEqual(p['dx'],-mirrored[name]['dx'])
                self.assertEqual(p['angle'],-mirrored[name]['angle'])

    def test_source_palette_alpha_and_input_are_preserved(self):
        for sid in (6,9,3):
            source=self.source(sid)
            original=source.tobytes()
            colors={pixel[:3] for pixel in source.getdata() if pixel[3]}
            for kind in ('attack','cast'):
                image=render_rig(source,sid,kind,'strike',.5)
                self.assertLessEqual({pixel[:3] for pixel in image.getdata() if pixel[3]},colors)
                self.assertLessEqual(set(image.getchannel('A').tobytes()),{0,255})
            self.assertEqual(source.tobytes(),original)
        with self.assertRaises(ValueError):
            sample_rig(6,'attack','strike',math.nan)

    def test_whole_body_pose_preserves_named_anchors_and_padded_canvas(self):
        for sid in (6,9,3):
            index=len(species_motion[sid]['strike'])//2
            pose=Pose('strike',index,(3,1,110,94,8,0),action_kind='attack')
            image=transform(self.source(sid),sid,pose)
            self.assertIn('foot_anchor',image.info)
            self.assertIn('rig_anchors',image.info)
            self.assertGreater(image.width,self.source(sid).width)
            self.assertLessEqual(max(image.size),128)

    def test_renderer_seeks_repeat_same_pixels_and_leave_authority_unchanged(self):
        for sid in (6,9,3):
            anim=make_scene(sid,'dummy',7)
            events=copy.deepcopy(anim.events)
            for kind in ('attack','cast'):
                action=next(a for a in anim.timeline.actions if a.attacker==0 and a.kind==kind and not a.secondary)
                t=action.release+.05
                image=anim.playback_frame(t,show_cutins=False).tobytes()
                view=anim._presentation_view()
                pose=MotionSystem.resolve(view,view.units[0],t)
                self.assertEqual(pose.action_kind,kind)
                anim.playback_frame(anim.presentation_duration,show_cutins=False)
                self.assertEqual(image,anim.playback_frame(t/2,speed=2,show_cutins=False).tobytes())
            self.assertEqual(anim.events,events)

    def test_freeze_stops_part_track_and_death_overrides_it(self):
        anim=make_scene(6,'dummy',7)
        action=next(a for a in anim.timeline.actions if a.attacker==0 and a.kind=='attack')
        t=action.start+.1
        anim.playback_frame(t,show_cutins=False)
        view=anim._presentation_view();unit=view.units[0]
        unit.statuses['freeze']=t
        self.assertEqual(MotionSystem.resolve(view,unit,t),MotionSystem.resolve(view,unit,t+.2))
        unit.die_t=t+.1
        pose=MotionSystem.resolve(view,unit,t+.2)
        self.assertEqual(pose.state,'death')
        self.assertIsNone(pose.action_kind)
        self.assertIsNone(render_rig(self.source(6),6,'attack','death',.5))


if __name__=='__main__':
    unittest.main()
