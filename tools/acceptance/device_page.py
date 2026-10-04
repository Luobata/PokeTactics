"""Three-button-only host reference. Screen is a display, never a touch target."""

HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PokeTactics · 林间掌机</title><style>
:root{--forest:#203d30;--dark:#152b22;--moss:#69836a;--cream:#f2ebd3;--paper:#fff9e6;--ochre:#c99645}
*{box-sizing:border-box}body{margin:0;min-height:100vh;color:var(--forest);background:#d9ddca;
font-family:"Courier New","Songti SC",serif;background-image:linear-gradient(#203d3010 1px,transparent 1px),linear-gradient(90deg,#203d3010 1px,transparent 1px);background-size:24px 24px}
main{max-width:1140px;margin:auto;min-height:100vh;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:42px;padding:34px}
.wordmark{font:700 13px "Courier New",monospace;letter-spacing:4px;border-top:3px solid var(--forest);padding-top:16px}
h1{font-size:clamp(27px,4vw,49px);line-height:1.3;font-weight:700;letter-spacing:3px;margin:28px 0 14px}.intro p{font-size:14px;line-height:1.9;max-width:240px}.kicker{font-size:10px;letter-spacing:2px;color:#526b52}
.console{background:var(--cream);width:352px;padding:22px 24px 25px;border:3px solid var(--forest);border-radius:13px 13px 36px 13px;box-shadow:9px 10px 0 #203d3038,0 0 0 4px #edf0df inset;position:relative}
.brand{display:flex;justify-content:space-between;align-items:center;font-size:11px;letter-spacing:2px;padding:0 1px 13px;font-weight:bold}.led{width:6px;height:6px;background:#92ad71;box-shadow:0 0 0 2px var(--forest);display:inline-block;margin-right:6px}
.bezel{background:var(--forest);padding:9px 8px 19px;border:2px solid #152b22;border-radius:5px}.screen-wrap{width:264px;height:352px;border:2px solid #101f18;background:#eff0d7;overflow:hidden}
canvas{display:block;width:260px;height:347px;image-rendering:pixelated;pointer-events:none;user-select:none;touch-action:none}.screen-note{font-size:8px;letter-spacing:3px;text-align:center;color:#9da98c;margin-top:9px}
.controls{display:flex;justify-content:space-between;gap:22px;margin:26px 5px 0}.key-wrap{text-align:center}.key{width:67px;height:43px;padding:0;border:2px solid var(--dark);background:var(--forest);color:var(--paper);box-shadow:0 5px 0 var(--dark);border-radius:8px;font:700 19px "Courier New",monospace;cursor:pointer;touch-action:none;user-select:none}.key[data-key=C]{background:#b17c36;color:#fff8da}.key.held{transform:translateY(4px);box-shadow:0 1px 0 var(--dark)}.key:focus-visible{outline:3px solid var(--ochre);outline-offset:5px}.key-label{font-size:9px;letter-spacing:1px;margin-top:11px}.vents{display:flex;gap:5px;justify-content:flex-end;margin:20px 7px 0;transform:rotate(-18deg)}.vents i{height:25px;width:4px;background:#bcc3a6;border:1px solid #9aa48c;border-radius:2px}
.guide{font-size:12px;line-height:1.9;max-width:230px}.guide dt{font-weight:bold;letter-spacing:2px;margin-top:21px}.guide dd{margin:5px 0 0;color:#4b644f}.guide .rule{height:2px;width:40px;background:var(--forest);margin-bottom:22px}.footnote{font-size:10px;letter-spacing:1px;margin-top:30px;color:#60715c}#status{height:36px;font-size:11px;margin-top:21px;line-height:1.6;word-break:break-all}.busy .led{background:#e8b25e}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;pointer-events:none}
@media(max-width:940px){main{grid-template-columns:1fr auto;gap:25px}.guide{display:none}}@media(max-width:620px){main{display:flex;flex-direction:column;justify-content:center;padding:23px 8px;gap:20px}.intro{width:340px}.intro h1,.intro p,.intro .kicker{display:none}.wordmark{font-size:10px;padding-top:8px}.console{width:340px;padding-left:18px;padding-right:18px}.footnote{margin-top:10px}}
@media(prefers-reduced-motion:no-preference){.console{animation:arrive .45s ease-out}@keyframes arrive{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}}
</style></head><body><main>
<section class="intro"><div class="wordmark">POKÉ TACTICS / FIELD 01</div><h1>口袋里的<br>战术旅程</h1><p>在林间商店相遇，在棋盘上并肩。带好行囊，再往前走一程。</p><div class="kicker">THREE KEYS. ONE ADVENTURE.</div><div class="footnote">240 × 320 · 三键主机参考</div></section>
<section class="console" aria-label="PokeTactics 三键设备"><div class="brand"><span>POKÉ TACTICS</span><span><i class="led"></i>FIELD</span></div>
<div class="bezel"><div class="screen-wrap"><canvas id="screen" width="240" height="320" aria-label="只读游戏屏幕" aria-describedby="screen-text"></canvas></div><div class="screen-note">DOT MATRIX / NO TOUCH</div></div>
<div id="screen-text" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>
<div class="controls"><div class="key-wrap"><button class="key" data-key="A" aria-label="A 上一项">A</button><div class="key-label">UP / 上</div></div><div class="key-wrap"><button class="key" data-key="B" aria-label="B 下一项，长按返回">B</button><div class="key-label">DOWN / 下</div></div><div class="key-wrap"><button class="key" data-key="C" aria-label="C 确认，长按详情或关屏">C</button><div class="key-label">OK / 确认</div></div></div>
<div class="vents" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div><div id="status" role="status" aria-live="polite">正在连接掌机…</div></section>
<aside class="guide"><div class="rule"></div><div class="kicker">FIELD MANUAL / 操作手册</div><dl><dt>轻按</dt><dd>A 上一项 · B 下一项<br>C 确认选中项</dd><dt>按住</dt><dd>B 0.6 秒：返回或取消<br>C 0.6 秒：查看详情<br>C 1.5 秒：关闭屏幕</dd><dt>键盘也可以</dt><dd>↑ / ↓ / Enter<br>或字母 A / B / C</dd><dt>棋盘移动</dt><dd>先选行，再选列。<br>屏幕只显示，三个按键完成全部操作。</dd></dl><div class="footnote">自动保存每次成功操作。<br>唤醒后的第一按仅用于亮屏。</div></aside>
</main><script>
const cv=document.getElementById('screen'),ctx=cv.getContext('2d'),status=document.getElementById('status');
const C={ink:'#203d30',paper:'#f1edce',soft:'#d6dcc0',moss:'#71856a',gold:'#b78238',white:'#fff9df'};
let device='',view=null,chain=Promise.resolve(),pending=0,actionPending=0,frameUrl='',frameImage=null,frameToken=0;
let disconnected=false,transportEpoch=0;
const pressed=new Set(),suppressed=new Set();const query=new URLSearchParams(location.search);
ctx.imageSmoothingEnabled=false;
function rect(x,y,w,h,color){ctx.fillStyle=color;ctx.fillRect(x,y,w,h)}
function text(s,x,y,size=11,color=C.ink){ctx.fillStyle=color;ctx.font=`${size}px "Courier New","Songti SC",monospace`;ctx.fillText(String(s??''),x,y)}
function clipped(s,x,y,width,size=11,color=C.ink){ctx.save();ctx.beginPath();ctx.rect(x,y-size,width,size+5);ctx.clip();text(s,x,y,size,color);ctx.restore()}
function tree(x,y){rect(x+6,y+17,4,9,C.ink);rect(x+3,y+5,10,15,C.moss);rect(x,y+11,16,7,C.ink);rect(x+5,y,6,9,C.ink)}
function draw(){if(!view)return;const s=view.screen;const description=view.sleeping?'屏幕已关闭。按任意键唤醒，整次唤醒手势不执行操作。':[s.title,s.prompt||'',...(s.detail||[]),...s.rows.map(r=>(r.index===s.selected?'当前选择：':'')+r.label+(r.subtitle?'，'+r.subtitle:'')),...s.footer].join('。');const a11y=document.getElementById('screen-text');if(a11y.textContent!==description)a11y.textContent=description;rect(0,0,240,320,C.paper);
if(view.sleeping){rect(0,0,240,320,'#18291f');text('Z z',101,151,20,'#93a385');text('轻按任意键唤醒',66,176,11,'#93a385');return}
rect(0,0,240,30,C.ink);clipped(s.title,10,19,214,12,C.paper);
if(s.hud){text(`♥${s.hud.hp}  G${s.hud.gold}  Lv${s.hud.level}  R${s.round}`,9,45,10);text(`上场 ${s.hud.on_board}/${s.hud.pop}`,153,45,9)}
let top=s.hud?57:42;
if(s.page==='home'){tree(187,40);tree(210,55);text('新的伙伴，新的阵容。',11,55,11);top=83}
if(s.page==='battle'&&s.battle){const url=s.battle.url;if(url!==frameUrl){frameUrl=url;const token=++frameToken,im=new Image();im.onload=()=>{if(token===frameToken){frameImage=im;draw()}};im.src=url}if(frameImage){ctx.drawImage(frameImage,0,0,240,320)}rect(0,263,240,57,C.paper);clipped((s.rows.find(r=>r.index===s.selected)||{}).label,9,276,222,11);}
else if(s.detail){s.detail.forEach((line,i)=>text(line,11,top+17+i*22,12));text(`${s.detail_page} / ${s.detail_total}`,190,266,10,C.moss)}
else{if(s.prompt){const lines=s.prompt.match(/.{1,17}/gu)||[];lines.slice(0,4).forEach((line,i)=>text(line,10,top+10+i*15,11,C.gold));top+=Math.min(4,lines.length)*15+13}
if(!s.rows.length){text('这里暂时空着',72,143,12,C.moss);text('按住 B 返回',78,168,10,C.moss)}
s.rows.forEach((r,i)=>{const y=top+i*36,selected=r.index===s.selected;rect(7,y,226,32,selected?C.ink:C.soft);if(selected){rect(10,y+11,3,9,C.gold);rect(13,y+13,3,5,C.gold)}clipped(r.label,selected?23:15,y+14,203,11,r.disabled?C.moss:selected?C.paper:C.ink);if(r.subtitle)clipped(r.subtitle,selected?23:15,y+27,203,9,selected?'#c5ccb2':C.moss)});
if(s.total>5){rect(235,top,2,174,C.soft);rect(235,top+(s.selected/Math.max(1,s.total-1))*154,2,20,C.moss)}
if(s.page.includes('columns')){let cells=s.row===2?s.bench:s.board[s.row]||[];for(let c=0;c<6;c++){const x=10+c*37;rect(x,244,32,21,c===s.selected?C.gold:C.moss);text(cells[c]?'●':String(c+1),x+10,259,10,C.paper)}}
}
rect(0,280,240,40,C.ink);text(s.footer[0],8,294,9,C.paper);text(s.footer[1],8,308,8,'#bcc9aa');
if(s.page!=='battle')clipped(s.message,10,277,222,9,C.moss);
}
function clearLocal(){pressed.clear();suppressed.clear();document.querySelectorAll('.key').forEach(b=>b.classList.remove('held'))}
async function request(phase,key){const params=new URLSearchParams({phase,device_id:device});if(key)params.set('key',key);if(!device){if(query.get('sid'))params.set('sid',query.get('sid'));else try{params.set('remembered_sid',localStorage.getItem('poketactics.slot')||'')}catch(e){}}const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),6000);try{const response=await fetch('/api/device/input?'+params,{cache:'no-store',signal:controller.signal});return await response.json()}finally{clearTimeout(timer)}}
function publish(result){if(!result.ok){status.textContent=result.error||'连接未完成';return}device=result.device_id;view=result;status.textContent=view.sleeping?'屏幕已关闭，进度已保留':view.screen.message;if(result.sid&&result.screen.page!=='home'){try{localStorage.setItem('poketactics.slot',result.sid)}catch(e){}history.replaceState(null,'','/device?sid='+encodeURIComponent(result.sid))}draw()}
async function recover(){clearLocal();if(device){const ended=await request('cancel');if(!ended.ok){device=''}}const fresh=await request('state');if(!fresh.ok)throw new Error(fresh.error);publish(fresh);disconnected=false}
function queue(phase,key){if(phase==='tick'&&pending)return;pending++;const epoch=transportEpoch,blocking=phase==='up'||phase==='cancel';if(blocking)actionPending++;document.querySelector('.console').classList.add('busy');chain=chain.then(async()=>{if(epoch!==transportEpoch)return;if(disconnected){await recover();return}publish(await request(phase,key))}).catch(()=>{disconnected=true;transportEpoch++;clearLocal();status.textContent='连接中断；恢复时会先清理按键并读取已保存进度，不重试操作。'}).finally(()=>{pending--;if(blocking)actionPending--;if(!pending)document.querySelector('.console').classList.remove('busy')});}
function down(key){if(pressed.has(key)||suppressed.has(key))return;if(disconnected){suppressed.add(key);queue('state');return}if(actionPending||!device){suppressed.add(key);return}pressed.add(key);document.querySelector(`[data-key=${key}]`).classList.add('held');queue('down',key)}
function up(key){document.querySelector(`[data-key=${key}]`).classList.remove('held');if(suppressed.delete(key))return;if(!pressed.delete(key))return;queue('up',key)}
function cancel(){clearLocal();queue('cancel')}
document.querySelectorAll('.key').forEach(button=>{const key=button.dataset.key;button.addEventListener('pointerdown',event=>{event.preventDefault();button.setPointerCapture(event.pointerId);down(key)});button.addEventListener('pointerup',event=>{event.preventDefault();up(key)});button.addEventListener('pointercancel',cancel);button.addEventListener('lostpointercapture',()=>{if(pressed.has(key))cancel()});button.addEventListener('click',event=>event.preventDefault())});
const keys={ArrowUp:'A',ArrowDown:'B',Enter:'C',a:'A',b:'B',c:'C',A:'A',B:'B',C:'C'};
window.addEventListener('keydown',event=>{const key=keys[event.key];if(!key)return;event.preventDefault();if(!event.repeat)down(key)});
window.addEventListener('keyup',event=>{const key=keys[event.key];if(!key)return;event.preventDefault();up(key)});
window.addEventListener('blur',cancel);document.addEventListener('visibilitychange',()=>{if(document.hidden)cancel()});
setInterval(()=>{if(device&&!document.hidden)queue('tick')},100);queue('state');
</script></body></html>'''


def page_html():
    return HTML
