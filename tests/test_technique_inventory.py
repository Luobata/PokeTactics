"""Teaching is a durable per-unit resource, including evolution and old saves."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / 'sim', ROOT / 'tools/acceptance'):
    sys.path.insert(0, str(path))
import demo
import techniques
from session_save import SessionCodec
from esp32_runtime import StorageIOError


class TechniqueInventoryContracts(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for p in (patch.object(demo, 'SAVE_ROOT', Path(folder.name)),
                  patch.object(demo, 'SESSIONS', {})):
            p.start()
            self.addCleanup(p.stop)
        result = demo.api_action({'cmd': 'new', 'seed': '7'})
        self.assertTrue(result['ok'], result)
        self.sid = result['sid']
        self.codec = SessionCodec()

    @property
    def session(self):
        return demo.SESSIONS[self.sid]

    def add(self, sid, machine=None):
        s = self.session
        s.pool.take(sid)
        owned = demo.shop_mod.OwnedPiece(s.templates[sid], s.templates[sid].tier)
        owned.technique = machine
        s.player.bench.append(owned)
        s.ensure_unit_ids()
        return owned

    def action(self, cmd, **params):
        return demo.api_action({'cmd': cmd, 'sid': self.sid, **params})

    def test_ordinary_pokemon_learning_replacement_and_sell_conserve_machines(self):
        owned = self.add(7)
        inv = self.session.player.inventory.techniques
        inv.update(surf=1, rest=1)
        learned = self.action('learn', uid=owned.uid, technique='surf')
        self.assertTrue(learned['ok'], learned)
        self.assertEqual(learned['state']['bench'][0]['technique']['id'], 'surf')
        before = self.codec.encode(self.session)
        for params in ({'technique': 'surf'}, {'technique': 'rest'}, {'technique': 'cut', 'replace': '1'}):
            bad = self.action('learn', uid=owned.uid, **params)
            self.assertFalse(bad['ok'], bad)
            self.assertEqual(self.codec.encode(self.session), before)
        self.assertTrue(self.action('learn', uid=owned.uid, technique='rest', replace='1')['ok'])
        inv = self.session.player.inventory.techniques
        self.assertEqual(inv, {'cut': 0, 'surf': 1, 'rest': 0})
        self.assertTrue(self.action('sell', loc='b0')['ok'])
        self.assertEqual(inv, {'cut': 0, 'surf': 1, 'rest': 1})

    def test_uid_survives_bench_compaction_move_and_process_restart(self):
        first, target = self.add(1), self.add(7)
        self.session.player.inventory.techniques['surf'] = 1
        self.assertTrue(self.action('sell', loc='b0')['ok'])
        self.assertTrue(self.action('move', **{'from': 'b0', 'to': 'g1,4'})['ok'])
        self.assertTrue(self.action('learn', uid=target.uid, technique='surf')['ok'])
        before = self.codec.encode(self.session)
        demo.SESSIONS.clear()
        resumed = self.action('resume')
        self.assertTrue(resumed['ok'], resumed)
        self.assertEqual(self.codec.encode(self.session), before)
        self.assertEqual(resumed['state']['board'][1][4]['uid'], target.uid)
        self.assertFalse(self.action('learn', uid=first.uid, technique='rest')['ok'])

    def test_merge_retains_first_identity_and_refunds_extra_learning(self):
        first = self.add(1, 'cut')
        self.add(1, 'rest')
        self.add(1, 'cut')
        self.session.combine_player()
        merged = self.session.player.bench[0]
        self.assertEqual((merged.piece.species_id, merged.uid, merged.technique), (2, first.uid, 'cut'))
        self.assertEqual(self.session.player.inventory.techniques, {'cut': 1, 'surf': 0, 'rest': 1})
        encoded = self.codec.encode(self.session)
        self.assertEqual(self.codec.encode(self.codec.decode(encoded, 3)), encoded)

    def test_legacy_schema_2_loadout_migrates_once_without_duplication(self):
        owned = self.add(4)
        s = self.session
        s.expedition = {'partner': 6, 'technique': 'cut', 'item': None}
        data = self.codec.encode(s)
        data.pop('next_unit_id')
        data.pop('opponent_learned')
        for seat in data['seats']:
            seat.pop('techniques')
            for record in seat['board'] + seat['bench'] + [g[2] for g in seat.get('grid', [])]:
                record.pop('uid')
                record.pop('technique')
        restored = self.codec.decode(data, 2)
        self.assertEqual(restored.player.bench[0].technique, 'cut')
        self.assertIsNone(restored.expedition['technique'])
        again = self.codec.decode(self.codec.encode(restored), 3)
        self.assertEqual(again.player.bench[0].technique, 'cut')
        self.assertEqual(sum(again.player.inventory.techniques.values()), 0)
        # Family sold in the old run: its machine becomes reusable stock.
        data['expedition_state']['loadout']['partner'] = 3
        recovered = self.codec.decode(data, 2)
        self.assertEqual(recovered.player.inventory.techniques['cut'], 1)

    def test_duplicate_ids_bad_compatibility_counter_and_inventory_rejected(self):
        self.add(1)
        self.add(7)
        base = self.codec.encode(self.session)
        mutations = [
            lambda d: d['seats'][0]['bench'][1].update(uid=d['seats'][0]['bench'][0]['uid']),
            lambda d: d['seats'][0]['bench'][0].update(technique='surf'),
            lambda d: d['seats'][0]['bench'][0].update(uid=True),
            lambda d: d.update(next_unit_id=1),
            lambda d: d['seats'][0]['techniques'].update(cut=-1),
            lambda d: d['seats'][0]['techniques'].update(rest=True),
            lambda d: d['seats'][0].pop('techniques'),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                bad = copy.deepcopy(base)
                mutate(bad)
                with self.assertRaises(ValueError):
                    self.codec.decode(bad, 3)

    def test_stale_or_failed_commit_does_not_consume_machine(self):
        owned = self.add(1)
        self.session.player.inventory.techniques['cut'] = 1
        self.assertTrue(self.action('save')['ok'])
        before = self.codec.encode(self.session)
        self.assertFalse(self.action('learn', uid=owned.uid, technique='cut', expected_sequence='0')['ok'])
        with patch('esp32_runtime.FileBackend.write_atomic', side_effect=StorageIOError('disk full')):
            self.assertFalse(self.action('learn', uid=owned.uid, technique='cut')['ok'])
        self.assertEqual(self.codec.encode(self.session), before)
        self.assertTrue(self.action('resume')['ok'])
        self.assertEqual(self.codec.encode(self.session), before)

    def test_every_catalog_entry_has_real_compatibility_and_no_partner_requirement(self):
        self.assertTrue(techniques.compatible_species(7, 'surf'))
        self.assertFalse(techniques.compatible_species(4, 'surf'))
        self.assertTrue(techniques.compatible_species(94, 'rest'))
        self.assertFalse(techniques.compatible_species(94, 'cut'))
        self.assertFalse(techniques.compatible_species(True, 'rest'))
        self.assertFalse(techniques.compatible_species(7, []))

    def test_pve_machine_drop_survives_settlement_resume_without_reaward(self):
        s = self.session
        s.expedition = {'partner': 6, 'technique': None, 'item': None}
        s.begin_round(5)  # Empty board resolves a real defeat without rendering.
        result = self.action('end_prep')
        self.assertTrue(result['ok'], result)
        self.assertEqual(sum(s.player.inventory.techniques.values()), 1)
        before = self.codec.encode(s)
        self.assertTrue(self.action('resume')['ok'])
        self.assertEqual(self.codec.encode(self.session), before)
        self.assertFalse(self.action('end_prep')['ok'])
        self.assertEqual(sum(self.session.player.inventory.techniques.values()), 1)

    def test_frozen_opponent_teaching_is_used_even_when_source_changes(self):
        s = self.session
        own = self.add(4)
        self.assertTrue(self.action('move', **{'from': 'b0', 'to': 'g0,2'})['ok'])
        source = s.bots[0]
        # Freeze legal teaching against the exact displayed order.
        s.opponent_comp = list(source.battle_comp())
        s.opponent_learned = ['rest'] * len(s.opponent_comp)
        for unit in source.board:
            unit.technique = None
        with patch.object(demo, '_render_battle_frames', return_value={
                'n': 0, 'winner': None, 'survivors': {0: 1, 1: 1}, 'duration': 10, 'events': []}) as render:
            s._fight_rendered(1, 0, s.player, source, None)
        self.assertEqual(render.call_args.kwargs['learned_b'], s.opponent_learned)
        self.assertEqual(own.uid, s.player.board[0].uid)
        encoded = self.codec.encode(s)
        self.assertEqual(self.codec.encode(self.codec.decode(encoded, 3)), encoded)


if __name__ == '__main__':
    unittest.main()
