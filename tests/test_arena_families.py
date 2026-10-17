"""Playable family pool, source conservation, branching and save contracts."""
import copy
import random
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/acceptance'), str(ROOT/'tools/mockups')]
import arena
import arena_families as families
import arena_bonds
import demo
import shop
from combat import Battle, Unit
from family_catalog import catalog_view
from session_save import SessionCodec, PRE_FAMILY_FINGERPRINT

class FamilyPoolTests(unittest.TestCase):
    def session(self):
        s=demo.Session(87,'arena_v1',arena_pool=families.VERSION)
        s.begin_round(1)
        return s

    def give(self,s,fid,n=1):
        # Reclaim only this family's shop reservations to make fixtures deterministic.
        for seat in s.seats:
            for i,card in enumerate(seat.shop.slots):
                if card == fid:
                    seat.shop.slots[i]=None;s.pool.put(fid)
        for _ in range(n):
            s.pool.take(fid)
            s.player.bench.append(shop.OwnedPiece(s.templates[fid],s.templates[fid].tier))
        s.ensure_unit_ids()

    def assert_conserved(self,s):
        held=Counter()
        for seat in s.seats:
            held.update(x for x in seat.shop.slots if x is not None)
            for o in seat.all_pieces():held.update(o.sources)
        self.assertEqual({sid:s.pool.remaining[sid]+held[sid] for sid in s.templates},families.pool_caps())

    def test_only_entrances_are_drawn_at_every_level(self):
        s=self.session()
        for level in range(1,10):
            for seed in range(20):
                s.player.shop.roll(random.Random(seed),level)
                self.assertTrue(set(s.player.shop.slots) <= families.FAMILIES.keys())
                self.assert_conserved(s)

    def test_three_shapes_short_chain_and_no_evolution_share_1_3_9(self):
        for fid,expected in ((4,(4,5,6)),(129,(129,130,130)),(131,(131,131,131))):
            with self.subTest(fid=fid):
                s=self.session();self.give(s,fid,3);s.combine_player()
                self.assertEqual(s.player.bench[0].piece.species_id,expected[1])
                self.give(s,fid,6);s.combine_player();self.assert_conserved(s)
                o=s.player.bench[0]
                self.assertEqual((o.piece.species_id,o.piece.star),(expected[2],3))
                self.assertEqual(o.sources,[fid]*9)
                self.assertEqual(o.invested,9*families.FAMILIES[fid][0])
                self.assertEqual(o.piece.tier,s.templates[fid].tier)
                s.player.bench.remove(o);shop.sell_owned(o,s.pool);self.assert_conserved(s)

    def test_evolved_form_does_not_change_shop(self):
        s=self.session();self.give(s,4,3);s.combine_player()
        self.assertEqual(s.player.bench[0].piece.species_id,5)
        self.assertEqual(s.pool.remaining[5],0)
        self.assertEqual(s.pool.remaining[6],0)
        self.assertIn(4,s.templates)
        self.assert_conserved(s)

    def test_eevee_waits_and_all_five_branches_are_explicit(self):
        for branch in (134,135,136,196,197):
            with self.subTest(branch=branch):
                s=self.session();self.give(s,133,3)
                self.assertEqual(s.combine_player(),[])
                self.assertEqual(len(s.player.bench),3)
                demo.act_family_evolve(s,'b0',branch)
                p=s.player.bench[0].piece
                self.assertEqual((p.species_id,p.star,p.branch_id),(branch,2,branch))
                self.assert_conserved(s)
                c=SessionCodec();restored=c.decode(c.encode(s),5)
                self.assertEqual(c.encode(s),c.encode(restored))

    def test_branch_rejection_is_atomic_and_no_cross_branch_merge(self):
        s=self.session();self.give(s,133,2);c=SessionCodec();before=c.encode(s)
        with self.assertRaises(demo.DemoError):demo.act_family_evolve(s,'b0',197)
        self.assertEqual(c.encode(s),before)
        self.give(s,133)
        for branch in (134,135,196):
            if branch!=134:self.give(s,133,3)
            loc=next('b'+str(i) for i,o in enumerate(s.player.bench) if o.piece.star==1)
            demo.act_family_evolve(s,loc,branch)
        self.assertEqual(len(s.player.bench),3)
        self.assertEqual(s.combine_player(),[])
        before=c.encode(s)
        with self.assertRaises(demo.DemoError):demo.act_family_evolve(s,'b0',197)
        self.assertEqual(c.encode(s),before)
        self.assert_conserved(s)

    def test_same_branch_reaches_full_training_with_nine_entrances(self):
        s=self.session()
        for _ in range(3):
            self.give(s,133,3)
            loc=next('b'+str(i) for i,o in enumerate(s.player.bench) if o.piece.star==1)
            demo.act_family_evolve(s,loc,197)
        p=s.player.bench[0]
        self.assertEqual((p.piece.species_id,p.piece.star,len(p.sources)),(197,3,9))
        self.assert_conserved(s)

    def test_family_bonds_count_once_even_when_forms_differ(self):
        a,b=families.make_piece(4),families.make_piece(4,3)
        self.assertEqual(arena_bonds.count([a,b])['FIRE'],1)
        self.assertEqual(arena_bonds.count([a,b])['FLYING'],1)
        self.assertEqual(arena_bonds.count([families.make_piece(133,2,134),families.make_piece(133,2,197)])['WATER'],1)

    def test_bond_hints_do_not_offer_an_already_counted_family(self):
        deployed = [(families.make_piece(4,2), 'leftovers')]
        prep = arena_bonds.preparation(deployed, families.build_templates().values())
        fire = next(row for row in prep['entries'] if row['id'] == 'FIRE')
        self.assertFalse({1,4,5,6} & set(fire['candidates']))
        self.assertIn('同一家族', prep['note'])

    def test_branch_with_full_bench_rejects_without_consuming_materials(self):
        s=self.session();self.give(s,133,3)
        for col in range(3):s.player.grid[(0,col)]=s.player.bench.pop()
        for fid in (4,7,10,29,32,43,58,66):self.give(s,fid)
        c=SessionCodec();before=c.encode(s)
        with self.assertRaises(demo.DemoError):demo.act_family_evolve(s,'g0,0',134)
        self.assertEqual(c.encode(s),before)
        self.assert_conserved(s)

    def test_form_change_preserves_uid_and_returns_surplus_learning(self):
        s=self.session();self.give(s,133,3)
        a,b,_=s.player.bench
        a.item='leftovers';b.item='focus_lens';a.technique='rest';b.technique='toxic'
        uid=a.uid
        demo.act_family_evolve(s,'b0',135)
        result,=s.player.bench
        self.assertEqual(result.uid,uid)
        self.assertEqual(result.item,'leftovers')
        self.assertIn('focus_lens',s.player.inventory.finished)
        self.assertEqual(result.technique,'rest')
        self.assertEqual(s.player.inventory.techniques['toxic'],1)
        self.assert_conserved(s)

    def test_dragonite_is_normal_and_rares_remain_single(self):
        dragon=shop.OwnedPiece(families.make_piece(147,3),27)
        self.assertFalse(arena.holds_legendary([dragon]))
        self.assertTrue(arena.holds_legendary([shop.OwnedPiece(families.make_piece(150),5)]))
        with self.assertRaises(ValueError):families.make_piece(150,2)

    def test_save_rejects_form_source_branch_and_shop_forgery(self):
        s=self.session();self.give(s,4,3);s.combine_player();c=SessionCodec();valid=c.encode(s)
        changes=[lambda d:d['seats'][0]['bench'][0].update(species=6),
                 lambda d:d['seats'][0]['bench'][0].update(sources=[5]*3),
                 lambda d:d['seats'][0]['bench'][0].update(branch=9),
                 lambda d:d['seats'][0]['bench'][0].update(invested=1),
                 lambda d:d['seats'][0]['shop'].__setitem__(0,5)]
        for change in changes:
            bad=copy.deepcopy(valid);change(bad)
            with self.assertRaises(ValueError):c.decode(bad,5)

    def test_verified_predecessor_keeps_species_rules(self):
        s=demo.Session(87,'arena_v1');s.begin_round(1);c=SessionCodec();payload=c.encode(s)
        payload['rules']=PRE_FAMILY_FINGERPRINT;payload.pop('arena_pool',None)
        r=c.decode(payload,5)
        self.assertFalse(r.is_family)
        self.assertEqual(set(r.templates),set(arena.ROSTER))

    def test_catalog_uses_real_combat_panels_all_branches(self):
        catalog=catalog_view();self.assertEqual(len(catalog['families']),56)
        for family in catalog['families']:
            for branch in family['branches']:
                for stage in branch['stages']:
                    p=families.make_piece(family['id'],stage['star'],branch['id'])
                    b=Battle([p],[families.make_piece(131)],random.Random(5),ruleset='arena_v1',stat_mode='budget_v1')
                    # Deployment panels intentionally exclude bonds and opening passives.
                    unit=Unit(p,0,(0,0),stat_mode='budget_v1')
                    ctx=object.__new__(Battle);ctx.units=[unit];ctx.arena_teams=[[],[]];ctx.arena_growth=[{},{}]
                    ctx._apply_arena_stats()
                    self.assertEqual(stage['stats']['max_hp'],unit.max_hp)
                    self.assertEqual(stage['stats']['atk'],unit.attack)
                    self.assertEqual(stage['stats']['sp_atk'],unit.sp_attack)
                    self.assertEqual(stage['total_cost'],family['cost']*stage['copies'])

    def test_bots_buy_family_sources_and_choose_a_branch(self):
        s=self.session();bot=s.bots[0]
        bot.board=[];bot.bench=[shop.OwnedPiece(s.templates[133],2) for _ in range(3)]
        bot.target_types=('DARK',)
        families.choose_bot_branches(bot)
        families.combine(bot.board,bot.bench,bot.inventory)
        self.assertEqual(bot.bench[0].piece.species_id,197)
        self.assertEqual(bot.count_species(133),3)

    def test_live_pvp_pve_rounds_and_replays_survive_save_load(self):
        s=self.session();self.give(s,129,3);s.combine_player()
        s.player.grid[(0,2)]=s.player.bench.pop()
        c=SessionCodec()
        def prepare_only(*args,**kwargs):
            return demo._prepare_battle_frames(*args,**kwargs)[0]
        with patch.object(demo,'DEFER_RENDER',False), patch.object(demo,'_render_battle_frames',side_effect=prepare_only):
            for r in range(1,7):
                for reward in list(s.arena_augments_pending):
                    arena.claim_augment(s,reward['id'],reward['options'][0]['id'])
                s.end_prep()
                self.assert_conserved(s)
                decoded=c.decode(c.encode(s),5)
                self.assertEqual(c.encode(decoded),c.encode(s))
                if s.phase=='over':break
                s.next_round()
                # The codec's hp bound is 100, so use legal real game state.
                self.assert_conserved(s)

    def test_renderer_accepts_every_family_form(self):
        from character_catalog import character_catalog
        for p in families.build_templates().values():
            result=character_catalog(mode='arena',pieces=[p])
            self.assertIn(str(p.species_id),result)

if __name__=='__main__':unittest.main()
