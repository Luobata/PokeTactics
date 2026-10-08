#!/usr/bin/env python3
"""Web 可玩完整 Demo：1 玩家 + 7 bot 的整局宝可梦自走棋（会话引擎 + /demo 页面）。

架构（防漂移，与验收后台同源）：
- **只读复用 sim**：economy / shop / items / bots / combo / synergy / status /
  weather / rng / combat.Battle / roster / match 的常量与规则
  （PVE_WAVES、weather_for_round、Match._pair_up 无重复对手配对）。
  Battle 显式接收玩家格点，BattleAnimation 接收权威 battle 和 HUD 快照；
  子类只负责接入外部 battle 子流与逐帧输出。
- 会话 = 内存 dict（uuid 键）+ 全局锁；玩家席位（seat 0）+ 7 bot
  （人格混合 L1×3 + L2×3 + L3×1，LINEUP[7]，开局一次 pers 子流发牌）。
- 回合循环：准备阶段（玩家操作，不限时）→ end_prep 服务端结算 →
  玩家战斗用 BattleAnimation 渲染成帧（存 .build/demo/<sid>/r<n>/，
  羁绊/状态/天气/齐射全开）→ bot 对 bot 秒算只留结果行 → 掉血/淘汰/
  下一轮（天气按 weather_for_round）→ 终局排名页。
- 与 sim/match.py 的差异（适配层裁定，均为简化/单机可用性让路）：
  · 商店 4 格 / 备战 6 格：2026-09-14 平衡 pass 起 sim 常量已对齐
    （docs/10 设备裁定），bot 与玩家同规则（此前 bot 5 格/9 格的不对等
    已消除，见 reports/matchbalance-2026-09-14.md）；
  · 玩家战斗的解算与渲染同源（DemoBattleAnimation 内部那次 Battle 就是
    权威结果），帧 = 战报；bot 战斗与 match 完全同轨；
  · 幽灵战/野怪战与 match 一样使用当轮天气；
  · 渲染器 HUD 使用开战时快照，Web HUD 使用战后结算状态。

动作 API（GET /api/demo/action?cmd=...&sid=...）：new(seed) / state / buy(i) /
sell(loc) / refresh / levelup / move(from,to)（棋盘↔备战互移，含交换）/
craft(item) / equip(item,loc) / unequip(loc) / lock / end_prep / next / finish。
金币/人口/容量校验全部服务端，错误返回中文原因（ok=false，HTTP 恒 200）。

自动试玩（2026-09-15）：「▶ 自动试玩」按钮——客户端按决策优先级
（合成→装备→上场→买棋→升级→刷新→卖冗余→开战）驱动完整一局到终局
排名，战斗动画照常逐场播放（倍速随播放器档位）。近战前排/远程后排
的摆位与角标语义一致；后台标签自动暂停；全部走公开动作 API，
对局可事后复盘（与 E2E 同轨）。
"""

import copy
import io
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "sim"), str(ROOT / "tools" / "mockups")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import economy  # noqa: E402
import items as items_mod  # noqa: E402
import techniques as techniques_mod  # noqa: E402
import tactics as tactics_mod  # noqa: E402
import abilities as abilities_mod  # noqa: E402
import arena as arena_mod  # noqa: E402
import arena_skills  # noqa: E402
import pacing
import rng as rng_mod  # noqa: E402
import shop as shop_mod  # noqa: E402
from data import pokedex  # noqa: E402
import synergy as syn_mod  # noqa: E402
import weather as weather_mod  # noqa: E402
from bots import LINEUP, Bot, assign_personalities  # noqa: E402
from combat import Battle  # noqa: E402
from match import (PVE_GOLD, PVE_WAVES, Match as _Match,  # noqa: E402
                   weather_for_round)
from shop import (build_templates, make_piece, sell_value,  # noqa: E402
                  try_combine)
from expedition import status as expedition_status, sync_profile  # noqa: E402

REPORT_EFFECT_KEYS = ('effect_version', 'combinations', 'enemy_combinations', 'fields', 'enemy_fields')

MAX_ROUNDS = 31          # 与 sim/match 相同的轮数上限（超限按 HP 排名收官）
BENCH_CAP = 6            # 我方备战行 6 格（docs/10 §1.1 C-sym）
SHOP_SLOTS_UI = 4        # 商店 4 格（docs/10 §1.2 裁定）
GRID_COLS = 6            # C-sym 6 列
FPS_DT = 0.05            # 战斗帧步长（20fps，与演出时间轴一致）
from presentation_modes import WEB_BATTLE_REVISION, make_renderer

# 我方战场 2 行的填充序（combat layout="back" 对 team0 自 combat 行 3 起密排）：
# 列表头 = 后排（grid 行 1）→ 列表尾 = 前排（grid 行 0，贴中线）
_GRID_ORDER = [(1, c) for c in range(GRID_COLS)] + [(0, c) for c in range(GRID_COLS)]

TYPE_ZH = {"NORMAL": "一般", "FIRE": "火", "WATER": "水", "GRASS": "草",
           "ELECTRIC": "电", "ICE": "冰", "FIGHTING": "格斗", "POISON": "毒",
           "GROUND": "地面", "FLYING": "飞行", "PSYCHIC": "超能", "BUG": "虫",
           "ROCK": "岩", "GHOST": "幽灵", "DRAGON": "龙", "STEEL": "钢",
           "DARK": "恶"}

WEATHER_NOTE = {None: "天气平静", "sun": "火/草系招式 +20%，水系 -20%",
                "rain": "水系招式 +20%，火系 -20%",
                "sand": "岩/地/钢系招式 +15%", "hail": "冰系招式 +25%"}

PVE_LABELS = ["大葱鸭群", "暴走肯泰罗", "肯泰罗+化石翼龙", "双化石翼龙",
              "化石翼龙军团", "化石翼龙大军"]

ITEM_KEY_ZH = {"heal": "每秒回血", "sash": "致命伤保留1HP", "atk": "攻/特攻",
               "speed": "攻速", "dodge": "闪避", "ult_dmg": "大招伤害",
               "type_dmg": "系别增伤", "dr": "减伤", "gold_per_round": "每轮金币",
               "stone": "通信进化"}

SESSIONS: dict = {}
_LOCK = threading.RLock()
MAX_SESSIONS = 8         # 每会话落帧 ~20MB，超限淘汰最旧会话并清目录


class DemoError(Exception):
    """玩家操作被拒（前端 toast 中文原因）。"""


# ---------------------------------------------------------------- 素材（懒加载）
_ASSETS = None


def _assets():
    """Front/Palettes/Font16 全局单例（读 PokeWalk 二进制，进程内复用）。"""
    global _ASSETS
    if _ASSETS is None:
        with _LOCK:
            if _ASSETS is None:
                from decoders import Font16, Front, Palettes
                _ASSETS = (Front(), Palettes(), Font16())
    return _ASSETS


_SPRITES: dict = {}


def sprite_png(species_id: int, shiny=False):
    """/demo/sprite/<id>.png：40/48/56px 源图直接出 PNG（Web 端 CSS 缩放）。"""
    key = (species_id, bool(shiny))
    if key in _SPRITES:
        return _SPRITES[key]
    from data import pokedex
    if not (1 <= species_id <= 65535) or not pokedex().has_species(species_id):
        return None
    front, pal, _ = _assets()
    buf = io.BytesIO()
    front.image(species_id, pal, shiny=bool(shiny)).save(buf, "PNG")
    _SPRITES[key] = buf.getvalue()
    return _SPRITES[key]


# ---------------------------------------------------------------- 渲染包装
def _render_battle_frames(comp_a, comp_b, rng, weather_name, out_dir: Path,
                          positions_a=None, hud_snapshot=None, **battle_options):
    """玩家战斗：DemoBattleAnimation（layout=back + 外部子流）解算并出全帧。

    解算与渲染同源：内部那次 Battle 就是本场的权威结果（胜者/存活数），
    帧目录 .build/demo/<sid>/r<轮>/，返回 meta（帧数/事件流/结果）。
    """
    from render_battle_gif import AnimUnit, BattleAnimation
    from data import pokedex

    class _Anim(BattleAnimation):
        """适配包装：layout=back + 外部 battle 子流；渲染器 R1 新接口
        （battle= 注入 + playback_clock 等回放态）由父类构造统一初始化。"""

        def __init__(self, a, b, battle_rng, front, pal, font):
            battle = Battle(a, b, battle_rng, layout="back",
                            weather_name=weather_name, positions_a=positions_a,
                            **battle_options)
            self.sim_result = battle.run()
            self.statistics = battle.statistics()
            super().__init__(a, b, 0, front, pal, font,
                             weather_name=weather_name, battle=battle,
                             hud_snapshot=hud_snapshot)

    front, pal, font = _assets()
    anim = _Anim(comp_a, comp_b, rng, front, pal, font)
    renderer = make_renderer(anim, 'arena' if anim.is_arena else 'classic')
    res = anim.sim_result
    t_end = max(e[0] for e in anim.events)
    winner = res["winner"]
    duration = anim.presentation_duration
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n, T = 0, 0.0
    team_frames = []
    while T <= duration + 1e-9:
        frame = renderer.frame(T)
        frame.convert("RGB").save(out_dir / f"{n}.png", compress_level=2)
        view = anim._presentation_view()
        team_frames.append({
            'alive': [sum(u.die_t is None for u in view.units.values() if u.u.team == team)
                      for team in (0, 1)],
            'hp': [sum(u.hp for u in view.units.values() if u.u.team == team)
                   for team in (0, 1)],
        })
        n += 1
        T += FPS_DT
    meta = {"n": n, "dt": FPS_DT,
            "width": renderer.width,
            "height": renderer.height,
            "presentation": renderer.revision,
            "render_revision": renderer.revision,
            "team_frames": team_frames,
            "combatants": [{'idx': u.idx, 'team': u.team, 'sid': u.piece.species_id,
                            'name': u.piece.name, 'star': getattr(u.piece, 'star', 1),
                            'role': getattr(u.piece, 'role_key', 'attack'),
                            'range': u.piece.distance, 'max_hp': u.max_hp}
                           for u in anim.by_idx.values()],
            "battle_rows": anim.battle_rows, "winner": winner, "event_version": 3 if anim.is_arena else 2,
            "hud": hud_snapshot,
            "deployments": [list(e) for e in anim.events if e[1] == "deploy"],
            "survivors": res["survivors"], "duration": round(duration, 1),
            "statistics": anim.statistics,
            "simulation_duration": round(t_end, 1), "clock": "presentation-v1",
            "events": [{"t": round(e[0], 2), "text": _fmt_event(anim, e)}
                       for e in anim.presentation_events if e[1] != 'unit_state'
                       and not (anim.is_arena and e[1] == 'attack' and anim._terrain_attack(e))
                       and (e[1] != 'skill_effect' or anim.is_arena and e[5] in
                            ('guard', 'energy_drain', 'energy', 'cleanse', 'knockback', 'pull',
                             'shield', 'absorb', 'expire', 'taunt', 'thorns', 'thorn_hit'))]}
    if anim.is_arena:
        teams = {unit.idx: unit.team for unit in anim.by_idx.values()}
        meta.update(_battle_effects(anim.events, teams))
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
    return meta



def _battle_effects(events, teams):
    """Both perspectives from the same committed combat, including real zeroes."""
    from combination_view import battle_summary, field_summary
    return {'effect_version': 1,
            'combinations': battle_summary(events, teams, team=0),
            'enemy_combinations': battle_summary(events, teams, team=1),
            'fields': field_summary(events, teams, team=0),
            'enemy_fields': field_summary(events, teams, team=1)}

_MOVES_ZH = None


def _move_zh(name: str) -> str:
    """事件流 cast 存英文名（契约不变），显示层翻译（与验收台同法）。"""
    global _MOVES_ZH
    if _MOVES_ZH is None:
        from data import pokedex
        _MOVES_ZH = {m["name"]: (m.get("name_zh") or {'cross_chop': '十字劈'}.get(m['name'], m['name']))
                     for m in pokedex().moves.values()}
        _MOVES_ZH.update({'arena_' + s['id']: s['name'] for s in arena_skills.catalog()})
        _MOVES_ZH.update({'roar': '吼叫', 'rapid_spin': '高速旋转'})
    return _MOVES_ZH.get(name, name)


def _fmt_event(anim, e: tuple) -> str:
    t, kind = e[0], e[1]
    def hit_text(requested):
        actual = anim._display_damage(e, requested) if getattr(anim, 'is_arena', False) else requested
        if requested > 0 and actual == 0:
            return '护盾全额吸收'
        text = f'<b>-{actual}</b>'
        return text + (f'（护盾吸收 {requested - actual}）' if actual < requested else '')

    def name(i):
        unit = anim.by_idx[i]
        side = ('我方·' if unit.team == 0 else '敌方·') if getattr(anim, 'is_arena', False) else ''
        return side + unit.piece.name
    if kind == "deploy":
        return f"<b>{name(e[2])}</b> 落位 {e[3]}"
    if kind == "move":
        return f"{name(e[2])} 移动到 {e[3]}"
    if kind == "attack":
        return f"{name(e[2])} 普攻 {name(e[3])} {hit_text(e[4])}"
    if kind == "miss":
        return f"{name(e[2])} 攻击 {name(e[3])} 未命中（亮粉闪避）"
    if kind == "sash":
        return f"<b>{name(e[2])} 气势披带发动</b>（保留 1 HP）"
    if kind == "cast":
        if getattr(anim, 'is_arena', False) and e[4] == 'roar':
            return f"<b>{name(e[2])} 施放 {_move_zh(e[4])}</b> → {name(e[3])}"
        if (getattr(anim, 'is_arena', False) and e[4].startswith('arena_') and e[6] == 0
                and (anim.by_idx[e[2]].team == anim.by_idx[e[3]].team
                     or any(raw[1] == 'field_effect' and raw[2] == e[2]
                            and raw[5] == 'place' and raw[6].get('cast_index') ==
                            anim.timeline.source_index_by_event.get(id(e))
                            for raw in anim.events))):
            return f"<b>{name(e[2])} 施放 {_move_zh(e[4])}</b> → {name(e[3])}"
        eff = {0.5: "效果不佳", 2.0: "效果拔群", 4.0: "效果绝群"}.get(e[5], f"x{e[5]}")
        immune = getattr(anim, 'is_arena', False) and e[5] == 0
        tail = (" 属性免疫" if immune else " 未命中") if e[6] == 0 else \
            f" {hit_text(e[6])}{(' ' + eff) if e[5] != 1 else ''}"
        return f"<b>{name(e[2])} 的 {_move_zh(e[4])}</b> → {name(e[3])}{tail}"
    if kind == "die":
        return f"<b>{name(e[2])} 倒下</b>"
    if kind == "combo":
        return f"<b>⚡ {e[4]}（{TYPE_ZH.get(e[3], e[3])}系齐射）</b>"
    if kind == "regen":
        return f"{name(e[2])} 回复 +{e[3]}"
    if kind == 'skill_effect':
        effect, info = e[5], e[6]
        if effect == 'guard':
            text = f"减伤 {info['reduction']:.0%}，持续 {info['duration']:g} 秒"
        elif effect == 'shield':
            text = f"护盾 {info['shield']}，持续 {info['duration']:g} 秒"
        elif effect == 'absorb':
            text = f"护盾吸收 {info['amount']}，剩余 {info['shield']}"
        elif effect == 'expire':
            text = '护盾到期'
        elif effect == 'taunt':
            text = f"嘲讽，持续 {info['duration']:g} 秒"
        elif effect == 'thorns':
            text = f"毒刺反击姿态，持续 {info['duration']:g} 秒"
        elif effect == 'thorn_hit':
            text = '毒刺反击'
        elif effect == 'energy_drain':
            text = f"能量 -{info['stolen']}" + (f"，施法者 +{info['gained']}" if info['gained'] else '')
        elif effect == 'energy':
            text = f"能量 +{info['amount']}"
        elif effect == 'cleanse':
            text = '净化异常状态'
        elif effect == 'knockback':
            text = '击退一格'
        elif effect == 'pull':
            text = '拉回友军一格'
        else:
            return ''
        move_name = info.get('move_name', 'arena_' + e[4])
        return f"<b>{name(e[2])} · {_move_zh(move_name)}</b> → {name(e[3])}（{text}）"
    if kind == 'arena_heal':
        return f"<b>{name(e[2])} · 团队回复</b> → {name(e[3])}（+{e[4]} 生命）"
    if kind == 'combo_effect':
        from combination_view import NAMES
        effect, info = e[5], e[6]
        amount = info.get('amount', 0)
        if effect == 'energy':
            text = f"能量 +{amount}"
        elif effect == 'shield':
            text = f"护盾 +{amount}，持续 {info.get('duration', 3):g} 秒"
        elif effect == 'heal':
            text = f"实际回复 +{amount} 生命"
        elif effect == 'cleanse':
            kind_name = {'sleep': '睡眠', 'para': '麻痹', 'freeze': '冰冻', 'poison': '中毒', 'burn': '灼伤'}.get(info.get('cleansed_status') or info.get('status_kind'), '异常')
            text = f"实际净化{kind_name}"
        elif effect == 'status':
            kind_name = {'para': '麻痹', 'poison': '中毒'}.get(info.get('status_kind'), '异常')
            text = f"实际施加{kind_name}" if info.get('applied') else f"{kind_name}未生效"
        elif effect in ('guard', 'absorb_damage'):
            text = f"本次实际避免生命损失 {amount}；不算治疗或护盾"
            if info.get('avoided_shield_absorption', 0):
                text += f"，另保留护盾 {info['avoided_shield_absorption']}"
        elif effect == 'wet':
            text = f"湿润 {info.get('duration', 4):g} 秒；另一位同队电/草主命中可消费，同一湿润只消费一次"
        elif effect == 'weather_request':
            label = {'rain': '雨天', 'sun': '晴天'}.get(info.get('new_weather'), '天气')
            text = f"申请{label} {info.get('duration', 12):g} 秒；随后一拍生效，双方共享"
        elif effect == 'weather':
            label = {'rain': '雨天', 'sun': '晴天', None: '平静'}.get(info.get('new_weather'), '平静')
            text = ('同一拍晴雨相抵，转为平静' if info.get('reason') == 'simultaneous_rain_sun' else
                    label + '已存在，不续时' if info.get('reason') == 'same_weather_no_refresh' else
                    f"全场变为{label}，持续 {info.get('duration', 0):g} 秒；双方共享")
        elif effect == 'damage' and (info.get('recoil') or info.get('damage_scope') == 'self_cost'):
            text = f"反噬自损 {amount} 生命，绕过护盾；不计入对抗输出或抗伤"
        elif effect == 'accuracy':
            text = ('雨中打雷跳过命中与亮粉闪避判定，地面免疫仍生效' if info.get('guaranteed') else
                    '打雷未命中' if info.get('technique') == 'thunder' and info.get('hit') is False else
                    '打雷命中判定通过' if info.get('technique') == 'thunder' else
                    '修正一次原本会被亮粉闪避的命中；只记录命中，不额外生成攻击')
        elif effect == 'weaken':
            text = f"物理攻击伤害降低 {info.get('fraction', 0):.0%}，持续 {info.get('duration', 0):g} 秒"
        elif effect == 'empowered_hit':
            text = f"强化贡献已计入本次命中：额外生命损失 {info.get('extra_damage', amount)}"
            if info.get('absorbed', 0):
                text += f"，额外护盾吸收 {info['absorbed']}"
        elif effect == 'absorb':
            text = f"护盾吸收 {amount} 伤害"
        elif effect == 'expire' and e[4] in ('element_wet', 'arena_weather', 'trait_chlorophyll', 'trait_swift_swim'):
            text = ('湿润结束' if e[4] == 'element_wet' else '天气到期，恢复平静' if e[4] == 'arena_weather' else '天气加速结束')
        elif effect == 'tempo' and e[4] in ('trait_chlorophyll', 'trait_swift_swim'):
            text = f"天气行动速度 +{info.get('fraction', .25):.0%}；对应天气结束后撤销"
        elif effect == 'expire':
            text = (('连击' if e[4] == 'bond_combo' else '节拍') + '清层：'
                    + ('普攻转火' if info.get('reason') == 'retarget' else '4秒无有效普攻')
                    if e[4] in ('metronome', 'bond_combo') else '3秒直接攻击鼓舞结束'
                    if e[4] in ('native_inspiration', 'bond_inspiration') else '特性效果结束' if e[4].startswith('trait_') else '护盾到期')
        elif effect == 'spread':
            kind_name = {'poison': '中毒', 'burn': '灼伤'}.get(info.get('status_kind'), '异常')
            text = (f"{name(info.get('origin_idx', e[2]))}累计3次真实跳伤后传播{kind_name}，"
                    f"持续 {info.get('duration', 0):g} 秒；传播异常不再传播")
        elif effect == 'tempo':
            label = '连击' if e[4] == 'bond_combo' else '节拍'
            text = (f"{label} {info.get('stacks', 0)} 层，攻速 +{info.get('fraction', 0):.0%}，"
                    f"{'有效生命普攻增层' if info.get('gained') else '满层普攻续期'}；普攻转火或4秒断档清层")
            if e[4] == 'metronome' and info.get('base_fraction', 0):
                text += (f"（连击羁绊 +{info['base_fraction']:.0%}，"
                         f"节拍器 +{info.get('item_fraction', 0):.0%}）")
        elif effect == 'offense_buff' and info.get('damage_scope') == 'physical':
            text = f"物理攻击伤害 +{info.get('fraction', 0):.0%}，主要异常解除后结束；不强化特攻、DOT或地形"
        elif effect == 'offense_buff':
            trigger = ('本命有效援护后，' if e[4] == 'bond_inspiration' else
                       f"本命实际回能 {info.get('native_energy_amount', 0)} 后，")
            text = (trigger +
                    f"直接攻击伤害 +{info.get('fraction', .25):.0%}，持续 {info.get('duration', 3):g} 秒；"
                    '不强化毒/灼伤或岩钉')
        elif effect == 'charge':
            bonus = info.get('fraction', 1.)
            boost = '伤害翻倍' if bonus == 1. else f'伤害 +{bonus:.0%}'
            text = f"反击蓄力 {info.get('duration', 4):g} 秒，下次有效普攻{boost}"
        elif effect == 'empowered_basic':
            extra = info.get('extra_damage', amount)
            text = f"强化贡献已计入本次普攻：额外生命损失 {extra}"
            if info.get('absorbed', 0):
                text += f"，额外护盾吸收 {info['absorbed']}"
        elif effect == 'vulnerability':
            text = (f"易伤：受到攻击伤害 +{info.get('fraction', .12):.0%}，"
                    f"持续 {info.get('duration', 4):g} 秒")
        else:
            return ''
        source_kind = '特性 · ' if e[4].startswith('trait_') else ''
        return f"<b>{name(e[2])} · {source_kind}{NAMES.get(e[4], '联动')}</b> → {name(e[3])}（{text}）"
    if kind == 'field_effect':
        key, effect, info = e[4], e[5], e[6]
        if key == 'rock_spikes':
            if effect == 'place':
                text = f"铺设岩钉 {len(info.get('cells', []))} 格，持续 6 秒"
            elif effect == 'enter':
                text = f"岩钉入格：生命 -{info.get('actual', 0)}"
                if info.get('absorbed'):
                    text += f"，护盾吸收 {info['absorbed']}"
            elif effect == 'avoid':
                reason = {'heavy_boots': '厚底靴免疫', 'cooldown': '入格冷却保护',
                          'field_limit': '本场区域次数已满', 'battle_limit': '本战入格次数已满'}
                text = '岩钉：' + reason.get(info.get('reason'), '未触发')
            elif effect == 'clear':
                text = f"清除敌方岩钉 {info.get('cleared_count', len(info.get('cells', [])))} 格"
            else:
                text = '岩钉到期'
        else:
            label = {'root': '定身', 'vulnerability': '易伤'}.get(key, key)
            text = label + ('解除' if effect == 'expire' else
                           f" {info.get('duration', 1.5 if key == 'root' else 4):g} 秒")
        return f"<b>{name(e[2])}</b> → {name(e[3])}（{text}）"
    if kind == "partner_effect":
        label = {"shell_guard": "并肩坚壳", "bloom": "共生花园",
                 "wing_rally": "振翼鼓舞", "relay": "接力电流",
                 "share_lunch": "分享便当", "cut": "居合斩",
                 "surf": "冲浪", "rest": "睡觉"}.get(e[5], "搭档特性")
        info = e[6]
        effect = (f"伤害 {info['damage']}" if "damage" in info else
                  f"回复 {info['amount']}" if "amount" in info else
                  f"能量 +{info['energy']}" if "energy" in info else
                  f"减伤 {info.get('reduction', 0):.0%}，持续 {info.get('duration', 0):g} 秒")
        return f"<b>{name(e[2])} · {label}</b> → {name(e[3])}（{effect}）"
    if kind == 'tactical_effect':
        effect, info = e[4], e[5]
        weather_label = lambda value: weather_mod.WEATHERS[value]['label'] if value else '平静天气'
        if effect == 'guard':
            return f"<b>{name(e[2])} · 护卫</b> 替 {name(e[3])} 承受本次突进主命中（本场次数已用完）"
        if effect == 'healing_block':
            return f"<b>{name(e[2])} · 封疗针</b>：{name(e[3])} 的治疗减少60%，持续8秒（本场已用）"
        if effect == 'healing_prevented':
            return f"{name(e[3])} 因封疗少恢复 {info['amount']} 生命，实际恢复 {info['healed']}"
        if effect == 'weather_request':
            if info.get('source_kind') == 'ability':
                return f"<b>{name(e[2])} · 入场特性</b> 申请 {weather_label(info['new_weather'])}（入场统一裁定）"
            return f"{name(e[2])} 申请 {weather_label(info['new_weather'])}（下一战斗步统一裁定）"
        if effect == 'weather_start':
            return f"<b>全场天气：{weather_label(info['old_weather'])} → {weather_label(info['new_weather'])}</b>（双方共享）"
        if effect == 'weather_conflict':
            return f"<b>晴雨同时发动，相互抵消</b>；恢复 {weather_label(info['base_weather'])}（双方次数消耗）"
        if effect == 'weather_end':
            return f"天气效果结束，恢复本轮基础天气：{weather_label(info['base_weather'])}"
        return '战术效果：' + effect
    if kind == "status":
        zh = {"burn": "灼伤", "poison": "中毒", "para": "麻痹", "paralysis": "麻痹",
              "freeze": "冰冻", "sleep": "睡眠", "flinch": "畏缩",
              "reflect": "反射壁", "lightscreen": "光墙",
              "swords": "剑舞"}.get(e[3], e[3])
        act = {"apply": "发作", "tick": "跳伤", "expire": "解除"}.get(e[4], e[4])
        tail = (f" {hit_text(e[5])}" if getattr(anim, 'is_arena', False) else f" -{e[5]}") \
            if len(e) > 5 and e[5] else ""
        return f"<b>{name(e[2])}</b> {zh}·{act}{tail}"
    if kind == "end":
        return f"— 战斗结束 {'（你胜）' if e[2] == 0 else '（对方胜）' if e[2] == 1 else '（平局）'}"
    return f"— {kind}"


# ---------------------------------------------------------------- 玩家席位
class PlayerSeat:
    """人类席位：与 Bot 鸭子类型兼容（hp/gold/level/board/bench/shop/inventory），
    供 sim 的幸运蛋计数、掉落权重、copycat 侦察与配对复用。"""

    seat = 0

    def __init__(self, pool, templates) -> None:
        self.name = "你"
        self.gold = economy.START_GOLD
        self.hp = economy.START_HP
        self.level, self.xp = 1, 0
        self.streak = 0
        self.grid = {}                      # (row, col) -> OwnedPiece
        self.grid_rows = 2
        self.bench = []
        self.shop = shop_mod.Shop(pool, templates)
        self.pool = pool
        self.templates = templates
        self.inventory = items_mod.Inventory()
        self.stone_used = False
        self.item_drops = 0
        self.alive = True
        self.rank = None
        self.last_damage = 0
        self.combines = 0
        self.refresh_j = 0                  # 当轮手动刷新序（shop 子流 j≥1）
        self.shop_locked = False

    @property
    def board(self) -> list:
        """上场列表（次序即 Battle 阵型：头=后排）。"""
        return [self.grid[(r, c)] for r in reversed(range(self.grid_rows))
                for c in range(GRID_COLS) if (r, c) in self.grid]

    def all_pieces(self) -> list:
        return self.board + self.bench

    def count_species(self, species_id: int) -> int:
        return sum(1 for o in self.all_pieces()
                   if o.piece.species_id == species_id)

    def pop(self) -> int:
        return economy.pop_of(self.level)

    def battle_comp(self) -> list:
        if getattr(self.inventory, 'ruleset', None) == arena_mod.RULESET:
            return arena_mod.battle_comp(self.board)
        return [o.piece if o.item is None else (o.piece, o.item)
                for o in self.board]

    def battle_positions(self) -> list:
        """与 battle_comp 同序；UI (row, col) → 战斗 (col, row)。"""
        return [(c, r + self.grid_rows) for r in reversed(range(self.grid_rows))
                for c in range(GRID_COLS) if (r, c) in self.grid]

    def counter_vs(self, opp_board) -> None:  # 人类无自动对位（占位，配对代码统一调用）
        return None


# ---------------------------------------------------------------- 会话
class Session:
    def __init__(self, seed: int, ruleset=tactics_mod.BASE_RULESET) -> None:
        self.ruleset = tactics_mod.validate_ruleset(ruleset)
        self.is_arena = self.ruleset == 'arena_v1'
        self.bench_capacity = 8 if self.is_arena else BENCH_CAP
        self.shop_slots = 5 if self.is_arena else SHOP_SLOTS_UI
        self.sid = uuid.uuid4().hex[:12]
        self.seed = seed
        self.templates = arena_mod.build_templates() if self.is_arena else build_templates()
        self.pool = shop_mod.SharedPool(self.templates)
        if self.is_arena:
            self.pool.arena = True
            self.pool.remaining = arena_mod.pool_caps()
        self.player = PlayerSeat(self.pool, self.templates)
        self.grid_rows = 3 if self.is_arena else 2
        self.player.grid_rows = self.grid_rows
        pers = assign_personalities(7, rng_mod.derive(self.seed, 0, "pers"))
        self.bots = [Bot(i + 1, LINEUP[7][i], pers[i], self.pool, self.templates)
                     for i in range(7)]
        self.round_no = 0
        self.phase = "prep"
        self.log: list = []
        self.last_battle = None
        self.battle_history = []
        self.scouting_history = ({'version': 1, 'from_round': 1, 'seats': [[] for _ in range(8)]}
                                 if self.is_arena else None)
        self.pairs = None
        self.ghost_seat = None
        self.ghost_src = None
        self.opp_view = None
        self.opponent_comp = None
        self.opponent_learned = None
        self.opponent_tactics = None
        self.tactical = [{'guard': None, 'weather': None} for _ in range(8)]
        self.rewards = []
        self.next_unit_id = 1
        self.player_frames_total = 0
        self.player_battles = 0
        self.final_team = None
        self.eliminated_round = None
        self.run_id = uuid.uuid4().hex
        self.expedition = None
        self.discoveries = {"seen": [], "fielded": [], "won": []}
        self.arena_augments_pending = []
        self.arena_loot = []
        self.arena_loot_start = 1
        self.arena_component_choices = []
        self.arena_component_choice_start = 1
        for seat in self.seats:
            seat.inventory.ruleset = self.ruleset
            seat.inventory.techniques = dict.fromkeys(techniques_mod.ids_for(self.ruleset), 0)
            if self.is_arena:
                seat.shop.slots = [None] * self.shop_slots
                seat.shop.slot_count = self.shop_slots
                seat.bench_capacity = self.bench_capacity
                arena_mod.init_seat(seat)

    def battle_options(self, a=None, b=None):
        learned = {key: [o.technique for o in seat.board]
                   for key, seat in (("learned_a", a), ("learned_b", b)) if seat is not None}
        learned = {k: v for k, v in learned.items() if any(v)}
        if self.is_arena:
            return {**learned, **arena_mod.battle_options(self, a, b)}
        if tactics_mod.enabled(self.ruleset):
            learned.update(ruleset=self.ruleset,
                           tactics_a=self.battle_tactics(a), tactics_b=self.battle_tactics(b))
        if self.expedition is None:
            return learned
        # Every fight in this run, including bot/ghost/PVE, uses the same budget.
        return {**learned, "stat_mode": "budget_v1", "team_options": [
            {k: self.expedition[k] for k in ("partner", "technique")}
            if seat is self.player else None for seat in (a, b)]}

    def ensure_unit_ids(self):
        for seat in self.seats:
            for owned in seat.all_pieces():
                if owned.uid is None:
                    owned.uid = f"u{self.next_unit_id:08d}"
                    self.next_unit_id += 1

    def locate_uid(self, uid):
        self.ensure_unit_ids()
        for pos, owned in self.player.grid.items():
            if owned.uid == uid:
                return owned, f"g{pos[0]},{pos[1]}"
        for i, owned in enumerate(self.player.bench):
            if owned.uid == uid:
                return owned, f"b{i}"
        raise DemoError("棋子已移动、合成或卖出，请重新选择")

    def teach_bots(self):
        for seat in self.bots:
            if tactics_mod.enabled(self.ruleset):
                self._claim_bot_rewards(seat)
            for technique in techniques_mod.ids_for(self.ruleset):
                for owned in seat.board:
                    if seat.inventory.techniques[technique] <= 0:
                        break
                    if owned.technique is None and techniques_mod.compatible_species(
                            owned.piece.species_id, technique, ruleset=self.ruleset):
                        owned.technique = technique
                        seat.inventory.techniques[technique] -= 1
            if tactics_mod.enabled(self.ruleset):
                self._configure_bot_tactics(seat)

    def _positions(self, seat):
        if seat is self.player:
            return seat.battle_positions()
        return [(i % GRID_COLS, 3 - i // GRID_COLS) for i in range(len(seat.board))]

    def validate_tactical(self, seat, config):
        if not isinstance(config, dict) or set(config) != {'guard', 'weather'}:
            raise DemoError('战术配置字段无效')
        if not tactics_mod.enabled(self.ruleset) and any(config.values()):
            raise DemoError('当前规则不支持战术配置')
        board = {o.uid: (i, o) for i, o in enumerate(seat.board)}
        positions = self._positions(seat)
        for kind, keys in (('guard', {'uid', 'target_uid'}), ('weather', {'uid'})):
            entry = config[kind]
            if entry is None:
                continue
            if not isinstance(entry, dict) or set(entry) != keys or any(
                    not isinstance(value, str) or value not in board for value in entry.values()):
                raise DemoError('战术棋子必须仍在场上，请重新选择')
            index, unit = board[entry['uid']]
            if kind == 'weather':
                if unit.technique not in ('sunny_day', 'rain_dance'):
                    raise DemoError('天气手需要先学习晴天或求雨')
            else:
                if unit.technique != 'guard':
                    raise DemoError('护卫需要先学习护卫技能机')
                target_index = board[entry['target_uid']][0]
                a, b = positions[index], positions[target_index]
                if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                    raise DemoError('护卫与受保护队友需要四向相邻，请调整站位后重选')
        return config

    def refresh_tactics(self):
        """Disable stale selections; never silently choose another player target."""
        if not tactics_mod.enabled(self.ruleset):
            return []
        self.ensure_unit_ids()
        messages = []
        for seat in self.seats:
            config = self.tactical[seat.seat]
            for kind in ('guard', 'weather'):
                if config[kind] is None:
                    continue
                probe = {'guard': None, 'weather': None, kind: config[kind]}
                try:
                    self.validate_tactical(seat, probe)
                except DemoError:
                    config[kind] = None
                    if seat is self.player:
                        note = ('护卫' if kind == 'guard' else '天气手') + '配置已失效并关闭，请重新选择'
                        self._say(note)
                        messages.append(note)
        return messages

    def battle_tactics(self, seat):
        if seat is None:
            return None
        config = self.validate_tactical(seat, self.tactical[seat.seat])
        lookup = {o.uid: i for i, o in enumerate(seat.board)}
        return {'guard': ({'source': lookup[config['guard']['uid']],
                           'target': lookup[config['guard']['target_uid']]}
                          if config['guard'] else None),
                'weather': ({'source': lookup[config['weather']['uid']]}
                            if config['weather'] else None)}

    def _configure_bot_tactics(self, seat):
        self.ensure_unit_ids()
        config = {'guard': None, 'weather': None}
        positions = self._positions(seat)
        for i, owned in enumerate(seat.board):
            if owned.technique == 'guard' and config['guard'] is None:
                adjacent = [o for j, o in enumerate(seat.board) if i != j and
                            abs(positions[i][0] - positions[j][0]) +
                            abs(positions[i][1] - positions[j][1]) == 1]
                if adjacent:
                    target = max(adjacent, key=lambda o: (o.piece.tier, o.piece.species_id))
                    config['guard'] = {'uid': owned.uid, 'target_uid': target.uid}
            if owned.technique in ('sunny_day', 'rain_dance') and config['weather'] is None:
                config['weather'] = {'uid': owned.uid}
        self.tactical[seat.seat] = config

    def _grant_technique_choice(self, seat, round_no):
        reward_id = f'{self.run_id}:r{round_no}:s{seat.seat}:technique'
        if any(row['id'] == reward_id for row in self.rewards):
            return
        rng = rng_mod.derive(self.seed, round_no, 'pve', 4096 + seat.seat)
        candidates = list(techniques_mod.ids_for(self.ruleset))
        # A universal guard is a real choice, consuming the same one-machine
        # grant as the original expedition; no free extra demonstration item.
        options = ['guard']
        compatible = [key for key in candidates if key != 'guard' and any(
            techniques_mod.compatible_species(o.piece.species_id, key, ruleset=self.ruleset) for o in seat.all_pieces())]
        options.append(rng.choice(compatible or ['rest']))
        options.append(rng.choice([key for key in candidates if key not in options]))
        self.rewards.append({'id': reward_id, 'seat': seat.seat, 'round': round_no,
                             'kind': 'technique', 'status': 'pending',
                             'options': options, 'choice': None, 'closed_reason': None})

    def _claim_bot_rewards(self, seat):
        if not seat.alive:
            return
        for row in self.rewards:
            if row['seat'] != seat.seat or row['status'] != 'pending':
                continue
            def score(key):
                eligible = [o for o in seat.board if o.technique is None and
                            techniques_mod.compatible_species(o.piece.species_id, key, ruleset=self.ruleset)]
                if not eligible:
                    return (0, 0)
                if key in ('sunny_day', 'rain_dance'):
                    types = {'FIRE', 'GRASS'} if key == 'sunny_day' else {'WATER'}
                    return (1, 2 * sum(bool(types.intersection(o.piece.types)) for o in seat.board))
                return (1, 3 if key == 'guard' and len(seat.board) > 1 else 1)
            choice = max(row['options'], key=score)
            seat.inventory.techniques[choice] += 1
            row.update(status='claimed', choice=choice)

    def _close_terminal_rewards(self):
        for row in self.rewards:
            if row['status'] == 'pending' and (self.phase == 'over' or not self.seats[row['seat']].alive):
                row.update(status='closed', closed_reason='terminal' if self.phase == 'over' else 'eliminated')
        for row in self.arena_component_choices:
            if row['status'] == 'pending' and (self.phase == 'over' or not self.seats[row['seat']].alive):
                row.update(status='closed', closed_reason='run_finished' if self.phase == 'over' else 'eliminated')

    def observe(self, fielded=(), won=()):
        seen = {o.piece.species_id for o in self.player.all_pieces()}
        seen.update(s for s in self.player.shop.slots if s is not None)
        for entry in self.opponent_comp or []:
            seen.add((entry[0] if isinstance(entry, tuple) else entry).species_id)
        if self.round_no > 0 and self.round_no % 5 == 0 and self.player.alive:
            seen.update(PVE_WAVES[min(self.round_no // 5 - 1, len(PVE_WAVES) - 1)])
        for key, incoming in (("seen", seen | set(fielded) | set(won)),
                              ("fielded", set(fielded) | set(won)), ("won", won)):
            self.discoveries[key] = sorted(set(self.discoveries[key]) | set(incoming))

    def progress_snapshot(self):
        return {"run_id": self.run_id, **copy.deepcopy(self.discoveries),
                "round": self.eliminated_round or self.round_no,
                "finished": not self.player.alive or self.phase == "over",
                "rank": self.player.rank}

    # ---- 工具 ----
    @property
    def seats(self) -> list:
        return [self.player] + self.bots

    def _alive(self) -> list:
        return [e for e in self.seats if e.alive]

    def _say(self, line: str) -> None:
        self.log.append(f"R{self.round_no}｜{line}")
        if len(self.log) > 240:
            del self.log[:120]

    def combine_player(self) -> list:
        """玩家 3 合 1（复用 shop.try_combine；格位按对象身份回填）。"""
        p = self.player
        pos_map = {id(o): pos for pos, o in p.grid.items()}
        board_list = list(p.board)
        logs = try_combine(board_list, p.bench, self.pool, self.templates,
                           p.inventory, respect_locks=tactics_mod.evolution_choices_enabled(self.ruleset))
        if logs:
            p.combines += len(logs)
            p.grid = {pos_map[id(o)]: o for o in board_list if id(o) in pos_map}
        return logs

    def locate(self, loc: str):
        """'b<i>' 备战格 / 'g<r>,<c>' 战场格 -> (OwnedPiece, 容器, 键)。"""
        p = self.player
        try:
            if loc.startswith("b"):
                i = int(loc[1:])
                if not (0 <= i < len(p.bench)):
                    raise DemoError("备战格里没有棋子")
                return p.bench[i], "bench", i
            m = loc[1:].split(",")
            r, c = int(m[0]), int(m[1])
            if not (0 <= r < self.grid_rows and 0 <= c < GRID_COLS):
                raise DemoError("格子坐标越界")
            if (r, c) not in p.grid:
                raise DemoError("这个格子是空的")
            return p.grid[(r, c)], "grid", (r, c)
        except (IndexError, ValueError):
            raise DemoError(f"无法识别的位置 {loc!r}")

    # ---- 回合推进 ----
    def _loss_damage(self, round_no, survivors):
        return pacing.loss_damage(self.ruleset, round_no, survivors)

    def begin_round(self, r: int) -> None:
        self.round_no = r
        self.phase = "prep"
        self.last_battle = None
        self.opponent_comp = None
        self.opponent_learned = None
        self.opponent_tactics = None
        if pacing.enabled(self.ruleset) and r >= pacing.DEFAULT_NATURAL_END_POLICY.start_round:
            self._say(f'终局压力：败方本轮至少扣 {pacing.DEFAULT_NATURAL_END_POLICY.minimum_loss} 生命；胜方不掉血')
        for e in self._alive():
            e.gold += economy.round_income(e.gold, e.streak)
            e.gold += items_mod.lucky_egg_income(e)
            e.level, e.xp = economy.gain_round_xp(e.level, e.xp)
        p = self.player
        p.refresh_j = 0
        if p.alive and not p.shop_locked:
            self._roll_player_shop(rng_mod.derive(
                self.seed, r, "shop", rng_mod.shop_counter(p.seat, 0)))
        for b in self.bots:
            if b.alive:
                b.shop.roll(rng_mod.derive(
                    self.seed, r, "shop", rng_mod.shop_counter(b.seat, 0)),
                    b.level)
        for b in self.bots:
            if b.alive:
                b.decide(r, self.seats,
                         rng_mod.derive(self.seed, r, "bots", b.seat))
        self.teach_bots()
        if self.is_arena:
            arena_mod.begin_round(self)
        # 配对：复用 match 规则（无重复对手优先 + 奇数打幽灵），
        # pair 子流每轮现派生，prep 期算好供 UI 展示对手快照（battle 时原样使用）
        self.pairs = None
        self.ghost_seat = self.ghost_src = None
        if r % 5 == 0:
            self.opp_view = self._pve_view(r)
        else:
            pair_rng = rng_mod.derive(self.seed, r, "pair")
            alive = self._alive()
            pairs, odd = _Match._pair_up(None, alive, pair_rng)
            ghost_src = None
            if odd is not None and len(alive) > 1:
                ghost_src = pair_rng.choice([e for e in alive if e is not odd])
            self.pairs, self.ghost_seat, self.ghost_src = pairs, odd, ghost_src
            if p.alive:
                self.opp_view = self._opponent_view()

    def _roll_player_shop(self, rng) -> None:
        # 2026-09-14 平衡 pass：sim SHOP_SLOTS 已对齐 4 格（docs/10 裁定），
        # bot 与玩家同规则，适配层不再裁第 5 格
        self.player.shop.roll(rng, self.player.level)

    def _enemy_rows(self, board: list):
        """与 team1 的 back 部署一致：team0 坐标旋转 180°。"""
        rows = [[None] * GRID_COLS for _ in range(self.grid_rows)]
        if self.is_arena:
            for entry, (col, row) in zip(board, arena_mod.positions_for(board, 1)):
                rows[row][col] = entry
            return rows
        for i, owned in enumerate(board[:2 * GRID_COLS]):
            rows[i // GRID_COLS][GRID_COLS - 1 - i % GRID_COLS] = owned
        return rows

    def _opponent_view(self):
        p = self.player
        src = None
        if self.ghost_seat is p and self.ghost_src is not None:
            src, name = self.ghost_src, f"幽灵（{self.ghost_src.name} 镜像）"
        else:
            for a, b in self.pairs or []:
                if a is p:
                    src, name = b, b.name
                elif b is p:
                    src, name = a, a.name
        if src is None:
            return None
        # 侦察快照即本轮承诺的对手布阵；玩家准备时不会再暗中换位。
        if isinstance(src, Bot):
            src.counter_vs(p.board)
            if tactics_mod.enabled(self.ruleset):
                self._configure_bot_tactics(src)
        self.opponent_comp = list(src.battle_comp())
        self.opponent_learned = [o.technique for o in src.board]
        if tactics_mod.enabled(self.ruleset):
            self.opponent_tactics = copy.deepcopy(self.battle_tactics(src))
        def opponent_piece(owned):
            if self.is_arena:
                return _owned_view(owned, self.ruleset)
            # Classic opponent snapshots have never persisted an owned UID.
            return _piece_view(owned.piece, owned.item, self.ruleset)
        return {"name": name, "hp": src.hp, "level": src.level,
                "rows": [[opponent_piece(o) if o else None for o in row]
                         for row in self._enemy_rows(src.board)],
                "bench": [opponent_piece(o) for o in src.bench[:GRID_COLS]]}

    def _pve_view(self, r: int):
        waves = arena_mod.PVE_WAVES if self.is_arena else PVE_WAVES
        labels = arena_mod.PVE_LABELS if self.is_arena else PVE_LABELS
        wave_ids = waves[min(r // 5 - 1, len(waves) - 1)]
        label = labels[min(r // 5 - 1, len(labels) - 1)]
        row = [_piece_view(make_piece(sid, self.templates), ruleset=self.ruleset)
               for sid in wave_ids]
        rows = self._enemy_rows(row)
        return {"name": f"野怪轮 · {label}", "hp": None, "level": None,
                "rows": rows, "bench": [], "pve": True}

    # ---- 战斗结算 ----
    def end_prep(self) -> None:
        if self.phase != "prep":
            raise DemoError("当前不是准备阶段（先看完战斗再进下一轮）")
        if self.is_arena and self.player.alive and self.arena_augments_pending:
            raise DemoError('请先选择本轮海克斯强化，再开始战斗')
        if self.player.alive and any(row['seat'] == 0 and row['status'] == 'pending' for row in self.rewards):
            raise DemoError('还有待领取技能机，请先领取或明确放弃本次奖励')
        self.refresh_tactics()
        r = self.round_no
        self.observe(fielded=[o.piece.species_id for o in self.player.board])
        weather = None if self.is_arena else weather_for_round(r)
        if weather is not None:
            self._say(f"天气：{weather_mod.WEATHERS[weather]['label']}"
                      f"（{WEATHER_NOTE[weather]}）")
        if r % 5 == 0:
            events = self._resolve_pve(r, weather)
        else:
            events = self._resolve_pvp(r, weather)
        for seat, dmg, _note in events:
            if dmg > 0:
                seat.hp -= dmg
                seat.last_damage = dmg
        for e in [x for x in self.seats if x.alive and x.hp <= 0]:
            self._eliminate(e)
        self.phase = "battle"
        if len(self._alive()) <= 1 or r >= MAX_ROUNDS:
            self._finalize()
        self._close_terminal_rewards()

        # One committed report per player round. Playback and loading only read
        # this ledger; they must never resolve another battle or grant rewards.
        meta = self.last_battle
        if meta and meta.get('round') == r and not any(row['round'] == r for row in self.battle_history):
            self.battle_history.append({
                'round': r, 'winner': meta['winner'],
                'duration': meta.get('duration', 0), 'pve': meta.get('pve', False),
                'ghost': meta.get('ghost', False), 'opp_name': meta.get('opp_name', '对手'),
                'statistics': copy.deepcopy(meta.get('statistics')),
                **({key: copy.deepcopy(meta[key]) for key in REPORT_EFFECT_KEYS}
                   if meta.get('effect_version') == 1 else {}),
            })

    def _record_scouting_battle(self, r, a, b, result, *, pve=False, ghost=False,
                                source='battle', opp_name=None):
        """Record the existing result once. Ghost sources never become participants."""
        if not self.is_arena or result.get('statistics') is None or result.get('effect_version') != 1:
            return
        if self.scouting_history is None:
            self.scouting_history = {'version': 1, 'from_round': r, 'seats': [[] for _ in range(8)]}
        for seat, opponent, team in ((a, b, 0),) if pve or ghost else ((a, b, 0), (b, a, 1)):
            ledger = self.scouting_history['seats'][seat.seat]
            if any(row['round'] == r for row in ledger):
                continue
            winner = result['winner']
            report = {'round': r, 'winner': None if winner is None else winner ^ team,
                      'duration': result.get('duration', 0), 'pve': pve, 'ghost': ghost,
                      'opp_name': opp_name if pve else opponent.name,
                      'opp_seat': None if pve else opponent.seat, 'source': source,
                      'statistics': copy.deepcopy(result.get('statistics'))}
            if report['statistics'] is not None and team:
                stats = report['statistics']
                for row in stats['units']:
                    row['team'] ^= 1
                # Stable sequential idx keeps the existing statistics contract.
                stats['units'].sort(key=lambda row: (row['team'], row['idx']))
                for idx, row in enumerate(stats['units']):
                    row['idx'] = idx
                stats['totals'] = [{**row, 'team': row['team'] ^ 1}
                                   for row in reversed(stats['totals'])]
            if result.get('effect_version') == 1:
                report['effect_version'] = 1
                for ours, theirs in (('combinations', 'enemy_combinations'), ('fields', 'enemy_fields')):
                    report[ours] = copy.deepcopy(result[theirs if team else ours])
                    report[theirs] = copy.deepcopy(result[ours if team else theirs])
            ledger.append(report)
            del ledger[:-3]

    def _uncontested_result(self, a, b, comp_a, comp_b, winner):
        # Only zero counter initialization; no run, rewards or session RNG are replayed.
        battle = Battle(comp_a, comp_b, rng_mod.derive(self.seed, self.round_no, 'battle', 0),
                        layout='back', **self.battle_options(a, b))
        result = {'winner': winner, 'survivors': {0: len(comp_a), 1: len(comp_b)},
                  'duration': 0, 'statistics': battle.statistics()}
        if self.is_arena:
            result.update(_battle_effects([], {}))
        return result

    def _fight(self, r, battle_i, a, b, weather):
        """bot 对 bot：秒算，只留结果（与 match._pvp_round 同轨）。"""
        if tactics_mod.enabled(self.ruleset):
            for seat in (a, b):
                if isinstance(seat, Bot):
                    self._configure_bot_tactics(seat)
        battle = Battle(a.battle_comp(), b.battle_comp(),
                        rng_mod.derive(self.seed, r, "battle", battle_i),
                        layout="back", weather_name=weather,
                        **self.battle_options(a, b))
        result = battle.run()
        if self.is_arena:
            result['statistics'] = battle.statistics()
            result.update(_battle_effects(battle.events, {u.idx: u.team for u in battle.units}))
        return result

    def _grant_arena_loot(self, seat, result):
        """Settle each real seat once; loading and playback never issue resources."""
        if not self.is_arena:
            return
        from arena_rewards import roll_rewards, grant_rewards, reward_view
        reward_id = f'{self.run_id}:r{self.round_no}:s{seat.seat}:loot'
        if any(row['id'] == reward_id for row in self.arena_loot):
            return
        grants = roll_rewards(rng_mod.derive(self.seed, self.round_no, 'pve', 12000 + seat.seat), result)
        grant_rewards(seat, grants)
        self.arena_loot.append({'id': reward_id, 'round': self.round_no,
                               'seat': seat.seat, 'result': result, 'grants': grants})
        self._grant_arena_component_choice(seat)
        if seat is self.player:
            names = '、'.join(reward_view(grant)['name'] for grant in grants)
            self._say(f'回合奖励已入仓：{names}（胜利2份，失败或平局1份）')

    def _grant_arena_component_choice(self, seat):
        from arena_rewards import (COMPONENT_CHOICE_ROUNDS, component_choice,
                                   bot_component_choice, claim_component)
        if (not self.is_arena or self.round_no not in COMPONENT_CHOICE_ROUNDS
                or self.round_no < self.arena_component_choice_start):
            return
        # Only committed real-seat loot proves participation in this settlement.
        if not any(row['round'] == self.round_no and row['seat'] == seat.seat
                   for row in self.arena_loot):
            return
        reward = component_choice(self.run_id, self.round_no, seat.seat)
        if any(row['id'] == reward['id'] for row in self.arena_component_choices):
            return
        if seat is not self.player:
            choice = bot_component_choice(
                seat, reward['options'],
                rng_mod.derive(self.seed, self.round_no, 'pve', 13000 + seat.seat))
            claim_component(seat, reward, choice)
        self.arena_component_choices.append(reward)
        if seat is self.player:
            self._say('获得阶段组件补给：下一准备阶段可从8种组件中任选1件，胜负均可领取')

    def _resolve_pvp(self, r, weather):
        events = []
        battle_i = 0
        p = self.player
        for a, b in self.pairs:
            dmg = {id(a): 0, id(b): 0}
            note = ""
            winner = None
            scout_result = None
            scout_source = 'battle'
            if a.battle_comp() and b.battle_comp():
                if p not in (a, b) and isinstance(a, Bot):
                    a.counter_vs(b.board)
                if p not in (a, b) and isinstance(b, Bot):
                    b.counter_vs(a.board)
                if p in (a, b):
                    # 玩家战斗：_fight_rendered 恒以玩家为 team0 —— 胜者
                    # 索引要换算回配对席位，再记 dmg/连胜
                    me, opp = (a, b) if a is p else (b, a)
                    meta = self._fight_rendered(r, battle_i, me, opp, weather)
                    scout_result = meta
                    w, surv = meta["winner"], meta["survivors"]
                    winner = (0 if a is p else 1) if w == 0 else (1 if a is p else 0) if w == 1 else None
                    if w == 0:
                        dmg[id(opp)] = self._loss_damage(r, surv[0])
                        note = f"你 胜（己方存活 {surv[0]}）"
                    elif w == 1:
                        dmg[id(me)] = self._loss_damage(r, surv[1])
                        note = f"{opp.name} 胜（存活 {surv[1]}）"
                    else:
                        dmg[id(me)] = self._loss_damage(r, surv[1])
                        dmg[id(opp)] = self._loss_damage(r, surv[0])
                        note = "平局双伤"
                    self._streak(me, w == 0)
                    self._streak(opp, w == 1)
                    my = dmg[id(p)]
                    self._say(f"vs {opp.name}：{note}"
                              + (f"｜你 -{my}" if my else "｜你不掉血"))
                else:
                    res = self._fight(r, battle_i, a, b, weather)
                    scout_result = res
                    winner = res['winner']
                    if res["winner"] == 0:
                        dmg[id(b)] = self._loss_damage(r, res["survivors"][0])
                        note = f"{a.name} 胜（存活 {res['survivors'][0]}）"
                    elif res["winner"] == 1:
                        dmg[id(a)] = self._loss_damage(r, res["survivors"][1])
                        note = f"{b.name} 胜（存活 {res['survivors'][1]}）"
                    else:
                        dmg[id(a)] = self._loss_damage(r, res["survivors"][1])
                        dmg[id(b)] = self._loss_damage(r, res["survivors"][0])
                        note = "平局双伤"
                    self._streak(a, res["winner"] == 0)
                    self._streak(b, res["winner"] == 1)
                    if note:
                        self._say(note)
                battle_i += 1
            else:
                if a.battle_comp():
                    winner = 0
                    dmg[id(b)] = self._loss_damage(r, len(a.battle_comp()))
                    self._streak(a, True), self._streak(b, False)
                    note = f"{a.name} 不战而胜"
                    if a is p:
                        self.observe(won=[o.piece.species_id for o in p.board])
                elif b.battle_comp():
                    winner = 1
                    dmg[id(a)] = self._loss_damage(r, len(b.battle_comp()))
                    self._streak(b, True), self._streak(a, False)
                    note = f"{b.name} 不战而胜"
                    if b is p:
                        self.observe(won=[o.piece.species_id for o in p.board])
                else:
                    note = "双方空场，无事发生"
                if p in (a, b):
                    opp = b if a is p else a
                    my = dmg[id(p)]
                    self._say(f"vs {opp.name}：{note}"
                              + (f"｜你 -{my}" if my else "｜你不掉血"))
                    player_winner = None if winner is None else (0 if (a if winner == 0 else b) is p else 1)
                    self._uncontested_battle(r, opp.name, p.battle_comp(), opp.battle_comp(),
                                             player_winner, note, opp=opp)
                    scout_result = self.last_battle
                elif self.is_arena:
                    scout_result = self._uncontested_result(a, b, a.battle_comp(), b.battle_comp(), winner)
                scout_source = 'uncontested'
            if scout_result is not None:
                # Rendered player fights always use player as team0.
                scout_a, scout_b = ((p, b if a is p else a) if p in (a, b) else (a, b))
                self._record_scouting_battle(r, scout_a, scout_b, scout_result, source=scout_source)
            self._grant_arena_loot(a, 'draw' if winner is None else 'win' if winner == 0 else 'loss')
            self._grant_arena_loot(b, 'draw' if winner is None else 'win' if winner == 1 else 'loss')
            events.append((a, dmg[id(a)], note))
            events.append((b, dmg[id(b)], ""))
        if self.ghost_seat is not None:   # 奇数席打幽灵（败方照常掉血）
            odd = self.ghost_seat
            scout_source = 'battle'
            if odd is p and p.battle_comp():
                meta = self._fight_rendered(r, battle_i, p, self.ghost_src,
                                            weather, ghost=True)
                res = meta
            elif odd.battle_comp():
                if tactics_mod.enabled(self.ruleset):
                    for seat in (odd, self.ghost_src):
                        if isinstance(seat, Bot):
                            self._configure_bot_tactics(seat)
                ghost_positions = ([(GRID_COLS - 1 - c, self.grid_rows * 2 - 1 - row)
                                    for c, row in p.battle_positions()]
                                   if self.ghost_src is p else None)
                options = self.battle_options(odd, self.ghost_src)
                if ghost_positions is not None or not self.is_arena:
                    options['positions_b'] = ghost_positions
                battle = Battle(odd.battle_comp(), self.ghost_src.battle_comp(),
                                rng_mod.derive(self.seed, r, "battle", battle_i),
                                layout="back", weather_name=weather, **options)
                res = battle.run()
                if self.is_arena:
                    res['statistics'] = battle.statistics()
                    res.update(_battle_effects(battle.events, {u.idx: u.team for u in battle.units}))
            else:   # 空场打幽灵：不战而败（保底掉血，Battle 空队会崩所以不走解算）
                res = {"winner": 1,
                       "survivors": {0: 0, 1: len(self.ghost_src.battle_comp())}}
                if odd is p:
                    self._uncontested_battle(r, self.ghost_src.name, [], self.ghost_src.battle_comp(),
                                             1, '空场，幽灵战不战而败', ghost=True, opp=self.ghost_src)
                    res = self.last_battle
                elif self.is_arena:
                    res = self._uncontested_result(odd, self.ghost_src, [], self.ghost_src.battle_comp(), 1)
                scout_source = 'uncontested'
            self._record_scouting_battle(r, odd, self.ghost_src, res, ghost=True, source=scout_source)
            dmg = 0
            if res["winner"] == 1 or self.is_arena and res['winner'] is None:
                dmg = self._loss_damage(r, res["survivors"][1])
                self._streak(odd, False)
            else:
                self._streak(odd, True)
            if odd is p:
                self._say(f"幽灵战（{self.ghost_src.name} 镜像）："
                          + (f"平局 -{dmg}" if self.is_arena and res['winner'] is None else f"败 -{dmg}" if dmg else "胜"))
            self._grant_arena_loot(odd, 'draw' if res['winner'] is None else 'win' if res['winner'] == 0 else 'loss')
            events.append((odd, dmg, "幽灵战"))
        return events

    def _resolve_pve(self, r, weather):
        waves = arena_mod.PVE_WAVES if self.is_arena else PVE_WAVES
        wave_ids = waves[min(r // 5 - 1, len(waves) - 1)]
        wave = [make_piece(sid, self.templates) for sid in wave_ids]
        events = []
        battle_i = 0
        p = self.player
        alive = self._alive()
        for i, e in enumerate(alive):
            scout_source = 'battle'
            if e.battle_comp():
                if e is p:
                    meta = self._fight_rendered(r, battle_i, e, None, weather,
                                                wave=wave, pve=True)
                    res = meta
                else:
                    options = self.battle_options(e)
                    if self.is_arena:
                        options['positions_b'] = arena_mod.positions_for(wave, 1)
                    battle = Battle(e.battle_comp(), list(wave),
                                    rng_mod.derive(self.seed, r, "battle", battle_i),
                                    layout="back", weather_name=weather, **options)
                    res = battle.run()
                    if self.is_arena:
                        res['statistics'] = battle.statistics()
                        res.update(_battle_effects(battle.events, {u.idx: u.team for u in battle.units}))
                battle_i += 1
                if res["winner"] == 0:
                    gold = rng_mod.derive(self.seed, r, "pve", i).randint(*PVE_GOLD)
                    e.gold += gold
                    if e is p:
                        self._say(f"野怪轮胜（+{gold} 金）")
                else:
                    dmg = self._loss_damage(r, res["survivors"][1])
                    if e is p:
                        self._say(f"野怪轮败 -{dmg}（存活敌棋 "
                                  f"{res['survivors'][1]}）")
                    events.append((e, dmg, "野怪败"))
            else:
                res = {'winner': 1, 'survivors': {0: 0, 1: len(wave)}}
                dmg = self._loss_damage(r, len(wave))
                if e is p:
                    self._say(f"野怪轮不战而败 -{dmg}（场上没有棋子！）")
                    self._uncontested_battle(r, (self.opp_view or {}).get('name', '野怪'),
                                             [], wave, 1, '场上没有棋子，野怪轮不战而败', pve=True)
                    res = self.last_battle
                elif self.is_arena:
                    res = self._uncontested_result(e, None, [], wave, 1)
                scout_source = 'uncontested'
                events.append((e, dmg, "野怪空场"))
            self._record_scouting_battle(r, e, None, res, pve=True, source=scout_source,
                                         opp_name=(self.opp_view or {}).get('name', '野怪'))
            self._grant_arena_loot(e, 'draw' if res['winner'] is None else 'win' if res['winner'] == 0 else 'loss')
        if self.is_arena:
            return events
        # S5 组件掉落：人头保底 + 血量加权加发（pve 子流掉落段，同 match）
        comps = sorted(items_mod.COMPONENT_ORDER)
        for i, e in enumerate(alive):
            rng_d = rng_mod.derive(self.seed, r, "pve",
                                   items_mod.PVE_DROP_COUNTER + i)
            e.inventory.add_component(rng_d.choice(comps))
            e.item_drops += 1
            if self.expedition is not None:
                if tactics_mod.enabled(self.ruleset):
                    self._grant_technique_choice(e, r)
                    if e is p:
                        self._say('获得一台待选技能机：下一准备阶段从三个固定选项中领取')
                else:
                    machine = rng_mod.derive(self.seed, r, "pve", 4096 + e.seat).choice(
                        techniques_mod.TECHNIQUE_IDS)
                    e.inventory.techniques[machine] += 1
                    if e is p:
                        self._say(f"技能机入仓：{techniques_mod.view(machine)['name']}；准备阶段可选择兼容棋子学习")
        weights = items_mod.drop_weights(alive)
        for j in range(items_mod.PVE_BONUS_DROPS):
            rng_d = rng_mod.derive(self.seed, r, "pve",
                                   items_mod.PVE_DROP_COUNTER + 256 + j)
            rec = rng_d.choices(alive, weights=weights)[0]
            rec.inventory.add_component(rng_d.choice(comps))
            rec.item_drops += 1
        got = {}
        for key, n in self.player.inventory.components.items():
            if n > 0:
                got[items_mod.COMPONENT_NAMES[key]] = got.get(
                    items_mod.COMPONENT_NAMES[key], 0) + n
        self._say("装备组件入仓：" + "、".join(
            f"{k}×{v}" for k, v in sorted(got.items()))
            if got else "野怪轮结束，等待下次掉落")
        return events

    def _uncontested_battle(self, r, opp_name, comp_a, comp_b, winner, headline,
                            pve=False, ghost=False, opp=None):
        """Record an empty-side round without running combat or rendering frames."""
        result = self._uncontested_result(self.player, opp, comp_a, comp_b, winner)
        self.last_battle = {
            'round': r, 'n': 0, 'events': [], 'duration': 0,
            'survivors': {0: len(comp_a), 1: len(comp_b)}, 'winner': winner,
            'opp_name': opp_name, 'headline': headline, 'pve': pve, 'ghost': ghost,
            'statistics': result['statistics'],
            **{key: result[key] for key in REPORT_EFFECT_KEYS if key in result},
        }

    def _fight_rendered(self, r, battle_i, me, opp, weather, ghost=False,
                        wave=None, pve=False):
        """玩家参与的战斗：渲染帧（=权威解算）。opp=None 时用野怪波次。"""
        comp_a = me.battle_comp()
        # 幽灵来源仍可能参加自己的另一场战斗，使用准备阶段已展示的拷贝。
        comp_b = (list(self.opponent_comp) if self.opponent_comp is not None else
                  opp.battle_comp()) if opp is not None else list(wave)
        rng = rng_mod.derive(self.seed, r, "battle", battle_i)
        out_dir = ROOT / ".build" / "demo" / self.sid / f"r{r}"
        t0 = time.time()
        battle_options = self.battle_options(me, opp)
        if self.is_arena:
            battle_options['positions_b'] = arena_mod.positions_for(comp_b, 1)
        if opp is not None and self.opponent_learned is not None:
            battle_options.pop("learned_b", None)
            if any(self.opponent_learned):
                battle_options["learned_b"] = list(self.opponent_learned)
        if opp is not None and tactics_mod.enabled(self.ruleset) and self.opponent_tactics is not None:
            battle_options['tactics_b'] = copy.deepcopy(self.opponent_tactics)
        meta = _render_battle_frames(
            comp_a, comp_b, rng, weather, out_dir,
            positions_a=me.battle_positions(),
            hud_snapshot={"hp": max(0, me.hp), "gold": me.gold,
                          "level": me.level, "round": r},
            **battle_options)
        meta["round"] = r
        meta["render_s"] = round(time.time() - t0, 1)
        meta["pve"] = pve
        meta["ghost"] = ghost
        meta["opp_name"] = (opp.name if opp is not None else
                            (self.opp_view or {}).get("name", "野怪"))
        winner = meta["winner"]
        if winner == 0:
            self.observe(won=[o.piece.species_id for o in me.board])
        meta["headline"] = ("你 获胜！" if winner == 0 else
                            "你 失败……" if winner == 1 else "平局")
        self.last_battle = meta
        self.player_battles += 1
        self.player_frames_total += meta["n"]
        return meta

    @staticmethod
    def _streak(seat, won: bool) -> None:
        if won:
            seat.streak = seat.streak + 1 if seat.streak > 0 else 1
        else:
            seat.streak = seat.streak - 1 if seat.streak < 0 else -1

    def _eliminate(self, seat) -> None:
        if isinstance(seat, PlayerSeat):
            self.final_team = [_owned_view(o, self.ruleset) for o in seat.board]
            self.eliminated_round = self.round_no
        seat.alive = False
        seat.rank = len(self._alive()) + 1
        for owned in seat.all_pieces():
            for sid in owned.sources:
                self.pool.put(sid)
        if isinstance(seat, PlayerSeat):
            seat.grid, seat.bench = {}, []
        else:
            seat.board, seat.bench = [], []
        seat.shop.return_all()
        if tactics_mod.enabled(self.ruleset):
            self.tactical[seat.seat] = {'guard': None, 'weather': None}
        self._close_terminal_rewards()
        self._say(f"{seat.name} 被淘汰（第 {seat.rank} 名）")

    def _finalize(self) -> None:
        self.phase = "over"
        self._close_terminal_rewards()
        alive = self._alive()
        if len(alive) == 1:
            alive[0].rank = 1
        else:
            for rank, e in enumerate(sorted(
                    alive, key=lambda x: (-x.hp, -x.level, x.seat)), 1):
                e.rank = rank
        order = sorted(self.seats, key=lambda e: (e.rank is None, e.rank))
        self._say("终局：" + " > ".join(
            f"{e.name}({e.rank})" for e in order[:3]))

    def next_round(self) -> None:
        if self.phase != "battle":
            raise DemoError("当前不在结算阶段")
        self.begin_round(self.round_no + 1)

    def finish_spectating(self) -> None:
        if self.player.alive and self.phase != "over":
            raise DemoError("仍在对局中，请先完成本轮战斗")
        for _ in range(MAX_ROUNDS + 1):
            if self.phase == "over":
                return
            if self.phase == "battle":
                self.next_round()
            if self.phase == "prep":
                self.end_prep()
        raise DemoError("观战轮数异常，请重新开局")


# ---------------------------------------------------------------- 状态 JSON
def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _piece_view(piece, item=None, ruleset=tactics_mod.BASE_RULESET):
    from data import pokedex
    from render_mockups import TYPE_COLORS
    dex = pokedex()
    from skills import resolve_cast, GENERIC_DESCRIPTIONS
    mv = resolve_cast(piece)
    from profiles import get as profile_of
    from skills import skill_of
    profile = profile_of(piece.species_id)
    skill = skill_of(piece.species_id)
    descriptions = GENERIC_DESCRIPTIONS
    from profiles import effective_range
    distance = effective_range(piece)
    view = {
        "sid": piece.species_id, "name": piece.name, "tier": piece.tier,
        "types": [TYPE_ZH.get(t, t) for t in piece.types],
        "colors": [_hex(TYPE_COLORS.get(t, (120, 120, 120)))
                   for t in piece.types],
        "ranged": distance > 1, "range": distance,
        "role": profile["role"] if profile else ("远程输出" if distance > 1 else "近战"),
        "skill_name": (skill["name"] if skill else "属性招式") if mv else "普通攻击",
        "skill_type": TYPE_ZH.get(mv['type'], mv['type']) if mv else '一般',
        "skill_description": (profile["ult"].get("note", descriptions.get(skill["arch"], skill["name"])) if profile and profile.get("ult") else
                              descriptions.get(skill["arch"], "") if skill else "能量满时释放属性招式")
                              if mv else "当前形态没有可释放的属性招式，仅进行普通攻击",
        "move": _move_zh(mv['name']) if mv else "—",
        "ability": abilities_mod.for_species(piece.species_id, ruleset),
        "item": item,
        "item_name": items_mod.FINISHED[item]["name"] if item else None,
    }
    if ruleset == 'arena_v1':
        import arena_bonds
        import arena_traits
        role = getattr(piece, 'role_key', 'attack')
        native = arena_skills.skill_of(piece.species_id)
        view.update(skill_name=native['name'],
                    skill_type=TYPE_ZH.get(native['type'], native['type']),
                    skill_description=native['description'], move=native['name'],
                    native_skill={**native, 'type': TYPE_ZH.get(native['type'], native['type']),
                                  'energy': arena_skills.ENERGY_MAX, 'replaceable': False})
        view.update(star=getattr(piece, 'star', 1), shiny=getattr(piece, 'shiny', False),
                    bonds=arena_bonds.memberships(piece.species_id),
                    trait=arena_traits.for_species(piece.species_id,
                                                   getattr(piece, 'arena_trait_key', None)),
                    trait_options=arena_traits.options_for(piece.species_id),
                    attack_style='远程' if distance > 1 else '近战',
                    role_key=role, role_name=arena_mod.ROLE_NAMES[role],
                    role_description=arena_mod.ROLE_DESCRIPTIONS[role],
                    learnable=[t['id'] for t in arena_mod.technique_catalog()
                               if techniques_mod.compatible_species(piece.species_id, t['id'], ruleset=ruleset)],
                    item_effect=_item_effect(item, 'budget_v1') if item else None,
                    stat_scope='deployment_base', stats=_deployment_stats(piece))
    return view


def _owned_view(owned, ruleset=tactics_mod.BASE_RULESET):
    piece = arena_mod.battle_piece(owned) if ruleset == arena_mod.RULESET else owned.piece
    view = {**_piece_view(piece, owned.item, ruleset), 'uid': owned.uid,
            'technique': techniques_mod.view(owned.technique, ruleset)}
    return view


_DEPLOYMENT_STATS = {}


def _deployment_stats(piece):
    """Base deployment values, with star/role but without gear, bonds or augments.

    Reuse Unit and the simulator's deterministic arena modifier. No Battle is
    constructed, run, or randomized for a read-only panel.
    """
    key = (piece.species_id, piece.star, getattr(piece, 'arena_trait_key', None))
    if key not in _DEPLOYMENT_STATS:
        from combat import Unit
        import stat_budget
        unit = Unit(piece, 0, (0, 0), stat_mode='budget_v1')
        context = object.__new__(Battle)
        context.units, context.arena_teams = [unit], [(), ()]
        Battle._apply_arena_stats(context)
        _DEPLOYMENT_STATS[key] = {'max_hp': unit.max_hp, 'atk': unit.attack,
                                 'sp_atk': unit.sp_attack, 'defense': unit.defense,
                                 'sp_defense': unit.sp_defense,
                                 'speed': stat_budget.unit_stats(piece)['speed'],
                                 'attack_interval': round(unit.attack_interval, 3)}
    return dict(_DEPLOYMENT_STATS[key])


def _item_effect(key: str, stat_mode='legacy') -> str:
    if key == 'healing_needle':
        return '首次原生大招成功主命中后，最终主目标8秒内治疗减少60%；单槽取代启动或输出装备。'
    from build_rules import item_description
    override = item_description(key, stat_mode)
    if override:
        return override
    spec = items_mod.FINISHED[key]
    if spec.get('description'):
        return spec['description']
    parts = []
    for k, v in spec.items():
        if k in ("name", "pairs"):
            continue
        if k == "type_dmg":
            parts.append("、".join(
                f"{TYPE_ZH.get(t, t)}系大招+{round(p * 100)}%"
                for t, p in v.items()))
        elif isinstance(v, bool):
            parts.append(ITEM_KEY_ZH.get(k, k))
        elif k == "gold_per_round":
            parts.append(f"每轮金币+{v:g}")
        else:
            parts.append(f"{ITEM_KEY_ZH.get(k, k)}+{v * 100:g}%")
    return "，".join(parts) or "—"


def _synergy_effect_text(effects) -> str:
    names = {"speed": "攻速", "dmg": "伤害", "hp": "生命", "dr": "减伤",
             "energy": "回能", "sp_defense": "特防", "defense": "双防",
             "atk": "双攻", "ult_dmg": "大招伤害"}
    parts = []
    for key, value in effects.items():
        percent = f"{value * 100:g}%"
        if key == "ult_cap":
            parts.append(f"单次大招承伤≤{percent}最大生命")
        elif key == "heal":
            parts.append(f"每秒回复{percent}最大生命")
        else:
            parts.append(f"{names.get(key, key)}+{percent}")
    return " · ".join(parts)


def _synergy_view(sess, seat=None) -> list:
    from render_mockups import TYPE_COLORS
    comp = [o.piece for o in (sess.player if seat is None else seat).board]
    if sess.is_arena:
        import arena_bonds
        return [{**row, 'type': row['id'], 'zh': row['name'],
                 'color': _hex(TYPE_COLORS.get(row.get('element'), (145, 110, 190)))}
                for row in arena_bonds.preparation(comp)['entries']]
    counts = syn_mod.compute(comp)
    out = []
    for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        spec = syn_mod.SYNERGY_TABLE.get(t)
        if not spec:
            continue
        rungs = sorted(spec["tiers"])
        tier = syn_mod.tier_of(n, t)
        nxt = next((x for x in rungs if x > n), None)
        eff = ""
        if tier:
            eff = _synergy_effect_text(spec["tiers"][tier])
        out.append({"type": t, "zh": TYPE_ZH.get(t, t), "n": n, "tier": tier,
                    "next": nxt, "need": (nxt - n) if nxt else 0,
                    "color": _hex(TYPE_COLORS.get(t, (120, 120, 120))),
                    "effect": eff})
    return out


def _entry_weather_view(sess):
    """Forecast deployed opening traits from the current preparation snapshot.

    Teaching casts happen later and cannot be predicted here. Bench traits are
    deliberately excluded; PVE uses the same frozen opponent rows as scouting.
    """
    if not tactics_mod.entry_abilities_enabled(sess.ruleset):
        return None
    you = []
    for owned in sess.player.board:
        ability = abilities_mod.for_species(owned.piece.species_id, sess.ruleset)
        if ability:
            you.append({**ability, 'unit_name': owned.piece.name, 'uid': owned.uid})
    opponent = []
    for cells in (sess.opp_view or {}).get('rows', []):
        for piece in cells:
            ability = abilities_mod.for_species(piece['sid'], sess.ruleset) if piece else None
            if ability:
                opponent.append({**ability, 'unit_name': piece['name'], 'uid': piece.get('uid')})
    sources = you + opponent
    requested = {source['weather'] for source in sources}
    conflict = len(requested) > 1
    base = weather_for_round(sess.round_no)
    result = next(iter(requested)) if len(requested) == 1 else base
    label = {'sun': '晴天', 'rain': '雨天'}.get(result, weather_mod.WEATHERS[result]['label'] if result else '平静天气')
    if conflict:
        note = f'入场晴雨相抵，恢复{label}；所有入场次数消耗，之后教学仍可争夺。'
    elif sources:
        note = f"入场{label} {sources[0]['duration']:g}秒，双方共享；后续教学可覆盖。"
    else:
        note = '当前上场队伍没有天气特性，沿用本轮基础天气。'
    return {'you': you, 'opponent': opponent, 'conflict': conflict,
            'weather': result, 'zh': label, 'note': note}


def _evolution_preview(sess, *, uid=None, shop_index=None):
    """Read-only rehearsal of the real combine operation, including recursive buys."""
    p = sess.player
    plan = {'merges': [], 'auto_allowed': False, 'defer_allowed': False,
            'detail': '', 'from_sid': None, 'source_uids': []}
    board, bench, pool, inventory = copy.deepcopy((p.board, p.bench, sess.pool, p.inventory))
    if shop_index is not None:
        sid = p.shop.slots[shop_index]
        if sid is None:
            plan['detail'] = '商店格为空'
            return plan
        bought = shop_mod.OwnedPiece(sess.templates[sid], sess.templates[sid].tier)
        bought.uid = f'u{sess.next_unit_id:08d}'
        bench.append(bought)
        affordable = p.gold >= bought.invested
        eligible = pokedex().next_evolution(sid) is not None and sid not in shop_mod.TRADE_EVOLUTIONS
        plan['defer_allowed'] = eligible and affordable and len(bench) <= BENCH_CAP
        try_combine(board, bench, pool, sess.templates, inventory,
                    respect_locks=True, changes=plan['merges'])
        plan['auto_allowed'] = affordable and len(bench) <= BENCH_CAP
        if not affordable:
            plan['detail'] = '金币不足'
        elif not plan['auto_allowed']:
            plan['detail'] = '购买后备战席超过六格'
        elif not plan['merges']:
            plan['detail'] = '购买后没有自动进化；暂缓的实例不会被消耗'
    else:
        owned = next((o for o in board + bench if o.uid == uid), None)
        if owned is None:
            plan['detail'] = '棋子已移动、合成或卖出，请重新选择'
            return plan
        sid = owned.piece.species_id
        plan['from_sid'] = sid
        if sid in shop_mod.TRADE_EVOLUTIONS:
            plan['detail'] = '此形态只通过通信石进化；同名卡不会三合一'
            return plan
        if pokedex().next_evolution(sid) is None:
            plan['detail'] = '此形态已无后续关都进化；同名卡可独立上场或卖出，当前没有升星或训练'
            return plan
        others = [o for o in board + bench if o.piece.species_id == sid and o.uid != uid]
        if len(others) < 2:
            plan['detail'] = '需要三只同形态；可暂缓自动进化保留当前职责'
            return plan
        plan['source_uids'] = [uid] + [o.uid for o in others[:2]]
        try_combine(board, bench, pool, sess.templates, inventory, only_species=sid,
                    single=True, selected_uids=plan['source_uids'], changes=plan['merges'])
        plan['auto_allowed'] = len(plan['merges']) == 1 and len(bench) <= BENCH_CAP
        if not plan['merges']:
            plan['detail'] = '共享池里目标形态已售罄；保留当前三只'
        elif not plan['auto_allowed']:
            plan['detail'] = '产物需要一格备战席；先空出位置'
    for merge in plan['merges']:
        source = _piece_view(sess.templates[merge['from_sid']], ruleset=sess.ruleset)
        target = _piece_view(sess.templates[merge['to_sid']], ruleset=sess.ruleset)
        inherited = (items_mod.FINISHED[merge['inherit_item']]['name'] if merge['inherit_item'] else '无装备')
        teaching = techniques_mod.view(merge['inherit_technique'])
        returned = [items_mod.FINISHED[key]['name'] for key in merge['returned_items']]
        returned += [f"{techniques_mod.view(key)['name']}×{n}" for key, n in merge['returned_techniques'].items()]
        def counts(values):
            return '、'.join(f'{TYPE_ZH.get(key, key)}{n}' for key, n in sorted(values.items())) or '无'
        merge['detail'] = (f"{merge['from_name']}×3（{source['role']}；{'/'.join(source['types'])}；{source['skill_name']}）"
                           f" → {merge['to_name']}（{target['role']}；"
                           f"{'/'.join(target['types'])}；{target['skill_name']}）。累计投入{merge['invested']}金，"
                           f"直购目标{merge['to_tier']}金；合成后卖出返{max(1, merge['invested']-1)}金。"
                           f"目标库存{merge['target_remaining_before']}→{merge['to_remaining']}；"
                           f"上场{merge['board_before']}→{merge['board_after']}，备战{merge['bench_before']}→{merge['bench_after']}。"
                           f"上场羁绊 {counts(merge['synergies_before'])} → {counts(merge['synergies_after'])}。"
                           f"沿用编号{merge['result_uid']}，继承{inherited}、{teaching['name'] if teaching else '无教学'}；"
                           f"退回仓库{'、'.join(returned) or '无'}。产物在备战席，需要重新上场。")
    if plan['merges']:
        detail = ' '.join(row['detail'] for row in plan['merges'])
        plan['detail'] = ((plan['detail'] + '。') if plan['detail'] else '') + detail
        if shop_index is not None:
            plan['detail'] += ' 暂缓会跳过本次所有自动合成，并暂缓该形态全部实例。'
            if not plan['defer_allowed']:
                plan['detail'] += ' 当前不能暂缓购买（金币或备战容量不足）。'
        else:
            plan['detail'] += ' 明确进化只消耗选中实例及另两只同形态，只进化一步。'
    return plan


def _evolution_view(sess, owned):
    sid = owned.piece.species_id
    plan = _evolution_preview(sess, uid=owned.uid)
    return {'locked': owned.evolution_locked,
            'can_lock': pokedex().next_evolution(sid) is not None and sid not in shop_mod.TRADE_EVOLUTIONS,
            'can_evolve': plan['auto_allowed'], 'detail': plan['detail'], 'preview': plan}


def _scouting_rows(sess, seat) -> list:
    """Expose deployed cells without reconfiguring bots or changing battle snapshots."""
    if seat is sess.player:
        rows = [[None] * GRID_COLS for _ in range(sess.grid_rows)]
        for (r, c), owned in seat.grid.items():
            rows[r][c] = _owned_view(owned, sess.ruleset)
        return rows
    return [[_owned_view(owned, sess.ruleset) if owned else None for owned in row]
            for row in sess._enemy_rows(seat.board)]



def _committed_opponent_snapshot(sess, seat, opponent):
    if seat is not opponent or not sess.opp_view:
        return None
    rows = copy.deepcopy(sess.opp_view.get('rows', []))
    return {'round': sess.round_no, 'scope': 'committed_opponent', 'rows': rows,
            'board': [unit for row in rows for unit in row if unit],
            'note': '本轮已锁定的上场阵容；备战、海克斯另列当前公开配置。'}

def _scouting_opponent(sess):
    """Read the committed pairing; PVE never marks a trainer as the opponent."""
    if sess.round_no % 5 == 0:
        return None, False
    if sess.ghost_seat is sess.player and sess.ghost_src is not None:
        return sess.ghost_src, True
    for a, b in sess.pairs or []:
        if a is sess.player:
            return b, False
        if b is sess.player:
            return a, False
    return None, False


def state_json(sess) -> dict:
    sess.ensure_unit_ids()
    p = sess.player
    stat_mode = 'budget_v1' if sess.expedition or sess.is_arena else 'legacy'
    from render_mockups import TYPE_COLORS
    weather = None if sess.is_arena else weather_for_round(sess.round_no)
    wkey = weather or ""
    board_rows = [[None] * GRID_COLS for _ in range(sess.grid_rows)]
    copies = {}
    for o in p.all_pieces():
        copies[o.piece.species_id] = copies.get(o.piece.species_id, 0) + 1
    for (r, c), o in p.grid.items():
        v = _owned_view(o, sess.ruleset)
        v['item_effect'] = _item_effect(o.item, stat_mode) if o.item else None
        v["copies"] = copies.get(o.piece.species_id, 1)
        v["sell"] = sell_value(o)
        if tactics_mod.evolution_choices_enabled(sess.ruleset):
            v['evolution'] = _evolution_view(sess, o)
        board_rows[r][c] = v
    bench = []
    for o in p.bench:
        v = _owned_view(o, sess.ruleset)
        v['item_effect'] = _item_effect(o.item, stat_mode) if o.item else None
        v["copies"] = copies.get(o.piece.species_id, 1)
        v["sell"] = sell_value(o)
        if tactics_mod.evolution_choices_enabled(sess.ruleset):
            v['evolution'] = _evolution_view(sess, o)
        bench.append(v)
    shop = []
    for i in range(sess.shop_slots):
        sid = p.shop.slots[i]
        if sid is None:
            shop.append(None)
        else:
            v = _piece_view(p.templates[sid], ruleset=sess.ruleset)
            v["price"] = p.templates[sid].tier
            if tactics_mod.evolution_choices_enabled(sess.ruleset):
                v['evolution_preview'] = _evolution_preview(sess, shop_index=i)
            shop.append(v)
    comps = [{"key": k, "name": items_mod.COMPONENT_NAMES[k], "n": n}
             for k, n in p.inventory.components.items() if n > 0]
    finished = [{"key": k, "name": items_mod.FINISHED[k]["name"],
                 "effect": _item_effect(k, stat_mode)}
                for k in p.inventory.finished]
    craftable = []
    lucky_capped = items_mod.lucky_egg_count(sess.seats) >= \
        items_mod.LUCKY_EGG_GLOBAL_CAP
    for key, spec in items_mod.catalog(sess.ruleset).items():
        pair = p.inventory.craftable(key)
        if pair is None:
            continue
        if key == "lucky_egg" and lucky_capped:
            continue
        recipe = " + ".join(items_mod.COMPONENT_NAMES[c] for c in pair)
        craftable.append({"key": key, "name": spec["name"],
                          "effect": _item_effect(key, stat_mode), "recipe": recipe})
    xp_next = economy.xp_to_next(p.level)
    st = {
        "sid": sess.sid, "seed": sess.seed, "round": sess.round_no, "ruleset": sess.ruleset,
        "phase": sess.phase, "max_rounds": MAX_ROUNDS,
        "you": {"hp": max(0, p.hp), "gold": p.gold, "level": p.level,
                "xp": p.xp, "xp_next": xp_next, "pop": p.pop(),
                "on_board": len(p.grid), "streak": p.streak,
                "alive": p.alive, "rank": p.rank, "combines": p.combines,
                "stone_used": p.stone_used, "bench_cap": sess.bench_capacity,
                "refresh_cost": economy.REFRESH_COST,
                "shop_locked": p.shop_locked,
                "xp_cost": economy.XP_BUY_COST},
        "weather": {"key": wkey,
                    "zh": weather_mod.WEATHERS[weather]["label"] if weather else "平静" if sess.is_arena else "无",
                    "note": "开场平静 · 战斗内由求雨/晴天改变，双方共享" if sess.is_arena else WEATHER_NOTE[weather]},
        "entry_weather": _entry_weather_view(sess),
        "pacing": ({"starts_at": pacing.DEFAULT_NATURAL_END_POLICY.start_round,
                    "minimum_loss": pacing.DEFAULT_NATURAL_END_POLICY.minimum_loss,
                    "active": sess.round_no >= pacing.DEFAULT_NATURAL_END_POLICY.start_round,
                    "note": f'第{pacing.DEFAULT_NATURAL_END_POLICY.start_round}轮起，败方至少扣{pacing.DEFAULT_NATURAL_END_POLICY.minimum_loss}生命；胜方不掉血，野怪奖励照常。'}
                   if pacing.enabled(sess.ruleset) else None),
        "shop": shop,
        "board": board_rows,
        "bench": bench,
        "synergies": _synergy_view(sess),
        "items": {"components": comps, "finished": finished,
                  "craftable": craftable},
        "techniques": {"inventory": [{**t, "count": p.inventory.techniques[t['id']]}
                                      for t in techniques_mod.catalog(sess.ruleset)
                                      if p.inventory.techniques[t['id']] > 0]},
        "rewards": [{**{key: row[key] for key in ('id', 'round', 'kind', 'status', 'choice', 'closed_reason')},
                     'options': [techniques_mod.view(key, sess.ruleset) for key in row['options']]}
                    for row in sess.rewards if row['seat'] == 0],
        "tactical": copy.deepcopy(sess.tactical[0]),
        "opponent": sess.opp_view,
        "standings": [{"name": e.name, "is_you": e is p,
                       "hp": max(0, e.hp), "level": e.level,
                       "alive": e.alive, "rank": e.rank, "streak": e.streak}
                      for e in sess.seats],
        "log": sess.log[-24:],
        "last_battle": sess.last_battle,
        "battle_history": copy.deepcopy(sess.battle_history),
        "save": {"sequence": getattr(sess, "save_sequence", None),
                 "warning": getattr(sess, "save_warning", None)},
        "expedition": expedition_status(sess),
        "profile_warning": getattr(sess, "profile_warning", None),
        "player_result": ({"rank": p.rank, "round": sess.eliminated_round or sess.round_no,
                           "team": sess.final_team if sess.final_team is not None else
                           [_owned_view(o, sess.ruleset) for o in p.board]}
                          if not p.alive or sess.phase == "over" else None),
        "stats": {"battles": sess.player_battles,
                  "frames": sess.player_frames_total},
        "type_colors": {t: _hex(c) for t, c in TYPE_COLORS.items()},
    }
    if sess.is_arena:
        from arena_rewards import reward_view, component_choice_view
        def augments_of(seat):
            return [arena_mod.augment_view(a['id'] if isinstance(a, dict) else a)
                    for a in seat.arena_augments_selected]
        st['arena'] = {'version': 'arena_v1', 'shop_slots': sess.shop_slots,
                       'combination_version': 1,
                       'bench_capacity': sess.bench_capacity, 'deployment_rows': sess.grid_rows,
                       'catalog': [{**_piece_view(piece, ruleset=sess.ruleset),
                                    'cost': piece.tier,
                                    'pool_remaining': sess.pool.remaining[sid],
                                    'pool_total': arena_mod.pool_cap(sid)}
                                   for sid, piece in sess.templates.items()]}
        st['augments'] = {'pending': copy.deepcopy(sess.arena_augments_pending),
                          'selected': augments_of(p)}
        from combination_view import preparation
        st['combinations'] = preparation(sess)
        import arena_bonds
        st['bonds'] = arena_bonds.preparation([o.piece for o in p.board])
        st['arena']['bond_catalog'] = arena_bonds.catalog()
        import arena_traits
        st['arena']['trait_catalog'] = arena_traits.catalog()
        st['round_rewards'] = [{**row, 'grants': [reward_view(grant) for grant in row['grants']]}
                               for row in sess.arena_loot if row['seat'] == 0]
        st['component_choices'] = [component_choice_view(row)
                                   for row in sess.arena_component_choices if row['seat'] == 0]
        st['items']['crafting_blocked'] = ['lucky_egg'] if lucky_capped else []
        st['techniques'] = [{**t, 'count': p.inventory.techniques[t['id']], 'eligible': [o.uid for o in p.all_pieces()
                                             if techniques_mod.compatible_species(o.piece.species_id, t['id'], ruleset=sess.ruleset)]}
                            for t in arena_mod.technique_catalog()]
        scout_opponent, scout_ghost = _scouting_opponent(sess)
        st['scouting'] = [{'seat': seat.seat, 'name': seat.name, 'human': seat is p,
                           'hp': max(0, seat.hp), 'level': seat.level, 'gold': seat.gold,
                           'alive': seat.alive, 'rank': seat.rank,
                           'current_opponent': seat is scout_opponent,
                           'ghost_opponent': seat is scout_opponent and scout_ghost,
                           'rows': _scouting_rows(sess, seat),
                           'configuration_scope': 'current_deployment',
                           'battle_snapshot': _committed_opponent_snapshot(sess, seat, scout_opponent),
                           'synergies': _synergy_view(sess, seat),
                           'bonds': arena_bonds.preparation([o.piece for o in seat.board]),
                           'board': [_owned_view(o, sess.ruleset) for o in seat.board],
                           'bench': [_owned_view(o, sess.ruleset) for o in seat.bench],
                           'augments': augments_of(seat),
                           'recent_reports': copy.deepcopy(list(reversed(
                               sess.scouting_history['seats'][seat.seat]))) if sess.scouting_history else [],
                           'reports_recorded_from': sess.scouting_history['from_round'] if sess.scouting_history else None}
                          for seat in sess.seats]
        for i, standing in enumerate(st['standings']):
            standing['seat'] = i
    if sess.phase == "over":
        st["over"] = {"ranking": [
            {"name": e.name, "rank": e.rank, "is_you": e is p,
             "hp": max(0, e.hp), "rounds": sess.round_no}
            for e in sorted(sess.seats,
                            key=lambda e: (e.rank is None, e.rank))]}
    return st


# ---------------------------------------------------------------- 动作
def _guard_prep(sess) -> None:
    if not sess.player.alive:
        raise DemoError("你已被淘汰，点「下一轮」观战到终局")
    if sess.phase != "prep":
        raise DemoError("当前不是准备阶段")


def act_buy(sess, i: int, evolution='auto'):
    _guard_prep(sess)
    p = sess.player
    if not (0 <= i < sess.shop_slots) or p.shop.slots[i] is None:
        raise DemoError("这个商店格是空的")
    price = p.shop.price(i)
    if p.gold < price:
        raise DemoError(f"金币不足（需要 {price} 金，你有 {p.gold} 金）")
    choices = tactics_mod.evolution_choices_enabled(sess.ruleset)
    if evolution not in ('auto', 'defer') or (evolution == 'defer' and not choices):
        raise DemoError('当前规则不支持这个进化选择')
    if evolution == 'defer' and (pokedex().next_evolution(p.shop.slots[i]) is None
                               or p.shop.slots[i] in shop_mod.TRADE_EVOLUTIONS):
        raise DemoError('该形态没有普通三合一进化')
    # 池恢复可能使其他待合成的场上棋子落入备战席，每次购买都检查最终容量。
    # 失败购买不改变金币、卡池、棋子或装备。
    board, bench, pool, inventory = copy.deepcopy(
        (p.board, p.bench, sess.pool, p.inventory))
    bench.append(shop_mod.OwnedPiece(p.templates[p.shop.slots[i]], price))
    if evolution == 'auto':
        try_combine(board, bench, pool, sess.templates, inventory, respect_locks=choices)
    if len(bench) > sess.bench_capacity:
        raise DemoError(f"备战席已满（{sess.bench_capacity} 格）：先上场、卖出或购买可立即合成的第三只")
    owned = p.shop.buy(i)
    p.gold -= price
    p.bench.append(owned)
    if choices:
        sess.ensure_unit_ids()
    if evolution == 'defer':
        # A later fourth copy must not consume the pair the player just retained.
        for unit in p.all_pieces():
            if unit.piece.species_id == owned.piece.species_id:
                unit.evolution_locked = True
        logs = ['本形态全部实例暂缓进化；可在棋子菜单明确进化']
    else:
        logs = sess.combine_player()
    msg = f"买入 {owned.piece.name}（-{price} 金）"
    for line in logs:
        msg += f"；{line}"
    return msg


def act_evolution_lock(sess, uid, locked):
    _guard_prep(sess)
    if not tactics_mod.evolution_choices_enabled(sess.ruleset):
        raise DemoError('旧规则不支持暂缓进化')
    owned, _ = sess.locate_uid(uid)
    sid = owned.piece.species_id
    if pokedex().next_evolution(sid) is None or sid in shop_mod.TRADE_EVOLUTIONS:
        raise DemoError('该形态没有普通三合一进化')
    if locked not in ('0', '1'):
        raise DemoError('暂缓状态必须为0或1')
    owned.evolution_locked = locked == '1'
    return ('已暂缓' if owned.evolution_locked else '已解除暂缓') + owned.piece.name + '；本次不触发合成'


def act_evolve(sess, uid):
    _guard_prep(sess)
    if not tactics_mod.evolution_choices_enabled(sess.ruleset):
        raise DemoError('旧规则不支持手动进化')
    plan = _evolution_preview(sess, uid=uid)
    if not plan['auto_allowed']:
        raise DemoError(plan['detail'])
    p = sess.player
    positions = {id(o): pos for pos, o in p.grid.items()}
    board = list(p.board)
    logs = try_combine(board, p.bench, sess.pool, sess.templates, p.inventory,
                       only_species=plan['from_sid'], single=True,
                       selected_uids=plan['source_uids'])
    if len(logs) != 1:
        raise DemoError('进化条件已变化，请重新选择')
    p.grid = {positions[id(o)]: o for o in board}
    p.combines += 1
    return logs[0] + '；只进化一步，产物在备战席'


def act_sell(sess, loc: str):
    _guard_prep(sess)
    p = sess.player
    owned, where, key = sess.locate(loc)
    if owned.item is not None and owned.item != "evo_stone":
        p.inventory.finished.append(owned.item)   # 卖棋自动卸回仓库（无惩罚）
    if owned.technique is not None and not sess.is_arena:
        p.inventory.techniques[owned.technique] += 1
        owned.technique = None
    gold = shop_mod.sell_owned(owned, sess.pool)
    p.gold += gold
    if where == "bench":
        p.bench.remove(owned)
    else:
        del p.grid[key]
    return f"卖出 {owned.piece.name}（+{gold} 金）"


def act_refresh(sess):
    _guard_prep(sess)
    p = sess.player
    if p.gold < economy.REFRESH_COST:
        raise DemoError(f"金币不足（刷新需 {economy.REFRESH_COST} 金）")
    p.gold -= economy.REFRESH_COST
    p.shop_locked = False
    p.refresh_j += 1
    sess._roll_player_shop(rng_mod.derive(
        sess.seed, sess.round_no, "shop",
        rng_mod.shop_counter(p.seat, p.refresh_j)))
    return "商店已刷新"


def act_levelup(sess):
    _guard_prep(sess)
    p = sess.player
    if economy.xp_to_next(p.level) is None:
        raise DemoError("已是满级（Lv7 · 9 人口）")
    if p.gold < economy.XP_BUY_COST:
        raise DemoError(f"金币不足（买经验需 {economy.XP_BUY_COST} 金）")
    lv0 = p.level
    p.level, p.xp, p.gold, _ = economy.buy_xp(p.level, p.xp, p.gold)
    return (f"升级！Lv{lv0} → Lv{p.level}（人口 {p.pop()}）"
            if p.level > lv0 else f"+{economy.XP_BUY_AMOUNT} 经验")


def act_move(sess, frm: str, to: str):
    _guard_prep(sess)
    p = sess.player
    src, src_where, src_key = sess.locate(frm)
    # 解析目标（允许交换：目标有棋子则互换位置）
    try:
        if to.startswith("b"):
            ti = int(to[1:])
            if not (0 <= ti < sess.bench_capacity):
                raise DemoError(f"备战只有 {sess.bench_capacity} 格")
            dst_where, dst_key = "bench", ti
        else:
            m = to[1:].split(",")
            rr, cc = int(m[0]), int(m[1])
            if not (0 <= rr < sess.grid_rows and 0 <= cc < GRID_COLS):
                raise DemoError(f"目标格越界（棋盘 6 列 × {sess.grid_rows} 行）")
            dst_where, dst_key = "grid", (rr, cc)
    except (IndexError, ValueError):
        raise DemoError(f"无法识别的位置 {to!r}")
    dst = (p.bench[dst_key] if dst_where == "bench"
           and dst_key < len(p.bench) else
           p.grid.get(dst_key) if dst_where == "grid" else None)
    if dst is src:
        raise DemoError("原地不动")
    # 人口约束：备战→空战场格 会让上场数 +1
    if src_where == "bench" and dst_where == "grid" and dst is None:
        if len(p.grid) >= p.pop():
            raise DemoError(f"上场人口已满（{p.pop()}）：先升级或撤下棋子")
    # 执行移动/交换
    if src_where == "bench":
        p.bench.remove(src)
    else:
        del p.grid[src_key]
    if dst is not None:
        if dst_where == "bench":
            p.bench.remove(dst)
        else:
            del p.grid[dst_key]
    if dst_where == "bench":
        if dst_key >= len(p.bench):
            p.bench.append(src)
        else:
            p.bench.insert(dst_key, src)
    else:
        p.grid[dst_key] = src
    if dst is not None:
        if src_where == "bench":
            if src_key >= len(p.bench):
                p.bench.append(dst)
            else:
                p.bench.insert(src_key, dst)
        else:
            p.grid[src_key] = dst
    return (f"{src.piece.name} 移动"
            + (f"（与 {dst.piece.name} 交换）" if dst is not None else ""))


def act_craft(sess, key: str):
    _guard_prep(sess)
    p = sess.player
    if key not in items_mod.catalog(sess.ruleset):
        raise DemoError("未知装备")
    pair = p.inventory.craftable(key)
    if pair is None:
        raise DemoError("组件不足，无法合成这件装备")
    if key == "lucky_egg" and items_mod.lucky_egg_count(sess.seats) >= \
            items_mod.LUCKY_EGG_GLOBAL_CAP:
        raise DemoError("幸运蛋已达全场上限（2 件）")
    p.inventory.craft(key, pair)
    recipe = " + ".join(items_mod.COMPONENT_NAMES[c] for c in pair)
    return f"合成 {items_mod.FINISHED[key]['name']}（{recipe}）"


def act_equip(sess, key: str, loc: str):
    _guard_prep(sess)
    p = sess.player
    if key not in p.inventory.finished:
        raise DemoError("仓库里没有这件装备（先合成）")
    owned, _where, _key = sess.locate(loc)
    if owned.item is not None:
        raise DemoError("该棋子已有装备（每单位 1 格），先卸下再换")
    if key == "evo_stone":
        if p.stone_used:
            raise DemoError("进化石每局只能触发一次通信进化")
        nxt = items_mod.STONE_TARGETS.get(owned.piece.species_id)
        if nxt is None:
            raise DemoError("进化石只能给勇基拉 / 豪力 / 鬼斯通"
                            "（触发通信进化）")
        if sess.pool.remaining.get(nxt, 0) <= 0:
            raise DemoError("共享池里该进化形态已售罄")
        p.inventory.finished.remove("evo_stone")
        owned.item = "evo_stone"
        sess.pool.take(nxt)
        old = owned.piece.name
        owned.piece = make_piece(nxt, sess.templates)
        owned.sources.append(nxt)
        p.stone_used = True
        return f"通信进化！{old} → {owned.piece.name}（进化石不消耗）"
    p.inventory.finished.remove(key)
    owned.item = key
    return f"{owned.piece.name} 装备了 {items_mod.FINISHED[key]['name']}"


def act_unequip(sess, loc: str):
    _guard_prep(sess)
    p = sess.player
    owned, _where, _key = sess.locate(loc)
    if owned.item is None:
        raise DemoError("这个棋子没有装备")
    if owned.item == "evo_stone":
        raise DemoError("进化石已触发通信进化，不能卸下")
    p.inventory.finished.append(owned.item)
    key = owned.item
    owned.item = None
    return f"卸下 {items_mod.FINISHED[key]['name']}（回仓库）"


def act_learn(sess, uid: str, technique: str, replace=False):
    _guard_prep(sess)
    owned, _ = sess.locate_uid(uid)
    try:
        techniques_mod.validate_learning(owned.piece.species_id, technique, ruleset=sess.ruleset)
    except ValueError as exc:
        raise DemoError(str(exc))
    if technique not in techniques_mod.ids_for(sess.ruleset):
        raise DemoError("请选择有效的技能机")
    if owned.technique == technique:
        raise DemoError("该棋子已经学会这个招式")
    if owned.technique and not replace:
        raise DemoError("已有教学招式，请确认替换；旧技能机将返还仓库")
    inv = sess.player.inventory.techniques
    if inv[technique] <= 0:
        raise DemoError("仓库里没有这台技能机")
    inv[technique] -= 1
    if owned.technique:
        inv[owned.technique] += 1
    owned.technique = technique
    sess.refresh_tactics()
    return f"{owned.piece.name} 学会了 {techniques_mod.view(technique)['name']}"


def act_claim_component(sess, reward_id, choice):
    _guard_prep(sess)
    if not sess.is_arena:
        raise DemoError('当前规则没有阶段组件补给')
    reward = next((row for row in sess.arena_component_choices
                   if row['seat'] == 0 and row['id'] == reward_id), None)
    if reward is None:
        raise DemoError('组件补给不存在，请重新选择')
    from arena_rewards import claim_component
    try:
        granted = claim_component(sess.player, reward, choice)
    except ValueError as exc:
        raise DemoError(str(exc)) from exc
    return (f'已领取 {items_mod.COMPONENT_NAMES[choice]}，可在仓库合成装备'
            if granted else '这份组件补给已领取，不会重复入仓')


def act_claim_reward(sess, reward_id, choice):
    _guard_prep(sess)
    if not tactics_mod.enabled(sess.ruleset):
        raise DemoError('当前规则没有待选战术奖励')
    reward = next((row for row in sess.rewards if row['seat'] == 0 and row['id'] == reward_id), None)
    if reward is None:
        raise DemoError('奖励不存在，请重新选择')
    if not isinstance(choice, str) or choice not in (*reward['options'], 'skip'):
        raise DemoError('请选择本次奖励的有效选项')
    if reward['status'] != 'pending':
        if reward['choice'] == choice:
            return '该奖励已处理，不会重复入仓'
        raise DemoError('该奖励已处理，不能更换领取结果')
    if choice == 'skip':
        reward.update(status='closed', choice='skip', closed_reason='skipped')
        return '已放弃本次技能机奖励'
    sess.player.inventory.techniques[choice] += 1
    reward.update(status='claimed', choice=choice)
    return f"已领取 {techniques_mod.view(choice)['name']}，可在仓库选择棋子学习"


def act_set_tactical(sess, kind, uid, target_uid=None):
    _guard_prep(sess)
    if not tactics_mod.enabled(sess.ruleset):
        raise DemoError('当前规则不支持战术配置')
    if not isinstance(uid, str):
        raise DemoError('请选择有效棋子')
    sess.ensure_unit_ids()
    config = copy.deepcopy(sess.tactical[0])
    config[kind] = ({'uid': uid, 'target_uid': target_uid} if kind == 'guard' else {'uid': uid}) if uid else None
    sess.validate_tactical(sess.player, config)
    sess.tactical[0] = config
    label = '护卫' if kind == 'guard' else '天气手'
    return label + ('已设置' if uid else '已关闭')


def _new_session(seed: int, params=None) -> Session:
    from expedition import configure, deploy_starter
    params = params or {}
    tactical = params.get('mode') == 'tactics'
    arena = params.get('mode') == 'arena'
    sess = Session(seed, 'arena_v1' if arena else tactics_mod.CURRENT_TACTICS_RULESET if tactical else tactics_mod.BASE_RULESET)
    if not arena:
        configure(sess, {**params, 'mode': 'expedition'} if tactical else params)
    sess.begin_round(1)
    if not arena:
        deploy_starter(sess)
    sess.observe()
    if len(SESSIONS) >= MAX_SESSIONS:
        oldest = next(iter(SESSIONS))
        _drop_session(oldest)
    SESSIONS[sess.sid] = sess
    return sess


def _drop_session(sid: str) -> None:
    sess = SESSIONS.pop(sid, None)
    if sess is not None:
        shutil.rmtree(ROOT / ".build" / "demo" / sess.sid, ignore_errors=True)


def _apply_action(params: dict):
    """/api/demo/action 的总入口。返回 (dict, status)；异常全部转 ok=false。"""
    cmd = params.get("cmd", "")
    try:
        with _LOCK:
            if cmd == "new":
                try:
                    seed = int(params["seed"]) if params.get("seed") else secrets.randbits(32)
                except ValueError:
                    raise DemoError("种子必须是整数")
                sess = _new_session(seed, params)
                return {"ok": True, "sid": sess.sid,
                        "state": state_json(sess)}
            sid = params.get("sid", "")
            sess = SESSIONS.get(sid)
            if sess is None:
                return {"ok": False, "dead": True,
                        "error": "会话不存在（服务可能已重启），请开新对局"}
            msg = None
            if cmd == "state":
                pass
            elif cmd == "save":
                msg = "进度已保存"
            elif cmd == "buy":
                msg = act_buy(sess, int(params.get("i", -1)), params.get('evolution', 'auto'))
            elif cmd == 'set_evolution_lock':
                msg = act_evolution_lock(sess, params.get('uid', ''), params.get('locked', ''))
            elif cmd == 'evolve':
                msg = act_evolve(sess, params.get('uid', ''))
            elif cmd == "sell":
                msg = act_sell(sess, params.get("loc", ""))
            elif cmd == "refresh":
                msg = act_refresh(sess)
            elif cmd == "lock":
                _guard_prep(sess)
                sess.player.shop_locked = not sess.player.shop_locked
                msg = "商店已锁定：下轮保留，手动刷新解除锁定" if sess.player.shop_locked else "已解除商店锁定"
            elif cmd == "levelup":
                msg = act_levelup(sess)
            elif cmd == "move":
                msg = act_move(sess, params.get("from", ""),
                               params.get("to", ""))
            elif cmd == "bench_to_board":       # move 的语义别名（自测/脚本友好）
                bench_i = params.get("bench", "")
                col = params.get("col", "")
                row = params.get("row", "1")
                msg = act_move(sess, f"b{bench_i}", f"g{row},{col}")
            elif cmd == "craft":
                msg = act_craft(sess, params.get("item", ""))
            elif cmd == "equip":
                msg = act_equip(sess, params.get("item", ""),
                                params.get("loc", ""))
            elif cmd == "unequip":
                msg = act_unequip(sess, params.get("loc", ""))
            elif cmd == "trait":
                _guard_prep(sess)
                if not sess.is_arena:
                    raise DemoError('当前规则不支持竞技特性选择')
                try:
                    msg = arena_mod.set_trait(sess, params.get('loc', ''), params.get('trait', ''))
                except ValueError as exc:
                    raise DemoError(str(exc)) from exc
            elif cmd == "learn":
                if sess.is_arena:
                    _guard_prep(sess)
                    try:
                        msg = arena_mod.learn(sess, params.get('loc', ''), params.get('technique', ''))
                    except ValueError as exc:
                        raise DemoError(str(exc)) from exc
                else:
                    msg = act_learn(sess, params.get("uid", ""), params.get("technique", ""),
                                    replace=params.get("replace") == "1")
            elif cmd == 'claim_augment':
                _guard_prep(sess)
                if not sess.is_arena:
                    raise DemoError('当前规则不支持海克斯强化')
                try:
                    msg = arena_mod.claim_augment(sess, params.get('id', ''), params.get('choice', ''))
                except ValueError as exc:
                    raise DemoError(str(exc)) from exc
            elif cmd == 'claim_reward':
                msg = act_claim_reward(sess, params.get('reward_id', ''), params.get('choice', ''))
            elif cmd == 'claim_component':
                msg = act_claim_component(sess, params.get('reward_id', ''), params.get('choice', ''))
            elif cmd == 'set_guard':
                msg = act_set_tactical(sess, 'guard', params.get('uid', ''), params.get('target_uid', ''))
            elif cmd == 'set_weather':
                msg = act_set_tactical(sess, 'weather', params.get('uid', ''))
            elif cmd == "end_prep":
                sess.end_prep()
                msg = "战斗结算完成"
            elif cmd == "finish":
                sess.finish_spectating()
                msg = "观战结束，最终排名已生成"
            elif cmd == "next":
                if sess.phase == "prep" and not sess.player.alive:
                    sess.end_prep()   # 淘汰后观战快进：跳过准备直接结算本轮
                if sess.phase == "battle":
                    sess.next_round()
                    msg = f"进入第 {sess.round_no} 轮准备阶段"
                else:
                    msg = "对局已结束"
            else:
                return {"ok": False, "error": f"未知动作 {cmd!r}"}
            if cmd != 'state':
                invalidated = sess.refresh_tactics()
                if invalidated:
                    msg = '；'.join(([msg] if msg else []) + invalidated)
            out = {"ok": True, "state": state_json(sess)}
            if msg:
                out["msg"] = msg
            return out
    except DemoError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 —— Demo 的 500 屏蔽层
        return {"ok": False, "error": f"内部错误：{exc!r}"}


SAVE_ROOT = Path(os.environ.get("POKETACTICS_SAVE_DIR", str(ROOT / ".build" / "saves")))


def _save_store(sid):
    if not re.fullmatch(r"[a-f0-9]{12}", sid or ""):
        raise ValueError("无效的存档编号")
    from esp32_runtime import SaveStore, FileBackend
    from session_save import SessionCodec
    return SaveStore(FileBackend(SAVE_ROOT), SessionCodec(), namespace="poketactics",
                     slot=sid, max_bytes=512 * 1024)


def _publish_loaded(loaded, sid):
    session = loaded.state
    session.sid, session.save_sequence = sid, loaded.sequence
    if loaded.recovered:
        session.save_warning = "最新存档损坏，已恢复上一份有效进度"
    if len(SESSIONS) >= MAX_SESSIONS and sid not in SESSIONS:
        _drop_session(next(iter(SESSIONS)))
    SESSIONS[sid] = session
    sync_profile(session)
    return {"ok": True, "sid": sid, "state": state_json(session),
            "msg": "进度已恢复，不会重复结算收入或奖励"}


def api_action(params: dict):
    """Persist before publishing successful actions; failed writes roll back memory."""
    with _LOCK:
        sid, cmd = params.get("sid", ""), params.get("cmd", "")
        before = copy.deepcopy(SESSIONS.get(sid)) if cmd not in ("state", "resume") else None
        try:
            if "expected_sequence" in params and cmd not in ("state", "resume", "new"):
                current = SESSIONS.get(sid)
                if current is None or str(getattr(current, "save_sequence", None)) != str(params["expected_sequence"]):
                    return {"ok": False, "error": "进度已在其他页面更新，请重新选择操作"}
            if getattr(SESSIONS.get(sid), "save_blocked", False) and cmd not in ("state", "resume", "new"):
                return {"ok": False, "error": "上次保存结果尚未确认，请先点继续存档重新读取"}
            if cmd == "resume":
                return _publish_loaded(_save_store(sid).load(), sid)
            if cmd == "restore_checkpoint":
                store = _save_store(sid)
                raw = store.export_checkpoint()
                checkpoint = {"checkpoint_state": SESSIONS[sid]} if sid in SESSIONS else {}
                loaded = store.import_backup(raw, **checkpoint)
                return _publish_loaded(loaded, sid)
            result = _apply_action(params)
            if not result.get("ok"):
                if before is not None:
                    SESSIONS[sid] = before
                return result
            if cmd != "state":
                sid = result.get("sid", sid)
                session = SESSIONS[sid]
                session.observe()
                info = _save_store(sid).save(session)
                session.save_sequence = info.sequence
                sync_profile(session)
                result["state"] = state_json(session)
            elif sid in SESSIONS and not getattr(SESSIONS[sid], "save_blocked", False):
                sync_profile(SESSIONS[sid])
                result["state"] = state_json(SESSIONS[sid])
            return result
        except Exception as exc:
            if getattr(exc, "commit_uncertain", False):
                # Rename succeeded but durable commit could not be confirmed. Do not
                # promise rollback or allow a stale in-memory state to overwrite disk.
                if sid in SESSIONS:
                    SESSIONS[sid].save_blocked = True
                return {"ok": False, "recovery_sid": sid,
                        "error": "保存提交状态未确认，请点继续存档核对磁盘进度；当前已暂停操作"}
            if cmd == "new":
                if sid in SESSIONS:
                    _drop_session(sid)
            elif before is not None:
                SESSIONS[sid] = before
            return {"ok": False, "error": f"存档操作未完成，进度未覆盖：{exc}"}


def backup_bytes(sid, checkpoint=False):
    with _LOCK:
        store = _save_store(sid)
        return store.export_checkpoint() if checkpoint else store.export_backup()


def import_backup(raw, sid=None, inspect_only=False):
    """Untrusted file bytes go through the same runtime and game codec as boot."""
    with _LOCK:
        try:
            target = sid or uuid.uuid4().hex[:12]
            store = _save_store(target)
            if inspect_only:
                loaded = store.inspect_backup(raw)
                session = loaded.state
                return {"ok": True, "preview": {"round": session.round_no,
                        "phase": session.phase, "hp": max(0, session.player.hp),
                        "gold": session.player.gold, "seed": session.seed,
                        "warning": getattr(session, "save_warning", None)}}
            checkpoint = {"checkpoint_state": SESSIONS[target]} if target in SESSIONS else {}
            loaded = store.import_backup(raw, **checkpoint)
            return _publish_loaded(loaded, target)
        except Exception as exc:
            if getattr(exc, "commit_uncertain", False):
                if target in SESSIONS:
                    SESSIONS[target].save_blocked = True
                return {"ok": False, "recovery_sid": target,
                        "error": "导入提交状态未确认，请点继续存档核对；导入前检查点仍可恢复"}
            return {"ok": False, "error": f"备份未导入，当前进度保持不变：{exc}"}


# ---------------------------------------------------------------- /demo 页面
DEMO_HTML = r"""<!doctype html><html lang="zh-CN">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>宝可梦自走棋 · Web Demo</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f2efe5;color:#29302b;font:14px/1.6 ui-monospace,"PingFang SC",monospace}
main{max-width:1180px;margin:auto;padding:16px}
header{display:flex;align-items:center;gap:12px;border-bottom:2px solid #29302b;padding-bottom:10px;margin-bottom:12px;flex-wrap:wrap}
h1{font-size:19px;margin:0}a{color:#355c3d}
button{font:inherit;color:inherit;background:#fffdf5;border:1px solid #899081;border-radius:4px;padding:7px 12px;cursor:pointer;min-height:36px}
button:hover{background:#e2e8d8}button.primary{background:#355c3d;color:#fff;border-color:#355c3d}
button.primary:hover{background:#28452f}button:disabled{opacity:.45;cursor:default}
input,select{font:inherit;color:inherit;background:#fffdf5;border:1px solid #899081;border-radius:4px;padding:6px 8px}
.muted{color:#8b938a;font-size:12px}
/* HUD */
#hud{display:flex;gap:10px;flex-wrap:wrap;align-items:center;background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:8px 12px;margin-bottom:10px}
#hud b{font-size:16px}
.hudchip{display:flex;gap:6px;align-items:center;padding:2px 10px;border-right:1px dashed #b9b3a0}
.hudchip:last-child{border-right:none}
/* 布局 */
.cols{display:grid;grid-template-columns:minmax(430px,1fr) 330px;gap:14px;align-items:start}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
.panel{background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:10px;margin-bottom:10px}
.panel h3{margin:0 0 8px;font-size:14px;border-bottom:1px solid #d8d2bf;padding-bottom:6px}
/* 棋盘 */
.rowtag{font-size:12px;color:#555e54;margin:4px 2px}
.grid{display:grid;grid-template-columns:repeat(6,64px);gap:4px;justify-content:center}
.cell{position:relative;width:64px;height:58px;border-radius:5px;background:#e9e4d3;border:1px solid #b9b3a0;display:flex;align-items:flex-end;justify-content:center;cursor:default}
.cell.ally{background:#c3cdb9;border-color:#93a186}
.cell.enemy{background:#d9cba6;border-color:#b3a67e}
.cell.bench{background:#e6e0cf;border-style:dashed}
.cell.ebench{background:#e6e0cf;border-style:dashed;opacity:.55}
.cell.empty-ally{cursor:pointer}
.cell img{width:50px;height:50px;image-rendering:pixelated;object-fit:contain;position:relative;z-index:2;pointer-events:none}
.cell .ring{position:absolute;left:8px;right:8px;bottom:2px;height:7px;border:2px solid #29302b;border-radius:4px;z-index:1;pointer-events:none}
.cell .cnt{position:absolute;top:1px;right:3px;font-size:11px;color:#fff;background:#355c3d;border-radius:3px;padding:0 3px;z-index:3}
.cell .eq{position:absolute;top:1px;left:3px;font-size:10px;text-decoration:none;color:#5a4a00;background:radial-gradient(circle,#ffd040,#c99b4a);border-radius:50%;width:16px;height:16px;line-height:16px;text-align:center;z-index:3;font-style:normal}
.cell .rng{position:absolute;bottom:2px;right:2px;font-size:10px;font-style:normal;color:#fff;border-radius:3px;padding:0 3px;line-height:14px;z-index:3}
.cell .rng.near{background:#8a4a2f}.cell .rng.far{background:#2f5a8a}
#warnfight{display:none;color:#fff;background:#8a2f27;border-radius:4px;padding:6px 10px;font-size:12px;animation:blink 1.2s infinite}
@keyframes blink{50%{opacity:.55}}
.cell.has-item{box-shadow:0 0 0 2px #e0a010 inset}
.cell.sel{outline:3px solid #355c3d;outline-offset:1px;z-index:5}
.cell.pickme{outline:3px dashed #c99b4a;outline-offset:1px}
.midline{display:flex;align-items:center;gap:8px;color:#555e54;font-size:12px;margin:6px 0}
.midline:before,.midline:after{content:"";flex:1;border-top:2px dashed #899081}
#info{min-height:56px;background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:8px 10px;margin-top:10px;font-size:13px}
#info .btns{margin-top:6px;display:flex;gap:8px;flex-wrap:wrap}
#info button{min-height:30px;padding:4px 10px}
/* 商店 */
#shop{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}
.shopcell{background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:6px;cursor:pointer;text-align:center}
.shopcell:hover{background:#e2e8d8}
.shopcell img{width:56px;height:56px;image-rendering:pixelated;object-fit:contain}
.shopcell .nm{font-size:12px}
.shopcell .pr{font-size:12px;color:#8a5a17}
.shopcell.off{opacity:.4;cursor:default}
#actions{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
#actions button{flex:1;min-width:96px}
/* 侧栏 */
.syrow{display:flex;align-items:center;gap:6px;padding:3px 4px;border-radius:3px;font-size:12px}
.syrow.on{background:#e5efe0}
.syrow .dot{width:10px;height:10px;border-radius:3px;flex:none}
.syrow .cnt2{margin-left:auto;color:#555e54}
.itrow{display:flex;align-items:center;gap:6px;font-size:12px;padding:3px 2px;flex-wrap:wrap}
.itrow button{min-height:26px;padding:2px 8px;font-size:12px}
.itchip{border:1px solid #c99b4a;background:#f7ecd2;border-radius:4px;padding:2px 8px;cursor:pointer;font-size:12px}
.itchip.on{outline:2px solid #c99b4a}
.strow{display:flex;gap:8px;align-items:center;font-size:12px;padding:2px 4px}
.strow .hpbar{flex:1;height:8px;background:#e6e0cf;border-radius:3px;overflow:hidden}
.strow .hpbar i{display:block;height:100%;background:#7fa383}
.strow.dead{opacity:.5;text-decoration:line-through}
#log{font-size:12px;max-height:180px;overflow-y:auto;line-height:1.5}
/* 战斗浮层 */
#overlay{position:fixed;inset:0;background:rgba(23,29,39,.82);display:none;align-items:center;justify-content:center;z-index:50;padding:12px}
#overlay.show{display:flex}
.bwrap{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;justify-content:center;max-height:96vh}
.bstage{background:#171d27;border:2px solid #899081;border-radius:10px;padding:12px}
canvas{display:block;width:480px;max-width:92vw;image-rendering:pixelated;background:#171d27;border-radius:4px}
.bctl{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;justify-content:center}
.bctl button{min-height:32px;padding:4px 10px;background:#fffdf5}
.bside{width:min(360px,92vw);max-height:92vh;overflow-y:auto}
.bside .panel{margin-bottom:10px}
#evlist{font-size:12px;max-height:300px;overflow-y:auto}
#evlist div{padding:1px 6px;border-radius:3px;color:#8b938a}
#evlist div.past{color:#3d453f}
#evlist div.now{background:#e5efe0;color:#28432c;font-weight:600}
#battle-report{font-size:13px;line-height:1.7}
.rank1{color:#8a5a17;font-weight:700}
/* toast */
#toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#292c35;color:#f2e8c9;padding:10px 18px;border-radius:6px;opacity:0;transition:opacity .25s;pointer-events:none;z-index:99;max-width:80vw;font-size:13px}
#toast.show{opacity:.96}
#toast.err{background:#8a2f27;color:#fff}
</style><link rel="stylesheet" href="/tools/acceptance/ui_theme.css"></head><body data-page="demo"><main>
<header>
<h1>宝可梦自走棋 · 战术棋盘</h1>
<span class="muted">招募伙伴，搭配羁绊，排出你的上场阵容。</span>
<span style="flex:1"></span>
<input id="seedin" type="number" placeholder="随机种子" style="width:110px" title="留空随机；填整数可复现对局">
<button class="primary" onclick="newGame()">开新经典对局</button>
<a href="/expedition">远征手册 · 挑战 / 主搭档</a>
<a id="device-link" href="/device">三键设备试玩</a>
<a href="/" class="muted">← 验收后台</a>
</header>
<details class="save-tools"><summary>存档与备份 · 每次成功操作后自动保存</summary><div class="panel">
  <button onclick="api('save')">保存进度</button>
  <button onclick="resumeGame()">继续存档</button>
  <button onclick="downloadBackup()">下载备份</button>
  <label>导入备份 <input id="backup-file" type="file" accept=".ptsave,application/json" onchange="inspectBackup(this.files[0])" style="max-width:230px"></label>
  <button onclick="api('restore_checkpoint')">恢复导入前进度</button>
  <p id="save-status" class="muted">每次操作成功后自动保存到本机服务；下载备份可另行保管。</p>
  <div id="import-preview" hidden><p id="import-info"></p><button class="primary" onclick="confirmImport()">确认导入并保留当前进度备份</button><button onclick="cancelImport()">取消导入</button></div>
</div>
</details>
<div id="expedition-status" class="panel" hidden></div>
<div id="hud" class="muted">加载中…</div>
<div class="cols">
<section>
  <div id="arena"></div>
  <div id="info" class="muted">点击商店买入 → 点击棋子 → 点击目标格摆位。3 只同种自动进化！</div>
  <div id="shop"></div>
  <div id="actions">
    <button id="btn-refresh" onclick="api('refresh')">刷新（2 金）</button>
    <button id="btn-lock" onclick="api('lock')">锁定商店</button>
    <button id="btn-xp" onclick="api('levelup')">买经验（4 金 +4XP）</button>
    <button id="btn-fill" onclick="fillBoard()">一键上场</button>
    <button id="btn-auto" onclick="toggleAuto()">▶ 自动试玩</button>
    <button id="btn-fight" class="primary" onclick="endPrep()">开战 ▶</button>
    <span id="warnfight">⚠ 上场为空</span>
  </div>
  <div id="confirm-empty" class="panel" hidden>
    <p>上场为空，开战会直接判负掉血。可以先买棋上场，也可以继续空场战斗。</p>
    <button onclick="endPrep(true)">确认空场开战</button>
    <button onclick="document.getElementById('confirm-empty').hidden=true">返回布阵</button>
  </div>
  <div id="result-panel" class="panel" hidden aria-live="polite"></div>
  <div id="spectate-actions" hidden>
    <button onclick="nextRound()">观战下一轮</button>
    <button class="primary" onclick="api('finish')">快进至最终排名</button>
  </div>
  <div id="round-actions" hidden>
    <button onclick="openBattle()">查看本轮结算</button>
    <button id="btn-resume-next" class="primary" onclick="nextRound()">进入下一轮</button>
  </div>
  <p class="muted" id="tips">准备阶段不限时；开战后自动战斗。败方掉血 = 2 + 对方存活棋子 × 阶段系数；每 5 轮野怪轮掉装备组件。HP 归零淘汰，活到最后就是冠军。</p>
</section>
<aside>
  <div class="panel"><h3>羁绊（按上场阵容）</h3><div id="syn" class="muted">—</div></div>
  <div class="panel"><h3>装备仓库</h3><div id="items" class="muted">—</div></div>
  <div class="panel"><h3>场上局势</h3><div id="standings"></div></div>
  <div class="panel"><h3>战报</h3><div id="log" class="muted">—</div></div>
</aside>
</div>
</main>
<div id="overlay"><div class="bwrap">
  <div class="bstage">
    <canvas id="cv" width="240" height="320"></canvas>
    <div class="bctl">
      <button onclick="btoggle()" id="bplay">▶ 播放</button>
      <select id="bspeed" onchange="bspeed()"><option value="1" selected>1x</option><option value="2">2x</option><option value="4">4x</option></select>
      <button onclick="breplay()">↻ 重播</button>
      <button onclick="bskip()">跳过 ⏭</button>
    </div>
    <p class="muted" id="bstatus" style="text-align:center;color:#b9b3a0;margin:6px 0 0"></p>
  </div>
  <div class="bside">
    <div class="panel"><h3 id="bhead">战斗</h3><div id="battle-report"></div>
      <div style="margin-top:10px"><button class="primary" style="width:100%" onclick="nextRound()" id="btn-next">下一轮 ▶</button></div>
    </div>
    <div class="panel"><h3>事件流（与画面逐条对照）</h3><div id="evlist"></div></div>
  </div>
</div></div>
<div id="toast"></div>
<script>
let S=null, sid="", selLoc=null, equipKey=null;
const $=id=>document.getElementById(id);
const escapeText=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function rememberSlot(){try{localStorage.setItem('poketactics.slot',sid);}catch(e){$('save-status').textContent='浏览器无法记住存档编号，请下载备份';}}
function savedSlot(){try{return localStorage.getItem('poketactics.slot')||'';}catch(e){return '';}}
function receiveState(j){if(j.ok&&j.state){sid=j.sid||j.state.sid;rememberSlot();S=j.state;render();}}
function rememberRecovery(j){if(j.recovery_sid){sid=j.recovery_sid;rememberSlot();$('save-status').textContent=j.error;}}
function toast(t,err){const el=$('toast');el.textContent=t;el.className='show'+(err?' err':'');clearTimeout(el._t);el._t=setTimeout(()=>el.className='',2600);}
async function api(cmd,params={}){
  const q=new URLSearchParams({cmd,sid,...params});
  const r=await fetch('/api/demo/action?'+q.toString());
  const j=await r.json();
  rememberRecovery(j);
  if(!j.ok&&j.error){toast(j.error,true);if(j.dead){sid='';}}
  receiveState(j);
  if(j.msg)toast(j.msg);
  return j;
}
function newGame(){autoStop();closeBattle();selLoc=equipKey=null;api('new',{seed:$('seedin').value}).then(j=>{if(j.ok)toast('对局开始 · 种子 '+S.seed+'：先买几只棋子上场吧');});}
async function resumeGame(){autoStop();closeBattle();selLoc=equipKey=null;const slot=sid||savedSlot();if(!slot){toast('没有记录到存档编号，可导入备份或开新局',true);return;}const j=await api('resume',{sid:slot});if(!j.ok)$('save-status').textContent=j.error;}
function downloadBackup(){if(!sid){toast('请先继续存档或开新局',true);return;}const link=document.createElement('a');link.href='/api/demo/backup?sid='+encodeURIComponent(sid);link.download='PokeTactics.ptsave';link.click();}
let pendingBackup=null;
function cancelImport(){pendingBackup=null;$('import-preview').hidden=true;$('backup-file').value='';}
async function backupRequest(path,raw){const response=await fetch(path+'?sid='+encodeURIComponent(sid),{method:'POST',headers:{'Content-Type':'application/json','X-PokeTactics-Import':'1'},body:raw});return response.json();}
async function inspectBackup(file){
  if(!file)return;autoStop();closeBattle();
  if(file.size>512*1024){toast('备份文件超过512KB',true);cancelImport();return;}
  try{const raw=await file.text();const j=await backupRequest('/api/demo/import/inspect',raw);if(!j.ok){toast(j.error,true);cancelImport();return;}
    pendingBackup=raw;$('import-preview').hidden=false;const p=j.preview;
    $('import-info').textContent=`备份为第 ${p.round} 轮，${p.hp} HP / ${p.gold} 金。导入前会保留当前进度，可通过“恢复导入前进度”找回。${p.warning||''}`;
  }catch(e){toast('备份读取失败：'+e.message,true);cancelImport();}
}
async function confirmImport(){if(!pendingBackup)return;try{const j=await backupRequest('/api/demo/import',pendingBackup);rememberRecovery(j);if(j.ok){selLoc=equipKey=null;receiveState(j);cancelImport();toast(j.msg);}else toast(j.error,true);}catch(e){toast('导入失败：'+e.message,true);}}
/* ---------- 渲染 ---------- */
function pieceCell(v,loc,cls){
  /* 空格子也带 data-loc（仅我方格）——2026-09-14 E2E 发现的 UI 级根因：
     空格无 data-loc 则点击委托命中不了，玩家没有任何途径把棋子放上场
     （只能空场开战 → 无帧 → 播放器黑屏）。敌方格保持不可点。 */
  if(!v)return `<div class="cell ${cls}"${(cls.includes('ally')||cls.includes('bench'))&&loc?` data-loc="${loc}"`:''}></div>`;
  const sel=(selLoc===loc)?' sel':'';
  const pick=(equipKey&&(cls.includes('ally')||cls.includes('bench')))?' pickme':'';
  return `<div class="cell ${cls}${sel}${pick}${v.item?' has-item':''}" data-loc="${loc}" title="${v.name} ${v.tier}费 ${v.types.join('/')} ${v.ranged?'远程':'近战'} 招式:${v.move}${v.item?' 装备:'+v.item_name:''}">
    <img loading="lazy" src="/demo/sprite/${v.sid}.png" draggable="false">
    <i class="ring" style="border-color:${v.colors[0]}"></i>
    <i class="rng ${v.ranged?'far':'near'}" title="射程 ${v.range} 格">${v.ranged?'远':'近'}</i>
    ${v.copies>=2?`<b class="cnt">×${Math.min(v.copies,3)}</b>`:''}
    ${v.item?'<i class="eq">装</i>':''}</div>`;
}
function render(){
  if(!S)return;
  $('device-link').href='/device?sid='+encodeURIComponent(S.sid);
  const y=S.you;
  const ex=S.expedition; $('expedition-status').hidden=!ex;
  if(ex)$('expedition-status').textContent='主搭档 '+ex.partner+' · '+ex.trait+'｜'+(ex.active?'当前伙伴：'+ex.active:'尚未上场，特性未激活')+'。'+ex.description+(ex.technique?' 学习 '+ex.technique.name+'：'+ex.technique.description:'');
  $('save-status').textContent=(S.profile_warning||'')+(S.save?.sequence?'已保存 · 第 '+S.save.sequence+' 次提交。':'')+(S.save?.warning||'每次操作自动保存；服务重启后可继续。');
  /* HUD */
  const w=S.weather;
  $('hud').innerHTML=[
    `<span class="hudchip">❤ HP <b>${y.hp}</b></span>`,
    `<span class="hudchip">🪙 <b>${y.gold}</b> 金</span>`,
    `<span class="hudchip">Lv${y.level} <span class="muted">(${y.xp}/${y.xp_next??'满'})</span> 人口 <b>${y.on_board}/${y.pop}</b></span>`,
    `<span class="hudchip">第 <b>${S.round}</b>/${S.max_rounds} 轮</span>`,
    `<span class="hudchip">${w.zh==='无'?'🌤':w.key==='sun'?'☀️':w.key==='rain'?'🌧️':w.key==='sand'?'🌪️':w.key==='hail'?'❄️':'🌤'} ${w.zh}<span class="muted">（${w.note}）</span></span>`,
    S.entry_weather?`<span class="hudchip">${S.entry_weather.note}</span>`:'',
    y.streak?`<span class="hudchip">${y.streak>0?'🔥 连胜':'💤 连败'} <b>${Math.abs(y.streak)}</b></span>`:'',
    `<span class="hudchip muted">${S.phase==='prep'?'准备阶段（不限时）':S.phase==='battle'?'结算阶段':'终局'}</span>`,
    y.alive?'':`<span class="hudchip" style="color:#8a2f27">已淘汰（第 ${y.rank} 名）</span>`
  ].join('');
  /* 棋盘 */
  const ov=S.opponent;
  let ar=`<div class="rowtag">敌方备战（${ov?ov.name:'—'} 的快照）</div>`;
  ar+=`<div class="grid">${(ov?ov.bench:[]).concat(Array(6).fill(null)).slice(0,6).map(v=>pieceCell(v,'','ebench')).join('')}</div>`;
  const erows=ov?ov.rows:[[],[]];
  ar+=`<div class="grid">${(erows[0]||[]).concat(Array(6).fill(null)).slice(0,6).map(v=>pieceCell(v,'','enemy')).join('')}</div>`;
  ar+=`<div class="grid">${(erows[1]||[]).concat(Array(6).fill(null)).slice(0,6).map(v=>pieceCell(v,'','enemy')).join('')}</div>`;
  ar+=`<div class="midline">战 场 中 线</div>`;
  ar+=`<div class="grid">${S.board[0].map((v,c)=>pieceCell(v,`g0,${c}`,'ally empty-ally')).join('')}</div>`;
  ar+=`<div class="grid">${S.board[1].map((v,c)=>pieceCell(v,`g1,${c}`,'ally empty-ally')).join('')}</div>`;
  ar+=`<div class="rowtag">我方备战（${S.bench.length}/${y.bench_cap}）</div>`;
  ar+=`<div class="grid">${Array(6).fill(null).map((_,i)=>pieceCell(S.bench[i]||null,`b${i}`,'bench empty-ally')).join('')}</div>`;
  $('arena').innerHTML=ar;
  /* 选中信息 */
  renderInfo();
  /* 商店 */
  const canBuy=S.phase==='prep'&&y.alive;
  $('confirm-empty').hidden=true;
  $('shop').innerHTML=S.shop.map((v,i)=>v?`<div class="shopcell ${canBuy?'':'off'}" data-shop="${i}" title="${v.types.join('/')} ${v.ranged?'远程':'近战'} · ${v.move}">
    <img loading="lazy" src="/demo/sprite/${v.sid}.png"><div class="nm">${v.name}</div><div class="pr">🪙${v.price} · ${v.tier}费 · <b style="color:${v.ranged?'#2f5a8a':'#8a4a2f'}">${v.ranged?'远程':'近战'}</b></div><div class="muted">${v.skill_name} · 射程${v.range}</div></div>`:
    `<div class="shopcell off"><div class="nm muted">空</div></div>`).join('');
  $('btn-refresh').disabled=$('btn-xp').disabled=$('btn-fight').disabled=$('btn-lock').disabled=!canBuy;
  $('btn-lock').textContent=y.shop_locked?'🔒 已锁定（点击解锁）':'锁定商店';
  $('btn-fight').style.display=(S.phase==='prep')?'':'none';
  $('spectate-actions').hidden=y.alive||S.phase==='over';
  $('round-actions').hidden=S.phase!=='battle';
  const result=S.player_result;
  $('result-panel').hidden=!result;
  $('result-panel').innerHTML=result?`<b>${S.phase==='over'?'对局结束':'你已淘汰'} · 第 ${result.rank} 名</b><p>第 ${result.round} 轮阵容：${result.team.map(v=>v.name).join('、')||'空场'}</p>`+(S.over?'<b>最终排名</b><ol>'+S.over.ranking.map(r=>`<li>${r.is_you?'★ ':''}${r.name} · ${r.hp} HP</li>`).join('')+'</ol>':'<p>可继续逐轮观战，或快进查看最终排名。</p>'):'';
  /* 空场防呆：按当前状态给下一步指引（2026-09-14 用户反馈——棋子买了/
     选中了但还在备战时，「上场为空」读起来像矛盾，改为指引文案） */
  const wf=$('warnfight');
  const benchN=S.bench.filter(Boolean).length;
  if(S.phase==='prep'&&y.alive&&y.on_board===0){
    wf.style.display='inline-block';
    wf.textContent=selLoc?'→ 已选中棋子：点击棋盘任意格完成上场':
      (benchN?'⚠ 棋子还在备战席（'+benchN+' 只）：点棋子 → 点棋盘格上场，或点「一键上场」':
              '⚠ 上场为空：先从下方商店买几只棋子');
  }else wf.style.display='none';
  $('btn-fill').style.display=(S.phase==='prep'&&y.alive&&benchN&&y.on_board<y.pop)?'':'none';
  /* 羁绊 */
  $('syn').innerHTML=S.synergies.length?S.synergies.map(s=>`<div class="syrow ${s.tier?'on':''}">
    <span class="dot" style="background:${s.color}"></span><b>${s.zh}</b> ×${s.n}
    ${s.tier?`<span class="badge on">(${s.tier}) ${s.effect}</span>`:'<span class="muted">未激活</span>'}
    <span class="cnt2">${s.next?`还差 ${s.need} 只到 (${s.next})`:'已满档'}</span></div>`).join(''):'<span class="muted">上场棋子后显示羁绊计数</span>';
  /* 装备 */
  let it='';
  it+='<div class="itrow"><b>组件</b>：'+(S.items.components.length?S.items.components.map(c=>`<span class="itchip" style="cursor:default;border-color:#899081;background:#e9e4d3">${c.name}×${c.n}</span>`).join(' '):'<span class="muted">暂无（野怪轮掉落）</span>')+'</div>';
  it+='<div class="itrow"><b>可合成</b>：'+(S.items.craftable.length?S.items.craftable.map(c=>`<button onclick="api(\'craft\',{item:\'${c.key}\'})" title="${c.recipe} → ${c.effect}">${c.name}</button>`).join(' '):'<span class="muted">组件凑齐配方后出现</span>')+'</div>';
  it+='<div class="itrow"><b>成品</b>：'+(S.items.finished.length?S.items.finished.map(f=>`<span class="itchip ${equipKey===f.key?'on':''}" data-item="${f.key}" title="${f.effect}（点击后选择棋子装备）">${f.name}</span>`).join(' '):'<span class="muted">无</span>')+'</div>';
  $('items').innerHTML=it;
  $('items').innerHTML+='<div class="itrow"><b>技能机</b>：'+(S.techniques.inventory.length?S.techniques.inventory.map(t=>escapeText(t.name)+' ×'+t.count).join('、'):'暂无（远征野怪轮掉落）')+' · <a href="/device?sid='+encodeURIComponent(S.sid)+'">三键选择目标并学习</a></div>';
  /* 排名 */
  $('standings').innerHTML=S.standings.map(e=>`<div class="strow ${e.alive?'':'dead'}">
    <b style="width:8em;overflow:hidden;text-overflow:ellipsis">${e.is_you?'★ ':''}${e.name}</b>
    <span class="hpbar"><i style="width:${Math.max(0,e.hp)}%"></i></span>
    <span class="muted">${e.hp}HP L${e.level}${e.rank?' 第'+e.rank+'名':''}</span></div>`).join('');
  /* 战报 */
  $('log').innerHTML=S.log.length?S.log.map(l=>`<div>${escapeText(l)}</div>`).join(''):'<span class="muted">尚无战报</span>';
}
function findPiece(loc){
  if(loc.startsWith('b'))return S.bench[+loc.slice(1)];
  const m=loc.slice(1).split(',');
  return S.board[+m[0]][+m[1]];
}
function renderInfo(){
  const el=$('info');
  if(!selLoc){el.className='muted';el.innerHTML='点击商店买入 → 点击棋子 → 点击目标格摆位。3 只同种自动进化！金环 = 持有装备。';return;}
  const v=findPiece(selLoc);
  if(!v){selLoc=null;return renderInfo();}
  el.className='';
  el.innerHTML=`<b>${v.name}</b> · ${v.tier} 费 · ${v.types.join('/')} · ${v.role} · 射程 ${v.range} · 招式「${v.move}」${v.copies>=2?` · 同种已有 ${v.copies} 只（3 只自动进化）`:''}${v.item?` · 装备「${v.item_name}」`:''}<p><b>${v.skill_name}</b>：${v.skill_description}</p>${v.ability?`<p>特性「${v.ability.name}」：${v.ability.description}</p>`:''}${v.technique?`<p>教学「${v.technique.name}」：${v.technique.description}</p>`:''}${v.item_effect?`<p>${v.item_name}：${v.item_effect}</p>`:''}
  <div class="btns"><button onclick="api('sell',{loc:selLoc}).then(()=>{selLoc=null})">卖出（+${v.sell} 金）</button>
  ${v.item?`<button onclick="api('unequip',{loc:selLoc})">卸下装备</button>`:''}</div>`;
}
/* ---------- 点击流 ---------- */
document.addEventListener('click',e=>{
  const shop=e.target.closest('[data-shop]');
  if(shop){if(!shop.classList.contains('off'))api('buy',{i:shop.dataset.shop});return;}
  const item=e.target.closest('[data-item]');
  if(item){equipKey=(equipKey===item.dataset.item)?null:item.dataset.item;toast(equipKey?'已选中装备，点击要装备的棋子（金框提示中）':'已取消选择');render();return;}
  const cell=e.target.closest('[data-loc]');
  if(!cell||!cell.dataset.loc)return;
  onCell(cell.dataset.loc);
});
function onCell(loc){
  if(!S||S.phase!=='prep'||!S.you.alive)return;
  const isMine=!loc.startsWith('x');
  if(!isMine)return;
  if(equipKey){api('equip',{item:equipKey,loc}).then(j=>{if(j.ok)equipKey=null;});return;}
  const v=findPiece(loc);
  if(selLoc===null){if(v)selLoc=loc;render();return;}
  if(selLoc===loc){selLoc=null;render();return;}
  const from=selLoc;selLoc=null;
  api('move',{from,to:loc});
}
async function fillBoard(){
  /* 一键上场：把备战棋子依次搬到棋盘空格（前排 g0 先填），人口满/备战空即停 */
  if(!S||S.phase!=='prep'||!S.you.alive)return;
  for(let k=0;k<12;k++){
    if(S.you.on_board>=S.you.pop){toast('人口已满（买经验升级可上场更多）');break;}
    const bi=S.bench.findIndex(Boolean);
    if(bi<0)break;
    let hole=null;
    for(const r of [0,1]){for(let c=0;c<6;c++){if(!S.board[r][c]){hole=`g${r},${c}`;break;}}if(hole)break;}
    if(!hole)break;
    const j=await api('move',{from:'b'+bi,to:hole});
    if(!j.ok)break;
  }
}
/* ---------- 自动试玩：客户端驱动完整一局（买棋→摆位→开战→播动画→下一轮→终局） ---------- */
let autoOn=false,autoGen=0;
const autoSleep=ms=>new Promise(r=>setTimeout(r,ms));
function toggleAuto(){
  autoOn=!autoOn;autoGen++;
  const b=$('btn-auto');
  b.textContent=autoOn?'⏸ 停止自动试玩':'▶ 自动试玩';
  b.classList.toggle('primary',autoOn);
  if(autoOn){const g=autoGen;autoLoop(g);toast('自动试玩开始：全程自动决策与播放，可随时接手');}
}
function autoStop(msg){if(!autoOn)return;autoOn=false;autoGen++;$('btn-auto').classList.remove('primary');$('btn-auto').textContent='▶ 自动试玩';if(msg)toast(msg);}
function autoBoardPieces(){return [...S.board[0],...S.board[1]].filter(Boolean);}
function autoTypeCounts(){const c={};autoBoardPieces().forEach(v=>v.types.forEach(t=>c[t]=(c[t]||0)+1));return c;}
function autoTargetCell(v){
  /* 近战前排（g0 贴中线）、远程后排（g1）——与角标语义一致 */
  const rows=v&&v.ranged?[1,0]:[0,1];
  for(const r of rows)for(let c=0;c<6;c++)if(!S.board[r][c])return `g${r},${c}`;
  return null;
}
function autoWantBuy(){
  const y=S.you,mine=[...autoBoardPieces(),...S.bench.filter(Boolean)];
  if(S.bench.filter(Boolean).length>=y.bench_cap-1&&y.on_board>=y.pop)return -1;
  const tc=autoTypeCounts();
  let best=-1,score=-1;
  S.shop.forEach((c,i)=>{
    if(!c||y.gold-c.price<2)return;
    let s=c.tier*10;
    s+=mine.filter(v=>v.sid===c.sid).length*55;          /* 复制件：3合1 进度 */
    s+=c.types.reduce((a,t)=>a+(tc[t]||0)*9,0);          /* 供主羁绊 */
    if(s>score){score=s;best=i;}
  });
  return best;
}
function autoFirstFreeHand(){
  for(const r of [0,1])for(let c=0;c<6;c++){const v=S.board[r][c];if(v&&!v.item)return `g${r},${c}`;}
  for(let i=0;i<S.bench.length;i++){if(S.bench[i]&&!S.bench[i].item)return 'b'+i;}
  return null;
}
function autoAllFreeHands(){
  const spots=[];
  for(const r of [0,1])for(let c=0;c<6;c++){if(S.board[r][c]&&!S.board[r][c].item)spots.push(`g${r},${c}`);}
  for(let i=0;i<S.bench.length;i++){if(S.bench[i]&&!S.bench[i].item)spots.push('b'+i);}
  return spots;
}
let autoSkipRound=-1,autoSkipItems=new Set();
function autoTickSkip(){
  if(S&&S.round!==autoSkipRound){autoSkipRound=S.round;autoSkipItems.clear();}
}
async function autoStep(){
  if(!S)return;
  if(S.phase==='over'){
    const my=(S.over&&S.over.ranking||[]).find(e=>e.is_you);
    autoStop('自动试玩结束：'+(my?`第 ${my.rank} 名（${S.round} 轮）`:'终局'));return;
  }
  if(S.phase==='prep'){
    if(!S.you.alive){await api('next');return;}          /* 淘汰后观战快进 */
    const y=S.you;
    autoTickSkip();
    /* 决策优先级：合成 → 装备 → 上场 → 买棋 → 升级 → 刷新 → 卖冗余 → 开战。
       合成/装备失败（如进化石只走通信进化、围巾无载体）不 return——
       穿透到下一优先级继续行动，该成品本轮记跳防反复空打（R11 卡死
       根因：进化石装备被拒 + 状态不变 → 空闲超时）。 */
    for(const c of S.items.craftable||[]){
      if(autoSkipItems.has('craft:'+c.key))continue;
      const j=await api('craft',{item:c.key});
      if(j.ok)return;
      autoSkipItems.add('craft:'+c.key);
    }
    for(const f of S.items.finished||[]){
      if(autoSkipItems.has('equip:'+f.key))continue;
      let done=false;
      for(const loc of autoAllFreeHands()){
        const j=await api('equip',{item:f.key,loc});
        if(j.ok){done=true;break;}
      }
      if(done)return;
      autoSkipItems.add('equip:'+f.key);
    }
    if(y.on_board<y.pop){
      const bi=S.bench.findIndex(Boolean);
      if(bi>=0){const cell=autoTargetCell(S.bench[bi]);if(cell){await api('move',{from:'b'+bi,to:cell});return;}}
    }
    const want=autoWantBuy();
    if(want>=0){await api('buy',{i:want});return;}
    if(y.gold>=8&&y.level<7&&S.round>=4){await api('levelup');return;}
    if(y.gold>=8&&S.round>=6&&autoWantBuy()<0&&S.bench.filter(Boolean).length<y.bench_cap-2){await api('refresh');return;}
    if(S.bench.filter(Boolean).length>=y.bench_cap){await api('sell',{loc:'b'+(S.bench.filter(Boolean).length-1)});return;}
    await api('end_prep');openBattle();return;
  }
  /* battle：等动画播完再进下一轮（无帧场面短等即走） */
  if(!$('overlay').classList.contains('show'))openBattle();
  if(bn>0&&(playing||bcur<bn-1))return;
  await api('next');
}
async function autoLoop(gen){
  /* 卡死盯防的签名含全部会动的量（轮次/相位/金币/人口/等级/XP/备战/成品/
     播放游标）：准备期升级连买经验不涨轮次、战斗期逐帧播放不涨轮次，
     都是正常推进——只有签名完全不变才计空闲 */
  const sig=()=>S?[S.round,S.phase,S.you.gold,S.you.on_board,S.you.level,
    S.you.xp,S.bench.filter(Boolean).length,(S.items.finished||[]).length,
    (S.items.craftable||[]).length,bcur].join('|'):'';
  let last=sig(),idle=0;
  while(autoOn&&gen===autoGen){
    if(document.hidden){await autoSleep(600);continue;}   /* 后台标签不推进 */
    try{await autoStep();}catch(e){/* 单步失败退避重试 */}
    const now=sig();
    idle=now!==last?0:idle+1;
    last=now;
    if(idle>60){autoStop('自动试玩空闲超时停止（疑似异常）');return;}
    await autoSleep(S&&S.phase==='prep'?560:650);
  }
}
async function endPrep(allowEmpty=false){
  if(!allowEmpty&&!autoOn&&S.board[0].every(c=>!c)&&S.board[1].every(c=>!c)&&S.you.alive){
    $('confirm-empty').hidden=false;return;
  }
  const j=await api('end_prep');
  if(j.ok)openBattle();
}
async function nextRound(){
  if(S.phase==='over'){closeBattle();return;}
  const j=await api('next');
  closeBattle();
  if(j.ok&&S.phase==='over')toast('对局结束');
}
/* ---------- 战斗回放 ---------- */
let frames=[],bcur=0,bn=0,btimer=null,bspeedv=1,playing=false,bevs=[],bmeta=null,loadToken=0,bdt=0.05;
function openBattle(){
  ++loadToken;bmeta=S.last_battle;bdt=bmeta?.dt||0.05;frames=[];bcur=0;bn=0;bevs=[];playing=false;btimer&&clearInterval(btimer);btimer=null;
  $('overlay').classList.add('show');
  const rep=[];
  rep.push(`<b>${bmeta?bmeta.headline:''}</b>`);
  rep.push(...S.log.slice(-6).map(l=>`<div>${escapeText(l)}</div>`));
  if(S.phase==='over'&&S.over){rep.push('<hr><b>最终排名</b><ol style="margin:6px 0;padding-left:22px">'+S.over.ranking.map(r=>`<li class="${r.rank===1?'rank1':''}">${r.is_you?'★ ':''}${r.name}</li>`).join('')+'</ol>');}
  $('battle-report').innerHTML=rep.join('');
  $('btn-next').textContent=S.phase==='over'?'查看终局 ▶':'下一轮 ▶';
  if(!bmeta||!bmeta.n){
    $('bhead').textContent='战斗结算';
    const ctx=$('cv').getContext('2d');
    ctx.clearRect(0,0,240,320);
    /* 空场等原因没有帧：画布上直接给出大字说明，不再留黑屏 */
    ctx.fillStyle='#e8e2cf';ctx.textAlign='center';
    const restored=!!bmeta?.restored;
    ctx.font='bold 18px monospace';ctx.fillText(restored?'本轮结算已恢复':'本场无战斗画面',120,132);
    ctx.font='13px monospace';ctx.fillStyle='#b9b3a0';
    const why=restored?'历史回放帧未存入备份':S.you&&!S.you.alive?'你已被淘汰（观战快进）':
      (S.you&&S.you.on_board===0?'我方空场 · 不战而败掉血':'空场判负 / 野怪轮空');
    ctx.fillText(why,120,158);
    ctx.fillText(restored?'可直接进入下一轮':'下一轮记得买棋上场',120,178);
    $('bstatus').textContent=restored?'战果已保存，恢复不会重复发奖励；历史帧未保存':'本场无战斗画面（'+(S.you&&S.you.on_board===0?'我方空场':'空场判负/轮空')+'）';
    $('evlist').innerHTML='<div class="muted">本场景没有战斗事件流</div>';return;}
  $('bhead').textContent=`第 ${bmeta.round} 轮战斗 vs ${bmeta.opp_name}`;
  bevs=bmeta.events||[];
  $('evlist').innerHTML=bevs.map((e,i)=>`<div id="ev${i}">[${e.t.toFixed(1)}] ${e.text}</div>`).join('');
  bn=bmeta.n;
  loadAndPlay();
}
async function loadAndPlay(){
  const token=loadToken;
  $('bstatus').textContent='战斗帧载入中…（'+bn+' 帧）';
  const jobs=[];
  for(let i=0;i<bn;i++)jobs.push(new Promise(res=>{const im=new Image();im.onload=im.onerror=()=>res();im.src=`/demo/frame/${sid}/r${bmeta.round}/${i}.png`;frames[i]=im;}));
  await Promise.all(jobs);
  if(token!==loadToken)return;
  $('bstatus').textContent=bn+' 帧就绪 @'+Math.round(1/bdt)+'fps';
  play();
}
function bshow(i){
  bcur=Math.max(0,Math.min(bn-1,i));
  const im=frames[bcur];
  if(im&&im.width){const ctx=$('cv').getContext('2d');ctx.clearRect(0,0,240,320);ctx.drawImage(im,0,0);}
  $('bstatus').textContent=`第 ${bcur+1} / ${bn} 帧 · ${(bcur*bdt).toFixed(2)}s`;
  let last=-1;
  for(let j=0;j<bevs.length;j++){const el=$('ev'+j);if(!el)continue;const past=bevs[j].t<=bcur*bdt+1e-9;el.className=past?'past':'';if(past)last=j;}
  if(last>=0){const el=$('ev'+last);el.className='now';el.scrollIntoView({block:'nearest'});}
}
function btick(){bshow(bcur+1);if(bcur>=bn-1)stopPlay();}
function play(){if(playing||!bn)return;playing=true;$('bplay').textContent='⏸ 暂停';btimer=setInterval(btick,bdt*1000/bspeedv);}
function stopPlay(){playing=false;clearInterval(btimer);btimer=null;$('bplay').textContent='▶ 播放';}
function btoggle(){playing?stopPlay():(bcur>=bn-1&&bshow(0),play());}
function breplay(){stopPlay();bshow(0);play();}
function bskip(){stopPlay();bshow(bn-1);}
function bspeed(){bspeedv=+$('bspeed').value;if(playing){stopPlay();play();}}
function closeBattle(){++loadToken;stopPlay();$('overlay').classList.remove('show');}
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPlay();});
/* ---------- 启动 ---------- */
(async()=>{const query=new URLSearchParams(location.search);if(query.get('new')==='classic'){history.replaceState(null,'','/demo');newGame();return;}const linked=query.get('sid');if(linked&&/^[a-f0-9]{12}$/.test(linked))sid=linked;if(sid||savedSlot())await resumeGame();else newGame();})();
</script></body></html>"""
