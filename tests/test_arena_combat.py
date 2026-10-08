"""Arena roles, fair augments, healing causality, and star combat strength."""
import copy
import random
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/mockups')]
import arena
from combat import Battle
from animation_timeline import AnimationTimeline


class ArenaCombat(unittest.TestCase):
    def battle(self, ids_a=(76, 26, 40), ids_b=(31, 68, 12), augments=None, star=1, seed=11):
        templates=arena.build_templates()
        a=[copy.copy(templates[sid]) for sid in ids_a]
        b=[copy.copy(templates[sid]) for sid in ids_b]
        for p in a:
            p.star=star
            p.shiny=star == 3
        return Battle(a,b,random.Random(seed),ruleset='arena_v1',stat_mode='budget_v1',
                      positions_a=arena.positions_for(a,0),positions_b=arena.positions_for(b,1),
                      arena_teams=augments)

    def test_nine_card_star_upgrade_changes_real_battle_strength(self):
        stronger=self.battle((26,),(26,),star=3)
        self.assertEqual(stronger.run()['winner'],0)
        one,two=self.battle(),self.battle(star=2)
        for a,b in zip(one.units[:3],two.units[:3]):
            self.assertGreater(b.max_hp,a.max_hp)
            self.assertGreater(b.attack,a.attack)

    def test_all_augments_change_both_teams_using_same_rules(self):
        plain=self.battle()
        for key in ('sharp_focus','iron_wall','vitality','quick_step','mana_flow'):
            boosted=self.battle(augments=[[key],[key]])
            for before,after in zip(plain.units,boosted.units):
                with self.subTest(augment=key,team=after.team):
                    if key == 'sharp_focus':self.assertGreater(after.attack,before.attack)
                    if key == 'iron_wall':self.assertLess(boosted._final_damage(after,after,None,100),plain._final_damage(before,before,None,100))
                    if key == 'vitality':self.assertGreater(after.max_hp,before.max_hp)
                    if key == 'quick_step':self.assertLess(after.attack_interval,before.attack_interval)
                    if key == 'mana_flow':self.assertEqual(after.energy,20)

    def test_native_healing_targets_injured_allies_and_respects_counter(self):
        import arena_skills
        battle=self.battle(augments=[['first_aid'],[]])
        tank,attacker,healer=battle.units[:3]
        healer.pos,tank.pos,attacker.pos=(2,4),(1,4),(3,4)
        tank.hp=tank.max_hp//2
        attacker.hp=attacker.max_hp//4
        tank_before,atk_before=tank.hp,attacker.hp
        healer.energy=80
        self.assertTrue(arena_skills.cast(battle,healer,battle.units[3],4.))
        heals=[e for e in battle.events if e[1]=='skill_effect' and e[5]=='heal']
        self.assertEqual([e[3] for e in heals],[attacker.idx,tank.idx])
        self.assertGreater(tank.hp,tank_before)
        self.assertGreater(attacker.hp,atk_before)
        amplified=heals[0][6]['amount']
        attacker.hp=atk_before
        attacker.healing_blocks=[{'source':battle.units[3].idx,'fraction':.6,'expires_at':12.}]
        healer.energy=80
        start=len(battle.events)
        self.assertTrue(arena_skills.cast(battle,healer,battle.units[3],8.))
        blocked=next(e for e in battle.events[start:] if e[1]=='skill_effect' and e[5]=='heal' and e[3]==attacker.idx)
        self.assertLess(blocked[6]['amount'],amplified)
        self.assertTrue(any(e[1]=='tactical_effect' and e[4]=='healing_prevented' for e in battle.events))

    def test_support_tick_recharges_energy_and_never_heals(self):
        battle=self.battle()
        tank,attacker,healer=battle.units[:3]
        healer.energy=78
        attacker.energy=0
        attacker.hp=attacker.max_hp//4
        before=attacker.hp
        battle._arena_support(1.)
        self.assertEqual((healer.energy,attacker.energy),(80,0))
        self.assertEqual(attacker.hp,before)
        self.assertFalse(any(e[1] in ('regen','arena_heal') for e in battle.events))

    def test_support_feedback_and_health_land_together_in_replay(self):
        battle=self.battle();battle.run()
        timeline=AnimationTimeline(battle.events,battle.units)
        heals=[e for e in timeline.events if e[1]=='skill_effect' and e[5]=='heal' and e[6]['amount']>0]
        self.assertTrue(heals)
        for heal in heals:
            self.assertTrue(any(e[1]=='regen' and e[2]==heal[3] and e[3]==heal[6]['amount']
                                and e[0]==heal[0] for e in timeline.events))
        for t in (0,2.,4.,8.,timeline.duration):
            self.assertLessEqual(timeline.time(t),timeline.duration)

    def test_rotating_and_swapping_sides_preserves_trial(self):
        for seed in range(6):
            left=self.battle(augments=[['first_aid'],['iron_wall']],seed=seed)
            right=self.battle((31,68,12),(76,26,40),augments=[['iron_wall'],['first_aid']],seed=seed)
            l,r=left.run(),right.run()
            self.assertEqual(r['winner'],None if l['winner'] is None else 1-l['winner'])
            self.assertEqual(l['duration'],r['duration'])
            self.assertEqual([u.hp for u in left.units[:3]],[u.hp for u in right.units[3:]])
            self.assertEqual([u.hp for u in left.units[3:]],[u.hp for u in right.units[:3]])

    def test_delayed_healing_cannot_play_after_the_healer_dies(self):
        choices=random.Random(27)
        ids=list(arena.ROSTER)
        battle=self.battle(choices.sample(ids,6),choices.sample(ids,6),seed=27)
        battle.run()
        timeline=AnimationTimeline(battle.events,battle.units)
        deaths={e[2]:e[0] for e in timeline.events if e[1]=='die'}
        for event in timeline.events:
            if event[1]=='skill_effect' and event[5]=='heal':
                self.assertLessEqual(event[0],deaths.get(event[2],timeline.duration))

    def test_invalid_loadouts_and_stars_are_rejected(self):
        for selection in ([['missing'],[]],[['iron_wall','iron_wall'],[]],[[],[],[]]):
            with self.assertRaises(ValueError):self.battle(augments=selection)
        for star in (0,4,True):
            with self.assertRaises(ValueError):self.battle(star=star)
        with self.assertRaises(ValueError):
            Battle([],[],random.Random(1),arena_teams=[[],[]])
