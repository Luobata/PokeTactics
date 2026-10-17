"""Fire Blast cels own one move while replay damage stays authoritative."""
import copy
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/mockups'),
               str(ROOT / 'tools/acceptance')]
import animation_preview
import arena
import arena_skills
import presentation_modes
import retro_moves
import retro_attacks
import web_battle
from arena_preview_scene import make_preview_scene
from combat import Battle
from decoders import Front, Palettes, Font16
from move_effects import DEFAULT_VISUAL
from render_battle_gif import BattleAnimation
from web_battle import WebBattleRenderer


class RetroMovePresentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = Front(), Palettes(), Font16()
        cls.templates = arena.build_templates()

    def native(self, settings=None):
        overrides = {6: settings} if settings is not None else None
        anim = make_preview_scene(6, 'cast', visual_overrides=overrides)
        event = next(e for e in anim.timeline.events
                     if e[1] == 'cast' and e[4] == 'arena_flame_storm')
        timing = anim.timeline.action_by_event[id(event)]
        return anim, WebBattleRenderer(anim), timing

    def layer(self, renderer):
        return Image.new('RGBA', (renderer.width, renderer.height))

    def other_action(self, *, move=None, learned=None, sid=6):
        # Resolve real damage packets. The arena currently has no Fire TM, so
        # flamethrower checks the shared non-native Fire cast dispatch directly.
        battle = Battle([copy.copy(self.templates[sid])],
                        [copy.copy(self.templates[9])], random.Random(7),
                        positions_a=[(2, 3)], positions_b=[(2, 2)],
                        learned_a=[learned], ruleset='arena_v1',
                        stat_mode='budget_v1')
        for unit in battle.units:
            unit.hp = unit.max_hp = 5000
            battle._emit_state(unit, 0.)
        source, target = battle.units
        if move is None:
            battle._strike(source, target, .5)
        else:
            damage = battle._move_damage(source, target, move)
            battle._land_hit(source, target, damage, .5, move=move,
                             primary=True, cast=True)
        anim = BattleAnimation([], [], 7, *self.assets, battle=battle)
        kind = 'cast' if move is not None or learned else 'attack'
        event = next(e for e in anim.timeline.events if e[1] == kind)
        return anim, WebBattleRenderer(anim), anim.timeline.action_by_event[id(event)]

    def test_native_has_one_cel_track_in_all_four_phases_without_generic_overlay(self):
        anim, renderer, timing = self.native()
        original = copy.deepcopy(anim.events)
        samples = ((timing.start + .20, 'windup'),
                   (timing.release + .05, 'flight'),
                   (timing.impact + .08, 'impact'),
                   (timing.impact + .32, 'aftermath'))
        for moment, phase in samples:
            with self.subTest(phase=phase):
                renderer.view._ensure(moment)
                image = self.layer(renderer)
                with patch.object(retro_moves, 'draw_fire_blast',
                                  wraps=retro_moves.draw_fire_blast) as draw, \
                     patch.object(renderer, '_configured_material') as material, \
                     patch.object(renderer, '_motif') as motif:
                    renderer._draw_actions(image, moment)
                self.assertEqual(draw.call_count, 1)
                self.assertEqual(draw.call_args.args[3], phase)
                self.assertFalse(draw.call_args.kwargs.get('secondary', False))
                material.assert_not_called()
                motif.assert_not_called()
                self.assertIsNotNone(image.getchannel('A').getbbox())
        self.assertEqual(anim.events, original)
        self.assertEqual(arena_skills.SKILLS[6]['name'], '大字爆炎')
        self.assertEqual(arena_skills.SKILLS[6]['power'], 70)
        self.assertEqual(arena_skills.SKILLS[6]['id'], 'flame_storm')

    def test_basic_authored_track_and_other_cast_dispatch_do_not_borrow_fire_blast(self):
        typhlosion = make_preview_scene(157, 'cast')
        other_native = next(t for t in typhlosion.timeline.actions if t.kind == 'cast')
        fixtures = (self.other_action(),
                    self.other_action(move={'name': 'flamethrower',
                                            'type': 'FIRE', 'power': 35}),
                    self.other_action(sid=26, learned='thunderbolt'),
                    (typhlosion, WebBattleRenderer(typhlosion), other_native))
        for anim, renderer, timing in fixtures:
            with self.subTest(event=anim.events[timing.source_index]):
                renderer.view._ensure(timing.impact + .08)
                image = self.layer(renderer)
                with patch.object(retro_moves, 'draw_fire_blast',
                                  wraps=retro_moves.draw_fire_blast) as retro, \
                     patch.object(renderer, '_configured_material',
                                  wraps=renderer._configured_material) as material, \
                     patch.object(retro_attacks, 'draw', wraps=retro_attacks.draw) as basic:
                    renderer._draw_actions(image, timing.impact + .08)
                retro.assert_not_called()
                authored_eruption = (timing.kind == 'cast' and
                                    anim.events[timing.source_index][4] == 'arena_cinder_eruption')
                self.assertEqual(material.called, timing.kind == 'cast' and not authored_eruption)
                self.assertEqual(basic.called, timing.kind == 'attack')
                self.assertIsNotNone(image.getchannel('A').getbbox())

    def test_primary_launch_uses_visible_mouth_and_holds_recorded_target_cell(self):
        _, renderer, timing = self.native()
        moment = timing.release + .05
        renderer.view._ensure(timing.release)
        source = renderer.view.units[timing.attacker]
        shown = next(row for row in renderer._shown(timing.release)
                     if row[1].u.idx == timing.attacker)
        _, unit, x, y, _ = shown
        mouth = renderer._unit_art(unit, x, y, timing.release)[3]['mouth']
        target = renderer.cell_point(timing.target_pos)
        expected_target = (target[0], target[1] - 35)
        with patch.object(retro_moves, 'draw_fire_blast',
                          wraps=retro_moves.draw_fire_blast) as draw:
            renderer._draw_actions(self.layer(renderer), moment)
        self.assertEqual(draw.call_args.args[1], mouth)
        self.assertEqual(draw.call_args.args[2], expected_target)
        # Seeking past release must not attach an in-flight ball to a new pose.
        later = timing.impact + .08
        renderer.view._ensure(later)
        self.assertEqual(renderer._action_emitters(source, timing, 'flight', later), [mouth])

    def test_main_and_real_side_recipients_change_hp_only_at_authoritative_impact(self):
        anim, renderer, timing = self.native()
        side_hits = [e for e in anim.timeline.events
                     if e[1] == 'skill_effect' and e[4:6] == ('flame_storm', 'side_hit')]
        self.assertEqual(len(side_hits), 2)
        recipients = {timing.target, *(e[3] for e in side_hits)}
        before = anim.presentation_state(timing.impact - .001)
        at = anim.presentation_state(timing.impact)
        for idx in recipients:
            self.assertEqual(before[idx]['hp'], anim.by_idx[idx].max_hp)
            self.assertLess(at[idx]['hp'], before[idx]['hp'])
        unaffected = set(range(3, 7)) - recipients
        self.assertEqual(len(unaffected), 1)
        for idx in unaffected:
            self.assertEqual(at[idx]['hp'], before[idx]['hp'])
        renderer.view._ensure(timing.impact - .001)
        with patch.object(retro_moves, 'draw_fire_blast') as draw:
            renderer._draw_outcomes(self.layer(renderer), timing.impact - .001)
            draw.assert_not_called()
        renderer.frame(timing.impact - .001)
        self.assertEqual({idx: renderer.view.units[idx].hp for idx in recipients},
                         {idx: before[idx]['hp'] for idx in recipients})
        renderer.frame(timing.impact)
        self.assertEqual({idx: renderer.view.units[idx].hp for idx in recipients},
                         {idx: at[idx]['hp'] for idx in recipients})
        self.assertTrue(all(e[0] == timing.impact for e in side_hits))

    def test_secondary_cels_follow_recorded_recipients_and_end_with_the_main_window(self):
        anim, renderer, timing = self.native()
        side_hits = [e for e in anim.timeline.events
                     if e[1] == 'skill_effect' and e[4:6] == ('flame_storm', 'side_hit')]
        expected = set()
        for event in side_hits:
            point = renderer.cell_point(event[6]['target_pos'])
            expected.add((point[0], point[1] - 34))
            self.assertEqual(event[6]['cast_index'], timing.source_index)
        for age, phase in ((.08, 'impact'), (.32, 'aftermath'),
                           (.55, 'aftermath'), (.75, 'aftermath')):
            renderer.view._ensure(timing.impact + age)
            # Subsequent movement cannot move a recorded contact to a new cell.
            for event in side_hits:
                renderer.view.units[event[3]].from_px = (10, 10)
                renderer.view.units[event[3]].to_px = (10, 10)
            with patch.object(retro_moves, 'draw_fire_blast',
                              wraps=retro_moves.draw_fire_blast) as draw:
                renderer._draw_outcomes(self.layer(renderer), timing.impact + age)
            self.assertEqual(draw.call_count, 2)
            self.assertEqual({call.args[2] for call in draw.call_args_list}, expected)
            self.assertTrue(all(call.args[3] == phase and call.kwargs['secondary']
                                for call in draw.call_args_list))
        with patch.object(retro_moves, 'draw_fire_blast') as draw:
            renderer._draw_outcomes(self.layer(renderer),
                                    timing.impact + retro_moves.FIRE_BLAST_LIFETIME + .001)
            draw.assert_not_called()

    def test_fire_blast_spark_tail_lasts_longer_without_delaying_damage_or_other_moves(self):
        anim, renderer, timing = self.native()
        self.assertEqual(retro_moves.CONTACT_DURATION, .22)
        self.assertEqual(retro_moves.FIRE_BLAST_LIFETIME, .8)
        landed_hp = {idx: row['hp'] for idx, row in
                     anim.presentation_state(timing.impact).items()}
        # At .5s the core has ended, but late sparks still visibly belong to
        # this real hit. Sampling the tail cannot apply a second damage packet.
        for age in (.55, .75):
            moment = timing.impact + age
            renderer.view._ensure(moment)
            image = self.layer(renderer)
            with patch.object(retro_moves, 'draw_fire_blast',
                              wraps=retro_moves.draw_fire_blast) as draw:
                renderer._draw_actions(image, moment)
            self.assertEqual(draw.call_count, 1)
            self.assertEqual(draw.call_args.args[3], 'aftermath')
            expected = (age - retro_moves.CONTACT_DURATION) / (
                retro_moves.FIRE_BLAST_LIFETIME - retro_moves.CONTACT_DURATION)
            self.assertAlmostEqual(draw.call_args.args[4], expected)
            self.assertIsNotNone(image.getchannel('A').getbbox())
            self.assertEqual({idx: row['hp'] for idx, row in
                              anim.presentation_state(moment).items()}, landed_hp)
        for age in (retro_moves.FIRE_BLAST_LIFETIME, 1.):
            with patch.object(retro_moves, 'draw_fire_blast') as draw:
                renderer._draw_actions(self.layer(renderer), timing.impact + age)
                draw.assert_not_called()
        _, generic, other = self.other_action(
            move={'name': 'flamethrower', 'type': 'FIRE', 'power': 35})
        moment = other.impact + .55
        generic.view._ensure(moment)
        image = self.layer(generic)
        with patch.object(generic, '_configured_material') as material:
            generic._draw_actions(image, moment)
        material.assert_not_called()
        self.assertIsNone(image.getchannel('A').getbbox())

    def test_zero_damage_side_packet_has_no_secondary_fire_blast(self):
        anim, renderer, timing = self.native()
        event = copy.deepcopy(next(e for e in anim.timeline.events
                                   if e[1] == 'skill_effect'
                                   and e[4:6] == ('flame_storm', 'side_hit')))
        event[6]['damage'] = 0
        renderer.view._ensure(timing.impact + .08)
        # Only exercise the presentation guard; simulation records stay intact.
        with patch.object(anim.timeline, 'recent_events', return_value=[event]), \
             patch.object(retro_moves, 'draw_fire_blast') as draw:
            image = self.layer(renderer)
            renderer._draw_outcomes(image, timing.impact + .08)
        draw.assert_not_called()
        self.assertIsNone(image.getchannel('A').getbbox())

    def test_settings_change_pixels_without_changing_actions_or_outcomes(self):
        anim, renderer, timing = self.native()
        original_events = copy.deepcopy(anim.events)
        moments = (timing.start + .20, timing.release + .05,
                   timing.impact + .08, timing.impact + .32)
        base = b''.join(renderer.frame(t).tobytes() for t in moments)
        for name, value in (('palette', 'vivid'), ('effect_scale', 1.3),
                            ('particle_density', .5), ('motion_scale', .5)):
            with self.subTest(control=name):
                edited, edited_renderer, edited_timing = self.native({name: value})
                self.assertEqual(timing, edited_timing)
                self.assertEqual(edited.events, original_events)
                self.assertEqual(edited.presentation_state(timing.impact),
                                 anim.presentation_state(timing.impact))
                pixels = b''.join(edited_renderer.frame(t).tobytes() for t in moments)
                self.assertNotEqual(base, pixels)
        self.assertEqual(anim.events, original_events)

    def test_rendering_and_backwards_seek_are_deterministic_without_state_mutation(self):
        anim, renderer, timing = self.native()
        original_events = copy.deepcopy(anim.events)
        final_state = [(u.hp, u.energy, u.pos) for u in anim.by_idx.values()]
        moments = (timing.start + .20, timing.release + .05,
                   timing.impact + .08, timing.impact + .32)
        frames = [renderer.frame(t).tobytes() for t in moments]
        renderer.frame(anim.presentation_duration)
        for moment, pixels in zip(moments, frames):
            self.assertEqual(renderer.frame(moment).tobytes(), pixels)
        self.assertEqual(anim.events, original_events)
        self.assertEqual([(u.hp, u.energy, u.pos) for u in anim.by_idx.values()], final_state)
        self.assertEqual(anim._cursor, 0)
        self.assertFalse(renderer._frame_art)

    def test_windup_and_early_flight_do_not_paint_the_targets_impact_glyph(self):
        source, target = (100, 230), (600, 110)
        for phase in ('windup', 'flight'):
            with self.subTest(phase=phase):
                image = Image.new('RGBA', (720, 360))
                retro_moves.draw_fire_blast(image, source, target, phase, .35,
                                           DEFAULT_VISUAL)
                box = image.getchannel('A').getbbox()
                self.assertIsNotNone(box)
                self.assertLess(box[2], target[0] - 150)
                contact = image.crop((target[0] - 70, target[1] - 70,
                                      target[0] + 70, target[1] + 70))
                self.assertIsNone(contact.getchannel('A').getbbox())

    def test_pixel_cels_have_bounded_palette_and_secondary_is_smaller(self):
        source, target = (100, 230), (600, 110)
        primary = Image.new('RGBA', (720, 360))
        secondary = Image.new('RGBA', primary.size)
        retro_moves.draw_fire_blast(primary, source, target, 'impact', .35, DEFAULT_VISUAL)
        retro_moves.draw_fire_blast(secondary, source, target, 'impact', .35,
                                   DEFAULT_VISUAL, secondary=True)
        box = primary.getchannel('A').getbbox()
        small = secondary.getchannel('A').getbbox()
        self.assertIsNotNone(box)
        self.assertIsNotNone(small)
        self.assertLess(small[2] - small[0], box[2] - box[0])
        self.assertLess(small[3] - small[1], box[3] - box[1])
        colors = primary.getcolors(maxcolors=17)
        self.assertIsNotNone(colors)
        self.assertLessEqual(len(colors) - 1, 16)
        self.assertTrue(box[0] < target[0] < box[2])
        self.assertTrue(box[1] < target[1] < box[3])
        self.assertGreater(box[0], source[0] + 200)

    def test_new_cel_source_and_render_revision_invalidate_public_preview_cache(self):
        self.assertEqual(presentation_modes.WEB_BATTLE_REVISION, 'web-arena-v18-family-effects-r1')
        request = animation_preview.normalize_preview({'species': 6, 'kind': 'cast'})
        before = animation_preview.source_revision()
        cel_path = Path(retro_moves.__file__).resolve()
        read_bytes = Path.read_bytes
        def altered_bytes(path):
            raw = read_bytes(path)
            return raw + b'\n# changed authored cel' if path.resolve() == cel_path else raw
        with patch.object(Path, 'read_bytes', autospec=True, side_effect=altered_bytes):
            after = animation_preview.source_revision()
        self.assertNotEqual(before, after)
        self.assertNotEqual(animation_preview._key(request, before),
                            animation_preview._key(request, after))


if __name__ == '__main__':
    unittest.main()
