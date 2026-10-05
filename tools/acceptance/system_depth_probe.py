#!/usr/bin/env python3
"""Inventory and a bounded, predeclared playstyle screen for tactics_v5.

This is an audit, not a balance change or a live acquisition simulation.
Eleven existing authored configurations are kept, including known failures.
Swaps verify one trial and never increase the independent sample count.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, replace
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sim"), str(ROOT / "tools/acceptance"), str(ROOT)]

import abilities
import build_rules
import combo
from data import pokedex
import items
import partners
import profiles
from roster import build_roster, CURATED_FAMILIES
import skills
import synergy
import techniques
from counterplay_probe import (
    battle_for, GUARD_ACTIVE, GUARD_CONFIG, HEALING_NEEDLE_DISRUPT,
    side_fingerprint, team_metrics,
)
from experiment_build_diversity import BUILDS, PIECES
from weather_ability_probe import SUN, RAIN, SUN_CONTROL, RAIN_GARDEN

RULESET = "tactics_v5"
SEED_BASE = 2026100580000
REVERSED_DISRUPT = replace(
    BUILDS[3], key="disrupt_reversed_rows", name="幽影换阵",
    positions=tuple((x, 5-y) for x, y in BUILDS[3].positions),
    plan="只交换原幽影的前后排，保留全部物种、装备、教学及搭档。",
)
# Family labels are authored audit categories, not engine classes.
CONFIGS = (
    (BUILDS[0], "garden", None),
    (BUILDS[1], "battery", None),
    (BUILDS[2], "dive", None),
    (BUILDS[3], "disrupt", None),
    (GUARD_ACTIVE, "anti_dive", GUARD_CONFIG),
    (SUN, "sun", None),
    (SUN_CONTROL, "sun", None),
    (RAIN, "rain", None),
    (RAIN_GARDEN, "rain", None),
    (HEALING_NEEDLE_DISRUPT, "disrupt", None),
    (REVERSED_DISRUPT, "disrupt", None),
)


def dependencies():
    paths = list((ROOT / "sim").glob("*.py")) + list((ROOT / "data").glob("*.json"))
    paths += [Path(__file__).resolve()] + [ROOT / "tools/acceptance" / name for name in
        ("counterplay_probe.py", "weather_ability_probe.py")]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def bank_hashes():
    directory = ROOT / ".build/saves/poketactics"
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.glob("5e9a2d878d07.*")) if p.is_file()}


def inventory():
    roster = [p for group in build_roster().values() for p in group]
    dex = pokedex()
    rows, signatures = [], defaultdict(list)
    role_tags = {
        "double_strike": ["output"], "charge": ["output", "dive"],
        "heavy_blow": ["output", "disrupt"], "volley_shot": ["output", "area"],
        "bulwark": ["defense"], "mend": ["defense", "healing"],
        "splash": ["output", "area"], "blink_strike": ["output", "dive"],
        "slam_heal": ["defense", "healing", "area"],
        "line_push": ["output", "area", "disrupt"],
        "solar_siphon": ["output", "healing"],
        "chain_lightning": ["output", "area"], "energy_drain": ["disrupt"],
        "quake_break": ["defense", "area", "disrupt"],
    }
    for piece in roster:
        skill = skills.skill_of(piece.species_id)
        move = build_rules.resolve_cast(piece, "budget_v1")
        ability = abilities.for_species(piece.species_id, RULESET)
        tags = role_tags[skill["arch"]]
        row = {
            "sid": piece.species_id, "name": piece.name, "tier": piece.tier,
            "types": piece.types, "range": profiles.effective_range(piece),
            "skill": skill, "move": {k: move.get(k) for k in
                ("id", "name", "type", "power", "accuracy", "effect", "damage_stat")},
            "ability": ability, "audit_role_tags": tags,
            "engine_role": (profiles.get(piece.species_id)["role"] if skill["tier"] == "signature"
                            else skills._role_of(dex.species[piece.species_id]["base"],
                                                 profiles.effective_range(piece) > 1)),
            "compatible_teachings": [key for key in techniques.ids_for(RULESET)
                                     if techniques.compatible_species(piece.species_id, key)],
        }
        rows.append(row)
        # Ignore names and stat shapes; this does NOT mean members are identical in battle.
        payload = {k: row["move"][k] for k in ("type", "power", "accuracy", "damage_stat")}
        signature = json.dumps([row["tier"], row["types"], row["range"], skill["arch"],
                                payload, None if ability is None else ability["id"]],
                               sort_keys=True)
        signatures[signature].append(piece.species_id)
    type_counts = Counter(t for p in roster for t in p.types)
    volley_witnesses, shadowed_volleys = {}, {}
    for key in synergy.SYNERGY_TABLE:
        carriers = [p for p in roster if key in p.types]
        if not carriers:
            continue
        # One or two carrier forms suffice for the present single/dual-type pool.
        for a, b in itertools.combinations_with_replacement(carriers, 2):
            comp = [a]*3+[b]*3
            if combo.volley_pick(comp) == key:
                volley_witnesses[key] = [p.species_id for p in comp]
                break
        if key not in volley_witnesses:
            guaranteed = sorted(set.intersection(*(set(p.types) for p in carriers))-{key})
            dominators = [t for t in guaranteed if t < key and
                          max(synergy.SYNERGY_TABLE[t]["tiers"]) <= max(synergy.SYNERGY_TABLE[key]["tiers"])]
            if dominators:
                shadowed_volleys[key] = dominators
    unresolved_volleys = sorted(set(type_counts)-set(volley_witnesses)-set(shadowed_volleys))
    assert not unresolved_volleys, unresolved_volleys
    synergies = []
    for key, spec in synergy.SYNERGY_TABLE.items():
        n = type_counts[key]
        synergies.append({
            "type": key, "theme": spec["theme"], "distinct_forms": n,
            "defined_thresholds": sorted(spec["tiers"]),
            "distinct_form_thresholds": [t for t in sorted(spec["tiers"]) if t <= n],
            "duplicate_allowed_thresholds": sorted(spec["tiers"]) if n else [],
            "effects": spec["tiers"],
        })
    recipes = [{"a": a, "b": b, "result": items.craft_result(a, b, RULESET)}
               for a, b in itertools.combinations_with_replacement(items.COMPONENT_ORDER, 2)]
    tiers = Counter(p.tier for p in roster)
    # Exact direct-template count for six DIFFERENT forms and exactly 15 gold.
    cost_combinations = sum(math.comb(tiers[1], a)*math.comb(tiers[2], b)*math.comb(tiers[3], c)
                            for a in range(7) for b in range(7) for c in range(7)
                            if a+b+c == 6 and a+2*b+3*c == 15)
    return {
        "roster_count": len(roster), "curated_families": len(CURATED_FAMILIES),
        "source_dex_entries": len(dex.species), "source_move_entries": len(dex.moves),
        "tiers": dict(tiers), "range_counts": dict(Counter(r["range"] for r in rows)),
        "signature_forms": sum(r["skill"]["tier"] == "signature" for r in rows),
        "generic_forms": sum(r["skill"]["tier"] == "generic" for r in rows),
        "skill_arch_counts": dict(Counter(r["skill"]["arch"] for r in rows)),
        "role_tag_counts_overlapping": dict(Counter(tag for r in rows for tag in r["audit_role_tags"])),
        "generic_engine_roles": dict(Counter(r["engine_role"] for r in rows if r["skill"]["tier"] == "generic")),
        "distinct_native_move_ids": len({p.move_id for p in roster if p.move_id is not None}),
        "generic_fallback_forms": [p.species_id for p in roster if p.move_id is None],
        "behavior_signatures_without_stat_shapes": len(signatures),
        "same_behavior_signature_groups": [s for s in signatures.values() if len(s) > 1],
        "species_rows": rows,
        "species_abilities": abilities.catalog(RULESET), "partners": partners.catalog(),
        "teachings": techniques.catalog(RULESET),
        "teaching_compatibility_counts": {key: sum(key in r["compatible_teachings"] for r in rows)
                                           for key in techniques.ids_for(RULESET)},
        "components": [{"id": c, "name": items.COMPONENT_NAMES[c]} for c in items.COMPONENT_ORDER],
        "finished_items": items.catalog(RULESET), "recipes": recipes,
        "recipe_result_counts": dict(Counter(r["result"] for r in recipes)),
        "synergies": synergies,
        "defined_synergy_threshold_states": sum(len(s["defined_thresholds"]) for s in synergies),
        "duplicate_reachable_threshold_states": sum(len(s["duplicate_allowed_thresholds"]) for s in synergies),
        "distinct_form_reachable_threshold_states": sum(len(s["distinct_form_thresholds"]) for s in synergies),
        "volley_types_with_duplicates": [s["type"] for s in synergies if s["distinct_forms"]],
        "selected_volley_witnesses": volley_witnesses,
        "guaranteed_shadowed_volley_types": shadowed_volleys,
        "volley_types_with_six_distinct_forms": [s["type"] for s in synergies
                                                if s["distinct_forms"] >= max(s["defined_thresholds"])],
        "raw_six_distinct_compositions": math.comb(len(roster), 6),
        "raw_six_distinct_exact_15_gold_compositions": cost_combinations,
        "limits": ["Role tags are audit labels and overlap, not implemented classes.",
                   "Native move IDs are payloads, not unique skill behavior counts.",
                   "Behavior signatures omit stats; group membership does not imply identical units.",
                   "Synergies currently count duplicate instances; distinct-only counts are a hypothetical comparison.",
                   "Reachable threshold states are counted separately, not simultaneously reachable in one squad.",
                   "Raw composition counts ignore shop, acquisition, positions, equipment and strategic value.",
                   "Natural weather, partner traits and species abilities are separate systems."]}


def wilson(wins, n):
    z = 1.959963984540054
    p = wins/n
    center = (p+z*z/(2*n))/(1+z*z/n)
    radius = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return [center-radius, center+radius]


def validate_builds():
    catalog = items.catalog(RULESET)
    for build, _, tactical in CONFIGS:
        assert len(build.species) == 6 and build.cost == 15
        assert len(build.items) == len(build.learned) == len(build.positions) == 6
        assert len(set(build.positions)) == 6
        assert all(0 <= x < 6 and y in (2, 3) for x, y in build.positions)
        assert sum(item is not None for item in build.items) == 3
        assert all(item is None or item in catalog for item in build.items)
        assert sum(key is not None for key in build.learned) == 1
        assert set(build.species).intersection(partners.family_ids(build.partner))
        for sid, key in zip(build.species, build.learned):
            techniques.validate_learning(sid, key, RULESET)
        if tactical:
            assert build.learned[tactical["guard"]["source"]] == "guard"


def tournament(count):
    validate_builds()
    seeds = range(SEED_BASE, SEED_BASE+count)
    fixtures = [{**asdict(build), "family": family, "tactics": tactical,
                 "cost": build.cost, "names": [PIECES[s].name for s in build.species],
                 "synergies": synergy.compute([PIECES[s] for s in build.species])}
                for build, family, tactical in CONFIGS]
    matches = []
    for (a, fa, ta), (b, fb, tb) in itertools.combinations(CONFIGS, 2):
        trials, failures = [], []
        for seed in seeds:
            battle, result = battle_for(a, b, seed, ta, tb, ruleset=RULESET)
            reverse, swapped = battle_for(a, b, seed, ta, tb, True, ruleset=RULESET)
            symmetric = (side_fingerprint(battle, 0, True) == side_fingerprint(reverse, 1)
                         and side_fingerprint(battle, 1, True) == side_fingerprint(reverse, 0)
                         and result["duration"] == swapped["duration"]
                         and swapped["winner"] == (None if result["winner"] is None else 1-result["winner"]))
            if not symmetric:
                failures.append(seed)
            event_blob = json.dumps(battle.events, ensure_ascii=False, separators=(",", ":"))
            trials.append({"seed": seed, "winner": result["winner"], "duration": result["duration"],
                           "a_metrics": team_metrics(battle, 0), "b_metrics": team_metrics(battle, 1),
                           "event_sha256": hashlib.sha256(event_blob.encode()).hexdigest(),
                           "event_count": len(battle.events), "side_swap_ok": symmetric})
        outcomes = Counter(t["winner"] for t in trials)
        matches.append({"a": a.key, "b": b.key, "family_a": fa, "family_b": fb,
                        "wins": outcomes[0], "losses": outcomes[1], "draws": outcomes[None],
                        "score": (outcomes[0]+.5*outcomes[None])/count,
                        "win_wilson_95": wilson(outcomes[0], count),
                        "loss_wilson_95": wilson(outcomes[1], count),
                        "duration_median": statistics.median(t["duration"] for t in trials),
                        "side_swap_failures": failures, "trials": trials})
        print(f"{a.key} vs {b.key}: {outcomes[0]}/{outcomes[1]}/{outcomes[None]}", flush=True)
    summaries = []
    for build, family, _ in CONFIGS:
        good, bad, uncertain = [], [], []
        for match in matches:
            if build.key not in (match["a"], match["b"]):
                continue
            left = build.key == match["a"]
            opponent = match["b"] if left else match["a"]
            opposing_family = match["family_b"] if left else match["family_a"]
            if opposing_family == family:
                continue
            wins = match["wins"] if left else match["losses"]
            losses = match["losses"] if left else match["wins"]
            if wins/count >= .60 and wilson(wins, count)[0] > .50:
                good.append(opponent)
            elif losses/count >= .60 and wilson(losses, count)[0] > .50:
                bad.append(opponent)
            else:
                uncertain.append(opponent)
        summaries.append({"key": build.key, "family": family, "favorable": good,
                          "unfavorable": bad, "uncertain": uncertain,
                          "has_tradeoff_in_sample": bool(good and bad)})
    all_families = sorted({family for _, family, _ in CONFIGS})
    screened = sorted({s["family"] for s in summaries if s["has_tradeoff_in_sample"]})
    return {"fixtures": fixtures, "matchups": matches, "summaries": summaries,
            "candidate_families": all_families, "screened_families_with_tradeoff": screened,
            "screened_configurations_with_tradeoff": sum(s["has_tradeoff_in_sample"] for s in summaries),
            "seed_range": [SEED_BASE, SEED_BASE+count-1], "independent_seeds_per_matchup": count,
            "matches": len(matches), "battles_including_symmetry_checks": 2*count*len(matches),
            "side_swap_failures": sum(len(m["side_swap_failures"]) for m in matches),
            "predeclared_screen": "Outside own authored family: >=60% wins with Wilson95 lower>50% is favorable; same criterion for losses is unfavorable. At least one of each screens a configuration as having a tradeoff. Draws count as neither win nor loss.",
            "limits": ["Eleven existing authored configurations in seven authored families; not all-roster search.",
                       "Same six population, 15 direct-purchase gold, three ordinary finished items, one teaching and one partner; initial weather clear.",
                       "Uses tactics_v5 and budget_v1; no gameplay values changed.",
                       "Same 100 primary seeds shared across matchups; swapped trials are checks, not extra samples.",
                       "Pointwise Wilson intervals are not adjusted for multiple comparisons; thresholds are exploratory screens, not proof of global balance.",
                       "A whole-config win cannot be attributed to its namesake weather/guard/item without an ablation.",
                       "No recruitment, component availability, progression, live AI, human-duration or physical-device claim."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--battle", action="store_true")
    parser.add_argument("--seeds", type=int, default=100)
    args = parser.parse_args()
    if args.seeds <= 0:
        parser.error("--seeds must be positive")
    before, banks = dependencies(), bank_hashes()
    started = time.perf_counter()
    payload = {"schema": "system-depth-v1", "ruleset": RULESET,
               "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "sources_sha256": before, "inventory": inventory(),
               "battle": tournament(args.seeds) if args.battle else None}
    payload.update(source_stable=before == dependencies(), original_banks_unchanged=banks == bank_hashes(),
                   original_bank_hashes=banks, elapsed_seconds=round(time.perf_counter()-started, 3))
    assert payload["source_stable"] and payload["original_banks_unchanged"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n")
    battle = payload["battle"]
    print(json.dumps({"roster_count": payload["inventory"]["roster_count"],
                      "source_stable": payload["source_stable"],
                      "battles": None if battle is None else battle["battles_including_symmetry_checks"],
                      "screened_families": None if battle is None else battle["screened_families_with_tradeoff"],
                      "elapsed_seconds": payload["elapsed_seconds"]}, ensure_ascii=False, indent=2))
    return bool(battle and battle["side_swap_failures"])


if __name__ == "__main__":
    raise SystemExit(main())
