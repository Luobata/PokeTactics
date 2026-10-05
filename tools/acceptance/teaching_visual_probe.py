#!/usr/bin/env python3
"""Real-event visual acceptance for the first two teaching machines.

The probe is deliberately isolated from production rendering: it imports the
real PokemonGo renderer read-only, derives every overlay from authoritative
``teaching_effect`` records, and never mutates the prototype battle.  It must
fail if the prototype module is absent; fabricated events are not evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools/mockups"), str(ROOT / "tools/acceptance")]

import render_battle_gif as renderer  # noqa: E402
from tactical_visual_probe import label_font  # noqa: E402

PROTOTYPE = ROOT / "tools/acceptance/teaching_skill_prototype.py"
DESIGN = ROOT / "docs/design/teaching-skills-v1.json"
DEFAULT_OUT = ROOT / "reports/evidence/teaching-visual-2026-10-05"
SCENES = (
    ("counter_valid", "counter", "valid"),
    ("counter_blocked", "counter", "blocked"),
    ("counter_invalid", "counter", "invalid"),
    ("counter_lethal", "counter", "lethal"),
    ("tempo_valid", "tempo", "valid"),
    ("tempo_zero", "tempo", "zero"),
    ("tempo_invalid", "tempo", "invalid"),
    ("tempo_lethal", "tempo", "lethal"),
    ("full_natural", "counter", "full"),
    ("tempo_full_natural", "tempo", "full"),
)
MACHINE_BY_SCENE = {
    "counter_valid": "guardian_riposte",
    "counter_blocked": "guardian_riposte",
    "counter_invalid": "guardian_riposte",
    "counter_lethal": "guardian_riposte",
    "tempo_valid": "tempo_break",
    "tempo_zero": "tempo_break",
    "tempo_invalid": "tempo_break",
    "tempo_lethal": "tempo_break",
    "full_natural": None,
    "tempo_full_natural": None,
}
POSITIVE_DIRECTED_SCENES = {"counter_valid", "counter_blocked", "tempo_valid", "tempo_zero"}
PAPER, INK, MUTED = "#f3f0e7", "#24332f", "#66746f"
CARD_W, CARD_H, SCALE = 516, 830, 2


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=False, allow_nan=False).encode("utf-8")


def digest(value):
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_prototype():
    if not PROTOTYPE.is_file():
        raise SystemExit(
            f"Missing real prototype module: {PROTOTYPE}. This probe refuses to "
            "invent teaching_effect events or render mock gameplay as acceptance."
        )
    spec = importlib.util.spec_from_file_location("teaching_skill_prototype", PROTOTYPE)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot import prototype module: {PROTOTYPE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "make_scene", None)
    if not callable(factory):
        raise SystemExit("teaching_skill_prototype.make_scene is missing or not callable")
    return module, factory


def unwrap_battle(result):
    """Accept PrototypeBattle or a raw Battle; reject ambiguous wrappers."""
    battle = getattr(result, "battle", None) if not hasattr(result, "events") else result
    if battle is None and hasattr(result, "raw_battle"):
        battle = result.raw_battle
    if battle is not None and not all(hasattr(battle, attr) for attr in ("events", "units")):
        battle = None
    if battle is None or not all(hasattr(battle, attr) for attr in ("events", "units")):
        raise SystemExit(
            "make_scene must return PrototypeBattle (a real Battle subclass) or raw Battle; "
            f"got {type(result).__name__}"
        )
    return battle


def load_design_contract():
    data = json.loads(DESIGN.read_text(encoding="utf-8"))
    machines = {row["id"]: row for row in data["machines"]}
    missing = {"guardian_riposte", "tempo_break"} - set(machines)
    if missing:
        raise SystemExit(f"Design truth source is missing frozen machines: {sorted(missing)}")
    first = {row["id"] for row in data["machines"] if row.get("status") == "first_batch"}
    if first != {"guardian_riposte", "tempo_break"}:
        raise SystemExit(f"First-batch design truth changed unexpectedly: {sorted(first)}")
    return data, machines


@dataclass
class TeachingBinding:
    scene: str
    raw_index: int
    event: tuple
    machine_id: str
    payload: dict
    actual_data: dict
    actual_shape: str
    parent_raw_index: int
    parent: tuple
    timing: object
    owned: list


def find_parent_timing(animation, parent_index, parent):
    # AnimationTimeline.ActionTiming.source_index is the raw event index.
    matches = [action for action in animation.timeline.actions
               if action.source_index == parent_index and action.kind == parent[1]]
    if len(matches) != 1:
        raise AssertionError(
            f"Expected one ActionTiming for raw event {parent_index}, found {len(matches)}"
        )
    return matches[0]


def actual_view(payload):
    """Return the nested actual object, or an alias-free view of flat fields."""
    actual_data = payload.get("actual", {})
    if not isinstance(actual_data, dict):
        raise AssertionError("teaching_effect actual must be an object when present")
    return actual_data


def actual(payload, name, default=None):
    # Both ABIs are first-class. Never fold one into the other by mutating payload.
    for source in (actual_view(payload), payload):
        if name in source:
            return source[name]
    return default


def collect_teachings(scene, battle, animation, expected_machine=None):
    bindings = []
    for index, event in enumerate(battle.events):
        if event[1] != "teaching_effect" or len(event) != 6:
            continue
        _, _, source_idx, target_idx, machine_id, payload = event
        if machine_id not in {"guardian_riposte", "tempo_break"}:
            raise AssertionError(f"Unexpected teaching machine {machine_id!r} in first-batch probe")
        if not isinstance(payload, dict):
            raise AssertionError("teaching_effect payload must be an object")
        cause_index = payload.get("cause_index")
        cause_count = payload.get("cause_event_count", payload.get("event_count"))
        event_count = payload.get("event_count", cause_count)
        if type(cause_index) is not int or not 0 <= cause_index < index:
            raise AssertionError(f"{scene}: invalid cause_index {cause_index!r}")
        parent = battle.events[cause_index]
        if parent[1] not in ("attack", "cast"):
            raise AssertionError(f"{scene}: parent {cause_index} is {parent[1]}, not attack/cast")
        if type(cause_count) is not int or not 1 <= cause_count or index + cause_count >= len(battle.events):
            raise AssertionError(f"{scene}: invalid cause_event_count {cause_count!r}")
        if event_count != cause_count:
            raise AssertionError(f"{scene}: event_count and cause_event_count disagree")
        if payload.get("source_idx") != source_idx or payload.get("target_idx") != target_idx:
            raise AssertionError(f"{scene}: source/target mismatch between tuple and payload")
        for key in ("source_pos", "target_pos"):
            pos = payload.get(key)
            if (not isinstance(pos, (tuple, list)) or len(pos) != 2
                    or any(type(value) is not int for value in pos)):
                raise AssertionError(f"{scene}: teaching payload lacks valid {key}")

        def related_agents(candidate):
            if candidate[1] in ("attack", "cast", "skill_effect"):
                return set(candidate[2:4])
            if candidate[1] in ("move", "unit_state", "status", "regen", "sash", "die"):
                return {candidate[2]}
            return set()

        legal = {source_idx, target_idx, parent[2], parent[3]}
        allowed = {"attack", "cast", "move", "unit_state", "status", "regen",
                   "sash", "die", "miss", "skill_effect"}
        native_side_children = set()
        for child_index in range(cause_index + 1, index):
            child = battle.events[child_index]
            if child[1] != "skill_effect":
                continue
            native_payload = child[6] if len(child) == 7 else {}
            count = native_payload.get("event_count") if isinstance(native_payload, dict) else None
            if (not isinstance(native_payload, dict) or native_payload.get("cast_index") != cause_index
                    or type(count) is not int or not 0 <= count
                    or child_index + count >= len(battle.events)):
                raise AssertionError(f"{scene}: native skill_effect {child_index} is not owned by the parent cast")
            if child[2] != parent[2]:
                raise AssertionError(f"{scene}: native skill_effect {child_index} changes caster")
            native_side_children.update(range(child_index + 1, child_index + count + 1))
        for child_index in range(cause_index + 1, index):
            child = battle.events[child_index]
            if child[1] == "teaching_effect" or child[1] not in allowed:
                raise AssertionError(f"{scene}: native packet event {child_index} is unsupported")
            if child[1] == "skill_effect":
                continue
            if child_index in native_side_children:
                continue
            if not related_agents(child).issubset(legal):
                raise AssertionError(f"{scene}: native packet event {child_index} introduces an unrelated unit")
        owned = list(range(index + 1, index + 1 + cause_count))
        for child_index in owned:
            child = battle.events[child_index]
            if child[1] == "teaching_effect" or child[1] not in allowed:
                raise AssertionError(f"{scene}: owned event {child_index} has unsupported kind {child[1]}")
            if not related_agents(child).issubset(legal):
                raise AssertionError(f"{scene}: owned event {child_index} introduces an unrelated unit")
        timing = find_parent_timing(animation, cause_index, parent)
        if machine_id == "guardian_riposte":
            if source_idx == parent[2] or target_idx != parent[2] or source_idx != parent[3]:
                raise AssertionError("guardian_riposte source/target must reverse the parent attacker/defender")
        elif machine_id == "tempo_break":
            if source_idx != parent[2] or target_idx != parent[3]:
                raise AssertionError("tempo_break source/target must match parent caster/target")
        if expected_machine and machine_id != expected_machine:
            raise AssertionError(f"{scene}: expected {expected_machine}, got {machine_id}")
        bindings.append(TeachingBinding(
            scene, index, event, machine_id, payload, actual_view(payload),
            "nested" if "actual" in payload else "flat",
            cause_index, parent, timing, owned))
    return bindings


def patch_owned_event_time(events, raw_event, impact):
    """Patch one presentation-stream match to the parent impact timestamp."""
    matches = [index for index, event in enumerate(events)
               if event[1:] == raw_event[1:]]
    if not matches:
        raise AssertionError("teaching owned event is absent from the presentation stream")
    # Duplicated unit_state rows are legal. The later scheduling slot is the child
    # inserted after the native packet, while an identical earlier row is native.
    match = max(matches, key=lambda index: (events[index][0], index))
    old = events[match][0]
    if old != impact:
        events[match] = (impact, *events[match][1:])
    return {"kind": raw_event[1], "raw_simulation_seconds": raw_event[0],
            "scheduled_before": old, "scheduled_after": impact}


def verify_actual_abi_compatibility(binding):
    """Self-test both documented payload views without fabricating an event."""
    if binding.machine_id == "guardian_riposte":
        names = ("pushed", "from_pos", "to_pos", "delay_seconds",
                 "next_act_before", "next_act_after")
    else:
        names = ("actual_loss", "energy_before", "energy_after", "returned_energy")
    flat = {name: actual(binding.payload, name) for name in names}
    if any(value is None for value in flat.values()):
        raise AssertionError(f"{binding.scene}: flat actual ABI is incomplete")
    nested = {"actual": dict(flat)}
    for name, value in flat.items():
        if actual(nested, name) != value:
            raise AssertionError(f"{binding.scene}: nested actual ABI changes {name}")
    return {"flat": True, "nested": True, "fields": list(names)}


def adapt_teaching_schedule(animation, binding):
    """Bind only this probe's owned presentation records to the parent impact.

    The raw battle and the production AnimationTimeline class remain untouched.
    This local event-stream copy is the acceptance adapter that prevents the
    isolated overlay from becoming correct while the body/state tracks lag behind.
    """
    adapted = list(animation.timeline.events)
    changes = []
    for raw_index in binding.owned:
        raw_event = animation.events[raw_index]
        if raw_event[1] not in ("move", "unit_state"):
            continue
        changes.append(patch_owned_event_time(adapted, raw_event, binding.timing.impact))
    adapted.sort(key=lambda event: event[0])
    public = list(animation.timeline.public_events)
    for raw_index in binding.owned:
        raw_event = animation.events[raw_index]
        if raw_event[1] in ("move", "unit_state"):
            patch_owned_event_time(public, raw_event, binding.timing.impact)
    public.sort(key=lambda event: event[0])
    animation.timeline.events = tuple(adapted)
    animation.timeline.event_times = [event[0] for event in adapted]
    animation.timeline.public_events = tuple(public)
    animation.presentation_events = animation.timeline.public_events
    return changes


def state_at(animation, when):
    return {key: copy.deepcopy(row) for key, row in animation.presentation_state(when).items()}



def replay_authoritative_events(events, units=()):
    """A second read-only state reducer used to audit the production replay.

    It intentionally consumes only authoritative deploy/unit_state/move/die rows;
    attack/cast numbers are never used to invent HP. Missing initial values stay
    explicit ``None`` until the simulator emits its first unit_state.
    """
    states = {}
    rows = [dict(states)]
    for event in events:
        kind = event[1]
        if kind == "deploy":
            idx, pos = event[2], event[3]
            old = states.get(idx, {"hp": None, "energy": None, "pos": None, "alive": True})
            states[idx] = {**old, "pos": tuple(pos)}
        elif kind in ("unit_state",):
            idx, hp, energy = event[2], event[3], event[4]
            old = states.get(idx, {"hp": None, "energy": None, "pos": None, "alive": True})
            states[idx] = {**old, "hp": hp, "energy": energy}
        elif kind == "move":
            idx, pos = event[2], event[3]
            if idx in states:
                states[idx] = {**states[idx], "pos": tuple(pos)}
        elif kind == "die":
            idx = event[2]
            if idx in states:
                states[idx] = {**states[idx], "hp": 0, "alive": False}
        rows.append(dict(states))
    return rows


def replay_at_index(rows, index):
    if not 0 <= index < len(rows):
        raise AssertionError(f"state replay index {index} is outside the event stream")
    return rows[index]


def replay_at_time(rows, events, when):
    selected = 0
    for index, event in enumerate(events):
        if event[0] <= when + 1e-9:
            selected = index + 1
        else:
            break
    return replay_at_index(rows, selected)


def compact_state(states, indexes):
    return {str(idx): states.get(idx) for idx in sorted(indexes)}


def reconcile_parent_state(scene, binding, battle, animation, parameters):
    """Reconcile native result, teaching metadata, owned events and presentation."""
    source, target = binding.event[2], binding.event[3]
    parent_attacker, parent_target = binding.parent[2], binding.parent[3]
    raw_rows = replay_authoritative_events(battle.events, battle.units)
    scheduled_rows = replay_authoritative_events(animation.timeline.events, battle.units)
    impact = binding.timing.impact
    before = replay_at_index(raw_rows, binding.parent_raw_index)
    native_after = replay_at_index(raw_rows, binding.raw_index)
    teaching_after = replay_at_index(raw_rows, binding.owned[-1] + 1)
    presentation_before = replay_at_time(scheduled_rows, animation.timeline.events, impact - 0.001)
    presentation_after = replay_at_time(scheduled_rows, animation.timeline.events, impact + 0.001)
    displayed_before = state_at(animation, impact - 0.001)
    displayed_after = state_at(animation, impact + 0.001)
    agents = sorted({source, target, parent_attacker, parent_target})

    for label, states in (("native_before", before), ("native_after", native_after),
                          ("teaching_after", teaching_after)):
        if any(states.get(idx) is None for idx in (source, target)):
            raise AssertionError(f"{scene}: {label} state is missing teaching source/target")
    if binding.machine_id == "guardian_riposte":
        parent_damage = binding.parent[4]
    else:
        parent_damage = binding.parent[6]
    native_hp_loss = max(0, before[parent_target]["hp"] - native_after[parent_target]["hp"])
    if native_hp_loss != parent_damage:
        raise AssertionError(
            f"{scene}: parent damage {parent_damage} does not match authoritative HP loss {native_hp_loss}")
    if native_hp_loss <= 0:
        raise AssertionError(f"{scene}: teaching parent did not cause authoritative HP loss")

    for idx in agents:
        rendered = {"hp": displayed_before.get(idx, {}).get("hp"),
                    "energy": displayed_before.get(idx, {}).get("energy"),
                    "die_t": displayed_before.get(idx, {}).get("die_t")}
        expected = presentation_before.get(idx, {})
        if rendered["hp"] != expected["hp"] or rendered["energy"] != expected["energy"]:
            raise AssertionError(f"{scene}: presentation HP/energy disagrees at impact boundary for {idx}")
        rendered_after = {"hp": displayed_after.get(idx, {}).get("hp"),
                          "energy": displayed_after.get(idx, {}).get("energy"),
                          "die_t": displayed_after.get(idx, {}).get("die_t")}
        expected_after = presentation_after.get(idx, {})
        if (rendered_after["hp"] != expected_after["hp"]
                or rendered_after["energy"] != expected_after["energy"]):
            raise AssertionError(f"{scene}: presentation HP/energy disagrees after impact for {idx}")

    row = {
        "parent_raw_index": binding.parent_raw_index,
        "parent_kind": binding.parent[1],
        "impact": impact,
        "native_before": compact_state(before, agents),
        "native_after": compact_state(native_after, agents),
        "teaching_after": compact_state(teaching_after, agents),
        "presentation_before": compact_state(presentation_before, agents),
        "presentation_after": compact_state(presentation_after, agents),
        "actual_shape": binding.actual_shape,
        "actual": binding.actual_data,
    }
    if binding.machine_id == "guardian_riposte":
        if not native_after[source]["hp"] < before[source]["hp"]:
            raise AssertionError(f"{scene}: guardian source did not lose authoritative HP")
        if not native_after[source]["alive"] or native_after[source]["hp"] <= 0:
            raise AssertionError(f"{scene}: guardian source must survive the parent hit")
        pushed = actual(binding.payload, "pushed")
        delay = actual(binding.payload, "delay_seconds")
        from_pos = actual(binding.payload, "from_pos")
        to_pos = actual(binding.payload, "to_pos")
        next_before = actual(binding.payload, "next_act_before")
        next_after = actual(binding.payload, "next_act_after")
        if type(pushed) is not bool or type(delay) not in (int, float):
            raise AssertionError(f"{scene}: guardian pushed/delay semantics are incomplete")
        if None in (from_pos, to_pos, next_before, next_after):
            raise AssertionError(f"{scene}: guardian displacement/timing semantics are incomplete")
        from_pos, to_pos = tuple(from_pos), tuple(to_pos)
        if tuple(binding.payload["target_pos"]) != from_pos:
            raise AssertionError(f"{scene}: guardian from_pos disagrees with native post-chain position")
        if tuple(binding.payload["source_pos"]) != native_after[source]["pos"]:
            raise AssertionError(f"{scene}: guardian source_pos is not the native post-chain snapshot")
        moves = [battle.events[i] for i in binding.owned if battle.events[i][1] == "move"]
        if pushed != (to_pos != from_pos) or (pushed and sum(abs(a-b) for a, b in zip(from_pos, to_pos)) != 1):
            raise AssertionError(f"{scene}: guardian displacement is not one legal cell")
        if pushed and (len(moves) != 1 or moves[0][2] != target or tuple(moves[0][3]) != to_pos):
            raise AssertionError(f"{scene}: guardian owned move does not express the actual push")
        if not pushed and moves:
            raise AssertionError(f"{scene}: blocked guardian emitted a success move")
        if teaching_after[target]["pos"] != to_pos:
            raise AssertionError(f"{scene}: guardian target position disagrees with owned events")
        if (delay != parameters["delay_seconds"]
                or abs((next_after - next_before) - delay) > 1e-9):
            raise AssertionError(f"{scene}: guardian next-action delay is inconsistent")
        for idx in (source, target):
            if (teaching_after[idx]["hp"] != native_after[idx]["hp"]
                    or teaching_after[idx]["energy"] != native_after[idx]["energy"]):
                raise AssertionError(f"{scene}: guardian invented HP or energy for {idx}")
        row["semantic"] = {
            "parent_hp_loss": native_hp_loss, "pushed": pushed,
            "from_pos": list(from_pos), "to_pos": list(to_pos),
            "delay_seconds": delay, "next_act_before": next_before,
            "next_act_after": next_after,
            "hp_unchanged_by_teaching": True, "energy_unchanged_by_teaching": True,
        }
    else:
        removed = actual(binding.payload, "actual_loss", None)
        if type(removed) is not int:
            removed = actual(binding.payload, "removed", None)
        energy_before = actual(binding.payload, "energy_before")
        energy_after = actual(binding.payload, "energy_after")
        returned = actual(binding.payload, "returned_energy")
        if type(removed) is not int or None in (energy_before, energy_after, returned):
            raise AssertionError(
                f"{scene}: tempo result semantics are incomplete: removed={removed!r}, "
                f"before={energy_before!r}, after={energy_after!r}, returned={returned!r}")
        if energy_before != native_after[target]["energy"]:
            raise AssertionError(f"{scene}: tempo energy_before disagrees with native post-hit state")
        if energy_after != teaching_after[target]["energy"] or energy_before - energy_after != removed:
            raise AssertionError(f"{scene}: tempo loss disagrees with owned unit_state")
        if removed != min(energy_before, parameters["energy_loss"]) or returned != 0:
            raise AssertionError(f"{scene}: tempo loss/return violates first-batch parameters")
        if teaching_after[source]["energy"] != native_after[source]["energy"]:
            raise AssertionError(f"{scene}: tempo returned energy to its source")
        state_children = [battle.events[i] for i in binding.owned if battle.events[i][1] == "unit_state"]
        if not any(child[2] == target and child[4] == energy_after for child in state_children):
            raise AssertionError(f"{scene}: tempo lacks the authoritative target unit_state")
        if (teaching_after[target]["hp"] != native_after[target]["hp"]
                or teaching_after[source]["hp"] != native_after[source]["hp"]):
            raise AssertionError(f"{scene}: tempo invented HP")
        row["semantic"] = {
            "parent_hp_loss": native_hp_loss, "actual_loss": removed,
            "energy_before": energy_before, "energy_after": energy_after,
            "returned_energy": returned, "zero_identified_by": "actual_loss == 0",
            "zero": removed == 0, "hp_unchanged_by_teaching": True,
        }
    for idx in (source, target):
        if (presentation_before.get(idx, {}).get("pos") != before[idx]["pos"]
                or presentation_after.get(idx, {}).get("pos") != teaching_after[idx]["pos"]):
            raise AssertionError(f"{scene}: presentation position disagrees with authoritative replay for {idx}")
    return row


def cell_center(pos):
    x = renderer.BX + pos[0] * renderer.BCELL + renderer.BCELL // 2
    y = renderer.BY + (pos[1] + renderer.VIS_ROW_OFF) * renderer.BCELL + renderer.BOARD_FOOT - 12
    return x * SCALE, y * SCALE


def overlay_cost_estimate(kind, phase):
    """Preliminary teaching-only draw estimate; native shared budget is unmetered."""
    if phase == "idle":
        return 0
    if kind == "guardian_riposte":
        return 28 if phase == "charge" else 42
    return 24 if phase == "charge" else 36


def draw_teaching_overlay(image, binding, when, font):
    """Draw one isolated teaching track on a 480x640 upscaled native frame."""
    timing = binding.timing
    before = timing.impact - 0.20
    fade_end = timing.impact + 0.45
    if not before <= when <= fade_end:
        return 0
    draw = ImageDraw.Draw(image, "RGBA")
    source = cell_center(binding.payload["source_pos"])
    target = cell_center(binding.payload["target_pos"])
    phase = "charge" if when < timing.impact else "result"
    p = min(1.0, max(0.0, (when - before) / (fade_end - before)))
    impact_p = min(1.0, max(0.0, (when - timing.impact) / 0.35))
    alpha = int(105 * (1 - max(0.0, (when - timing.impact) / 0.45)) + 150) if when >= timing.impact else int(100 + 90 * p)
    if binding.machine_id == "guardian_riposte":
        color = (94, 176, 214, alpha)
        radius = 18 + 26 * p
        draw.arc((source[0]-radius, source[1]-radius*.65,
                  source[0]+radius, source[1]+radius*.65), 190, 350, fill=color, width=5)
        if phase == "result":
            dx, dy = target[0]-source[0], target[1]-source[1]
            norm = math.hypot(dx, dy) or 1.0
            ux, uy = dx/norm, dy/norm
            start = (target[0]-ux*30, target[1]-uy*30)
            end = (target[0]+ux*(30+36*impact_p), target[1]+uy*(30+36*impact_p))
            draw.line((start, end), fill=color, width=7)
            draw.polygon((end[0]-ux*14-uy*9, end[1]-uy*14+ux*9,
                          end[0]-ux*14+uy*9, end[1]-uy*14-ux*9), fill=color)
            pushed = bool(actual(binding.payload, "pushed", False))
            delay = actual(binding.payload, "delay_seconds", 0.3)
            label = "推离" if pushed else "堵位·迟滞"
            draw.text((target[0]+8, target[1]-30), label, font=font, fill=(32, 54, 66, min(255, alpha+40)))
            draw.text((target[0]+8, target[1]-8), f"{delay:g}s", font=font, fill=(32, 54, 66, min(255, alpha+40)))
    else:
        color = (232, 116, 82, alpha)
        for i in range(6):
            t0, t1 = i/6, (i+.52)/6
            a = (source[0]+(target[0]-source[0])*t0, source[1]+(target[1]-source[1])*t0)
            b = (source[0]+(target[0]-source[0])*t1, source[1]+(target[1]-source[1])*t1)
            draw.line((a, b), fill=color, width=6)
        if phase == "result":
            for i in range(4):
                angle = math.tau * i / 4 + impact_p * 2.0
                r0, r1 = 16+8*impact_p, 28+16*impact_p
                draw.line((target[0]+r0*math.cos(angle), target[1]+r0*math.sin(angle),
                           target[0]+r1*math.cos(angle), target[1]+r1*math.sin(angle)),
                          fill=color, width=5)
            removed = actual(binding.payload, "actual_loss", actual(binding.payload, "removed", 0))
            zero = actual(binding.payload, "actual_loss", 0) == 0
            label = "能量断点" if removed else "零能消耗"
            value = f"-{removed}" if not zero else "0"
            draw.text((target[0]+8, target[1]-30), label, font=font, fill=(58, 30, 30, min(255, alpha+40)))
            draw.text((target[0]+8, target[1]-8), value, font=font, fill=(58, 30, 30, min(255, alpha+40)))
    return overlay_cost_estimate(binding.machine_id, phase)


def card(frame, title, subtitle, when, fonts):
    image = Image.new("RGB", (CARD_W, CARD_H), PAPER)
    draw = ImageDraw.Draw(image)
    draw.text((18, 13), title, font=fonts[0], fill=INK)
    draw.text((18, 48), subtitle, font=fonts[1], fill=MUTED)
    image.paste(frame.convert("RGB"), (18, 80))
    # The native renderer owns y=80..720. Keep acceptance metadata in a separate
    # footer band so it can never cover the production board, meters, or log.
    draw.line((18, 728, CARD_W-18, 728), fill="#c7cfc9", width=2)
    draw.text((18, 738), f"演出时刻 {when:.2f}s · 原生 240×320 / 2×", font=fonts[2], fill=MUTED)
    draw.text((18, 761), "teaching_effect 只读叠加 · 不改权威事件", font=fonts[2], fill=MUTED)
    draw.text((18, 784), "PC 画面证据，不代表 ESP32 或平衡结论", font=fonts[2], fill=MUTED)
    return image


def render_frame(animation, binding, when, fonts, title, subtitle,
                  speed=1.0, skip=False):
    presentation_when = animation.timeline.time(when, speed=speed, skip=skip)
    native = animation.playback_frame(when, speed=speed, skip=skip).convert("RGB").resize(
        (240*SCALE, 320*SCALE), Image.Resampling.NEAREST)
    particles = (draw_teaching_overlay(native, binding, presentation_when, fonts[2])
                 if binding is not None else 0)
    return card(native, title, subtitle, presentation_when, fonts), particles


def frame_pixels(image):
    return hashlib.sha256(image.tobytes()).hexdigest()


def verify_rewind(animation, binding, fonts, title, subtitle, moment):
    reference, _ = render_frame(animation, binding, moment, fonts, title, subtitle)
    expected = frame_pixels(reference)
    later = moment + 0.32
    render_frame(animation, binding, later, fonts, title, subtitle)
    rewound, _ = render_frame(animation, binding, moment, fonts, title, subtitle)
    half, _ = render_frame(animation, binding, moment / 0.5, fonts, title, subtitle, speed=0.5)
    doubled, _ = render_frame(animation, binding, moment / 2.0, fonts, title, subtitle, speed=2.0)
    settled, _ = render_frame(animation, binding, animation.timeline.duration + 1.0,
                              fonts, title, subtitle, skip=True)
    direct_settled, _ = render_frame(animation, binding, animation.timeline.duration,
                                     fonts, title, subtitle)
    pixels = {
        "pixel_sha256": expected,
        "rewind_pixel_sha256": frame_pixels(rewound),
        "playback_0_5x_pixel_sha256": frame_pixels(half),
        "playback_1x_pixel_sha256": expected,
        "playback_2x_pixel_sha256": frame_pixels(doubled),
        "skip_pixel_sha256": frame_pixels(settled),
        "skip_direct_final_pixel_sha256": frame_pixels(direct_settled),
    }
    if pixels["playback_0_5x_pixel_sha256"] != expected or pixels["playback_2x_pixel_sha256"] != expected:
        raise AssertionError("playback speed changes the overlay pixel at the same presentation moment")
    if pixels["rewind_pixel_sha256"] != expected:
        raise AssertionError("rewind changes the overlay pixel at the same presentation moment")
    if pixels["skip_pixel_sha256"] != pixels["skip_direct_final_pixel_sha256"]:
        raise AssertionError("skip changes the settled final pixel")
    return {"presentation_seconds": moment, **pixels}


def save_gif(path, animation, binding, fonts, title, subtitle, fps, start, end):
    frames = []
    peak_particles = 0
    count = int(math.ceil((end-start) * fps)) + 1
    for index in range(count):
        when = start + index / fps
        frame, particles = render_frame(animation, binding, when, fonts, title, subtitle)
        frames.append(frame)
        peak_particles = max(peak_particles, particles)
    stack = Image.new("RGB", (frames[0].width, frames[0].height * len(frames)))
    for index, frame in enumerate(frames):
        stack.paste(frame, (0, frame.height * index))
    palette = stack.quantize(colors=256)
    indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    indexed[0].save(path, save_all=True, append_images=indexed[1:],
                    duration=round(1000/fps), loop=0, disposal=2, optimize=False)
    return {"frames": len(frames), "fps": fps, "peak_teaching_overlay_estimate": peak_particles,
            "range": [start, end]}


def output_row(path, scene, kind, extra=None):
    row = {"file": path.name, "scene": scene, "kind": kind,
           "bytes": path.stat().st_size,
           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    if extra:
        row.update(extra)
    return row


def native_negative_moment(scene, battle, animation, expected):
    candidates = [event for event in battle.events
                  if event[1] in ("attack", "cast", "miss")]
    if not candidates:
        raise AssertionError(f"{scene}: negative scene has no native outcome event")
    parent = candidates[0]
    if parent[1] in ("attack", "cast"):
        timing = find_parent_timing(animation, battle.events.index(parent), parent)
        return parent, timing.impact
    matches = [event for event in animation.timeline.events
               if event[1] == "miss" and event[2:4] == parent[2:4]]
    if len(matches) != 1:
        raise AssertionError(f"{scene}: expected one scheduled miss, found {len(matches)}")
    return parent, matches[0][0]


def run_probe(args, fonts, factory, design, design_machines, failure):
    assets = (renderer.Front(), renderer.Palettes(), renderer.Font16())
    scene_rows = {}
    outputs = []
    overview_cards = []
    all_checks = {
        "cause_ownership": True,
        "state_reconciliation": True,
        "negative_paths": True,
        "actual_abi_compatibility": True,
        "event_hash_unchanged": True,
        "rewind_speed_pixels": True,
        "teaching_overlay_estimated_budget": True,
    }
    failure.update({"scenes": scene_rows, "outputs": outputs, "checks": all_checks})
    subtitles = {
        "counter_valid": "守备反击 / 真实推离",
        "counter_blocked": "守备反击 / 堵位但仍迟滞",
        "counter_invalid": "守备反击 / 远程无效路径",
        "counter_lethal": "守备反击 / 死亡取消",
        "tempo_valid": "心律截断 / 真实削能",
        "tempo_zero": "心律截断 / 零能场景",
        "tempo_invalid": "心律截断 / 真实未命中",
        "tempo_lethal": "心律截断 / 目标死亡取消",
        "full_natural": "6 人口自然战斗 / 首个守备窗口",
        "tempo_full_natural": "6 人口自然战斗 / 首个心律窗口",
    }

    for scene, kind, scenario in SCENES:
        battle = unwrap_battle(factory(kind, scenario=scenario, seed=7))
        original = copy.deepcopy(battle.events)
        original_hash = digest(battle.events)
        failure_scene = {
            "factory_kind": kind, "scenario": scenario,
            "authoritative_event_sha256": original_hash,
            "authoritative_events": [list(event) for event in original],
        }
        scene_rows[scene] = failure_scene
        animation = renderer.BattleAnimation([], [], 7, *assets, battle=battle)
        expected = MACHINE_BY_SCENE[scene]
        if scene in ("full_natural", "tempo_full_natural"):
            team_counts = {0: 0, 1: 0}
            for unit in battle.units:
                team_counts[unit.team] = team_counts.get(unit.team, 0) + 1
            if team_counts != {0: 6, 1: 6}:
                raise AssertionError(f"full scene population is {team_counts}, expected 6 per side")
        bindings = collect_teachings(scene, battle, animation, expected)
        positive = bool(bindings)
        if scene in POSITIVE_DIRECTED_SCENES and not positive:
            all_checks["negative_paths"] = False
            raise AssertionError(f"{scene}: expected directed teaching event")
        if not positive:
            if any(event[1] == "teaching_effect" for event in battle.events):
                all_checks["negative_paths"] = False
                raise AssertionError(f"{scene}: negative scenario emitted teaching_effect")
            native_event, moment = native_negative_moment(scene, battle, animation, expected)
            title = f"{scene} · {expected or kind}"
            shots = (
                (f"{scene}-pre", moment - .10, "原生动作前 / 无成功反馈"),
                (f"{scene}-outcome", moment + .25, "真实负向结果 / 无教学成功轨"),
            )
            cards = []
            for filename, when, label in shots:
                frame, particles = render_frame(animation, None, when, fonts, title, subtitles[scene])
                frame.save(args.out / f"{filename}.png")
                outputs.append(output_row(
                    args.out / f"{filename}.png", scene, "keyframe", {
                        "presentation_seconds": round(when, 6), "phase": label,
                        "teaching_overlay_estimate": particles,
                        "pixels_sha256": frame_pixels(frame),
                    }))
                cards.append(frame)
            overview_cards.extend(cards[:1])
            start, end = moment - .20, moment + .50
            gif_path = args.out / f"{scene}.gif"
            gif = save_gif(gif_path, animation, None, fonts, title, subtitles[scene],
                           args.fps, start, end)
            outputs.append(output_row(gif_path, scene, "continuous_clip", gif))
            playback = verify_rewind(animation, None, fonts, title, subtitles[scene], moment + .08)
            if playback["pixel_sha256"] != playback["rewind_pixel_sha256"]:
                all_checks["rewind_speed_pixels"] = False
            if battle.events != original or digest(battle.events) != original_hash:
                all_checks["event_hash_unchanged"] = False
                raise AssertionError(f"{scene}: negative rendering mutated authoritative events")
            scene_rows[scene] = {
                "factory_kind": kind, "scenario": scenario,
                "unit_count": len(battle.units), "event_count": len(battle.events),
                "teaching_event_count": 0,
                "negative_reason": {
                    "counter_invalid": "ranged_primary",
                    "counter_lethal": "defender_death_at_snapshot",
                    "tempo_invalid": "real_accuracy_miss",
                    "tempo_lethal": "target_death_at_snapshot",
                }[scene],
                "native_outcome": {"raw_index": battle.events.index(native_event),
                                   "kind": native_event[1], "scheduled_seconds": moment},
                "authoritative_event_sha256": original_hash,
                "after_render_event_sha256": digest(battle.events),
                "playback": playback, "peak_teaching_overlay_estimate": 0,
                "success_overlay_present": False,
            }
            continue

        if expected and len(bindings) != 1:
            raise AssertionError(f"{scene}: expected exactly one directed teaching event")
        machine_parameters = {
            machine: design_machines[machine]["candidate_parameters"]
            for machine in ("guardian_riposte", "tempo_break")
        }
        actual_abi_rows = [verify_actual_abi_compatibility(binding)
                           for binding in bindings]
        schedule_adapters = [adapt_teaching_schedule(animation, binding)
                             for binding in bindings]
        reconciliations = [reconcile_parent_state(
            scene, binding, battle, animation, machine_parameters[binding.machine_id])
            for binding in bindings]
        use_counts = {}
        for binding in bindings:
            uses = actual(binding.payload, "uses_per_battle", 1)
            if type(uses) is not int or uses != 1:
                raise AssertionError(f"{scene}: first-batch teaching use contract changed")
            key = (binding.machine_id, binding.event[2])
            use_counts[key] = use_counts.get(key, 0) + 1
        if any(count > 1 for count in use_counts.values()):
            raise AssertionError(f"{scene}: a source used first-batch teaching more than once")
        primary = bindings[0]
        title = f"{scene} · {primary.machine_id}"
        shots = (
            (f"{scene}-pre", primary.timing.impact - .10, "父动作前 / 只预亮不结算"),
            (f"{scene}-impact", primary.timing.impact, "父命中同拍 / 教学生效"),
            (f"{scene}-after", primary.timing.impact + .30, "恢复余波 / 权威状态不回写"),
        )
        cards = []
        peak_particles = 0
        for filename, when, label in shots:
            frame, particles = render_frame(
                animation, primary, when, fonts, title, subtitles[scene])
            frame.save(args.out / f"{filename}.png")
            outputs.append(output_row(
                args.out / f"{filename}.png", scene, "keyframe", {
                    "presentation_seconds": round(when, 6), "phase": label,
                    "teaching_overlay_estimate": particles,
                    "pixels_sha256": frame_pixels(frame),
                }))
            cards.append(frame)
            peak_particles = max(peak_particles, particles)
        overview_cards.extend(cards[:2])
        start, end = primary.timing.impact - .20, primary.timing.impact + .50
        gif_path = args.out / f"{scene}.gif"
        gif = save_gif(gif_path, animation, primary, fonts, title, subtitles[scene],
                       args.fps, start, end)
        outputs.append(output_row(gif_path, scene, "continuous_clip", gif))
        peak_particles = max(peak_particles, gif["peak_teaching_overlay_estimate"])
        if peak_particles > 192:
            all_checks["teaching_overlay_estimated_budget"] = False
        playback = verify_rewind(
            animation, primary, fonts, title, subtitles[scene], primary.timing.impact + .08)
        if battle.events != original or digest(battle.events) != original_hash:
            all_checks["event_hash_unchanged"] = False
            raise AssertionError(f"{scene}: rendering mutated authoritative events")
        scene_rows[scene] = {
            "factory_kind": kind, "scenario": scenario,
            "unit_count": len(battle.units), "event_count": len(battle.events),
            "authoritative_event_sha256": original_hash,
            "after_render_event_sha256": digest(battle.events),
            "teaching_events": [
                {"raw_index": row.raw_index, "machine_id": row.machine_id,
                 "source_idx": row.event[2], "target_idx": row.event[3],
                 "cause_index": row.parent_raw_index, "cause_parent_kind": row.parent[1],
                 "cause_event_count": len(row.owned), "payload": row.payload,
                 "actual_shape": row.actual_shape,
                 "owned_raw_indices": row.owned,
                 "actual_abi_self_test": actual_abi_rows[index],
                 "schedule_adapter": schedule_adapters[index],
                 "owned_events": [list(battle.events[i]) for i in row.owned],
                 "parent_timing": {"start": row.timing.start, "release": row.timing.release,
                                   "impact": row.timing.impact, "recover_end": row.timing.recover_end}}
                for index, row in enumerate(bindings)
            ],
            "parent_state_reconciliation": reconciliations[0] if len(reconciliations) == 1 else reconciliations,
            "playback": playback, "peak_teaching_overlay_estimate": peak_particles,
        }

    columns = 3
    rows = math.ceil(len(overview_cards) / columns)
    gap = 18
    overview = Image.new("RGB", (columns*CARD_W+(columns+1)*gap,
                                 rows*CARD_H+(rows+1)*gap), "#dce1d9")
    for index, current in enumerate(overview_cards):
        overview.paste(current, (gap+(index % columns)*(CARD_W+gap),
                                 gap+(index // columns)*(CARD_H+gap)))
    overview_path = args.out / "teaching-overview.png"
    overview.save(overview_path)
    outputs.append(output_row(overview_path, None, "overview"))

    source_paths = [
        "docs/32-teaching-skill-animation-contract.md",
        "docs/design/teaching-skills-v1.json",
        "tools/acceptance/teaching_skill_prototype.py",
        "tools/acceptance/teaching_visual_probe.py",
        "tools/mockups/animation_timeline.py",
        "tools/mockups/render_battle_gif.py",
    ]
    return {
        "schema": "teaching-visual-probe-v2",
        "seed": 7,
        "renderer": "BattleAnimation.playback_frame + isolated teaching overlay",
        "adapter": {
            "scope": "acceptance-only teaching_effect parser and parent ActionTiming binder",
            "actual_abi": ["flat", "nested"],
            "tempo_zero": "scene name only; zero is actual_loss == 0",
            "production_renderer_consumes_teaching_effect": False,
        },
        "prototype_module_sha256": hashlib.sha256(PROTOTYPE.read_bytes()).hexdigest(),
        "design_truth": {
            "version": design["version"], "status": design["status"],
            "first_batch_parameters": {
                machine: design_machines[machine]["candidate_parameters"]
                for machine in ("guardian_riposte", "tempo_break")
            },
            "note": "Eligibility is read from the design truth; this visual probe does not recompute thresholds."
        },
        "sources_sha256": {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
                           for path in source_paths},
        "scenes": scene_rows,
        "outputs": outputs,
        "checks": all_checks,
        "limits": [
            "All overlays derive from authoritative teaching_effect records and real parent ActionTiming.",
            "The production renderer and tools/mockups are imported read-only; no default behavior was patched.",
            "State reconciliation replays authoritative unit_state/move/die records and cross-checks presentation HP, energy and position at the parent impact.",
            "Negative invalid and lethal scenes render native outcomes only; no teaching success overlay is allowed.",
            "Full scenes are one six-unit natural prototype battle each and are not balance claims.",
            "PC PNG/GIF evidence does not measure ESP32 memory, cache, C sampling, or frame time.",
            "The overlay and adapter are isolated acceptance tracks, not production animation integration.",
            "Budget check covers only a constant teaching-overlay estimate; native/weather/teaching shared total budget is not implemented or verified.",
            "Old cut/surf/rest defects are audited by the contract but are not fixed by this probe.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--fps", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.fps <= 20:
        parser.error("fps must be between 1 and 20")
    args.out.mkdir(parents=True, exist_ok=True)
    font_path = label_font(args.font)
    fonts = tuple(ImageFont.truetype(font_path, size) for size in (24, 18, 14))
    _module, factory = load_prototype()
    design, design_machines = load_design_contract()
    failure = {"schema": "teaching-visual-probe-v2-failure", "seed": 7}
    try:
        evidence = run_probe(args, fonts, factory, design, design_machines, failure)
        if not all(evidence["checks"].values()):
            failure["error"] = {"type": "AssertionError",
                                "message": f"acceptance checks failed: {evidence['checks']}"}
            failure["checks"] = evidence["checks"]
            failure_path = args.out / "visual.failure.json"
            failure_path.write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
            raise AssertionError(f"acceptance checks failed: {evidence['checks']}; raw JSON: {failure_path}")
        metadata = args.out / "visual.json"
        metadata.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(json.dumps({
            "output": str(args.out),
            "scenes": list(evidence["scenes"]),
            "outputs": len(evidence["outputs"]),
            "checks": evidence["checks"],
            "authoritative_events_unchanged": True,
            "metadata": str(metadata),
        }, ensure_ascii=False, indent=2))
    except Exception as error:
        if "error" not in failure:
            failure["error"] = {"type": type(error).__name__, "message": str(error)}
        failure_path = args.out / "visual.failure.json"
        failure_path.write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
