#!/usr/bin/env python3
"""Read-only audit for the v1 teaching-machine design contract.

This tool intentionally imports the formal roster only to verify the design JSON
against current tactics_v5 form shape. It never mutates gameplay modules, saves,
or user banks, and does not register the proposal as a ruleset/catalog entry.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sim"))

import techniques  # noqa: E402
from data import pokedex  # noqa: E402
from profiles import effective_range  # noqa: E402
from roster import build_roster  # noqa: E402


DESIGN = ROOT / "docs/design/teaching-skills-v1.json"
PRIMARY = ("breakthrough", "counter", "suppression", "rally")
FROZEN_THRESHOLDS = {
    "frontline_bulk": 220,
    "heavy_bulk": 260,
    "tempo_speed": 70,
    "rare_tempo_speed": 100,
    "finisher_offense": 100,
    "triage": {"bulk_min": 200, "bulk_max": 259, "speed_max": 70},
}
RARE = ("finisher", "standburst", "triage", "tempo")


def fail(errors, message):
    errors.append(message)


def formal_rows(errors):
    rows = {}
    for pieces in build_roster().values():
        for piece in pieces:
            if piece.species_id in rows:
                fail(errors, f"duplicate formal species {piece.species_id}")
            dex = pokedex()
            base = dex.species[piece.species_id]["base"]
            rows[piece.species_id] = {
                "piece": piece,
                "name": piece.name,
                "tier": piece.tier,
                "ranged": effective_range(piece) > 1,
                "bulk": base["hp"] + 2 * base["defense"],
                "max_offense": max(base["attack"], base["special_attack"]),
                "speed": base["speed"],
            }
    return rows


def derived_licenses(row, thresholds):
    if not row["ranged"] and row["bulk"] >= thresholds["frontline_bulk"]:
        primary = "counter"
    elif not row["ranged"]:
        primary = "breakthrough"
    elif row["speed"] >= thresholds["tempo_speed"]:
        primary = "suppression"
    else:
        primary = "rally"
    licenses = {primary}
    if row["max_offense"] >= thresholds["finisher_offense"]:
        licenses.add("finisher")
    if row["bulk"] >= thresholds["heavy_bulk"]:
        licenses.add("standburst")
    triage = thresholds["triage"]
    if triage["bulk_min"] <= row["bulk"] <= triage["bulk_max"] and row["speed"] <= triage["speed_max"]:
        licenses.add("triage")
    if row["speed"] >= thresholds["rare_tempo_speed"]:
        licenses.add("tempo")
    return licenses


def reason_for(row, license_id, rules, thresholds):
    if license_id in derived_licenses(row, thresholds):
        frontline = thresholds["frontline_bulk"]
        tempo_speed = thresholds["tempo_speed"]
        finisher_offense = thresholds["finisher_offense"]
        heavy_bulk = thresholds["heavy_bulk"]
        triage = thresholds["triage"]
        rare_tempo_speed = thresholds["rare_tempo_speed"]
        return {
            "breakthrough": f"近战且体格{row['bulk']}<{frontline}：低体格贴身突破职责",
            "counter": f"近战且体格{row['bulk']}≥{frontline}：高质量受击反击职责",
            "suppression": f"远程且速度{row['speed']}≥{tempo_speed}：远程压启动职责",
            "rally": f"远程且速度{row['speed']}<{tempo_speed}：慢速指挥职责",
            "finisher": f"最高双攻{row['max_offense']}≥{finisher_offense}：稀有终结窗口",
            "standburst": f"体格{row['bulk']}≥{heavy_bulk}：重装阵型爆发",
            "triage": f"体格{row['bulk']}在{triage['bulk_min']}–{triage['bulk_max']}且速度{row['speed']}≤{triage['speed_max']}：稳态救援",
            "tempo": f"速度{row['speed']}≥{rare_tempo_speed}：稀有心律截断",
        }[license_id]
    rule = rules[license_id]
    return f"不具备：{rule}（当前射程{'远程' if row['ranged'] else '近战'}、体格{row['bulk']}、最高双攻{row['max_offense']}、速度{row['speed']}）"


def validate_design(errors):
    text = DESIGN.read_text(encoding="utf-8")
    data = json.loads(text)
    machine_ids = [m["id"] for m in data["machines"]]
    if len(machine_ids) != len(set(machine_ids)):
        fail(errors, "machine ids are not unique")
    if data.get("version") != "teaching-skills-v1":
        fail(errors, "wrong design version")
    if data.get("status") != "proposal_not_gameplay":
        fail(errors, "design status must remain proposal_not_gameplay")
    if data.get("resolution_contract_version") != "teaching-resolution-design-v1":
        fail(errors, "eight-machine deterministic resolution contract is missing")
    shared = data.get("shared_resolution_contract", {})
    if set(shared.get("resolution_order", [])) != set(machine_ids):
        fail(errors, "resolution order must cover each designed machine exactly once")
    if len(shared.get("resolution_order", [])) != len(machine_ids):
        fail(errors, "resolution order repeats a machine")
    if not data.get("invariants", {}).get("canonical_learnsets_used") is False:
        fail(errors, "design must not use canonical learnsets")
    if not data.get("invariants", {}).get("existing_six_teachings_unchanged"):
        fail(errors, "existing teachings must remain unchanged")
    thresholds = data.get("thresholds")
    if thresholds != FROZEN_THRESHOLDS:
        fail(errors, "declared thresholds do not match the frozen teaching-design values")
        thresholds = FROZEN_THRESHOLDS
    if data.get("shape_formulas", {}).get("bulk") != "base.hp + 2 * base.defense":
        fail(errors, "bulk formula must remain base.hp + 2 * base.defense")

    formal = formal_rows(errors)
    if set(formal) != {r["species_id"] for r in data["forms"]}:
        fail(errors, "design form ids do not exactly cover the formal 84-shape roster")
    if len(data["forms"]) != 84:
        fail(errors, f"expected 84 forms, got {len(data['forms'])}")
    if len(data["families"]) != 35:
        fail(errors, f"expected 35 families, got {len(data['families'])}")

    legacy = techniques.catalog("tactics_v5")
    legacy_ids = [r["id"] for r in legacy]
    expected_legacy_ids = ["cut", "surf", "rest", "guard", "sunny_day", "rain_dance"]
    if legacy_ids != expected_legacy_ids:
        fail(errors, "formal six-teaching catalog changed unexpectedly")
    legacy_by_id = {r["id"]: r for r in legacy}

    first_batch = {m["id"]: m for m in data["machines"] if m.get("status") == "first_batch"}
    if set(first_batch) != {"guardian_riposte", "tempo_break"}:
        fail(errors, "first-batch machine set is not guardian_riposte + tempo_break")
    if first_batch.get("guardian_riposte", {}).get("candidate_parameters") != {
            "uses_per_battle": 1, "delay_seconds": 0.3, "push_cells": 1}:
        fail(errors, "guardian_riposte candidate parameters are not frozen")
    if first_batch.get("tempo_break", {}).get("candidate_parameters") != {
            "uses_per_battle": 1, "energy_loss": 20}:
        fail(errors, "tempo_break candidate parameters are not frozen")
    for machine in data["machines"]:
        if not isinstance(machine.get("candidate_parameters"), dict):
            fail(errors, f"{machine['id']} lacks structured candidate_parameters")
        contract = machine.get("resolution_contract", {})
        for key in ("eligibility", "resolution", "resource", "interaction"):
            if not isinstance(contract.get(key), str) or not contract[key].strip():
                fail(errors, f"{machine['id']} lacks {key} resolution design")

    machine_by_license = {m["license"]: m["id"] for m in data["machines"]}
    rules = {r["id"]: r["rule"] for group in ("primary_licenses", "rare_licenses")
             for r in data.get(group, [])}
    if set(machine_by_license) != set(PRIMARY + RARE):
        fail(errors, "machine-to-license mapping does not cover the eight licenses")

    paired = []
    matrix = []
    for declared in data["forms"]:
        sid = declared["species_id"]
        row = formal.get(sid)
        if row is None:
            continue
        expected = derived_licenses(row, thresholds)
        actual = set(declared["licenses"])
        if actual != expected:
            fail(errors, f"{sid} {row['name']} licenses {sorted(actual)} != derived {sorted(expected)}")
        if declared.get("primary_license") not in expected or expected.intersection(PRIMARY) != {declared["primary_license"]}:
            fail(errors, f"{sid} has invalid primary license")
        if declared.get("machines") != [machine_by_license[k] for k in sorted(actual)]:
            fail(errors, f"{sid} machine mapping does not match licenses")
        matrix_row = {
            "species_id": sid,
            "name": row["name"],
            "tier": row["tier"],
            "range": "ranged" if row["ranged"] else "melee",
            "bulk": row["bulk"],
            "max_offense": row["max_offense"],
            "speed": row["speed"],
            "primary": declared["primary_license"],
        }
        for legacy_id in legacy_ids:
            legacy_eligible = techniques.compatible_species(sid, legacy_id)
            matrix_row[legacy_id] = "yes" if legacy_eligible else "no"
            matrix_row[f"reason_{legacy_id}"] = (
                f"现行正式教学兼容规则：{legacy_by_id[legacy_id]['compatibility']}")
        for machine in data["machines"]:
            eligible = machine["license"] in expected
            reason = reason_for(row, machine["license"], rules, thresholds)
            matrix_row[machine["id"]] = "yes" if eligible else "no"
            matrix_row[f"reason_{machine['id']}"] = reason
            paired.append({
                "species_id": sid,
                "name": row["name"],
                "machine": machine["id"],
                "eligible": eligible,
                "reason": reason,
            })
        matrix.append(matrix_row)

    dex = pokedex()
    mismatches = []
    evolution_edges = []
    for declared in data["forms"]:
        sid = declared["species_id"]
        nxt = dex.next_evolution(sid)
        if nxt is None:
            continue
        target = next((r for r in data["forms"] if r["species_id"] == nxt), None)
        if target is None:
            fail(errors, f"missing evolution target {nxt}")
            continue
        edge = {"from_species_id": sid, "from_name": declared["name"],
                "to_species_id": nxt, "to_name": target["name"],
                "inheritable_machines": [], "returned_machines": []}
        for machine in data["machines"]:
            if machine["id"] in declared["machines"]:
                inherited = machine["id"] in target["machines"]
                edge["inheritable_machines" if inherited else "returned_machines"].append(machine["id"])
                if not inherited:
                    mismatches.append({
                        "from_species_id": sid, "from_name": declared["name"],
                        "to_species_id": nxt, "to_name": target["name"],
                        "machine": machine["id"], "policy": "preview_then_return_on_commit"})
        evolution_edges.append(edge)
    if len(evolution_edges) != 47:
        fail(errors, f"expected 47 evolution edges, got {len(evolution_edges)}")

    expected_family_ids = {min(dex.family_of(sid)) for sid in formal}
    if {r["family_head"] for r in data["families"]} != expected_family_ids:
        fail(errors, "family heads do not match the formal 35 families")
    for family in data["families"]:
        if not family.get("capability_tags") or not family.get("notes"):
            fail(errors, f"family {family['family_head']} lacks capability tags or note")
        expected_members = set(dex.family_of(family["family_head"]))
        if set(family["species_ids"]) != expected_members:
            fail(errors, f"family {family['family_head']} membership mismatch")

    natural_endpoints = [r for r in data["forms"] if dex.next_evolution(r["species_id"]) is None]
    if len(natural_endpoints) != 37:
        fail(errors, f"expected 37 endpoint forms, got {len(natural_endpoints)}")
    if any(not r["licenses"] for r in natural_endpoints):
        fail(errors, "an endpoint form has no teaching license")

    legacy_coverage = {
        key: sum(techniques.compatible_species(sid, key) for sid in formal)
        for key in legacy_ids
    }
    coverage = Counter()
    for row in matrix:
        for machine in data["machines"]:
            if row[machine["id"]] == "yes":
                coverage[machine["id"]] += 1

    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        commit = "unknown"
    summary = {
        "ok": not errors,
        "errors": errors,
        "git_commit": commit,
        "design_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "form_count": len(matrix),
        "family_count": len(data["families"]),
        "evolution_edge_count": len(evolution_edges),
        "endpoint_count": len(natural_endpoints),
        "natural_endpoint_family_count": sum(bool(f["natural_endpoint_family"]) for f in data["families"]),
        "machine_coverage": dict(sorted(coverage.items())),
        "primary_coverage": dict(Counter(r["primary"] for r in matrix)),
        "first_batch_machine_ids": [m["id"] for m in data["machines"] if m.get("status") == "first_batch"],
        "second_batch_machine_ids": [m["id"] for m in data["machines"] if m.get("status") == "second_batch"],
        "formal_six_teachings_unchanged": not errors,
        "legacy_teaching_compatibility_counts": legacy_coverage,
        "learning_matrix_machine_count": len(legacy_ids) + len(data["machines"]),
        "learning_matrix_decision_count": len(matrix) * (len(legacy_ids) + len(data["machines"])),
        "new_machine_pair_count": len(paired),
        "evolution_incompatible_machine_pairs": len(mismatches),
        "all_endpoints_have_primary": all(r["primary_license"] in PRIMARY for r in natural_endpoints),
    }
    return data, summary, matrix, paired, evolution_edges, mismatches


def write_outputs(out, data, summary, matrix, paired, edges, mismatches):
    out.mkdir(parents=True, exist_ok=True)
    with (out / "learning-matrix.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(matrix[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(matrix)
    (out / "pairwise-eligibility.json").write_text(
        json.dumps(paired, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "evolution-inheritance.json").write_text(
        json.dumps(edges, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (out / "evolution-incompatibilities.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=(
            "from_species_id", "from_name", "to_species_id", "to_name", "machine", "policy"),
            lineterminator="\n")
        writer.writeheader()
        writer.writerows(mismatches)
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=".build/teaching-design-v1", help="output directory")
    args = parser.parse_args()
    errors = []
    data, summary, matrix, paired, edges, mismatches = validate_design(errors)
    summary["ok"] = not errors
    out = ROOT / args.output
    write_outputs(out, data, summary, matrix, paired, edges, mismatches)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        print("\n".join(f"ERROR: {e}" for e in errors), file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
