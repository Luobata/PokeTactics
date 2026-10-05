#!/usr/bin/env python3
"""Acceptance probe for current-mechanism anti-rush counterplay.

Phase I freezes a six-unit, 15-gold squad with three finished items and one
teaching, then separates formation, species, rest, learning, and guard selection.
Exploration and held-out formal seeds are kept apart. A side swap verifies
symmetry and is never an independent trial.

Phase II compares the frozen disrupt build against old focus lens, an equipped
but no-reduction healing needle, and the full healing needle under tactics_v3.
It is run only after the main implementation is confirmed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gc
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time
from typing import Iterable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "reports/evidence/counterplay-2026-10-05"
sys.path[:0] = [str(ROOT / "sim"), str(ROOT / "tools/acceptance"), str(ROOT)]

from combat import Battle  # noqa: E402
import items as items_mod  # noqa: E402
from experiment_build_diversity import BUILDS, PIECES, rotate, side_fingerprint, team_metrics  # noqa: E402

SCHEMA = "counterplay-probe-v2"
PHASE1_RULESET = "tactics_v2"
PHASE2_RULESET = "tactics_v3"
EXPLORE_SEEDS = tuple(range(310200, 310220))
FORMAL_SEEDS = tuple(range(2026100550000, 2026100550099+1))

GARDEN, BATTERY, DIVE, DISRUPT = BUILDS
FORMATION = ((2, 2), (1, 2), (1, 3), (4, 3), (3, 2), (2, 3))
GUARD_CONFIG = {"guard": {"source": 1, "target": 2}}
MIRRORED_DIVE = replace(
    DIVE,
    key="dive_horizontal_mirror",
    positions=tuple((5 - x, y) for x, y in DIVE.positions),
    plan="Original dive resources and units with columns mirrored; symmetry control only.",
)

FORMATION_ONLY = replace(
    GARDEN,
    key="garden_formation_only",
    name="花园换阵",
    positions=FORMATION,
    plan="Original garden species/items/rest/partner with the frozen counterplay formation.",
)
REST_CANDIDATE = replace(
    FORMATION_ONLY,
    key="ghost_rest_line",
    name="幽影休息护阵",
    species=(94, 9, 3, 80, 76, 2),
    learned=(None, "rest", None, None, None, None),
    plan="Gengar replaces Snorlax; Wartortle keeps one teaching as rest in the frozen formation.",
)
GUARD_LEARNED = replace(
    REST_CANDIDATE,
    key="ghost_guard_learned",
    name="幽影护卫学习",
    learned=(None, "guard", None, None, None, None),
    plan="The frozen squad learns guard but does not select it in battle.",
)
GUARD_ACTIVE = replace(
    GUARD_LEARNED,
    key="ghost_guard_active",
    name="幽影护阵",
    plan="Frozen anti-rush candidate: Wartortle guards the adjacent Venusaur after Gengar replaces Snorlax.",
)
PHASE1_ARMS = (
    ("original_garden", GARDEN, None),
    ("formation_only", FORMATION_ONLY, None),
    ("species_rest", REST_CANDIDATE, None),
    ("guard_learned_unselected", GUARD_LEARNED, None),
    ("guard_selected", GUARD_ACTIVE, GUARD_CONFIG),
)
OPPONENTS = (
    ("dive_original", DIVE),
    ("dive_horizontal_mirror", MIRRORED_DIVE),
    ("garden_original", GARDEN),
    ("disrupt_original", DISRUPT),
    ("battery_original", BATTERY),
)
PHASE2_OPPONENTS = (("garden_original", GARDEN), ("dive_original", DIVE), ("battery_original", BATTERY))
HEALING_NEEDLE_DISRUPT = replace(
    DISRUPT,
    key="disrupt_healing_needle",
    name="幽影封疗",
    items=tuple("healing_needle" if i == 2 else item for i, item in enumerate(DISRUPT.items)),
    plan="Original frozen disrupt build with Charizard's focus lens replaced by healing needle.",
)



def git_state() -> dict:
    def run(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    return {
        "head": run("rev-parse", "HEAD"),
        "status_porcelain": run("status", "--short"),
    }


def rules_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted((ROOT / "sim").glob("*.py")) + sorted((ROOT / "data").glob("*.json")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_dict(build) -> dict:
    result = dict(asdict(build))
    result["cost"] = build.cost
    result["unit_names"] = [PIECES[s].name for s in build.species]
    return result


def battle_for(a, b, seed: int, tactics_a=None, tactics_b=None, swapped: bool = False,
               ruleset: str = PHASE1_RULESET, disable_needle: bool = False):
    if swapped:
        a, b = b, a
        tactics_a, tactics_b = tactics_b, tactics_a
    comp = lambda build: [
        (PIECES[s], item) if item else PIECES[s]
        for s, item in zip(build.species, build.items)
    ]
    battle = Battle(
        comp(a), comp(b), random.Random(seed), ruleset=ruleset,
        stat_mode="budget_v1", positions_a=list(a.positions),
        positions_b=rotate(b.positions),
        team_options=[{"partner": x.partner} if x.partner else None for x in (a, b)],
        learned_a=list(a.learned), learned_b=list(b.learned),
        tactics_a=tactics_a, tactics_b=tactics_b,
    )
    if disable_needle:
        with patch.object(Battle, "_apply_healing_needle",
                          lambda self, unit, target, t: None):
            result = battle.run()
    else:
        result = battle.run()
    return battle, result


def result_event_summary(battle) -> dict:
    tactical = [e for e in battle.events if e[1] == "tactical_effect" and e[4] == "guard"]
    rows = []
    for event in tactical:
        payload = event[5]
        index = payload.get("result_event_index")
        result = battle.events[index] if isinstance(index, int) and 0 <= index < len(battle.events) else None
        effective = bool(
            result is not None
            and result[1] in ("cast", "attack")
            and result[3] == payload.get("recipient_idx")
            and payload.get("result_event_count", 0) > 0
        )
        rows.append({
            "time": event[0], "source": event[2], "protected": event[3],
            "result_kind": None if result is None else result[1],
            "result_recipient": None if result is None else result[3],
            "result_event_count": payload.get("result_event_count", 0),
            "effective_primary_redirection": effective,
        })
    return {"events": rows, "triggered": len(rows), "effective": sum(r["effective_primary_redirection"] for r in rows)}


def control_events(battle, team: int) -> dict:
    indices = {u.idx for u in battle.units if u.team == team}
    kinds = Counter(e[4] for e in battle.events if e[1] == "skill_effect" and e[2] in indices)
    tactical = Counter(e[4] for e in battle.events if e[1] == "tactical_effect" and e[2] in indices)
    return {**dict(kinds), **{f"tactical:{k}": v for k, v in tactical.items()}}


def healing_needle_summary(battle) -> dict:
    targets = {u.idx: u for u in battle.units}
    blocked = [e for e in battle.events if e[1] == "tactical_effect" and e[4] == "healing_prevented"]
    blocks = [e for e in battle.events if e[1] == "tactical_effect" and e[4] == "healing_block"]
    by_target = Counter(targets[e[3]].piece.species_id for e in blocked if e[3] in targets)
    return {
        "block_events": len(blocks), "prevented_events": len(blocked),
        "prevented_amount": sum(e[5].get("amount", 0) for e in blocked),
        "blocked_target_species": dict(by_target),
        "events": [{"time": e[0], "source": e[2], "target": e[3], **e[5]} for e in blocked],
    }


def score(result: dict, team: int = 0) -> float:
    winner = result["winner"]
    return 0.5 if winner is None else float(winner == team)


def trial_record(seed: int, battle, result: dict, swapped: dict, build, opponent) -> dict:
    guards = result_event_summary(battle)
    return {
        "seed": seed,
        "winner": result["winner"],
        "score": score(result),
        "duration": result["duration"],
        "swap_winner": swapped["winner"],
        "swap_expected_winner": None if result["winner"] is None else 1 - result["winner"],
        "a_metrics": team_metrics(battle, 0),
        "b_metrics": team_metrics(battle, 1),
        "a_controls": control_events(battle, 0),
        "b_controls": control_events(battle, 1),
        "guard_trigger_count": guards["triggered"],
        "guard_effective_count": guards["effective"],
        "guard_events": guards["events"],
        "healing_needle": healing_needle_summary(battle),
        "fixture": {"a": build.key, "b": opponent.key},
    }


def wilson(successes: int, n: int) -> list[float]:
    if not n:
        return [None, None]
    z, p = 1.96, successes / n
    center = (p + z*z/(2*n)) / (1 + z*z/n)
    half = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return [round(center-half, 4), round(center+half, 4)]


def exact_mcnemar_p(gains: int, losses: int) -> float:
    n = gains + losses
    if n == 0:
        return 1.0
    count = min(gains, losses)
    tail = sum(math.comb(n, i) for i in range(count+1)) / (2**n)
    return round(min(1.0, 2*tail), 6)


def mean_optional(rows: Iterable[float]):
    values = list(rows)
    return round(statistics.mean(values), 4) if values else None


def run_arm(arm_name: str, build, opponent, opponent_name: str, seeds: Iterable[int], tactics=None,
            ruleset: str = PHASE1_RULESET, disable_needle: bool = False):
    seeds = tuple(seeds)
    outcomes, trials, failures = Counter(), [], []
    for seed in seeds:
        battle, result = battle_for(build, opponent, seed, tactics_a=tactics,
                                    ruleset=ruleset, disable_needle=disable_needle)
        reverse, swapped = battle_for(build, opponent, seed, tactics_a=tactics, swapped=True,
                                      ruleset=ruleset, disable_needle=disable_needle)
        if (side_fingerprint(battle, 0, True) != side_fingerprint(reverse, 1)
                or side_fingerprint(battle, 1, True) != side_fingerprint(reverse, 0)
                or result["duration"] != swapped["duration"]
                or swapped["winner"] != (None if result["winner"] is None else 1-result["winner"])):
            failures.append(seed)
        outcomes["win" if result["winner"] == 0 else "loss" if result["winner"] == 1 else "draw"] += 1
        trials.append(trial_record(seed, battle, result, swapped, build, opponent))
        del battle, result, reverse, swapped
        gc.collect()
    score_rate = (outcomes["win"] + 0.5*outcomes["draw"]) / len(seeds)
    return {
        "arm": arm_name, "a": build.key, "b": opponent.key,
        "opponent_label": opponent_name, "ruleset": ruleset,
        "needle_counter_disabled": disable_needle, "tactics_a": tactics,
        "independent_trials": len(seeds),
        "games_including_symmetry_swaps": 2*len(seeds),
        "outcomes": dict(outcomes), "score": round(score_rate, 4),
        "win_rate": outcomes["win"]/len(seeds), "win_wilson_95": wilson(outcomes["win"], len(seeds)),
        "duration_median": round(statistics.median(t["duration"] for t in trials), 3),
        "trigger_trials": sum(t["guard_trigger_count"] > 0 for t in trials),
        "effective_trigger_trials": sum(t["guard_effective_count"] > 0 for t in trials),
        "guard_trigger_events": sum(t["guard_trigger_count"] for t in trials),
        "guard_effective_events": sum(t["guard_effective_count"] for t in trials),
        "healing_prevented_amount": sum(t["healing_needle"]["prevented_amount"] for t in trials),
        "healing_block_trials": sum(t["healing_needle"]["block_events"] > 0 for t in trials),
        "healing_prevented_trials": sum(t["healing_needle"]["prevented_events"] > 0 for t in trials),
        "a_metrics_mean": {
            key: round(statistics.mean(t["a_metrics"][key] for t in trials if t["a_metrics"][key] is not None), 4)
            if any(t["a_metrics"][key] is not None for t in trials) else None
            for key in trials[0]["a_metrics"]
        },
        "side_swap_failures": failures, "trials": trials,
        "fixture": {"a": build_dict(build), "b": build_dict(opponent)},
    }


def paired_comparison(off: dict, on: dict) -> dict:
    rows = list(zip(off["trials"], on["trials"]))
    gains = [f["seed"] for f, n in rows if f["winner"] != 0 and n["winner"] == 0]
    losses = [f["seed"] for f, n in rows if f["winner"] == 0 and n["winner"] != 0]
    deltas = [n["score"] - f["score"] for f, n in rows]
    return {
        "opponent": on["opponent_label"], "off_arm": off["arm"], "on_arm": on["arm"],
        "off_score": off["score"], "on_score": on["score"],
        "paired_score_delta_mean": round(statistics.mean(deltas), 4),
        "win_gains": gains, "win_losses": losses,
        "draw_to_win": [f["seed"] for f, n in rows if f["winner"] is None and n["winner"] == 0],
        "win_to_draw": [f["seed"] for f, n in rows if f["winner"] == 0 and n["winner"] is None],
        "exact_mcnemar_p_on_win_reversals": exact_mcnemar_p(len(gains), len(losses)),
        "on_trigger_trials": on["trigger_trials"], "on_effective_trigger_trials": on["effective_trigger_trials"],
        "off_trigger_trials": off["trigger_trials"], "off_effective_trigger_trials": off["effective_trigger_trials"],
    }


def fixture_invariants() -> dict:
    expected_originals = {
        "garden": (143, 9, 3, 80, 76, 2),
        "battery": (9, 6, 94, 26, 65, 82),
        "dive": (130, 68, 143, 67, 22, 65),
        "disrupt": (94, 3, 6, 26, 76, 65),
    }
    rows = [build_dict(b) for b in (*BUILDS, FORMATION_ONLY, REST_CANDIDATE, GUARD_LEARNED, GUARD_ACTIVE, MIRRORED_DIVE)]
    assert len(BUILDS) == 4
    assert {b.key: b.species for b in BUILDS} == expected_originals
    for build in (GARDEN, FORMATION_ONLY, REST_CANDIDATE, GUARD_LEARNED, GUARD_ACTIVE):
        assert len(build.species) == 6 and len(set(build.species)) == 6
        assert build.cost == 15
        assert sum(item is not None for item in build.items) == 3
        assert sum(x is not None for x in build.learned) == 1
        assert len(build.positions) == 6 and len(set(build.positions)) == 6
        assert all(0 <= x < 6 and 2 <= y <= 3 for x, y in build.positions)
    assert REST_CANDIDATE.learned[1] == "rest"
    assert GUARD_ACTIVE.species == (94, 9, 3, 80, 76, 2)
    assert GUARD_ACTIVE.positions == FORMATION
    assert GUARD_ACTIVE.learned[1] == "guard"
    source_pos, target_pos = GUARD_ACTIVE.positions[1], GUARD_ACTIVE.positions[2]
    assert abs(source_pos[0]-target_pos[0]) + abs(source_pos[1]-target_pos[1]) == 1
    assert GUARD_ACTIVE.partner == 3 and sum(x is not None for x in GUARD_ACTIVE.items) == 3
    return {
        "population": 6, "unit_cost": 15, "finished_items": 3, "teachings": 1,
        "ruleset": PHASE1_RULESET, "stat_mode": "budget_v1",
        "original_build_keys": [b.key for b in BUILDS],
        "candidate": build_dict(GUARD_ACTIVE), "builds": rows,
        "checks": ["original BUILDS preserved", "equal budget/resources", "unique legal positions", "guard adjacency", "one rest or guard teaching"],
    }


def source_state() -> dict:
    return {"git": git_state(), "rules_fingerprint": rules_fingerprint()}


def common_payload(mode: str, started: float, before: dict, after: dict, phase: str = "1-current-mechanism") -> dict:
    stable = before["rules_fingerprint"] == after["rules_fingerprint"] and before["git"]["head"] == after["git"]["head"]
    return {
        "schema": SCHEMA, "mode": mode, "phase": "1-current-mechanism",
        "fixture_invariants": fixture_invariants(), "source_before": before, "source_after": after,
        "source_stable_during_run": stable,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "elapsed_seconds": round(time.perf_counter()-started, 3),
    }


def write_evidence(payload: dict, filename: str) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    script_copy = EVIDENCE / "counterplay_probe.py"
    script_copy.write_bytes(Path(__file__).read_bytes())
    output = EVIDENCE / filename
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps({
        "output": str(output), "schema": payload["schema"], "mode": payload["mode"],
        "games": payload.get("games"), "side_swap_failures": payload.get("side_swap_failure_count"),
        "source_stable_during_run": payload.get("source_stable_during_run"),
    }, ensure_ascii=False))


def phase1_matrix(mode: str, seeds: tuple[int, ...], arms=PHASE1_ARMS, filename: str | None = None):
    started, before = time.perf_counter(), source_state()
    rows = [run_arm(arm, build, opponent, opponent_name, seeds, tactics)
            for arm, build, tactics in arms
            for opponent_name, opponent in OPPONENTS]
    after = source_state()
    payload = common_payload(mode, started, before, after)
    payload.update({
        "seed_range": [seeds[0], seeds[-1]], "independent_trials_per_arm_opponent": len(seeds),
        "arms": rows, "games": sum(r["games_including_symmetry_swaps"] for r in rows),
        "side_swap_failure_count": sum(len(r["side_swap_failures"]) for r in rows),
    })
    payload["limits"] = [
        "Fixed authored squads; no recruitment-economy or all-roster balance claim.",
        "The 20 exploration seeds select nothing post hoc: the candidate was frozen before running.",
        "Side-swaps verify symmetry and never increase independent N.",
        "Guard 'effective' means a redirected primary cast/attack packet was observed; it is not a counterfactual life-saving claim.",
        "A 100-seed interval is a finite-sample frequentist summary, not a live balance guarantee.",
    ]
    if filename:
        write_evidence(payload, filename)
    return payload


def phase1_explore():
    return phase1_matrix("phase1-exploration", EXPLORE_SEEDS, filename="formation-explore.json")


def phase1_recheck(explore: dict):
    active_rows = [run_arm("guard_selected_recheck", GUARD_ACTIVE, opponent, name, EXPLORE_SEEDS, GUARD_CONFIG)
                   for name, opponent in OPPONENTS]
    # Compare only compact outcomes/metrics; event payload objects can reorder no fields in deterministic replay.
    reproduction_failures = []
    for row in active_rows:
        original = next(r for r in explore["arms"] if r["arm"] == "guard_selected" and r["opponent_label"] == row["opponent_label"])
        for left, right in zip(original["trials"], row["trials"]):
            keys = ("winner", "duration", "a_metrics", "b_metrics", "guard_trigger_count", "guard_effective_count")
            if any(left[k] != right[k] for k in keys):
                reproduction_failures.append({"opponent": row["opponent_label"], "seed": left["seed"]})
    started, before = time.perf_counter(), source_state()
    after = source_state()
    payload = common_payload("phase1-recheck", started, before, after)
    payload.update({
        "seed_range": [EXPLORE_SEEDS[0], EXPLORE_SEEDS[-1]],
        "independent_trials_per_arm_opponent": len(EXPLORE_SEEDS), "arms": active_rows,
        "reproduction_failures": reproduction_failures,
        "games": sum(r["games_including_symmetry_swaps"] for r in active_rows),
        "side_swap_failure_count": sum(len(r["side_swap_failures"]) for r in active_rows),
        "limits": ["This reuses exploration seeds solely as a deterministic replay check, not as new evidence."],
    })
    write_evidence(payload, "formation-recheck.json")
    return payload


def phase1_formal():
    started, before = time.perf_counter(), source_state()
    rows = [run_arm(arm, build, opponent, name, FORMAL_SEEDS, tactics)
            for arm, build, tactics in PHASE1_ARMS
            for name, opponent in OPPONENTS]
    after = source_state()
    by_key = {(r["arm"], r["opponent_label"]): r for r in rows}
    comparisons = []
    for name, _ in OPPONENTS:
        disabled = by_key[("guard_learned_unselected", name)]
        active = by_key[("guard_selected", name)]
        rest = by_key[("species_rest", name)]
        original = by_key[("original_garden", name)]
        comparisons.append(paired_comparison(disabled, active))
        comparisons.append({**paired_comparison(rest, active), "contrast": "rest_vs_guard_selected"})
        comparisons.append({**paired_comparison(original, active), "contrast": "original_garden_vs_guard_selected"})
    payload = common_payload("phase1-formal-held-out", started, before, after)
    payload.update({
        "seed_range": [FORMAL_SEEDS[0], FORMAL_SEEDS[-1]],
        "independent_trials_per_arm_opponent": len(FORMAL_SEEDS), "arms": rows,
        "comparisons": comparisons, "games": sum(r["games_including_symmetry_swaps"] for r in rows),
        "side_swap_failure_count": sum(len(r["side_swap_failures"]) for r in rows),
    })
    payload["limits"] = [
        "Held-out formal seeds are independent of the exploration/recheck seeds.",
        "Draws count one half in paired score delta; win gains/losses exclude draw changes.",
        "The exact McNemar p-value conditions on observed win reversals and is exploratory, not a registration protocol.",
        "No recruitment, human-play, or full-run counterplay claim.",
    ]
    write_evidence(payload, "phase1-formal.json")
    return payload


def phase2_fixture_invariants() -> dict:
    spec = items_mod.FINISHED["healing_needle"]
    assert DISRUPT.species[2] == 6 and DISRUPT.items[2] == "focus_lens"
    assert HEALING_NEEDLE_DISRUPT.species == DISRUPT.species
    assert HEALING_NEEDLE_DISRUPT.positions == DISRUPT.positions
    assert HEALING_NEEDLE_DISRUPT.items[2] == "healing_needle"
    assert HEALING_NEEDLE_DISRUPT.items == tuple(
        "healing_needle" if i == 2 else item for i, item in enumerate(DISRUPT.items)
    )
    assert HEALING_NEEDLE_DISRUPT.cost == DISRUPT.cost == 15
    assert sum(x is not None for x in HEALING_NEEDLE_DISRUPT.learned) == 1
    assert spec["pairs"] == (("band", "charcoal"),)
    assert spec["healing_reduction"] == 0.60 and spec["duration"] == 8.0
    assert "healing_needle" in items_mod.catalog(PHASE2_RULESET)
    assert "healing_needle" not in items_mod.catalog(PHASE1_RULESET)
    assert callable(getattr(Battle, "_apply_healing_needle", None))
    return {
        "ruleset": PHASE2_RULESET, "base_build": build_dict(DISRUPT),
        "needle_build": build_dict(HEALING_NEEDLE_DISRUPT),
        "replaced_slot": 2, "replaced_species": PIECES[DISRUPT.species[2]].name,
        "old_item": "focus_lens", "new_item": "healing_needle",
        "item_spec": spec, "legacy_v2_catalog_contains_needle": False,
        "checks": ["same species/positions/teaching/partner", "same 15-cost and three items", "60% for 8 seconds", "band+charcoal recipe", "legacy tactics_v2 excludes item"],
    }


def phase2_run_arm(arm_name: str, build, opponent, opponent_name: str, *, disable_needle=False):
    return run_arm(
        arm_name, build, opponent, opponent_name, FORMAL_SEEDS,
        ruleset=PHASE2_RULESET, disable_needle=disable_needle,
    )


def archive_phase2_exploration() -> list[dict]:
    archived = []
    for pattern in ("seal-explore*.json", "seal-explore*.py"):
        for source in sorted((ROOT/".build").glob(pattern)):
            target = EVIDENCE / f"phase2-archive-{source.name}"
            target.write_bytes(source.read_bytes())
            archived.append({
                "source": str(source), "archived": str(target), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "bytes": source.stat().st_size,
            })
    return archived


def phase2_formal():
    started, before = time.perf_counter(), source_state()
    arms = []
    for name, opponent in PHASE2_OPPONENTS:
        arms.append(phase2_run_arm("old_focus_lens", DISRUPT, opponent, name))
        arms.append(phase2_run_arm("needle_no_reduction", HEALING_NEEDLE_DISRUPT, opponent, name, disable_needle=True))
        arms.append(phase2_run_arm("needle_full_reduction", HEALING_NEEDLE_DISRUPT, opponent, name))
    after = source_state()
    by_key = {(r["arm"], r["opponent_label"]): r for r in arms}
    comparisons = []
    for name, _ in PHASE2_OPPONENTS:
        old = by_key[("old_focus_lens", name)]
        noop = by_key[("needle_no_reduction", name)]
        full = by_key[("needle_full_reduction", name)]
        comparisons.append({**paired_comparison(noop, full), "contrast": "reduction_effect_same_needle"})
        comparisons.append({**paired_comparison(old, noop), "contrast": "lost_lens_startup_same_no_reduction"})
        comparisons.append({**paired_comparison(old, full), "contrast": "total_needle_replacement_vs_old_lens"})
    payload = common_payload("phase2-formal-held-out", started, before, after, "2-healing-needle")
    payload.update({
        "phase2_fixture": phase2_fixture_invariants(),
        "exploration_archive": archive_phase2_exploration(),
        "seed_range": [FORMAL_SEEDS[0], FORMAL_SEEDS[-1]],
        "independent_trials_per_arm_opponent": len(FORMAL_SEEDS), "arms": arms,
        "comparisons": comparisons, "games": sum(r["games_including_symmetry_swaps"] for r in arms),
        "side_swap_failure_count": sum(len(r["side_swap_failures"]) for r in arms),
    })
    payload["limits"] = [
        "The no-reduction arm changes behavior through a test patch of _apply_healing_needle; it is an ablation, not a producible item.",
        "Both needle arms lose focus lens's 40 starting energy under budget_v1; full-vs-no-reduction isolates healing denial.",
        "Actual healing lost counts only healing_prevented amounts bounded by real missing HP; requested overheal is excluded.",
        "These fixed squads do not estimate item acquisition frequency, bot crafting choices, or full-run win rates.",
        "Counter usefulness is judged by paired outcomes and mechanisms; it need not exceed 55% win rate against every opponent.",
    ]
    for row in arms:
        if row["arm"] == "needle_no_reduction":
            assert row["healing_block_trials"] == 0 and row["healing_prevented_trials"] == 0
        if row["arm"] == "old_focus_lens":
            assert row["healing_block_trials"] == 0 and row["healing_prevented_trials"] == 0
        if row["arm"] == "needle_full_reduction":
            assert all(t["healing_needle"]["block_events"] <= 1 for t in row["trials"])
    write_evidence(payload, "phase2-formal.json")
    return payload


def run_all_phase1():
    explore = phase1_explore()
    recheck = phase1_recheck(explore)
    formal = phase1_formal()
    failures = (explore["side_swap_failure_count"] + recheck["side_swap_failure_count"]
                + formal["side_swap_failure_count"] + len(recheck["reproduction_failures"]))
    unstable = not all((explore["source_stable_during_run"], recheck["source_stable_during_run"], formal["source_stable_during_run"]))
    return failures > 0 or unstable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("all-phase1", "explore", "recheck", "formal", "phase2"))
    args = parser.parse_args()
    if args.command == "all-phase1":
        return int(run_all_phase1())
    if args.command == "explore":
        payload = phase1_explore()
        return int(payload["side_swap_failure_count"] > 0 or not payload["source_stable_during_run"])
    if args.command == "recheck":
        explore = phase1_matrix("phase1-exploration", EXPLORE_SEEDS)
        payload = phase1_recheck(explore)
        return int(payload["side_swap_failure_count"] > 0 or payload["reproduction_failures"] or not payload["source_stable_during_run"])
    if args.command == "phase2":
        payload = phase2_formal()
        return int(payload["side_swap_failure_count"] > 0 or not payload["source_stable_during_run"])
    payload = phase1_formal()
    return int(payload["side_swap_failure_count"] > 0 or not payload["source_stable_during_run"])


if __name__ == "__main__":
    raise SystemExit(main())
