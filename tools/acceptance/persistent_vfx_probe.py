"""Repeatable, save-free evidence for persistent arena battle presentation states.

The probe is deliberately presentation-only. Each scenario is simulated from a
fixed seed in a fresh process; images are direct renderer output and JSON records
the actual replay state/events. No session file or renderer cache is required.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = ROOT / ".build/persistent-vfx-2026-10-14/baseline/tools/mockups"
SOURCE_FILES = (
    "tools/mockups/web_battle.py",
    "tools/mockups/render_battle_gif.py",
    "tools/mockups/presentation_modes.py",
)
SIM_FILES = (
    "sim/arena.py",
    "sim/arena_fields.py",
    "sim/arena_weather.py",
    "sim/combat.py",
    "sim/status.py",
)
MOCKUP_IMPORTS = (
    "arena_scenarios",
    "presentation_modes",
    "render_battle_gif",
    "web_battle",
    "arena_vfx",
    "animation_timeline",
    "motion",
    "move_effects",
    "retro_native",
    "web_motion",
)
MAJOR_STATUSES = ("burn", "poison", "para", "freeze", "sleep")
ACTUAL_CASES = (
    {"stage": 1, "label": "status", "scenario": "arena_attack_attrition", "t": 6.5},
    {"stage": 2, "label": "shields", "scenario": "arena_shield_branches", "t": 6.25},
    {"stage": 3, "label": "rocks", "scenario": "arena_rocks", "t": 5.0},
    {"stage": 4, "label": "weather", "scenario": "arena_rain_conduct", "t": 4.0},
)
REAL_STATUS_CASES = (
    {"status": "poison", "scenario": "arena_status", "seed": 7, "t": 1.5},
    {"status": "paralysis", "scenario": "arena_cleanse_branches", "seed": 7, "t": 16.0},
    {"status": "burn", "scenario": "arena_trait_sustain", "seed": 1, "t": 13.4},
    {"status": "sleep", "scenario": "arena_support", "seed": 1, "t": 5.0},
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(text.encode("utf-8"))


def clean_number(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return round(value, 6)
    if isinstance(value, tuple):
        return [clean_number(item) for item in value]
    if isinstance(value, list):
        return [clean_number(item) for item in value]
    if isinstance(value, dict):
        return {str(key): clean_number(item) for key, item in value.items()}
    return value


def configure_imports(source_root: Path) -> dict[str, str]:
    """Import a complete mockups tree while keeping simulator modules at ROOT/sim."""
    source_root = source_root.resolve()
    if not (source_root / "presentation_modes.py").is_file():
        raise SystemExit(f"source root does not contain presentation_modes.py: {source_root}")
    wanted = [str(source_root), str(ROOT / "sim"), str(ROOT)]
    old_paths = [Path(entry).resolve() for entry in sys.path if Path(entry).exists()]
    stale = []
    for entry in old_paths:
        try:
            is_mockup = entry == (ROOT / "tools/mockups") or DEFAULT_BASELINE in entry.parents
        except OSError:
            continue
        if is_mockup:
            stale.append(str(entry))
    for entry in stale:
        while entry in sys.path:
            sys.path.remove(entry)
    sys.path[0:0] = wanted
    for name in list(sys.modules):
        module = sys.modules.get(name)
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        path = Path(module_file).resolve()
        if path.parent == (ROOT / "tools/mockups") or DEFAULT_BASELINE in path.parents:
            del sys.modules[name]
    imports = {name: importlib.import_module(name) for name in MOCKUP_IMPORTS}
    resolved = {name: str(Path(module.__file__).resolve()) for name, module in imports.items()}
    for name, path in resolved.items():
        if source_root not in Path(path).parents:
            raise RuntimeError(f"mockup import escaped isolated tree: {name}: {path}")
    return resolved


def compact_event(event: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "index": None,
        "t": clean_number(event[0]),
        "kind": event[1],
        "actors": list(event[2:4]),
        "key": event[4] if len(event) > 4 else None,
        "effect": event[5] if len(event) > 5 else None,
        "payload": clean_number(event[6] if len(event) > 6 else {}),
    }


def selected_events(anim: Any, stage: int) -> tuple[list[dict[str, Any]], list[float]]:
    rows: list[tuple[Any, str]] = []
    if stage == 1:
        major = {"burn", "poison", "para", "freeze", "sleep", "paralysis"}
        applies = [e for e in anim.events if e[1] == "status" and e[3] in major and e[4] == "apply"]
        rows.extend((e, "status_apply") for e in applies[:2])
        cleanses = [e for e in anim.events if e[1] in ("combo_effect", "skill_effect")
                    and e[5] == "cleanse"]
        rows.extend((e, "status_cleanse") for e in cleanses[:2])
    elif stage == 2:
        shield = [e for e in anim.events if e[1] in ("combo_effect", "skill_effect")
                  and e[5] in ("shield", "absorb", "expire")]
        first_shield = next((e for e in shield if e[5] == "shield"), None)
        broken = next((e for e in shield if e[5] == "absorb" and e[6].get("shield") == 0), None)
        expired = next((e for e in shield if e[5] == "expire"), None)
        rows.extend((e, label) for e, label in (
            (first_shield, "shield_gain"), (broken, "shield_break"), (expired, "shield_expire")) if e)
    elif stage == 3:
        rocks = [e for e in anim.events if e[1] == "field_effect" and e[4] == "rock_spikes"]
        wanted = {"place": "place", "enter": "enter", "clear": "clear", "expire": "expire"}
        seen: set[str] = set()
        for event in rocks:
            label = wanted.get(event[5])
            if label and label not in seen:
                rows.append((event, f"rock_{label}"))
                seen.add(label)
    elif stage == 4:
        for event in anim.events:
            if event[1] == "combo_effect" and event[4] == "arena_weather" and event[5] in (
                    "weather_request", "weather", "expire"):
                rows.append((event, f"weather_{event[5]}"))
                if len([row for row in rows if row[1] == "weather_expire"]) >= 1:
                    break
    result = []
    times: list[float] = []
    for event, label in rows[:6]:
        row = compact_event(event)
        row["label"] = label
        result.append(row)
        times.extend([max(0.0, event[0] - .1), min(anim.timeline.duration, event[0] + .2)])
    return result, times[:12]


def replay_state(anim: Any, seconds: float) -> dict[str, Any]:
    view = anim._presentation_view()
    view._ensure(seconds)
    units = {}
    for idx, unit in sorted(view.units.items()):
        units[str(idx)] = {
            "name": unit.u.piece.name,
            "team": unit.u.team,
            "pos": list(unit.u.pos),
            "hp": clean_number(unit.hp),
            "energy": clean_number(unit.energy),
            "statuses": {kind: clean_number(start) for kind, start in unit.statuses.items()},
            "shield": clean_number(unit.shield),
            "shield_until": clean_number(unit.shield_until),
            "wet_until": clean_number(getattr(unit, "wet_until", 0.0)),
            "arena_trait_key": getattr(unit, "arena_trait_key", None),
        }
    return {
        "t": clean_number(seconds),
        "weather": view.weather_name,
        "weather_until": clean_number(view.weather_until),
        "rock_fields": clean_number(view.active_rock_fields),
        "field_statuses": {f"{idx}:{key}": clean_number(start)
                           for (idx, key), start in view.field_statuses.items()},
        "units": units,
    }


def nearby_source_events(anim: Any, seconds: float, radius: float = 1.0) -> list[dict[str, Any]]:
    rows = []
    for index, event in enumerate(anim.events):
        if abs(event[0] - seconds) > radius:
            continue
        if event[1] not in ("status", "field_effect", "combo_effect", "skill_effect", "tactical_effect"):
            continue
        row = compact_event(event)
        row["index"] = index
        rows.append(row)
    return rows


def frame_digest(frame: Image.Image) -> str:
    return sha256_bytes(frame.tobytes())


def save_gif(renderer: Any, path: Path, start: float, end: float) -> dict[str, Any]:
    duration = max(.1, end - start)
    count = max(2, round(duration / .05) + 1)
    frames = [renderer.frame(start + i * .05).resize((720, 480), Image.Resampling.NEAREST)
              for i in range(count)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=50, loop=0,
                   optimize=False)
    return {"path": path.name, "fps": 20, "frame_count": len(frames),
            "start": clean_number(start), "end": clean_number(end)}


def label_on(frame: Image.Image, text: str) -> Image.Image:
    out = frame.copy()
    draw = ImageDraw.Draw(out)
    font = ImageFont.load_default()
    draw.rectangle((0, 0, out.width, 22), fill=(10, 20, 24, 220))
    draw.text((8, 5), text, font=font, fill=(240, 248, 255))
    return out


def make_sheet(frames: list[Image.Image], labels: list[str], path: Path,
               cell=(480, 320), columns=2) -> None:
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell[0], rows * cell[1]), (12, 20, 24))
    font = ImageFont.load_default()
    for index, frame in enumerate(frames):
        im = frame.resize(cell, Image.Resampling.NEAREST)
        x, y = (index % columns) * cell[0], (index // columns) * cell[1]
        sheet.paste(im, (x, y + 24))
        ImageDraw.Draw(sheet).rectangle((x, y, x + cell[0], y + 22), fill=(10, 20, 24))
        ImageDraw.Draw(sheet).text((x + 8, y + 5), labels[index], font=font, fill=(240, 248, 255))
    sheet.save(path)


def reverse_seek(renderer: Any, seconds: float) -> dict[str, Any]:
    times = [max(0.0, seconds - .5), seconds, min(seconds + .5, renderer.anim.timeline.duration),
             seconds, max(0.0, seconds - .5)]
    digests = [frame_digest(renderer.frame(value)) for value in times]
    return {
        "request_times": [clean_number(value) for value in times],
        "frame_sha256": digests,
        "repeated_time_matches": [digests[1] == digests[3], digests[0] == digests[4]],
        "all_repeated_matches": all([digests[1] == digests[3], digests[0] == digests[4]]),
    }


def capture_case(case: dict[str, Any], make_scene: Any, make_renderer: Any,
                 out: Path, variant: str) -> dict[str, Any]:
    stage, label, scenario, seconds = case["stage"], case["label"], case["scenario"], case["t"]
    anim = make_scene(7, scenario)
    renderer = make_renderer(anim, "arena")
    frame = renderer.frame(seconds)
    name = f"{stage:02d}-{label}-actual-{variant}.png"
    frame.save(out / name)
    lifecycle, lifecycle_times = selected_events(anim, stage)
    lifecycle_frames, lifecycle_states = [], []
    for value in lifecycle_times:
        lifecycle_frames.append(renderer.frame(value))
        lifecycle_states.append(replay_state(anim, value))
    if lifecycle_frames:
        labels = [f"{stage}/{label} t={value:.2f}" for value in lifecycle_times]
        make_sheet(lifecycle_frames, labels, out / f"{stage:02d}-{label}-lifecycle-{variant}.png",
                   columns=2)
    gif = save_gif(renderer, out / f"{stage:02d}-{label}-{variant}.gif",
                   max(0.0, seconds - 1.0), min(anim.timeline.duration, seconds + 2.0))
    return {
        "stage": stage,
        "label": label,
        "scenario": scenario,
        "seed": 7,
        "sample_t": seconds,
        "source_event_count": len(anim.events),
        "source_events_sha256": canonical_sha(anim.events),
        "actual_frame": name,
        "actual_frame_sha256": frame_digest(frame),
        "actual_state": replay_state(anim, seconds),
        "nearby_source_events": nearby_source_events(anim, seconds),
        "lifecycle_events": lifecycle,
        "lifecycle_states": lifecycle_states,
        "reverse_seek": reverse_seek(renderer, seconds),
        "gif": gif,
    }


def capture_real_status(case: dict[str, Any], make_scene: Any, make_renderer: Any,
                        out: Path, variant: str) -> dict[str, Any]:
    anim = make_scene(case["seed"], case["scenario"])
    renderer = make_renderer(anim, "arena")
    frame = renderer.frame(case["t"])
    name = f"status-real-{case['status']}-{variant}.png"
    frame.save(out / name)
    return {
        **case,
        "provenance": "actual simulator event; no presentation state injection",
        "source_event_count": len(anim.events),
        "source_events_sha256": canonical_sha(anim.events),
        "actual_state": replay_state(anim, case["t"]),
        "frame": name,
        "frame_sha256": frame_digest(frame),
    }


def capture_diagnostics(make_scene: Any, make_renderer: Any, out: Path,
                        variant: str) -> dict[str, Any]:
    anim = make_scene(7, "arena_showcase")
    renderer = make_renderer(anim, "arena")
    seconds = 3.0
    base_t = 3.0
    frames, rows = [], []
    original = {idx: dict(unit.statuses) for idx, unit in renderer.renderer.view.units.items()}
    for index, status in enumerate(MAJOR_STATUSES):
        idx = 1 + (index % 6)
        unit = renderer.renderer.view.units[idx]
        unit.statuses.clear()
        unit.statuses[status] = base_t
        frame = renderer.frame(seconds)
        name = f"status-diagnostic-{status}-{variant}.png"
        frame.save(out / name)
        frames.append(frame)
        rows.append({"status": status, "unit": idx, "frame": name,
                     "frame_sha256": frame_digest(frame)})
    overflow_idx = 4
    unit = renderer.renderer.view.units[overflow_idx]
    overflow_statuses = dict.fromkeys(("burn", "poison", "sleep", "paralysis", "freeze"), base_t)
    unit.statuses.clear()
    unit.statuses.update(overflow_statuses)
    frame = renderer.frame(seconds)
    name = f"status-diagnostic-overflow-{variant}.png"
    frame.save(out / name)
    rows.append({"status": "overflow", "unit": overflow_idx,
                 "requested_statuses": list(overflow_statuses), "frame": name,
                 "frame_sha256": frame_digest(frame)})
    for idx, statuses in original.items():
        renderer.renderer.view.units[idx].statuses.clear()
        renderer.renderer.view.units[idx].statuses.update(statuses)
    labels = [f"synthetic single: {status}" for status in MAJOR_STATUSES] + ["synthetic meter overflow"]
    make_sheet(frames + [frame], labels, out / f"status-diagnostic-sheet-{variant}.png", columns=2)
    return {
        "base_scenario": "arena_showcase",
        "seed": 7,
        "base_t": base_t,
        "sample_t": seconds,
        "provenance": "diagnostic presentation-only status injection; clearly not a simulator outcome",
        "source_events_sha256": canonical_sha(anim.events),
        "cases": rows,
    }


def capture(out: Path, variant: str, source_root: Path, compare_before: Path | None) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    resolved = configure_imports(source_root)
    make_scene = importlib.import_module("arena_scenarios").make_scene
    presentation = importlib.import_module("presentation_modes")
    make_renderer = presentation.make_renderer
    # Bind evidence to the tree actually imported, including the new status
    # module when the selected renderer uses it. Baseline bytes stay immutable.
    source_paths = {relative: source_root / Path(relative).name for relative in SOURCE_FILES}
    source_paths.update({relative: ROOT / relative for relative in SIM_FILES})
    if "retro_status" in sys.modules:
        resolved["retro_status"] = str(Path(sys.modules["retro_status"].__file__).resolve())
        source_paths["tools/mockups/retro_status.py"] = Path(resolved["retro_status"])
    source_hashes = {relative: sha256_file(path) for relative, path in source_paths.items()}
    module_hashes = {name: sha256_file(Path(path)) for name, path in resolved.items()}
    metadata = {
        "variant": variant,
        "captured_at_unix": time.time(),
        "presentation_revision": presentation.WEB_BATTLE_REVISION,
        "source_root": str(source_root),
        "import_isolation": {
            "resolved_modules": resolved,
            "module_sha256": module_hashes,
            "sim_modules": {name: str(importlib.import_module(name).__file__)
                            for name in ("combat", "data", "roster", "arena", "arena_fields", "arena_weather")},
        },
        "source_sha256": source_hashes,
        "method": {
            "simulation": "fresh fixed-seed Battle per scenario; no saves and no renderer cache",
            "rendering": "direct deterministic PIL frames from the selected source tree",
            "seek_check": "same renderer renders forward, then reverse and repeats two timestamps",
            "diagnostics": "synthetic status injection is separate from actual simulator cases",
        },
        "actual_cases": [],
        "real_status_cases": [],
    }
    contact_frames, contact_labels = [], []
    for case in ACTUAL_CASES:
        began = time.perf_counter()
        row = capture_case(case, make_scene, make_renderer, out, variant)
        row["capture_seconds"] = round(time.perf_counter() - began, 3)
        metadata["actual_cases"].append(row)
        frame = Image.open(out / row["actual_frame"])
        contact_frames.append(frame)
        contact_labels.append(f"stage {case['stage']} {case['label']} t={case['t']:g}")
    make_sheet(contact_frames, contact_labels, out / f"actual-contact-sheet-{variant}.png", columns=2)
    real_frames = []
    for case in REAL_STATUS_CASES:
        row = capture_real_status(case, make_scene, make_renderer, out, variant)
        metadata["real_status_cases"].append(row)
        real_frames.append(Image.open(out / row["frame"]))
    make_sheet(real_frames, [f"real event: {case['status']}" for case in REAL_STATUS_CASES],
               out / f"status-real-contact-sheet-{variant}.png", columns=2)
    metadata["status_diagnostics"] = capture_diagnostics(make_scene, make_renderer, out, variant)
    metadata["output_sha256"] = {
        path.name: sha256_file(path) for path in sorted(out.iterdir())
        if path.is_file() and path.name != "metadata.json"
    }
    if compare_before is not None:
        before_path = compare_before / "metadata.json"
        before = json.loads(before_path.read_text(encoding="utf-8"))
        comparisons = []
        for before_row, after_row in zip(before["actual_cases"], metadata["actual_cases"]):
            assert before_row["scenario"] == after_row["scenario"]
            comparisons.append({
                "stage": before_row["stage"],
                "source_events_sha256_equal": before_row["source_events_sha256"] == after_row["source_events_sha256"],
                "actual_frame_before": before_row["actual_frame_sha256"],
                "actual_frame_after": after_row["actual_frame_sha256"],
                "actual_frame_changed": before_row["actual_frame_sha256"] != after_row["actual_frame_sha256"],
                "all_repeated_reverse_seek_matches": after_row["reverse_seek"]["all_repeated_matches"],
            })
        metadata["before_after"] = {
            "before_metadata": str(before_path),
            "before_revision": before["presentation_revision"],
            "after_revision": metadata["presentation_revision"],
            "actual_cases": comparisons,
            "all_source_event_shas_equal": all(row["source_events_sha256_equal"] for row in comparisons),
        }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", required=True, choices=("before", "after"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT / "tools/mockups")
    parser.add_argument("--compare-before", type=Path)
    args = parser.parse_args()
    result = capture(args.out, args.variant, args.source_root, args.compare_before)
    print(json.dumps({
        "out": str(args.out),
        "variant": args.variant,
        "revision": result["presentation_revision"],
        "actual_cases": [{"stage": row["stage"], "frame": row["actual_frame"],
                          "events_sha": row["source_events_sha256"],
                          "seek_ok": row["reverse_seek"]["all_repeated_matches"]}
                         for row in result["actual_cases"]],
        "real_status_cases": [row["status"] for row in result["real_status_cases"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
