"""End-to-end contracts for loadout validation and the durable profile outbox."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / 'sim', ROOT / 'tools/acceptance'):
    sys.path.insert(0, str(path))
import demo
import expedition
import metagame
from meta_profile import ProfileStore
from session_save import SessionCodec
from esp32_runtime import StorageIOError


def fast_render(a, b, rng, weather, path, positions_a=None, hud_snapshot=None, **options):
    result = demo.Battle(a, b, rng, layout='back', weather_name=weather,
                         positions_a=positions_a, **options).run()
    return {'n': 0, 'winner': result['winner'], 'survivors': result['survivors'],
            'duration': result['duration'], 'events': []}


class ExpeditionContracts(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for p in (patch.object(demo, 'SAVE_ROOT', self.root), patch.object(demo, 'SESSIONS', {}),
                  patch.object(demo, '_render_battle_frames', side_effect=fast_render)):
            p.start()
            self.addCleanup(p.stop)

    def start(self, **params):
        result = demo.api_action({'cmd': 'new', 'mode': 'expedition', 'partner': '6', 'seed': '7', **params})
        self.assertTrue(result['ok'], result)
        return demo.SESSIONS[result['sid']]

    def action(self, session, cmd, **params):
        r = demo.api_action({'cmd': cmd, 'sid': session.sid, **params})
        self.assertTrue(r['ok'], r)
        return r

    def test_starter_paid_and_loadout_saved_and_duplicate_import_is_one_run(self):
        s = self.start()
        self.assertEqual(s.player.board[0].piece.species_id, 4)
        self.assertEqual(s.player.gold, 6)
        before = SessionCodec().encode(s)
        raw = demo.backup_bytes(s.sid)
        imported = demo.import_backup(raw)
        self.assertTrue(imported['ok'], imported)
        loaded = demo.SESSIONS[imported['sid']]
        self.assertNotEqual(loaded.sid, s.sid)
        self.assertEqual(SessionCodec().encode(loaded), before)
        self.assertEqual(expedition.api_profile()['stats']['runs'], 1)

    def test_locked_or_incompatible_loadout_does_not_create_session(self):
        for params in ({'partner':'143'}, {'technique':'cut'}, {'item':'sash'},
                       {'partner':'6','technique':'surf'}, {'partner':'999'}):
            r = demo.api_action({'cmd':'new','mode':'expedition','seed':'7', **params})
            self.assertFalse(r['ok'], r)
        self.assertEqual(demo.SESSIONS, {})

    def test_real_fielding_unlocks_cut_for_next_run_only(self):
        s = self.start()
        self.action(s, 'end_prep')
        view = expedition.api_profile()
        self.assertEqual(view['stats']['fielded'], 1)
        self.assertTrue(next(t for t in view['techniques'] if t['id']=='cut')['unlocked'])
        self.assertIsNone(s.expedition['technique'])
        new = self.start(technique='cut')
        self.assertEqual(new.expedition['technique'], 'cut')
        self.assertNotEqual(s.run_id, new.run_id)

    def test_profile_write_failure_retains_committed_battle_and_resume_retries(self):
        s = self.start()
        with patch.object(ProfileStore, 'save', side_effect=StorageIOError('profile disk full')):
            result = self.action(s, 'end_prep')
            self.assertIn('档案同步待重试', result['state']['profile_warning'])
        self.assertEqual(s.phase, 'battle')
        before = SessionCodec().encode(s)
        self.action(s, 'resume')
        loaded = demo.SESSIONS[s.sid]
        self.assertEqual(SessionCodec().encode(loaded), before)
        self.assertIsNone(loaded.profile_warning)
        self.assertEqual(expedition.api_profile()['stats']['fielded'], 1)

    def test_session_write_failure_never_publishes_profile_achievement(self):
        s = self.start()
        before = SessionCodec().encode(s)
        original = demo._save_store
        def failing(sid):
            store = original(sid)
            store.save = lambda state: (_ for _ in ()).throw(StorageIOError('session full'))
            return store
        with patch.object(demo, '_save_store', side_effect=failing):
            r = demo.api_action({'cmd':'end_prep','sid':s.sid})
        self.assertFalse(r['ok'])
        self.assertEqual(SessionCodec().encode(demo.SESSIONS[s.sid]), before)
        self.assertEqual(expedition.api_profile()['stats']['fielded'], 0)

    def test_finish_loss_unlocks_equipment_and_rest_once_even_after_import(self):
        s = self.start()
        # Empty-board loss is a real simulated loss; no forged profile writes.
        self.action(s, 'sell', loc='g0,2')
        for _ in range(31):
            if not s.player.alive or s.phase == 'over':
                break
            self.action(s, 'end_prep')
            if s.player.alive and s.phase == 'battle':
                self.action(s, 'next')
        self.assertFalse(s.player.alive)
        view = expedition.api_profile()
        self.assertEqual(view['stats']['finished'], 1)
        self.assertEqual(view['stats']['wins'], 0)
        self.assertTrue(next(i for i in view['items'] if i['id']=='leftovers')['unlocked'])
        raw = demo.backup_bytes(s.sid)
        self.assertTrue(demo.import_backup(raw)['ok'])
        self.assertEqual(expedition.api_profile()['stats']['finished'], 1)
        n = self.start(technique='rest', item='leftovers')
        self.assertEqual(n.player.board[0].item, 'leftovers')

    def test_legacy_migration_and_new_schema_reject_missing_or_bad_extension(self):
        s = self.start(mode='classic')
        codec = SessionCodec()
        data = codec.encode(s)
        legacy = copy.deepcopy(data)
        del legacy['expedition_state']
        a, b = codec.decode(legacy, 1), codec.decode(legacy, 1)
        self.assertEqual(a.run_id, b.run_id)
        self.assertIsNone(a.expedition)
        with self.assertRaises(ValueError):
            codec.decode(legacy, 2)
        for bad in (None, {'run_id':s.run_id,'loadout':{'partner':None,'technique':None,'item':None},'discoveries':s.discoveries}, {'run_id':'bad','loadout':None,'discoveries':s.discoveries},
                    {'run_id':s.run_id,'loadout':{'partner':True,'technique':None,'item':None},'discoveries':s.discoveries},
                    {'run_id':s.run_id,'loadout':None,'discoveries':{'seen':[],'fielded':[6],'won':[]}}):
            invalid = copy.deepcopy(data)
            invalid['expedition_state'] = bad
            with self.assertRaises(ValueError):
                codec.decode(invalid, 2)

    def test_all_battle_paths_receive_budget_including_pve_and_ghost_source(self):
        s = self.start()
        self.assertEqual(s.battle_options(s.player, s.bots[0])['team_options'][0]['partner'], 6)
        self.assertEqual(s.battle_options(s.bots[0], s.player)['team_options'][1]['partner'], 6)
        self.assertEqual(s.battle_options(s.bots[0], s.bots[1])['team_options'], [None,None])
        calls = []
        original = demo.Battle
        def capture(*args, **kwargs):
            calls.append(kwargs)
            return original(*args, **kwargs)
        with patch.object(demo, 'Battle', side_effect=capture):
            for _ in range(5):
                self.action(s, 'end_prep')
                if s.phase == 'battle':
                    self.action(s, 'next')
        self.assertTrue(calls)
        self.assertTrue(all(c.get('stat_mode')=='budget_v1' for c in calls))
        self.assertTrue(any(c.get('weather_name') is None for c in calls))

    def test_backup_round_trip_and_corrupt_profile_is_not_reset(self):
        s = self.start()
        before = expedition.api_profile()['stats']
        raw = expedition.store().export_backup()
        self.assertTrue(expedition.import_profile(raw, True)['ok'])
        self.assertTrue(expedition.import_profile(raw)['ok'])
        self.assertEqual(expedition.api_profile()['stats'], before)
        self.assertFalse(expedition.import_profile(b'broken')['ok'])
        self.assertEqual(expedition.api_profile()['stats'], before)

    def test_checksumming_invalid_loadout_cannot_replace_any_state(self):
        from esp32_runtime.storage import _canonical
        s = self.start()
        before = demo.backup_bytes(s.sid)
        memory = SessionCodec().encode(s)
        profile = expedition.store().export_backup()
        for bad in (None, {'run_id':s.run_id,'loadout':{'partner':None,'technique':None,'item':None},
                           'discoveries':s.discoveries},
                    {'run_id':s.run_id,'loadout':{'partner':{'partner':6},'technique':None,'item':None},
                     'discoveries':s.discoveries}):
            body = json.loads(before)
            body['payload']['expedition_state'] = bad
            del body['checksum']
            body['checksum'] = hashlib.sha256(_canonical(body)).hexdigest()
            raw = _canonical(body)
            self.assertFalse(demo.import_backup(raw, s.sid, inspect_only=True)['ok'])
            self.assertFalse(demo.import_backup(raw, s.sid)['ok'])
            self.assertEqual(demo.backup_bytes(s.sid), before)
            self.assertEqual(SessionCodec().encode(demo.SESSIONS[s.sid]), memory)
            self.assertEqual(expedition.store().export_backup(), profile)

    def test_visible_pve_wave_is_recorded_in_seen_dex(self):
        s = self.start()
        s.begin_round(5)
        s.observe()
        self.assertTrue(set(demo.PVE_WAVES[0]) <= set(s.discoveries['seen']))
        self.assertEqual(s.discoveries['fielded'], [])
        demo.sync_profile(s)
        shown = {d['id']: d for d in expedition.api_profile()['dex']}
        self.assertTrue(shown[83]['seen'])

    def test_empty_opponent_victory_still_marks_fielded_team_as_won(self):
        s = self.start()
        opponent = s.bots[0]
        opponent.board = []
        s.pairs, s.ghost_seat = [(s.player, opponent)], None
        s.end_prep()
        self.assertEqual(s.player.streak, 1)
        self.assertIn(4, s.discoveries['won'])


if __name__ == '__main__':
    unittest.main()
