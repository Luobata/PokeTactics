"""Distinct authored arena tracks and per-unit shiny rendering."""
import copy
import hashlib
import random
import sys
from pathlib import Path
import unittest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'sim'),str(ROOT/'tools/mockups')]
import arena
import arena_vfx
from combat import Battle
from decoders import Front,Palettes,Font16
from render_battle_gif import BattleAnimation


class ArenaVisuals(unittest.TestCase):
    def test_all_species_have_distinct_complete_attack_tracks(self):
        self.assertEqual(set(arena_vfx.EFFECTS),set(arena.ROSTER))
        hashes=[]
        for sid in arena.ROSTER:
            track=hashlib.sha256()
            for phase in ('windup','flight','impact','aftermath'):
                image=Image.new('RGBA',(240,160))
                arena_vfx.draw_attack(image,sid,(30,80),(200,80),phase,.5)
                self.assertIsNotNone(image.getbbox())
                track.update(image.tobytes())
            hashes.append(track.hexdigest())
        self.assertEqual(len(set(hashes)),18)

    def test_same_attack_uses_both_color_and_shape_to_show_faction(self):
        a,b=Image.new('RGBA',(240,160)),Image.new('RGBA',(240,160))
        arena_vfx.draw_attack(a,26,(30,80),(200,80),'flight',.5,0)
        arena_vfx.draw_attack(b,26,(30,80),(200,80),'flight',.5,1)
        self.assertNotEqual(a.tobytes(),b.tobytes())
        # Source markers retain different silhouettes after discarding colour.
        self.assertNotEqual(a.crop((22,71,39,89)).getchannel('A').tobytes(),
                            b.crop((22,71,39,89)).getchannel('A').tobytes())

    def test_shiny_and_ordinary_same_species_coexist_in_a_battle(self):
        p=arena.build_templates()[6]
        shiny=copy.copy(p);shiny.star=3;shiny.shiny=True
        battle=Battle([p],[shiny],random.Random(1),ruleset='arena_v1')
        battle.run()
        anim=BattleAnimation([p],[shiny],1,Front(),Palettes(),Font16(),battle=battle)
        normal=anim._board_sprite(6,3,shiny=False)
        sparkling=anim._board_sprite(6,3,shiny=True)
        self.assertEqual(normal.getchannel('A').tobytes(),sparkling.getchannel('A').tobytes())
        self.assertNotEqual(normal.tobytes(),sparkling.tobytes())
        anim.frame(0.,show_cutins=False)
        rendered=[]
        for au in anim.units.values():
            sprite,_,_=anim._sprite_placement(au,0.,anim._unit_pose(au,0.))
            self.assertIsNotNone(sprite.getbbox())
            rendered.append(sprite.tobytes())
        self.assertNotEqual(*rendered)
        self.assertFalse(getattr(anim.units[0].u.piece,'shiny',False))
        self.assertTrue(anim.units[1].u.piece.shiny)
