"""Partner selection, bounded teamwork, learning and unchanged native skills."""
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
from combat import Battle
from data import ENERGY_MAX
import partners
import skills
import status
import synergy
from roster import build_roster

ROSTER = {p.species_id: p for group in build_roster().values() for p in group}


def fixture(sid, technique=None, allies=(143, 143), enemies=(143, 143)):
    battle = Battle([ROSTER[s] for s in (sid, *allies)],
                    [ROSTER[s] for s in enemies], random.Random(7),
                    team_options=[{"partner": sid, "technique": technique}, None],
                    positions_a=[(2, 2), (1, 2), (3, 2)][:len(allies) + 1],
                    positions_b=[(2, 1), (3, 1)][:len(enemies)])
    for unit in battle.units:
        unit.max_hp = unit.hp = 1000
    return battle


def cast(battle, unit=None):
    unit = unit or battle.units[0]
    target = next(other for other in battle.units if other.team != unit.team)
    unit.energy = ENERGY_MAX
    with patch.dict(battle.dex.moves[unit.piece.move_id], accuracy=100):
        battle._strike(unit, target, .1)


class PartnerContracts(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(status, "STATUS_ON", False))
        self.enterContext(patch.object(synergy, "SYNERGIES_ON", False))

    def test_catalog_and_learning_compatibility_are_fresh_and_strict(self):
        self.assertEqual([row["id"] for row in partners.catalog() if row["starter"]], [3, 6, 9])
        self.assertEqual(partners.family_ids(3), [1, 2, 3])
        self.assertEqual(partners.family_ids(26), [25, 26])
        self.assertTrue(partners.compatible(3, "cut"))
        self.assertTrue(partners.compatible(6, "cut"))
        self.assertTrue(partners.compatible(9, "surf"))
        self.assertTrue(all(partners.compatible(sid, "rest") for sid in (3, 6, 9, 26, 143)))
        for partner, technique in ((9, "cut"), (6, "surf"), (143, "surf"), (True, None), (65, None)):
            with self.subTest(partner=partner, technique=technique):
                self.assertFalse(partners.compatible(partner, technique))
                with self.assertRaises(ValueError):
                    partners.validate_loadout(partner, technique)
        rows = partners.catalog()
        rows[0]["family_ids"].clear()
        rows[0]["techniques"].clear()
        self.assertEqual(partners.catalog()[0]["family_ids"], [1, 2, 3])
        with self.assertRaises(ValueError):
            partners.validate_loadout({"partner": 3, "extra": True})
        for invalid in ({}, {"partner": None}):
            with self.assertRaises(ValueError):
                partners.validate_loadout(invalid)
        for invalid in ([], [None], [6, None], [None, None, None],
                        [{"partner": 9, "technique": "cut"}, None]):
            with self.assertRaises(ValueError):
                Battle([ROSTER[6]], [ROSTER[9]], random.Random(7), team_options=invalid)

    def test_first_deployed_family_member_is_only_partner_and_native_skills_remain(self):
        battle = Battle([ROSTER[s] for s in (4, 6, 6, 9)], [ROSTER[143]], random.Random(3),
                        team_options=[{"partner": 6, "technique": "cut"}, None])
        self.assertEqual([u.partner_id for u in battle.units], [6, None, None, None, None])
        self.assertEqual([u.technique for u in battle.units], ["cut", None, None, None, None])
        for unit in battle.units:
            self.assertEqual(unit.ult_arch, skills.arch_of(unit.piece.species_id))
        for unit in battle.units[1:4]:
            unit.pos = (2, 2)
            battle.units[-1].pos = (2, 1)
            battle.units[-1].hp = battle.units[-1].max_hp = 10000
            cast(battle, unit)
            self.assertTrue(any(e[1:3] == ("cast", unit.idx) for e in battle.events))
            self.assertEqual(unit.partner_trait_uses, 0)

    def test_absent_partner_and_explicit_legacy_are_event_identical_to_default(self):
        comps = ([ROSTER[65], ROSTER[143]], [ROSTER[9], ROSTER[26]])
        ordinary = Battle(*comps, random.Random(22)); ordinary.run()
        missing = Battle(*comps, random.Random(22), stat_mode="legacy",
                         team_options=[{"partner": 6, "technique": "cut"}, None]); missing.run()
        self.assertEqual(ordinary.events, missing.events)

    def test_all_five_traits_have_real_bounded_teammate_effects(self):
        flower = fixture(3)
        flower.units[1].hp = 100
        cast(flower)
        # Native solar healing also exists, so inspect the extra partner packet.
        bloom = [e for e in flower.events if e[1] == "partner_effect" and e[5] == "bloom"]
        self.assertEqual(len(bloom), 1)
        self.assertEqual(bloom[0][6]["amount"], 200)
        cast(flower)
        self.assertEqual(sum(e[1] == "partner_effect" and e[5] == "bloom" for e in flower.events), 1)

        fire = fixture(6)
        cast(fire)
        self.assertEqual([u.energy for u in fire.units[1:3]], [18, 18])
        cast(fire)
        self.assertEqual([u.energy for u in fire.units[1:3]], [18, 18])
        self.assertEqual(fire.units[0].energy, 0)

        water = fixture(9)
        self.assertEqual([u.partner_dr for u in water.units[:3]], [0, .2, .2])
        water.duration = 1.0
        self.assertEqual(water._final_damage(water.units[-1], water.units[1], None, 100), 80)
        water.duration = 6.1
        self.assertEqual(water._final_damage(water.units[-1], water.units[1], None, 100), 100)

        lightning = fixture(26)
        unit, mate_a, mate_b = lightning.units[:3]
        for _ in range(3):
            unit.energy = 0
            lightning._strike(unit, lightning.units[-2], .1)
        self.assertEqual((mate_a.energy, mate_b.energy, unit.partner_trait_uses), (16, 16, 2))

        snorlax = fixture(143)
        unit, mate_a, mate_b = snorlax.units[:3]
        mate_a.hp = mate_b.hp = 100
        snorlax._land_hit(snorlax.units[-1], unit, 501, .1)
        self.assertEqual((mate_a.hp, mate_b.hp), (250, 250))
        snorlax._land_hit(snorlax.units[-1], unit, 10, .2)
        self.assertEqual((mate_a.hp, mate_b.hp, unit.partner_trait_uses), (250, 250, 1))
        for battle in (flower, fire, water, lightning, snorlax):
            changed = {e[3] for e in battle.events if e[1] == "partner_effect"
                       and any(key in e[6] for key in ("amount", "energy"))}
            states = {e[2]: e[3:] for e in battle.events if e[1] == "unit_state"}
            for idx in changed:
                self.assertEqual(states[idx], (battle.units[idx].hp, battle.units[idx].energy))

    def test_no_self_target_or_distant_teamwork_and_no_energy_recursion(self):
        alone = fixture(6, allies=())
        cast(alone)
        self.assertFalse(any(e[1] == "partner_effect" for e in alone.events))
        distant = fixture(26, allies=(143,))
        distant.units[1].pos = (5, 3)
        distant._strike(distant.units[0], distant.units[-2], .1)
        self.assertEqual(distant.units[1].energy, 0)
        # Received relay energy cannot call another relay; only basic actions do.
        pairs = Battle([ROSTER[26], ROSTER[26]], [ROSTER[143]], random.Random(5),
                       team_options=[{"partner": 26}, None],
                       positions_a=[(2, 2), (3, 2)], positions_b=[(2, 1)])
        pairs._strike(pairs.units[0], pairs.units[-1], .1)
        self.assertEqual(sum(e[1] == "partner_effect" for e in pairs.events), 1)

    def test_cut_is_extra_once_and_never_replaces_signature_or_grants_side_energy(self):
        battle = fixture(6, "cut")
        unit, primary, side = battle.units[0], battle.units[-2], battle.units[-1]
        battle._strike(unit, primary, .1)
        cut = next(e for e in battle.events if e[1] == "partner_effect" and e[5] == "cut")
        self.assertEqual(cut[3], side.idx)
        self.assertGreater(cut[6]["damage"], 0)
        self.assertEqual(side.energy, 0)
        before = sum(e[1] == "partner_effect" and e[5] == "cut" for e in battle.events)
        battle._strike(unit, primary, .2)
        self.assertEqual(sum(e[1] == "partner_effect" and e[5] == "cut" for e in battle.events), before)
        cast(battle)
        self.assertEqual(unit.ult_arch, "splash")
        self.assertTrue(any(e[1] == "cast" and e[4] == skills.resolve_cast(unit.piece)["name"]
                            for e in battle.events))

    def test_surf_adds_bounded_damage_and_rest_trades_an_action_for_healing(self):
        water = fixture(9, "surf")
        cast(water)
        wave = [e for e in water.events if e[1] == "partner_effect" and e[5] == "surf"]
        self.assertEqual(len(wave), 1)
        self.assertEqual(wave[0][3], water.units[-1].idx)
        self.assertGreater(wave[0][6]["damage"], 0)
        self.assertEqual(water.units[-1].energy, 0)
        cast(water)
        self.assertEqual(sum(e[1] == "partner_effect" and e[5] == "surf" for e in water.events), 1)
        sleeper = fixture(6, "rest")
        unit = sleeper.units[0]
        unit.hp = 400
        sleeper._act(unit, .1)
        self.assertEqual(unit.hp, 650)
        self.assertFalse(any(e[1] == "attack" and e[2] == unit.idx for e in sleeper.events))
        self.assertAlmostEqual(unit.next_act, .1 + unit.attack_interval)
        unit.hp = 400
        sleeper._act(unit, .2)
        self.assertEqual(unit.hp, 400)

    def test_partner_loadout_rng_is_side_swap_symmetric_in_budget_mode(self):
        # Same composition but different partner/learning: loadout must join RNG key.
        comp = [ROSTER[s] for s in (3, 6, 9, 26, 143)]
        options = [{"partner": 3, "technique": "rest"}, {"partner": 6, "technique": "cut"}]
        for seed in (3, 11, 29, 43):
            first = Battle(comp, comp, random.Random(seed), team_options=options, stat_mode="budget_v1")
            other = Battle(comp, comp, random.Random(seed), team_options=options[::-1], stat_mode="budget_v1")
            first.run(); other.run()
            self.assertEqual(first.duration, other.duration)
            self.assertEqual([(u.hp, u.energy, (5-u.pos[0], 3-u.pos[1]), u.damage_dealt)
                              for u in first.units],
                             [(u.hp, u.energy, u.pos, u.damage_dealt)
                              for u in other.units[5:] + other.units[:5]])


if __name__ == "__main__":
    unittest.main()
