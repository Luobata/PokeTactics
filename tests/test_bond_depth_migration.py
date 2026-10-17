"""The research-era save keeps committed battles and nonzero research intact."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance'), str(ROOT)]
import demo
import session_save


class BondDepthMigration(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT / 'tests/fixtures/families-v2-pre-bond-depth.json').read_text())
        self.codec = session_save.SessionCodec()

    def test_real_terminal_predecessor_preserves_every_ledger(self):
        self.assertEqual(self.payload['rules'], session_save.PRE_BOND_DEPTH_FINGERPRINT)
        untouched = copy.deepcopy(self.payload)
        with patch.object(demo.Session, 'end_prep', side_effect=AssertionError('no combat on load')), \
                patch.object(demo.Session, 'begin_round', side_effect=AssertionError('no rewards on load')), \
                patch.object(demo, '_render_battle_frames', side_effect=AssertionError('no rendering on load')):
            restored = self.codec.decode(self.payload, self.codec.schema_version)
        expected = copy.deepcopy(self.payload)
        expected['rules'] = session_save.rules_fingerprint()
        self.assertEqual(self.codec.encode(restored), expected)
        self.assertEqual(self.payload, untouched)
        self.assertIn('历史战斗结果不会重算', restored.save_warning)
        import arena_research
        tracks = arena_research.view(restored.arena_research, 0)['tracks']
        self.assertEqual(next(row['stacks'] for row in tracks if row['id'] == 'tempo'), 5)

    def test_research_is_required_for_both_current_and_previous_rules(self):
        for rules in (session_save.rules_fingerprint(), session_save.PRE_BOND_DEPTH_FINGERPRINT):
            for bad_research in (None, {}):
                payload = copy.deepcopy(self.payload)
                payload['rules'] = rules
                payload['arena']['research'] = bad_research
                with self.subTest(rules=rules, research=bad_research), self.assertRaises(ValueError):
                    self.codec.decode(payload, self.codec.schema_version)

    def test_unknown_rules_still_fail_closed(self):
        self.payload['rules'] = '0' * 64
        with self.assertRaises(session_save.UnknownRulesError):
            self.codec.decode(self.payload, self.codec.schema_version)

    def test_live_process_does_not_relabel_rules_after_source_edits(self):
        original = session_save.rules_fingerprint()
        with patch.object(session_save, '_compute_rules_fingerprint', return_value='changed'), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('no per-save disk scan')):
            self.assertEqual(session_save.rules_fingerprint(), original)


if __name__ == '__main__':
    unittest.main()
