"""Versioned evolution decisions: real pool/capacity/inheritance/save boundaries."""
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
from session_save import SessionCodec, LEGACY_COUNTER_PACING_FINGERPRINT, UnknownRulesError
from esp32_runtime import StorageIOError
from test_tactical_session import fast_render


class EvolutionChoices(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        for p in (patch.object(demo, 'SAVE_ROOT', Path(directory.name)),
                  patch.object(demo, 'SESSIONS', {}),
                  patch.object(demo, '_render_battle_frames', side_effect=fast_render)):
            p.start(); self.addCleanup(p.stop)
        created = demo.api_action({'cmd': 'new', 'seed': '7', 'mode': 'tactics', 'partner': '6'})
        self.assertTrue(created['ok'], created)
        self.sid = created['sid']; self.codec = SessionCodec()
        self.clear_player()

    @property
    def s(self):
        return demo.SESSIONS[self.sid]

    def clear_player(self):
        for unit in self.s.player.all_pieces():
            for sid in unit.sources:
                self.s.pool.put(sid)
        self.s.player.grid = {}; self.s.player.bench = []
        self.s.player.shop.return_all()
        self.s.player.level = 7; self.s.player.gold = 100

    def add(self, sid, pos=None, locked=False, item=None, technique=None):
        self.s.pool.take(sid)
        unit = demo.shop_mod.OwnedPiece(self.s.templates[sid], self.s.templates[sid].tier)
        unit.evolution_locked = locked; unit.item = item; unit.technique = technique
        if pos is None:
            self.s.player.bench.append(unit)
        else:
            self.s.player.grid[pos] = unit
        self.s.ensure_unit_ids()
        return unit

    def set_version(self, version):
        self.s.ruleset = version
        self.s.opponent_tactics = None if version == "base_v1" else {"guard": None, "weather": None}
        for seat in self.s.seats:
            seat.inventory.ruleset = version
            seat.inventory.techniques = dict.fromkeys(demo.techniques_mod.ids_for(version), 0)

    def offer(self, sid):
        self.s.player.shop.return_all(); self.s.pool.take(sid)
        self.s.player.shop.slots[0] = sid

    def act(self, cmd, **args):
        result = demo.api_action({'sid': self.sid, 'cmd': cmd, **args})
        self.assertTrue(result['ok'], result)
        return result

    def assert_pool(self):
        from collections import Counter
        held = Counter()
        for seat in self.s.seats:
            held.update(sid for sid in seat.shop.slots if sid is not None)
            for unit in seat.all_pieces(): held.update(unit.sources)
        for sid, piece in self.s.templates.items():
            self.assertEqual(held[sid] + self.s.pool.remaining[sid], demo.shop_mod.POOL_COPIES[piece.tier])

    def test_preview_is_read_only_and_recursive_prediction_matches_purchase(self):
        self.add(1, (0, 0), item='choice_band', technique='guard')
        self.add(1, (0, 1), item='leftovers', technique='guard')
        self.add(2); self.add(2)
        self.offer(1)
        before = self.codec.encode(self.s)
        preview = demo.state_json(self.s)['shop'][0]['evolution_preview']
        self.assertEqual(self.codec.encode(self.s), before)
        self.assertEqual([(r['from_sid'], r['to_sid']) for r in preview['merges']], [(1, 2), (2, 3)])
        self.assertEqual(preview, demo._evolution_preview(self.s, shop_index=0))
        self.act('buy', i='0')
        self.assertEqual(len(self.s.player.bench), 1)
        unit = self.s.player.bench[0]; predicted = preview['merges'][-1]
        self.assertEqual((unit.piece.species_id, unit.uid, unit.invested, unit.item, unit.technique),
                         (predicted['to_sid'], predicted['result_uid'], predicted['invested'],
                          predicted['inherit_item'], predicted['inherit_technique']))
        self.assertEqual(unit.sources, [2, 2, 1, 1, 1, 2, 3])
        self.assertEqual(self.s.player.inventory.finished, ['leftovers'])
        self.assertEqual(self.s.player.inventory.techniques['guard'], 1)
        self.assertEqual(self.s.player.combines, 2)
        self.assert_pool()

    def test_defer_locks_pair_and_fourth_purchase_cannot_consume_it(self):
        first = self.add(1, (0, 0)); self.add(1)
        self.offer(1); self.act('buy', i='0', evolution='defer')
        self.assertEqual(len(self.s.player.all_pieces()), 3)
        self.assertTrue(all(o.evolution_locked for o in self.s.player.all_pieces()))
        self.offer(1); self.act('buy', i='0')
        self.assertEqual(len(self.s.player.all_pieces()), 4)
        self.assertEqual(self.s.player.combines, 0)
        self.assertTrue(next(o for o in self.s.player.all_pieces() if o.uid == first.uid).evolution_locked)
        self.assert_pool()

    def test_explicit_selected_fourth_copy_and_only_one_step(self):
        units = [self.add(1, locked=True) for _ in range(4)]
        self.add(2); self.add(2)
        fourth = units[-1]
        preview = demo._evolution_preview(self.s, uid=fourth.uid)
        self.assertIn(fourth.uid, preview['merges'][0]['source_uids'])
        self.assertNotIn(units[2].uid, preview['merges'][0]['source_uids'])
        self.act('evolve', uid=fourth.uid)
        self.assertEqual([o.piece.species_id for o in self.s.player.bench], [1, 2, 2, 2])
        self.assertEqual(self.s.player.combines, 1)
        self.assertEqual(self.s.player.bench[0].uid, units[2].uid)
        self.assertFalse(self.s.player.bench[-1].evolution_locked)
        self.assert_pool()

    def test_unlock_and_move_do_not_trigger_merge_and_lock_survives_restart(self):
        unit = self.add(1, locked=True); self.add(1, locked=True); self.add(1, locked=True)
        self.act('set_evolution_lock', uid=unit.uid, locked='0')
        self.act('move', **{'from': 'b0', 'to': 'g0,2'})
        self.assertEqual(self.s.player.combines, 0)
        before = self.codec.encode(self.s)
        demo.SESSIONS.clear(); self.act('resume')
        self.assertEqual(self.codec.encode(self.s), before)
        self.assertEqual([o.evolution_locked for o in self.s.player.all_pieces()], [False, True, True])

    def test_full_bench_buy_can_merge_but_cannot_defer(self):
        self.add(1); self.add(1)
        for sid in (95, 123, 131, 143): self.add(sid)
        self.offer(1)
        plan = demo._evolution_preview(self.s, shop_index=0)
        self.assertTrue(plan['auto_allowed']); self.assertFalse(plan['defer_allowed'])
        before = self.codec.encode(self.s)
        failed = demo.api_action({'sid': self.sid, 'cmd': 'buy', 'i': '0', 'evolution': 'defer'})
        self.assertFalse(failed['ok']); self.assertEqual(self.codec.encode(self.s), before)
        self.act('buy', i='0')
        self.assertEqual(len(self.s.player.bench), 5); self.assert_pool()

    def test_manual_board_merge_needs_bench_slot_and_pool_exhaustion_preserves_sources(self):
        units = [self.add(1, (0, i), locked=True) for i in range(3)]
        for _ in range(6): self.add(95)
        before = self.codec.encode(self.s)
        rejected = demo.api_action({'sid': self.sid, 'cmd': 'evolve', 'uid': units[0].uid})
        self.assertFalse(rejected['ok']); self.assertIn('备战', rejected['error'])
        self.assertEqual(self.codec.encode(self.s), before)
        self.act('sell', loc='b0')
        # Exhaust stock through legitimate held shop/bench sources, not forged pool counts.
        remaining = self.s.pool.remaining[2]
        other = self.s.bots[0]
        for _ in range(remaining):
            self.s.pool.take(2); other.bench.append(demo.shop_mod.OwnedPiece(self.s.templates[2], 2))
        plan = demo._evolution_preview(self.s, uid=units[0].uid)
        self.assertFalse(plan['auto_allowed']); self.assertIn('售罄', plan['detail'])
        self.assertEqual(len(self.s.player.grid), 3)
        self.assert_pool()

    def test_incompatible_teaching_returns_to_inventory_and_removed_guard_is_invalidated(self):
        first = self.add(133, (1, 0), locked=True, technique='guard')
        target = self.add(95, (1, 1))
        self.add(133, (0, 0), locked=True, technique='cut'); self.add(133, locked=True)
        self.act('set_guard', uid=first.uid, target_uid=target.uid)
        plan = demo._evolution_preview(self.s, uid=first.uid)
        self.assertEqual(plan['merges'][0]['board_after'], 1)
        self.act('evolve', uid=first.uid)
        self.assertIsNone(self.s.tactical[0]['guard'])
        self.assertEqual(self.s.player.bench[0].technique, 'guard')
        self.assertEqual(self.s.player.inventory.techniques['cut'], 1)

    def test_terminal_and_trade_forms_reject_ordinary_choices(self):
        for sid in (95, 123, 131, 143, 3, 64, 67, 93):
            unit = self.add(sid)
            before = self.codec.encode(self.s)
            for cmd, args in [('set_evolution_lock', {'uid': unit.uid, 'locked': '1'}), ('evolve', {'uid': unit.uid})]:
                result = demo.api_action({'sid': self.sid, 'cmd': cmd, **args})
                self.assertFalse(result['ok']); self.assertEqual(self.codec.encode(self.s), before)
            self.offer(sid)
            result = demo.api_action({'sid': self.sid, 'cmd': 'buy', 'i': '0', 'evolution': 'defer'})
            self.assertFalse(result['ok'])
            self.clear_player()

    def test_save_failures_backup_restore_and_stale_sequence_are_atomic(self):
        unit = self.add(1); self.add(1); self.add(1)
        self.act('save'); before = self.codec.encode(self.s)
        sequence = self.s.save_sequence; backup = demo.backup_bytes(self.sid)
        with patch('esp32_runtime.FileBackend.write_atomic', side_effect=StorageIOError('disk full')):
            rejected = demo.api_action({'sid': self.sid, 'cmd': 'set_evolution_lock', 'uid': unit.uid, 'locked': '1'})
        self.assertFalse(rejected['ok']); self.assertEqual(self.codec.encode(self.s), before)
        self.act('set_evolution_lock', uid=unit.uid, locked='1')
        locked = self.codec.encode(self.s)
        stale = demo.api_action({'sid': self.sid, 'cmd': 'evolve', 'uid': unit.uid, 'expected_sequence': str(sequence)})
        self.assertFalse(stale['ok']); self.assertEqual(self.codec.encode(self.s), locked)
        self.assertTrue(demo.import_backup(backup, self.sid)['ok'])
        self.assertEqual(self.codec.encode(self.s), before)
        self.act('restore_checkpoint'); self.assertEqual(self.codec.encode(self.s), locked)

    def test_versioned_fields_and_fingerprint_do_not_enable_choices_in_old_saves(self):
        self.add(1)
        payload = self.codec.encode(self.s)
        forged = copy.deepcopy(payload); forged['rules'] = LEGACY_COUNTER_PACING_FINGERPRINT
        with self.assertRaises(UnknownRulesError): self.codec.decode(forged, 4)
        for value in (None, 1, 'false'):
            invalid = copy.deepcopy(payload); invalid['seats'][0]['bench'][0]['evolution_locked'] = value
            with self.assertRaises(ValueError): self.codec.decode(invalid, 4)
        invalid = copy.deepcopy(payload); del invalid['seats'][0]['bench'][0]['evolution_locked']
        with self.assertRaises(ValueError): self.codec.decode(invalid, 4)
        self.add(95)
        invalid = self.codec.encode(self.s); invalid['seats'][0]['bench'][1]['evolution_locked'] = True
        with self.assertRaises(ValueError): self.codec.decode(invalid, 4)
        for version in ('base_v1', 'tactics_v1', 'tactics_v2', 'tactics_v3', 'tactics_v4'):
            self.set_version(version)
            old = self.codec.encode(self.s)
            self.assertNotIn('evolution_locked', old['seats'][0]['bench'][0])
            old['seats'][0]['bench'][0]['evolution_locked'] = False
            with self.assertRaises(ValueError): self.codec.decode(old, 4)
            with self.assertRaises(demo.DemoError): demo.act_evolution_lock(self.s, self.s.player.bench[0].uid, '1')

    def test_old_rules_keep_immediate_recursive_combine(self):
        for version in ('base_v1', 'tactics_v1', 'tactics_v2', 'tactics_v3', 'tactics_v4'):
            self.clear_player(); self.set_version(version)
            self.add(1); self.add(1); self.add(2); self.add(2); self.offer(1)
            self.act('buy', i='0')
            self.assertEqual([o.piece.species_id for o in self.s.player.bench], [3])
            self.assertNotIn('evolution_preview', demo.state_json(self.s)['shop'][1] or {})
            self.assert_pool()

    def test_v5_preserves_v4_complete_combat_events_for_same_tactical_inputs(self):
        from evolution_fairness_probe import battle_for, SUN_CONTROL, RAIN_GARDEN
        for seed in range(2026100580000, 2026100580020):
            streams = []
            for version in ('tactics_v4', 'tactics_v5'):
                battle, result = battle_for(SUN_CONTROL, RAIN_GARDEN, seed, version)
                streams.append(({key: result[key] for key in ('winner', 'survivors', 'duration')}, battle.events))
            self.assertEqual(streams[0], streams[1], seed)

    def test_v4_golden_replays_complete_state_and_event_stream(self):
        saved = json.loads((ROOT / 'tests/fixtures/tactics-v4-schema4-session.json').read_text())
        session = self.codec.decode(saved['initial'], 4); session.sid = self.sid
        demo.SESSIONS[self.sid] = session
        battles = []
        def render(a, b, rng, weather, path, positions_a=None, hud_snapshot=None, **options):
            battle = demo.Battle(a, b, rng, layout='back', weather_name=weather, positions_a=positions_a, **options)
            result = battle.run()
            battles.append({'events_sha256': hashlib.sha256(json.dumps(battle.events, ensure_ascii=False,
                           separators=(',', ':')).encode()).hexdigest(), 'event_count': len(battle.events),
                           'winner': result['winner'], 'survivors': {str(k): v for k, v in result['survivors'].items()},
                           'duration': result['duration']})
            return {'n': 0, 'winner': result['winner'], 'survivors': result['survivors'], 'duration': result['duration'], 'events': []}
        with patch.object(demo, '_render_battle_frames', side_effect=render):
            for command in saved['commands']:
                result = demo._apply_action({'sid': self.sid, **command}); self.assertTrue(result['ok'], result)
        actual = self.codec.encode(session); actual['rules'] = LEGACY_COUNTER_PACING_FINGERPRINT
        self.assertEqual(actual, saved['expected_after'])
        self.assertEqual(battles, saved['expected_battles'])


if __name__ == '__main__':
    unittest.main()
