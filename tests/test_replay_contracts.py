"""Replay must show live sim HP/energy at every completed damage packet."""
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))
sys.path.insert(0, str(ROOT / "tools" / "mockups"))
import status
import render_battle_gif as renderer
from combat import Battle
from roster import build_roster

ROSTER = {p.species_id: p for ps in build_roster().values() for p in ps}


def state(units):
    return {u.idx: (u.hp, u.energy) for u in units}


class ReplayContracts(unittest.TestCase):
    def test_every_hit_matches_live_state_including_combo_cast_and_secondary_hits(self):
        a = [(ROSTER[6], "focus_lens")] * 6
        b = [(ROSTER[9], "leftovers")] * 5 + [(ROSTER[9], "sash")]
        battle = Battle(a, b, random.Random(17), weather_name="sun")
        snapshots = {len(battle.events): state(battle.units)}
        original = battle._land_hit

        def capture(*args, **kwargs):
            original(*args, **kwargs)
            snapshots[len(battle.events)] = state(battle.units)

        battle._land_hit = capture
        with patch.dict(status.DEBUFFS["burn"], chance=1.0):
            battle.run()
        snapshots[len(battle.events)] = state(battle.units)
        animation = renderer.BattleAnimation(a, b, 17, None, None, None, battle=battle)
        kinds = {e[1] for e in battle.events}
        self.assertTrue({"combo", "cast", "attack", "regen", "status", "die"} <= kinds)
        self.assertGreater(len(snapshots), 20)
        for index, event in enumerate(battle.events, 1):
            animation._apply(event)
            if index in snapshots:
                actual = {idx: (u.hp, u.energy) for idx, u in animation.units.items()}
                self.assertEqual(actual, snapshots[index], (index, event))
        animation._reset()
        animation._ensure(battle.duration)
        final = {idx: (u.hp, u.energy) for idx, u in animation.units.items()}
        self.assertEqual(final, state(battle.units))
        animation._ensure(0)
        animation._ensure(battle.duration)
        self.assertEqual({idx: (u.hp, u.energy) for idx, u in animation.units.items()}, final)

    def test_sash_primary_then_lethal_secondary_replays_one_death(self):
        battle = Battle([ROSTER[6]], [(ROSTER[143], "sash")], random.Random(3),
                        positions_a=[(2, 2)], positions_b=[(2, 1)])
        u, target = battle.units
        u.energy, u.ult_arch, target.hp = 80, "double_strike", 1
        battle._emit_state(u, 0)
        battle._emit_state(target, 0)
        with patch.dict(battle.dex.moves[u.piece.move_id], accuracy=100), \
             patch.object(status, "STATUS_ON", False):
            battle._strike(u, target, .1)
        self.assertEqual(sum(e[1] == "sash" for e in battle.events), 1)
        self.assertEqual(sum(e[1] == "die" for e in battle.events), 1)
        animation = renderer.BattleAnimation([], [], 3, None, None, None, battle=battle)
        animation._ensure(.1)
        self.assertEqual({idx: (au.hp, au.energy) for idx, au in animation.units.items()}, state(battle.units))
        self.assertEqual(animation.units[target.idx].die_t, .1)

    def test_dot_lethal_and_healing_have_authoritative_snapshots(self):
        battle = Battle([ROSTER[6]], [ROSTER[143]], random.Random(3))
        unit = battle.units[1]
        unit.hp = 5
        battle._emit_state(unit, 0)
        battle._heal(unit, 2, .1)
        status._apply_debuff(battle, unit, "burn", .2)
        with patch.dict(status.DEBUFFS["burn"], dot=1.0):
            status.tick(battle, 1.2)
        battle._death_check(unit, 1.2)
        animation = renderer.BattleAnimation([], [], 3, None, None, None, battle=battle)
        animation._ensure(.1)
        self.assertEqual(animation.units[unit.idx].hp, 7)
        animation._ensure(1.2)
        self.assertEqual(animation.units[unit.idx].hp, 0)
        self.assertEqual(sum(e[1] == "die" for e in battle.events), 1)

    def test_hud_draws_supplied_match_snapshot(self):
        battle = Battle([ROSTER[6]], [ROSTER[9]], random.Random(7))
        animation = renderer.BattleAnimation([], [], 7, renderer.Front(), renderer.Palettes(),
                                             renderer.Font16(), battle=battle,
                                             hud_snapshot={"hp": 23, "gold": 41, "level": 6, "round": 17})
        with patch.object(renderer, "draw_hud") as hud:
            animation.frame(0)
        self.assertEqual(hud.call_args.kwargs, {"hp": 23, "gold": 41, "level": 6, "rnd": 17, "right": "▶"})


if __name__ == "__main__":
    unittest.main()
