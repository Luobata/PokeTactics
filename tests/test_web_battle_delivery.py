"""Web frames and their scoreboards follow the same authoritative battle."""
import copy
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools/acceptance'), str(ROOT / 'tools/mockups'), str(ROOT / 'sim')]
import arena
import demo
from combat import Battle
from render_battle_gif import BattleAnimation


class WebBattleDelivery(unittest.TestCase):
    def test_web_frames_scoreboards_and_statistics_share_one_simulation(self):
        templates = arena.build_templates()
        a, b = [copy.copy(templates[26])], [copy.copy(templates[68])]
        options = {'ruleset': arena.RULESET, 'positions_b': [(2, 2)]}
        battle = Battle(a, b, random.Random(42), layout='back',
                        positions_a=[(2, 3)], **options)
        result = battle.run()
        anim = BattleAnimation(a, b, 0, *demo._assets(), battle=battle)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            meta = demo._render_battle_frames(a, b, random.Random(42), None, path,
                                             positions_a=[(2, 3)], **options)
            self.assertEqual(meta['winner'], result['winner'])
            self.assertEqual(meta['statistics'], battle.statistics())
            self.assertEqual(demo.WEB_BATTLE_REVISION, 'web-arena-v18-family-effects-r1')
            self.assertEqual(meta['presentation'], demo.WEB_BATTLE_REVISION)
            self.assertEqual(meta['render_revision'], demo.WEB_BATTLE_REVISION)
            self.assertNotEqual(meta['render_revision'], 'web-arena-v1')
            self.assertEqual((meta['width'], meta['height']), (960, 640))
            self.assertEqual(len(meta['team_frames']), meta['n'])
            self.assertEqual(meta['team_frames'][0]['alive'], [1, 1])
            self.assertEqual(meta['team_frames'][0]['hp'], [u.max_hp for u in battle.units])
            last = meta['team_frames'][-1]
            self.assertEqual(last['hp'], [u.hp for u in battle.units])
            self.assertEqual(last['alive'], [int(u.hp > 0) for u in battle.units])
            self.assertEqual([u['idx'] for u in meta['combatants']], [0, 1])
            self.assertEqual([u['range'] for u in meta['combatants']], [a[0].distance, b[0].distance])
            first_hit = anim.timeline.actions[0].impact
            for index in (max(0, round(first_hit / meta['dt']) - 1),
                          round(first_hit / meta['dt']), meta['n'] // 2):
                states = anim.presentation_state(index * meta['dt'])
                self.assertEqual(meta['team_frames'][index]['hp'],
                                 [states[u.idx]['hp'] for u in battle.units])
                self.assertEqual(meta['team_frames'][index]['alive'],
                                 [int(states[u.idx]['die_t'] is None) for u in battle.units])
            self.assertEqual(json.loads((path / 'meta.json').read_text()),
                             json.loads(json.dumps(meta)))
            self.assertEqual(len(list(path.glob('*.png'))), meta['n'])
            for index in (0, meta['n'] // 2, meta['n'] - 1):
                with Image.open(path / f'{index}.png') as image:
                    self.assertEqual(image.size, (960, 640))

    def test_loadout_highlights_and_technique_tags_reach_the_report(self):
        templates = arena.build_templates()
        a = [(copy.copy(templates[26]), 'choice_band')]
        b = [copy.copy(templates[68])]
        options = {'ruleset': arena.RULESET, 'positions_b': [(2, 2)],
                   'learned_a': ['thunderbolt']}
        with tempfile.TemporaryDirectory() as directory:
            meta = demo._render_battle_frames(a, b, random.Random(42), None,
                                              Path(directory), positions_a=[(2, 3)], **options)
            mine = next(unit for unit in meta['combatants'] if unit['team'] == 0)
            self.assertEqual((mine['item'], mine['item_name']), ('choice_band', '专爱头巾'))
            self.assertEqual((mine['technique'], mine['technique_name']),
                             ('thunderbolt', '十万伏特'))
            highlights = meta['loadout_highlights']
            technique = next(row for row in highlights if row['kind'] == 'technique')
            self.assertEqual(technique['unit'], mine['name'])
            self.assertIn('十万伏特（技能机）', technique['name'])
            self.assertIn('1 次施放', technique['text'])
            passive = next(row for row in highlights
                           if row['kind'] == 'item' and row['unit'] == mine['name'])
            self.assertEqual(passive['name'], '专爱头巾')
            self.assertTrue(passive['text'])
            self.assertTrue(any('（技能机）' in event['text'] for event in meta['events']),
                            '事件流里的技能机招式需要带来源标注')

    def test_passive_item_estimate_card_quantifies_contribution(self):
        class FakeUnit:
            max_hp = 200
        unit = FakeUnit()
        self.assertEqual(demo._passive_item_estimate('choice_band', unit, {'damage_dealt': 100}, 8.0),
                         '估算多打 26 伤害')
        self.assertIn('反噬', demo._passive_item_estimate('life_orb', unit, {'damage_dealt': 100}, 8.0))
        self.assertIsNone(demo._passive_item_estimate('choice_band', unit, {'damage_dealt': 0}, 8.0))
        self.assertIsNone(demo._passive_item_estimate('choice_band', unit, None, 8.0))
        self.assertEqual(demo._passive_item_estimate('leftovers', unit, {}, 10.0),
                         '估算回复 30 生命（存活 10 秒）')
        self.assertIsNone(demo._passive_item_estimate('leftovers', unit, {}, 0.0))
        self.assertIsNone(demo._passive_item_estimate('bright_powder', unit, {'damage_dealt': 100}, 8.0))

    def test_loadout_highlights_quantify_passive_item_contribution(self):
        templates = arena.build_templates()
        a = [(copy.copy(templates[26]), 'choice_band')]
        b = [copy.copy(templates[68])]
        options = {'ruleset': arena.RULESET, 'positions_b': [(2, 2)]}
        with tempfile.TemporaryDirectory() as directory:
            meta = demo._render_battle_frames(a, b, random.Random(42), None,
                                              Path(directory), positions_a=[(2, 3)], **options)
            mine = next(unit for unit in meta['combatants'] if unit['team'] == 0)
            passive = next(row for row in meta['loadout_highlights']
                           if row['kind'] == 'item' and row['unit'] == mine['name'])
            self.assertEqual(passive['name'], '专爱头巾')
            self.assertRegex(passive['text'], r'^估算多打 [1-9]\d* 伤害$')

    def test_legacy_device_frames_keep_their_revision_and_dimensions(self):
        templates = arena.build_templates()
        a, b = [copy.copy(templates[26])], [copy.copy(templates[68])]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            meta = demo._render_battle_frames(a, b, random.Random(42), None, path)
            self.assertEqual(meta['presentation'], 'device-v1')
            self.assertEqual(meta['render_revision'], 'device-v1')
            self.assertEqual((meta['width'], meta['height']), (240, 320))
            for index in (0, meta['n'] - 1):
                with Image.open(path / f'{index}.png') as image:
                    self.assertEqual(image.size, (240, 320))


if __name__ == '__main__':
    unittest.main()
