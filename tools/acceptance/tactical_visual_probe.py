#!/usr/bin/env python3
"""Render tactical presentation fixtures as labeled real-frame evidence.

Requires Pillow, the existing PokemonGo art resources used by the renderer,
and a Chinese font for labels outside the unmodified 240x320 game frame.
This is a presentation probe, not a full expedition or balance simulation.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "reports/evidence/tactics-2026-10-05"
PAPER, INK, MUTED = "#f3f0e7", "#24332f", "#66746f"
MARGIN, HEADER, FOOTER, SCALE = 18, 78, 84, 2


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def label_font(explicit=None):
    candidates = [explicit] if explicit else [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise SystemExit("A Chinese label font is required; pass --font /path/to/font.ttf")


def panel(frame, title, description, seconds, fonts):
    """Only the surrounding caption is added; the game frame stays intact."""
    width, height = frame.width*SCALE, frame.height*SCALE
    image = Image.new("RGB", (width+2*MARGIN, height+HEADER+FOOTER), PAPER)
    draw = ImageDraw.Draw(image)
    draw.text((MARGIN, 12), title, font=fonts[0], fill=INK)
    draw.text((MARGIN, 47), description, font=fonts[1], fill=MUTED)
    image.paste(frame.convert("RGB").resize((width, height), Image.Resampling.NEAREST),
                (MARGIN, HEADER))
    y = HEADER+height+10
    draw.text((MARGIN, y), f"演出时间 {seconds:.2f}s · 原生画面 240×320 / 2×显示",
              font=fonts[2], fill=MUTED)
    draw.text((MARGIN, y+23), "战斗演出样例 · 高生命定向场景",
              font=fonts[2], fill=INK)
    draw.text((MARGIN, y+45), "不代表完整远征或数值配平验收", font=fonts[2], fill=MUTED)
    return image


def load_fixtures():
    path = ROOT / "tests/test_tactical_presentation.py"
    spec = importlib.util.spec_from_file_location("tactical_presentation_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TacticalPresentation.setUpClass()
    fixture = module.TacticalPresentation(
        "test_guard_link_and_hp_arrive_with_the_actual_intercepted_cast")
    return fixture


def tactical_events(animation):
    return [event for event in animation.timeline.events if event[1] == "tactical_effect"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--fps", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.fps <= 30:
        parser.error("fps must be between 1 and 30")
    args.out.mkdir(parents=True, exist_ok=True)
    font_path = label_font(args.font)
    fonts = tuple(ImageFont.truetype(font_path, size) for size in (24, 18, 14))
    fixture = load_fixtures()
    battles = {"guard": fixture.guard(), "weather": fixture.weather(),
               "conflict": fixture.weather(simultaneous=True)}
    original_hashes = {key: digest(battle.events) for key, battle in battles.items()}
    animations = {key: fixture.animation(battle) for key, battle in battles.items()}
    guard_event = next(event for event in tactical_events(animations["guard"])
                       if event[4] == "guard")
    weather_starts = [event for event in tactical_events(animations["weather"])
                      if event[4] == "weather_start"]
    sun_event = next(event for event in weather_starts if event[5]["new_weather"] == "sun")
    rain_event = next(event for event in weather_starts if event[5]["new_weather"] == "rain")
    conflict_event = next(event for event in tactical_events(animations["conflict"])
                          if event[4] == "weather_conflict")
    shots = [
        ("guard", "guard", "01 / 护卫承伤", "隆隆岩替卡比兽承受冲锋主命中", guard_event[0]+.25),
        ("sun", "weather", "02 / 晴天生效", "喷火龙大招后，全场进入晴天窗口", sun_event[0]+.30),
        ("rain-override", "weather", "03 / 雨天覆盖", "后到的求雨覆盖晴天，双方共用天气", rain_event[0]+.30),
        ("weather-conflict", "conflict", "04 / 晴雨冲突", "同一解算 tick 请求相抵，次数均消耗", conflict_event[0]+.30),
    ]
    cards, outputs = [], []
    for name, scene, title, description, seconds in shots:
        frame = animations[scene].playback_frame(seconds)
        card = panel(frame, title, description, seconds, fonts)
        filename = f"visual-{name}.png"
        card.save(args.out / filename)
        cards.append(card)
        outputs.append({"file": filename, "kind": "keyframe", "scene": scene,
                        "presentation_seconds": round(seconds, 6),
                        "native_frame_sha256": hashlib.sha256(frame.tobytes()).hexdigest()})
    gap = 20
    card_width, card_height = cards[0].size
    overview = Image.new("RGB", (2*card_width+3*gap, 2*card_height+3*gap), "#dce1d9")
    for index, card in enumerate(cards):
        overview.paste(card, (gap+(index % 2)*(card_width+gap),
                             gap+(index // 2)*(card_height+gap)))
    overview.save(args.out / "visual-overview.png")
    outputs.append({"file": "visual-overview.png", "kind": "overview"})

    clips = [
        ("guard", "护卫承伤 / 连续演出", "主命中交给护卫，连接线与承伤同步", guard_event[0]+1.),
        ("weather", "先晴后雨 / 连续演出", "先发天气生效，后发天气覆盖；无剪辑", rain_event[0]+1.),
        ("conflict", "晴雨冲突 / 连续演出", "等双方施法演出完成后显示冲突结果", conflict_event[0]+1.),
    ]
    for scene, title, description, until in clips:
        frames = []
        times = [index/args.fps for index in range(math.ceil(until*args.fps)+1)]
        for seconds in times:
            frame = animations[scene].playback_frame(seconds)
            frames.append(panel(frame, title, description, seconds, fonts))
        # One fixed palette avoids per-frame palette flicker in both the native
        # board and external captions; the PNGs remain unquantized references.
        swatches = Image.new("RGB", (frames[0].width, frames[0].height*len(frames)))
        for index, frame in enumerate(frames):
            swatches.paste(frame, (0, frame.height*index))
        palette = swatches.quantize(colors=256)
        indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
        filename = f"visual-{scene}.gif"
        indexed[0].save(args.out / filename, save_all=True, append_images=indexed[1:],
                        duration=round(1000/args.fps), loop=0, disposal=2, optimize=False)
        outputs.append({"file": filename, "kind": "continuous_clip", "scene": scene,
                        "fps": args.fps, "frame_count": len(frames),
                        "presentation_range": [times[0], times[-1]], "playback_speed": 1.})

    for key, battle in battles.items():
        if digest(battle.events) != original_hashes[key]:
            raise AssertionError("Rendering mutated the authoritative battle events")
    for row in outputs:
        file = args.out / row["file"]
        row.update(bytes=file.stat().st_size, sha256=hashlib.sha256(file.read_bytes()).hexdigest())
    sources = ["sim/combat.py", "sim/tactics.py", "sim/weather_control.py",
               "tools/mockups/animation_timeline.py", "tools/mockups/render_battle_gif.py",
               "tools/mockups/render_mockups.py",
               "tests/test_tactical_presentation.py", "tools/acceptance/tactical_visual_probe.py"]
    evidence = {"schema": "tactical-visual-probe-v1", "seed": 42,
                "renderer": "BattleAnimation.playback_frame", "label_font": font_path,
                "sources_sha256": {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
                                   for path in sources},
                "scenes": {key: {"authoritative_event_sha256": original_hashes[key],
                                  "authoritative_events": battle.events,
                                  "presentation_tactical_events": tactical_events(animations[key]),
                                  "presentation_duration": animations[key].presentation_duration}
                           for key, battle in battles.items()},
                "outputs": outputs,
                "limits": ["Real renderer frames from high-HP, manually staged combat fixtures; not a full expedition.",
                           "Fixture positions and energy are staged by the existing presentation regression tests.",
                           "The renderer HUD is its default sample data, not this fixture's economic game state.",
                           "Captions are outside the intact native frame; GIFs use a fixed 256-color palette.",
                           "Weather clip ends after rain starts; expiry is tested elsewhere and not shown in this short clip.",
                           "No balance, hardware performance, complete mode or asset-quality acceptance claim."]}
    (args.out / "visual-metadata.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"output": str(args.out), "files": [row["file"] for row in outputs],
                      "authoritative_events_unchanged": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
