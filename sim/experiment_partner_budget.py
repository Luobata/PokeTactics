"""Reproducible budget audit and exploratory mirrored-combat samples.

Run: python3 sim/experiment_partner_budget.py --seeds 120 --output reports/partner-budget-2026-10-05.json
No dependencies, global feature mutations or claims of completed balance tuning.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import random
import statistics
import time

from combat import Battle
from roster import build_roster
import stat_budget


def percentile(values, percentile_value):
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * percentile_value)]


def cross_species_diagnostic(roster, opponent_count=12, seed_count=8):
    """Same-cost native-skill 1v1 samples, paired across modes and board sides.

    Side swaps are reproducibility checks of the same seeded trial, not extra
    independent samples. Every species keeps the same opponent list in both modes.
    """
    if (type(opponent_count) is not int or opponent_count <= 0
            or type(seed_count) is not int or seed_count <= 0):
        raise ValueError("cross-species opponent and seed counts must be positive integers")
    started = time.perf_counter()
    all_rows, failures = [], []
    for mode in ("legacy", "budget_v1"):
        for tier, group in roster.items():
            for piece in group:
                pool = [candidate for candidate in group if candidate.species_id != piece.species_id]
                opponents = random.Random(20261005 + piece.species_id).sample(
                    pool, min(opponent_count, len(pool)))
                wins, losses, draws, timeouts = 0, 0, 0, 0
                durations, matchups = [], []
                for opponent in opponents:
                    opponent_wins, opponent_draws = 0, 0
                    for seed in range(seed_count):
                        first = Battle([piece], [opponent], random.Random(seed), stat_mode=mode)
                        swap = Battle([opponent], [piece], random.Random(seed), stat_mode=mode)
                        a, b = first.run(), swap.run()
                        rotated = [(u.hp, u.energy, (5-u.pos[0], 3-u.pos[1])) for u in first.units]
                        actual = [(u.hp, u.energy, u.pos) for u in swap.units[::-1]]
                        if (rotated != actual or a["duration"] != b["duration"]
                                or b["winner"] != (None if a["winner"] is None else 1-a["winner"])):
                            failures.append({"mode": mode, "species_id": piece.species_id,
                                             "opponent_id": opponent.species_id, "seed": seed})
                        for result, side in ((a, 0), (b, 1)):
                            durations.append(result["duration"])
                            timeouts += int(all(result["survivors"][team] for team in (0, 1)))
                            if result["winner"] is None:
                                draws += 1
                                opponent_draws += 1
                            elif result["winner"] == side:
                                wins += 1
                                opponent_wins += 1
                            else:
                                losses += 1
                    matchups.append({"opponent_id": opponent.species_id, "opponent_name": opponent.name,
                                     "games": seed_count * 2, "wins": opponent_wins, "draws": opponent_draws})
                games = wins + losses + draws
                all_rows.append({"mode": mode, "species_id": piece.species_id, "name": piece.name,
                                 "tier": tier, "games": games, "independent_seeded_trials": games // 2,
                                 "wins": wins, "losses": losses, "draws": draws,
                                 "win_rate": wins / games, "score_rate": (wins + .5 * draws) / games,
                                 "duration_median": round(statistics.median(durations), 2),
                                 "duration_p90": round(percentile(durations, .9), 2),
                                 "timeouts": timeouts, "matchups": matchups})
    summaries = []
    for mode in ("legacy", "budget_v1"):
        for tier in roster:
            rows = sorted((row for row in all_rows if row["mode"] == mode and row["tier"] == tier),
                          key=lambda row: (row["score_rate"], row["species_id"]))
            scores = [row["score_rate"] for row in rows]
            brief = lambda row: {key: row[key] for key in ("species_id", "name", "win_rate", "score_rate")}
            summaries.append({"mode": mode, "tier": tier, "species_count": len(rows),
                              "score_rate_min": min(scores), "score_rate_max": max(scores),
                              "score_rate_spread": max(scores) - min(scores),
                              "score_rate_mean": statistics.mean(scores),
                              "score_rate_stdev": statistics.pstdev(scores),
                              "bottom_five": [brief(row) for row in rows[:5]],
                              "top_five": [brief(row) for row in rows[-5:][::-1]]})
    before = {row["species_id"]: row for row in all_rows if row["mode"] == "legacy"}
    deltas = [{"species_id": row["species_id"], "name": row["name"], "tier": row["tier"],
               "legacy_win_rate": before[row["species_id"]]["win_rate"],
               "budget_win_rate": row["win_rate"],
               "score_rate_change": row["score_rate"] - before[row["species_id"]]["score_rate"]}
              for row in all_rows if row["mode"] == "budget_v1"]
    return {"opponents_per_species": opponent_count, "seeds": [0, seed_count - 1],
            "opponent_selection_seed": "20261005 + species_id; sample without replacement within tier",
            "games": sum(row["games"] for row in all_rows),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "conditions": "1v1 with native skills and normal default combat rules; no items, weather, selected partners or learned techniques. Single-unit synergies (if any) remain active. This does not model a full team's synergies, multi-target skill value or partner cooperation.",
            "sample_limit": "Each side swap repeats the same seeded trial. Each species has only 12 distinct opponents and 96 independent seeded trials per mode at default settings; these are exploratory matchup samples, not proof of equal strength.",
            "side_swap_failure_count": len(failures), "side_swap_failures": failures,
            "tier_summaries": summaries, "species_results": all_rows, "species_changes": deltas}


def run_experiment(seeds=120, cross_opponents=12, cross_seeds=8):
    started = time.perf_counter()
    if type(seeds) is not int or seeds <= 0:
        raise ValueError("seeds must be a positive integer")
    roster = build_roster()
    pieces = {p.species_id: p for group in roster.values() for p in group}
    audit = []
    for tier, group in roster.items():
        for piece in group:
            panel = stat_budget.unit_stats(piece)
            audit.append({"species_id": piece.species_id, "name": piece.name,
                          "tier": tier, "budget": panel["budget"],
                          "points": panel["points"],
                          "error": sum(panel["points"].values()) - panel["budget"]})
    extrema = {}
    for tier in roster:
        rows = [row for row in audit if row["tier"] == tier]
        extrema[tier] = {key: {
            "min": min(row["points"][key] for row in rows),
            "max": max(row["points"][key] for row in rows),
        } for key in stat_budget.STAT_KEYS}

    mirrors = []
    for mode in ("legacy", "budget_v1"):
        for partner, technique in ((3, "cut"), (6, "cut"), (9, "surf"),
                                   (26, "rest"), (143, "rest")):
            ids = [partner, 143, 65, 26, 76, 9]
            comp = [pieces[sid] for sid in ids]
            loadout = {"partner": partner, "technique": technique}
            wins, durations, effects = Counter(), [], Counter()
            for seed in range(seeds):
                battle = Battle(comp, comp, random.Random(seed), stat_mode=mode,
                                team_options=[loadout, loadout])
                result = battle.run()
                wins[str(result["winner"])] += 1
                durations.append(result["duration"])
                effects.update(e[5] for e in battle.events if e[1] == "partner_effect")
            mirrors.append({"mode": mode, "partner": partner, "technique": technique,
                            "species_ids": ids, "seeds": [0, seeds - 1],
                            "games": seeds, "wins": dict(wins),
                            "team0_win_rate": wins["0"] / seeds,
                            "duration_median": round(statistics.median(durations), 2),
                            "duration_p90": round(percentile(durations, .9), 2),
                            "duration_min": round(min(durations), 2),
                            "duration_max": round(max(durations), 2),
                            "effect_packets_per_game": {
                                effect: round(count / seeds, 3) for effect, count in effects.items()}})

    # Different loadouts on otherwise identical squads must be part of the key.
    comp = [pieces[sid] for sid in (3, 6, 9, 26, 143)]
    options = [{"partner": 3, "technique": "rest"}, {"partner": 6, "technique": "cut"}]
    swap_failures = []
    for seed in range(seeds):
        original = Battle(comp, comp, random.Random(seed), team_options=options, stat_mode="budget_v1")
        swapped = Battle(comp, comp, random.Random(seed), team_options=options[::-1], stat_mode="budget_v1")
        a, b = original.run(), swapped.run()
        rotated = [(u.hp, u.energy, (5-u.pos[0], 3-u.pos[1]), u.damage_dealt) for u in original.units]
        actual = [(u.hp, u.energy, u.pos, u.damage_dealt) for u in swapped.units[5:] + swapped.units[:5]]
        if (rotated != actual or a["duration"] != b["duration"]
                or b["winner"] != (None if a["winner"] is None else 1-a["winner"])):
            swap_failures.append(seed)
    cross_species = cross_species_diagnostic(roster, cross_opponents, cross_seeds)
    return {"version": 2, "balance_validated": False,
            "scope": "Exact base-budget conservation and RNG side-swap checks, mirrored pacing samples, and paired same-tier cross-species native-skill 1v1 diagnostics. No completed species or team balance claim.",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "policy": {"budgets": stat_budget.BUDGET_BY_TIER,
                       "axis_bounds": [stat_budget.MIN_SHARE, stat_budget.MAX_SHARE],
                       "hp_points_to_hp": 2,
                       "profile_policy": "budget_v1 ignores hp_mult and atk_interval_mult; keeps range and move_mult. Equipment and team synergies apply after the base budget.",
                       "tier_policy": "Existing tier prices stay unchanged; within a tier BST magnitude gives no extra points."},
            "roster_count": len(audit), "max_absolute_budget_error": max(abs(row["error"]) for row in audit),
            "axis_extrema_by_tier": extrema, "species_audit": audit,
            "mirror_samples": mirrors,
            "cross_species": cross_species,
            "side_swap": {"games": seeds, "failure_count": len(swap_failures), "failed_seeds": swap_failures}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=120)
    parser.add_argument("--cross-opponents", type=int, default=12)
    parser.add_argument("--cross-seeds", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_experiment(args.seeds, args.cross_opponents, args.cross_seeds)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
        print(json.dumps({"output": str(args.output), "roster_count": result["roster_count"],
                          "max_absolute_budget_error": result["max_absolute_budget_error"],
                          "side_swap": result["side_swap"],
                          "elapsed_seconds": result["elapsed_seconds"],
                          "cross_species": {key: result["cross_species"][key] for key in (
                              "games", "elapsed_seconds", "side_swap_failure_count", "tier_summaries")},
                          "balance_validated": False}, ensure_ascii=False, indent=2))
    else:
        print(rendered)
