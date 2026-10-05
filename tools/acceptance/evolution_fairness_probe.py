#!/usr/bin/env python3
"""Reproducible evolution-capability fairness audit.

The static phase partitions all 84 shop templates and compares direct endpoint
purchase with the canonical all-from-earliest-form evolution route.  It records
gold, shared-pool copies, held units, sale value, visibility and readable role
changes; it deliberately does not reduce fairness to BST.

The optional battle phase is a bounded endpoint-role control, not an all-roster
balance experiment.  It swaps equal-tier opening-weather anchors in two frozen
15-gold squads and runs every arm against four existing authored squads with
side-swap symmetry checks.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, replace
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import sys
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "sim"), str(ROOT / "tools/acceptance")]

from abilities import for_species  # noqa: E402
from combat import Battle  # noqa: E402
from data import pokedex  # noqa: E402
from experiment_build_diversity import (  # noqa: E402
    BUILDS, Build, PIECES, rotate, side_fingerprint, team_metrics,
)
from items import STONE_TARGETS  # noqa: E402
from session_save import rules_fingerprint  # noqa: E402
from synergy import compute as synergy_compute  # noqa: E402
from shop import (  # noqa: E402
    LEVEL_ODDS, OwnedPiece, SharedPool, TRADE_EVOLUTIONS,
    build_templates, sell_value, try_combine,
)

SCHEMA = "evolution-fairness-v1"
DEFAULT_OUT = ROOT / "reports/evidence/evolution-fairness-2026-10-05"
BATTLE_RULESET = "tactics_v4"
BATTLE_START_SEED = 2026100570000
BATTLE_SEEDS = 100

MIDSTAGE_SIDS = {
    1, 4, 7, 10, 11, 13, 14, 16, 17, 19, 21, 25, 29, 32, 37, 41, 43, 54, 56,
    58, 60, 63, 66, 69, 74, 79, 81, 92, 111, 116, 120, 129, 133, 147,
    2, 5, 8, 30, 33, 44, 61, 64, 67, 70, 75, 93, 148,
}
NATURAL_TERMINAL_SIDS = {95, 123, 131, 143}
BRANCH_UNREACHABLE_SIDS = {135, 136}
# Every evolved leaf that the current deterministic next_evolution/stone route
# can reach.  The two Eevee siblings above are evolved leaves but unreachable.
REACHABLE_TERMINAL_SIDS = {
    3, 6, 9, 12, 15, 18, 20, 22, 26, 31, 34, 38, 42, 45, 55, 57, 59, 62, 65,
    68, 71, 76, 80, 82, 94, 112, 117, 121, 130, 134, 149,
}
TERMINAL_SIDS = REACHABLE_TERMINAL_SIDS | BRANCH_UNREACHABLE_SIDS

SUN_CONTROL = replace(
    BUILDS[3], key="sun_control", name="日照控场",
    species=(38, 3, 6, 26, 76, 65),
    plan="Existing replacement fixture: Ninetales is the evolved opening-sun anchor.",
)
RAIN_GARDEN = replace(
    BUILDS[0], key="rain_garden", name="降雨续航",
    species=(143, 131, 3, 80, 76, 2),
    plan="Existing replacement fixture: Lapras is the natural no-evolution opening-rain anchor.",
)
SUN_NATURAL_ANCHOR = replace(
    SUN_CONTROL, key="sun_anchor_natural_lapras", name="日照骨架·天然雨锚",
    species=(131, 3, 6, 26, 76, 65),
    plan="Equal-tier endpoint control: natural Lapras replaces evolved Ninetales at the same slot.",
)
RAIN_EVOLVED_ANCHOR = replace(
    RAIN_GARDEN, key="rain_anchor_evolved_ninetales", name="降雨骨架·进化晴锚",
    species=(143, 38, 3, 80, 76, 2),
    plan="Equal-tier endpoint control: evolved Ninetales replaces natural Lapras at the same slot.",
)

DEPENDENCIES = (
    "sim/roster.py", "sim/shop.py", "sim/items.py", "sim/bots.py",
    "sim/abilities.py", "sim/tactics.py", "sim/data.py",
    "data/pokemon.json", "data/moves.json",
)


def git_state() -> dict:
    def run(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "status_porcelain": run("status", "--short"),
    }


def dependency_state() -> dict:
    digest = hashlib.sha256()
    rows = {}
    for rel in DEPENDENCIES:
        path = ROOT / rel
        digest.update(rel.encode())
        digest.update(path.read_bytes())
        rows[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"sha256_by_path": rows, "combined_sha256": digest.hexdigest()}


def actual_graph(dex) -> Tuple[Dict[int, set], Dict[int, int]]:
    """Infer parent->children and child->parent from each complete lineage."""
    children: Dict[int, set] = defaultdict(set)
    parents: Dict[int, int] = {}
    for sid, record in dex.species.items():
        lineage = record.get("lineage", [])
        if len(lineage) >= 2:
            parent, child = lineage[1], sid
            children[parent].add(child)
            parents[child] = parent
    return children, parents


def role_fields(sid: int, templates: dict) -> dict:
    piece = templates[sid]
    move = pokedex().moves.get(piece.move_id, {})
    return {
        "tier": piece.tier,
        "types": list(piece.types),
        "range": piece.distance,
        "move_id": piece.move_id,
        "move_type": move.get("type"),
        "move_power": move.get("power"),
        "move_effect": move.get("effect"),
        "ability": (for_species(sid, "tactics_v2") or {}).get("id"),
    }


def changed_role_dimensions(source: int, target: int, templates: dict) -> list:
    a, b = role_fields(source, templates), role_fields(target, templates)
    return sorted(key for key in a if key != "move_id" and a[key] != b[key])


def acquisition_rows(templates: dict) -> List[dict]:
    tier_counts = Counter(p.tier for p in templates.values())
    rows = []
    for sid in sorted(templates):
        tier = templates[sid].tier
        for level in range(1, 8):
            p = LEVEL_ODDS[level][tier - 1] / 100 / tier_counts[tier]
            rows.append({
                "sid": sid,
                "name": templates[sid].name,
                "tier": tier,
                "level": level,
                "slot_probability": round(p, 8),
                "at_least_one_in_four_slots": round(1 - (1-p)**4, 8),
                "expected_slots_for_one": round(1/p, 4) if p else None,
                "expected_slots_for_three": round(3/p, 4) if p else None,
            })
    return rows


def canonical_route(leaf: int, templates: dict) -> Optional[dict]:
    """Build the all-from-earliest-form route used by current combine rules."""
    dex = pokedex()
    _, parents = actual_graph(dex)

    chain = [leaf]
    while chain[-1] in parents and parents[chain[-1]] in templates:
        chain.append(parents[chain[-1]])
    chain.reverse()
    if chain[0] == leaf:
        return None

    invested = templates[chain[0]].tier
    copies = Counter({chain[0]: 1})
    # Sequential minimum: make and keep two completed current forms, then buy
    # three source forms for the third; the largest transient is 5 units.
    peak_units = 1
    normal_combines_seen = 0
    steps = []
    for source, target in zip(chain, chain[1:]):
        source_cost = invested
        source_copies = dict(copies)
        stone = source in TRADE_EVOLUTIONS and STONE_TARGETS.get(source) == target
        if stone:
            need = 1
            invested = source_cost
            copies = Counter({key: n for key, n in copies.items()}) + Counter()
            peak_units = max(peak_units, need)
        else:
            need = 3
            invested = source_cost * 3
            copies = Counter({key: n*3 for key, n in copies.items()})
            normal_combines_seen += 1
            peak_units = max(peak_units, 3 if normal_combines_seen == 1 else 5)
        copies[target] += 1
        steps.append({
            "from_sid": source, "to_sid": target,
            "kind": "evo_stone" if stone else "three_into_one",
            "material_units": need,
            "invested_after": invested,
            "source_pool_before": source_copies,
            "pool_after": dict(copies),
            "role_changes": changed_role_dimensions(source, target, templates),
            "population_before": need,
            "population_after": 1,
            "population_delta": 1-need,
            "isolated_type_counts_before": synergy_compute([templates[source]] * need),
            "isolated_type_counts_after": synergy_compute([templates[target]]),
        })
    return {
        "leaf": leaf,
        "chain": chain,
        "steps": steps,
        "invested": invested,
        "pool_copies": dict(sorted(copies.items())),
        "pool_copy_total": sum(copies.values()),
        # Minimum transient owned-unit count when every legal group is combined
        # as soon as possible. It is not the cumulative purchase count.
        "minimal_sequential_peak_owned_units": peak_units,
        "final_source_units": steps[-1]["material_units"],
        "sale_value": sell_value_for_invested(invested),
    }


def sell_value_for_invested(invested: int) -> int:
    return max(invested - 1, 1)


def endpoint_route_rows(templates: dict) -> List[dict]:
    dex = pokedex()
    rows = []
    for leaf in sorted(TERMINAL_SIDS | NATURAL_TERMINAL_SIDS):
        piece = templates[leaf]
        natural = leaf in NATURAL_TERMINAL_SIDS
        branch = leaf in BRANCH_UNREACHABLE_SIDS
        route = None if natural or branch else canonical_route(leaf, templates)
        root = None if route is None else route["chain"][0]
        row = {
            "sid": leaf,
            "name": piece.name,
            "endpoint_class": ("natural_no_evolution" if natural else
                               "evolved_branch_unreachable" if branch else
                               "evolved_reachable"),
            "tier": piece.tier,
            "bst": dex.bst(leaf),
            "direct_invested": piece.tier,
            "direct_pool_copies": 1,
            "direct_sale_value": sell_value_for_invested(piece.tier),
            "direct_first_shop_level": min(level for level in range(1, 8)
                                           if LEVEL_ODDS[level][piece.tier-1] > 0),
            "route_invested": None if route is None else route["invested"],
            "route_pool_copy_total": None if route is None else route["pool_copy_total"],
            "route_peak_owned_units": None if route is None else route["minimal_sequential_peak_owned_units"],
            "route_final_material_units": None if route is None else route["final_source_units"],
            "route_sale_value": None if route is None else route["sale_value"],
            "route_root_sid": root,
            "route_root_first_shop_level": (None if root is None else
                                            min(level for level in range(1, 8)
                                                if LEVEL_ODDS[level][templates[root].tier-1] > 0)),
            "route_extra_gold_vs_direct": None if route is None else route["invested"] - piece.tier,
            "route_extra_pool_copies_vs_direct": None if route is None else route["pool_copy_total"] - 1,
            "route_chain": None if route is None else route["chain"],
            "route_steps": None if route is None else route["steps"],
        }
        rows.append(row)
    return rows


def static_payload() -> dict:
    dex = pokedex()
    templates = build_templates()
    children, parents = actual_graph(dex)
    pool = set(templates)
    midstage = {sid for sid in pool if dex.next_evolution(sid) is not None}
    terminals = pool - midstage
    natural = {sid for sid in terminals if sid not in parents}
    evolved = terminals - natural
    reachable = set()
    for sid in pool:
        if dex.next_evolution(sid) is None:
            continue
        cursor = sid
        while dex.next_evolution(cursor) is not None:
            cursor = dex.next_evolution(cursor)
        reachable.add(cursor)
    branch = evolved - reachable

    assert len(templates) == 84
    assert Counter(p.tier for p in templates.values()) == {1: 34, 2: 32, 3: 18}
    assert midstage == MIDSTAGE_SIDS, sorted(midstage ^ MIDSTAGE_SIDS)
    assert natural == NATURAL_TERMINAL_SIDS, sorted(natural ^ NATURAL_TERMINAL_SIDS)
    assert branch == BRANCH_UNREACHABLE_SIDS, sorted(branch ^ BRANCH_UNREACHABLE_SIDS)
    assert reachable == REACHABLE_TERMINAL_SIDS, sorted(reachable ^ REACHABLE_TERMINAL_SIDS)
    assert evolved == REACHABLE_TERMINAL_SIDS | BRANCH_UNREACHABLE_SIDS
    assert pool == midstage | evolved | natural
    assert not (midstage & evolved), "midstage/terminal overlap"
    assert not (midstage & natural), "midstage/natural overlap"
    assert not (evolved & natural), "evolved/natural overlap"
    assert len(midstage) == 47 and len(evolved) == 33 and len(natural) == 4

    endpoint_pool = SharedPool(templates)
    unchanged_endpoints = []
    for sid in sorted(terminals):
        before = [(o.piece.species_id, o.invested, list(o.sources)) for o in [
            OwnedPiece(templates[sid], templates[sid].tier) for _ in range(3)]]
        owned = [OwnedPiece(templates[sid], templates[sid].tier) for _ in range(3)]
        logs = try_combine([], owned, endpoint_pool, templates)
        after = [(o.piece.species_id, o.invested, list(o.sources)) for o in owned]
        assert logs == [] and before == after and len(owned) == 3
        unchanged_endpoints.append(sid)

    class_rows = []
    for sid in sorted(templates):
        piece = templates[sid]
        nxt = dex.next_evolution(sid)
        if sid in midstage:
            category = "evolving_midstage"
            subtype = ("trade_stone_only" if sid in TRADE_EVOLUTIONS else
                       "normal_three_into_one")
        elif sid in natural:
            category, subtype = "terminal", "natural_no_evolution"
        elif sid in branch:
            category, subtype = "terminal", "evolved_branch_unreachable"
        else:
            category, subtype = "terminal", "evolved_reachable"
        move = dex.moves.get(piece.move_id, {})
        class_rows.append({
            "sid": sid, "name": piece.name, "tier": piece.tier,
            "bst": dex.bst(sid), "category": category, "subtype": subtype,
            "next_sid": nxt, "parent_sid": parents.get(sid),
            "parent_in_pool": parents.get(sid) in pool,
            "types": list(piece.types), "range": piece.distance,
            "move_id": piece.move_id, "move_name": move.get("name_zh"),
            "move_type": move.get("type"), "move_power": move.get("power"),
            "move_effect": move.get("effect"),
            "entry_ability": (for_species(sid, "tactics_v2") or {}).get("id"),
            "pool_copies": {1: 22, 2: 18, 3: 12}[piece.tier],
        })

    edge_rows = []
    edge_counter = Counter()
    for source in sorted(midstage):
        if source in TRADE_EVOLUTIONS:
            target = STONE_TARGETS[source]
            kind = "evo_stone"
        else:
            target = dex.next_evolution(source)
            kind = "three_into_one"
        changes = changed_role_dimensions(source, target, templates)
        edge_counter.update(changes)
        edge_rows.append({
            "source_sid": source, "source_name": templates[source].name,
            "target_sid": target, "target_name": templates[target].name,
            "kind": kind, "changed_dimensions": changes,
            "changes_tier": "tier" in changes,
            "has_non_tier_role_change": any(key != "tier" for key in changes),
            "population_delta": 0 if kind == "evo_stone" else -2,
        })

    routes = endpoint_route_rows(templates)
    route_examples = [row for row in routes if row["sid"] in {
        38, 131, 18, 143, 65, 123, 135, 136, 3,
    }]
    return {
        "schema": SCHEMA,
        "phase": "static-partition-and-route-accounting",
        "probe_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "git": git_state(),
        "rules_fingerprint": rules_fingerprint(),
        "dependencies": dependency_state(),
        "partition": {
            "total": len(pool),
            "tier_counts": dict(sorted(Counter(p.tier for p in templates.values()).items())),
            "midstage_count": len(midstage),
            "evolved_terminal_count": len(evolved),
            "natural_terminal_count": len(natural),
            "reachable_evolved_terminal_count": len(reachable),
            "branch_unreachable_terminal_count": len(branch),
            "midstage_sids": sorted(midstage),
            "evolved_terminal_sids": sorted(evolved),
            "natural_terminal_sids": sorted(natural),
            "reachable_terminal_sids": sorted(reachable),
            "branch_unreachable_sids": sorted(branch),
            "set_relations_checked": [
                "84 templates exactly partition into midstage/evolved terminal/natural terminal",
                "33 evolved terminals exactly partition into reachable 31 + branch-unreachable 2",
                "all category pairs are disjoint",
                "all inferred evolved-terminal predecessors are present in the 84-form pool",
            ],
            "external_predecessor_sids": sorted(
                sid for sid in evolved if parents.get(sid) not in pool),
        },
        "duplicate_endpoint_check": {
            "method": "Construct three direct copies of every terminal and invoke shop.try_combine.",
            "unchanged_sids": unchanged_endpoints,
            "all_unchanged": len(unchanged_endpoints) == len(terminals) == 37,
            "meaning": "All terminal duplicates remain ordinary units; neither evolved nor natural leaves star up.",
        },
        "route_model": {
            "canonical_route": "all-from-earliest-pool-form; direct endpoint purchase is always listed separately",
            "peak_accounting": "cumulative purchased pool copies are separate from the minimum transient owned-unit count when each group is combined as soon as possible",
            "gold_rule": "Combining/stone evolution adds a target pool copy but no additional gold; invested is the sum of bought materials.",
            "limits": [
                "Canonical route is not the only legal hybrid acquisition strategy.",
                "Draw probabilities are an analytic full-pool/uniform-species model with replacement; they are not live whole-game frequencies.",
                "The model ignores other seats, changing tier availability after a species reaches zero, level timing, refresh spending and bench state.",
                "Static tables do not prove all-roster combat balance.",
            ],
        },
        "evolution_edge_summary": {
            "edges": len(edge_rows),
            "changed_dimension_counts": dict(sorted(edge_counter.items())),
            "edges_with_non_tier_role_change": sum(row["has_non_tier_role_change"] for row in edge_rows),
            "edges_with_only_tier_change": sum(row["changes_tier"] and not row["has_non_tier_role_change"] for row in edge_rows),
            "edges_without_tracked_role_change": sum(not row["changed_dimensions"] for row in edge_rows),
            "normal_edges_population_delta": -2,
            "stone_edges_population_delta": 0,
            "edge_rows": edge_rows,
        },
        "ai_duplicate_policy": {
            "normal_midstage_species": sum(sid in midstage and sid not in TRADE_EVOLUTIONS for sid in pool),
            "trade_stone_midstage_species": sum(sid in TRADE_EVOLUTIONS for sid in pool),
            "terminal_species_without_combine_progress": len(terminals),
            "policy": "Bots protect and score second/third copies for normal evolving forms; trade mids use the stone instead and their third copy is penalized; every terminal is unprotected.",
        },
        "route_examples": route_examples,
        "class_rows": class_rows,
        "acquisition_rows": acquisition_rows(templates),
    }


def write_csv(path: Path, field: str, rows: List[dict]) -> None:
    if not rows:
        return
    fields = sorted({key for row in rows for key in row},
                    key=lambda key: (key not in ("sid", "name", "level", "category", "subtype"), key))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def battle_for(a: Build, b: Build, seed: int, ruleset: str, swapped: bool = False):
    if swapped:
        a, b = b, a
    comp = lambda build: [(PIECES[s], item) if item else PIECES[s]
                          for s, item in zip(build.species, build.items)]
    battle = Battle(
        comp(a), comp(b), random.Random(seed), ruleset=ruleset,
        stat_mode="budget_v1", positions_a=list(a.positions),
        positions_b=rotate(b.positions),
        team_options=[{"partner": x.partner} for x in (a, b)],
        learned_a=list(a.learned), learned_b=list(b.learned),
    )
    return battle, battle.run()


def wilson(successes: int, n: int) -> list:
    if not n:
        return [None, None]
    z, p = 1.96, successes/n
    center = (p + z*z/(2*n)) / (1 + z*z/n)
    half = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return [round(center-half, 4), round(center+half, 4)]


def run_battle_arm(a: Build, b: Build, seeds: range, ruleset: str) -> dict:
    outcomes = Counter()
    failures, durations, metrics, trial_records = [], [], [], []
    for seed in seeds:
        battle, result = battle_for(a, b, seed, ruleset)
        reverse, swapped = battle_for(a, b, seed, ruleset, True)
        expected = None if result["winner"] is None else 1 - result["winner"]
        if (side_fingerprint(battle, 0, True) != side_fingerprint(reverse, 1)
                or side_fingerprint(battle, 1, True) != side_fingerprint(reverse, 0)
                or result["duration"] != swapped["duration"]
                or swapped["winner"] != expected):
            failures.append(seed)
        outcomes["win" if result["winner"] == 0 else
                  "loss" if result["winner"] == 1 else "draw"] += 1
        durations.append(result["duration"])
        metrics.append(team_metrics(battle, 0))
        trial_records.append({
            "seed": seed, "winner": result["winner"],
            "score": 0.5 if result["winner"] is None else float(result["winner"] == 0),
            "duration": result["duration"],
            "swap_winner": swapped["winner"],
        })
    average = lambda rows: {
        key: round(statistics.mean(row[key] for row in rows if row[key] is not None), 4)
        if any(row[key] is not None for row in rows) else None for key in rows[0]
    }
    score = (outcomes["win"] + .5*outcomes["draw"]) / len(seeds)
    return {
        "a": a.key, "b": b.key, "ruleset": ruleset,
        "independent_trials": len(seeds), "games_including_symmetry_swaps": len(seeds)*2,
        "outcomes": dict(outcomes), "score": round(score, 4),
        "win_rate": outcomes["win"]/len(seeds),
        "win_wilson_95": wilson(outcomes["win"], len(seeds)),
        "duration_median": round(statistics.median(durations), 3),
        "a_metrics_mean": average(metrics),
        "side_swap_failures": failures,
        "fixture": {"a": dict(asdict(a), cost=a.cost), "b": dict(asdict(b), cost=b.cost)},
        "trials": trial_records,
    }


def paired_anchor_comparison(arms: list, baseline_key: str, variant_key: str) -> list:
    indexed = {(arm["a"], arm["b"]): arm for arm in arms}
    comparisons = []
    opponents = sorted({arm["b"] for arm in arms if arm["a"] == baseline_key})
    for opponent in opponents:
        base, variant = indexed[(baseline_key, opponent)], indexed[(variant_key, opponent)]
        rows = list(zip(base["trials"], variant["trials"]))
        gains = [off["seed"] for off, on in rows if off["winner"] != 0 and on["winner"] == 0]
        losses = [off["seed"] for off, on in rows if off["winner"] == 0 and on["winner"] != 0]
        n = len(gains) + len(losses)
        tail = sum(math.comb(n, i) for i in range(min(len(gains), len(losses))+1)) / 2**n if n else 1.0
        comparisons.append({
            "baseline": baseline_key, "variant": variant_key, "opponent": opponent,
            "baseline_score": base["score"], "variant_score": variant["score"],
            "score_delta": round(variant["score"] - base["score"], 4),
            "baseline_win_to_variant_loss": losses,
            "baseline_loss_to_variant_win": gains,
            "exact_mcnemar_p_on_win_reversals": round(min(1.0, 2*tail), 6),
        })
    return comparisons


def battle_payload(seeds: int, start_seed: int, ruleset: str) -> dict:
    candidates = (
        ("sun_evolved_anchor", SUN_CONTROL),
        ("sun_natural_anchor", SUN_NATURAL_ANCHOR),
        ("rain_natural_anchor", RAIN_GARDEN),
        ("rain_evolved_anchor", RAIN_EVOLVED_ANCHOR),
    )
    opponents = tuple((build.key, build) for build in BUILDS)
    for _, build in candidates:
        assert build.cost == 15 and len(build.species) == 6
        assert len(set(build.species)) == 6
        assert sum(item is not None for item in build.items) == 3
        assert sum(item is not None for item in build.learned) == 1
    assert SUN_CONTROL.species[0] == 38 and SUN_NATURAL_ANCHOR.species[0] == 131
    assert RAIN_GARDEN.species[1] == 131 and RAIN_EVOLVED_ANCHOR.species[1] == 38
    seed_range = range(start_seed, start_seed + seeds)
    arms = [run_battle_arm(build, opponent, seed_range, ruleset)
            for _, build in candidates for _, opponent in opponents]
    return {
        "schema": SCHEMA,
        "phase": "bounded-endpoint-role-control",
        "probe_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "predeclared": {
            "ruleset": BATTLE_RULESET,
            "start_seed": BATTLE_START_SEED,
            "independent_seeds": BATTLE_SEEDS,
            "candidate_builds": [key for key, _ in candidates],
            "opponents": [key for key, _ in opponents],
            "resources": "six population, 15 unit gold, three items, one teaching, one partner, unchanged positions",
        },
        "actual": {"ruleset": ruleset, "start_seed": start_seed, "seeds": seeds},
        "git": git_state(),
        "rules_fingerprint": rules_fingerprint(),
        "dependencies": dependency_state(),
        "arms": arms,
        "paired_anchor_comparisons": (
            paired_anchor_comparison(arms, "sun_control", "sun_anchor_natural_lapras")
            + paired_anchor_comparison(arms, "rain_garden", "rain_anchor_evolved_ninetales")
        ),
        "side_swap_failure_count": sum(len(arm["side_swap_failures"]) for arm in arms),
        "limits": [
            "This evidence ran under tactics_v4. The tactics_v5 entry is expected to retain these combat/pacing numbers, but that routing/event equivalence is a separate test and is not asserted here.",
            "This is an equal-resource endpoint role comparison, not acquisition timing or full-pool balance.",
            "The side swap is a symmetry check and never an independent trial.",
            "Ninetales/Lapras have different types and native moves; differences cannot be attributed solely to evolution capability.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--battle", action="store_true",
                        help="run the bounded endpoint-role battle control after the static audit")
    parser.add_argument("--battle-seeds", type=int, default=BATTLE_SEEDS)
    parser.add_argument("--battle-start-seed", type=int, default=BATTLE_START_SEED)
    parser.add_argument("--battle-ruleset", default=BATTLE_RULESET)
    args = parser.parse_args()
    if args.battle_seeds < 1:
        parser.error("--battle-seeds must be positive")

    args.output.mkdir(parents=True, exist_ok=True)
    before = {"git": git_state(), "rules_fingerprint": rules_fingerprint(),
              "dependencies": dependency_state()}
    payload = static_payload()
    source_signature_keys = ("rules_fingerprint", "dependencies")
    payload["source_stable_during_static"] = (
        before["git"]["head"] == payload["git"]["head"]
        and all(before[key] == payload[key] for key in source_signature_keys)
    )
    (args.output / "static.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(args.output / "templates.csv", "class_rows", payload["class_rows"])
    write_csv(args.output / "evolution_edges.csv", "edge_rows",
              payload["evolution_edge_summary"]["edge_rows"])
    write_csv(args.output / "acquisition_full_pool.csv", "acquisition_rows",
              payload["acquisition_rows"])
    route_writer_rows = []
    for row in endpoint_route_rows(build_templates()):
        compact = {key: value for key, value in row.items() if key != "route_steps"}
        compact["route_chain"] = ",".join(map(str, row["route_chain"] or []))
        route_writer_rows.append(compact)
    write_csv(args.output / "endpoint_routes.csv", "routes", route_writer_rows)

    summary = {
        "output": str(args.output),
        "partition": payload["partition"],
        "duplicate_endpoint_check": payload["duplicate_endpoint_check"],
        "source_stable_during_static": payload["source_stable_during_static"],
    }
    if args.battle:
        battle = battle_payload(args.battle_seeds, args.battle_start_seed,
                                args.battle_ruleset)
        after = {"git": git_state(), "rules_fingerprint": rules_fingerprint(),
                 "dependencies": dependency_state()}
        battle["source_stable_during_battle"] = (
            before["git"]["head"] == after["git"]["head"]
            and before["rules_fingerprint"] == after["rules_fingerprint"]
            and before["dependencies"] == after["dependencies"]
        )
        (args.output / "battle.json").write_text(
            json.dumps(battle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["battle"] = {
            "arms": len(battle["arms"]),
            "independent_trials_per_arm": args.battle_seeds,
            "side_swap_failure_count": battle["side_swap_failure_count"],
            "source_stable_during_battle": battle["source_stable_during_battle"],
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(not payload["source_stable_during_static"]
               or (args.battle and (summary["battle"]["side_swap_failure_count"]
                                    or not summary["battle"]["source_stable_during_battle"])))


if __name__ == "__main__":
    raise SystemExit(main())
