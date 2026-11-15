# 64 · 背景音乐

日期：2026-11-15。全部为原创程序化芯片音乐（`tools/acceptance/play_music.js`，WebAudio 实时合成），不引入任何音频文件。

| 场景 | 曲目 | 风格 |
|---|---|---|
| 准备阶段 第 1–9 轮 | `prep_calm` | 88 BPM，C 大调，三角波旋律 + 柔和铺底 + 轻沙锤 |
| 准备阶段 第 10–19 轮 | `prep_mid` | 100 BPM，D 大调，方波旋律，加入底鼓 |
| 准备阶段 第 20 轮起或生命 ≤30 | `prep_tense` | 112 BPM，A 小调，脉冲贝斯、密集镲片 |
| 战斗回放 | `battle` | 142 BPM，E 小调，十六分琶音、完整鼓组 |
| 野怪轮战斗（每 5 轮） | `battle_wild` | 132 BPM，D 多利亚，锯齿主音 |
| 第 20 轮起战斗 | `battle_final` | 156 BPM，F# 小调 |
| 终局 / 结算 | `results` | 76 BPM，F 大调，舒缓 |
| 一次性 | `victory` / `defeat` / `levelup` | 战斗胜负、升级时播放短旋律，主曲临时压低 |

- 切换时 0.8 秒淡入淡出；页面切到后台时暂停。
- 浏览器要求用户交互后才能出声：首次点击后在空闲时启动，不会卡住那次点击。
- 顶栏 ♪ 按钮开关（默认开启，记在 `localStorage` 的 `poketactics.music`），音量 `poketactics.music.volume`（0.05–1，默认 0.6，可通过 `PlayMusic.setVolume()` 调整）。音效（rail 的“音效”按钮）独立开关。
- 扩展：在 `TRACKS` 里加一条 `{bpm, root, scale, prog, motif, bass, hat, kick, snare, ...}`，再在 `desired()` 里决定何时使用。
