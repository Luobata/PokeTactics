"""Round/weather and experiment isolation contracts; standard library only."""

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))
import combat
import data
import experiment_matchbalance as balance
import experiment_pacing as pacing
import match
import profiles
from shop import OwnedPiece


class MatchWeatherContracts(unittest.TestCase):
    def setUp(self):
        self.match = match.Match(7401)
        for index, bot in enumerate(self.match.bots):
            bot.alive = index < 3
            bot.board = [OwnedPiece(self.match.templates[9], 3)] if bot.alive else []

    @staticmethod
    def battle_result():
        return {"winner": 0, "survivors": [1, 0], "units": []}

    def test_regular_and_ghost_pvp_share_round_weather(self):
        with patch.object(match, "Battle") as battle:
            battle.return_value.run.side_effect = self.battle_result
            events = self.match._pvp_round(11)
        self.assertEqual(len(events), 3)
        self.assertEqual(battle.call_count, 2)  # 一场普通、一场幽灵
        self.assertEqual([call.kwargs["weather_name"] for call in battle.call_args_list],
                         ["rain", "rain"])

    def test_every_pve_wave_receives_its_scheduled_weather(self):
        for round_no, weather in ((5, None), (10, "sun"), (15, "rain"),
                                  (20, "sand"), (25, "hail"), (30, "sun")):
            with self.subTest(round=round_no), patch.object(match, "Battle") as battle:
                battle.return_value.run.side_effect = self.battle_result
                self.match._pve_round(round_no)
                self.assertEqual(battle.call_count, 3)
                self.assertEqual([call.kwargs["weather_name"]
                                  for call in battle.call_args_list], [weather] * 3)


class ExperimentIsolationContracts(unittest.TestCase):
    def setUp(self):
        self.before = balance.runtime_snapshot()
        self.addCleanup(balance.restore_runtime, self.before)

    @staticmethod
    def match_fingerprint():
        game = match.Match(7421, max_rounds=7)
        result = game.run()
        return (tuple(b.seat for b in result["ranking"]),
                tuple((b.hp, b.gold, b.level, b.xp,
                       tuple(o.piece.species_id for o in b.board),
                       tuple(b.shop.slots)) for b in game.bots))

    def test_current_balance_restores_all_fields_after_each_predecessor(self):
        balance.set_arm(balance.V4)
        expected = balance.runtime_snapshot()
        fingerprint = self.match_fingerprint()
        for previous in (balance.V1, dict(balance.V1, saver_late_cap=30,
                                         follow_lag=1, shop_slots=4, bench=6)):
            with self.subTest(previous=previous):
                balance.set_arm(previous)
                pacing.set_arm("E0")
                balance.set_arm(balance.V4)
                self.assertEqual(balance.runtime_snapshot(), expected)
                self.assertEqual(self.match_fingerprint(), fingerprint)
        self.assertEqual(combat.ENERGY_PER_ATTACK, data.ENERGY_PER_ATTACK)
        self.assertEqual(combat.ATTACK_INTERVAL_MULT, data.ATTACK_INTERVAL_MULT)
        self.assertEqual(balance.V4["saver_late_cap"], self.before["saver_late_cap"])

    def test_pacing_arms_are_order_independent_in_state_and_behavior(self):
        forward = {}
        for arm in pacing.ARM_CONFIGS:
            pacing.set_arm(arm)
            forward[arm] = (pacing.runtime_snapshot(), pacing.metrics(3, 7400, 3))
        for arm in reversed(pacing.ARM_CONFIGS):
            pacing.set_arm(arm)
            self.assertEqual((pacing.runtime_snapshot(), pacing.metrics(3, 7400, 3)),
                             forward[arm], arm)

    def test_historical_energy_is_not_derived_from_live_energy(self):
        pacing.set_arm("CURRENT")
        self.assertEqual(combat.ENERGY_PER_ATTACK, data.ENERGY_PER_ATTACK)
        self.assertEqual(combat.ATTACK_INTERVAL_MULT, data.ATTACK_INTERVAL_MULT)
        for arm in ("A0", "A1", "A2", "M0"):
            pacing.set_arm(arm)
            self.assertEqual(combat.ENERGY_PER_ATTACK, 15, arm)
        pacing.set_arm("E0")
        self.assertEqual(combat.ENERGY_PER_ATTACK, 12)
        self.assertEqual(combat.ENERGY_PER_HIT_TAKEN, 8)

    def test_importing_pacing_has_no_gameplay_side_effect(self):
        code = ("import sys; sys.path.insert(0, 'sim'); "
                "import combat, profiles; "
                "before=(combat.ATTACK_INTERVAL_MULT, combat.ENERGY_PER_ATTACK, "
                "profiles.PROFILES_ON); import experiment_pacing; "
                "assert before==(combat.ATTACK_INTERVAL_MULT, combat.ENERGY_PER_ATTACK, "
                "profiles.PROFILES_ON)")
        subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True,
                       capture_output=True, text=True)

    def test_pacing_main_restores_state_on_failure(self):
        pacing.set_arm("A2")
        before = pacing.runtime_snapshot()
        with patch.object(sys, "argv", ["experiment_pacing", "--games", "1", "--pairs", "1"]), \
                patch.object(pacing, "metrics", side_effect=RuntimeError("injected")), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                pacing.main()
        self.assertEqual(pacing.runtime_snapshot(), before)

    def test_balance_main_restores_state_on_failure(self):
        before = balance.runtime_snapshot()
        with patch.object(sys, "argv", ["experiment_matchbalance", "--games", "1"]), \
                patch.object(balance, "run_arm", side_effect=RuntimeError("injected")), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                balance.main()
        self.assertEqual(balance.runtime_snapshot(), before)

    def test_balance_health_failure_returns_nonzero_and_restores_state(self):
        before = balance.runtime_snapshot()

        def failed_run(_args):
            balance.set_arm(balance.V1)
            return 1

        with patch.object(sys, "argv", ["experiment_matchbalance", "--games", "1"]), \
                patch.object(balance, "run_experiment", side_effect=failed_run):
            with self.assertRaises(SystemExit) as failure:
                balance.main()
        self.assertEqual(failure.exception.code, 1)
        self.assertEqual(balance.runtime_snapshot(), before)


if __name__ == "__main__":
    unittest.main()
