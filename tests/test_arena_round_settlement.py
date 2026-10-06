"""Round results grant real resources once, including ghosts and old saves."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/acceptance'))
import demo
import arena
from session_save import SessionCodec, UnknownRulesError


class ArenaRoundSettlement(unittest.TestCase):
    def session(self):
        s = demo.Session(7, 'arena_v1')
        s.begin_round(1)
        choice = s.arena_augments_pending[0]
        arena.claim_augment(s, choice['id'], choice['options'][0]['id'])
        s.pool.take(26)
        s.player.grid[(2, 2)] = demo.shop_mod.OwnedPiece(copy.copy(s.templates[26]), 1)
        return s

    @staticmethod
    def result(winner):
        return {'n': 0, 'winner': winner, 'survivors': {0: 1, 1: 1},
                'duration': 1, 'events': []}

    def test_player_winner_mapping_when_player_is_second_and_restore_is_idempotent(self):
        codec = SessionCodec()
        for winner, expected in ((0, 'win'), (1, 'loss'), (None, 'draw')):
            with self.subTest(winner=winner):
                s = self.session()
                s.pairs = [(s.seats[1], s.player), (s.seats[2], s.seats[3]),
                           (s.seats[4], s.seats[5]), (s.seats[6], s.seats[7])]
                with patch.object(s, '_fight_rendered', return_value=self.result(winner)), \
                     patch.object(s, '_fight', return_value=self.result(0)):
                    s.end_prep()
                rows = {row['seat']: row for row in s.arena_loot}
                self.assertEqual(len(rows), 8)
                self.assertEqual(rows[0]['result'], expected)
                self.assertEqual(len(rows[0]['grants']), 2 if expected == 'win' else 1)
                self.assertEqual(rows[1]['result'], 'loss' if expected == 'win' else 'win' if expected == 'loss' else 'draw')
                saved = codec.encode(s)
                restored = codec.decode(saved, codec.schema_version)
                self.assertEqual(codec.encode(restored), saved)
                restored._grant_arena_loot(restored.player, expected)
                self.assertEqual(codec.encode(restored), saved)
                with self.assertRaises(demo.DemoError):
                    restored.end_prep()

    def test_pve_obeys_same_two_one_rule_without_old_bonus_drops(self):
        for winner in (0, 1, None):
            s = self.session()
            s.begin_round(5)
            before = [sum(e.inventory.components.values()) + len(e.inventory.finished)
                      + sum(e.inventory.techniques.values()) for e in s.seats]
            with patch.object(s, '_fight_rendered', return_value=self.result(winner)):
                s.end_prep()
            after = sum(s.player.inventory.components.values()) + len(s.player.inventory.finished) + sum(s.player.inventory.techniques.values())
            self.assertEqual(after - before[0], 2 if winner == 0 else 1)
            self.assertEqual(len(s.arena_loot), 8)

    def test_ghost_grants_only_real_participant_once(self):
        s = self.session()
        s.seats[7].hp = 0
        s._eliminate(s.seats[7])
        s.pairs = [(s.seats[1], s.seats[2]), (s.seats[3], s.seats[4]), (s.seats[5], s.seats[6])]
        s.ghost_seat, s.ghost_src = s.player, s.seats[1]
        with patch.object(s, '_fight_rendered', return_value=self.result(0)), \
             patch.object(s, '_fight', return_value=self.result(0)):
            s.end_prep()
        self.assertEqual(sorted(r['seat'] for r in s.arena_loot), list(range(7)))
        self.assertEqual(next(r['result'] for r in s.arena_loot if r['seat'] == 0), 'win')

    def test_reward_ledger_rejects_duplicate_and_wrong_count(self):
        s = self.session()
        with patch.object(s, '_fight_rendered', return_value=self.result(0)), \
             patch.object(s, '_fight', return_value=self.result(0)):
            s.end_prep()
        codec = SessionCodec()
        snapshot = codec.encode(s)
        for invalid in ('duplicate', 'count', 'future'):
            bad = copy.deepcopy(snapshot)
            if invalid == 'duplicate': bad['arena']['loot'].append(bad['arena']['loot'][0])
            if invalid == 'count': bad['arena']['loot'][0]['grants'] = []
            if invalid == 'future': bad['phase'] = 'prep'
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                codec.decode(bad, codec.schema_version)

    def test_real_v4_save_preserves_front_and_back_without_replaying_past_reward(self):
        payload = json.loads((ROOT / 'tests/fixtures/arena-v4-prep.json').read_text())
        codec = SessionCodec()
        restored = codec.decode(payload, 4)
        self.assertEqual(sorted(restored.player.grid), [(0, 3), (2, 2)])
        self.assertEqual([o.piece.species_id for o in restored.player.board], [26, 68])
        self.assertEqual(restored.player.battle_positions(), [(2, 5), (3, 3)])
        self.assertEqual(len(demo.state_json(restored)['board']), 3)
        self.assertEqual(restored.arena_loot, [])
        upgraded = codec.encode(restored)
        self.assertEqual(codec.encode(codec.decode(upgraded, 5)), upgraded)
        settled = copy.deepcopy(payload)
        settled['phase'] = 'battle'
        settled['arena']['pending'] = []
        settled['arena']['selected'][0] = ['sharp_focus']
        settled['last_battle'] = {'winner': 1, 'round': 1, 'duration': 12,
                                  'survivors': {'0': 0, '1': 1}}
        battle = codec.decode(settled, 4)
        self.assertEqual(battle.arena_loot_start, 2)
        self.assertEqual(battle.arena_loot, [])
        self.assertEqual(codec.encode(codec.decode(codec.encode(battle), 5)), codec.encode(battle))
        payload['rules'] = 'unknown-future-fingerprint'
        with self.assertRaises(UnknownRulesError): codec.decode(payload, 4)


if __name__ == '__main__':
    unittest.main()
