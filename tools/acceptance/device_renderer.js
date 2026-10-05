/* 240 × 320 presentation only. Formation and actions come from device_controls. */
const cv = document.getElementById('screen'), ctx = cv.getContext('2d');
const status = document.getElementById('status');
const C = {ink:'#283d34', paper:'#f4ecd5', white:'#fff9e8', line:'#b6b99b',
  muted:'#66745d', gold:'#c89846', sand:'#d5c69f', grass:'#aeba98', dark:'#162c25', red:'#a24f3d'};
let device='', view=null, chain=Promise.resolve(), pending=0, actionPending=0;
let frameUrl='', frameImage=null, frameToken=0, disconnected=false, transportEpoch=0;
let notice={text:'',until:0};
const heldAt=new Map();
const pressed=new Set(), suppressed=new Set(), query=new URLSearchParams(location.search);
const sprites=new Map();
ctx.imageSmoothingEnabled=false;
const ICONS={
  shop:['001111100','011111110','111111111','101010101','011111110','010000010','010110010','010110010','011111110'],
  board:['111011101','101010101','111011101','000000000','111011101','101010101','111011101','000000000','111011101'],
  bag:['001111100','001000100','011111110','110000011','110000011','111111111','110010011','110000011','011111110'],
  link:['001100000','011110000','110011000','110111100','011101110','001111011','000110011','000011110','000001100'],
  scout:['000000000','001111100','011000110','110010011','100111001','110010011','011000110','001111100','000000000'],
  battle:['110000011','011000110','001101100','000111000','001111100','011111110','110101011','000101000','000111000'],
  system:['000111000','010111010','111111111','011000110','111010111','011000110','111111111','010111010','000111000'],
  item:['000111000','001000100','001000100','011111110','010000010','010101010','010010010','010000010','001111100'],
  craft:['000010000','000111000','001111100','011111110','111111111','011111110','001111100','000111000','000010000'],
  technique:['001111100','011111110','111111111','111000111','111010111','111000111','111111111','011111110','001111100'],
  dex:['011111110','110000010','110111010','110000010','110111010','110000010','110111010','110000010','011111110'],
  heart:['011011000','111111100','111111100','011111000','001110000','000100000'],
  coin:['001110000','010101000','110101100','110101100','010101000','001110000'],
  flag:['110000000','111111100','111111000','111110000','110000000','110000000','110000000','110000000','111100000']
};
ICONS.guard=['111111111','100000001','101111101','101010101','101010101','010101010','010101010','001000100','000111000'];
ICONS.weather=['000010000','010010010','001111100','001111100','111111111','001111100','001111100','010010010','000010000'];
ICONS.back=['000100000','001100000','011111110','111111110','011111110','001100000','000100000'];
const PREP_ICONS=['shop','board','bag','link','scout','battle','system'];
const PREP_TIPS=['招募伙伴，组成新阵容','选择棋子，调整上场位置','装备、合成与招式教学','查看上场队伍的羁绊','侦察对手与训练家排名','阵容就绪，开始自动战斗','进度与旅途选项'];
function rect(x,y,w,h,color){ctx.fillStyle=color;ctx.fillRect(Math.round(x),Math.round(y),Math.round(w),Math.round(h));}
function box(x,y,w,h,fill=C.white,border=C.line){rect(x,y,w,1,border);rect(x,y+h-1,w,1,border);rect(x,y,1,h,border);rect(x+w-1,y,1,h,border);if(fill!=='transparent')rect(x+1,y+1,w-2,h-2,fill);}
function font(size=12,bold=false){ctx.font=`${bold?600:400} ${size}px "PingFang SC","Microsoft YaHei",sans-serif`;}
function width(s,size=12){font(size);return (ctx.measureText(String(s))||{}).width||String(s).length*size;}
function text(s,x,y,size=12,color=C.ink,bold=false){font(size,bold);ctx.fillStyle=color;ctx.fillText(String(s??''),Math.round(x),Math.round(y));}
function fit(s,max,size=12){s=String(s??'');if(width(s,size)<=max)return s;while(s&&width(s+'…',size)>max)s=s.slice(0,-1);return s+'…';}
function label(s,x,y,max,size=12,color=C.ink,bold=false){text(fit(s,max,size),x,y,size,color,bold);}
function center(s,x,y,w,size=12,color=C.ink,bold=false){text(s,x+(w-width(s,size))/2,y,size,color,bold);}
function wrap(s,max,size=12){
  const out=[];let line='';
  for(const ch of String(s??'')){if(ch==='\n'||(line&&width(line+ch,size)>max)){out.push(line);line=ch==='\n'?'':ch;}else line+=ch;}
  if(line)out.push(line);
  return out;
}
function lines(s,x,y,max,size=12,color=C.ink,limit=3,leading=17){
  const out=wrap(s,max,size);
  out.slice(0,limit).forEach((l,i)=>text(i===limit-1&&out.length>limit?fit(l+'…',max,size):l,x,y+i*leading,size,color));
  return Math.min(out.length,limit)*leading;
}
function icon(name,x,y,color=C.ink,scale=1){(ICONS[name]||ICONS.bag).forEach((r,j)=>Array.from(r).forEach((v,i)=>{if(v==='1')rect(x+i*scale,y+j*scale,scale,scale,color);}));}
function sprite(p,x,y,size=36){
  if(!p?.sid)return;
  let im=sprites.get(p.sid);
  if(!im&&typeof Image!=='undefined'){
    im=new Image();sprites.set(p.sid,im);im.onload=()=>draw();im.onerror=()=>{im.failed=true;draw();};im.src=`/demo/sprite/${p.sid}.png`;
  }
  if(im?.complete&&im.naturalWidth){
    const w=im.naturalWidth,h=im.naturalHeight;
    // The same nearest-neighbour fit as the battle renderer; integer target pixels.
    const scale=Math.min(size/w,size/h),dw=Math.round(w*scale),dh=Math.round(h*scale);
    ctx.drawImage(im,Math.round(x+(size-dw)/2),Math.round(y+(size-dh)/2),dw,dh);
  }else{icon('dex',x+size/2-4,y+size/2-4,C.line);}
}
function header(s,subtitle){
  rect(0,0,240,28,C.ink);label(s.title,10,20,186,14,C.paper,true);
  if(s.total)text(`${s.selected+1}/${s.total}`,205,19,10,'#d5ddbf');
  if(s.hud&&!['home','expedition','collection','loadout','challenges','dex'].includes(s.page)){hud(s,28);return 57;}
  if(subtitle){label(subtitle,10,45,220,10,C.muted);return 56;}
  return 42;
}
function hud(s,y=0){
  const h=s.hud||{},vals=[['HP',h.hp??'—',48],['金币',h.gold??'—',48],['LV',h.level??'—',37],['回合',s.round??'—',45],['上场',`${h.on_board??0}/${h.pop??0}`,62]];
  let x=0;rect(0,y,240,27,C.paper);
  vals.forEach(([name,n,w])=>{rect(x+w-1,y+4,1,19,C.line);text(name,x+5,y+10,8,C.muted);text(n,x+5,y+23,12,name==='HP'&&n<30?C.red:C.ink,true);x+=w;});rect(0,y+26,240,1,C.line);
}
function footer(s){
  rect(0,297,240,23,C.ink);
  if(pressed.has('C')&&heldAt.has('C')){
    const ms=Date.now()-heldAt.get('C');
    rect(0,297,Math.min(240,ms/1500*240),2,C.gold);
    text(ms>=600?'松开看详情 · 继续按住关屏':'松开确认 · 按住看详情',9,313,11,C.paper);
    return;
  }
  const detail=!!s.detail,grid=s.page?.includes('columns'),row=s.page?.endsWith('_rows');
  const a=detail?'上页':grid?'前格':row?'上行':'上项';
  const b=detail?'下页':grid?'后格':row?'下行':'下项';
  let c=detail?'返回':s.page==='shop'&&s.selected<4?'买入':grid?'选定':'确认';
  const hints=[['A',a],['B',b],['C',c]];
  hints.forEach(([key,t],i)=>{const x=8+i*59;box(x,303,12,12,i===2?C.gold:'#485b48',i===2?C.gold:'#485b48');text(key,x+3,312,9,C.white,true);text(t,x+16,312,10,C.paper);});
  text(s.can_back?'B长按返':'长按详情',186,312,9,'#c0c9ac');
}
function corner(x,y,w,h,color=C.gold){
  [[x,y,1,1],[x+w-1,y,-1,1],[x,y+h-1,1,-1],[x+w-1,y+h-1,-1,-1]].forEach(([a,b,dx,dy])=>{rect(dx>0?a:a-5,b,6,2,color);rect(a,dy>0?b:b-5,2,6,color);});
}
function cell(p,c,y,{enemy=false,bench=false,active=false,source=false}={}){
  const x=c*40,h=bench?32:40;
  box(x,y,40,h,bench?'#dee0c5':enemy?(c%2?'#cdbf96':'#d5c8a2'):(c%2?'#aebb97':'#b6c39e'),bench?'#aeb694':enemy?'#b4a57e':'#97a981');
  if(p){
    rect(x+10,y+h-7,20,3,enemy?'#b6a77f':'#91a57e');rect(x+13,y+h-4,14,1,enemy?'#b6a77f':'#91a57e');
    sprite(p,x+3,y+(bench?0:2),bench?30:34);
    if(p.item)rect(x+3,y+3,3,3,C.gold);
    if(p.technique)rect(x+8,y+3,3,3,'#527d98');
    if(enemy&&p.ability&&!bench){box(x+2,y+24,10,12,C.paper,'#87703f');text(p.ability.weather==='rain'?'雨':'日',x+3,y+33,8,'#87703f',true);}
  }else{rect(x+19,y+Math.floor(h/2),2,2,bench?'#aeb694':enemy?'#b4a57e':'#97a981');}
  if(source){rect(x+1,y+1,10,10,C.ink);text('起',x+2,y+9,8,C.white);}
  if(active){box(x+1,y+1,38,h-2,'transparent',C.ink);corner(x+1,y+1,37,h-3,C.white);rect(x+16,y+h-4,8,3,C.gold);}
}
function formation(s){
  hud(s);const opp=s.scene?.opponent||{};
  rect(0,27,240,18,C.ink);label(opp.name?`对手 · ${opp.name}`:'等待配对',6,39,140,10,C.paper);
  const weather=s.scene?.weather?.zh&&s.scene.weather.zh!=='无'?s.scene.weather.zh:'晴朗';
  const tactical=['tactics_v1','tactics_v2','tactics_v3','tactics_v4'].includes(s.ruleset),entry=s.scene?.entry_weather;
  const opening=entry&&(entry.you?.length||entry.opponent?.length);
  label(opening?`入场 · ${entry.conflict?'晴雨相抵':entry.zh}`:tactical?`共用 · ${weather}`:weather,tactical?151:190,39,tactical?83:44,10,'#d8cf99');
  for(let r=0;r<2;r++)for(let c=0;c<6;c++)cell(opp.rows?.[r]?.[c],c,45+r*40,{enemy:true});
  rect(0,125,240,5,C.ink);for(let x=4;x<240;x+=10)rect(x,127,4,1,C.gold);
  const selectingRows=s.page==='board_rows'||s.page==='move_rows';
  const selectingCols=s.page==='board_columns'||s.page==='move_columns';
  const activeRow=selectingRows?s.selected:selectingCols?s.row:-1;
  for(let r=0;r<2;r++)for(let c=0;c<6;c++)cell(s.board?.[r]?.[c],c,130+r*40,{active:activeRow===r&&(selectingRows||s.selected===c),source:s.focus?.loc===`g${r},${c}`&&s.page.startsWith('move')});
  tacticsOverlay(s);
  if(!(s.board||[]).flat().some(Boolean)&&s.page==='prep'){center('队伍还没上场',0,162,240,13,C.ink,true);center((s.bench||[]).length?'选择棋盘，将伙伴放上战场':'去商店招募第一位伙伴',0,183,240,10,C.muted);}
  rect(0,210,240,4,C.ink);
  for(let c=0;c<6;c++)cell(s.bench?.[c],c,214,{bench:true,active:activeRow===2&&(selectingRows||s.selected===c),source:s.focus?.loc===`b${c}`&&s.page.startsWith('move')});
  // Small lane labels stay on empty edge space; unit images remain unobscured.
  if(!(s.bench||[]).some(Boolean))center('备 战 席',0,235,240,10,C.muted);
}
function tacticsOverlay(s){
  if(!['tactics_v1','tactics_v2','tactics_v3','tactics_v4'].includes(s.ruleset))return;
  const located=new Map();
  (s.board||[]).forEach((cells,r)=>cells.forEach((p,c)=>{if(p)located.set(p.uid,{x:c*40,y:130+r*40,p});}));
  const saved=s.scene?.tactical||{},preview=s.tactical_preview;
  const guard=preview?.guard||saved.guard,weather=preview?.weather||saved.weather;
  const color=preview?.guard&&preview.valid===false?C.red:'#536f86';
  const mark=(at,glyph,tint,offset=28,yOffset=2)=>{if(!at)return;box(at.x+offset,at.y+yOffset,10,12,C.paper,tint);text(glyph,at.x+offset+1,at.y+yOffset+9,8,tint,true);};
  for(const at of located.values())if(at.p.ability)mark(at,at.p.ability.weather==='rain'?'雨':'日','#87703f',2,24);
  if(guard){
    const source=located.get(guard.uid),target=located.get(guard.target_uid);
    if(source&&target){
      // Route along the floor/gutter, leaving both portraits and cell centres
      // visible. The controller owns validity; this is only a relationship view.
      if(source.y===target.y){
        rect(Math.min(source.x,target.x)+20,source.y+37,Math.abs(source.x-target.x),2,color);
      }else{
        const x=Math.max(source.x,target.x)+38;
        rect(x,Math.min(source.y,target.y)+37,2,Math.abs(source.y-target.y),color);
        rect(source.x+20,source.y+37,x-source.x-18,2,color);rect(target.x+20,target.y+37,x-target.x-18,2,color);
      }
      corner(target.x+1,target.y+1,38,38,color);
      mark(source,'护',color);mark(target,'守',color);
    }
  }
  if(weather){
    const at=located.get(weather.uid),protectedWeather=guard?.target_uid===weather.uid;
    mark(at,at?.p.technique?.id==='rain_dance'?'雨':'晴','#87703f',protectedWeather?16:28);
  }
  if(s.page==='piece_tactics'&&s.focus?.loc?.startsWith('g')){
    const at=located.get(s.focus.piece.uid);if(at)corner(at.x+1,at.y+1,38,38,C.white);
  }
}
function prep(s){
  formation(s);rect(0,247,240,50,C.paper);
  (s.choices||[]).forEach((r,i)=>{const x=1+i*34,on=i===s.selected;box(x,250,33,22,on?C.ink:'#e3e3c8',on?C.ink:C.line);icon(PREP_ICONS[i],x+12,256,on?C.paper:C.muted);if(on)rect(x+8,273,17,2,C.gold);});
  if(s.scene?.pending_rewards){box(90,248,12,12,C.gold,C.ink);center(s.scene.pending_rewards,90,258,12,8,C.ink,true);}
  label(s.active?.label,9,290,150,13,C.ink,true);text(`${s.selected+1} / ${s.total}`,201,289,10,C.muted);
}
function board(s){
  formation(s);rect(0,247,240,50,C.paper);
  if(s.page.endsWith('_rows')){
    ['前排','后排','备战'].forEach((name,i)=>{box(5+i*78,251,74,22,s.selected===i?C.ink:C.white);center(name,5+i*78,267,74,12,s.selected===i?C.paper:C.ink);});
    label(s.page.startsWith('move')?`移动 ${s.focus?.piece?.name||'棋子'} · 选择目标行`:'选择行，再选择宝可梦',8,290,224,11,C.muted);
  }else{
    const p=s.active?.portrait;
    label(s.active?.label,8,265,167,13,C.ink,true);text(`${s.selected+1}/6`,207,264,10,C.muted);
    const detail=s.page.startsWith('move')?(p?'C 交换位置 · B 按住取消':'C 放置到这里 · B 按住取消'):(p?`${p.role||''} · ${(p.types||[]).join(' / ')}`:'这里是空位，选择有伙伴的格子');
    label(detail,8,286,224,11,C.muted);
  }
}
function partyStrip(s,y=47,benchOnly=false){
  const pieces=benchOnly?(s.bench||[]):[...(s.board||[]).flat().filter(Boolean),...(s.bench||[])];
  rect(0,y,240,33,'#dce0c6');
  for(let i=0;i<6;i++){const p=pieces[i];rect(i*40+39,y+5,1,23,C.line);if(p)sprite(p,i*40+5,y+1,30);else text('·',i*40+18,y+22,12,C.line);if(p&&p.uid===s.focus?.piece?.uid)corner(i*40+1,y,38,32,C.gold);}
}
function shop(s){
  hud(s);rect(0,27,240,18,C.ink);text('林间商店',7,40,11,C.paper,true);text(`备战 ${(s.bench||[]).length}/${s.hud?.bench_cap||6}`,175,40,10,'#d1d8b8');partyStrip(s,45,true);
  (s.choices||[]).slice(0,4).forEach((r,i)=>{
    const x=5+i%2*117,y=83+Math.floor(i/2)*65,on=s.selected===i,p=r.portrait;
    box(x,y,113,60,on?C.ink:C.white,on?C.ink:C.line);
    if(p){sprite(p,x+3,y+7,40);label(p.name,x+46,y+20,62,12,on?C.paper:C.ink,true);label((p.types||[]).join('/'),x+46,y+35,61,9,on?'#c6d0ae':C.muted);text(`${p.price??p.tier} 金`,x+46,y+50,11,on?'#edca75':C.gold,true);}
    else center('已售出',x,y+35,113,12,C.muted);
    if(on)corner(x,y,112,59,C.gold);
  });
  ['刷新','锁店','经验'].forEach((name,i)=>{const on=s.selected===i+4;box(5+i*78,218,74,25,on?C.ink:'#e1e2c8');icon(['shop','system','flag'][i],11+i*78,225,on?C.paper:C.muted);text(i===1&&s.hud?.shop_locked?'已锁':name,25+i*78,235,11,on?C.paper:C.ink);});
  const p=s.active?.portrait;
  label(p?.skill_name||s.active?.label,8,261,224,12,C.ink,true);
  lines(p?.skill_description||s.active?.detail||(s.selected===4?'花费金币，遇见新的伙伴':s.selected===5?'锁定后，下一轮保留当前商店':'购买经验，提升上场人数'),8,278,224,10,C.muted,1);
  if(p&&p.price>s.hud?.gold)text('金币不足',173,293,10,C.red);
}
function piece(s){
  header({...s,title:s.focus?.piece?.name||'伙伴资料'});const p=s.focus?.piece;
  if(!p){list(s,60);return;}
  box(8,60,224,104,C.white);rect(9,61,68,102,'#dbe1c6');sprite(p,15,71,56);
  center(s.focus.loc?.startsWith('b')?'备战中':'已上场',9,150,68,10,C.muted);
  label(p.role||'队伍成员',85,78,138,12,C.ink,true);label((p.types||[]).join(' / ')+(p.ability?` · ${p.ability.name}`:''),85,96,138,11,C.muted);
  label(p.skill_name,85,116,138,12,C.ink,true);
  label(`装备 · ${p.item_name||'无'}`,85,136,138,10,C.muted);label(`招式 · ${p.technique?.name||'未学习'}`,85,153,138,10,C.muted);
  partyStrip(s,169);
  const names=['移动 / 交换','装备道具','卸下装备','学习招式','卖出',['tactics_v1','tactics_v2','tactics_v3','tactics_v4'].includes(s.ruleset)?'战术配置':'查看详情'];
  (s.choices||[]).forEach((r,i)=>{const x=8+i%2*114,y=209+Math.floor(i/2)*27,on=s.selected===i;box(x,y,110,24,on?C.ink:C.white);icon(['board','item','item','technique','coin','dex'][i],x+6,y+8,on?C.paper:C.muted);label(names[i],x+22,y+16,83,11,r.disabled?C.muted:on?C.paper:C.ink);});
}
function tactical(s){
  formation(s);rect(0,247,240,50,C.paper);
  const r=s.active||{},color=r.disabled?C.muted:C.ink;
  label(r.label||'选择伙伴安排分工',9,263,184,13,color,true);text(`${s.selected+1}/${s.total}`,207,262,10,C.muted);
  label(r.subtitle||s.focus?.piece?.name||'',9,282,222,10,C.muted);
  if(s.page==='guard_targets')text(s.tactical_preview?.valid===false?'红线：距离不符合':'连线为预览，确认后才生效',9,294,9,s.tactical_preview?.valid===false?C.red:'#536f86');
}
function rewardOptions(s){
  header(s);const choices=s.choices||[];
  choices.forEach((r,i)=>{
    const abandon=i===choices.length-1,on=s.selected===i,y=abandon?247:60+i*59,h=abandon?30:54;
    box(7,y,226,h,on?C.ink:C.white,on?C.ink:C.line);
    icon(r.icon||'technique',17,y+(abandon?10:12),on?C.gold:C.muted);
    label(r.label,34,y+18,186,12,on?C.paper:C.ink,true);
    if(!abandon){label(r.detail?.split('\n')[0]||'',17,y+34,207,9,on?'#d7dec7':C.muted);label(r.subtitle,17,y+47,207,9,on?'#edca75':'#536f86');}
    if(on)corner(7,y,225,h-1,C.gold);
  });
  text('C 预览确认 · 返回仍保留候选',10,291,10,C.muted);
}
function list(s,top=57,step=43){
  if(!s.rows.length){icon('bag',111,109,C.muted,2);center('这里暂时空着',0,159,240,14,C.muted);center(['techniques','learn_items'].includes(s.page)?'野怪轮可获得招式机器':'继续旅程，收集新的物资',0,181,240,11,C.muted);return;}
  s.rows.forEach((r,i)=>{
    const y=top+i*step,on=r.index===s.selected;
    box(7,y,224,step-4,on?C.ink:C.white,on?C.ink:C.line);
    const art=!!r.portrait||!!r.icon;
    if(r.portrait){rect(9,y+2,37,step-8,on?'#b8c59d':'#e4e5cc');sprite(r.portrait,11,y+3,32);}
    else if(r.icon)icon(r.icon,18,y+14,on?C.gold:C.muted);
    else if(on){rect(13,y+15,3,7,C.gold);rect(16,y+17,3,3,C.gold);}
    const x=art?52:23,color=r.disabled?(on?'#a9b895':'#818872'):on?C.paper:C.ink;
    const compact=step<38;
    label(r.label,x,y+(r.subtitle?(compact?12:16):(compact?20:24)),223-x,12,color,true);
    if(r.subtitle)label(r.subtitle,x,y+(compact?24:32),223-x,compact?9:10,on?'#c7d0b2':C.muted);
    if(r.disabled)rect(226,y+5,2,4,C.gold);
  });
  if(s.total>5){rect(235,top,2,step*5-4,'#d9dcc0');rect(235,top+Math.round(s.selected/Math.max(1,s.total-1)*(step*5-18)),2,14,C.muted);}
}
function meadow(){
  rect(0,28,240,97,'#dfe5c9');rect(0,89,240,36,'#b0c298');
  for(let x=6;x<240;x+=19){rect(x,109+(x%3)*3,1,4,'#91a87e');rect(x-1,108+(x%3)*3,3,1,'#91a87e');}
  [[1,13],[214,5]].forEach(([x,y])=>{rect(x+9,y+57,6,27,'#627958');rect(x+2,y+41,22,21,'#7f9d6e');rect(x+6,y+31,14,30,'#90ab79');rect(x,y+56,26,5,'#527051');});
}
function home(s){
  header(s);meadow();sprite({sid:1},34,67,40);sprite({sid:4},98,57,48);sprite({sid:7},164,67,40);
  center('和伙伴一起，走下一程',0,140,240,13,C.ink,true);list(s,149,28);
}
function expedition(s){
  header(s);rect(8,39,224,82,'#dce3c5');sprite({sid:s.scene?.loadout_partner||6},14,45,64);
  text('出发前的行囊',91,63,13,C.ink,true);text('搭档 · 招式 · 装备',91,84,11,C.muted);text(s.scene?.loadout_mode==='tactics'?'途中获取护卫与天气':'解锁新的阵容玩法',91,103,10,C.muted);list(s,129,39);
}
function inventory(s){
  header(s);const stock=s.scene?.inventory||{};
  rect(8,59,224,47,'#dfe3ca');
  [['item','装备',stock.items||0],['craft','组件',stock.components||0],['technique','机器',stock.techniques||0]].forEach(([ico,t,n],i)=>{const x=15+i*74;icon(ico,x,69,C.muted);text(`${n}`,x+16,79,14,C.ink,true);text(t,x+15,97,10,C.muted);});
  list({...s,rows:s.rows.map(r=>({...r,icon:r.icon||(r.label.includes('机器')?'technique':'bag')}))},115,s.total>4?35:42);
}
function result(s){
  header(s);const r=s.scene?.result||{};
  rect(8,59,224,60,'#dce2c5');icon(r.winner===0?'flag':'battle',19,72,C.muted,2);
  text(r.headline||(s.page==='spectate'?'观战下一轮':'本轮已结束'),48,84,17,C.ink,true);
  label(r.opp_name?`对手 · ${r.opp_name}`:'准备新的战术，再出发',48,105,175,11,C.muted);
  list(s,128,32);
}
function confirm(s){
  if(s.hud){formation(s);rect(0,247,240,50,C.paper);rect(0,27,240,220,'#162c2577');}
  else{header(s);meadow();}
  const h=100+Math.min(4,wrap(s.prompt,198,13).length)*18,y=Math.floor((297-h)/2),buttons=y+h-38;
  box(8,y,224,h,C.paper,C.ink);rect(11,y+3,218,28,C.ink);text('确认这次操作',22,y+22,14,C.paper,true);
  if(s.focus?.piece)sprite(s.focus.piece,199,y+5,24);
  lines(s.prompt,21,y+53,198,13,C.ink,4,18);
  s.rows.forEach((r,i)=>{const x=20+i*105,on=r.index===s.selected;box(x,buttons,95,26,on?C.ink:C.white,on?C.ink:C.line);center(r.label,x,buttons+18,95,12,on?C.paper:C.ink,true);if(on)rect(x+10,buttons+28,75,2,C.gold);});
  box(26,y+h+10,188,19,C.paper,C.paper);
  center('默认取消 · 确认后自动保存',26,y+h+23,188,10,C.ink);
}
function details(s){
  header(s);box(7,60,226,222,C.white);s.detail.forEach((l,i)=>text(l,15,80+i*24,12,C.ink));
  text(`${s.detail_page} / ${s.detail_total}`,191,273,10,C.muted);
}
function battle(s){
  const url=s.battle.url;
  if(url!==frameUrl){frameUrl=url;const token=++frameToken,im=new Image();im.onload=()=>{if(token===frameToken){frameImage=im;draw();}};im.src=url;}
  if(frameImage)ctx.drawImage(frameImage,0,0,240,320);else{formation(s);center('战斗画面载入中…',0,266,240,12);}
  rect(0,267,240,30,C.paper);label(s.active?.label||'查看结算',9,286,173,12,C.ink,true);text(`${s.battle.speed}×`,213,286,11,C.muted);
}
function draw(){
  if(!view)return;
  const s=view.screen;
  const description=view.sleeping?'屏幕已关闭。按任意键唤醒，整次唤醒手势不执行操作。':[s.title,s.prompt||'',...(s.detail||[]),...s.rows.map(r=>(r.index===s.selected?'当前选择：':'')+r.label+(r.subtitle?'，'+r.subtitle:'')),...s.footer].join('。');
  const a11y=document.getElementById('screen-text');if(a11y.textContent!==description)a11y.textContent=description;
  rect(0,0,240,320,C.paper);
  if(view.sleeping){rect(0,0,240,320,C.dark);icon('dex',107,116,'#a6b78e',3);center('旅程已保存',0,183,240,14,'#cbd6b4');center('轻按任意键唤醒',0,207,240,11,'#95a780');return;}
  if(s.page==='battle'&&s.battle)battle(s);
  else if(s.detail)details(s);
  else if(s.page==='prep')prep(s);
  else if(['board_rows','board_columns','move_rows','move_columns'].includes(s.page))board(s);
  else if(s.page==='shop')shop(s);
  else if(s.page==='piece')piece(s);
  else if(['piece_tactics','guard_targets'].includes(s.page))tactical(s);
  else if(s.page==='reward_options')rewardOptions(s);
  else if(s.page==='home')home(s);
  else if(s.page==='expedition')expedition(s);
  else if(s.page==='inventory')inventory(s);
  else if(s.page==='confirm')confirm(s);
  else if(['result','spectate'].includes(s.page))result(s);
  else{const top=header(s);list(s,Math.max(51,top));if(s.active?.detail)label(s.active.detail.split('\n')[0],10,289,220,10,C.muted);}
  if(notice.text&&Date.now()<notice.until&&s.page!=='battle'){
    box(8,53,224,50,C.white,C.gold);lines(notice.text,16,73,208,11,C.ink,2,17);
  }
  footer(s);
  const hint=document.getElementById('context-hint');
  if(hint)hint.textContent=s.page==='prep'?PREP_TIPS[s.selected]:s.page.startsWith('move')?'棋盘中的「起」标记是移动起点。选择目标行、目标格；有伙伴的格子会交换位置。':s.page==='shop'?'上方是备战席。选择宝可梦，按 C 买入；按住 C 查看技能与定位。':s.page.includes('board')?'金色光标显示当前选择。先选行，再选格，按 C 查看伙伴与可执行动作。':s.active?.detail||'A / B 选择，C 确认。按住 B 返回上一层。';
}
