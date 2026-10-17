"""docs/49 补强档（91/93/124/148/198/200/215/227 + 149 传说档）前的存档指纹兼容：
同上限守恒 + 9 只新物种补满 + 伪造持仓拒绝。"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools' / 'acceptance')]
import arena
import demo
from arena_save_expectations import _held_counts
from session_save import PRE_REBALANCE_FINGERPRINT, SessionCodec

NEW_SPECIES = set(arena.REBALANCE_ROSTER) | {149}


def new_session(seed=7):
    session = demo.Session(seed, 'arena_v1')
    session.begin_round(1)
    return session


class ArenaRebalancePoolCompatibility(unittest.TestCase):
    def setUp(self):
        self.codec = SessionCodec()
        self.session = new_session()

    def _pre_rebalance_payload(self):
        """现行格式、53 物种、20/16/10/10/8 上限时代的存档：只差 9 只新物种。"""
        payload = self.codec.encode(self.session)
        payload['rules'] = PRE_REBALANCE_FINGERPRINT
        payload['arena'].pop('research', None)
        for sid in NEW_SPECIES:
            payload['pool'].pop(str(sid), None)
        self.assertEqual(len(payload['pool']), 53)
        return payload

    def test_pre_rebalance_saves_decode_with_warning_and_roundtrip(self):
        payload = self._pre_rebalance_payload()
        restored = self.codec.decode(payload, self.codec.schema_version)
        self.assertEqual(restored.save_warning,
                         '竞技池补强：新增哈克龙、鬼斯通、迷唇姐、刺甲贝、黑暗鸦、梦妖、狃拉、盔甲鸟，'
                         '快龙进入 5 费传说档（同场限一）；阵容、装备、已学技能、海克斯与历史账本已保留，'
                         '新精灵从后续刷新进入，历史战斗结果不会重算。')
        # 缺失的新物种按现行上限补满，且迁移前无人持有。
        held = _held_counts(payload)
        for sid in NEW_SPECIES:
            self.assertEqual(held[sid], 0)
            self.assertEqual(restored.pool.remaining[sid], arena.pool_cap(sid))
        # 既有物种按现行上限守恒（该时代上限未变）。
        for key, count in payload['pool'].items():
            sid = int(key)
            self.assertEqual(restored.pool.remaining[sid] + held[sid], arena.pool_cap(sid))
        # 重编码升级指纹，且在新规则下可无损往返。
        current = self.codec.encode(restored)
        self.assertEqual(current['rules'], self.codec.encode(self.session)['rules'])
        self.assertEqual(self.codec.encode(self.codec.decode(current, 5)), current)

    def test_current_cap_conservation_is_still_enforced(self):
        # 补强时代上限未收紧：账目错误不能被静默吸收。
        payload = self._pre_rebalance_payload()
        sid = next(iter(payload['pool']))
        payload['pool'][sid] += 1
        with self.assertRaises(ValueError):
            self.codec.decode(payload, self.codec.schema_version)

    def test_holding_new_species_without_pool_record_is_rejected(self):
        # 持有补强物种却缺池记录的存档是伪造的。
        payload = self._pre_rebalance_payload()
        board = payload['seats'][1]['board']
        forged = copy.deepcopy(board[0])
        forged['species'] = 91
        forged['sources'] = [91]
        board.append(forged)
        with self.assertRaises(ValueError):
            self.codec.decode(payload, self.codec.schema_version)


if __name__ == '__main__':
    unittest.main()
