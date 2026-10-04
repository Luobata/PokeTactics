"""Pixel, causality and editor isolation contracts for the eight core moves."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'/'mockups'))
from move_effects import (SUPPORTED_SPECIES, CELS, PALETTES, FAMILIES,
                          normalize_overrides, effect_profile, pixel_cel, draw_move_effect)
from profile_range import make_scene
from render_battle_gif import BattleAnimation, ParticleBudget
from animation_timeline import CORE_CAST_TRAVEL


def digest(image):
    return hashlib.sha256(image.tobytes()).hexdigest()


class MoveEffectContracts(unittest.TestCase):
    def draw(self,sid,phase='flight',progress=.7,values=None,budget=None):
        config=effect_profile(sid,normalize_overrides({sid: values or {}}))
        image=Image.new('RGBA',(240,320))
        budget=budget or ParticleBudget()
        draw_move_effect(image,sid,(45,190),(175,95),phase,progress,budget,config)
        return image,budget.used

    def test_original_material_cels_have_three_different_frames_and_four_opaque_inks(self):
        for sid in SUPPORTED_SPECIES:
            family=FAMILIES[sid]
            self.assertEqual(len(CELS[family]),3)
            images=[pixel_cel(family,i) for i in range(3)]
            self.assertEqual(len({digest(im) for im in images}),3)
            for im in images:
                self.assertEqual(set(im.getchannel('A').tobytes()),{0,255})
                opaque={im.getpixel((x,y))[:3] for y in range(9) for x in range(9) if im.getpixel((x,y))[3]}
                self.assertLessEqual(opaque,set(PALETTES[family][0]))

    def test_every_move_has_visible_distinct_charge_stream_contact_and_afterwork(self):
        phases=('charge','flight','impact','aftermath')
        for phase in phases:
            fingerprints=[]
            for sid in SUPPORTED_SPECIES:
                image,particles=self.draw(sid,phase)
                self.assertIsNotNone(image.getbbox(),(sid,phase))
                self.assertGreater(particles,0)
                self.assertLessEqual(particles,32)
                fingerprints.append(digest(image))
            self.assertEqual(len(set(fingerprints)),8,phase)
        for sid in SUPPORTED_SPECIES:
            self.assertEqual(len({digest(self.draw(sid,p)[0]) for p in phases}),4)

    def test_palette_density_and_size_are_visible_controls_not_metadata(self):
        for sid in SUPPORTED_SPECIES:
            default,full=self.draw(sid)
            vivid,_=self.draw(sid,values={'palette':'vivid'})
            sparse,low=self.draw(sid,values={'particle_density':.5})
            small,_=self.draw(sid,values={'effect_scale':.7})
            large,_=self.draw(sid,values={'effect_scale':1.3})
            self.assertNotEqual(digest(default),digest(vivid),sid)
            self.assertNotEqual(digest(default),digest(sparse),sid)
            self.assertLess(low,full,sid)
            self.assertNotEqual(digest(small),digest(large),sid)
            self.assertGreater(sum(large.getchannel('A').tobytes()),sum(small.getchannel('A').tobytes()),sid)

    def test_repeated_tracks_cannot_overrun_budget_and_dont_touch_hud(self):
        budget=ParticleBudget(23)
        image=Image.new('RGBA',(240,320))
        for sid in SUPPORTED_SPECIES*3:
            draw_move_effect(image,sid,(60,140),(180,180),'impact',.5,budget)
        self.assertEqual(budget.used,23)
        self.assertIsNone(image.crop((0,0,240,32)).getbbox())
        self.assertIsNone(image.crop((0,288,240,320)).getbbox())

    def test_override_validation_and_detached_values(self):
        raw={'6':{'palette':'vivid','effect_scale':1.2}}
        normalized=normalize_overrides(raw)
        raw['6']['palette']='classic'
        self.assertEqual(normalized[6]['palette'],'vivid')
        config=effect_profile(6,normalized)
        config['palette']='classic'
        self.assertEqual(normalized[6]['palette'],'vivid')
        for invalid in ({1:{}},{True:{}},{6:{'time_scale':2}}, {6:{'palette':'unknown'}},
                        {6:{'effect_scale':float('nan')}},{6:{'motion_scale':True}},
                        {6:{'particle_density':1.1}},{6:{'effect_scale':.69}},
                        {6:{'motion_scale':1.51}},{6:{},'6':{}},{6:[]},[]):
            with self.assertRaises(ValueError,msg=str(invalid)):
                normalize_overrides(invalid)

    def test_renderer_instances_share_real_battle_without_visual_or_state_contamination(self):
        base=make_scene(6,'dummy',7)
        battle_events=copy.deepcopy(base.events)
        settings={6:{'palette':'vivid','effect_scale':1.3,'particle_density':.5,'motion_scale':1.5}}
        # Same Battle unit objects and raw event stream, just as an editor diff.
        class BattleView:
            units=list(base.by_idx.values())
            events=base.events
        edited=BattleAnimation([],[],7,base.front,base.pal,base.font,
                               battle=BattleView(),visual_overrides=settings)
        settings[6]['palette']='classic'
        action=next(a for a in base.timeline.actions if a.attacker==0 and a.kind=='cast')
        t=(action.release+action.impact)/2
        baseline=base.playback_frame(t,show_cutins=False).tobytes()
        revised=edited.playback_frame(t,show_cutins=False).tobytes()
        self.assertNotEqual(baseline,revised)
        self.assertEqual(baseline,base.playback_frame(t,show_cutins=False).tobytes())
        edited.playback_frame(edited.presentation_duration)
        self.assertEqual(revised,edited.playback_frame(t/2,speed=2,show_cutins=False).tobytes())
        self.assertEqual(base.presentation_events,edited.presentation_events)
        self.assertEqual(base.presentation_state(t),edited.presentation_state(t))
        self.assertEqual(base.events,battle_events)
        self.assertEqual(edited.visual_config(6)['palette'],'vivid')

    def test_all_eight_real_skills_expose_flight_and_land_hp_at_authoritative_impact(self):
        for sid in SUPPORTED_SPECIES:
            anim=make_scene(sid,'dummy',7)
            action=next(a for a in anim.timeline.actions if a.attacker==0 and a.kind=='cast')
            self.assertGreaterEqual(action.impact-action.release+1e-8,CORE_CAST_TRAVEL)
            before=anim.presentation_state(action.impact-.001)[action.target]['hp']
            after=anim.presentation_state(action.impact)[action.target]['hp']
            expected=[e[3] for e in anim.timeline.events
                      if e[1]=='unit_state' and e[2]==action.target and abs(e[0]-action.impact)<1e-8][-1]
            self.assertEqual(after,expected,sid)
            # Water can miss; Electric vs the ground-type dummy is immune.
            damage=anim.events[action.source_index][6]
            self.assertGreaterEqual(before-after,damage,sid)
            for t in (action.start+.15,(action.release+action.impact)/2,action.impact+.1):
                frame=anim.playback_frame(t,show_cutins=False)
                self.assertEqual(frame.size,(240,320))
                metrics=anim._presentation_view().last_frame_metrics
                self.assertLessEqual(metrics['particles'],192)
                self.assertLessEqual(metrics['signature_tracks'],3)

    def test_motion_scale_changes_native_body_pose_without_retiming(self):
        for sid in SUPPORTED_SPECIES:
            small=make_scene(sid,'dummy',7,visual_overrides={sid:{'motion_scale':.5}})
            large=make_scene(sid,'dummy',7,visual_overrides={sid:{'motion_scale':1.5}})
            action=next(a for a in small.timeline.actions if a.attacker==0 and a.kind=='cast')
            t=action.start+(action.release-action.start)*.55
            a,b=small._presentation_view(),large._presentation_view()
            a._ensure(t);b._ensure(t)
            self.assertNotEqual(a._authored_motion(a.units[0],t).frame,
                                b._authored_motion(b.units[0],t).frame,sid)
            self.assertEqual(small.presentation_events,large.presentation_events)


if __name__=='__main__':
    unittest.main()
