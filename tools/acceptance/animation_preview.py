"""Bounded, deterministic previews using the same real-Battle renderer as the game.

Presets describe presentation only. Rendering never writes game rules, saves or
global visual defaults. Cache identities include source and packed asset bytes.
The HTTP adapter serializes rendering with the Demo's shared simulation lock.
"""
from dataclasses import asdict
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
    _object(value, ("schema_version", "species", "settings"), "预设")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("不支持的动画预设版本")
    sid = value.get("species")
    characters = character_catalog()
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
    if sid in SUPPORTED_SPECIES:
        normalized = normalize_overrides({sid: settings})[sid]
    else:
        normalized = {**DEFAULT_VISUAL, **settings}
        if normalized != DEFAULT_VISUAL:
            raise ValueError("该角色当前支持默认动作预览，尚未接入表现参数编辑")
    return {"schema_version": 1, "species": sid, "settings": normalized}


def normalize_preview(value):
    _object(value, ("species", "kind", "seed", "settings"), "预览请求")
    preset = normalize_preset({"schema_version": 1, "species": value.get("species"),
                               "settings": value.get("settings", {})})
    kind, seed = value.get("kind", "cast"), value.get("seed", 7)
    if kind not in ("attack", "cast"):
        raise ValueError("只支持普攻或大招预览")
    if type(seed) is not int or not 0 <= seed <= 2**32-1:
        raise ValueError("种子必须为 0–4294967295 的整数")
    return {"species": preset["species"], "kind": kind, "seed": seed,
            "settings": preset["settings"]}


def source_revision():
    files = sorted((ROOT / "tools/mockups").glob("*.py"))
    files += sorted((ROOT / "sim").glob("*.py")) + sorted((ROOT / "data").glob("*.json"))
    files += [Path(__file__)]
    # Packed asset provenance must invalidate the cache as well as renderer code.
    from decoders import POKEWALK
    files += [POKEWALK / name for name in ("gen1_front.bin", "palettes.bin", "font16.bin")]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode())
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
    from profile_range import make_preview_scene
    key = _key(request, revision)
    output = CACHE_ROOT / key
    meta = _valid_cached(output)
    if meta:
        output.touch()
        return key, meta
    from move_effects import SUPPORTED_SPECIES
    overrides = {request["species"]: request["settings"]} if request["species"] in SUPPORTED_SPECIES else None
    anim = make_preview_scene(request["species"], request["kind"], request["seed"], visual_overrides=overrides)
    actions = [a for a in anim.timeline.actions if a.attacker == 0 and
               a.kind == request["kind"] and not a.secondary]
    damage_index = 6 if request["kind"] == "cast" else 4
    action = next((a for a in actions if anim.events[a.source_index][damage_index] > 0),
                  actions[0] if actions else None)
    if action is None:
        raise ValueError("本种子没有产生可预览动作")
    start, end = max(0., action.start-.25), max(action.impact+.95, action.recover_end+.25)
    count = round((end-start)/DT)+1
    if not 0 < count <= MAX_CLIP_FRAMES:
        raise ValueError("预览片段超出帧数限制")
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".render-", dir=CACHE_ROOT))
    try:
        milliseconds, particle_peak, track_peak = [], 0, 0
        digest = hashlib.sha256()
        for index in range(count):
            tick = time.perf_counter()
            frame = anim.playback_frame(round(start+index*DT, 6), show_cutins=False).convert("RGB")
            milliseconds.append((time.perf_counter()-tick)*1000)
            digest.update(frame.tobytes())
            frame.save(temporary / f"{index}.png")
            metric = anim._presentation_view().last_frame_metrics
            particle_peak = max(particle_peak, metric["particles"])
            track_peak = max(track_peak, metric["signature_tracks"])
        meta = {"n": count, "dt": DT, "clip_start": start, "action": asdict(action),
                "settings": request["settings"], "revision": revision,
                "frame_sha256": digest.hexdigest(),
                "target_before_impact": anim.presentation_state(action.impact-.001)[action.target],
                "target_at_impact": anim.presentation_state(action.impact)[action.target],
                "training_scene": "precharged_skill" if request["kind"] == "cast" else "stationary_posts",
                "skill_effects": [{"at": ev[0], "effect": ev[5],
                                   "target": anim.by_idx[ev[3]].piece.name, "payload": ev[6]}
                                  for ev in anim.timeline.events if ev[1] == "skill_effect"
                                  and ev[6]["cast_index"] == action.source_index],
                "metrics": {"particle_peak": particle_peak, "signature_track_peak": track_peak,
                            "particle_limit": 192, "signature_track_limit": 3,
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
            if meta["action"] != baseline["action"] or meta["n"] != baseline["n"]:
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
