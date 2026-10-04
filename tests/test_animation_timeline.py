"""Timing, visible health, causality, deterministic seeking and finite FX budgets."""
import copy
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sim'))
sys.path.insert(0, str(ROOT / 'tools' / 'mockups'))
import status
import render_battle_gif as renderer
from animation_timeline import MAX_ACTIVE_SIGNATURES, MAX_CUTINS, CUTIN_DURATION
from combat import Battle
from roster import build_roster

ROSTER = {p.species_id: p for ps in build_roster().values() for p in ps}


class AnimationTimelineContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = renderer.Front(), renderer.Palettes(), renderer.Font16()

    def fixture(self, sid=6, lethal=False, cast=False):
        b = Battle([ROSTER[sid]], [ROSTER[143]], random.Random(19),
                   positions_a=[(2, 2)], positions_b=[(2, 1)])
        u, target = b.units
        if lethal:
            target.hp = 1
        if cast:
            u.energy = 80
        target.next_act = 1e6
        b._emit_state(target, 0.)
        b._emit_state(u, 0.)
        with patch.object(status, 'STATUS_ON', False):
            b.run()
        return b, renderer.BattleAnimation([], [], 19, *self.assets, battle=b)

    def test_lethal_projectile_arrives_before_hp_and_death_change(self):
        battle, anim = self.fixture(lethal=True)
        timing = anim.timeline.actions[0]
        self.assertLess(timing.start, timing.release)
        self.assertLess(timing.release, timing.impact)
        before = anim.presentation_state(timing.impact-.001)[1]
        landed = anim.presentation_state(timing.impact)[1]
        dead = anim.presentation_state(timing.impact+.1)[1]
        self.assertEqual(before['hp'], 1)
        self.assertIsNone(before['die_t'])
        self.assertEqual(landed['hp'], 0)
        self.assertIsNone(landed['die_t'])
        self.assertEqual(dead['die_t'], timing.impact+.1)
        view = anim._presentation_view()
        event = next(e for e in view.events if e[1] == 'attack')
        self.assertFalse(view._projectile_cancelled(event))
        # The actual flight layer must contain visible pixels before impact.
        view._ensure((timing.release+timing.impact)/2)
        image = renderer.Image.new('RGBA', (240, 320))
        view._draw_projectiles(image, (timing.release+timing.impact)/2, renderer.ParticleBudget())
        self.assertIsNotNone(image.getbbox())
        floats = [f for f in view.floats if f[3].startswith('-')]
        self.assertEqual(floats[0][0], timing.impact)
        self.assertEqual(battle.units[1].hp, 0)

    def test_legacy_lethal_attack_does_not_cancel_its_own_projectile(self):
        _, anim = self.fixture(lethal=True)
        hit = next(e for e in anim.events if e[1] == 'attack')
        anim._ensure(anim.events[-1][0])
        self.assertEqual(anim.units[hit[3]].die_t, hit[0])
        self.assertFalse(anim._projectile_cancelled(hit))

    def test_cast_energy_stays_visible_through_windup_then_uses_authoritative_state(self):
        _, anim = self.fixture(cast=True)
        timing = next(a for a in anim.timeline.actions if a.kind == 'cast')
        self.assertEqual(anim.presentation_state(timing.release-.001)[0]['energy'], 80)
        self.assertEqual(anim.presentation_state(timing.impact)[0]['energy'], 0)
        logs = [e for e in anim.presentation_events if e[1] == 'cast']
        self.assertEqual(logs[0][0], timing.impact)

    def test_unit_state_order_and_final_result_match_raw_simulation(self):
        a = [ROSTER[s] for s in (6,65,143,9,26,68)]
        b = [ROSTER[s] for s in (3,94,130,59,76,123)]
        battle = Battle(a,b,random.Random(21)); battle.run()
        original = copy.deepcopy(battle.events)
        anim = renderer.BattleAnimation([],[],21,*self.assets,battle=battle)
        for u in battle.units:
            raw = [e[2:] for e in original if e[1]=='unit_state' and e[2]==u.idx]
            presented = [e[2:] for e in anim.timeline.events if e[1]=='unit_state' and e[2]==u.idx]
            self.assertEqual(raw, presented)
        state = anim.presentation_state(anim.presentation_duration)
        self.assertEqual([(state[u.idx]['hp'],state[u.idx]['energy']) for u in battle.units],
                         [(u.hp,u.energy) for u in battle.units])
        self.assertEqual(anim._presentation_view().result, battle.events[-1][2])
        self.assertEqual(original, battle.events)

    def test_seek_speed_skip_and_independent_same_seed_render_identical_pixels(self):
        _, anim = self.fixture(cast=True)
        _, other = self.fixture(cast=True)
        moment = anim.timeline.actions[0].impact+.15
        reference = anim.playback_frame(moment).tobytes()
        anim.playback_frame(anim.presentation_duration)
        self.assertEqual(reference, anim.playback_frame(moment).tobytes())
        self.assertEqual(reference, anim.playback_frame(moment/2,speed=2).tobytes())
        self.assertEqual(reference, other.playback_frame(moment).tobytes())
        self.assertEqual(anim.playback_frame(0,skip=True).tobytes(),
                         anim.playback_frame(anim.presentation_duration).tobytes())
        for speed in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                anim.playback_frame(1,speed=speed)

    def test_death_never_precedes_its_last_landed_state(self):
        _, anim = self.fixture(lethal=True,cast=True)
        death = next(e for e in anim.presentation_events if e[1]=='die')
        state = next(e for e in anim.presentation_events if e[1]=='unit_state' and e[2]==death[2] and e[3]==0)
        self.assertGreater(death[0], state[0])
        self.assertGreaterEqual(anim.presentation_duration, death[0]+.8)

    def test_hero_rhythm_and_body_poses_are_distinct(self):
        preparations, poses = [], []
        for sid in (6,65,143):
            _, anim = self.fixture(sid,cast=True)
            action = next(a for a in anim.timeline.actions if a.kind=='cast')
            preparations.append(round(action.release-action.start,2))
            view = anim._presentation_view()
            view._ensure(action.start+(action.release-action.start)*.8)
            pose = view._authored_motion(view.units[0],action.start+(action.release-action.start)*.8)
            self.assertEqual(pose.state,'windup')
            poses.append(pose.frame)
        self.assertEqual(preparations,[.5,.45,.6])
        self.assertEqual(len(set(poses)),3)

    def test_blink_preserves_origin_then_disappears_before_destination(self):
        _, anim = self.fixture(65,cast=True)
        blink = anim.timeline.blinks[0]
        view = anim._presentation_view()
        before = blink['departure']-.001
        view._ensure(before)
        self.assertEqual(view._event_position(0,before),view.units[0].cell_px(blink['origin']))
        self.assertIsNotNone(view._unit_pose(view.units[0],before))
        between = blink['landing']-.025
        view._ensure(between)
        self.assertIsNone(view._unit_pose(view.units[0],between))
        view._ensure(blink['landing']+.025)
        self.assertEqual(view._event_position(0,blink['landing']),
                         view.units[0].cell_px(blink['target']))
        self.assertIsNotNone(view._unit_pose(view.units[0],blink['landing']+.025))

    def test_heavy_hero_has_crouch_lift_and_downward_contact(self):
        _, anim = self.fixture(143,cast=True)
        action=next(a for a in anim.timeline.actions if a.kind=='cast')
        view=anim._presentation_view()
        frames=[]
        for t in (action.start+.15,action.release-.075,action.release+.05):
            view._ensure(t)
            frames.append(view._authored_motion(view.units[0],t).frame)
        crouch,lift,contact=frames
        self.assertLess(crouch[3],100)
        self.assertLess(lift[1],-3)
        self.assertGreater(contact[1],3)

    def test_dense_battle_has_finite_cinematics_signature_tracks_and_particles(self):
        a=[ROSTER[6]]*6; b=[ROSTER[9]]*6
        battle=Battle(a,b,random.Random(31))
        for u in battle.units:
            u.energy=80
            battle._emit_state(u,0)
        battle.run()
        anim=renderer.BattleAnimation([],[],31,*self.assets,battle=battle)
        windows=anim.timeline.cutin_windows
        self.assertLessEqual(len(windows),MAX_CUTINS)
        self.assertLessEqual(sum(end-start for start,end,_ in windows),MAX_CUTINS*CUTIN_DURATION+1e-8)
        for action in anim.timeline.actions:
            if not action.secondary:
                self.assertLessEqual(action.impact-action.start,1.05+1e-8)
        for t in sorted({a.impact for a in anim.timeline.actions}):
            anim.playback_frame(t)
            metrics=anim._presentation_view().last_frame_metrics
            self.assertLessEqual(metrics['particles'],192)
            self.assertLessEqual(metrics['signature_tracks'],MAX_ACTIVE_SIGNATURES)
        combo = [a for a in anim.timeline.actions if battle.events[a.source_index][0]==0]
        self.assertEqual(len({a.start for a in combo}),1)
        self.assertEqual(len({a.impact for a in combo}),1)


if __name__=='__main__':
    unittest.main()
