"""Bounded, deterministic previews using the same real-Battle renderer as the game.

Presets describe presentation only. Rendering never writes game rules, saves or
global visual defaults. Cache identities include source and packed asset bytes.
The HTTP adapter serializes rendering with the Demo's shared simulation lock.
"""
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = ROOT / ".build/animation-editor"
MAX_REQUEST_BYTES = 8192
MAX_CACHE_ENTRIES = 24
MAX_CLIP_FRAMES = 100
DT = .05
_LOCK = threading.RLock()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 字段不能重复")
        result[key] = value
    return result


def parse_request(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_REQUEST_BYTES:
        raise ValueError("动画配置必须非空且不超过 8KB")
    def invalid_number(_):
        raise ValueError("动画配置不能含 NaN 或 Infinity")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                          parse_constant=invalid_number)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("动画配置不是有效的 UTF-8 JSON") from exc


def _object(value, allowed, name):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f"{name} 含未知字段或不是对象")


def normalize_preset(value):
    from move_effects import SUPPORTED_SPECIES, normalize_overrides, DEFAULT_VISUAL
    from character_catalog import character_catalog
    from presentation_modes import normalize_mode
    _object(value, ("schema_version", "mode", "species", "settings"), "预设")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("不支持的动画预设版本")
    # Schema 1 predates web arenas: mode-less imported presets remain classic.
    mode = normalize_mode(value.get("mode", "classic"))
    sid = value.get("species")
    characters = character_catalog(mode=mode)
    if type(sid) is not int or str(sid) not in characters:
        raise ValueError("请选择当前上场池中的宝可梦")
    capability = characters[str(sid)]["capabilities"]
    if not capability["resource_ready"]:
        raise ValueError("；".join(capability["resource_errors"]))
    settings = value.get("settings", {})
    _object(settings, ("palette", "effect_scale", "particle_density", "motion_scale"), "动作设置")
    # HTTP contract uses exactly these bounds, independent of Python coercion.
    for key, low, high in (("effect_scale", .7, 1.3),
                           ("particle_density", .5, 1.), ("motion_scale", .5, 1.5)):
        v = settings.get(key, 1.)
        if type(v) not in (int, float) or not low <= v <= high or not math.isfinite(v):
            raise ValueError(f"{key} 必须在 {low}–{high} 之间")
    if settings.get("palette", "classic") not in ("classic", "vivid"):
        raise ValueError("未知色板")
    if mode == "arena":
        from web_battle import normalize_visual_overrides
        normalized = normalize_visual_overrides({sid: settings})[sid]
    elif sid in SUPPORTED_SPECIES:
        normalized = normalize_overrides({sid: settings})[sid]
    else:
        normalized = {**DEFAULT_VISUAL, **settings}
        if normalized != DEFAULT_VISUAL:
            raise ValueError("该角色当前支持默认动作预览，尚未接入表现参数编辑")
    return {"schema_version": 1, "mode": mode, "species": sid, "settings": normalized}


def normalize_preview(value):
    from action_preview import PREVIEW_ACTIONS
    _object(value, ("mode", "species", "kind", "seed", "settings"), "预览请求")
    # New requests default to the playable arena, unlike old imported presets.
    preset = normalize_preset({"schema_version": 1, "mode": value.get("mode", "arena"),
                               "species": value.get("species"),
                               "settings": value.get("settings", {})})
    kind, seed = value.get("kind", "cast"), value.get("seed", 7)
    if not isinstance(kind, str) or kind not in PREVIEW_ACTIONS:
        raise ValueError("不支持的动作预览")
    if type(seed) is not int or not 0 <= seed <= 2**32-1:
        raise ValueError("种子必须为 0–4294967295 的整数")
    return {"mode": preset["mode"], "species": preset["species"], "kind": kind, "seed": seed,
            "settings": preset["settings"]}


def source_revision():
    files = sorted((ROOT / "tools/mockups").glob("*.py"))
    files += sorted((ROOT / "sim").glob("*.py")) + sorted((ROOT / "data").glob("*.json"))
    files += [Path(__file__)]
    files += sorted((ROOT / "esp32_runtime").glob("*.py"))
    # Packed asset provenance must invalidate the cache as well as renderer code.
    from decoders import POKEWALK, GEN2_FRONT
    files += sorted(GEN2_FRONT.rglob("*.png"))
    files += [POKEWALK / name for name in ("gen1_front.bin", "palettes.bin", "font16.bin")]
    digest = hashlib.sha256()
    for path in files:
        identity = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        digest.update(str(identity).encode())
        digest.update(path.read_bytes())
    import data, status, synergy, profiles
    for module in (data, status, synergy, profiles):
        constants = {k: v for k, v in vars(module).items() if k.isupper()
                     and type(v) in (str, int, float, bool, type(None))}
        digest.update(json.dumps(constants, sort_keys=True).encode())
    return digest.hexdigest()


def _key(request, revision):
    payload = json.dumps({"request": request, "revision": revision}, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()[:32]


def _valid_cached(directory):
    if directory.is_symlink() or not directory.is_dir():
        return None
    try:
        meta = json.loads((directory / "meta.json").read_text())
        if not 0 < meta["n"] <= MAX_CLIP_FRAMES:
            return None
        if all((directory / f"{i}.png").is_file() for i in range(meta["n"])):
            return meta
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _render(request, revision):
    from action_preview import describe_clip
    from presentation_modes import make_renderer, mode_info
    mode = request["mode"]
    key = _key(request, revision)
    output = CACHE_ROOT / key
    meta = _valid_cached(output)
    if meta:
        output.touch()
        return key, meta
    from move_effects import SUPPORTED_SPECIES
    overrides = ({request["species"]: request["settings"]} if mode == "arena" or
                 request["species"] in SUPPORTED_SPECIES else None)
    if mode == "arena":
        from arena_preview_scene import make_preview_scene
    else:
        from profile_range import make_preview_scene
    anim = make_preview_scene(request["species"], request["kind"], request["seed"], visual_overrides=overrides)
    clip = describe_clip(anim, request["kind"])
    renderer = make_renderer(anim, mode)
    start, end = clip['clip_start'], clip['clip_end']
    count = round((end-start)/DT)+1
    if not 0 < count <= MAX_CLIP_FRAMES:
        raise ValueError("预览片段超出帧数限制")
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".render-", dir=CACHE_ROOT))
    try:
        milliseconds, particle_peak, track_peak = [], 0, 0
        particle_limit, track_limit, active_peak = 0, 0, 0
        digest = hashlib.sha256()
        for index in range(count):
            tick = time.perf_counter()
            frame = renderer.frame(round(start+index*DT, 6), show_cutins=False).convert("RGB")
            if frame.size != (renderer.width, renderer.height):
                raise ValueError("预览画布尺寸与展示模式不一致")
            milliseconds.append((time.perf_counter()-tick)*1000)
            digest.update(frame.tobytes())
            frame.save(temporary / f"{index}.png")
            metric = renderer.metrics
            particle_peak = max(particle_peak, metric.get("particles", 0))
            track_peak = max(track_peak, metric.get("signature_tracks", 0))
            particle_limit = max(particle_limit, metric.get("particle_limit", 192))
            track_limit = max(track_limit, metric.get("signature_track_limit", 3))
            active_peak = max(active_peak, metric.get("active_actions", 0))
        subject = clip['subject']['unit']
        source_action = None
        if clip['action'] is not None:
            event = anim.events[clip['source_index']]
            move = event[4] if event[1] == 'cast' else None
            source_action = {
                'event_index': clip['source_index'], 'kind': event[1],
                'attacker': event[2], 'target': event[3],
                'move': move, 'move_name': anim.move_zh.get(move, move),
                'targeting': clip.get('targeting','enemy'),
                'native': bool(move and move == anim._native_moves.get(event[2]))}
        native = None
        if mode == "arena":
            from arena_skills import skill_of
            native = skill_of(request["species"])
        meta = {**mode_info(mode), **clip, "n": count, "dt": DT,
                "dimensions": {"width": renderer.width, "height": renderer.height},
                "settings": request["settings"], "revision": revision, "source_revision": revision,
                "native_skill": native, "source_action": source_action,
                "selected_actor": {"unit": 0, "species": request["species"],
                                   "name": anim.by_idx[0].piece.name},
                "fixture": getattr(anim, "preview_fixture", None),
                "frame_sha256": digest.hexdigest(),
                "target_before_impact": anim.presentation_state(clip['snapshot_before'])[subject],
                "target_at_impact": anim.presentation_state(clip['snapshot_at'])[subject],
                "skill_effects": [{"at": ev[0], "kind": ev[1], "arch": ev[4], "effect": ev[5],
                                   "target": anim.by_idx[ev[3]].piece.name, "payload": ev[6]}
                                  for ev in anim.timeline.events
                                  if clip['source_index'] is not None and
                                  ev[1] in ("skill_effect", "field_effect", "combo_effect") and
                                  len(ev) == 7 and isinstance(ev[6], dict) and
                                  any(ev[6].get(owner) == clip['source_index']
                                      for owner in ("cast_index", "source_cast_index", "action_index"))],
                "metrics": {"particle_peak": particle_peak, "signature_track_peak": track_peak,
                            "particle_limit": particle_limit, "signature_track_limit": track_limit,
                            "active_action_peak": active_peak,
                            "particle_scope": "web material decorations; authored motifs bounded by active action limit"
                                              if mode == "arena" else "classic particle budget",
                            "host_frame_ms_p95": round(sorted(milliseconds)[int((count-1)*.95)], 3),
                            "scope": "PC isolated training scene; not ESP32 performance"}}
        meta = json.loads(json.dumps(meta, ensure_ascii=False))
        (temporary / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
        if output.exists() or output.is_symlink():
            if output.is_symlink():
                raise ValueError("预览缓存目录不能是符号链接")
            shutil.rmtree(output)
        temporary.rename(output)
        return key, meta
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _prune(protected):
    candidates = sorted((p for p in CACHE_ROOT.iterdir() if p.is_dir() and
                         not p.is_symlink() and len(p.name) == 32 and
                         all(c in "0123456789abcdef" for c in p.name)),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    keep = set(protected)
    for path in candidates:
        if path.name in keep:
            continue
        if len(keep) < MAX_CACHE_ENTRIES:
            keep.add(path.name)
        else:
            shutil.rmtree(path)


def preview(value):
    request = normalize_preview(value)
    base = normalize_preview({**request, "settings": {}})
    with _LOCK:
        revision = source_revision()
        base_key, key = _key(base, revision), _key(request, revision)
        existed = {k for k in (base_key, key) if (CACHE_ROOT / k).exists()}
        try:
            base_key, baseline = _render(base, revision)
            key, meta = _render(request, revision)
            if any(meta[k] != baseline[k] for k in ('action', 'phases', 'clip_start', 'clip_end', 'n')):
                raise ValueError("视觉设置不应改变动作时间轴")
        except Exception:
            # A failed pair must not accumulate newly published base frames or
            # evict the last successful pair still displayed by the editor.
            for candidate in set((base_key, key)) - existed:
                directory = CACHE_ROOT / candidate
                if directory.is_dir() and not directory.is_symlink():
                    shutil.rmtree(directory)
            raise
        _prune((base_key, key))
        prefix = "/.build/animation-editor/"
        return {"ok": True, **meta, "key": key, "base_key": base_key,
                "frames": [f"{prefix}{key}/{i}.png" for i in range(meta["n"])],
                "base_frames": [f"{prefix}{base_key}/{i}.png" for i in range(baseline["n"])],
                "base_frame_sha256": baseline["frame_sha256"]}
