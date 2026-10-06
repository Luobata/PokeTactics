"""Resource accounting and saved arena choices survive a real round trip."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/acceptance'))
import demo
import arena
from session_save import SessionCodec, PRE_ARENA_FINGERPRINT, UnknownRulesError


class ArenaRules(unittest.TestCase):
    def setUp(self):
        self.s=demo.Session(7,'arena_v1')
        self.s.begin_round(1)
        self.codec=SessionCodec()

    def test_nine_cards_merge_to_shiny_without_creating_pool_copies(self):
        s,p=self.s,self.s.player
        original=s.pool.remaining[6]
        for _ in range(9):
            s.pool.take(6)
            p.bench.append(demo.shop_mod.OwnedPiece(copy.copy(s.templates[6]),3))
            s.combine_player()
        self.assertEqual(len(p.bench),1)
        own=p.bench[0]
        self.assertEqual((own.piece.species_id,own.piece.star,own.piece.shiny),(6,3,True))
        self.assertEqual(own.sources,[6]*9)
        self.assertEqual(own.invested,27)
        self.assertEqual(s.pool.remaining[6],original-9)
        saved=self.codec.encode(s)
        restored=self.codec.decode(saved,self.codec.schema_version)
        self.assertEqual(self.codec.encode(restored),saved)
        self.assertTrue(restored.player.bench[0].piece.shiny)
        demo.act_sell(restored,'b0')
        self.assertEqual(restored.pool.remaining[6],original)

    def test_paid_skill_replacement_does_not_refund_old_skill(self):
        s,p=self.s,self.s.player
        s.pool.take(9)
        p.bench.append(demo.shop_mod.OwnedPiece(copy.copy(s.templates[9]),3))
        p.gold=10
        arena.learn(s,'b0','surf')
        arena.learn(s,'b0','rest')
        self.assertEqual(p.gold,6)
        self.assertEqual(p.bench[0].technique,'rest')
        self.assertFalse(any(p.inventory.techniques.values()))
        before=self.codec.encode(s)
        with self.assertRaises(ValueError):arena.learn(s,'b0','rest')
        with self.assertRaises(ValueError):arena.learn(s,'b0','cut')
        self.assertEqual(self.codec.encode(s),before)
        restored=self.codec.decode(before,self.codec.schema_version)
        self.assertEqual(restored.player.gold,6)
        self.assertEqual(restored.player.bench[0].technique,'rest')

    def test_first_choice_is_required_and_cannot_be_reclaimed_after_restore(self):
        s=self.s
        with self.assertRaises(demo.DemoError):s.end_prep()
        reward=s.arena_augments_pending[0]
        chosen=reward['options'][0]['id']
        arena.claim_augment(s,reward['id'],chosen)
        payload=self.codec.encode(s)
        restored=self.codec.decode(payload,self.codec.schema_version)
        self.assertEqual(self.codec.encode(restored),payload)
        with self.assertRaises(ValueError):arena.claim_augment(restored,reward['id'],chosen)
        self.assertEqual(len(restored.player.arena_augments_selected),1)

    def test_pre_arena_classic_save_remains_compatible(self):
        classic=demo.Session(7);classic.begin_round(1)
        payload=self.codec.encode(classic)
        payload['rules']=PRE_ARENA_FINGERPRINT
        restored=self.codec.decode(payload,self.codec.schema_version)
        self.assertFalse(restored.is_arena)
        self.assertEqual(restored.player.gold,classic.player.gold)
        arena_payload=self.codec.encode(self.s)
        arena_payload['rules']=PRE_ARENA_FINGERPRINT
        with self.assertRaises(UnknownRulesError):self.codec.decode(arena_payload,self.codec.schema_version)

    def test_scouting_lists_all_eight_seats_and_real_loadouts(self):
        state=demo.state_json(self.s)
        self.assertEqual([row['seat'] for row in state['scouting']],list(range(8)))
        for row,seat in zip(state['scouting'],self.s.seats):
            self.assertEqual(len(row['board']),len(seat.board))
            self.assertEqual([a['id'] for a in row['augments']],[a['id'] for a in seat.arena_augments_selected])
            self.assertTrue(all(o['sid'] in arena.ROSTER for o in row['board']))
        self.assertEqual(len(state['arena']['catalog']),18)
