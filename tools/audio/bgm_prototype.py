#!/usr/bin/env python3
"""BGM 环节样带渲染器（docs/08 §3 落地样张，零第三方依赖）。

用途：把「各环节 BGM」设计做成**可试听**的证据——
1. 解析 PokeWalk firmware/main/music_assets.h 的 17 首金银音序
   （{frames, midi, volume, duty, envelope} × 4 声部，GB 定点帧时长）；
2. 在 PC 上复刻 firmware music.c 的四声道渲染（方波占空比四档 /
   波表三角 / LFSR 噪声 / 线性包络），与固件逐样本同构；
3. 按 docs/08 §3.1+§3.2 的 cue 表拼「一局时间线样带」：
   菜单 → 准备 → 开战横幅（duck）→ 常规战斗（大招 duck 演示）
   → 胜利结算 → 决赛圈 → 终局名次，外加各单曲节选。

输出 reports/evidence/bgm-2026-09-14/*.wav（22050Hz mono PCM16）。

用法：python3 tools/audio/bgm_prototype.py [--pokewalk 路径]
"""

import argparse
import math
import re
import struct
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SR = 22050
# GB 定点换算（music.c 同款）：samples = frames·70224·SR/4194304
FRAME_SAMPLES = 70224 * SR / 4194304


# ---------------------------------------------------------------- 解析 C 资产
def parse_music_assets(path: Path):
    """music_assets.h → (scores, arrays)。scores = [(name, [track…])…]，
    track = (channel, loop, notes)；notes = [(frames, midi, vol, duty, env)…]。
    MUSIC_SCORES 的 track 引用（MUSIC_TRACK_n）在此展开为实体。"""
    src = path.read_text()
    notes_arrays = {}          # 名 -> [(frames, midi, vol, duty, env), ...]
    for m in re.finditer(
            r"static const music_note_t (MUSIC_\d+_\d+)\[\]\s*=\s*\{(.*?)\};",
            src, re.S):
        rows = []
        for row in re.findall(r"\{(\d+),(-?\d+),(\d+),(\d+),(-?\d+)\}", m.group(2)):
            rows.append(tuple(int(x) for x in row))
        notes_arrays[m.group(1)] = rows
    track_arrays = {}          # 名 -> (channel, loop, notes)
    for m in re.finditer(
            r"static const music_track_t (MUSIC_TRACK_\d+)\[\]\s*=\s*\{(.*?)\};",
            src, re.S):
        body = m.group(2)
        entries = []
        for em in re.finditer(
                r"\{\s*(MUSIC_\d+_\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\}", body):
            entries.append({"notes": notes_arrays[em.group(1)],
                            "count": int(em.group(2)),
                            "loop": int(em.group(3)),
                            "channel": int(em.group(4))})
        track_arrays[m.group(1)] = entries
    scores = {}
    m = re.search(r"music_score_t MUSIC_SCORES\[\]\s*=\s*\{(.*?)\n\};", src, re.S)
    for sm in re.finditer(r'\{\s*"(\w+)",\s*(MUSIC_TRACK_\d+),[^}]*\}',
                          m.group(1)):
        scores[sm.group(1)] = track_arrays[sm.group(2)]
    return scores


# ---------------------------------------------------------------- 四声道渲染
class Voice:
    """一个声部的逐样本状态（music.c voice_sample 的 Python 直译）。"""

    def __init__(self, track):
        self.t = track
        self.note_i = 0
        self.pos_in_note = 0
        self.length = 0
        self.remainder = 0.0
        self.phase = 0.0
        self.noise = 0x7fff

    def hz(self, midi: int) -> float:
        return 440.0 * 2 ** ((midi - 69) / 12)

    def sample(self) -> int:
        t = self.t
        notes = t["notes"]
        if self.length and self.pos_in_note >= self.length:
            self.note_i += 1
            self.pos_in_note = 0
            self.length = 0
        if self.note_i >= t["count"]:
            if t["loop"] >= t["count"]:
                return 0
            self.note_i = t["loop"]
        n = notes[self.note_i]
        if not self.length:
            samples = n[0] * FRAME_SAMPLES + self.remainder
            self.length = int(samples)
            self.remainder = samples - self.length
            self.increment = (0 if n[1] < 0 else
                              self.hz(n[1]) / SR)
        position = self.pos_in_note
        self.pos_in_note += 1
        if n[1] < 0:
            return 0
        old = self.phase
        self.phase += self.increment
        if self.phase >= 1.0:
            self.phase -= int(self.phase)
        ch = t["channel"]
        if ch == 4:
            if self.phase < old:
                bit = (self.noise ^ (self.noise >> 1)) & 1
                self.noise = (self.noise >> 1) | (bit << 14)
            wave_v = 1024 if (self.noise & 1) else -1024
        elif ch == 3:
            x = int(self.phase * 2048)
            wave_v = x * 2 - 1024 if x < 1024 else 3071 - x * 2
        else:
            thresholds = (0.125, 0.25, 0.5, 0.75)
            wave_v = 1024 if self.phase < thresholds[n[3] & 3] else -1024
        volume = n[2]
        if ch == 3:
            volume = {1: 12, 2: 6, 3: 3}.get(volume, 0)
        elif n[4]:
            step = abs(n[4])
            change = int(position * 64 / (SR * step))
            volume += change if n[4] < 0 else -change
            volume = max(0, min(15, volume))
        return wave_v * volume // 12


def render_score(score_tracks, seconds: float, gain: float = 1.0):
    """渲染一首曲子（各声部循环），返回 float[-1,1] 列表。"""
    voices = [Voice(t) for t in score_tracks if t["count"]]
    total = int(seconds * SR)
    out = [0.0] * total
    for i in range(total):
        mixed = sum(v.sample() for v in voices)      # 每 Voice ≤ ±1280
        out[i] = mixed / 5120.0 * gain               # 与固件同界，防削波
    return out


# ---------------------------------------------------------------- 拼接与写出
def mix_into(base, sfx, at_t: float, gain: float = 0.7):
    start = int(at_t * SR)
    for i, s in enumerate(sfx):
        j = start + i
        if 0 <= j < len(base):
            base[j] += s * gain


def duck_gain_curve(total: int, dips):
    """dips = [(start_s, hold_s)]：1 → 93ms 淡出到 1/3 → hold → 93ms 回升。"""
    g = [1.0] * total
    fade = int(0.093 * SR)
    for start_s, hold_s in dips:
        a, b = int(start_s * SR), int((start_s + hold_s) * SR)
        for i in range(a, min(a + fade, total)):
            k = (i - a) / fade
            g[i] = min(g[i], 1 - k * 2 / 3)
        for i in range(a + fade, min(b, total)):
            g[i] = min(g[i], 1 / 3)
        for i in range(b, min(b + fade, total)):
            k = (i - b) / fade
            g[i] = min(g[i], 1 / 3 + k * 2 / 3)
    return g


def fade_edges(samples, ms=93):
    n = int(SR * ms / 1000)
    for i in range(min(n, len(samples))):
        k = i / n
        samples[i] *= k
        samples[-1 - i] *= k
    return samples


def write_wav(path: Path, samples, gain=1.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = max(1e-9, max(abs(s) for s in samples))
    norm = min(1.0, 0.92 / peak) * gain
    rms = math.sqrt(sum((s * norm) ** 2 for s in samples) / len(samples))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(
            struct.pack("<h", int(max(-1, min(1, s * norm)) * 32767))
            for s in samples))
    return peak, rms


def main() -> None:
    ap = argparse.ArgumentParser(description="BGM 环节样带渲染器")
    ap.add_argument("--pokewalk", default=str(
        ROOT.parent / "ESP32-PokemonGo"))
    ap.add_argument("--out", default=str(
        ROOT / "reports/evidence/bgm-2026-09-14"))
    args = ap.parse_args()
    pk = Path(args.pokewalk)
    scores = parse_music_assets(pk / "firmware/main/music_assets.h")
    print(f"解析到 {len(scores)} 首音序：{' '.join(sorted(scores))}")
    out = Path(args.out)

    # PokeWalk SFX 合成器（开战横幅 = encounter 风格，docs/08 §2.2）
    sys.path.insert(0, str(pk / "sim"))
    import audio as pk_audio                    # noqa: E402
    fanfare = pk_audio.render(pk_audio.sfx_encounter())

    # ---- 一局时间线样带（docs/08 §3.1/§3.2 cue 表的听感演示）----
    # 段落：(标签, 曲目, 秒, 段内 duck 演示)
    timeline = [
        ("01 主菜单·选种子", "route29", 4.0, []),
        ("02 准备阶段·买棋摆位（满金市）", "goldenrodcity", 6.0, []),
        ("03 开战横幅→常规战斗（大招 duck 演示）", "kantotrainerbattle", 8.0,
         [(1.2, 0.5), (4.0, 0.6)]),
        ("04 胜利结算", "trainervictory", 3.5, []),
        ("05 野怪轮（每 5 轮）", "kantowildbattle", 5.0, []),
        ("06 决赛圈（剩 2 人，准备+战斗同曲）", "championbattle", 6.0, []),
        ("07 终局名次页", "pokemoncenter", 4.0, []),
    ]
    flow = []
    marks = []                                  # (秒, 标签) 供打印
    for label, name, secs, dips in timeline:
        marks.append((len(flow) / SR, label))
        seg = render_score(scores[name], secs)
        if label.startswith("03"):
            mix_into(seg, fanfare, 0.0, 0.8)    # 开战横幅叠在切曲首拍
        g = duck_gain_curve(len(seg), dips)
        for i, s in enumerate(seg):
            flow.append(s * g[i])
        fade = int(0.093 * SR)                  # 93ms 淡切（§3.1 切歌规则）
        for i in range(min(fade, len(seg), max(0, len(flow) - len(seg)))):
            pass
    write_wav(out / "game-flow-timeline.wav", fade_edges(flow))
    print("\n一局时间线样带（duck 段为 BGM 降至 1/3 的大招演示）：")
    for t, label in marks:
        print(f"  {int(t)//60}:{int(t)%60:02d}  {label}")

    # ---- 单曲节选（每首 ~8s，环节 → 曲目对照试听）----
    print("\n单曲节选：")
    for name in ("route29", "goldenrodcity", "kantotrainerbattle",
                 "kantowildbattle", "championbattle", "trainervictory",
                 "gymleadervictory", "wildpokemonvictory", "evolution",
                 "pokemoncenter"):
        seg = render_score(scores[name], 8.0)
        peak, rms = write_wav(out / f"track-{name}.wav", seg)
        print(f"  {name:<22} peak {peak:.2f}  rms {rms:.3f}")
    print(f"\n全部输出至 {out}/（22050Hz mono PCM16，零依赖可随处播放）")


if __name__ == "__main__":
    main()
