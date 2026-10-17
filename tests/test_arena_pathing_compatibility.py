"""寻路开火线修复前的存档指纹兼容：记录布局一致，纯战斗逻辑升级。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools' / 'acceptance')]
import demo
from arena_save_expectations import (_held_counts,
                                     downgrade_to_pre_legendary_pool,
                                     migrate_legendary_pool)
from session_save import PRE_PATHING_FIX_FINGERPRINT, SessionCodec


def new_session(seed=7):
    session = demo.Session(seed, 'arena_v1')
    session.begin_round(1)
    return session


class ArenaPathingCompatibility(unittest.TestCase):
    def setUp(self):
        self.codec = SessionCodec()
        self.session = new_session()

    def test_pre_pathing_fix_saves_decode_with_warning_and_roundtrip(self):
        payload = self.codec.encode(self.session)
        payload['rules'] = PRE_PATHING_FIX_FINGERPRINT
        downgrade_to_pre_legendary_pool(payload)
        restored = self.codec.decode(payload, self.codec.schema_version)
        self.assertIn('已修复战斗寻路', restored.save_warning)
        current = self.codec.encode(restored)
        self.assertEqual(current['rules'], self.codec.encode(self.session)['rules'])
        expected = {k: v for k, v in payload.items() if k != 'rules'}
        from arena_research import initial_state
        expected['arena']['research'] = initial_state()
        expected['pool'] = migrate_legendary_pool(payload['pool'], _held_counts(payload))
        self.assertEqual({k: v for k, v in current.items() if k != 'rules'},
                         expected)

    def test_pre_pathing_fix_save_missing_battle_history_is_rejected(self):
        payload = self.codec.encode(self.session)
        payload['rules'] = PRE_PATHING_FIX_FINGERPRINT
        downgrade_to_pre_legendary_pool(payload)
        del payload['battle_history']
        with self.assertRaises(ValueError):
            self.codec.decode(payload, self.codec.schema_version)


if __name__ == '__main__':
    unittest.main()
