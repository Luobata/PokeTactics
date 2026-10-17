"""Fixed traits and reactive gear expose real, independent battle outcomes."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/mockups'), str(ROOT / 'tools/acceptance')]
import arena
import arena_scenarios
import arena_traits
import arena_vfx
import demo
import portal
from combination_view import battle_summary
from render_battle_gif import ParticleBudget
from web_battle import WebBattleRenderer


def packet(t, key, effect, *, source=0, target=0, **payload):
    return (t, 'combo_effect', source, target, key, effect,
            {'source_pos': (1, 1), 'target_pos': (1, 2), **payload})


class ArenaTraitPresentation(unittest.TestCase):
    def test_catalog_is_session_free_and_accurate_about_full_53_coverage(self):
        with patch.object(demo, 'Session', side_effect=AssertionError('Allocated game')):
            catalog = portal.catalog_view(demo)
        self.assertEqual((len(catalog['traits']), len(catalog['pokemon'])), (65, 62))
        covered = [row for row in catalog['pokemon'] if row.get('trait')]
        uncovered = [row for row in catalog['pokemon'] if row.get('trait') is None]
        self.assertEqual((len(covered), len(uncovered)), (62, 0))
        self.assertEqual({row['trait']['sid'] for row in covered}, set(arena_traits.TRAITS))
        for row in covered:
            with self.subTest(species=row['sid']):
                self.assertEqual(row['trait'], arena_traits.for_species(row['sid']))
                self.assertEqual(row['trait']['fixed'], row['sid'] not in (9, 34, 154))
                self.assertEqual(row['trait_options'], arena_traits.options_for(row['sid']))
                self.assertEqual(len(row['trait_options']), 2 if row['sid'] in (9, 34, 154) else 1)
                self.assertTrue(row['trait']['arena_only'])
                self.assertEqual(row['trait']['source_label'],
                                 '竞技战术设计' if row['sid'] in (196, 197, 198) else '原作特性改编')
                self.assertFalse(row['native_skill']['replaceable'])
        changed = arena_traits.for_species(68)
        changed['tags'].append('not a real trait')
        changed['description'] = 'modified response'
        self.assertNotIn('not a real trait', arena_traits.for_species(68)['tags'])
        self.assertNotEqual(changed['description'], arena_traits.for_species(68)['description'])
        self.assertIsNone(demo._piece_view(arena.build_templates()[68]).get('trait'))

    def test_summary_counts_successes_and_preserved_shields_without_fake_hits(self):
        events = [packet(1, 'drain_fang', 'heal', amount=7),
                  packet(1, 'dew_charm', 'heal', amount=0),
                  packet(2, 'grounding_cloak', 'cleanse', amount=0, removed='para'),
                  packet(3, 'trait_static', 'status', applied=True, status_kind='para'),
                  packet(3, 'trait_poison_point', 'status', applied=False, status_kind='poison'),
                  packet(4, 'trait_sturdy', 'guard', amount=3, prevented=3),
                  packet(4, 'trait_magic_guard', 'guard', amount=0, prevented=5,
                         avoided_shield_absorption=5),
                  packet(4, 'trait_magic_guard', 'guard', amount=0, prevented=0),
                  packet(5, 'trait_volt_absorb', 'absorb_damage', amount=4),
                  packet(6, 'trait_compound_eyes', 'accuracy', saved_dodge=True),
                  packet(6, 'trait_compound_eyes', 'accuracy', saved_dodge=False),
                  packet(7, 'trait_intimidate', 'weaken', source=1, target=2,
                         amount=0, damage_scope='physical', fraction=.10),
                  packet(8, 'trait_blaze', 'empowered_hit', amount=5, extra_damage=5,
                         absorbed=2, actual_total=80, baseline_actual=75, action_index=10),
                  packet(9, 'drain_fang', 'heal', source=2, target=2, amount=99)]
        original = copy.deepcopy(events)
        summary = battle_summary(events, {0: 0, 1: 0, 2: 1})
        self.assertEqual((summary['triggers'], summary['total_healing'],
                          summary['total_cleanses'], summary['total_statuses'],
                          summary['total_mitigated'], summary['total_accuracy_saves'],
                          summary['total_weakens']), (9, 7, 1, 1, 7, 1, 1))
        self.assertEqual((summary['total_shield'], summary['absorbed'],
                          summary['total_damage'], summary['damage_absorbed']), (0, 0, 5, 2))
        magic = next(row for row in summary['by_key'] if row['id'] == 'trait_magic_guard')
        self.assertEqual((magic['triggers'], magic['mitigated'], magic['absorbed']), (1, 0, 0))
        self.assertNotIn('trait_poison_point', {row['id'] for row in summary['by_key']})
        self.assertEqual(events, original)

    def test_physical_stances_keep_inspiration_scope_and_independent_expiry_on_rewind(self):
        events = [packet(1, 'native_inspiration', 'offense_buff', fraction=.25, duration=3),
                  packet(1.2, 'trait_guts', 'offense_buff', fraction=.20, duration=3,
                         damage_scope='physical'),
                  packet(1.3, 'trait_intimidate', 'weaken', source=1,
                         fraction=.10, duration=5, damage_scope='physical'),
                  packet(2, 'trait_guts', 'expire', damage_scope='physical'),
                  packet(3, 'trait_guts', 'offense_buff', fraction=.20, duration=3,
                         damage_scope='physical'),
                  packet(4, 'native_inspiration', 'expire'),
                  packet(5, 'trait_intimidate', 'expire', source=1, damage_scope='physical')]
        original = copy.deepcopy(events)
        renderer = WebBattleRenderer.__new__(WebBattleRenderer)
        renderer.anim = SimpleNamespace(events=events, timeline=SimpleNamespace(
            recent_events=lambda t, window: [e for e in events if t-window <= e[0] <= t]))
        renderer.view = SimpleNamespace(units={})
        expected = {1.5: {'offense_buff', 'physical_buff', 'physical_weaken'},
                    2.1: {'offense_buff', 'physical_weaken'},
                    4.1: {'physical_buff', 'physical_weaken'},
                    5.1: {'physical_buff'}, 6.1: set()}
        for t, keys in expected.items():
            with self.subTest(time=t):
                active = renderer._active_identity_effects(t, 0)
                self.assertEqual(set(active), keys)
                if 'offense_buff' in active:
                    self.assertEqual(active['offense_buff'][6]['fraction'], .25)
                if 'physical_buff' in active:
                    self.assertEqual(active['physical_buff'][6]['fraction'], .20)
                self.assertEqual(renderer._active_identity_effects(t, 2), {})
        self.assertEqual(set(renderer._active_identity_effects(1.5, 0)), expected[1.5])
        self.assertEqual(events, original)

    def test_labels_preserve_physical_scope_shield_protection_and_actual_extra_damage(self):
        guts = arena_vfx.combination_label('trait_guts', 'offense_buff',
                                           {'fraction': .20, 'damage_scope': 'physical'})
        self.assertIn('特性 · 毅力', guts)
        self.assertIn('物理直接伤害 +20%', guts)
        self.assertNotIn('25%', guts)
        guard = arena_vfx.combination_label('trait_magic_guard', 'guard',
                                            {'amount': 0, 'avoided_shield_absorption': 5})
        self.assertIn('避免生命损失 0', guard)
        self.assertIn('保留护盾 5', guard)
        hit = arena_vfx.combination_label('trait_blaze', 'empowered_hit',
                                          {'amount': 5, 'extra_damage': 5, 'absorbed': 2,
                                           'actual_total': 80})
        self.assertIn('已结算额外生命损失 5', hit)
        self.assertIn('额外护盾吸收 2', hit)
        self.assertNotIn('80', hit)

    def test_applied_trait_categories_have_visible_distinct_materials(self):
        outputs = []
        tracks = [('trait_static', 'status', {'status_kind': 'para'}),
                  ('trait_poison_point', 'status', {'status_kind': 'poison'}),
                  ('trait_guts', 'offense_buff', {'fraction': .20}),
                  ('trait_intimidate', 'weaken', {'fraction': .10}),
                  ('trait_magic_guard', 'guard', {'amount': 0}),
                  ('trait_sturdy', 'guard', {'amount': 3}),
                  ('trait_compound_eyes', 'accuracy', {'saved_dodge': True}),
                  ('trait_torrent', 'empowered_hit', {'extra_damage': 5})]
        for key, effect, details in tracks:
            image = Image.new('RGBA', (180, 140))
            arena_vfx.draw_combination(image, key, effect, (25, 75), (110, 75), .5, details)
            self.assertIsNotNone(image.getbbox(), (key, effect))
            outputs.append(image.tobytes())
        self.assertEqual(len(set(outputs)), len(tracks))

    def test_plunder_shows_denied_and_received_energy_without_blank_frames(self):
        details = {'stolen': 8, 'gained': 4, 'amount': 4}
        label = arena_vfx.combination_label('trait_night_feed', 'energy_drain', details)
        self.assertIn('趁隙掠能', label)
        self.assertIn('掠取 8', label)
        self.assertIn('回能 +4', label)
        image = Image.new('RGBA', (180, 140))
        arena_vfx.draw_combination(image, 'trait_night_feed', 'energy_drain',
                                   (25, 75), (110, 75), .5, details)
        self.assertIsNotNone(image.getbbox())

    def test_flareon_ignite_is_labeled_and_drawn_as_burn_not_poison(self):
        outputs = []
        for kind, name in (('burn', '灼伤'), ('poison', '中毒'), ('para', '麻痹'),
                           ('sleep', '睡眠'), ('freeze', '冰冻')):
            label = arena_vfx.combination_label('trait_ignite_pursuit', 'status',
                                                {'status_kind': kind})
            self.assertIn('施加' + name, label)
        for kind in ('burn', 'poison', 'para'):
            image = Image.new('RGBA', (180, 140))
            arena_vfx.draw_combination(image, 'trait_ignite_pursuit', 'status',
                                       (25, 75), (110, 75), .5, {'status_kind': kind})
            self.assertIsNotNone(image.getbbox())
            outputs.append(image.tobytes())
        self.assertEqual(len(set(outputs)), 3)

    def test_healing_annotations_bind_only_their_child_not_same_tick_unrelated_regen(self):
        events = [packet(1, 'dew_charm', 'heal', target=1, amount=6, event_count=2),
                  (1, 'regen', 1, 6), (1, 'unit_state', 1, {}),
                  (1, 'regen', 1, 6), (1, 'unit_state', 1, {}),
                  packet(1, 'trait_volt_absorb', 'heal', source=2, target=1,
                         amount=6, event_count=2),
                  (1, 'regen', 1, 6), (1, 'unit_state', 1, {})]
        original = copy.deepcopy(events)
        renderer = WebBattleRenderer.__new__(WebBattleRenderer)
        renderer.anim = SimpleNamespace(events=events)
        renderer.view = SimpleNamespace(units={0: None, 1: None, 2: None})
        owners = renderer._index_healing_packets()
        self.assertEqual(set(owners), {1, 6})
        self.assertEqual((owners[1]['source'], owners[6]['source']), (0, 2))
        self.assertIsNone(owners[1]['key'])
        self.assertEqual(events, original)

    def test_natural_preview_shows_named_gear_from_legal_loadouts(self):
        expected = {'arena_trait_sustain': {('drain_fang', 'heal'), ('torrent_orb', 'energy')},
                    'arena_trait_cadence': {('pulse_band', 'energy'), ('storm_chime', 'energy')},
                    'arena_trait_relay': {('relay_coil', 'shield'), ('trait_intimidate', 'weaken')},
                    'arena_trait_mending': {('dew_charm', 'heal')}}
        for key, required in expected.items():
            with self.subTest(scene=key):
                scene = arena_scenarios.SCENARIOS[key]
                self.assertEqual((len(set(scene['a'])), len(set(scene['b']))), (6, 6))
                self.assertFalse(scene.get('augments_a'))
                self.assertFalse(scene.get('learned_a'))
                anim = arena_scenarios.make_scene(7, key)
                actual = {(e[4], e[5]) for e in anim.events if e[1] == 'combo_effect'
                          and anim.by_idx[e[2]].team == 0}
                self.assertTrue(required <= actual, (key, required - actual))

    def test_web_healing_has_one_real_material_and_float_and_device_keeps_trait_stance(self):
        anim = arena_scenarios.make_scene(7, 'arena_trait_sustain')
        original = copy.deepcopy(anim.events)
        heal = next(e for e in anim.timeline.events
                    if e[1] == 'combo_effect' and e[4:6] == ('drain_fang', 'heal'))
        renderer = WebBattleRenderer(anim)
        at = heal[0] + .05
        with patch.object(arena_vfx, 'draw_combination', wraps=arena_vfx.draw_combination) as draw:
            renderer.frame(at)
        self.assertFalse(any(call.args[1:3] == ('drain_fang', 'heal') for call in draw.call_args_list))
        expected_heals = [e[3] for e in anim.timeline.events if e[1] == 'regen' and e[0] <= at and e[3] > 0]
        actual_heals = [row[3] for row in renderer.view.floats if row[3].startswith('+')]
        self.assertCountEqual(actual_heals, ['+' + str(amount) for amount in expected_heals])
        renderer.frame(0)
        self.assertEqual(anim.events, original)
        # The 240x320 preview uses the same physical stance track while retaining
        # its own finite particle budget. No synthetic event or state is added.
        relay = arena_scenarios.make_scene(7, 'arena_trait_relay')
        weak = next(e for e in relay.timeline.events
                    if e[1] == 'combo_effect' and e[4:6] == ('trait_intimidate', 'weaken'))
        view = relay._presentation_view()
        view._ensure(weak[0] + 1)
        image = Image.new('RGBA', (240, 320))
        with patch.object(arena_vfx, 'draw_combination', wraps=arena_vfx.draw_combination) as draw:
            view._draw_arena_fx(image, weak[0] + 1, ParticleBudget())
        self.assertTrue(any(call.args[1:3] == ('trait_intimidate', 'active')
                            for call in draw.call_args_list))


if __name__ == '__main__':
    unittest.main()
