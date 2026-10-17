/* Execute real preview players and authoring-page handlers with controlled I/O. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '../..');
const source = name => fs.readFileSync(path.join(ROOT,'tools/acceptance',name),'utf8');
const scenario = process.argv[2];
const settle = async () => { for(let n=0;n<5;n++) await new Promise(resolve=>setImmediate(resolve)); };
const clone = value => JSON.parse(JSON.stringify(value));
function playback({n=90,mode='arena',view='composite',paired=true,key='clip'}={}) {
  return {ok:true,key,mode,view,width:mode==='arena'?960:240,height:mode==='arena'?640:320,
    presentation:mode==='arena'?'web-arena-v2-articulated':'device-v1',render_revision:mode==='arena'?'web-r3':'device-v1',
    n,dt:.05,clip_start:.3,frames:Array.from({length:n},(_,i)=>`/preview/${key}/frames/${i}.png`),
    base_frames:Array.from({length:n},(_,i)=>`/preview/${key}/${paired?'base':'frames'}/${i}.png`),
    phases:[{label:'开始',at:.3},{label:'命中',at:.5},{label:'恢复',at:.7}],
    settings:{palette:'classic',effect_scale:1,particle_density:1,motion_scale:1},
    ...(view==='body'?{body_preview:{unit:0,scale:4,camera:'follow_cell',external_effects:false}}:{}),
    target_before_impact:{hp:100,energy:3},target_at_impact:{hp:50,energy:7},subject:{name:'目标'},metrics:{particle_peak:12,host_frame_ms_p95:7},skill_effects:[]};
}
function clock() {
  let counter=0,now=0;const timers=new Map(),rafs=new Map(),images=[],draws=[];
  const canvas=label=>({dataset:{},width:960,height:640,getContext(){return this.context ||= {imageSmoothingEnabled:false,clearRect(){},fillRect(){},drawImage(image){draws.push({label,src:image.src,index:Number(new URL(image.src).pathname.match(/(\d+)\.png$/)[1])});}};}});
  class Image {
    set src(value) {
      this._src=value;const rec={src:value,image:this,settled:false,load:(width=960,height=640)=>{if(rec.settled)return;rec.settled=true;this.naturalWidth=width;this.naturalHeight=height;this.onload?.();},fail:()=>{if(rec.settled)return;rec.settled=true;this.onerror?.();}};images.push(rec);
    }
    get src(){return this._src;} removeAttribute(name){if(name==='src')this._src='';}
  }
  const context={URL,URLSearchParams,AbortController,Image,location:{href:'http://fixture.invalid/animation-lab'},
    setTimeout:(callback,delay)=>{const id=++counter;timers.set(id,{callback,delay});return id;},clearTimeout:id=>timers.delete(id),
    requestAnimationFrame:callback=>{const id=++counter;rafs.set(id,callback);return id;},cancelAnimationFrame:id=>rafs.delete(id)};
  function tick(ms=50){now+=ms;for(const [id,callback]of [...rafs]){if(!rafs.has(id))continue;rafs.delete(id);callback(now);}}
  const active=()=>images.filter(rec=>!rec.settled && (rec.image.onload || rec.image.onerror));
  function loadPending(width=960,height=640) {let limit=0;while(active().length){assert.ok(limit++<100,'Prefetch must settle within a bounded number of requests');for(const rec of active())rec.load(width,height);}}
  const forFrame=(index)=>active().filter(rec=>Number(new URL(rec.src).pathname.match(/(\d+)\.png$/)[1])===index);
  return {context,timers,rafs,images,draws,canvas,tick,active,loadPending,forFrame};
}
function playerFixture(options={}) {
  const c=clock(), frames=[], states=[],canvases=[c.canvas('base'),c.canvas('edited')].slice(0,options.pair===false?1:2);
  c.context.module={exports:{}};vm.runInNewContext(source('animation_player.js'),c.context);
  const api=c.context.module.exports;
  const player=new api.PreviewPlayer({canvases,maxCache:options.maxCache || 12,baseURL:'http://fixture.invalid/animation-lab',onFrame:value=>frames.push(value),onState:value=>states.push(value)});
  return {...c,api,player,canvases,frames,states};
}
const cases={
  async paired(){
    const p=playerFixture();const ready=p.player.load(playback());
    assert.equal(p.active().length,8,'Four concurrent paired frames are allowed');
    p.forFrame(2).forEach(rec=>rec.load());assert.equal(p.draws.length,0,'Prefetching must not display another frame');
    const first=p.forFrame(0);first[1].load();assert.equal(p.draws.length,0,'Both default and edited frame must be ready before either canvas advances');
    first[0].load();await ready;assert.deepEqual(p.draws.map(draw=>draw.index),[0,0]);
    p.loadPending();p.player.seek(7);assert.deepEqual(p.draws.slice(-2).map(draw=>draw.index),[7,7]);
    assert.equal(p.player.frame,7);assert.equal(p.player.getState().status,'ready');
    assert.ok(p.canvases.every(canvas=>canvas.width===960 && canvas.height===640 && canvas.context.imageSmoothingEnabled));
    assert.ok(p.images.every(rec=>new URL(rec.src).searchParams.get('v')==='web-r3'));p.player.cancel();
    const q=playerFixture();const same=q.player.load(playback({paired:false,n:9}));q.loadPending();await same;
    assert.equal(q.images.length,9,'Identical default and edited URLs share one image');q.player.cancel();
  },
  async rollingCache(){
    for(const maxCache of [12,24]){
      const p=playerFixture({maxCache,pair:false});const ready=p.player.load(playback({n:180}),{autoplay:true});p.loadPending();await ready;p.tick(0);
      for(let i=0;i<180 && p.player.frame<179;i++){p.tick();p.loadPending();assert.ok(p.player.cache.size<=maxCache);assert.ok(p.player.pending.size<=4);}
      assert.equal(p.player.frame,179);assert.equal(p.player.getState().status,'complete');
      assert.equal(p.images.length,180,'Forward playback should read each frame once, without eviction/refetch loops');p.player.cancel();
    }
  },
  async failedSeek(){
    const p=playerFixture({maxCache:12});const ready=p.player.load(playback({n:200}));p.loadPending();await ready;
    p.player.seek(150);p.forFrame(150)[0].fail();p.loadPending();
    assert.equal(p.player.frame,0,'Failed seeks retain the displayed frame');assert.equal(p.player.getState().status,'error');
    assert.ok(p.player.cache.size<=12);const attempts=p.images.length;p.player.pump();p.loadPending();
    assert.equal(p.images.length,attempts,'An old visible frame and failed far seek may not repeatedly evict prefetch frames');
    p.player.retry();p.loadPending();assert.equal(p.player.frame,150);assert.equal(p.player.getState().error,null);p.player.cancel();
  },
  async failure(){
    const p=playerFixture();const rejected=p.player.load(playback({n:20}),{autoplay:true}).catch(error=>error);
    p.forFrame(0)[0].fail();const error=await rejected;assert.match(error.message,/读取失败/);
    p.loadPending();assert.equal(p.player.getState().status,'error');assert.equal(p.draws.length,0);
    p.player.retry();p.loadPending();assert.equal(p.player.frame,0);assert.equal(p.player.getState().playing,true);p.tick(0);p.tick(50);assert.equal(p.player.frame,1);
    p.player.pause();p.player.seek(18);p.forFrame(18)[0].fail();p.loadPending();assert.equal(p.player.getState().status,'error');
    p.player.retry();p.loadPending();assert.equal(p.player.frame,18);assert.equal(p.player.wanted,false);p.player.cancel();
  },
  async bufferPause(){
    const p=playerFixture({pair:false,maxCache:4});const ready=p.player.load(playback({n:40}),{autoplay:true});p.forFrame(0)[0].load();await ready;
    assert.equal(p.player.getState().status,'buffering');p.player.pause();p.loadPending();p.tick();assert.equal(p.player.frame,0,'Pause during next-frame buffering prevents later image callbacks from starting playback');
    p.player.play();p.tick(0);p.tick(50);assert.equal(p.player.frame,1);
    p.tick(200);assert.equal(p.player.getState().status,'buffering');const displayed=p.player.frame;
    p.player.pause();p.loadPending();p.tick();assert.equal(p.player.frame,displayed,'Pause must clear automatic advancement requests');
    p.player.seek(-9);p.loadPending();assert.equal(p.player.frame,0);p.player.seek(999);p.loadPending();assert.equal(p.player.frame,39);p.player.cancel();
  },
  async stale(){
    const p=playerFixture({pair:false});const old=p.player.load(playback({key:'old',n:15})).catch(error=>error);
    const record=p.forFrame(0)[0], callback=record.image.onload,expired=[...p.timers.values()][0].callback;
    const current=p.player.load(playback({key:'current',n:15}));assert.equal((await old).name,'AbortError');
    record.image.naturalWidth=960;record.image.naturalHeight=640;callback();expired();assert.equal(p.draws.length,0,'Cancelled-generation callbacks must not paint or error');
    p.loadPending();await current;assert.ok(p.draws.every(draw=>draw.src.includes('/current/')));p.player.cancel();assert.equal(p.timers.size,0);assert.equal(p.rafs.size,0);assert.equal(p.player.getState().status,'cancelled');
  },
  async modes(){
    const p=playerFixture({pair:false});const normal=playback();assert.throws(()=>p.api.normalizePlayback({...normal,presentation:{bad:true}}));
    assert.throws(()=>p.api.normalizePlayback({...normal,width:240}));assert.throws(()=>p.api.normalizePlayback({...normal,frames:['https://untrusted.invalid/frame.png'],n:1,base_frames:['https://untrusted.invalid/frame.png']}));
    assert.throws(()=>p.api.normalizePlayback({...normal,dt:0}));assert.throws(()=>p.api.normalizePlayback({...normal,n:2}));assert.throws(()=>p.api.normalizePlayback(normal,{mode:'classic'}));
    assert.equal(p.api.presetMode({species:6}),'classic');assert.equal(p.api.presetMode({mode:'arena'}),'arena');assert.equal(p.api.presetMode({mode:'broken'}),null);
    const classic=playback({mode:'classic',n:8});const {frames,base_frames,...meta}=classic;const ready=p.player.load({ok:true,meta,frames,base_frames},{mode:'classic'});p.loadPending(240,320);await ready;
    assert.equal(p.canvases[0].width,240);assert.equal(p.canvases[0].height,320);assert.equal(p.canvases[0].context.imageSmoothingEnabled,false);p.player.cancel();
  },
};
function character(species,mode) {
  return {species,name:species===212?'巨钳螳螂':species===19?'小拉达':species===9?'水箭龟':'喷火龙',role:'攻击型',cost:2,range:3,
    skill:{name:'测试技能',description:'实际原生技能',tactic:'侧翼',counterplay:'控制',can_cast:true,tier:mode==='arena'?'native':'generic'},
    rig:{parts:[],implemented:false},motion_notes:{},
    capabilities:{body:'procedural',editable_controls:['palette','effect_scale','particle_density','motion_scale'],resource_ready:true,
      action_matrix:Object.fromEntries(['idle','move','attack','cast','hit','death'].map(kind=>[kind,{label:kind,body:'procedural',parts:'none',supported:true,preview:true}]))}};
}
async function previewPage(name,options={}) {
  const c=clock(),fetches=[],held=[];let document;
  const voids=new Set(['area','base','br','col','embed','hr','img','input','link','meta','source','track','wbr']);
  const decode=text=>text.replace(/&(amp|lt|gt|quot|#39);/g,(_,key)=>({amp:'&',lt:'<',gt:'>',quot:'"','#39':"'"})[key]);
  class Element {
    constructor(tag,attrs={}) {
      this.tagName=tag.toUpperCase();this.attrs=attrs;this.children=[];this.listeners={};this.parentElement=null;this._text='';this._value=attrs.value ?? null;
      this.hidden=Object.hasOwn(attrs,'hidden');this.disabled=Object.hasOwn(attrs,'disabled');this.files=[];this.style={};this.width=Number(attrs.width)||300;this.height=Number(attrs.height)||150;
      this.dataset=new Proxy({}, {set:(obj,key,value)=>{obj[key]=String(value);this.attrs['data-'+key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase())]=String(value);return true;}});
      for(const[key,value]of Object.entries(attrs))if(key.startsWith('data-'))this.dataset[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;
      this.classList={toggle:(key,on)=>{const names=this.className.split(/\s+/).filter(Boolean);on ??= !names.includes(key);this.className=on?[...new Set([...names,key])].join(' '):names.filter(n=>n!==key).join(' ');},add:key=>this.classList.toggle(key,true),remove:key=>this.classList.toggle(key,false)};
    }
    get id(){return this.attrs.id || '';}set id(value){this.attrs.id=String(value);}
    get className(){return this.attrs.class || '';}set className(value){this.attrs.class=String(value);}
    get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}set textContent(value){this._text=String(value);this.children=[];}
    get value(){return this._value ?? (this.tagName==='SELECT'?(this.children.find(child=>child.attrs.selected!=null)||this.children.find(child=>child.tagName==='OPTION'))?.value || '':this.tagName==='OPTION'?this.textContent:'');}set value(value){this._value=String(value);}
    get valueAsNumber(){return this.value.trim()===''?NaN:Number(this.value);}
    get open(){return this.attrs.open!=null;}set open(value){value?this.attrs.open='':delete this.attrs.open;}
    getAttribute(key){return this.attrs[key] ?? null;}setAttribute(key,value){this.attrs[key]=String(value);}removeAttribute(key){delete this.attrs[key];}
    append(...children){for(let child of children){if(typeof child==='string'){const e=new Element('#text');e.textContent=child;child=e;}child.parentElement=this;this.children.push(child);}}
    prepend(...children){const nodes=children.map(child=>typeof child==='string'?Object.assign(new Element('#text'),{_text:child}):child);for(const child of nodes)child.parentElement=this;this.children.unshift(...nodes);}
    replaceChildren(...children){this.children=[];this._text='';this.append(...children);}
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);}
    addEventListener(type,fn){(this.listeners[type] ||= []).push(fn);}
    matches(selector){return selector.split(',').some(s=>{const attrs=[...s.matchAll(/\[([^=\]]+)(?:=["']?([^\]"']*)["']?)?\]/g)],simple=s.replace(/\[[^\]]+\]/g,'').trim(),tag=simple.match(/^[a-z][\w-]*/i)?.[0],id=simple.match(/#([\w-]+)/)?.[1];return (!tag||this.tagName===tag.toUpperCase())&&(!id||this.id===id)&&[...simple.matchAll(/\.([\w-]+)/g)].every(m=>this.className.split(/\s+/).includes(m[1]))&&attrs.every(([,key,value])=>this.attrs[key]!=null&&(value==null||this.attrs[key]===value));});}
    closest(selector){return this.matches(selector)?this:this.parentElement?.closest(selector)||null;}
    querySelectorAll(selector){const result=[];for(const child of this.children){if(child.matches(selector))result.push(child);result.push(...child.querySelectorAll(selector));}return result;}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    getContext(kind){assert.equal(kind,'2d');return this.context ||= {imageSmoothingEnabled:false,clearRect(){},fillRect(){},drawImage:image=>c.draws.push({label:this.id,src:image.src,index:Number(new URL(image.src).pathname.match(/(\d+)\.png$/)[1])})};}
  }
  const root=new Element('document');
  function parse(html){const stack=[root];for(const token of html.matchAll(/<![^>]*>|<\/?([\w:-]+)([^>]*?)\/?>|([^<]+)/g)){if(token[0].startsWith('<!'))continue;if(token[3]){const text=new Element('#text');text._text=decode(token[3]);stack.at(-1).append(text);}else if(token[0].startsWith('</')){const i=stack.findLastIndex(node=>node.tagName===token[1].toUpperCase());if(i>0)stack.length=i;}else{const attrs=Object.fromEntries([...token[2].matchAll(/([^\s=\/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)].map(([,key,a,b,d])=>[key,decode(a??b??d??'')]));const e=new Element(token[1],attrs);stack.at(-1).append(e);if(!voids.has(token[1])&&!token[0].endsWith('/>'))stack.push(e);}}}
  const html=source(name+'.html');parse(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<style\b[^>]*>[\s\S]*?<\/style>/g,''));
  document={hidden:false,listeners:{},body:root.querySelector('body'),getElementById:id=>root.querySelector('#'+id),querySelectorAll:s=>root.querySelectorAll(s),querySelector:s=>root.querySelector(s),createElement:tag=>new Element(tag),addEventListener(type,fn){(this.listeners[type] ||= []).push(fn);}};
  const reply=(data)=>({ok:true,status:200,json:async()=>clone(data)});
  const historyCalls=[];const location={href:'http://fixture.invalid/'+name,search:options.query||''};
  const history={replaceState(data,title,url){historyCalls.push(String(url));const next=new URL(url,location.href);location.href=next.href;location.search=next.search;}};
  const context=vm.createContext({...c.context,document,window:{matchMedia:()=>({matches:!!options.reducedMotion}),history},Blob,location,history,console,
    fetch:(url,args={})=>{
      const record={url,args,body:args.body?JSON.parse(args.body):null};fetches.push(record);
      const mode=new URL(url,'http://fixture.invalid').searchParams.get('mode') || record.body?.mode || 'arena';
      const sid=mode==='arena'?212:19;
      const failure=options.fail?.(record); if(failure)return Promise.resolve({ok:false,status:failure,json:async()=>({ok:false,error:'HTTP '+failure})});
      let data;
      if(url.startsWith('/api/animation/characters'))data={ok:true,characters:{[sid]:character(sid,mode),6:character(6,mode),...(mode==='arena'?{9:character(9,mode),68:character(68,mode)}:{})}};
      else if(url==='/api/animation/preview')data={...playback({mode:record.body.mode,view:record.body.view || 'composite',key:'preview'+fetches.length,n:12}),settings:record.body.settings,...options.preview?.(record)};
      else if(url==='/api/animation/preset/validate')data={ok:true,preset:{...record.body,mode:record.body.mode || 'classic'}};
      else if(url==='/.build/animation-b/manifest.json')return Promise.resolve({ok:false,status:404,json:async()=>({})});
      else throw new Error('Unexpected request '+url);
      if(options.hold?.(record)){return new Promise(resolve=>held.push({record,release:()=>resolve(reply(data))}));}
      const response=Promise.resolve(reply(data));if(url==='/api/animation/preview'&&!options.manualImages)response.then(()=>queueMicrotask(()=>{for(const rec of c.active())rec.load(mode==='arena'?960:240,mode==='arena'?640:320);}));return response;
    }});
  vm.runInContext(source('animation_player.js'),context);
  const inline=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(match=>match[1]).filter(s=>s.trim()).join('\n');
  vm.runInContext(inline,context);
  async function finish(){await settle();if(!options.manualImages){for(let n=0;n<10 && c.active().length;n++){const mode=document.body.dataset.mode || 'arena';c.loadPending(mode==='arena'?960:240,mode==='arena'?640:320);await settle();}}}
  await finish();
  const element=id=>{const e=document.getElementById(id);assert.ok(e,'Missing #'+id);return e;};
  async function start(id,type='click',extra={}) {const target=typeof id==='string'?element(id):id,event={target,preventDefault(){},...extra},pending=[];for(const fn of target.listeners[type]||[])pending.push(fn(event));let parent=target.parentElement;while(parent){for(const fn of parent.listeners[type]||[])pending.push(fn(event));parent=parent.parentElement;}for(const fn of document.listeners[type]||[])pending.push(fn(event));const done=Promise.all(pending);await finish();return {done};}
  async function dispatch(id,type='click',extra={}) {const begun=await start(id,type,extra);await begun.done;await finish();}
  async function change(id,value,type='change'){element(id).value=value;await dispatch(id,type);}
  return {...c,fetches,held,historyCalls,document,element,start,dispatch,change,finish,context};
}
cases.lab=async()=>{
  const p=await previewPage('animation_lab',{query:'?mode=arena&species=212&kind=hit'});
  assert.equal(p.element('species').value,'212');assert.equal(p.fetches[0].url,'/api/animation/characters?mode=arena');
  let previews=p.fetches.filter(rec=>rec.url==='/api/animation/preview');assert.equal(previews.length,1,'Lab should only render the selected action once');assert.equal(previews[0].body.species,212);assert.equal(previews[0].body.kind,'hit');
  assert.equal(p.element('preview-canvas').width,960);assert.equal(p.element('preview-canvas').height,640);assert.equal(p.element('empty').hidden,true);assert.equal(p.element('seek').max,11);
  assert.ok(p.element('editor-link').href.includes('mode=arena'));assert.ok(p.element('editor-link').href.includes('species=212'));
  assert.equal(p.fetches.filter(rec=>rec.url.startsWith('/.build')).length,0,'Historical manifests are not eagerly loaded');
  await p.change('mode','classic');assert.equal(p.document.body.dataset.mode,'classic');assert.equal(p.element('preview-canvas').width,240);
  assert.equal(p.fetches.filter(rec=>rec.url==='/api/animation/preview').length,1,'Mode switching only reloads catalog until explicit generation');
  await p.change('species','19');await p.dispatch('preview-form','submit');previews=p.fetches.filter(rec=>rec.url==='/api/animation/preview');assert.equal(previews.at(-1).body.mode,'classic');assert.equal(previews.at(-1).body.species,19);assert.equal(p.element('preview-canvas').getContext('2d').imageSmoothingEnabled,false);
  p.element('history').open=true;await p.dispatch('history','toggle');assert.equal(p.element('history-body').hidden,true);assert.match(p.element('history-status').textContent,/暂不可用/);assert.equal(p.element('empty').hidden,true,'Missing historical evidence cannot break live preview');
};
cases.assistIdentity=async()=>{
  const preview=()=>({targeting:'ally',native_skill:{targeting:'ally'},
    phases:[{label:'开始',at:.3},{label:'释放',at:.4},{label:'生效',at:.5},{label:'恢复结束',at:.7}],
    subject:{name:'怪力'},target_before_impact:{hp:450,energy:25,shield:0},
    target_at_impact:{hp:450,energy:43,shield:84},
    skill_effects:[{at:.5,target:'怪力',effect:'shield',payload:{amount:84}},{at:.5,target:'怪力',effect:'energy',payload:{amount:18}}]});
  const lab=await previewPage('animation_lab',{query:'?mode=arena&species=212&kind=cast',reducedMotion:true,preview});
  assert.match(lab.element('subject').textContent,/生效前 → 生效时/);
  assert.match(lab.element('snapshot-shield').textContent,/0 → 84/);assert.equal(lab.element('snapshot-shield').hidden,false);
  assert.equal(lab.element('snapshot-hp').textContent,'450 → 450');assert.equal(lab.element('snapshot-energy').textContent,'25 → 43');
  assert.ok(lab.element('phases').children.some(node=>node.textContent.startsWith('生效 ')));
  assert.match(lab.element('skill-outcomes').textContent,/护盾/);assert.match(lab.element('skill-outcomes').textContent,/补充能量/);
  await lab.change('mode','classic');assert.equal(lab.element('snapshot-shield').hidden,true,'Mode switching clears the old shield snapshot');
  const editor=await previewPage('animation_editor',{query:'?mode=arena&species=212&kind=cast',reducedMotion:true,preview});
  await editor.dispatch('settings-form','submit');
  assert.match(editor.element('snapshot-title').textContent,/生效快照/);assert.equal(editor.element('before-hp-label').textContent,'生效前 HP');
  assert.equal(editor.element('at-hp-label').textContent,'生效时 HP');assert.match(editor.element('shield-snapshot').textContent,/0 → 84/);
  assert.equal(editor.element('shield-snapshot').hidden,false);assert.match(editor.element('skill-outcomes').textContent,/护盾 84/);
  assert.ok(editor.element('phase-rail').querySelectorAll('.marker.impact').length,'The actual benefit phase has a timeline impact marker');
};
cases.bodyView=async()=>{
  const p=await previewPage('animation_lab',{query:'?mode=arena&species=212&kind=hit&view=body'});
  assert.equal(p.element('view').value,'body');assert.equal(p.document.body.dataset.view,'body');
  let previews=p.fetches.filter(rec=>rec.url==='/api/animation/preview');
  assert.equal(previews.at(-1).body.view,'body');assert.equal(p.element('preview-canvas').dataset.view,'body');
  assert.equal(p.element('preview-canvas').getContext('2d').imageSmoothingEnabled,false,'Body frames are fixed 4x NEAREST samples');
  assert.ok(p.element('editor-link').href.includes('view=body'));
  const samples=p.element('body-samples').querySelectorAll('[data-body-kind]');
  assert.equal(samples.length,6);assert.ok([...samples].every(button=>button.dataset.bodyKind==='cast'));
  await p.dispatch(samples[0]);
  assert.equal(p.element('kind').value,'cast');assert.equal(p.element('species').value,'68');
  assert.match(p.element('status').textContent,/预览已就绪/);
  const speciesOptions=[...p.element('species').querySelectorAll('option')];
  assert.ok(speciesOptions.some(option=>option.value==='68' && option.textContent.startsWith('#068 ')),'The catalog loading placeholder must be replaced by the selected real character option');
  assert.ok(speciesOptions.every(option=>!option.textContent.includes('正在读取角色目录')));
  previews=p.fetches.filter(rec=>rec.url==='/api/animation/preview');
  assert.equal(previews.at(-1).body.view,'body');assert.equal(previews.at(-1).body.species,68);
  assert.match(p.historyCalls.at(-1),/[?&]view=body/);assert.match(p.historyCalls.at(-1),/[?&]kind=cast/);
  await p.change('view','composite');assert.equal(p.document.body.dataset.view,'composite');
  assert.ok(!p.historyCalls.at(-1).includes('view=body') || new URL(p.historyCalls.at(-1),'http://fixture.invalid').searchParams.get('view')==='composite');
  await p.change('mode','classic');
  assert.equal(p.element('view').value,'composite');
  await p.dispatch('preview-form','submit');
  previews=p.fetches.filter(rec=>rec.url==='/api/animation/preview');
  assert.equal(previews.at(-1).body.mode,'classic');assert.notEqual(previews.at(-1).body.view,'body');
  assert.equal(p.element('preview-canvas').dataset.view,'composite');
};
cases.editorBodyView=async()=>{
  let hold=false;const p=await previewPage('animation_editor',{query:'?mode=arena&species=212&kind=cast&view=body',reducedMotion:true,manualImages:true,hold:rec=>hold&&rec.url==='/api/animation/preview'});
  assert.equal(p.element('view').value,'body');
  const first=await p.start('settings-form','submit');p.loadPending();await first.done;await p.finish();
  const oldURL=p.draws.at(-1).src,oldKey=new URL(oldURL).pathname.split('/')[2];
  hold=true;await p.change('view','composite');
  assert.equal(p.held.length,1);assert.equal(p.held[0].record.body.view,'composite');
  assert.equal(p.draws.at(-1).src,oldURL,'The installed body result stays visible until the composite candidate is ready');
  p.held[0].release();for(let n=0;n<10;n++){p.loadPending();await p.finish();}
  const newURL=p.draws.at(-1).src,newKey=new URL(newURL).pathname.split('/')[2];
  assert.notEqual(newKey,oldKey);assert.notEqual(p.draws.at(-1).src,oldURL);
  assert.equal(new URL(newURL).searchParams.get('v'),new URL(oldURL).searchParams.get('v'));
  assert.equal(p.element('base-canvas').dataset.view,'composite');assert.equal(p.element('current-canvas').dataset.view,'composite');
};
cases.labCancellation=async()=>{
  let hold=true;const p=await previewPage('animation_lab',{query:'?species=212',hold:rec=>hold&&rec.url==='/api/animation/preview'});
  assert.equal(p.held.length,1);const request=p.held[0];await p.dispatch('cancel');assert.equal(request.record.args.signal.aborted,true);
  request.release();await p.finish();assert.equal(p.draws.length,0,'Cancelled preview response must not draw');assert.equal(p.element('empty').hidden,false);
  hold=false;await p.change('species','6');await p.dispatch('preview-form','submit');assert.equal(p.element('empty').hidden,true);assert.match(p.element('live-title').textContent,/喷火龙/);
};
cases.editorPresets=async()=>{
  const p=await previewPage('animation_editor',{query:'?mode=arena&species=212&kind=cast',reducedMotion:true});
  await p.dispatch('settings-form','submit');assert.equal(p.element('base-canvas').width,960);assert.equal(p.element('current-canvas').width,960);assert.equal(p.element('export').disabled,false);
  const drawn=p.draws.length;await p.change('effect-scale','1.3','input');assert.equal(p.element('export').disabled,true,'Unapplied settings cannot be exported');assert.equal(p.draws.length,drawn,'Editing settings preserves last applied preview');
  await p.dispatch('settings-form','submit');assert.equal(p.element('export').disabled,false);
  const preset={schema_version:1,species:19,settings:{palette:'classic',effect_scale:1,particle_density:1,motion_scale:1}};
  p.element('file').files=[{size:200,text:async()=>JSON.stringify(preset)}];await p.dispatch('file','change');
  assert.equal(p.element('mode').value,'classic','Presets without mode must load classic catalog');assert.equal(p.element('species').value,'19');assert.equal(p.element('base-canvas').width,240);assert.equal(p.element('export').disabled,true,'Import applies form values but does not imply a rendered result');
  await p.dispatch('settings-form','submit');assert.equal(p.element('current-canvas').width,240);assert.equal(p.element('current-canvas').height,320);
  assert.equal(p.element('current-canvas').getContext('2d').imageSmoothingEnabled,false);
};
cases.editorImportRace=async()=>{
  let hold=false;const p=await previewPage('animation_editor',{query:'?mode=arena&species=212',hold:rec=>hold&&rec.url==='/api/animation/characters?mode=classic'});
  hold=true;const preset={schema_version:1,species:19,settings:{palette:'classic',effect_scale:1.2,particle_density:1,motion_scale:1}};
  p.element('file').files=[{size:200,text:async()=>JSON.stringify(preset)}];const importing=await p.start('file','change');
  assert.equal(p.held.length,1);await p.change('effect-scale','0.8','input');p.held[0].release();await importing.done;await p.finish();
  assert.equal(p.element('effect-scale').value,'0.8','Later edits during preset catalog loading must survive import completion');assert.match(p.element('notice').textContent,/未应用/);
};
cases.editorRecovery=async()=>{
  const p=await previewPage('animation_editor',{query:'?mode=arena&species=212',manualImages:true,reducedMotion:true});
  const first=await p.start('settings-form','submit');p.loadPending();await first.done;await p.finish();
  const oldURL=p.draws.at(-1).src,oldLabel=p.element('result-label').textContent,oldDraws=p.draws.length;
  await p.change('palette','vivid','input');const second=await p.start('settings-form','submit');
  p.forFrame(0)[0].fail();await second.done;await p.finish();
  assert.equal(p.draws.length,oldDraws,'A failed candidate first pair may not clear or replace the successful canvases');
  assert.equal(p.element('result-label').textContent,oldLabel);assert.equal(p.element('retry-frame').hidden,false);
  await p.dispatch('play');p.tick(0);p.tick(50);assert.equal(p.draws.at(-1).index,1);
  assert.equal(new URL(p.draws.at(-1).src).pathname.split('/')[2],new URL(oldURL).pathname.split('/')[2],'The previous player remains playable after a failed generation');
  await p.dispatch('play');const retry=await p.start('retry-frame');p.loadPending();await retry.done;await p.finish();
  const currentURL=p.draws.at(-1).src;assert.notEqual(currentURL,oldURL,'Explicit retry installs the new result after both first frames load');assert.equal(p.element('palette').value,'vivid');
  const cancelled=await p.start('settings-form','submit');const late=p.forFrame(0)[0],lateLoad=late.image.onload;
  const beforeCancel=p.draws.length;await p.dispatch('cancel-render');late.image.naturalWidth=960;late.image.naturalHeight=640;lateLoad();await cancelled.done;await p.finish();
  assert.equal(p.draws.length,beforeCancel,'Late candidate image callbacks after cancel cannot paint over the applied preview');
  await p.change('seek','3','input');assert.equal(p.draws.at(-1).index,3);assert.equal(new URL(p.draws.at(-1).src).pathname.split('/')[2],new URL(currentURL).pathname.split('/')[2]);
  const switching=await p.start('settings-form','submit');const old=p.forFrame(0)[0],oldLoad=old.image.onload;
  const beforeSwitch=p.draws.length;await p.change('species','6','input');old.image.naturalWidth=960;old.image.naturalHeight=640;oldLoad();await switching.done;await p.finish();
  assert.equal(p.draws.length,beforeSwitch,'Changing species cancels the pending candidate before a stale callback can paint');
};
cases.editorCatalogFailure=async()=>{
  let failed=true;const p=await previewPage('animation_editor',{query:'?mode=arena&species=212',reducedMotion:true,fail:rec=>failed&&rec.url==='/api/animation/characters?mode=classic'?503:null});
  const preset={schema_version:1,species:19,settings:{palette:'classic',effect_scale:1,particle_density:1,motion_scale:1}};
  p.element('file').files=[{size:200,text:async()=>JSON.stringify(preset)}];await p.dispatch('file','change');
  assert.equal(p.element('mode').value,'classic');assert.match(p.element('error').textContent,/读取失败/);
  await p.dispatch('settings-form','submit');
  assert.equal(p.fetches.filter(rec=>rec.url==='/api/animation/preview').length,0,'A failed cross-mode catalog cannot POST an arena species to classic preview');
  assert.equal(p.fetches.filter(rec=>rec.url==='/api/animation/characters?mode=classic').length,2,'Generation after import failure retries the current-mode catalog');
  failed=false;await p.dispatch('settings-form','submit');
  const preview=p.fetches.find(rec=>rec.url==='/api/animation/preview');assert.ok(preview,'A recovered catalog permits normal generation');assert.equal(preview.body.mode,'classic');assert.notEqual(preview.body.species,212);assert.equal(p.element('base-canvas').width,240);assert.equal(p.element('base-canvas').height,320);
};
cases.editorSpeed=async()=>{
  const p=await previewPage('animation_editor',{query:'?mode=arena&species=212',reducedMotion:true});
  await p.dispatch('settings-form','submit');await p.change('speed','2');
  await p.change('palette','vivid','input');await p.dispatch('settings-form','submit');await p.dispatch('play');
  p.tick(0);p.tick(50);assert.equal(p.element('speed').value,'2');assert.equal(p.draws.at(-1).index,2,'A successful candidate inherits the selected 2x speed, rather than silently resetting to 1x');
};
cases.labLegacyActorArtURL=async()=>{
  const p=await previewPage('animation_lab',{query:'?mode=arena&species=9&kind=cast&actor_art=keyframes'});
  assert.equal(p.element('species').value,'9');
  assert.equal(p.document.getElementById('actor-art'),null,'The removed actor-art control must not remain in real lab HTML');
  const previews=p.fetches.filter(rec=>rec.url==='/api/animation/preview');
  assert.equal(previews.length,1);
  assert.equal(previews[0].body.species,9);
  assert.equal(previews[0].body.kind,'cast');
  assert.ok(!Object.hasOwn(previews[0].body,'actor_art'),'Legacy lab URLs must request the original baseline material');
  assert.equal(p.element('empty').hidden,true);
  assert.ok(p.draws.length>0,'The baseline result remains playable');
  const url=new URL(p.historyCalls.at(-1),'http://fixture.invalid');
  assert.equal(url.searchParams.has('actor_art'),false);
  assert.ok(!p.element('editor-link').href.includes('actor_art=keyframes'));
};
cases.editorLegacyActorArtURL=async()=>{
  const p=await previewPage('animation_editor',{query:'?mode=arena&species=9&kind=cast&actor_art=keyframes',reducedMotion:true});
  assert.equal(p.element('species').value,'9');
  assert.equal(p.document.getElementById('actor-art'),null,'The removed actor-art control must not remain in real editor HTML');
  assert.equal(p.fetches.filter(rec=>rec.url==='/api/animation/preview').length,0,'Editor catalog loading still does not silently render');
  await p.dispatch('settings-form','submit');
  const previews=p.fetches.filter(rec=>rec.url==='/api/animation/preview');
  assert.equal(previews.length,1);
  assert.equal(previews[0].body.species,9);
  assert.equal(previews[0].body.kind,'cast');
  assert.ok(!Object.hasOwn(previews[0].body,'actor_art'),'Legacy editor URLs must request the original baseline material');
  assert.ok(p.draws.length>0,'The baseline result remains playable');
  assert.ok(!p.element('lab-link').href.includes('actor_art=keyframes'));
  await p.change('view','body');
  assert.equal(p.element('view').value,'body');
  const url=new URL(p.historyCalls.at(-1),'http://fixture.invalid');
  assert.equal(url.searchParams.has('actor_art'),false);
};

(async()=>{assert.ok(cases[scenario],'Unknown scenario '+scenario);await cases[scenario]();console.log('OK animation '+scenario);})().catch(error=>{console.error(error);process.exitCode=1;});
