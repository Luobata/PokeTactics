"""Same-cost team tactics, paired side swaps and controlled loadout ablations.

python3 sim/experiment_build_diversity.py --seeds 120 --output reports/build-diversity-2026-10-05.json
A side swap verifies one trial; it is never counted as an independent sample.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass, replace
import itertools
import json
from pathlib import Path
import random
import statistics
import time
from unittest.mock import patch

import build_rules
from combat import Battle
from roster import build_roster
import skills
import synergy

PIECES = {p.species_id: p for group in build_roster().values() for p in group}


@dataclass(frozen=True)
class Build:
    key: str
    name: str
    species: tuple
    positions: tuple
    items: tuple
    partner: int
    learned: tuple
    plan: str

    @property
    def cost(self):
        return sum(PIECES[s].tier for s in self.species)


BUILDS = (
    Build("garden", "花园续航", (143, 9, 3, 80, 76, 2),
          ((2, 2), (3, 2), (2, 3), (4, 3), (1, 2), (1, 3)),
          ("leftovers", "sash", "focus_lens", None, None, None), 3,
          ("rest", None, None, None, None, None),
          "卡比兽承伤、剩饭/睡觉与妙蛙花治疗；水系持续回复，紧密站位换治疗覆盖，付出群伤暴露。"),
    Build("battery", "电流法阵", (9, 6, 94, 26, 65, 82),
          ((2, 2), (2, 3), (4, 3), (3, 3), (5, 3), (1, 3)),
          ("sash", "focus_lens", None, "swift_feather", None, None), 26,
          ("surf", None, None, None, None, None),
          "水箭龟挡前排，雷丘加速法系第一次施法，喷火龙群伤、耿鬼干扰；后排密集且单坦。"),
    Build("dive", "双翼突进", (130, 68, 143, 67, 22, 65),
          ((1, 2), (2, 2), (3, 2), (4, 2), (0, 2), (4, 3)),
          ("sash", "choice_band", None, "swift_feather", None, None), 143,
          (None, "cut", None, None, None, None),
          "暴鲤龙/豪力/大嘴雀突破两格内可达后排，胡地收割；物理爆发配格斗羁绊，缺少持续远程群伤。"),
    Build("disrupt", "幽影控场", (94, 3, 6, 26, 76, 65),
          ((2, 3), (3, 3), (4, 3), (1, 3), (2, 2), (5, 3)),
          ("swift_feather", None, "focus_lens", None, "sash", None), 6,
          (None, "cut", None, None, None, None),
          "隆隆岩牵制近战，喷火龙首次施法接力，耿鬼压最高能量目标；依赖首次技能，面对快速突进脆弱。"),
)


def rotate(positions):
    return [(5-x, 3-y) for x, y in positions]


def combat_pair(a, b, seed, *, swapped=False, old_rules=False):
    if swapped:
        a, b = b, a
    comp = lambda build: [(PIECES[s], item) if item else PIECES[s]
                           for s, item in zip(build.species, build.items)]
    with ExitStack() as context:
        if old_rules:
            context.enter_context(patch.object(build_rules, "resolve_cast",
                                              lambda piece, mode: skills.resolve_cast(piece)))
            context.enter_context(patch.object(build_rules, "energy_targeting", return_value=False))
            context.enter_context(patch.object(build_rules, "apply_item_rules", return_value=None))
        battle = Battle(comp(a), comp(b), random.Random(seed), stat_mode="budget_v1",
                        positions_a=list(a.positions), positions_b=rotate(b.positions),
                        team_options=tuple({"partner": x.partner} if x.partner else None for x in (a, b)),
                        learned_a=list(a.learned), learned_b=list(b.learned))
        result = battle.run()
    return battle, result


def side_fingerprint(battle, team, rotated=False):
    return [(u.hp, u.energy, (5-u.pos[0], 3-u.pos[1]) if rotated else u.pos,
             u.damage_dealt, u.casts, u.technique_used, u.partner_trait_uses)
            for u in battle.units if u.team == team]


def team_metrics(battle, team):
    units = [u for u in battle.units if u.team == team]
    indices = {u.idx for u in units}
    casts = [event for event in battle.events if event[1] == "cast" and event[2] in indices]
    events = [event for event in battle.events if event[1] == "partner_effect" and event[2] in indices]
    return {"damage": sum(u.damage_dealt for u in units),
            "casts": len(casts),
            "healing": sum(e[3] for e in battle.events if e[1] == "regen" and e[2] in indices),
            "partner_energy": sum(e[6].get("energy", 0) for e in events),
            "technique_uses": sum(u.technique_used for u in units),
            "first_cast": min((e[0] for e in casts), default=None),
            "drained_energy": sum(e[6].get("stolen", 0) for e in battle.events
                                  if e[1] == "skill_effect" and e[2] in indices),
            "survivors": sum(u.alive for u in units)}


def matchup(a, b, seeds, old_rules=False):
    scores, durations, failures, metrics_a, metrics_b = [], [], [], [], []
    outcomes = Counter()
    timeouts = 0
    for seed in seeds:
        first, result = combat_pair(a, b, seed, old_rules=old_rules)
        swap, swapped = combat_pair(a, b, seed, swapped=True, old_rules=old_rules)
        if (side_fingerprint(first, 0, True) != side_fingerprint(swap, 1)
                or side_fingerprint(first, 1, True) != side_fingerprint(swap, 0)
                or result["duration"] != swapped["duration"]
                or swapped["winner"] != (None if result["winner"] is None else 1-result["winner"])):
            failures.append(seed)
        winner = result["winner"]
        outcomes["draw" if winner is None else "a" if winner == 0 else "b"] += 1
        scores.append(.5 if winner is None else int(winner == 0))
        durations.append(result["duration"])
        timeouts += int(all(result["survivors"].values()))
        metrics_a.append(team_metrics(first, 0))
        metrics_b.append(team_metrics(first, 1))
    def averages(rows):
        return {key: round(statistics.mean(row[key] for row in rows if row[key] is not None), 3)
                if any(row[key] is not None for row in rows) else None for key in rows[0]}
    return {"a": a.key, "b": b.key, "trials": len(seeds), "games": 2*len(seeds),
            "a_wins": outcomes["a"], "b_wins": outcomes["b"], "draws": outcomes["draw"],
            "a_score": statistics.mean(scores), "duration_median": round(statistics.median(durations), 2),
            "timeouts": timeouts, "side_swap_failures": failures,
            "metrics_a": averages(metrics_a), "metrics_b": averages(metrics_b)}


def variants(build):
    lens = build.items.index("focus_lens") if "focus_lens" in build.items else None
    frontline_items = list(build.items)
    if lens is not None:
        front = next(i for i, (_, y) in enumerate(build.positions) if y == 2)
        frontline_items[front], frontline_items[lens] = frontline_items[lens], frontline_items[front]
    startup_slots = {"garden": (0, 2, 3), "battery": (1, 2, 4),
                     "dive": (0, 1, 2), "disrupt": (0, 2, 3)}[build.key]
    return {
        "no_items": replace(build, items=(None,)*6),
        "no_technique": replace(build, learned=(None,)*6),
        "no_partner": replace(build, partner=None),
        # Exchange the two friendly rows, preserving columns and uniqueness.
        "reversed_rows": replace(build, positions=tuple((x, 5-y) for x, y in build.positions)),
        "frontline_lens": replace(build, items=tuple(frontline_items)),
        "three_lenses": replace(build, items=tuple("focus_lens" if i in startup_slots else None
                                                  for i in range(6))),
    }


def experiment(seed_count=120, start_seed=10000, include_ablations=True):
    if type(seed_count) is not int or seed_count <= 0:
        raise ValueError("seed_count must be a positive integer")
    started = time.perf_counter()
    seeds = range(start_seed, start_seed + seed_count)
    for build in BUILDS:
        assert len(build.species) == 6 and build.cost == 15
        assert sum(item is not None for item in build.items) == 3
        assert sum(x is not None for x in build.learned) == 1
    baseline = [matchup(a, b, seeds, True) for a, b in itertools.combinations(BUILDS, 2)]
    matrix = [matchup(a, b, seeds) for a, b in itertools.combinations(BUILDS, 2)]
    ablations = []
    if include_ablations:
        for build in BUILDS:
            for opponent in BUILDS:
                if build == opponent:
                    continue
                full = next(row for row in matrix if {row["a"], row["b"]} == {build.key, opponent.key})
                full_score = full["a_score"] if full["a"] == build.key else 1-full["a_score"]
                for key, variant in variants(build).items():
                    row = matchup(variant, opponent, seeds)
                    row.update(variant=key, full_score=full_score,
                               score_delta=full_score-row["a_score"])
                    ablations.append(row)
    summaries = []
    for build in BUILDS:
        scores = {row["b"] if row["a"] == build.key else row["a"]:
                  row["a_score"] if row["a"] == build.key else 1-row["a_score"]
                  for row in matrix if build.key in (row["a"], row["b"])}
        summaries.append({"build": build.key, "scores": scores,
                          "favorable": [key for key, rate in scores.items() if rate >= .55],
                          "unfavorable": [key for key, rate in scores.items() if rate <= .45]})
    # Equal-resource stress: every squad gets six items in both arms. This is
    # outside the three-item primary fixture; never pool these score rates.
    stress = []
    if include_ablations:
        for a, b in itertools.combinations(BUILDS, 2):
            for key in ("focus_lens", "choice_band"):
                row = matchup(replace(a, items=(key,)*6), replace(b, items=(key,)*6), seeds)
                row["equipment"] = key
                stress.append(row)
        for build in BUILDS:
            row = matchup(replace(build, items=("focus_lens",)*6),
                          replace(build, items=("choice_band",)*6), seeds)
            row["equipment"] = "six_lenses_vs_six_bands_same_roster"
            stress.append(row)
    all_rows = baseline + matrix + ablations + stress
    return {"version": 1, "seeds": [start_seed, start_seed+seed_count-1],
            "rules": {"stat_mode": "budget_v1", "team_cost": 15, "population": 6,
                      "finished_items": 3, "learned_techniques": 1, "partners": 1,
                      "gengar_power": build_rules.GENGAR_CAST_POWER,
                      "focus_lens_start_energy": build_rules.FOCUS_LENS_START_ENERGY,
                      "baseline": "same budget_v1 with prior Gengar native payload/locked target and old lens +25% ultimate damage",
                      "default_synergies_status_profiles": True},
            "builds": [{**build.__dict__, "cost": build.cost,
                        "names": [PIECES[s].name for s in build.species],
                        "synergies": synergy.compute([PIECES[s] for s in build.species])} for build in BUILDS],
            "baseline": baseline, "matrix": matrix, "ablations": ablations, "summaries": summaries,
            "equipment_stress": stress,
            "all_have_favorable_and_unfavorable": all(s["favorable"] and s["unfavorable"] for s in summaries),
            "side_swap_failure_count": sum(len(row["side_swap_failures"]) for row in all_rows),
            "games": sum(row["games"] for row in all_rows),
            "elapsed_seconds": round(time.perf_counter()-started, 3),
            "limits": "Fixed hand-built 15-cost teams only; paired swaps are not independent trials. No all-roster balance claim; ablations intentionally remove a paid resource, while row swaps retain all resources."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=120)
    parser.add_argument("--start-seed", type=int, default=10000)
    parser.add_argument("--skip-ablations", action="store_true")
    parser.add_argument("--output", default="reports/build-diversity-2026-10-05.json")
    args = parser.parse_args()
    result = experiment(args.seeds, args.start_seed, not args.skip_ablations)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("summaries", "games", "side_swap_failure_count", "elapsed_seconds")}, ensure_ascii=False, indent=2))
