"""Real expedition rewards, UID configuration, transactional saves and old rules."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/acceptance'))
import demo
import techniques
from session_save import SessionCodec, LEGACY_BASE_FINGERPRINT
from esp32_runtime import StorageIOError, UnsupportedVersionError
from esp32_runtime.storage import _canonical


def fast_render(a, b, rng, weather, path, positions_a=None, hud_snapshot=None, **options):
    battle = demo.Battle(a, b, rng, layout='back', weather_name=weather,
                         positions_a=positions_a, **options)
    result = battle.run()
    return {'n': 0, 'winner': result['winner'], 'survivors': result['survivors'],
            'duration': result['duration'], 'events': []}


class TacticalSessionContracts(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for patcher in (patch.object(demo, 'SAVE_ROOT', self.root),
                        patch.object(demo, 'SESSIONS', {}),
                        patch.object(demo, '_render_battle_frames', side_effect=fast_render)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.codec = SessionCodec()
        result = demo.api_action({'cmd': 'new', 'mode': 'tactics', 'partner': '6', 'seed': '7'})
        self.assertTrue(result['ok'], result)
        self.sid = result['sid']

    @property
    def state(self):
        return demo.SESSIONS[self.sid]

    def act(self, cmd, **params):
        result = demo.api_action({'cmd': cmd, 'sid': self.sid, **params})
        self.assertTrue(result['ok'], result)
        return result

    def reach_reward(self):
        self.act('buy', i='0')
        self.act('move', **{'from': 'b0', 'to': 'g1,2'})
        for round_no in range(1, 6):
            self.assertEqual(self.state.round_no, round_no)
            self.act('end_prep')
            self.assertTrue(self.state.player.alive)
            self.act('next')
        return next(row for row in self.state.rewards if row['seat'] == 0)

    def assert_pool(self):
        from collections import Counter
        held = Counter()
        for seat in self.state.seats:
            held.update(sid for sid in seat.shop.slots if sid is not None)
            for unit in seat.all_pieces():
                held.update(unit.sources)
        for sid, piece in self.state.templates.items():
            self.assertEqual(held[sid] + self.state.pool.remaining[sid], demo.shop_mod.POOL_COPIES[piece.tier])

    def test_real_reward_learning_guard_and_battle_preserve_machine_and_pool(self):
        reward = self.reach_reward()
        self.assertEqual(self.state.ruleset, 'tactics_v5')
        self.assertEqual(len(reward['options']), 3)
        self.assertIn('guard', reward['options'])
        self.assertEqual(sum(self.state.player.inventory.techniques.values()), 0)
        rejected = demo.api_action({'cmd': 'end_prep', 'sid': self.sid})
        self.assertFalse(rejected['ok'])
        self.assertIn('待领取', rejected['error'])
        self.act('claim_reward', reward_id=reward['id'], choice='guard')
        source, target = self.state.player.board
        self.act('learn', uid=source.uid, technique='guard')
        self.act('set_guard', uid=source.uid, target_uid=target.uid)
        expected = {'source': 0, 'target': 1}
        self.assertEqual(self.state.battle_options(self.state.player)['tactics_a']['guard'], expected)
        self.assertEqual(sum(self.state.player.inventory.techniques.values()) +
                         sum(o.technique is not None for o in self.state.player.all_pieces()), 1)
        self.act('end_prep')
        self.assert_pool()
        bot_claims = [row for row in self.state.rewards if row['seat'] != 0 and row['status'] == 'claimed']
        self.assertTrue(bot_claims)
        for seat in self.state.bots:
            if seat.alive:
                self.assertEqual(sum(seat.inventory.techniques.values()) +
                                 sum(o.technique is not None for o in seat.all_pieces()), 1)

    def test_frozen_options_atomic_claim_duplicate_restore_and_full_backup_rollback(self):
        reward = self.reach_reward()
        reward_id = reward['id']
        original = self.codec.encode(self.state)
        backup = demo.backup_bytes(self.sid)
        self.act('resume')
        self.assertEqual(self.codec.encode(self.state), original)
        with patch('esp32_runtime.FileBackend.write_atomic', side_effect=StorageIOError('disk full')):
            failed = demo.api_action({'cmd': 'claim_reward', 'sid': self.sid,
                                      'reward_id': reward_id, 'choice': 'guard'})
        self.assertFalse(failed['ok'])
        self.assertEqual(self.codec.encode(self.state), original)
        self.assertEqual(demo.backup_bytes(self.sid), backup)
        self.act('claim_reward', reward_id=reward_id, choice='guard')
        self.act('resume')
        self.act('claim_reward', reward_id=reward_id, choice='guard')
        self.assertEqual(self.state.player.inventory.techniques['guard'], 1)
        self.assertFalse(demo.api_action({'cmd': 'claim_reward', 'sid': self.sid,
                                         'reward_id': reward_id, 'choice': 'skip'})['ok'])
        self.assertTrue(demo.import_backup(backup, self.sid)['ok'])
        self.assertEqual(self.codec.encode(self.state), original)
        self.act('claim_reward', reward_id=reward_id, choice='guard')
        self.assertEqual(self.state.player.inventory.techniques['guard'], 1)

    def test_guard_invalidated_by_move_sell_and_replacement_without_retargeting(self):
        reward = self.reach_reward()
        self.act('claim_reward', reward_id=reward['id'], choice='guard')
        source, target = self.state.player.board
        self.act('learn', uid=source.uid, technique='guard')
        self.act('set_guard', uid=source.uid, target_uid=target.uid)
        result = self.act('move', **{'from': 'g1,2', 'to': 'g1,5'})
        self.assertIsNone(self.state.tactical[0]['guard'])
        self.assertIn('失效', result['msg'])
        self.act('move', **{'from': 'g1,5', 'to': 'g1,2'})
        self.assertIsNone(self.state.tactical[0]['guard'])
        self.act('set_guard', uid=source.uid, target_uid=target.uid)
        self.state.player.inventory.techniques['rest'] = 1
        self.act('learn', uid=source.uid, technique='rest', replace='1')
        self.assertIsNone(self.state.tactical[0]['guard'])
        self.act('learn', uid=source.uid, technique='guard', replace='1')
        self.act('set_guard', uid=source.uid, target_uid=target.uid)
        self.act('sell', loc='g0,2')
        self.assertIsNone(self.state.tactical[0]['guard'])
        self.assertEqual(self.state.player.inventory.techniques['guard'], 0)
        self.assert_pool()

    def test_weather_requires_compatible_learned_fielded_uid_and_saves(self):
        source = self.state.player.board[0]
        self.state.player.inventory.techniques['sunny_day'] = 1
        self.assertFalse(demo.api_action({'cmd': 'set_weather', 'sid': self.sid, 'uid': source.uid})['ok'])
        self.act('learn', uid=source.uid, technique='sunny_day')
        self.act('set_weather', uid=source.uid)
        self.act('resume')
        self.assertEqual(self.state.battle_options(self.state.player)['tactics_a']['weather'], {'source': 0})
        self.act('move', **{'from': 'g0,2', 'to': 'b0'})
        self.assertIsNone(self.state.tactical[0]['weather'])
        self.assertFalse(demo.api_action({'cmd': 'set_weather', 'sid': self.sid, 'uid': source.uid})['ok'])
        self.act('set_weather', uid='')

    def test_frozen_opponent_teaching_and_tactics_used_after_live_board_changes(self):
        self.reach_reward()
        src = next(b if a is self.state.player else a for a, b in self.state.pairs
                   if self.state.player in (a, b))
        self.assertGreaterEqual(len(src.board), 2)
        src.board[0].technique = 'guard'
        self.state._opponent_view()
        expected = copy.deepcopy(self.state.opponent_tactics)
        self.assertIsNotNone(expected['guard'])
        src.board.reverse()
        for unit in src.board:
            unit.technique = None
        self.state._configure_bot_tactics(src)
        restored = self.codec.decode(self.codec.encode(self.state), 4)
        restored.sid = self.sid
        demo.SESSIONS[self.sid] = restored
        src = restored.seats[src.seat]
        captured = {}
        def render(*args, **kwargs):
            captured.update(kwargs)
            return fast_render(*args, **kwargs)
        with patch.object(demo, '_render_battle_frames', side_effect=render):
            self.state._fight_rendered(6, 0, self.state.player, src, None, ghost=True)
        self.assertEqual(captured['tactics_b'], expected)
        self.assertEqual(captured['learned_b'], self.state.opponent_learned)

    def test_skip_and_terminal_rewards_close_without_extra_inventory(self):
        reward = self.reach_reward()
        self.act('claim_reward', reward_id=reward['id'], choice='skip')
        self.act('claim_reward', reward_id=reward['id'], choice='skip')
        self.assertEqual(sum(self.state.player.inventory.techniques.values()), 0)
        self.act('end_prep')
        self.state.begin_round(10)
        self.state._grant_technique_choice(self.state.player, 10)
        self.state.player.hp = 0
        self.state._eliminate(self.state.player)
        row = self.state.rewards[-1]
        self.assertEqual((row['status'], row['closed_reason']), ('closed', 'eliminated'))
        bot = next(seat for seat in self.state.bots if seat.alive)
        self.state._grant_technique_choice(bot, 10)
        self.state._finalize()
        self.assertTrue(all(row['status'] != 'pending' for row in self.state.rewards))

    def test_base_modes_preserve_old_catalog_inventory_and_reject_tactical_commands(self):
        self.assertEqual(techniques.TECHNIQUE_IDS, ('cut', 'surf', 'rest'))
        for mode in ('classic', 'expedition'):
            result = demo.api_action({'cmd': 'new', 'seed': '7', 'mode': mode, 'partner': '6'})
            self.assertTrue(result['ok'], result)
            session = demo.SESSIONS[result['sid']]
            self.assertEqual(session.ruleset, 'base_v1')
            self.assertEqual(set(session.player.inventory.techniques), set(techniques.TECHNIQUE_IDS))
            self.assertEqual(len(techniques.catalog()), 3)
            for cmd in ('set_guard', 'set_weather', 'claim_reward'):
                self.assertFalse(demo.api_action({'cmd': cmd, 'sid': session.sid})['ok'])
            with self.assertRaises(ValueError):
                techniques.validate_learning(4, 'sunny_day')

    def test_unknown_fingerprint_backup_and_disk_do_not_fall_back_or_overwrite(self):
        self.act('save')  # Have two valid banks before corrupting only the latest rules.
        before = demo.backup_bytes(self.sid)
        state_before = self.codec.encode(self.state)
        body = json.loads(before)
        body['payload']['rules'] = 'unknown-rules'
        del body['checksum']
        body['checksum'] = hashlib.sha256(_canonical(body)).hexdigest()
        raw = _canonical(body)
        self.assertFalse(demo.import_backup(raw, self.sid)['ok'])
        self.assertEqual(demo.backup_bytes(self.sid), before)
        self.assertEqual(self.codec.encode(self.state), state_before)
        store = demo._save_store(self.sid)
        record, _ = store._scan()
        store.backend.write_atomic(store.namespace, store._key(record.index), raw)
        with self.assertRaises(UnsupportedVersionError):
            store.load()
        self.assertFalse(demo.api_action({'cmd': 'save', 'sid': self.sid})['ok'])
        self.assertEqual(store.backend.read(store.namespace, store._key(record.index)), raw)

    def test_schema4_rejects_mixed_rules_missing_snapshots_and_reward_replays(self):
        self.reach_reward()
        original = self.codec.encode(self.state)
        changes = [lambda p: p.__setitem__('ruleset', 'base_v1'),
                   lambda p: p.__setitem__('opponent_tactics', None),
                   lambda p: p['rewards'].append(copy.deepcopy(p['rewards'][0])),
                   lambda p: p['rewards'][0].update(status='claimed', choice='bogus'),
                   lambda p: p['tactical'][0].update(weather={'uid': 'u99999999'})]
        for change in changes:
            bad = copy.deepcopy(original)
            change(bad)
            with self.assertRaises(ValueError):
                self.codec.decode(bad, 4)
        with self.assertRaises(ValueError):
            self.codec.decode(original, 3)

    def test_real_schema3_fixture_replays_existing_commands_and_events_identically(self):
        fixture = json.loads((ROOT / 'tests/fixtures/base-v1-schema3-session.json').read_text())
        self.assertEqual(fixture['initial']['rules'], LEGACY_BASE_FINGERPRINT)
        session = self.codec.decode(fixture['initial'], 3)
        session.sid = self.sid
        demo.SESSIONS[self.sid] = session
        battles = []
        def render(a, b, rng, weather, path, positions_a=None, hud_snapshot=None, **options):
            battle = demo.Battle(a, b, rng, layout='back', weather_name=weather,
                                 positions_a=positions_a, **options)
            result = battle.run()
            battles.append({'events_sha256': hashlib.sha256(json.dumps(
                battle.events, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(),
                'event_count': len(battle.events), 'winner': result['winner'],
                'survivors': {str(k): v for k, v in result['survivors'].items()},
                'duration': result['duration']})
            return {'n': 0, 'winner': result['winner'], 'survivors': result['survivors'],
                    'duration': result['duration'], 'events': []}
        with patch.object(demo, '_render_battle_frames', side_effect=render):
            for command in fixture['commands']:
                result = demo._apply_action({'sid': self.sid, **command})
                self.assertTrue(result['ok'], result)
        actual = self.codec.encode(session)
        actual['rules'] = LEGACY_BASE_FINGERPRINT
        self.assertEqual({key: actual[key] for key in fixture['expected_after']}, fixture['expected_after'])
        self.assertEqual(battles, fixture['expected_battles'])


if __name__ == '__main__':
    unittest.main()
