"""Impact hierarchy follows real damage, source ownership and authored pixels."""
import copy
import hashlib
import random
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/mockups')]
from arena import build_templates, ROSTER
from arena_preview_scene import make_preview_scene
from arena_teaching import after_basic
from combat import Battle
from decoders import Front, Palettes, Font16
from render_battle_gif import BattleAnimation
from web_battle import WebBattleRenderer
from move_effects import DEFAULT_VISUAL
import arena_combinations
import retro_attacks


class BattleVfxHierarchy(unittest.TestCase):
    def battle(self, source=150, target=9, learned=None):
        templates = build_templates()
        return Battle([copy.copy(templates[source])], [copy.copy(templates[target])],
            random.Random(7), positions_a=[(2, 3)], positions_b=[(2, 2)],
            ruleset='arena_v1', stat_mode='budget_v1', learned_a=[learned])

    def renderer(self, battle):
        return WebBattleRenderer(BattleAnimation([], [], 7, Front(), Palettes(), Font16(), battle=battle))

    def test_real_teaching_hit_never_inherits_original_game_ultimate_power(self):
        battle = self.battle(26, learned='thunderbolt')
        after_basic(battle, *battle.units, .5)
        renderer = self.renderer(battle)
        self.assertTrue(any(e[1] == 'cast' and e[4] == 'thunderbolt' and e[6] > 0 for e in battle.events))
        self.assertTrue(renderer._impacts)
        self.assertFalse(renderer._ults)

    def test_support_and_self_casts_do_not_shake_flash_or_hitstop(self):
        for sid in (40, 113, 242, 31):
            anim = make_preview_scene(sid, 'cast')
            renderer = WebBattleRenderer(anim)
            timing = next(a for a in anim.timeline.actions if a.attacker == 0 and a.kind == 'cast')
            self.assertNotIn(round(timing.impact, 3), {round(row[0], 3) for row in renderer._impacts})
            self.assertFalse(renderer._ults)
            self.assertEqual(renderer._shake_offset(timing.impact + .01), (0, 0))
            self.assertEqual(renderer._ult_overlay_state(timing.impact + .01), (0, None))

    def test_fully_absorbed_native_cast_keeps_shield_feedback_without_damage_staging(self):
        battle = self.battle()
        caster, enemy = battle.units
        arena_combinations.grant_shield(battle, enemy, enemy, 9999, 0., None,
            source_kind='item', source_key='tide_shell')
        caster.energy = 80
        initial_hp = enemy.hp
        battle._strike(caster, enemy, .5)
        renderer = self.renderer(battle)
        self.assertEqual(enemy.hp, initial_hp)
        self.assertTrue(any(e[1] == 'combo_effect' and e[5] == 'absorb' for e in battle.events))
        self.assertFalse(renderer._impacts)
        self.assertFalse(renderer._ults)

    def test_immunity_keeps_zero_damage_off_the_impact_layer(self):
        battle = self.battle(94, 108)
        caster, enemy = battle.units
        caster.energy = 80
        battle._strike(caster, enemy, .5)
        renderer = self.renderer(battle)
        self.assertFalse(renderer._impacts)
        self.assertFalse(renderer._ults)

    def test_basic_attack_dispatch_uses_one_authored_silhouette_and_no_guides(self):
        renderer = WebBattleRenderer(make_preview_scene(6, 'attack'))
        timing = next(a for a in renderer.anim.timeline.actions if a.attacker == 0 and a.kind == 'attack')
        at = (timing.release + timing.impact) / 2
        renderer.view._ensure(at)
        with patch.object(renderer, '_configured_material', side_effect=AssertionError('duplicate material')), \
             patch.object(retro_attacks, 'draw', wraps=retro_attacks.draw) as authored:
            layer = Image.new('RGBA', (960, 640))
            renderer._draw_actions(layer, at)
        self.assertEqual(authored.call_count, 1)
        self.assertIsNotNone(layer.getbbox())

    def test_all_53_basic_silhouettes_survive_scaling_and_have_finite_tails(self):
        hashes = []
        for sid in ROSTER:
            layer = Image.new('RGBA', (480, 360))
            retro_attacks.draw(layer, sid, (90, 260), (340, 120), 'impact', .4, DEFAULT_VISUAL)
            self.assertIsNotNone(layer.getbbox(), sid)
            hashes.append(hashlib.sha256(layer.tobytes()).hexdigest())
            expired = Image.new('RGBA', layer.size)
            retro_attacks.draw(expired, sid, (90, 260), (340, 120), 'aftermath', 1., DEFAULT_VISUAL)
            self.assertIsNone(expired.getbbox(), sid)
        self.assertEqual(len(set(hashes)), len(ROSTER))


if __name__ == '__main__':
    unittest.main()
