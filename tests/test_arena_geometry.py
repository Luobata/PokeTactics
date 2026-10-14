"""Arena's third row is real simulation geometry; classic instances stay fixed."""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/acceptance'))
import demo
import arena
from combat import Battle, ROWS
from render_battle_gif import BattleAnimation, board_floor


class ArenaGeometry(unittest.TestCase):
    def test_roles_use_three_rows_and_rotating_sides_is_symmetric(self):
        t = arena.build_templates()
        comp = [t[76], t[26], t[40]]
        ally = arena.positions_for(comp, 0)
        enemy = arena.positions_for(comp, 1)
        self.assertEqual([r for c, r in ally], [3, 4, 5])
        self.assertEqual(enemy, [(5-c, 5-r) for c, r in ally])

    def test_third_row_deployment_bounds_and_classic_do_not_leak(self):
        t = arena.build_templates()
        comp = [t[26]] * 18
        a = Battle(comp, comp, random.Random(9), ruleset='arena_v1')
        self.assertEqual(a.rows, 6)
        self.assertEqual(len({u.pos for u in a.units}), 36)
        with self.assertRaises(ValueError):
            Battle([t[26]], [t[76]], random.Random(9), ruleset='arena_v1', positions_a=[(2, 6)])
        classic = Battle([t[26]], [t[76]], random.Random(9))
        self.assertEqual((classic.rows, ROWS), (4, 4))
        with self.assertRaises(ValueError):
            Battle([t[26]], [t[76]], random.Random(9), positions_a=[(2, 5)])

    def test_real_movement_and_renderer_share_height_and_preserve_classic_floor(self):
        t = arena.build_templates()
        b = Battle([t[68]], [t[76]], random.Random(12), ruleset='arena_v1',
                   positions_a=[(2, 5)], positions_b=[(2, 0)])
        b.run()
        self.assertTrue(any(e[1] == 'move' for e in b.events))
        self.assertTrue(all(0 <= e[3][1] < 6 for e in b.events if e[1] in ('move', 'deploy')))
        front, pal, font = demo._assets()
        anim = BattleAnimation([t[68]], [t[76]], 12, front, pal, font, battle=b)
        self.assertEqual((anim.width, anim.height, anim.battle_rows, anim.visual_rows), (240, 400, 6, 8))
        self.assertEqual(anim.playback_frame(0).size, (240, 400))
        self.assertEqual(anim.playback_frame(anim.presentation_duration).size, (240, 400))
        classic = Battle([t[68]], [t[76]], random.Random(12)); classic.run()
        old = BattleAnimation([t[68]], [t[76]], 12, front, pal, font, battle=classic)
        self.assertEqual(old.playback_frame(0).size, (240, 320))
        self.assertEqual(board_floor(None).size, (240, 240))
        self.assertEqual(board_floor(None, 8).size, (240, 320))

    def test_sealed_ranged_target_advances_to_firing_line(self):
        # 第 9 轮实战复盘案例：目标格被围死时远程不再原地空转，走一步进入射程开火。
        t = arena.build_templates()
        b = Battle([t[26]], [t[76]] * 4, random.Random(7), ruleset='arena_v1',
                   positions_a=[(2, 4)], positions_b=[(2, 0), (1, 0), (3, 0), (2, 1)])
        u, sealed = b.units[:2]
        u.target_idx = sealed.idx
        b._act(u, 0.1)
        self.assertEqual(u.pos, (2, 3))
        b._act(u, 0.7)
        self.assertTrue(any(e[1] == 'attack' and e[2] == u.idx for e in b.events))

    def test_taunt_keeps_lock_even_when_taunter_is_sealed(self):
        # 近战够不到被围死的嘲讽者：不改锁、不换目标，原地等待嘲讽结束。
        t = arena.build_templates()
        b = Battle([t[68], t[76]], [t[76]] * 4, random.Random(7), ruleset='arena_v1',
                   positions_a=[(2, 4), (2, 3)], positions_b=[(2, 2), (1, 2), (3, 2), (2, 1)])
        u, taunter = b.units[0], b.units[2]
        u.target_idx = taunter.idx
        u.taunt_source_idx, u.taunt_until = taunter.idx, 99.0
        b._act(u, 0.1)
        self.assertEqual((u.pos, u.target_idx), ((2, 4), taunter.idx))


if __name__ == '__main__': unittest.main()
