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
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "mockups"))
sys.path.insert(0, str(ROOT / "sim"))

FPS_DT = 0.1
META_REV = "r2"  # meta 生成逻辑版本：变更高级此号使缓存整体失效
_LOCK = threading.Lock()
_CACHE = {}  # seed -> (key, meta)

INDEX_HTML = """<!doctype html><html lang="zh-CN">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>验收后台 · PokeTactics</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f2efe5;color:#29302b;font:14px/1.6 ui-monospace,"PingFang SC",monospace}
main{max-width:1080px;margin:auto;padding:24px}header{border-bottom:2px solid #29302b;padding-bottom:16px;margin-bottom:24px}
h1{font-size:22px;margin:0 0 6px}h2{font-size:16px;margin:28px 0 10px}p{margin:6px 0;color:#555e54}a{color:#355c3d}
button{font:inherit;color:inherit;background:#fffdf5;border:1px solid #899081;border-radius:3px;padding:8px 14px;cursor:pointer;min-height:40px}
button:hover{background:#e2e8d8}button.primary{background:#355c3d;color:white;border-color:#355c3d}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:12px}
.card{display:block;background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:8px;text-decoration:none;color:#29302b}
.card:hover{background:#e2e8d8}.card img{width:100%;image-rendering:pixelated;border:1px solid #363e35;border-radius:3px;background:#363e35}
.card span{display:block;font-size:12px;margin-top:6px;color:#555e54}
.badge{font-size:12px;border:1px solid;border-radius:3px;padding:1px 6px;margin-left:8px;vertical-align:2px}
.todo{color:#8a5a17;border-color:#c99b4a;background:#f7ecd2}.ok{color:#355c3d;border-color:#7fa383;background:#e5efe0}
ul{margin:6px 0;padding-left:20px}li{margin:3px 0}
.note{border-left:3px solid #a5b195;padding-left:12px;margin-top:20px}
.small{font-size:12px}details{margin-top:16px}
.launch{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}
</style></head><body><main>
<header><h1>PokeTactics · 验收后台</h1>
<a href="/anim?seed=7">动画验收台 →</a><p>双端同源验收入口：帧由本地渲染器产出（现为 Python 参考实现，M4 换 C 内核），浏览器只回放。动画即事件流（宪法 2.6）。</p></header>

<h2>待验收 · 战斗动画 v3<span class="badge todo">等你验收</span></h2>
<div class="launch">
<a href="/anim?seed=7"><button class="primary">打开动画验收台（seed=7）</button></a>
<a href="/anim?seed=11"><button>seed=11 · 12.7s 长战</button></a>
</div>
<details open><summary>验收点清单</summary><ul>
<li>精灵无白色剪影、颜色饱满（雷丘橙 / 暴鲤龙蓝 / 隆隆岩灰）</li>
<li>原生尺寸入格（精灵可上溢格子）、前排遮后排</li>
<li>攻击三段：预备后拉 → 突进 + 挥击弧光 → 恢复；受击方击退</li>
<li>移动有步行摆动 + 脚下灰尘 + 行进朝向镜像，不是图片平移</li>
<li>大招抬手多帧（下蹲 → 上顶 + 底座光环脉冲）→ 特写切镜 → 后坐</li>
<li>按属性特效：电=锯齿闪电、草=环绕、水=抛物水珠……</li>
<li>右侧事件流与画面逐条对齐（同种子 → 同事件流 → 同画面）</li>
</ul></details>

<h2>系统控制台<span class="badge ok">每系统一页</span></h2>
<div class="launch">
<a href="/anim?seed=11"><button>动画验收台（战斗回放）</button></a>
<a href="/roster"><button>棋子库（84 只 · 排序筛选）</button></a>
<a href="/match"><button>单局模拟（8 bot 锦标赛）</button></a>
<a href="/experiments"><button>实验台（8 个对照实验）</button></a>
<a href="/synergy"><button>羁绊表（17 系）</button></a>
<a href="/scenarios"><button>场景动画库（分场景带动画）</button></a>
</div>

<h2>静态设计稿<span class="badge ok">已上稿</span></h2>
<div class="grid">
<a class="card" href="/mockups/prep_hd6x.png" target="_blank"><img src="/mockups/prep_hd6x.png"><span>准备页 · 方案C（HD 1440×1920）</span></a>
<a class="card" href="/mockups/battle_hd6x.png" target="_blank"><img src="/mockups/battle_hd6x.png"><span>战斗页（HD）</span></a>
<a class="card" href="/mockups/cutin_hd6x.png" target="_blank"><img src="/mockups/cutin_hd6x.png"><span>大招特写（HD）</span></a>
<a class="card" href="/mockups/battle_storyboard.png" target="_blank"><img src="/mockups/battle_storyboard.png"><span>动画分镜图（六格）</span></a>
</div>

<h2>验证报告</h2><ul id="reports">加载中…</ul>
<p class="small note">确定性自检在 sim/prototype.py 常驻；本服务仅本地验收用，不读写真机数据。</p>
<script>fetch('/api/reports').then(r=>r.json()).then(fs=>{
document.getElementById('reports').innerHTML=fs.map(f=>'<li><a href="/reports/'+f+'">'+f+'</a></li>').join('');});</script>
</main></body></html>"""


PLAYER_HTML = """<!doctype html><html lang="zh-CN">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>动画验收台 · seed=__SEED__</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f2efe5;color:#29302b;font:14px/1.6 ui-monospace,"PingFang SC",monospace}
main{max-width:1180px;margin:auto;padding:24px}header{border-bottom:2px solid #29302b;padding-bottom:12px;margin-bottom:20px}
.tabs{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.tabs a{text-decoration:none;color:inherit;border:1px solid #899081;border-radius:4px 4px 0 0;
padding:4px 12px;font-size:13px;background:#e9e4d3}
.tabs a.on{background:#355c3d;color:#fff;border-color:#355c3d;font-weight:600}
.tabs a:hover:not(.on){background:#dfe5d4}
h1{font-size:20px;margin:0 0 4px}p{margin:6px 0;color:#555e54}a{color:#355c3d}
.layout{display:grid;grid-template-columns:230px auto minmax(250px,340px);gap:28px;align-items:start}
label{display:block;font-size:12px;margin:14px 0 4px}
select,input,button{font:inherit;color:inherit;background:#fffdf5;border:1px solid #899081;border-radius:3px;padding:8px;width:100%}
button{cursor:pointer;min-height:40px}button:hover{background:#e2e8d8}button.primary{background:#355c3d;color:white;border-color:#355c3d}
.stage{display:flex;flex-direction:column;align-items:center;gap:12px}
.shell{padding:16px;background:#363e35;border:1px solid #232923;border-radius:9px}
.screen{width:480px;max-width:100%}canvas{display:block;width:100%;image-rendering:pixelated;border-radius:2px}
.keys{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;width:100%;max-width:360px}
.keys button{font-size:16px;font-weight:700}
.controls{display:flex;flex-wrap:wrap;gap:8px;width:100%;max-width:480px}.controls button{flex:1;width:auto}
input[type=range]{padding:0;accent-color:#355c3d}
.status{font-size:12px;min-height:36px;word-break:break-all;width:100%;max-width:480px;color:#555e54}
.small{font-size:12px}.note{border-left:3px solid #a5b195;padding-left:12px;margin-top:16px}
details{margin-top:16px}.kbd{background:#e6e0cf;border:1px solid #b9b3a0;border-radius:3px;padding:0 5px;font-size:12px}
#evpanel{background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:8px;max-height:760px;overflow-y:auto}
#evpanel h2{font-size:13px;margin:2px 4px 8px;color:#555e54}
#evpanel div.ev{padding:1px 6px;border-radius:3px;white-space:nowrap;color:#8b938a;font-size:12px}
#evpanel div.ev.past{color:#3d453f}#evpanel div.ev.now{background:#e5efe0;color:#28432c;font-weight:600}
#evpanel div.ev b{color:#29302b}
@media(max-width:980px){.layout{grid-template-columns:1fr}.stage{order:1}#evpanel{order:2;max-height:300px}.settings{order:3}}
</style></head><body><main>
<header><h1>战斗动画验收台 · seed=__SEED__ <span class="muted" id="scenlabel" data-l="__SCENLABEL__" data-s="__SCEN__"></span></h1><a href="/">← 返回验收清单</a> · <a href="__SYNLINK__"><button style="display:inline-block;width:auto;min-height:0;padding:4px 10px;font-size:12px">__SYNBTN__</button></a><div class="tabs" id="tabs"></div></header>
<div class="layout">
<aside class="settings">
<label for="seed">战斗种子</label><input id="seedin" type="number" value="__SEED__" min="1" max="99999">
<button id="reload" class="primary">载入场景</button>
<label for="speed">播放倍速</label><select id="speed"><option value="0.5">0.5x</option><option value="1" selected>1x（10fps）</option><option value="2">2x</option><option value="4">4x</option></select>
<label for="zoom">像素缩放</label><select id="zoom"><option value="480" selected>2 倍 · 480×640</option><option value="240">1 倍 · 240×320</option></select>
<p class="small"><span class="kbd">空格</span> 播放/暂停，<span class="kbd">←</span> <span class="kbd">→</span> 单步。标签页隐藏自动停钟（PokeWalk 预览纪律）。</p>
<details open><summary>验收点</summary><ul class="small" style="padding-left:16px">
<li>精灵无白剪影、颜色饱满</li><li>原生尺寸入格、前排遮后排</li>
<li>攻击三段 + 挥击弧、受击击退</li><li>步行摆动 + 灰尘 + 朝向</li>
<li>抬手多帧 + 光环 → 切镜 → 后坐</li><li>按属性特效、事件流对齐</li>
</ul></details>
<p class="small note">帧缓存按 seed + 渲染器源码哈希键控；改渲染代码后刷新自动重算。</p>
</aside>
<section class="stage">
<div class="shell"><div class="screen"><canvas id="cv" width="240" height="320"></canvas></div></div>
<div class="keys"><button id="prev">|◀ 退</button><button id="play">⏯ 播放</button><button id="next">进 ▶|</button></div>
<input type="range" id="scrub" min="0" max="0" value="0" style="max-width:480px">
<div class="controls" id="fxjumps" style="max-width:480px"></div>
<div class="controls"><button id="step">单步 0.1s</button><button id="save">保存 PNG</button></div>
<p class="small" id="clock-state" role="status">正在载入场景…</p>
<p class="status" id="meta" role="status">帧生成中…（首次约数秒）</p>
</section>
<div id="evpanel"><h2>事件流（与画面逐条对照）</h2><div id="ev"></div></div>
</div>
</main>
<script>
const seed=__SEED__, DT=__DT__, syn=__SYN__;
const TAB_SEEDS=[3,7,11,42,100,777];
(function(){const el=document.getElementById('tabs');
el.innerHTML=TAB_SEEDS.map(n=>'<a href="/anim?seed='+n+'&synergy='+syn+(scenS?'&scenario='+scenS:'')+'" class="'+(n===seed?'on':'')+'">seed '+n+'</a>').join('')
+(TAB_SEEDS.includes(seed)?'':'<a class="on">seed '+seed+'</a>');})();
let frames=[], n=0, cur=0, playing=false, timer=null, events=[];
const cv=document.getElementById('cv'), ctx=cv.getContext('2d');
const scrub=document.getElementById('scrub');
function clock(text){document.getElementById('clock-state').textContent=text;}
const scen=document.getElementById('scenlabel');
const scenS=scen.dataset.s;
if(scenS){fetch('/api/prepare?seed='+seed+'&synergy='+syn+'&scenario='+scenS).then}else{fetch('/api/prepare?seed='+seed+'&synergy='+syn).then}(r=>r.json()).then(m=>{
  n=m.n; events=m.events;
  document.getElementById('meta').textContent=
    m.na+' vs '+m.nb+' · '+m.n+' 帧 @10fps · '+(m.n*DT).toFixed(1)+'s · 胜者='+(m.result===null?'平':('AB'[m.result]??m.result))+' · '+m.casts+' 次大招 · 构建 '+m.key;
  scrub.max=n-1;
  let loaded=0;
  for(let i=0;i<n;i++){const im=new Image();im.onload=()=>{frames[i]=im;
    if(loaded===0&&i===0)show(0);  // 首帧到达立即上屏
    if(++loaded===n){clock('就绪 · '+n+' 帧已加载');show(cur);}};im.src='/frame/'+m.key+'/'+i+'.png';}
  document.getElementById('ev').innerHTML=events.map((e,i)=>'<div class="ev" id="ev'+i+'">['+e.t.toFixed(1)+'] '+e.text+'</div>').join('');
  const jf=document.getElementById('fxjumps');
  jf.innerHTML=(m.fx||[]).map(f=>'<button data-t="'+f[0]+'">'+f[1]+' · '+f[0]+'s</button>').join('');
  jf.querySelectorAll('button').forEach(b=>b.onclick=()=>{stop();show(Math.round(parseFloat(b.dataset.t)/DT));});

}).catch(e=>{clock('载入失败：'+e);});
function show(i){cur=Math.max(0,Math.min(n-1,i));if(frames[cur])ctx.drawImage(frames[cur],0,0);
scrub.value=cur;clock('第 '+cur+' / '+(n-1)+' 帧 · '+(cur*DT).toFixed(1)+'s');
let last=-1;for(let j=0;j<events.length;j++){const el=document.getElementById('ev'+j);
if(el){el.className=(events[j].t<=cur*DT+1e-9)?'ev past':'ev';if(events[j].t<=cur*DT+1e-9)last=j;}}
if(last>=0){const el=document.getElementById('ev'+last);el.className='ev now';el.scrollIntoView({block:'nearest'});}}
function tick(){show(cur+1);if(cur>=n-1)stop();}
function play(){if(playing)return stop();if(cur>=n-1)show(0);playing=true;clock('播放中 '+(cur*DT).toFixed(1)+'s');
timer=setInterval(tick, DT*1000/parseFloat(document.getElementById('speed').value));}
function stop(){playing=false;clearInterval(timer);}
document.getElementById('play').onclick=play;
document.getElementById('prev').onclick=()=>{stop();show(cur-1);};
document.getElementById('next').onclick=()=>{stop();show(cur+1);};
document.getElementById('step').onclick=()=>{stop();show(cur+1);};
document.getElementById('speed').onchange=()=>{if(playing){stop();play();}};
document.getElementById('zoom').onchange=e=>{document.querySelector('.screen').style.width=e.target.value+'px';};
document.getElementById('scrub').oninput=()=>{stop();show(+scrub.value);};
document.getElementById('save').onclick=()=>{const a=document.createElement('a');
a.download='poketactics_seed'+seed+'_f'+cur+'.png';a.href=cv.toDataURL();a.click();};
document.getElementById('reload').onclick=()=>{location.href='/anim?seed='+document.getElementById('seedin').value;};
if(window.innerHeight<760){document.querySelector('.screen').style.width='240px';
  document.getElementById('zoom').value='240';}  // 低视口自动 1x
document.addEventListener('keydown',e=>{
if(e.target.tagName==='INPUT')return;
if(e.code==='Space'){e.preventDefault();play();}
if(e.code==='ArrowLeft'){stop();show(cur-1);}
if(e.code==='ArrowRight'){stop();show(cur+1);}});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});  // 隐藏停钟
</script></body></html>"""


def render_battle(seed: int, synergy: bool = False, scenario: str = None) -> dict:
    """跑一场战斗并渲染全部帧（缓存；synergy=羁绊；scenario=场景库预设）."""
    import data
    import status as status_mod
    import synergy as syn
    from decoders import Front, Font16, Palettes
    from render_battle_gif import BattleAnimation
    from roster import build_roster

    sim_files = ["sim/combat.py", "sim/synergy.py", "sim/roster.py",
                 "sim/status.py", "sim/weather.py", "data/moves.json",
                 "data/pokemon.json", "data/typechart.json"]
    h = hashlib.sha256()
    h.update((ROOT / "tools/mockups/render_battle_gif.py").read_bytes())
    for rel in sim_files:  # sim 状态也进缓存键：否则 sim 改动会静默吃旧帧
        h.update(rel.encode())
        h.update((ROOT / rel).read_bytes())
    src_hash = h.hexdigest()[:10]
    key = (f"s{seed}{'sy' if synergy else ''}"
           f"{'sc_' + scenario if scenario else ''}_{META_REV}_{src_hash}")
    out_dir = ROOT / ".build" / "acceptance" / key
    meta_path = out_dir / "meta.json"
    if not meta_path.exists():
        with _LOCK:
            if not meta_path.exists():
                prev_syn = syn.SYNERGIES_ON
                prev_status = status_mod.STATUS_ON
                syn.SYNERGIES_ON = synergy  # 仅在锁内翻转，渲染完还原
                front, pal, font = Front(), Palettes(), Font16()
                roster = build_roster()

                def find(name):
                    return next(p for ps in roster.values() for p in ps if p.name == name)

                sc = SCENARIOS.get(scenario) if scenario else None
                if sc:
                    comp_a = [find(n) for n in sc["a"]]
                    comp_b = [find(n) for n in sc["b"]]
                    weather = sc.get("weather")
                    status_mod.STATUS_ON = bool(sc.get("status"))
                else:
                    comp_a = [find(n) for n in ("雷丘", "妙蛙花", "隆隆岩", "怪力", "水伊布")]
                    comp_b = [find(n) for n in ("暴鲤龙", "喷火龙", "胡地", "大比鸟", "霸王花")]
                    weather = None
                anim = BattleAnimation(comp_a, comp_b, seed, front, pal, font,
                                       weather_name=weather)
                t_end = max(e[0] for e in anim.events)
                result = next((e[2] for e in reversed(anim.events)
                               if e[1] == "end"), None)
                n_casts = sum(1 for e in anim.events if e[1] == "cast")
                duration = t_end + 1.2 + (1.5 if result is not None else 0)
                out_dir.mkdir(parents=True, exist_ok=True)
                frames_meta = []
                T, i = 0.0, 0
                while T <= duration:
                    anim.frame(T).convert("RGB").save(out_dir / f"{i}.png")
                    frames_meta.append(round(T, 2))
                    T += FPS_DT
                    i += 1
                events = []
                for e in anim.events:
                    events.append({"t": round(e[0], 2),
                                   "text": _fmt_event(anim, e)})
                syn.SYNERGIES_ON = prev_syn
                status_mod.STATUS_ON = prev_status
                fx_moments = [("0.2", "开战演出")]
                first_atk = next((e[0] for e in anim.events
                                  if e[1] == "attack"), None)
                if first_atk:
                    fx_moments.append((round(first_atk + 0.1, 2), "普攻火花"))
                fx_moments += [(round(c[1] + 0.1, 2), f"大招落点{ j + 1}")
                               for j, c in enumerate(
                                   sorted(anim.cutins, key=lambda x: x[0]))]
                first_die = next((e[0] for e in anim.events
                                  if e[1] == "die"), None)
                if first_die:
                    fx_moments.append((round(first_die + 0.1, 2), "濒死演出"))
                meta = {"key": key, "n": i, "times": frames_meta,
                        "events": events, "result": result, "casts": n_casts,
                        "synergy": synergy, "fx": fx_moments,
                        "scenario": scenario,
                        "scenario_label": (SCENARIOS.get(scenario) or {}).get("label", ""),
                        "weather": weather,
                        "na": " ".join(p.name for p in comp_a),
                        "nb": " ".join(p.name for p in comp_b)}
                meta_path.write_text(json.dumps(meta, ensure_ascii=False))
    return json.loads(meta_path.read_text())


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

NAV = ('<div class="tabs"><a href="/">总览</a><a href="/anim?seed=11">动画验收台</a>'
       '<a href="/roster">棋子库</a><a href="/match">单局模拟</a>'
       '<a href="/experiments">实验台</a><a href="/synergy">羁绊表</a>'
       '<a href="/scenarios">场景动画库</a><a href="/items">装备</a></div>')

SCEN_HTML = ("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
             "<title>场景动画库 · PokeTactics</title><style>" + CONSOLE_CSS + "</style>"
             "<main><header><h1>场景动画库</h1>" + NAV + "</header>"
             "<p>每个分场景模拟的动画回放——与实验台文字读数一一对应。</p>"
             "<div class=cardrow>__CARDS__</div></main></body></html>")



ITEMS_HTML = ("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
              "<title>装备与道具 · PokeTactics</title><style>" + CONSOLE_CSS + "</style>"
              "<main><header><h1>装备与道具（S5 v1）</h1>" + NAV + "</header>"
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
               "<main><header><h1>棋子库</h1>" + NAV + "</header>"
               "<p>84 只池 · BST 定档（S2）。点列头排序。</p>"
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
            "fetch('/api/scenarios').then(r=>r.json()).then(scs=>{"
            "const byExp={};scs.forEach(x=>{(byExp[x.exp]=byExp[x.exp]||[]).push(x)});"
            "document.getElementById('cards').innerHTML=names.map(n=>"
            "'<div class=card><b>'+n+'</b><br><span class=muted>'+(EXPS[n]||'')+'</span>"
            "<button onclick=run(this) data-n='+n+'>运行</button>"
            "+((byExp[n]||[]).map(x=>'<br><a href=\'/anim?seed=7&scenario='+x.key+'\'>▶ '+x.label+'</a>').join(''))"
            "+'</div>').join('');});});"
            "function run(b){document.getElementById('out').textContent='运行中…（最长 60s）';"
            "fetch('/api/experiment?name='+b.dataset.n).then(r=>r.text())"
            ".then(t=>document.getElementById('out').textContent=t);}</script></body></html>")

SYN_HTML = ("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
            "<title>羁绊表 · PokeTactics</title><style>" + CONSOLE_CSS + "</style>"
            "<main><header><h1>17 系羁绊表（S3，默认开）</h1>" + NAV + "</header>"
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

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/":
            body = INDEX_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/anim":
            seed = int(qs.get("seed", ["7"])[0])
            syn_on = qs.get("synergy", ["1"])[0] == "1"  # 2026-09-14 起 S3 默认开
            scenario = qs.get("scenario", [""])[0] or None
            body = (PLAYER_HTML.replace("__SEED__", str(seed))
                    .replace("__SYN__", "1" if syn_on else "0")
                    .replace("__SYNLINK__",
                             f"/anim?seed={seed}&synergy={0 if syn_on else 1}"
                             + (f"&scenario={scenario}" if scenario else ""))
                    .replace("__SYNBTN__",
                             "羁绊：开（点击关闭）" if syn_on else "羁绊：关（点击开启）")
                    .replace("__SCEN__", scenario or "")
                    .replace("__SCENLABEL__",
                             (SCENARIOS.get(scenario) or {}).get("label", ""))
                    .replace("__DT__", str(FPS_DT))).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/scenarios":
            cards = []
            for k, sc in SCENARIOS.items():
                cards.append(
                    f'<div class="card"><b>{sc["label"]}</b>'
                    f'<br><span class="muted">{sc["exp"]} 实验 · '
                    f'{"天气:" + (sc.get("weather") or "无")}'
                    f'{" · 状态开" if sc.get("status") else ""}</span>'
                    f'<a href="/anim?seed={SCENARIO_SEED_DEFAULT}&scenario={k}">'
                    f'<button class="primary">播放动画</button></a></div>')
            body = (SCEN_HTML.replace("__CARDS__", "\n".join(cards))).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/items":
            body = ITEMS_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/prepare":
            seed = int(qs.get("seed", ["7"])[0])
            syn_on = qs.get("synergy", ["1"])[0] == "1"
            scenario = qs.get("scenario", [""])[0] or None
            t0 = time.time()
            meta = render_battle(seed, syn_on, scenario)
            print(f"[acceptance] seed={seed} 帧渲染+缓存 "
                  f"{time.time() - t0:.1f}s（key={meta['key']}）")
            self._json(meta)
        elif parsed.path == "/api/roster":
            from roster import build_roster
            from data import pokedex
            dex = pokedex()
            rows = []
            for tier, pieces in sorted(build_roster().items()):
                for pc in pieces:
                    b = dex.species[pc.species_id]["base"]
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
            self._json([{"key": k, "label": v["label"], "exp": v["exp"]}
                       for k, v in SCENARIOS.items()])
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
            self.path = "/reports" + parsed.path[len("/reports"):]
            super().do_GET()
        else:
            super().do_GET()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"PokeTactics 验收后台：{url}（Ctrl-C 退出）")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
