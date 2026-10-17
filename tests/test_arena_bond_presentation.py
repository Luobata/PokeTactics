"""Actual bond packets keep distinct telemetry and independent visual deadlines."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/mockups'), str(ROOT / 'tools/acceptance')]
import arena_vfx
from combination_view import battle_summary
from web_battle import WebBattleRenderer
from session_save import SessionCodec


def packet(t, key, effect, *, source=0, target=0, **payload):
    return (t, 'combo_effect', source, target, key, effect,
            {'source_pos': (1, 1), 'target_pos': (1, 2), **payload})


class ArenaBondPresentation(unittest.TestCase):
    def test_new_controls_are_counted_separately_and_survive_compact_reports(self):
        events = [packet(1, 'bond_frostline', 'chill', target=2, applied=True, fraction=.15, duration=3),
                  packet(2, 'bond_spirit', 'root', target=2, applied=True, duration=1.5),
                  packet(2.1, 'bond_spirit', 'root', target=2, applied=False, duration=1.5),
                  packet(3, 'bond_mindsong', 'energy', target=1, amount=3, requested=5),
                  packet(3.1, 'bond_dragon_pressure', 'vulnerability', target=2, fraction=.12),
                  packet(4, 'bond_frostline', 'expire', target=2)]
        summary = battle_summary(events, {0: 0, 1: 0, 2: 1})
        self.assertEqual((summary['triggers'], summary['total_controls'], summary['total_energy'],
                          summary['total_vulnerable'], summary['total_damage']), (4, 2, 3, 1, 0))
        SessionCodec._validate_combination_summary(summary)
        from combination_view import field_summary
        report = {'effect_version': 1, 'combinations': summary,
                  'enemy_combinations': battle_summary(events, {0: 0, 1: 0, 2: 1}, 1),
                  'fields': field_summary([], {}), 'enemy_fields': field_summary([], {})}
        compact = SessionCodec._pack_report(report)
        self.assertEqual(compact['combinations']['version'], 2)
        self.assertEqual(compact['enemy_combinations']['version'], 1)
        SessionCodec()._decode_report_effects(compact, SimpleNamespace(is_arena=True))
        self.assertEqual(compact, report)
        tampered = copy.deepcopy(summary)
        tampered['total_controls'] += 1
        with self.assertRaises(ValueError):
            SessionCodec._validate_combination_summary(tampered)

    def test_control_badges_follow_recorded_lifetime_and_rewind(self):
        events = [packet(1, 'bond_frostline', 'chill', target=0, applied=True, duration=3),
                  packet(2, 'bond_spirit', 'root', target=0, applied=True, duration=1.5),
                  packet(4, 'bond_frostline', 'expire', target=0)]
        renderer = WebBattleRenderer.__new__(WebBattleRenderer)
        renderer.anim = SimpleNamespace(events=events, timeline=SimpleNamespace(
            recent_events=lambda t, window: [e for e in events if t-window <= e[0] <= t]))
        renderer.view = SimpleNamespace(units={})
        self.assertEqual(set(renderer._active_identity_effects(2.5, 0)), {'chill', 'root'})
        self.assertEqual(set(renderer._active_identity_effects(3.6, 0)), {'chill'})
        self.assertFalse(renderer._active_identity_effects(4.1, 0))
        self.assertEqual(set(renderer._active_identity_effects(1.5, 0)), {'chill'})

    def test_new_bond_feedback_is_visible_and_distinct(self):
        outputs = []
        for key, effect, payload in (
                ('bond_frostline', 'chill', {'fraction': .15, 'duration': 3}),
                ('bond_spirit', 'root', {'duration': 1.5}),
                ('bond_mindsong', 'energy', {'amount': 3}),
                ('bond_dragon_pressure', 'vulnerability', {'fraction': .12})):
            image = Image.new('RGBA', (160, 120))
            arena_vfx.draw_combination(image, key, effect, (20, 60), (100, 60), .5, payload)
            self.assertIsNotNone(image.getbbox(), key)
            outputs.append(image.tobytes())
            self.assertIn(arena_vfx.COMBINATION_NAMES[key], arena_vfx.combination_label(key, effect, payload))
        self.assertEqual(len(set(outputs)), 4)

    def test_actual_friend_values_use_existing_summary_fields_without_bonus_damage(self):
        events = [packet(1, 'bond_erosion', 'energy', amount=3, requested=8),
                  packet(2, 'bond_combo', 'tempo', gained=1, stacks=1, fraction=.05),
                  packet(3, 'bond_guard', 'shield', amount=20),
                  packet(4, 'bond_guard', 'absorb', amount=9),
                  packet(5, 'bond_inspiration', 'offense_buff', source=1, target=0,
                         recipient_idx=0, fraction=.10),
                  packet(6, 'bond_guard', 'expire', amount=11),
                  packet(7, 'bond_erosion', 'energy', source=2, target=2, amount=8)]
        original = copy.deepcopy(events)
        result = battle_summary(events, {0: 0, 1: 0, 2: 1})
        self.assertEqual((result['triggers'], result['total_energy'], result['total_shield'],
                          result['absorbed'], result['total_tempo_stacks'],
                          result['total_offense_buffs']), (4, 3, 20, 9, 1, 1))
        self.assertEqual((result['total_damage'], result['damage_absorbed']), (0, 0))
        self.assertEqual({row['id'] for row in result['by_key']},
                         {'bond_erosion', 'bond_combo', 'bond_guard', 'bond_inspiration'})
        self.assertEqual(events, original)

    def test_interleaved_buff_expiry_keeps_other_stronger_track_and_rewinds(self):
        events = [packet(1, 'bond_inspiration', 'offense_buff', source=1, target=0,
                         fraction=.10, duration=3),
                  packet(2, 'native_inspiration', 'offense_buff', source=2, target=0,
                         fraction=.25, duration=3),
                  packet(4, 'bond_inspiration', 'expire', target=0),
                  packet(4.5, 'bond_inspiration', 'offense_buff', source=1, target=0,
                         fraction=.15, duration=3),
                  packet(5, 'native_inspiration', 'expire', target=0)]
        original = copy.deepcopy(events)
        anim = SimpleNamespace(events=events, timeline=SimpleNamespace(
            recent_events=lambda t, window: [event for event in events if t-window <= event[0] <= t]))
        renderer = WebBattleRenderer.__new__(WebBattleRenderer)
        renderer.anim = anim
        renderer.view = SimpleNamespace(units={})
        expected = [(1.1, 'bond_inspiration', .10), (2.1, 'native_inspiration', .25),
                    (4.1, 'native_inspiration', .25), (4.6, 'native_inspiration', .25),
                    (5.1, 'bond_inspiration', .15)]
        for t, key, fraction in expected:
            with self.subTest(time=t):
                direct = arena_vfx.active_offense(events, t, 0)['offense_buff']
                self.assertEqual((direct[4], direct[6]['fraction']), (key, fraction))
                self.assertEqual(renderer._active_identity_effects(t, 0)['offense_buff'], direct)
                self.assertNotIn('offense_buff', arena_vfx.active_offense(events, t, 1))
        self.assertNotIn('offense_buff', renderer._active_identity_effects(7.5, 0))
        self.assertEqual(renderer._active_identity_effects(1.1, 0)['offense_buff'][4], 'bond_inspiration')
        self.assertEqual(events, original)

    def test_tempo_sources_keep_their_own_reset_and_actual_total_fraction(self):
        events = [packet(1, 'metronome', 'tempo', stacks=2, gained=1, fraction=.40,
                         item_fraction=.30, base_fraction=.10, duration=4),
                  packet(1.5, 'bond_combo', 'tempo', stacks=1, gained=1, fraction=.08, duration=4),
                  packet(2, 'bond_combo', 'expire', previous_stacks=1)]
        initial = arena_vfx.active_offense(events, 1.6, 0)
        self.assertEqual(set(initial), {'tempo', 'bond_combo'})
        self.assertEqual(initial['tempo'][6]['fraction'], .40)
        reset = arena_vfx.active_offense(events, 2.1, 0)
        self.assertEqual(set(reset), {'tempo'})
        self.assertEqual(arena_vfx.active_offense(events, 5.1, 0), {})
        self.assertEqual(arena_vfx.active_offense(events, 1.6, 0), initial)
        label = arena_vfx.combination_label('metronome', 'tempo', events[0][6])
        self.assertIn('+40%', label)
        self.assertIn('连击+10% / 装备+30%', label)
        self.assertIn('连击清层', arena_vfx.combination_label('bond_combo', 'expire', events[2][6]))

    def test_four_applied_bond_effects_have_visible_distinct_cues(self):
        outputs = []
        for key, effect, payload in (
                ('bond_erosion', 'energy', {'amount': 4}),
                ('bond_combo', 'tempo', {'stacks': 2, 'gained': 1, 'fraction': .10}),
                ('bond_guard', 'shield', {'amount': 20}),
                ('bond_inspiration', 'offense_buff', {'fraction': .10})):
            image = Image.new('RGBA', (160, 120))
            arena_vfx.draw_combination(image, key, effect, (20, 60), (100, 60), .5, payload)
            self.assertIsNotNone(image.getbbox(), key)
            outputs.append(image.tobytes())
            self.assertIn(arena_vfx.COMBINATION_NAMES[key], arena_vfx.combination_label(key, effect, payload))
        self.assertEqual(len(set(outputs)), 4)


if __name__ == '__main__':
    unittest.main()
