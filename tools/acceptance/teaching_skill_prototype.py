#!/usr/bin/env python3
"""Isolated teaching experiments; never registered in the game or save codec.

The design table is the eligibility authority. Two finite effects run on real
Battle actions, after the native result packet. Off arms reserve the same slot.
No production classes, rules, inventories, save banks or RNGs are patched.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sim"), str(ROOT / "tools/acceptance"), str(ROOT)]
from combat import Battle
from experiment_build_diversity import BUILDS, PIECES, rotate, side_fingerprint, team_metrics
from counterplay_probe import MIRRORED_DIVE

COUNTER = "guardian_riposte"
TEMPO = "tempo_break"
SEED_BASE = 2026100590000
DESIGN_PATH = ROOT / "docs/design/teaching-skills-v1.json"


@lru_cache(maxsize=1)
def design():
    value = json.loads(DESIGN_PATH.read_text())
    machines = {row["id"]: row for row in value["machines"]}
    forms = {row["species_id"]: row for row in value["forms"]}
    if {row["id"] for row in value["machines"] if row["status"] == "first_batch"} != {COUNTER, TEMPO}:
        raise ValueError("prototype and first-batch design do not agree")
    return machines, forms


class PrototypeBattle(Battle):
    """Reference experiment with a separate, nonpersistent learning overlay."""

    def __init__(self, comp_a, comp_b, rng, *, experimental_a=None,
                 experimental_b=None, effects_enabled=True, **kwargs):
        if type(effects_enabled) is not bool:
            raise ValueError("effects_enabled must be a boolean")
        self.effects_enabled = effects_enabled
        self._reaction_queue = []
        self._acting = None
        self._delays = {}
        machines, forms = design()
        assignments = []
        for team, comp, extra in ((0, comp_a, experimental_a), (1, comp_b, experimental_b)):
            if extra is None:
                extra = [None] * len(comp)
            if not isinstance(extra, list) or len(extra) != len(comp):
                raise ValueError("experimental teaching must match deployed units")
            learned = kwargs.get("learned_a" if team == 0 else "learned_b") or [None] * len(comp)
            if len(learned) != len(comp):
                raise ValueError("native teaching list length mismatch")
            for index, (entry, key, old) in enumerate(zip(comp, extra, learned)):
                piece = entry[0] if isinstance(entry, tuple) else entry
                if key is None:
                    continue
                if key not in (COUNTER, TEMPO) or key not in forms[piece.species_id]["machines"]:
                    raise ValueError("form cannot learn this experimental machine")
                if old is not None:
                    raise ValueError("one teaching slot cannot hold two machines")
                assignments.append((team, index, key))
        super().__init__(comp_a, comp_b, rng, **kwargs)
        self.prototype_teaching = {}
        for team, local_index, key in assignments:
            unit = next(u for u in self.units if u.team == team and u.local_idx == local_index)
            self.prototype_teaching[unit.idx] = key
        self.parameters = {key: dict(machines[key]["candidate_parameters"]) for key in (COUNTER, TEMPO)}

    def _land_hit(self, attacker, target, damage, t, move=None, primary=False, cast=False,
                  *, direct=True, basic_enhancement=None):
        index, hp = len(self.events), target.hp
        adjacent = abs(attacker.pos[0] - target.pos[0]) + abs(attacker.pos[1] - target.pos[1]) == 1
        actual_hp = super()._land_hit(attacker, target, damage, t, move=move,
                                     primary=primary, cast=cast, direct=direct,
                                     basic_enhancement=basic_enhancement)
        lost = actual_hp if self._arena_on else max(0, max(0, hp) - max(0, target.hp))
        if not self.effects_enabled or not primary or not lost or not attacker.alive or not target.alive:
            return actual_hp
        if adjacent and self.prototype_teaching.get(target.idx) == COUNTER and not target.technique_used:
            self._reaction_queue.append((COUNTER, target, attacker, index, t))
        if cast and self.prototype_teaching.get(attacker.idx) == TEMPO and not attacker.technique_used:
            self._reaction_queue.append((TEMPO, attacker, target, index, t))
        return actual_hp

    def _strike(self, u, target, t):
        previous, self._reaction_queue = self._reaction_queue, []
        try:
            super()._strike(u, target, t)
            queue = self._reaction_queue
            self._reaction_queue = []
            # Counter before tempo is an explicit experiment ordering. Neither
            # reacts to a derived hit; the native result packet is already done.
            for key, source, patient, owner, time in queue:
                if source.technique_used or not source.alive or not patient.alive:
                    continue
                source.technique_used = True
                payload = {"cause_index": owner, "source_idx": source.idx,
                           "target_idx": patient.idx, "source_pos": source.pos,
                           "target_pos": patient.pos, "uses_per_battle": 1}
                marker = len(self.events)
                self.events.append((time, "teaching_effect", source.idx, patient.idx, key, payload))
                if key == COUNTER:
                    old = patient.pos
                    cell = self._knock_cell(patient, source.pos)
                    if cell is not None:
                        patient.pos = cell
                        self.events.append((time, "move", patient.idx, cell))
                    delay = self.parameters[key]["delay_seconds"]
                    payload.update(pushed=cell is not None, from_pos=old, to_pos=patient.pos,
                                   delay_seconds=delay)
                    if self._acting == patient.idx:
                        self._delays.setdefault(patient.idx, []).append(payload)
                    else:
                        payload["next_act_before"] = max(time, patient.next_act)
                        patient.next_act = payload["next_act_before"] + delay
                        payload["next_act_after"] = patient.next_act
                    self._emit_state(patient, time)
                    self._emit_state(source, time)
                else:
                    before = patient.energy
                    loss = min(before, self.parameters[key]["energy_loss"])
                    patient.energy -= loss
                    payload.update(actual_loss=loss, energy_before=before,
                                   energy_after=patient.energy, returned_energy=0)
                    self._emit_state(patient, time)
                payload["cause_event_count"] = payload["event_count"] = len(self.events) - marker - 1
        finally:
            self._reaction_queue = previous

    def _act(self, u, t):
        previous, self._acting = self._acting, u.idx
        try:
            super()._act(u, t)
            payloads = self._delays.pop(u.idx, [])
            for payload in payloads:
                payload["next_act_before"] = u.next_act
                u.next_act += payload["delay_seconds"]
                payload["next_act_after"] = u.next_act
        finally:
            self._acting = previous


def effects(battle):
    return [event for event in battle.events if event[1] == "teaching_effect"]


def make_scene(kind, scenario="valid", seed=7):
    """Real action, exaggerated HP/energy only for readable boundary fixtures."""
    key = {"counter": COUNTER, "tempo": TEMPO}.get(kind, kind)
    if key not in (COUNTER, TEMPO):
        raise ValueError("unknown prototype scene")
    if scenario == "full":
        candidate = 0 if key == COUNTER else 1
        return prototype_match(candidate, BUILDS[2], seed, "on")[0]
    if scenario not in ("valid", "blocked", "zero", "invalid", "lethal"):
        raise ValueError("unknown boundary scene")
    if key == COUNTER:
        battle = PrototypeBattle([PIECES[68]], [PIECES[143]], random.Random(seed),
                                 positions_a=[(2, 2)], positions_b=[(2, 1)],
                                 experimental_b=[COUNTER], ruleset="tactics_v5", stat_mode="budget_v1")
        actor, patient = battle.units
        actor.pos = (2, 0) if scenario == "blocked" else (2, 1)
        patient.pos = (2, 1) if scenario == "blocked" else (2, 2)
        if scenario == "invalid":
            actor.range, actor.pos = 3, (2, 0)
        actor.energy = 0
    else:
        battle = PrototypeBattle([PIECES[26]], [PIECES[143]], random.Random(seed),
                                 positions_a=[(2, 2)], positions_b=[(2, 1)],
                                 experimental_a=[TEMPO], ruleset="tactics_v5", stat_mode="budget_v1")
        actor, patient = battle.units
        actor.pos, patient.pos = (2, 2), (2, 1)
        actor.energy = 80
        patient.energy = 40 if scenario != "zero" else 0
        if scenario == "invalid":
            # A real accuracy failure, without a stubbed damage/state packet.
            patient.item_dodge = 1.
        elif scenario == "zero":
            # No defender hit-gain in this controlled negative-value scene.
            # This factor is clamped to zero gain by the unchanged base engine.
            patient.synergy_energy = -1.
    for unit in battle.units:
        unit.hp = unit.max_hp = 10000
        unit.target_idx = (patient if unit is actor else actor).idx
        unit.next_act = .1
    if scenario == "lethal":
        patient.hp = 1
    battle.events = [(0., "deploy", u.idx, u.pos) for u in battle.units]
    for unit in battle.units:
        battle._emit_state(unit, 0.)
    battle.duration = .1
    battle._act(actor, .1)
    battle.events.append((2., "end", None))
    return battle


CANDIDATES = (
    (replace(BUILDS[0], key="garden_riposte", learned=(None,) * 6), 0, COUNTER, BUILDS[0]),
    (replace(BUILDS[3], key="disrupt_tempo", learned=(None,) * 6), 3, TEMPO, BUILDS[3]),
)
OPPONENTS = (BUILDS[2], MIRRORED_DIVE, BUILDS[0], BUILDS[1])
ARMS = ("off", "on", "alternative")


def prototype_match(candidate, opponent, seed, arm="on", swapped=False):
    if arm not in ARMS:
        raise ValueError("unknown experiment arm")
    build, learner, key, alternative = CANDIDATES[candidate]
    build = alternative if arm == "alternative" else build
    a, b = (opponent, build) if swapped else (build, opponent)
    extra = [None] * 6
    if arm != "alternative":
        extra[learner] = key
    comp = lambda row: [(PIECES[s], item) if item else PIECES[s] for s, item in zip(row.species, row.items)]
    battle = PrototypeBattle(comp(a), comp(b), random.Random(seed),
                             ruleset="tactics_v5", stat_mode="budget_v1", weather_name=None,
                             positions_a=list(a.positions), positions_b=rotate(b.positions),
                             team_options=[{"partner": x.partner} for x in (a, b)],
                             learned_a=list(a.learned), learned_b=list(b.learned),
                             experimental_a=None if swapped else extra,
                             experimental_b=extra if swapped else None,
                             effects_enabled=arm != "off")
    return battle, battle.run()


def hashes():
    paths = sorted((ROOT / "sim").glob("*.py")) + sorted((ROOT / "data").glob("*.json"))
    paths += [DESIGN_PATH, Path(__file__), ROOT / "tools/acceptance/counterplay_probe.py"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def banks():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / ".build/saves/poketactics").glob("5e9a2d878d07.*"))}


def event_hash(battle):
    return hashlib.sha256(json.dumps(battle.events, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def exact_paired(left, right):
    positive = sum(a > b for a, b in zip(left, right))
    negative = sum(a < b for a, b in zip(left, right))
    m = positive + negative
    p = min(1., 2 * sum(math.comb(m, k) for k in range(min(positive, negative) + 1)) / 2**m) if m else 1.
    return {"positive": positive, "negative": negative, "net": positive - negative, "mcnemar_two_sided_p": p}


def league(seeds=100):
    if type(seeds) is not int or not 1 <= seeds <= 100:
        raise ValueError("prototype seed count must be 1..100")
    before, bank_before = hashes(), banks()
    rows, swaps, replays, identity_controls = [], [], [], 0
    for candidate in range(2):
        for opponent in OPPONENTS:
            by_arm = {}
            for arm in ARMS:
                records = []
                for seed in range(SEED_BASE, SEED_BASE + seeds):
                    battle, result = prototype_match(candidate, opponent, seed, arm)
                    swap, reverse = prototype_match(candidate, opponent, seed, arm, True)
                    same_input = arm == "alternative" and CANDIDATES[candidate][3] == opponent
                    if same_input:
                        # Identical teams with identical arguments repeat the
                        # same random symmetry breaker. This is identity, not
                        # a requirement that the seeded winner should reverse.
                        identity_controls += 1
                        if event_hash(battle) != event_hash(swap):
                            replays.append([candidate, opponent.key, arm, seed, "self_identity"])
                    elif (side_fingerprint(battle, 0, True) != side_fingerprint(swap, 1)
                          or side_fingerprint(battle, 1, True) != side_fingerprint(swap, 0)
                          or result["duration"] != reverse["duration"]
                          or reverse["winner"] != (None if result["winner"] is None else 1-result["winner"])):
                        swaps.append([candidate, opponent.key, arm, seed])
                    if seed == SEED_BASE:
                        again, identical = prototype_match(candidate, opponent, seed, arm)
                        if event_hash(again) != event_hash(battle) or identical["winner"] != result["winner"]:
                            replays.append([candidate, opponent.key, arm, seed])
                    annotation = effects(battle)
                    records.append({"seed": seed, "winner": result["winner"], "duration": result["duration"],
                                    "survivors": result["survivors"], "event_sha256": event_hash(battle),
                                    "candidate_metrics": team_metrics(battle, 0),
                                    "teaching_uses": len(annotation),
                                    "energy_lost": sum(e[5].get("actual_loss", 0) for e in annotation),
                                    "successful_pushes": sum(e[5].get("pushed", False) for e in annotation),
                                    "delays": sum(e[5].get("delay_seconds", 0) for e in annotation)})
                by_arm[arm] = records
            score = lambda arm: [.5 if r["winner"] is None else int(r["winner"] == 0) for r in by_arm[arm]]
            rows.append({"candidate": CANDIDATES[candidate][0].key, "machine": CANDIDATES[candidate][2],
                         "opponent": opponent.key, "arms": by_arm,
                         "scores": {arm: statistics.mean(score(arm)) for arm in ARMS},
                         "effect_vs_off": exact_paired(score("on"), score("off")),
                         "on_vs_existing_teaching": exact_paired(score("on"), score("alternative"))})
            print(CANDIDATES[candidate][0].key, opponent.key, rows[-1]["scores"], flush=True)
    after, bank_after = hashes(), banks()
    return {"schema": "teaching-isolated-prototype-v1", "production_ruleset": "tactics_v5",
            "status": "experimental_not_registered", "seed_range": [SEED_BASE, SEED_BASE+seeds-1],
            "independent_seeds_per_pair": seeds, "pair_count": 8, "arms_per_pair": 3,
            "battles_including_controls": 8*3*seeds*2, "side_swap_checks": 23*seeds,
            "self_identity_checks": identity_controls, "additional_first_seed_replays": 24,
            "swap_failures": swaps, "replay_failures": replays,
            "sources_sha256": before, "source_stable": before == after,
            "bank_hashes_before": bank_before, "bank_hashes_after": bank_after,
            "original_banks_unchanged": bank_before == bank_after,
            "candidates": [{"build": asdict(b), "learner": i, "machine": key,
                            "existing_alternative": asdict(alt)} for b, i, key, alt in CANDIDATES],
            "opponents": [asdict(o) for o in OPPONENTS], "results": rows,
            "preregistered_screen": "Exploratory only: report paired winner changes and exact McNemar; no corrected multiple-comparison or whole-pool balance claim.",
            "limits": ["100 seeds are reused across matchups; swaps do not enlarge N.",
                       "No production learning/reward/save/UI or acquisition implementation.",
                       "Fixed squads, not a whole-pool search; candidate parameters are unbalanced."]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--output", default=".build/teaching-prototype/league.json")
    args = parser.parse_args()
    data = league(args.seeds)
    path = ROOT / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if data["swap_failures"] or data["replay_failures"] or not data["source_stable"] or not data["original_banks_unchanged"]:
        raise SystemExit("prototype invariants failed; raw output retained")


if __name__ == "__main__":
    main()
