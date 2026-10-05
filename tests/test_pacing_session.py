"""Production pressure routing and restore boundaries; normal PVE rewards remain."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools/acceptance'), str(ROOT/'sim'), str(ROOT)]
import demo
from session_save import SessionCodec
from test_tactical_session import fast_render


class PacingSessionContracts(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        for p in (patch.object(demo, 'SAVE_ROOT', Path(directory.name)), patch.object(demo, 'SESSIONS', {}),
                  patch.object(demo, '_render_battle_frames', side_effect=fast_render)):
            p.start(); self.addCleanup(p.stop)

    def test_production_version_routes_pressure_and_round19_save_stays_on_its_rules(self):
        codec = SessionCodec()
        for version in ('base_v1', 'tactics_v1', 'tactics_v2', 'tactics_v3', 'tactics_v4'):
            session = demo.Session(7, version)
            session.expedition = {'partner': 6, 'technique': None, 'item': None}
            session.begin_round(19)
            payload = codec.encode(session)
            restored = codec.decode(payload, 4)
            self.assertEqual(codec.encode(restored), payload)
            self.assertEqual(restored._loss_damage(19, 1), demo.economy.loss_damage(19, 1))
            self.assertEqual(restored._loss_damage(20, 1),
                             21 if version == 'tactics_v4' else demo.economy.loss_damage(20, 1))
            restored.begin_round(20)
            info = demo.state_json(restored)['pacing']
            if version == 'tactics_v4':
                self.assertTrue(info['active']); self.assertEqual(info['minimum_loss'], 21)
                self.assertIn('野怪奖励照常', info['note'])
                self.assertIn('败方', restored.log[-1] if len(restored.log) == 1 else '\n'.join(restored.log))
            else:
                self.assertIsNone(info)

    def test_same_ai_and_economy_are_identical_before_pressure_start(self):
        first, candidate = (demo.Session(8, version) for version in ('tactics_v3', 'tactics_v4'))
        codec = SessionCodec()
        for session in (first, candidate):
            session.begin_round(1)
        a, b = codec.encode(first), codec.encode(candidate)
        for field in ('ruleset', 'expedition_state'):
            a.pop(field); b.pop(field)
        self.assertEqual(a, b)

    def test_terminal_pve_is_still_pve_and_grants_original_components_and_choices(self):
        session = demo.Session(7, 'tactics_v4')
        session.expedition = {'partner': 6, 'technique': None, 'item': None}
        session.begin_round(30)
        before = sum(seat.inventory.total_components() for seat in session.seats)
        session.end_prep()
        self.assertEqual(sum(seat.item_drops for seat in session.seats), 10)
        # Dead seats return their items during elimination, so use receipt count.
        self.assertEqual(len(session.rewards), 8)
        self.assertTrue(all(reward['round'] == 30 for reward in session.rewards))
        self.assertEqual(before, 0)
        session._close_terminal_rewards()
        if session.phase == 'over':
            self.assertFalse(any(reward['status'] == 'pending' for reward in session.rewards))


if __name__ == '__main__':
    unittest.main()
