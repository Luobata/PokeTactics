"""Actual skill packets drive links, without early feedback or moved endpoints."""
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools/mockups'), str(ROOT / 'sim')]
from profile_range import make_scene, make_signature_scene, _assets
from render_battle_gif import BattleAnimation, ParticleBudget
from move_effects import draw_skill_effect, draw_move_effect
from combat import Battle
from roster import build_roster


class SignaturePresentationContracts(unittest.TestCase):
    def test_real_effects_are_visible_only_at_their_owned_impact(self):
        for sid, effect in ((9, 'side_hit'), (3, 'heal'), (26, 'side_hit'),
                            (94, 'energy_drain'), (76, 'flinch')):
            anim = make_signature_scene(sid)
            action = next(a for a in anim.timeline.actions if a.kind == 'cast')
            with self.subTest(sid=sid), patch('render_battle_gif.draw_skill_effect', wraps=draw_skill_effect) as draw:
                anim.playback_frame(action.impact-.001, show_cutins=False)
                self.assertEqual(draw.call_count, 0)
                first = anim.playback_frame(action.impact+.05, show_cutins=False)
                self.assertIn(effect, [call.args[2] for call in draw.call_args_list])
                self.assertLessEqual(anim._presentation_view().last_frame_metrics['particles'], 192)
                for call in draw.call_args_list:
                    self.assertGreaterEqual(call.args[5], 0)
                anim.playback_frame(0., show_cutins=False)
                self.assertEqual(first.tobytes(), anim.playback_frame(action.impact+.05, show_cutins=False).tobytes())

    def test_energy_return_uses_logged_caster_position_before_same_tick_push(self):
        pieces = {p.species_id: p for ps in build_roster().values() for p in ps}
        battle = Battle([pieces[94]], [pieces[3], pieces[9]], random.Random(7))
        for unit, position in zip(battle.units, ((2,2), (2,1), (1,2))):
            unit.pos = position
            unit.hp = unit.max_hp = 1000
            unit.energy = 80
        battle.events = [(0., 'deploy', u.idx, u.pos) for u in battle.units]
        for unit in battle.units:
            battle._emit_state(unit, 0.)
        with patch('status.on_hit'), patch.object(battle.rng, 'randrange', return_value=0):
            battle._strike(battle.units[0], battle.units[1], .1)
            battle._strike(battle.units[2], battle.units[0], .1)
        self.assertNotEqual(battle.units[0].pos, (2,2))
        anim = BattleAnimation([], [], 7, *_assets(), battle=battle)
        action = next(a for a in anim.timeline.actions if a.attacker == 0 and a.kind == 'cast')
        with patch('render_battle_gif.draw_skill_effect', wraps=draw_skill_effect) as draw:
            anim.playback_frame(action.impact, show_cutins=False)
        call = next(call for call in draw.call_args_list if call.args[2] == 'energy_drain')
        x,y = anim.units[0].cell_px((2,2))
        self.assertEqual(call.args[4], (x+20,y+16))

    def test_basic_projectiles_consume_species_attachment_points(self):
        for sid, required in ((6, ('mouth',)), (9, ('left_muzzle','right_muzzle')),
                               (3, ('left_vine_tip',))):
            anim = make_scene(sid, 'dummy', 7)
            action = next(a for a in anim.timeline.actions if a.attacker == 0 and a.kind == 'attack')
            with self.subTest(sid=sid), patch('render_battle_gif.draw_move_effect', wraps=draw_move_effect) as draw:
                anim.playback_frame(action.release+.05, show_cutins=False)
            call = next(c for c in draw.call_args_list if c.args[4]=='flight' and c.kwargs.get('basic'))
            self.assertTrue(all(name in call.kwargs['anchors'] for name in required))
            default, attached = Image.new('RGBA',(240,320)), Image.new('RGBA',(240,320))
            draw_move_effect(default, *call.args[1:6], ParticleBudget(), basic=True)
            draw_move_effect(attached, *call.args[1:6], ParticleBudget(), basic=True, anchors=call.kwargs['anchors'])
            self.assertNotEqual(default.tobytes(), attached.tobytes())

    def test_zero_heal_and_zero_energy_do_not_draw_success_feedback(self):
        for sid, effect, payload in ((3,'heal',{'amount':0}), (94,'energy_drain',{'stolen':0})):
            frame = Image.new('RGBA',(240,320))
            draw_skill_effect(frame,sid,effect,(50,150),(180,100),.1,ParticleBudget(),payload=payload)
            self.assertIsNone(frame.getbbox())


if __name__ == '__main__':
    unittest.main()
