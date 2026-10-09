#!/usr/bin/env python3
"""PokeTactics 验收后台（参考 PokeWalk tools/inspector 的服务模式）。

架构对齐 PokeWalk 固件同源预览的四条经验（docs/11、12）：
1. 浏览器不自行计算画面——帧由本地渲染器（现为 Python，M4 换 C 内核）产出，
   浏览器只做 Canvas 平移；动画逻辑只有一个来源（事件流回放）；
2. 确定性时间轴：播放器支持暂停/单步/倍速，标签页隐藏自动停钟
   （PokeWalk「预览默认实时、逐帧检查需暂停/单步 60ms」的同款纪律）；
3. 构建按源哈希键控：帧缓存目录 = seed + 渲染器源码哈希，改代码自动失效；
4. stdlib HTTP + /api/* JSON 路由（SimpleHTTPRequestHandler 扩展）。

启动：
    python3 tools/acceptance/server.py [--port 8799]
    浏览器打开 http://127.0.0.1:8799/
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "mockups"))
sys.path.insert(0, str(ROOT / "sim"))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # Web 可玩 Demo（demo.py）

from presentation_modes import normalize_mode, mode_info
from arena_scenarios import SCENARIOS as ARENA_SCENARIOS

import portal  # noqa: E402
import demo as demo_mod  # noqa: E402  /demo 页 + /api/demo/* 动作（只加挂接）

FPS_DT = 0.05
META_REV = "r5-presentation-20fps"  # 统一演出时钟；改轴后禁止沿用旧帧缓存
_LOCK = demo_mod._LOCK  # One rule-state lock shared by /anim and /demo.
_CACHE = {}  # seed -> (key, meta)

INDEX_HTML = """<!doctype html><html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>验收入口 · PokeTactics</title><style>
body{margin:0;background:#eeecdf;color:#29362e;font:14px/1.7 "PingFang SC",system-ui,sans-serif}main{max-width:1000px;padding:28px;margin:auto}a{color:#416345}h1{font-size:27px}h2{font-size:18px;margin-top:30px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card{background:#fafbf2;border:1px solid #bdc8ad;padding:16px;border-radius:7px;text-decoration:none}.card b{display:block;font-size:17px}.card span{color:#67745e}li{margin:5px 0}.note{padding:14px;border-left:3px solid #678453;background:#e0e8d5}
</style></head><body><main><header><a href="/tools">← 调试工具</a><h1>竞技试玩 · 预览与验收</h1>
<p>试玩、战斗预览、动作实验室、动画编辑器和新导出样片共享渲染器与当前角色目录。</p>
<p id="coverage" class="note">正在读取当前渲染版本与动作覆盖…</p></header>
<div class="grid">
<a class="card" href="/anim?mode=arena&seed=7"><b>战斗预览</b><span>960 × 640 · 真实战斗事件、暂停与逐帧</span></a>
<a class="card" href="/scenarios?mode=arena"><b>竞技场景库</b><span>分件动作、岩钉击退、异常追击、治疗防守</span></a>
<a class="card" href="/animation-lab?mode=arena"><b>动作实验室 / 靶场</b><span>当前 48 种精灵，六类动作实时样片</span></a>
<a class="card" href="/animation-editor?mode=arena"><b>动画编辑器</b><span>默认 / 调参对照，真实命中帧与生命快照</span></a>
</div>
<h2>检查重点</h2><ul><li>角色、原生技能和资源与试玩一致，一二世代共 48 种。</li>
<li>怪力四臂、雷丘耳尾、巨钳螳螂双钳双翼，以及御三家已有分件动作；其余角色的覆盖按目录实际标注。</li>
<li>施法、弹道、命中、治疗与退场跟随真实事件，拖动回卷不改变伤害和模拟结果。</li>
<li>动画参数只影响表现；独立预览不创建游戏局、不写入试玩存档。</li></ul>
<h2>经典 / 设备工具</h2><p>保留 84 种经典角色与 240 × 320 设备演出，用于经典规则和设备回归。</p>
<p><a href="/anim?mode=classic&seed=7">经典战斗</a> · <a href="/animation-editor?mode=classic">经典编辑器</a> · <a href="/scenarios?mode=classic">经典场景</a> · <a href="/device">设备面板</a></p>
<h2>使用说明与历史素材</h2><p><a href="/reference?path=docs/34-unified-preview-tools.md">预览工具与样片生成说明</a> · <a href="/mockups/battle_storyboard.png">早期设备分镜（历史参考）</a></p>
<h2>验证报告</h2><ul id="reports">加载中…</ul>
<script>fetch('/api/animation/characters?mode=arena').then(r=>r.json()).then(m=>{if(!m.ok)throw Error();document.getElementById('coverage').textContent=Object.keys(m.characters).length+' 种精灵 · '+m.width+' × '+m.height+' · '+m.render_revision;}).catch(()=>{document.getElementById('coverage').textContent='目录加载失败，请刷新重试。';});
fetch('/api/reports').then(r=>r.json()).then(files=>{const list=document.getElementById('reports');list.replaceChildren();for(const file of files.reverse()){const li=document.createElement('li'),a=document.createElement('a');a.href='/reference?path='+encodeURIComponent('reports/'+file);a.textContent=file;li.append(a);list.append(li);}});</script>
</main></body></html>"""


PLAYER_HTML = (Path(__file__).parent / 'battle_preview.html').read_text()


def _cached_battle(directory):
    """Only complete published frame sets are replayable; retry repairs missing frames."""
    try:
        meta = json.loads((directory / 'meta.json').read_text())
        count = meta['n']
        if type(count) is not int or not 0 < count <= 12000:
            return None
        if all((directory / f'{i}.png').is_file() and (directory / f'{i}.png').stat().st_size
               for i in range(count)):
            return meta
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def render_battle(seed: int, synergy: bool = False, scenario: str = None,
                  mode: str = 'arena') -> dict:
    """Render a save-free encounter with the shared trial/authoring renderer."""
    from presentation_modes import normalize_mode, mode_info, make_renderer
    from animation_preview import source_revision
    from arena_scenarios import SCENARIOS as ARENA_SCENARIOS, make_scene
    from decoders import Front, Font16, Palettes
    from render_battle_gif import BattleAnimation
    import status as status_mod
    import synergy as syn
    import combo as combo_mod
    import shutil
    import tempfile

    mode = normalize_mode(mode)
    scenarios = ARENA_SCENARIOS if mode == 'arena' else SCENARIOS
    if scenario and scenario not in scenarios:
        raise ValueError('所选场景不属于当前模式，请重新选择')
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError('种子必须为 0–4294967295 的整数')
    # Metadata also contains the shared event formatter and combination names.
    # Their changes must invalidate cached logs even when pixel frames are unchanged.
    event_sources = ''.join((Path(__file__).parent / name).read_text()
                            for name in ('demo.py', 'combination_view.py'))
    digest = hashlib.sha256((source_revision() + Path(__file__).read_text() + event_sources
                             + repr(FPS_DT)).encode()).hexdigest()[:12]
    key = f"{mode}_s{seed}_{int(synergy) if mode == 'classic' else 0}_{scenario or 'default'}_{digest}"
    out_dir = ROOT / '.build' / 'acceptance' / key
    meta_path = out_dir / 'meta.json'
    with _LOCK:
        cached = _cached_battle(out_dir)
        if cached:
            return cached
        previous = syn.SYNERGIES_ON, status_mod.STATUS_ON, combo_mod.COMBOS_ON
        temporary = None
        try:
            if mode == 'arena':
                anim = make_scene(seed, scenario)
                weather = None
            else:
                from roster import build_roster
                roster = build_roster()
                names = {p.name: p for ps in roster.values() for p in ps}
                sc = SCENARIOS.get(scenario) or {}
                a = sc.get('a', ('雷丘', '妙蛙花', '隆隆岩', '怪力', '水伊布'))
                b = sc.get('b', ('暴鲤龙', '喷火龙', '胡地', '大比鸟', '霸王花'))
                weather = sc.get('weather')
                syn.SYNERGIES_ON = synergy
                status_mod.STATUS_ON = bool(sc.get('status')) if scenario else previous[1]
                combo_mod.COMBOS_ON = bool(sc.get('combo'))
                anim = BattleAnimation([names[n] for n in a], [names[n] for n in b],
                                       seed, Front(), Palettes(), Font16(), weather_name=weather)
            renderer = make_renderer(anim, mode)
            duration = anim.presentation_duration
            out_dir.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=out_dir.parent))
            times = [round(i * FPS_DT, 8) for i in range(round(duration / FPS_DT) + 1)]
            for i, moment in enumerate(times):
                renderer.frame_playback(moment).convert('RGB').save(temporary / f'{i}.png', compress_level=2)
            fmt = demo_mod._fmt_event if mode == 'arena' else _fmt_event
            events = [{'t': round(renderer.playback_time(e[0]), 2), 'text': fmt(anim, e)}
                      for e in anim.presentation_events if e[1] != 'unit_state']
            events = [e for e in events if e['text']]
            fx = [('0.2', '开战演出')]
            first_attack = min((a for a in anim.timeline.actions if a.kind == 'attack'),
                               key=lambda a: a.impact, default=None)
            if first_attack:
                fx += [(round(renderer.playback_time(first_attack.start), 2), '普攻蓄力'),
                       (round(renderer.playback_time(first_attack.impact), 2), '普攻命中')]
            casts = sorted((a for a in anim.timeline.actions if a.kind == 'cast' and not a.secondary),
                           key=lambda a: a.impact)
            fx += [(round(renderer.playback_time(a.impact), 2), f'技能命中 {j+1}') for j, a in enumerate(casts[:10])]
            first_die = next((e[0] for e in anim.presentation_events if e[1] == 'die'), None)
            if first_die is not None:
                fx.append((round(renderer.playback_time(first_die + .1), 2), '退场演出'))
            meta = {**mode_info(mode), 'key': key, 'n': len(times), 'times': times,
                    'clock': 'presentation-v1', 'fps': 20, 'dt': FPS_DT,
                    'presentation_duration': duration,
                    'simulation_duration': max(e[0] for e in anim.events),
                    'events': events, 'result': next(e[2] for e in reversed(anim.events) if e[1] == 'end'),
                    'casts': sum(e[1] == 'cast' for e in anim.events),
                    'synergy': synergy if mode == 'classic' else None, 'fx': fx,
                    'scenario': scenario, 'scenario_label': (scenarios.get(scenario) or {}).get('label', ''),
                    'weather': weather,
                    'na': ' '.join(u.piece.name for u in anim.by_idx.values() if u.team == 0),
                    'nb': ' '.join(u.piece.name for u in anim.by_idx.values() if u.team == 1)}
            (temporary / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False))
            if out_dir.exists():
                shutil.rmtree(out_dir)
            temporary.replace(out_dir)
            temporary = None
            return meta
        finally:
            syn.SYNERGIES_ON, status_mod.STATUS_ON, combo_mod.COMBOS_ON = previous
            if temporary and temporary.exists():
                shutil.rmtree(temporary)


_MOVES_ZH = None


def _move_zh(name: str) -> str:
    """事件流 cast 存英文名（契约不变），面板显示层翻译。"""
    global _MOVES_ZH
    if _MOVES_ZH is None:
        import json as _j
        entries = _j.loads((ROOT / "data/moves.json").read_text())["entries"]
        _MOVES_ZH = {m["name"]: (m.get("name_zh") or m["name"]) for m in entries}
    return _MOVES_ZH.get(name, name)


def _fmt_event(anim, e: tuple) -> str:
    t, kind = e[0], e[1]
    name = lambda i: anim.by_idx[i].piece.name  # noqa: E731
    if kind == "deploy":
        return f"<b>{name(e[2])}</b> 落位 {e[3]}"
    if kind == "move":
        return f"{name(e[2])} 移动到 {e[3]}"
    if kind == "attack":
        return f"{name(e[2])} 普攻 {name(e[3])} <b>-{e[4]}</b>"
    if kind == "cast":
        eff = {0.5: "效果不佳", 2.0: "效果拔群", 4.0: "效果绝群"}.get(e[5], f"x{e[5]}")
        tail = " 未命中" if e[6] == 0 else f" <b>-{e[6]}</b>{(' ' + eff) if e[5] != 1 else ''}"
        return f"<b>{name(e[2])} 的 {_move_zh(e[4])}</b> → {name(e[3])}{tail}"
    if kind == "die":
        return f"<b>{name(e[2])} 倒下</b>"
    if kind == "combo":
        tz = {"ELECTRIC": "电", "WATER": "水", "FIRE": "火", "GRASS": "草",
              "POISON": "毒", "FLYING": "飞行", "NORMAL": "一般", "BUG": "虫",
              "GROUND": "地面", "ROCK": "岩", "FIGHTING": "格斗", "PSYCHIC": "超能",
              "GHOST": "幽灵", "DRAGON": "龙", "ICE": "冰", "STEEL": "钢", "DARK": "恶"}
        return f"<b>⚡ {e[4]}（{tz.get(e[3], e[3])}系齐射）</b>"
    if kind == "regen":
        return f"{name(e[2])} 回复 +{e[3]}"
    if kind == "status":
        zh = {"burn": "灼伤", "poison": "中毒", "paralysis": "麻痹", "freeze": "冰冻",
              "sleep": "睡眠", "flinch": "畏缩", "reflect": "反射壁", "lightscreen": "光墙",
              "swords": "剑舞"}.get(e[3], e[3])
        act = {"apply": "发作", "tick": "跳伤", "expire": "解除"}.get(e[4], e[4])
        tail = f" -{e[5]}" if len(e) > 5 and e[5] else ""
        return f"<b>{name(e[2])}</b> {zh}·{act}{tail}"
    return f"— end {e[2]}"




# ---- 全系统控制台（每系统一个后台页）----
CONSOLE_CSS = """
*{box-sizing:border-box}body{margin:0;background:#f2efe5;color:#29302b;font:14px/1.6 ui-monospace,"PingFang SC",monospace}
main{max-width:1080px;margin:auto;padding:24px}header{border-bottom:2px solid #29302b;padding-bottom:12px;margin-bottom:20px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:20px 0 8px}p{margin:6px 0;color:#555e54}a{color:#355c3d}
label{display:block;font-size:12px;margin:10px 0 4px}
input,select,button{font:inherit;color:inherit;background:#fffdf5;border:1px solid #899081;border-radius:3px;padding:8px}
button{cursor:pointer;min-height:38px}button:hover{background:#e2e8d8}button.primary{background:#355c3d;color:#fff;border-color:#355c3d}
table{border-collapse:collapse;width:100%;background:#fffdf5;font-size:12px}
th,td{border:1px solid #b9b3a0;padding:4px 8px;text-align:left}th{background:#e6e0cf;cursor:pointer}
tr:hover td{background:#e2e8d8}.tierbar{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px}
pre{background:#fffdf5;border:1px solid #899081;border-radius:4px;padding:10px;font-size:12px;white-space:pre-wrap;max-height:520px;overflow:auto}
.cardrow{display:flex;gap:10px;flex-wrap:wrap}.card{background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:10px;width:230px}
.card button{width:100%;margin-top:6px}.muted{color:#8b938a;font-size:12px}
.tabs{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.tabs a{text-decoration:none;color:inherit;border:1px solid #899081;border-radius:4px 4px 0 0;padding:4px 12px;font-size:13px;background:#e9e4d3}
.tabs a.on{background:#355c3d;color:#fff;border-color:#355c3d;font-weight:600}
"""

NAV = ""  # Global portal navigation replaces the older per-console tabs.

SCEN_HTML = ("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
             "<title>场景动画库 · PokeTactics</title><style>" + CONSOLE_CSS + "</style>"
             "<main><header><h1>场景动画库</h1>" + NAV + "</header>"
             "<p>每个分场景模拟的动画回放——与实验台文字读数一一对应。</p>"
             "<div class=cardrow>__CARDS__</div></main></body></html>")



ITEMS_HTML = ("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
              "<title>装备与道具 · PokeTactics</title><style>" + CONSOLE_CSS + "</style>"
              "<main><header><h1>经典规则 · 装备与道具（S5 v1）</h1>" + NAV + "</header>"
              "<h2>组件（野怪轮掉落 · 血量加权）</h2><div id=comps>加载中…</div>"
              "<h2>成品（两组件合成 · 每单位 1 格）</h2><div id=fin>加载中…</div>"
              "<p class=muted>装备默认关（experiment_items 开/关对照）；"
              "进化石=通信进化 catalyst（不消耗 · 每局一次）。</p></main>"
              "<script>Promise.all([fetch('/api/items').then(r=>r.json())]).then(([d])=>{"
              "document.getElementById('comps').innerHTML='<table><tr><th>组件</th><th>倾向</th></tr>'+"
              "d.components.map(c=>'<tr><td><b>'+c[1]+'</b></td><td>'+c[0]+'</td></tr>').join('')+'</table>';"
              "document.getElementById('fin').innerHTML='<table><tr><th>成品</th><th>配方</th><th>效果</th></tr>'+"
              "d.finished.map(f=>'<tr><td><b>'+f.name+'</b></td><td>'+f.recipe+'</td><td>'+f.effect+'</td></tr>').join('')+'</table>';});</script>"
              "</body></html>")


ROSTER_HTML = ("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
               "<title>棋子库 · PokeTactics</title><style>" + CONSOLE_CSS + "</style>"
               "<main><header><h1>经典规则 · 棋子库</h1>" + NAV + "</header>"
               "<p>经典规则 84 只池 · BST 定档（S2）。点列头排序。当前竞技试玩的 18 种精灵请查看 <a href=/pokedex>竞技图鉴</a>。</p>"
               "<label>筛选 <input id=q placeholder=中文名/属性/招式… style=width:280px></label>"
               "<div id=out>加载中…</div></main>"
               "<script>fetch('/api/roster').then(r=>r.json()).then(rows=>{"
               "let sortKey='tier',asc=true;"
               "const draw=()=>{const q=document.getElementById('q').value;"
               "const f=rows.filter(r=>!q||Object.values(r).join('').includes(q));"
               "f.sort((a,b)=>(asc?1:-1)*(a[sortKey]>b[sortKey]?1:a[sortKey]<b[sortKey]?-1:0));"
               "document.getElementById('out').innerHTML='<table><tr>'+"
               "['tier','name','bst','types','move','range','level'].map(k=>"
               "'<th data-k='+k+'>'+'档位/名称/BST/属性/招牌招/射程/等级'.split('/')[['tier','name','bst','types','move','range','level'].indexOf(k)]+'</th>').join('')+'</tr>'+"
               "f.map(r=>'<tr><td><span class=tierbar style=background:'+r.color+'></span>'+r.tier+'费</td>"
               "<td><b>'+r.name+'</b></td><td>'+r.bst+'</td><td>'+r.types+'</td>"
               "<td>'+r.move+'</td><td>'+(r.range>1?'远程':'近战')+'</td><td>L'+r.level+'</td></tr>').join('')+'</table>';"
               "document.querySelectorAll('th').forEach(th=>th.onclick=()=>{sortKey=th.dataset.k;asc=!asc;draw();});};"
               "draw();document.getElementById('q').oninput=draw;});</script></body></html>")

MATCH_HTML = ("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
              "<title>单局模拟 · PokeTactics</title><style>" + CONSOLE_CSS + "</style>"
              "<main><header><h1>单局模拟（8 bot 锦标赛）</h1>" + NAV + "</header>"
              "<label>master_seed <input id=seed type=number value=100 min=1 max=99999></label> "
              "<button class=primary onclick=run()>跑一局</button>"
              "<span class=muted>首次约 2-4 秒；同种子逐字节可复现（S7 分层子流）</span>"
              "<pre id=out>点「跑一局」开始</pre></main>"
              "<script>function run(){document.getElementById('out').textContent='运行中…';"
              "fetch('/api/match?seed='+document.getElementById('seed').value)"
              ".then(r=>r.text()).then(t=>document.getElementById('out').textContent=t);}</script>"
              "</body></html>")

EXP_HTML = ("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
            "<title>实验台 · PokeTactics</title><style>" + CONSOLE_CSS + "</style>"
            "<main><header><h1>实验台</h1>" + NAV + "</header>"
            "<p>服务端子进程执行既有对照实验（结果按 参数+sim 源哈希 缓存）。</p>"
            "<div class=cardrow id=cards>加载中…</div><pre id=out></pre></main>"
            "<script>const EXPS={effectiveness:'克制×倍率×等级 六臂',melee:'近远程补偿六臂',"
            "tiering:'BST 档位同质化',synergy:'羁绊开/关',weather:'四天气',status:'状态/Buff',"
            "balance:'ICE/BUG 平衡',match:'M2 四条验收(50局)'};"
            "fetch('/api/experiments').then(r=>r.json()).then(names=>"
            "fetch('/api/scenarios?mode=classic').then(r=>r.json()).then(scs=>{"
            "const byExp={};scs.forEach(x=>{(byExp[x.exp]=byExp[x.exp]||[]).push(x)});"
            "document.getElementById('cards').innerHTML=names.map(n=>"
            "'<div class=card><b>'+n+'</b><br><span class=muted>'+(EXPS[n]||'')+'</span>"
            "<button onclick=run(this) data-n='+n+'>运行</button>"
            "+((byExp[n]||[]).map(x=>'<br><a href=\'/anim?mode=classic&seed=7&scenario='+x.key+'\'>▶ '+x.label+'</a>').join(''))"
            "+'</div>').join('');});});"
            "function run(b){document.getElementById('out').textContent='运行中…（最长 60s）';"
            "fetch('/api/experiment?name='+b.dataset.n).then(r=>r.text())"
            ".then(t=>document.getElementById('out').textContent=t);}</script></body></html>")

SYN_HTML = ("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
            "<title>羁绊表 · PokeTactics</title><style>" + CONSOLE_CSS + "</style>"
            "<main><header><h1>经典规则 · 17 系羁绊表（S3，默认开）</h1>" + NAV + "</header>"
            "<div id=out>加载中…</div></main>"
            "<script>fetch('/api/synergy').then(r=>r.json()).then(t=>{"
            "document.getElementById('out').innerHTML='<table><tr><th>属性</th><th>(2)</th><th>(4)</th><th>(6)</th></tr>'+"
            "t.map(r=>'<tr><td><span class=tierbar style=background:'+r[3]+'></span><b>'+r[0]+'</b></td>"
            "<td>'+r[1]+'</td><td>'+r[2]+'</td><td>'+r[4]+'</td></tr>').join('')+'</table>';});</script>"
            "</body></html>")




# ---- 场景库：分场景模拟的动画预设（comp_a/comp_b 用棋子中文名）----
SCENARIOS = {
    "eff_clean_2x": {"exp": "effectiveness", "label": "克制 · 干净2x对位",
                     "a": ["水箭龟"] * 6, "b": ["喷火龙"] * 6, "weather": None},
    "eff_4x_rock": {"exp": "effectiveness", "label": "克制 · 4x+近战（岩地欠账）",
                    "a": ["水箭龟"] * 6, "b": ["隆隆岩"] * 6, "weather": None},
    "melee_counterpart": {"exp": "melee", "label": "近战 · 物特对照组",
                          "a": ["怪力"] * 6, "b": ["胡地"] * 6, "weather": None},
    "melee_lunge_pair": {"exp": "melee", "label": "近战 · 两段线终形态",
                         "a": ["风速狗"] * 6, "b": ["喷火龙"] * 6, "weather": None},
    "weather_rain": {"exp": "weather", "label": "天气 · 雨（水增益火减）",
                     "a": ["水箭龟", "水伊布", "宝石海星", "蚊香泳士", "哥达鸭", "水箭龟"],
                     "b": ["喷火龙", "风速狗", "胡地", "大比鸟", "霸王花", "喷火龙"],
                     "weather": "rain"},
    "weather_sun": {"exp": "weather", "label": "天气 · 晴（火增益水减）",
                    "a": ["水箭龟", "水伊布", "宝石海星", "蚊香泳士", "哥达鸭", "水箭龟"],
                    "b": ["喷火龙", "风速狗", "胡地", "大比鸟", "霸王花", "喷火龙"],
                    "weather": "sun"},
    "weather_sand": {"exp": "weather", "label": "天气 · 沙暴（岩地主场）",
                     "a": ["隆隆岩", "隆隆石", "尼多王", "尼多后", "大岩蛇", "钻角犀兽"],
                     "b": ["喷火龙", "妙蛙花", "水箭龟", "胡地", "大比鸟", "霸王花"],
                     "weather": "sand"},
    "syn_ice_bias": {"exp": "synergy", "label": "羁绊 · 冰偏置水队 vs 散件",
                     "a": ["拉普拉斯", "水箭龟", "水伊布", "宝石海星", "蚊香泳士", "哥达鸭"],
                     "b": ["喷火龙", "胡地", "怪力", "大比鸟", "霸王花", "妙蛙花"],
                     "weather": None},
    "syn_poison_deep": {"exp": "synergy", "label": "羁绊 · 毒深池 vs 飞行",
                        "a": ["尼多后", "尼多王", "大食花", "大针蜂", "臭臭花", "霸王花"],
                        "b": ["大比鸟", "喷火龙", "暴鲤龙", "大嘴蝠", "超音蝠", "烈雀"],
                        "weather": None},
    "status_shock": {"exp": "status", "label": "状态 · 电麻展示（自动开状态）",
                     "a": ["雷丘", "三合一磁怪", "雷伊布", "皮卡丘", "雷丘", "三合一磁怪"],
                     "b": ["水箭龟", "水伊布", "宝石海星", "蚊香泳士", "哥达鸭", "拉普拉斯"],
                     "weather": None, "status": True},
    "balance_pair": {"exp": "balance", "label": "平衡 · 水vs岩（上限检验）",
                     "a": ["水箭龟"] * 6, "b": ["隆隆岩"] * 6, "weather": None},
    "combo_volley": {"exp": "combo", "label": "组合技 · 电(6)雷霆万钧齐射（自动开）",
                     "a": ["雷丘", "皮卡丘", "三合一磁怪", "小磁怪", "雷伊布", "雷丘"],
                     "b": ["水箭龟", "水伊布", "宝石海星", "蚊香泳士", "哥达鸭", "拉普拉斯"],
                     "weather": None, "combo": True},
}
SCENARIO_SEED_DEFAULT = 7

def _sim_state_hash() -> str:
    h = hashlib.sha256()
    for rel in ("sim/combat.py", "sim/synergy.py", "sim/roster.py", "sim/status.py",
                "sim/weather.py", "sim/match.py", "sim/shop.py", "sim/bots.py",
                "sim/economy.py", "sim/rng.py", "sim/items.py"):
        f = ROOT / rel
        if f.exists():
            h.update(rel.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:10]


_EXP_CACHE = {}


WHITELIST = {
    "effectiveness": ["sim/experiment_effectiveness.py", "--games", "400", "--seed", "3"],
    "melee": ["sim/experiment_melee.py", "--games", "400", "--seed", "9"],
    "tiering": ["sim/experiment_tiering.py"],
    "synergy": ["sim/experiment_synergy.py", "--games", "400"],
    "weather": ["sim/experiment_weather.py", "--games", "400", "--seed", "3"],
    "status": ["sim/experiment_status.py", "--games", "400", "--seed", "12"],
    "balance": ["sim/experiment_balance.py", "--games", "400"],
    "match": ["sim/experiment_match.py", "--games", "20", "--seed", "5"],
}


def run_experiment(name: str) -> str:
    """白名单实验 / __match_<seed> 单局：服务端子进程执行，按 参数+sim 源哈希 缓存。"""
    import subprocess
    import sys as _sys
    if name.startswith("__match_"):
        cmd = [_sys.executable, "sim/match.py", "--bots", "8",
               "--seed", name.split("_")[-1]]
    elif name in WHITELIST:
        cmd = [_sys.executable] + WHITELIST[name]
    else:
        raise ValueError(f"未知实验: {name}")
    key = (name, _sim_state_hash())
    if key not in _EXP_CACHE:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
        _EXP_CACHE[key] = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return _EXP_CACHE[key]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args) -> None:
        pass  # 安静模式；准备动作单独打点

    def _txt(self, text: str, status: int = 200) -> None:
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/api/animation/preview", "/api/animation/preset/validate"):
            from animation_preview import MAX_REQUEST_BYTES, parse_request, normalize_preset, preview
            if self.headers.get("Origin") not in (None, f"http://{self.headers.get('Host')}"):
                return self._json({"ok": False, "error": "只允许本地页面预览"}, 403)
            if self.headers.get("X-PokeTactics-Preview") != "1":
                return self._json({"ok": False, "error": "缺少动画预览标记"}, 400)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST_BYTES:
                    return self._json({"ok": False, "error": "动画配置必须非空且不超过 8KB"}, 413)
                self.connection.settimeout(15)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("动画配置传输不完整")
                value = parse_request(raw)
                if parsed.path.endswith("/validate"):
                    result = {"ok": True, "preset": normalize_preset(value)}
                else:
                    with demo_mod._LOCK:
                        result = preview(value)
                return self._json(result)
            except (ValueError, TypeError) as exc:
                return self._json({"ok": False, "error": str(exc)}, 400)
            except (OSError, RuntimeError) as exc:
                return self._json({"ok": False, "error": "预览生成失败：" + str(exc)}, 500)
        profile_import = parsed.path in ("/api/expedition/import", "/api/expedition/import/inspect")
        if not profile_import and parsed.path not in ("/api/demo/import", "/api/demo/import/inspect"):
            return self.send_error(404)
        if self.headers.get("Origin") not in (None, f"http://{self.headers.get('Host')}"):
            return self._json({"ok": False, "error": "只允许本地页面导入"}, 403)
        if self.headers.get("X-PokeTactics-Import") != "1":
            return self._json({"ok": False, "error": "缺少导入标记"}, 400)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json({"ok": False, "error": "无效文件长度"}, 400)
        limit = 8 * 1024 * 1024 if profile_import else 512 * 1024
        if not 0 < length <= limit:
            return self._json({"ok": False, "error": f"备份必须非空且不超过 {limit // 1024}KB"}, 413)
        self.connection.settimeout(15)
        raw = self.rfile.read(length)
        if len(raw) != length:
            return self._json({"ok": False, "error": "备份传输不完整"}, 400)
        params = urllib.parse.parse_qs(parsed.query)
        if profile_import:
            from expedition import import_profile
            return self._json(import_profile(raw, parsed.path.endswith("/inspect")))
        self._json(demo_mod.import_backup(raw, params.get("sid", [None])[0],
                                         inspect_only=parsed.path.endswith("/inspect")))

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        requested = (ROOT / urllib.parse.unquote(parsed.path).lstrip("/")).resolve()
        if requested == demo_mod.SAVE_ROOT.resolve() or demo_mod.SAVE_ROOT.resolve() in requested.parents:
            return self.send_error(403, "Use the backup export endpoint")
        if parsed.path.rstrip('/') in ('', '/pokedex', '/guide', '/tools'):
            self._play_asset("hub.html", "text/html; charset=utf-8")
        elif parsed.path == "/api/portal/catalog":
            with _LOCK:
                self._json(portal.catalog_view(demo_mod))
        elif parsed.path == "/reference":
            relative = qs.get('path', [''])[0]
            document = (ROOT / relative).resolve()
            libraries = ((ROOT / 'docs').resolve(), (ROOT / 'reports').resolve())
            if document.suffix != '.md' or not document.is_file() or not any(
                    library in document.parents for library in libraries):
                return self.send_error(404, "Document not found")
            relative = document.relative_to(ROOT).as_posix()
            self._html(portal.document_view(relative, document.read_text()))
        elif parsed.path.startswith("/hub/assets/"):
            assets = {"/hub/assets/hub.css": ("hub.css", "text/css; charset=utf-8"),
                      "/hub/assets/hub.js": ("hub.js", "text/javascript; charset=utf-8"),
                      "/hub/assets/portal.css": ("portal.css", "text/css; charset=utf-8")}
            asset = assets.get(parsed.path)
            if asset is None:
                return self.send_error(404)
            self._play_asset(*asset)
        elif parsed.path in ("/play", "/play/"):
            self._play_asset("play.html", "text/html; charset=utf-8")
        elif parsed.path.startswith("/play/assets/"):
            assets = {
                "/play/assets/play.css": ("play.css", "text/css; charset=utf-8"),
                "/play/assets/play.js": ("play.js", "text/javascript; charset=utf-8"),
                "/play/assets/battle.css": ("battle.css", "text/css; charset=utf-8"),
            }
            asset = assets.get(parsed.path)
            if asset is None:
                return self.send_error(404)
            self._play_asset(*asset)
        elif parsed.path == "/acceptance":
            body = INDEX_HTML.encode()
            self._html(body)
        elif parsed.path == "/animation-lab":
            self._play_asset("animation_lab.html", "text/html; charset=utf-8")
        elif parsed.path == "/animation-editor":
            self._play_asset("animation_editor.html", "text/html; charset=utf-8")
        elif parsed.path == "/api/animation/characters":
            from character_catalog import character_catalog
            try:
                mode = normalize_mode(qs.get('mode', ['arena'])[0])
                with _LOCK:
                    self._json({'ok': True, **mode_info(mode),
                                'characters': character_catalog(mode=mode)})
            except ValueError as exc:
                self._json({'ok': False, 'error': str(exc)}, 400)
        elif parsed.path == "/anim":
            try:
                mode = normalize_mode(qs.get('mode', ['arena'])[0])
                seed = int(qs.get('seed', ['7'])[0])
                if not 0 <= seed <= 2**32 - 1:
                    raise ValueError('种子必须为 0–4294967295 的整数')
                syn_on = qs.get('synergy', ['1'])[0] == '1'
                scenario = qs.get('scenario', [''])[0] or None
                scenarios = ARENA_SCENARIOS if mode == 'arena' else SCENARIOS
                if scenario and scenario not in scenarios:
                    raise ValueError('所选场景不属于当前模式，请从场景库重新选择')
            except ValueError as exc:
                return self._txt(str(exc), 400)
            info = mode_info(mode)
            values = {'SEED': str(seed), 'MODE': mode, 'MODELABEL': info['label'],
                      'WIDTH': str(info['width']), 'HEIGHT': str(info['height']),
                      'SYN': '1' if syn_on else '0', 'SCEN': scenario or '',
                      'SCENLABEL': (scenarios.get(scenario) or {}).get('label', '竞技综合场景' if mode == 'arena' else '经典综合场景'),
                      'ARENA_CURRENT': 'aria-current="page"' if mode == 'arena' else '',
                      'CLASSIC_CURRENT': 'aria-current="page"' if mode == 'classic' else '',
                      'SYNHIDDEN': 'hidden' if mode == 'arena' else '',
                      'MODENOTE': ('48 种竞技精灵 · 每方三行站位。与试玩共享原生技能、属性特效和分件动作。' if mode == 'arena' else
                                   '经典 84 种角色 · 240 × 320 设备画面，保留经典羁绊与动画契约。')}
            body = PLAYER_HTML
            for key, value in values.items():
                body = body.replace('__' + key + '__', value)
            self._html(body)
        elif parsed.path == "/scenarios":
            try:
                mode = normalize_mode(qs.get('mode', ['arena'])[0])
            except ValueError as exc:
                return self._txt(str(exc), 400)
            scenes = ARENA_SCENARIOS if mode == 'arena' else SCENARIOS
            cards = []
            for key, scene in scenes.items():
                description = scene.get('description', scene['exp'] + ' 经典规则实验')
                cards.append(f'<div class="card"><b>{scene["label"]}</b>'
                             f'<p class="muted">{description}</p>'
                             f'<a href="/anim?mode={mode}&seed={SCENARIO_SEED_DEFAULT}&scenario={key}">'
                             '<button class="primary">播放场景</button></a></div>')
            body = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                    '<title>场景库 · PokeTactics</title><style>' + CONSOLE_CSS +
                    '.card{flex:1 1 260px;max-width:360px}.card p{min-height:44px}</style></head><body><main><header>'
                    f'<h1>{mode_info(mode)["label"]} · 场景库</h1>'
                    '<p>选择一个真实战斗场景，检查动作、属性特效与技能联动。</p>'
                    '<a href="/scenarios?mode=arena">竞技试玩</a> · '
                    '<a href="/scenarios?mode=classic">经典 / 设备</a> · <a href="/tools">调试工具</a></header>'
                    '<div class="cardrow">' + ''.join(cards) + '</div></main></body></html>')
            self._html(body)
        elif parsed.path == "/items":
            body = ITEMS_HTML.encode()
            self._html(body)
        elif parsed.path == "/api/items":
            import items as it
            comp_tendency = {"band": "物攻", "hardstone": "物防", "magnet": "特攻",
                             "shoes": "攻速", "bell": "回能", "charcoal": "火伤",
                             "mysticwater": "水伤", "spark": "电伤"}
            comps = [[comp_tendency.get(k, k), v] for k, v in it.COMPONENT_NAMES.items()]
            fin = []
            for key, spec in it.FINISHED.items():
                pairs = spec.get("pairs") or ((None,),)
                recipe = " + ".join(it.COMPONENT_NAMES.get(c, c)
                                    for c in pairs[0] if c) or "（进化石：任意两组件）"
                eff = []
                KEY_ZH2 = {"heal": "回血", "sash": "保命", "atk": "攻击", "spatk": "特攻",
                           "speed": "攻速", "dodge": "闪避", "ult": "大招", "fire": "火伤",
                           "water": "水伤", "electric": "电伤", "dr": "减伤", "gold": "金币",
                           "evo": "通信进化"}
                for k, v in spec.items():
                    if k in ("name", "pairs"):
                        continue
                    if isinstance(v, bool):
                        eff.append(KEY_ZH2.get(k, k))
                    elif isinstance(v, (int, float)):
                        eff.append(f"{KEY_ZH2.get(k, k)}+{round(v * 100, 1)}%")
                fin.append({"name": spec["name"], "recipe": recipe,
                            "effect": " ".join(eff) or "—"})
            self._json({"components": comps, "finished": fin})
        elif parsed.path in ("/roster", "/match", "/experiments", "/synergy"):
            page = {"/roster": ROSTER_HTML, "/match": MATCH_HTML,
                    "/experiments": EXP_HTML, "/synergy": SYN_HTML}[parsed.path]
            body = page.encode()
            self._html(body)
        elif parsed.path == "/api/prepare":
            try:
                seed = int(qs.get('seed', ['7'])[0])
                mode = normalize_mode(qs.get('mode', ['arena'])[0])
                syn_on = qs.get('synergy', ['1'])[0] == '1'
                scenario = qs.get('scenario', [''])[0] or None
                started = time.time()
                meta = render_battle(seed, syn_on, scenario, mode=mode)
                print(f"[acceptance] {mode} seed={seed} {time.time() - started:.1f}s key={meta['key']}")
                self._json(meta)
            except ValueError as exc:
                self._json({'ok': False, 'error': str(exc)}, 400)
            except (OSError, RuntimeError) as exc:
                self._json({'ok': False, 'error': '场景生成失败：' + str(exc)}, 500)
        elif parsed.path == "/api/roster":
            from roster import build_roster
            from data import pokedex
            dex = pokedex()
            rows = []
            for tier, pieces in sorted(build_roster().items()):
                for pc in pieces:
                    b = dex.species_record(pc.species_id)["base"]
                    mv = dex.moves.get(pc.move_id) if pc.move_id else None
                    from render_mockups import TYPE_COLORS
                    rows.append({
                        "tier": tier, "name": pc.name,
                        "bst": dex.bst(pc.species_id),
                        "types": "/".join(pc.types),
                        "move": (mv.get("name_zh") or mv["name"]) if mv else "—",
                        "range": pc.distance, "level": pc.level,
                        "color": "#{:02x}{:02x}{:02x}".format(*TYPE_COLORS[pc.types[0]]),
                    })
            rows.sort(key=lambda r: (r["tier"], -r["bst"]))
            self._json(rows)
        elif parsed.path == "/api/match":
            seed = int(qs.get("seed", ["100"])[0])
            with _LOCK:  # match 子进程读共享文件，串行化避免缓存竞态
                out = run_experiment(f"__match_{seed}")
            self._txt(out)
        elif parsed.path == "/api/scenarios":
            try:
                mode = normalize_mode(qs.get('mode', ['arena'])[0])
                scenes = ARENA_SCENARIOS if mode == 'arena' else SCENARIOS
                self._json([{'key': k, 'label': v['label'], 'exp': v['exp'], 'mode': mode}
                            for k, v in scenes.items()])
            except ValueError as exc:
                self._json({'ok': False, 'error': str(exc)}, 400)
        elif parsed.path == "/api/experiments":
            self._json(sorted(set(WHITELIST) - {k for k in WHITELIST if k.startswith("__")}))
        elif parsed.path == "/api/experiment":
            name = qs.get("name", [""])[0]
            try:
                self._txt(run_experiment(name))
            except Exception as exc:
                self._txt(f"运行失败: {exc}")
        elif parsed.path == "/api/synergy":
            import json as _j
            out = []
            try:
                import synergy as syn
                import re as _re
                from render_mockups import TYPE_COLORS
                tbl = getattr(syn, "SYNERGY_TABLE", None) or getattr(syn, "TIERS", None)
                KEY_ZH = {"speed": "攻速", "dmg": "伤害", "hp": "HP", "heal": "回复",
                          "dr": "减伤", "cap": "大招上限", "energy": "回能",
                          "spdef": "特防", "def": "防御", "atk": "攻击"}
                if isinstance(tbl, dict):
                    for t, spec in sorted(tbl.items()):
                        tiers = spec.get("tiers", {}) if isinstance(spec, dict) else {}
                        def fmt(n):
                            d = tiers.get(n)
                            if not d:
                                return "—"
                            parts = []
                            for k, v in d.items():
                                val = v if isinstance(v, str) else f"{round(v * 100, 1)}%"
                                parts.append(f"{KEY_ZH.get(k, k)}+{val}")
                            return " ".join(parts)
                        low = fmt(1) + ("；" + fmt(2) if tiers.get(2) else "") if tiers.get(1) else fmt(2)
                        out.append([t, low or "—", fmt(4),
                                    "#{:02x}{:02x}{:02x}".format(*TYPE_COLORS.get(t, (120, 120, 120))),
                                    fmt(6)])
            except Exception as exc:
                out.append(["读取失败", str(exc), "", "#888", ""])
            self._json(out)
        elif parsed.path == "/api/reports":
            files = sorted(p.name for p in (ROOT / "reports").glob("*.md"))
            self._json(files)
        elif parsed.path.startswith("/frame/"):
            # /frame/<key>/<i>.png -> .build/acceptance/<key>/<i>.png
            m = re.match(r"^/frame/([\w.-]+)/(\d+)\.png$", parsed.path)
            if not m:
                return self.send_error(404)
            self.path = f"/.build/acceptance/{m.group(1)}/{m.group(2)}.png"
            super().do_GET()
        elif parsed.path.startswith("/mockups/"):
            self.path = "/docs/design/mockups" + parsed.path[len("/mockups"):]
            super().do_GET()
        elif parsed.path.startswith("/reports/"):
            if requested.is_file() and requested.suffix == '.html' and ROOT / 'reports' in requested.parents:
                self._html(requested.read_text())
            else:
                self.path = "/reports" + parsed.path[len("/reports"):]
                super().do_GET()
        elif parsed.path == "/range":
            try:
                mode = normalize_mode(qs.get('mode', ['arena'])[0])
            except ValueError as exc:
                return self._txt(str(exc), 400)
            # The live range always follows current code and catalog; exported evidence
            # remains reachable by its explicit dated report URL.
            self.send_response(302)
            self.send_header('Location', '/animation-lab?mode=' + mode)
            self.end_headers()
        elif parsed.path == "/device":
            from device_page import page_html
            body = page_html().encode()
            self._html(body)
        elif parsed.path == "/api/device/input":
            from device_controls import api_input
            self._json(api_input({k: v[0] for k, v in qs.items()}))
        elif parsed.path == "/expedition":
            from expedition_page import EXPEDITION_HTML
            body = EXPEDITION_HTML.encode()
            self._html(body)
        elif parsed.path == "/api/expedition/profile":
            from expedition import api_profile
            self._json(api_profile())
        elif parsed.path == "/api/expedition/backup":
            from expedition import store
            try:
                with demo_mod._LOCK:
                    profile_store = store()
                    raw = (profile_store.store.export_checkpoint() if qs.get("checkpoint", ["0"])[0] == "1"
                           else profile_store.export_backup())
            except Exception as exc:
                return self._json({"ok": False, "error": str(exc)}, 400)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", 'attachment; filename="PokeTactics-profile.ptsave"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        elif parsed.path == "/demo":
            # Web 可玩 Demo（tools/acceptance/demo.py 提供页面与会话引擎）
            body = demo_mod.DEMO_HTML.encode()
            self._html(body)
        elif parsed.path == "/api/demo/action":
            params = {k: v[0] for k, v in qs.items()}
            self._json(demo_mod.api_action(params))
        elif parsed.path == "/api/demo/backup":
            try:
                sid = qs.get("sid", [""])[0]
                raw = demo_mod.backup_bytes(sid, checkpoint=qs.get("checkpoint", ["0"])[0] == "1")
            except Exception as exc:
                return self._json({"ok": False, "error": str(exc)}, 400)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", f'attachment; filename="PokeTactics-{sid}.ptsave"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        elif parsed.path.startswith("/demo/sprite/"):
            m = re.match(r"^/demo/sprite/(\d+)\.png$", parsed.path)
            data = demo_mod.sprite_png(int(m.group(1)), shiny=qs.get("shiny", ["0"])[0] == "1") if m else None
            if data is None:
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path.startswith("/demo/frame/"):
            # /demo/frame/<sid>/r<round>/<i>.png -> .build/demo/<sid>/r<round>/
            m = re.match(r"^/demo/frame/([\w-]+)/r(\d+)/(\d+)\.png$", parsed.path)
            if not m:
                return self.send_error(404)
            self.path = (f"/.build/demo/{m.group(1)}/"
                         f"r{m.group(2)}/{m.group(3)}.png")
            super().do_GET()
        else:
            super().do_GET()

    def _html(self, page) -> None:
        """Serve a page with consistent, route-aware global navigation."""
        path = urllib.parse.urlparse(self.path).path
        page = page.decode() if isinstance(page, bytes) else page
        body = portal.wrap_page(page, path).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _play_asset(self, filename: str, content_type: str) -> None:
        """Serve fixed local UI files; HTML pages receive the shared navigation."""
        try:
            body = (Path(__file__).resolve().parent / filename).read_bytes()
        except OSError:
            return self.send_error(503, "The page is temporarily unavailable")
        if content_type.startswith("text/html"):
            return self._html(body)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"PokeTactics 统一入口：{url}（Ctrl-C 退出）")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
