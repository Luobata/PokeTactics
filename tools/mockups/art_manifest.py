#!/usr/bin/env python3
"""Export/validate portable art references and motion tables; never copy assets.

The manifest is deterministic: it contains no wall clock, absolute paths or
machine-dependent timing. Optional PC measurements are separately hashed input.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import importlib
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SCHEMA_VERSION = 1
STATES = ("idle", "walk", "windup", "strike", "recover", "hit", "death")
SOURCE_FILES = (
    "tools/mockups/art_manifest.py",
    "tools/mockups/decoders.py", "tools/mockups/motion.py",
    "tools/mockups/animation_timeline.py", "tools/mockups/render_battle_gif.py",
    "tools/mockups/render_mockups.py", "tools/mockups/skill_vfx.py",
    "tools/mockups/profile_vfx.py", "tools/mockups/pixel_vfx.py",
    "tools/mockups/move_effects.py",
    "tools/mockups/character_rigs.py", "tools/mockups/character_catalog.py",
    "tools/mockups/action_preview.py", "esp32_runtime/animation.py",
    "sim/data.py", "sim/roster.py", "sim/profiles.py", "sim/skills.py",
    "sim/combat.py", "sim/status.py", "data/pokemon.json", "data/moves.json", "data/typechart.json",
)


class ManifestError(ValueError):
    pass


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_revision(manifest):
    return hashlib.sha256(canonical_bytes({k: v for k, v in manifest.items()
                                          if k != "revision"})).hexdigest()


def _file(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ManifestError("resource path must be relative")
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ManifestError("resource path escapes its logical root")
    try:
        return target.read_bytes()
    except OSError as exc:
        raise ManifestError(f"missing/unreadable resource {relative}: {exc}") from exc


def _reference(root, relative, root_key):
    data = _file(root, relative)
    return {"root": root_key, "path": relative, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def _unpack(fmt, data, offset=0):
    try:
        return struct.unpack_from(fmt, data, offset)
    except struct.error as exc:
        raise ManifestError("truncated binary resource") from exc


def _front(data):
    magic, version, segments = _unpack("<4sHH", data)
    if magic != b"FRNT" or version != 1 or not 1 <= segments <= 3:
        raise ManifestError("unsupported FRNT header")
    payload_start = 8 + segments * 12
    atlas, segment_info, occupied = {}, [], []
    for index in range(segments):
        size, per, count, offset = _unpack("<HHII", data, 8 + index * 12)
        if size not in (40, 48, 56) or per != size * size // 4 or not count:
            raise ManifestError("invalid FRNT segment")
        start, end = payload_start + offset, payload_start + offset + count * (per + 2)
        if end > len(data) or any(start < right and end > left for left, right in occupied):
            raise ManifestError("overlapping/truncated FRNT segment")
        occupied.append((start, end))
        segment_info.append({"width": size, "height": size, "count": count,
                             "record_pixel_bytes": per})
        for record in range(count):
            base = start + record * (per + 2)
            sid, = _unpack("<H", data, base)
            key = f"front/{sid}"
            if not 1 <= sid <= 65535 or key in atlas:
                raise ManifestError("invalid/duplicate FRNT species")
            blob = data[base + 2:base + 2 + per]
            atlas[key] = {"asset": "front", "species_id": sid, "offset": base + 2,
                          "bytes": per, "width": size, "height": size,
                          "sha256": hashlib.sha256(blob).hexdigest()}
    if max(right for _, right in occupied) != len(data):
        raise ManifestError("unexpected FRNT trailing bytes")
    return {"format": "FRNT-v1", "encoding": "2bpp-row-major-msb-first",
            "transparent_index": 3, "palette_asset": "palettes",
            "record_count": len(atlas), "segments": segment_info}, atlas


def _palettes(data):
    magic, version, sets, colors, count = _unpack("<4sHHHH", data)
    if magic != b"PALS" or version != 1 or colors != 4 or not 1 <= sets <= 256:
        raise ManifestError("unsupported PALS header")
    mapping_start = 12 + 2 * sets * colors * 2
    if len(data) != mapping_start + count or not count:
        raise ManifestError("invalid PALS length")
    mapping = list(data[mapping_start:])
    if any(index >= sets for index in mapping):
        raise ManifestError("PALS references a missing palette")
    return {"format": "PALS-v1", "encoding": "RGB565-little-endian",
            "colors_per_set": colors, "normal_sets": sets, "shiny_sets": sets,
            "species_count": count}, mapping


def _font(data):
    magic, version, size, per, count = _unpack("<4sHHHI", data)
    if magic != b"FNT1" or version != 1 or size != 16 or per != 32:
        raise ManifestError("unsupported FNT1 header")
    if len(data) != 14 + count * (2 + per):
        raise ManifestError("invalid FNT1 length")
    codepoints = [_unpack("<H", data, 14 + i * 2)[0] for i in range(count)]
    if len(set(codepoints)) != count:
        raise ManifestError("duplicate font codepoint")
    return {"format": "FNT1-v1", "encoding": "1bpp-row-major-msb-first",
            "width": size, "height": size, "glyph_bytes": per,
            "glyph_count": count, "codepoint_encoding": "uint16-le"}


def _modules():
    for path in (str(ROOT / "sim"), str(HERE)):
        if path not in sys.path:
            sys.path.insert(0, path)
    return {name: importlib.import_module(name) for name in (
        "decoders", "motion", "animation_timeline", "render_battle_gif",
        "render_mockups", "skill_vfx", "move_effects", "character_rigs", "character_catalog",
        "profiles", "skills", "roster", "data")}


def _motion_clips(motion):
    clips, rigs = {}, {}
    for sid, states in sorted(motion.species_motion.items()):
        if set(states) != set(STATES):
            raise ManifestError(f"incomplete authored motion set: {sid}")
        for name in STATES:
            frames = [list(frame) for frame in states[name]]
            if any(len(frame) != 6 or any(type(v) is not int for v in frame) for frame in frames):
                raise ManifestError(f"non-integer motion frame: {sid}/{name}")
            phase = [Fraction(str(value)).limit_denominator(1024)
                     for value in motion.RIG_PHASES[sid][name]]
            key = f"motion.{sid}.{name}"
            body_frames, hit_frames = [], []
            for index, frame in enumerate(states[name]):
                body = motion.presentation_pose(sid, motion.Pose(name, index, frame))
                hit = motion.presentation_pose(sid, motion.Pose("idle", 0, motion.REST, hit=frame))
                body_frames.append(list(body.frame))
                hit_frames.append(list(hit.hit))
            clips[key] = {"kind": "integer_pose_table", "species_id": sid, "state": name,
                          "sample_ms": round(motion.frame_dt(name) * 1000),
                          "loop": name in ("idle", "walk"), "frames": frames,
                          "presentation_frames": hit_frames if name == "hit" else body_frames,
                          "rig_phase": [[v.numerator, v.denominator] for v in phase],
                          "source": "tools/mockups/motion.py"}
        rigs[str(sid)] = [{"bounds_percent": list(region[:4]),
                           "dx_px": list(region[4]), "dy_px": list(region[5])}
                          for region in motion.RIGS.get(sid, ())]
    for name in ("gait", "attack", "hit", "death"):
        clips[f"fallback.{name}"] = {"kind": "procedural_python", "frames_exported": False,
                                     "source": "tools/mockups/render_battle_gif.py"}
    return clips, rigs


def build_manifest(*, asset_root=None, pc_metrics=None):
    modules = _modules()
    asset_root = Path(asset_root) if asset_root is not None else modules["decoders"].POKEWALK
    motion, visual, profiles, skills = (modules[name] for name in ("motion", "skill_vfx", "profiles", "skills"))
    renderer, timeline, layout = (modules[name] for name in ("render_battle_gif", "animation_timeline", "render_mockups"))
    dex = modules["data"].pokedex()
    meta_front, atlas = _front(_file(asset_root, "gen1_front.bin"))
    meta_palette, palette_map = _palettes(_file(asset_root, "palettes.bin"))
    meta_font = _font(_file(asset_root, "font16.bin"))
    assets = {
        key: {**_reference(asset_root, filename, "pokewalk_assets"), **meta}
        for key, filename, meta in (("front", "gen1_front.bin", meta_front),
                                    ("palettes", "palettes.bin", meta_palette),
                                    ("font16", "font16.bin", meta_font))
    }
    for entry in atlas.values():
        if entry["species_id"] > len(palette_map):
            raise ManifestError("front sprite has no palette mapping")
        entry["palette_index"] = palette_map[entry["species_id"] - 1]
    provenance = json.loads(_file(asset_root, "pokemon_art_sources.json"))
    clips, rigs = _motion_clips(motion)
    character_rigs = modules["character_rigs"].manifest_data()
    characters = modules["character_catalog"].character_catalog(asset_root=asset_root)
    for arch in visual.ARCHS:
        clips[f"vfx.{arch}"] = {"kind": "procedural_python", "frames_exported": False,
                                "source": "tools/mockups/skill_vfx.py", "archetype": arch}
    for sid, (move_id, label, design) in sorted(visual.AUTHORED_SKILLS.items()):
        clips[f"vfx.{sid}.{move_id}"] = {"kind": "procedural_python", "frames_exported": False,
                                        "source": "tools/mockups/skill_vfx.py", "design": design,
                                        "label": label, "species_id": sid, "move_id": move_id}
    core_effects = modules["move_effects"].SUPPORTED_SPECIES
    effect_module = modules["move_effects"]
    effect_cels = {family: {"pixels": [list(rows) for rows in frames],
                             "transparent_index": 0,
                             "palettes_rgb888": {
                                 "classic": [list(rgb) for rgb in effect_module.PALETTES[family][0]],
                                 "vivid": [list(rgb) for rgb in effect_module.PALETTES[family][1]]}}
                   for family, frames in effect_module.CELS.items()}
    for sid in core_effects:
        clips[f"vfx.core.{sid}"] = {"kind": "procedural_python", "frames_exported": False,
                                    "source": "tools/mockups/move_effects.py", "species_id": sid,
                                    "phases": ["charge", "flight", "impact", "aftermath"]}
    roster = {p.species_id: p for group in modules["roster"].build_roster().values() for p in group}
    actors = {}
    for sid, piece in sorted(roster.items()):
        profile, skill = profiles.get(sid), skills.skill_of(sid)
        character = characters[str(sid)]
        if not character["capabilities"]["resource_ready"]:
            raise ManifestError("; ".join(character["capabilities"]["resource_errors"]))
        authored = sid in motion.species_motion
        body = ({name: f"motion.{sid}.{name}" for name in STATES} if authored else
                {name: f"fallback.{name}" for name in ("gait", "attack", "hit", "death")})
        has_move = skills.resolve_cast(piece) is not None
        special = visual.AUTHORED_SKILLS.get(sid)
        vfx_key = (f"vfx.core.{sid}" if sid in core_effects and has_move else
                   f"vfx.{sid}.{piece.move_id}" if special and special[0] == piece.move_id
                   else f"vfx.{skill['arch']}" if skill and has_move else None)
        actors[f"species.{sid}"] = {
            "species_id": sid, "name": piece.name,
            "role_key": f"signature.{sid}" if profile else "ranged" if piece.distance > 1 else "melee",
            "role_label": profile["role"] if profile else ("远程" if piece.distance > 1 else "近战"),
            "character": characters.get(str(sid)),
            "atlas_key": f"front/{sid}", "palette_asset": "palettes",
            "animations": body, "authored_motion": authored,
            "skill": {"move_id": piece.move_id, "can_cast": has_move,
                      "tier": skill["tier"] if skill and has_move else None,
                      "archetype": skill["arch"] if skill and has_move else None,
                      "animation_key": vfx_key, "authored_visual": bool(has_move and special and special[0] == piece.move_id)},
        }
    inputs = [_reference(ROOT, name, "project") for name in SOURCE_FILES]
    inputs.append(_reference(asset_root, "pokemon_art_sources.json", "pokewalk_assets"))
    total_asset_bytes = sum(entry["bytes"] for entry in assets.values())
    measured = {"asset_inventory": {"status": "measured_from_files", "total_bytes": total_asset_bytes},
                "pc_render": {"status": "not_measured", "frame_time_ms": None, "peak_rss_bytes": None},
                "esp32": {"status": "pending_port_and_device_measurement"}}
    if pc_metrics is not None:
        raw = Path(pc_metrics).read_bytes()
        evidence = json.loads(raw)
        if type(evidence) is not dict:
            raise ManifestError("PC metrics must be an object")
        measured["pc_render"] = {"status": "supplied_evidence_not_remeasured",
                                  "evidence_sha256": hashlib.sha256(raw).hexdigest(),
                                  "embedded_evidence_sha256": hashlib.sha256(canonical_bytes(evidence)).hexdigest(),
                                  "evidence": evidence}
    manifest = {
        "schema_version": SCHEMA_VERSION, "game_id": "poketactics",
        "logical_roots": {"project": ".", "pokewalk_assets": "../ESP32-PokemonGo/assets"},
        "provenance": {"art": {key: provenance.get(key) for key in ("repository", "commit", "source_mode", "palette_rule")},
                       "art_ownership": "Original Pokemon sprite/palette material referenced through PokeWalk; not original PokeTactics artwork.",
                       "font": {"source": "PokeWalk assets/font16.bin", "upstream_font_identity": "not recorded by this binary; requires provenance verification before redistribution"},
                       "motion": "PokeTactics authored pose tables and procedural effects around referenced source sprites"},
        "inputs": inputs, "assets": assets, "atlas": atlas,
        "animation_data": {"frame_fields": ["forward_px", "down_px", "scale_x_percent", "scale_y_percent", "clockwise_degrees", "dissolve_quarters"],
                           "clips": clips, "rigs": rigs, "character_rigs": character_rigs, "effect_cels": effect_cels,
                           "visual_defaults": dict(effect_module.DEFAULT_VISUAL),
                           "portable_status": "integer pose/rig data and indexed effect cels exported; effect choreography and raster transform remain Python"},
        "actors": actors,
        "coverage": {"roster_species": len(actors), "atlas_species": len(atlas),
                     "layered_core_visual_species": sorted(core_effects),
                     "part_rig_species": sorted(int(sid) for sid, rig in character_rigs["species"].items() if rig["implemented"]),
                     "planned_part_rig_species": sorted(int(sid) for sid, rig in character_rigs["species"].items() if not rig["implemented"]),
                     "authored_motion_species": sum(a["authored_motion"] for a in actors.values()),
                     "authored_skill_visual_species": sum(a["skill"]["authored_visual"] for a in actors.values()),
                     "gameplay_signature_species": sum(a["skill"]["tier"] == "signature" for a in actors.values()),
                     "gameplay_generic_species": sum(a["skill"]["tier"] == "generic" for a in actors.values()),
                     "no_cast_species": [a["species_id"] for a in actors.values() if not a["skill"]["can_cast"]]},
        "clock": {"portable_unit": "integer_milliseconds", "python_event_unit": "seconds_float",
                  "presentation_grid_ms": round(timeline.GRID * 1000),
                  "idle_sample_ms": round(motion.frame_dt("idle") * 1000),
                  "action_sample_ms": round(motion.frame_dt("strike") * 1000),
                  "effect_sample_ms": round(renderer.FPS_DT * 1000),
                  "sampling": "floor(age_ms/sample_ms); loop idle/walk, clamp other clips",
                  "pose_rounding": "Python round ties-to-even; exported integer frames are authoritative",
                  "speed": "AnimationTimeline.time applies speed once; skip maps to duration",
                  "event_contract": "internal action timestamps=start; public damage log timestamps=impact; states/status/death follow causal schedule"},
        "coordinates": {"canvas_px": [layout.W, layout.H], "origin": "top-left", "x_positive": "right", "y_positive": "down",
                        "sim_grid_cells": [6, 4], "render_grid_cells": [renderer.BCOLS, renderer.BROWS],
                        "cell_px": renderer.BCELL, "board_origin_px": [renderer.BX, renderer.BY],
                        "sim_to_render_row_offset": renderer.VIS_ROW_OFF, "foot_offset_px": layout.BOARD_FOOT,
                        "sampling": "nearest-neighbor", "atlas_kind": "packed binary records; no generated texture sheet"},
        "budget": {"configured_pc_contract": {"particles_per_frame": renderer.PARTICLE_LIMIT,
                   "active_signature_tracks": timeline.MAX_ACTIVE_SIGNATURES,
                   "cutins_per_battle": timeline.MAX_CUTINS,
                   "max_travel_ms": round(timeline.MAX_TRAVEL * 1000),
                   "cutin_ms": round(timeline.CUTIN_DURATION * 1000),
                   "end_hold_ms": round(timeline.END_HOLD * 1000)},
                   "derived_storage_estimates": {"packed_resource_bytes": total_asset_bytes,
                   "one_rgba_canvas_bytes": layout.W * layout.H * 4,
                   "one_rgb565_canvas_bytes": layout.W * layout.H * 2,
                   "note": "Arithmetic size only; excludes Python/Pillow objects, caches, temporary layers and device buffers."},
                   "measurements": measured},
        "port_status": {"resource_decode": "PC implemented", "motion_tables": "exported; C sampler pending",
                        "event_scheduler": "Python reference implemented; C integer clock pending",
                        "draw_backend": "Pillow implemented; ESP32 blitter/cache/partial-refresh pending"},
    }
    manifest["revision"] = content_revision(manifest)
    validate_manifest(manifest, asset_root=asset_root)
    return manifest


def validate_manifest(manifest, *, asset_root=None):
    """Check actual files, packed ranges and all actor animation references."""
    if (manifest.get("schema_version") != SCHEMA_VERSION
            or not isinstance(manifest.get("game_id"), str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", manifest["game_id"])):
        raise ManifestError("unsupported manifest schema/game")
    asset_root = Path(asset_root) if asset_root is not None else ROOT.parent / "ESP32-PokemonGo" / "assets"
    roots = {"project": ROOT, "pokewalk_assets": asset_root}
    blobs = {}
    if set(manifest["assets"]) != {"front", "palettes", "font16"}:
        raise ManifestError("missing required binary asset")
    for key, reference in list(manifest["assets"].items()) + [(None, ref) for ref in manifest["inputs"]]:
        if reference["root"] not in roots:
            raise ManifestError("unknown logical resource root")
        blob = _file(roots[reference["root"]], reference["path"])
        if len(blob) != reference["bytes"] or hashlib.sha256(blob).hexdigest() != reference["sha256"]:
            raise ManifestError(f"resource size/hash mismatch: {reference['path']}")
        if key is not None:
            blobs[key] = blob
    front_info, expected_atlas = _front(blobs["front"])
    palette_info, palette_map = _palettes(blobs["palettes"])
    font_info = _font(blobs["font16"])
    for key, expected in (("front", front_info), ("palettes", palette_info), ("font16", font_info)):
        if any(manifest["assets"][key].get(field) != value for field, value in expected.items()):
            raise ManifestError(f"binary format metadata mismatch: {key}")
    for entry in expected_atlas.values():
        if entry["species_id"] > len(palette_map):
            raise ManifestError("front sprite has no palette mapping")
        entry["palette_index"] = palette_map[entry["species_id"] - 1]
    if manifest["atlas"] != expected_atlas:
        raise ManifestError("atlas records do not match the packed binary")
    for key, entry in manifest["atlas"].items():
        if entry["asset"] not in blobs:
            raise ManifestError(f"missing atlas asset: {key}")
        blob = blobs[entry["asset"]]
        start, size = entry["offset"], entry["bytes"]
        if (type(start) is not int or type(size) is not int or start < 0 or size < 1
                or start + size > len(blob) or hashlib.sha256(blob[start:start + size]).hexdigest() != entry["sha256"]):
            raise ManifestError(f"invalid atlas record: {key}")
    clips = manifest["animation_data"]["clips"]
    modules = _modules()
    expected_rigs = modules["character_rigs"].manifest_data()
    if manifest["animation_data"].get("character_rigs") != expected_rigs:
        raise ManifestError("character rigs do not match implementation")
    for label, enabled in (("part_rig_species", True), ("planned_part_rig_species", False)):
        expected = sorted(int(sid) for sid, rig in expected_rigs["species"].items() if rig["implemented"] == enabled)
        if manifest["coverage"].get(label) != expected:
            raise ManifestError("character rig coverage does not match implementation")
    expected_cels = modules["move_effects"].CELS
    actual_cels = manifest["animation_data"].get("effect_cels", {})
    if set(actual_cels) != set(expected_cels):
        raise ManifestError("effect cel families do not match implementation")
    for family, frames in expected_cels.items():
        entry = actual_cels[family]
        palettes = modules["move_effects"].PALETTES[family]
        if (entry["pixels"] != [list(rows) for rows in frames] or entry["transparent_index"] != 0
                or entry["palettes_rgb888"] != {"classic": [list(rgb) for rgb in palettes[0]],
                                                "vivid": [list(rgb) for rgb in palettes[1]]}):
            raise ManifestError("effect cels or palette do not match implementation")
    expected_keys = {f"motion.{sid}.{name}" for sid in modules["motion"].species_motion for name in STATES}
    expected_keys.update(f"fallback.{name}" for name in ("gait", "attack", "hit", "death"))
    expected_keys.update(f"vfx.{arch}" for arch in modules["skill_vfx"].ARCHS)
    expected_keys.update(f"vfx.{sid}.{value[0]}" for sid, value in modules["skill_vfx"].AUTHORED_SKILLS.items())
    expected_keys.update(f"vfx.core.{sid}" for sid in modules["move_effects"].SUPPORTED_SPECIES)
    if set(clips) != expected_keys:
        raise ManifestError("animation catalog does not match implemented keys")
    source_paths = {ref["path"] for ref in manifest["inputs"] if ref["root"] == "project"}
    for key, clip in clips.items():
        if clip["source"] not in source_paths:
            raise ManifestError(f"missing animation implementation source: {key}")
        if clip["kind"] == "integer_pose_table":
            if (not clip["frames"] or len(clip["frames"]) != len(clip["rig_phase"])
                    or len(clip["frames"]) != len(clip["presentation_frames"])
                    or type(clip["sample_ms"]) is not int or clip["sample_ms"] <= 0):
                raise ManifestError(f"invalid animation samples: {key}")
            for frame in clip["frames"] + clip["presentation_frames"]:
                if len(frame) != 6 or any(type(value) is not int for value in frame):
                    raise ManifestError(f"invalid integer animation frame: {key}")
            if any(len(phase) != 2 or type(phase[0]) is not int or type(phase[1]) is not int or phase[1] <= 0 for phase in clip["rig_phase"]):
                raise ManifestError(f"invalid rig phase: {key}")
    expected_characters = modules["character_catalog"].character_catalog(asset_root=asset_root)
    for key, actor in manifest["actors"].items():
        character = expected_characters.get(str(actor["species_id"]))
        if actor.get("character") != character or character is None:
            raise ManifestError(f"actor capability does not match implementation: {key}")
        if actor["skill"]["can_cast"] != character["skill"]["can_cast"]:
            raise ManifestError(f"actor cast capability mismatch: {key}")
        if actor["atlas_key"] not in manifest["atlas"] or actor["palette_asset"] not in blobs:
            raise ManifestError(f"missing actor asset: {key}")
        references = list(actor["animations"].values()) + [actor["skill"]["animation_key"]]
        for animation in references:
            if animation is not None and animation not in clips:
                raise ManifestError(f"missing animation reference: {key} -> {animation}")
    if manifest.get("revision") != content_revision(manifest):
        raise ManifestError("manifest revision does not match content")
    measured = manifest["budget"]["measurements"]["pc_render"]
    if "evidence" in measured and hashlib.sha256(canonical_bytes(measured["evidence"])).hexdigest() != measured["embedded_evidence_sha256"]:
        raise ManifestError("embedded PC evidence checksum mismatch")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".build/animation-b/art-manifest.json")
    parser.add_argument("--asset-root", type=Path, help="Resolve logical pokewalk_assets root without copying files")
    parser.add_argument("--pc-metrics", type=Path, help="Optional measured PC evidence JSON; kept separate from configuration")
    parser.add_argument("--verify", type=Path, help="Validate an existing manifest against files and references")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            validate_manifest(json.loads(args.verify.read_text()), asset_root=args.asset_root)
            print(f"PASS {args.verify}")
            return 0
        manifest = build_manifest(asset_root=args.asset_root, pc_metrics=args.pc_metrics)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_bytes(manifest) + b"\n")
        print(json.dumps({"output": str(args.output), "revision": manifest["revision"],
                          "resource_bytes": manifest["budget"]["measurements"]["asset_inventory"]["total_bytes"],
                          "coverage": manifest["coverage"]}, ensure_ascii=False))
        return 0
    except (ManifestError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL art manifest: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
