#!/usr/bin/env python3
"""Eight signatures: reproducible directed first-cast evidence, not a balance claim.

Every enabled/disabled pair starts from the same authored fixture and seed.
Only the hero acts once; prefilled energy, durable targets and an injured nearby
ally make each signature legible without waiting for unrelated combat actions.
Use make_signature_battle + run_fixture to share real sim evidence with previews.
"""
import argparse
import json
import random

import profiles
import status
from combat import Battle
from data import ENERGY_MAX
from roster import build_roster

HEROES = (6, 9, 3, 26, 65, 94, 76, 143)
DEFAULT_SEEDS = (7, 11, 29)


def make_signature_battle(species_id, seed=7, profiles_on=True):
    """Return an unplayed Battle with explicit real-combat initial state.

    The caster is unit 0 and fixture_target_idx identifies its first target.
    Positions are mid-battle training layout, so enemies may occupy either half.
    The profile flag is scoped to Unit construction and restored before return.
    All later effects are resolved by normal Battle._act/_strike code.
    """
    if species_id not in HEROES:
        raise ValueError(f"unknown signature species {species_id}")
    roster = {p.species_id: p for ps in build_roster().values() for p in ps}
    friends = (143,) if species_id == 3 else ()
    enemies = ((9, 9, 9) if species_id == 26 else
               (76, 76, 76) if species_id in (3, 94) else (143, 143, 143))
    prior = profiles.PROFILES_ON
    try:
        profiles.PROFILES_ON = profiles_on
        battle = Battle([roster[s] for s in (species_id, *friends)],
                        [roster[s] for s in enemies], random.Random(seed))
    finally:
        profiles.PROFILES_ON = prior
    # Explicit forward line, two-hop corridor, clustered splash or adjacent quake.
    positions = ([(0, 3), (1, 2), (2, 1), (3, 0)] if species_id == 9 else
                 [(0, 3), (0, 2), (2, 2), (4, 2)] if species_id == 26 else
                 [(2, 3), (3, 3), (2, 2), (4, 0), (5, 1)] if species_id == 3 else
                 [(2, 2), (2, 1), (1, 2), (3, 2)] if species_id in (76, 143) else
                 [(2, 3), (2, 2), (1, 2), (3, 2)])
    for unit, position in zip(battle.units, positions):
        unit.pos = position
        unit.max_hp *= 6
        unit.hp = unit.max_hp
        unit.energy = 0
        unit.next_act = 1e6
    caster = battle.units[0]
    caster.energy, caster.next_act = ENERGY_MAX, .5
    caster.hp = caster.max_hp * 3 // 4
    battle.fixture_target_idx = len(friends) + 1
    target = battle.units[battle.fixture_target_idx]
    caster.target_idx = target.idx
    if species_id == 3:
        patient = battle.units[1]
        patient.hp = patient.max_hp // 4
    if species_id == 94:
        target.energy = 35
    if species_id == 65:
        battle.units[-1].hp //= 2  # A different, wounded enemy exercises retarget + blink.
    # Rebuild initial records after fixture setup; no replay may read terminal HP.
    battle.events = [(0., "deploy", unit.idx, unit.pos) for unit in battle.units]
    for unit in battle.units:
        battle._emit_state(unit, 0.)
    return battle


def run_fixture(battle):
    """Resolve one normal hero action and return the same Battle for rendering."""
    battle.duration = .5
    battle._act(battle.units[0], .5)
    return battle


def summarize(battle, seed, enabled):
    casts = [event for event in battle.events if event[1] == "cast"]
    caster = battle.units[0]
    effects = []
    for index, event in enumerate(battle.events):
        if event[1] != "skill_effect":
            continue
        payload = event[6]
        effects.append({"event_index": index, "target": event[3], "effect": event[5],
                        "payload": payload,
                        "events": battle.events[index + 1:index + 1 + payload["event_count"]]})
    return {"species_id": caster.piece.species_id, "name": caster.piece.name,
            "seed": seed, "profiles_on": enabled, "arch": caster.ult_arch,
            "cast": casts[0] if casts else None,
            "actual_damage": caster.damage_dealt,
            "side_hits": [e for e in battle.events if e[1] == "attack"],
            "moves": [e for e in battle.events if e[1] == "move"],
            "heals": [e for e in battle.events if e[1] == "regen"],
            "statuses": [e for e in battle.events if e[1] == "status"],
            "effects": effects,
            "units": [{"idx": u.idx, "hp": u.hp, "energy": u.energy, "pos": u.pos,
                       "stunned_after_hit": status.stunned(u, .6)} for u in battle.units]}


def run_experiment(seeds=DEFAULT_SEEDS):
    rows = [summarize(run_fixture(make_signature_battle(sid, seed, enabled)), seed, enabled)
            for sid in HEROES for seed in seeds for enabled in (False, True)]
    observed = {sid: sorted({effect["effect"] for row in rows
                            if row["species_id"] == sid and row["profiles_on"]
                            for effect in row["effects"]}) for sid in HEROES}
    expected = {9: {"side_hit", "knockback"}, 3: {"heal"}, 26: {"side_hit"},
                94: {"energy_drain"}, 76: {"side_hit", "flinch"}}
    checks = {"all_enabled_cast": all(row["cast"] is not None for row in rows if row["profiles_on"]),
              "disabled_arches_silent": all(row["arch"] is None and not row["effects"]
                                            for row in rows if not row["profiles_on"]),
              "all_five_mechanics_observed": all(kinds <= set(observed[sid])
                                                 for sid, kinds in expected.items()),
              "all_eight_change_events": all(any(
                  rows[i]["species_id"] == sid and rows[i]["profiles_on"] is False and
                  (rows[i]["cast"], rows[i]["side_hits"], rows[i]["moves"], rows[i]["heals"], rows[i]["effects"]) !=
                  (rows[i + 1]["cast"], rows[i + 1]["side_hits"], rows[i + 1]["moves"], rows[i + 1]["heals"], rows[i + 1]["effects"])
                  for i in range(0, len(rows), 2)) for sid in HEROES)}
    return {"kind": "directed_first_cast", "balance_validated": False,
            "seeds": list(seeds), "checks": checks, "observed_effects": observed, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS)
    args = parser.parse_args()
    result = run_experiment(args.seeds)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(result["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
