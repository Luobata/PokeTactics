// Physical input transport: release commits, recovery never replays an action.
function clearLocal(){pressed.clear();heldAt.clear();suppressed.clear();document.querySelectorAll('.key').forEach(b=>b.classList.remove('held'))}
async function request(phase,key){const params=new URLSearchParams({phase,device_id:device});if(key)params.set('key',key);if(!device){if(query.get('sid'))params.set('sid',query.get('sid'));else try{params.set('remembered_sid',localStorage.getItem('poketactics.slot')||'')}catch(e){}}const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),6000);try{const response=await fetch('/api/device/input?'+params,{cache:'no-store',signal:controller.signal});return await response.json()}finally{clearTimeout(timer)}}
function publish(result){if(!result.ok){status.textContent=result.error||'连接未完成';return}if(view&&result.screen.message!==view.screen.message){notice={text:result.screen.message,until:Date.now()+2800};}device=result.device_id;view=result;status.textContent=view.sleeping?'屏幕已关闭，进度已保留':view.screen.message||'操作就绪';const link=document.getElementById('web-game-link');if(link&&result.sid)link.href='/demo?sid='+encodeURIComponent(result.sid);if(result.sid&&result.screen.page!=='home'){try{localStorage.setItem('poketactics.slot',result.sid)}catch(e){}history.replaceState(null,'','/device?sid='+encodeURIComponent(result.sid))}draw()}
async function recover(){clearLocal();if(device){const ended=await request('cancel');if(!ended.ok){device=''}}const fresh=await request('state');if(!fresh.ok)throw new Error(fresh.error);publish(fresh);disconnected=false}
function queue(phase,key){if(phase==='tick'&&pending)return;pending++;const epoch=transportEpoch,blocking=phase==='up'||phase==='cancel';if(blocking)actionPending++;if(blocking)document.querySelector('.console').classList.add('busy');chain=chain.then(async()=>{if(epoch!==transportEpoch)return;if(disconnected){await recover();return}publish(await request(phase,key))}).catch(()=>{disconnected=true;transportEpoch++;clearLocal();status.textContent='连接中断；恢复时会先清理按键并读取已保存进度，不重试操作。'}).finally(()=>{pending--;if(blocking)actionPending--;if(!pending)document.querySelector('.console').classList.remove('busy')});}
function down(key){if(pressed.has(key)||suppressed.has(key))return;if(disconnected){suppressed.add(key);queue('state');return}if(actionPending||!device){suppressed.add(key);return}pressed.add(key);heldAt.set(key,Date.now());document.querySelector(`[data-key=${key}]`).classList.add('held');queue('down',key)}
function up(key){heldAt.delete(key);document.querySelector(`[data-key=${key}]`).classList.remove('held');if(suppressed.delete(key))return;if(!pressed.delete(key))return;queue('up',key)}
function cancel(){clearLocal();queue('cancel')}
document.querySelectorAll('.key').forEach(button=>{const key=button.dataset.key;button.addEventListener('pointerdown',event=>{event.preventDefault();button.setPointerCapture(event.pointerId);down(key)});button.addEventListener('pointerup',event=>{event.preventDefault();up(key)});button.addEventListener('pointercancel',cancel);button.addEventListener('lostpointercapture',()=>{if(pressed.has(key))cancel()});button.addEventListener('click',event=>event.preventDefault())});
const keys={ArrowUp:'A',ArrowDown:'B',Enter:'C',a:'A',b:'B',c:'C',A:'A',B:'B',C:'C'};
window.addEventListener('keydown',event=>{if(event.target?.closest?.('select,input,textarea,a'))return;const key=keys[event.key];if(!key)return;event.preventDefault();if(!event.repeat)down(key)});
window.addEventListener('keyup',event=>{const key=keys[event.key];if(event.target?.closest?.('select,input,textarea,a')&&!pressed.has(key)&&!suppressed.has(key))return;if(!key)return;event.preventDefault();up(key)});
window.addEventListener('blur',cancel);document.addEventListener('visibilitychange',()=>{if(document.hidden)cancel()});
setInterval(()=>{if(device&&!document.hidden)queue('tick')},100);queue('state');

const scaleControl=document.getElementById('display-scale');
if(scaleControl){
  const fitScale=()=>{
    scaleControl.querySelector('option[value="2"]').disabled=window.innerWidth<560;
    if(window.innerWidth<560&&scaleControl.value==='2')scaleControl.value='auto';
    document.querySelector('.console').dataset.scale=scaleControl.value;
  };
  scaleControl.addEventListener('change',fitScale);window.addEventListener('resize',fitScale);fitScale();
}
