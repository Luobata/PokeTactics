#!/usr/bin/env node
/* Execute the exact generated viewer JS with native Skia canvas + PNG decoding.
 * No browser/network permissions needed. This checks pixels and state/races;
 * it is explicitly NOT browser compositor/timer-throttling certification.
 * NODE_PATH must expose @napi-rs/canvas and pngjs. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {createCanvas, loadImage} = require('@napi-rs/canvas');
const {PNG} = require('pngjs');
const ROOT = path.resolve(__dirname, '../..');
const OUT = path.join(ROOT, 'reports/evidence/blank-frames-2026-10-04/viewer-equivalent.json');
const hash = b => crypto.createHash('sha256').update(b).digest('hex');
const yieldIO = () => new Promise(resolve => setImmediate(resolve));
async function until(fn) {
  for (let n = 0; n < 20000; n++) { if (fn()) return; await yieldIO(); }
  throw new Error('test did not settle');
}
function setup(page) {
  const dir = path.join(ROOT, 'reports/evidence', page);
  const source = fs.readFileSync(path.join(dir, 'index.html'), 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
  assert.equal(source.trim(), fs.readFileSync(path.join(__dirname, 'range_viewer.js'), 'utf8').trim());
  const stage = createCanvas(240, 320);
  stage.dataset = {};
  const el = Object.fromEntries(['clip','play','prev','next','seek','retry','label','info'].map(id => [id, {
    value: '0', textContent: '', hidden: false, appendChild() {}
  }]));
  el.frame = stage;
  const io = {mode: 'normal', requests: 0, inFlight: 0, peak: 0, blocked: [], failedAttempts: 0};
  const deadlines = new Map(), requestsInProgress = new Set();
  let nextTimer = 1, tick;
  const sandbox = {
    console, AbortController, DOMException,
    document: {getElementById: id => el[id], createElement: tag => tag === 'canvas' ? createCanvas(1,1) : {}},
    setInterval: fn => { tick = fn; return 1; },
    setTimeout: (fn, ms) => { const id = nextTimer++; deadlines.set(id, {fn,ms}); return id; },
    clearTimeout: id => deadlines.delete(id),
    fetch: async (url, opts = {}) => {
      io.requests++;
      const pathname = url.split('?')[0];
      const frame = pathname.endsWith('.png');
      if (!frame) {
        assert.equal(opts.cache, 'no-store');
        return {ok: true, json: async () => JSON.parse(fs.readFileSync(path.join(dir,pathname)))};
      }
      assert.match(url, /\?v=[a-f0-9]{64}$/, 'frame cache keyed by content hash');
      io.inFlight++; requestsInProgress.add(opts.signal);
      io.peak = Math.max(io.peak, [...requestsInProgress].filter(signal => !signal.aborted).length);
      try {
        if (opts.signal?.aborted) throw new DOMException('abort', 'AbortError');
        if (io.mode === 'hold' || io.mode === 'timeout') {
          await new Promise((resolve, reject) => {
            const abort = () => reject(new DOMException('abort', 'AbortError'));
            opts.signal.addEventListener('abort', abort, {once:true});
            io.blocked.push(() => { opts.signal.removeEventListener('abort', abort); resolve(); });
          });
        }
        if (io.mode === '404') { io.failedAttempts++; return {ok:false,status:404}; }
        const blob = io.mode === 'corrupt' ? Buffer.from('broken PNG') :
          io.mode === 'size' ? createCanvas(1,1).toBuffer('image/png') : await fs.promises.readFile(path.join(dir,pathname));
        return {ok:true,blob:async()=>blob};
      } finally { io.inFlight--; requestsInProgress.delete(opts.signal); }
    },
    createImageBitmap: async blob => { const im = await loadImage(blob); im.close = () => {}; return im; }
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, {filename:page+'/index.html'});
  return {dir, el, stage, io, deadlines, eval:s => vm.runInContext(s,sandbox), tick:()=>tick()};
}
function pixels(h) { return h.stage.getContext('2d').getImageData(0,0,240,320).data; }
function expected(h, c, n) {
  const png = PNG.sync.read(fs.readFileSync(path.join(h.dir,c.path,`frame-${String(n).padStart(3,'0')}.png`)));
  return hash(png.data);
}
function verify(h, digest) {
  const p = pixels(h);
  assert.equal(hash(p), digest, 'display must equal the requested PNG, including alpha');
  for (let i = 3; i < p.length; i += 4) assert.equal(p[i],255,'transparent tick');
}
async function select(h, n) {
  h.el.clip.value = String(n);
  await h.el.clip.onchange();
  assert.equal(h.stage.dataset.status,'ready');
}
async function faults(h, clips) {
  const results = [];
  // Delay a long clip, drag to its last frame, switch away before it completes.
  const skillIndices = clips.map((c,i) => ['skill','cast'].includes(c.action) ? i : -1).filter(i => i >= 0);
  const longest = skillIndices.reduce((best,i) => clips[i].frames > clips[best].frames ? i : best, skillIndices[0]);
  await select(h,0);
  h.eval('cache.clear(); cacheBytes=0; running=false');
  const held = hash(pixels(h));
  h.io.mode = 'hold';
  h.el.clip.value = String(longest);
  const delayed = h.el.clip.onchange();
  await until(() => h.io.blocked.length >= 1);
  h.el.seek.oninput({target:{value:String(clips[longest].frames-1)}});
  for (let n=0;n<30;n++) {h.tick();verify(h,held);}
  h.io.mode = 'normal';
  await select(h,1);
  const latest = hash(pixels(h));
  for (const resolve of h.io.blocked.splice(0)) resolve();
  await delayed;
  verify(h,latest);
  results.push({case:'slow-load-seek-switch-stale-completion',hold_ticks:30,passed:true});
  // Seek while loading must be remembered until atomic ready.
  h.eval('cache.clear(); cacheBytes=0');
  h.io.mode = 'hold';
  h.el.clip.value = String(longest);
  const seekLoad = h.el.clip.onchange();
  await until(() => h.io.blocked.length >= 1);
  h.el.seek.oninput({target:{value:String(clips[longest].frames-1)}});
  h.io.mode = 'normal';
  for (const resolve of h.io.blocked.splice(0)) resolve();
  await seekLoad;
  verify(h,expected(h,clips[longest],clips[longest].frames-1));
  results.push({case:'longest-clip-pending-seek',frames:clips[longest].frames,passed:true});
  for (const mode of ['404','corrupt','size','timeout']) {
    h.eval('cache.clear(); cacheBytes=0; running=true');
    const held = hash(pixels(h));
    h.io.mode = mode;
    h.el.clip.value = '0';
    const load = h.el.clip.onchange();
    if (mode === 'timeout') {
      // Fire the actual 12s production deadline twice, avoiding a 24s sleep.
      for (let attempt=0;attempt<2;attempt++) {
        await until(() => h.deadlines.size > 0);
        const old = [...h.deadlines.values()];
        h.deadlines.clear();
        old.forEach(timer => { assert.equal(timer.ms,12000); timer.fn(); });
        for(let n=0;n<10;n++) await yieldIO();
      }
    }
    await load;
    assert.equal(h.stage.dataset.status,'error',mode);
    assert.equal(h.el.retry.hidden,false);
    assert.equal(h.eval('cache.has(clips[0].path)'),false);
    for(let n=0;n<30;n++){h.tick();verify(h,held);}
    h.io.mode = 'normal';
    await h.el.retry.onclick();
    assert.equal(h.stage.dataset.status,'ready');
    verify(h,expected(h,clips[0],0));
    results.push({case:mode+'-hold-retry',hold_ticks:30,passed:true});
  }
  return results;
}
(async () => {
  const result = {kind:'native-canvas-exact-viewer-script; virtual timers; local PNG IO',browser_executed:false,
    viewer_sha256:hash(fs.readFileSync(path.join(__dirname,'range_viewer.js'))),pages:[],playback_ticks:0,seek_checks:0,blank_ticks:0,pixel_mismatches:0,passed:false};
  for (const page of ['per-unit-2026-10-04','range-refined-2026-10-04']) {
    const h = setup(page);
    await until(() => h.stage.dataset.status === 'ready');
    h.eval('running=false');
    const clips = JSON.parse(fs.readFileSync(path.join(h.dir,'manifest.json'))).clips;
    const rows = [];
    for (let n=0;n<clips.length;n++) {
      await select(h,n);
      const c = clips[n], digests = Array.from({length:c.frames},(_,i)=>expected(h,c,i));
      verify(h,digests[0]);
      const requests = h.io.requests;
      h.eval('running=true');
      for(let j=1;j<=c.frames*2;j++) {h.tick();verify(h,digests[j%c.frames]);result.playback_ticks++;}
      for(let j=c.frames-1;j>=0;j--) {
        h.el.seek.oninput({target:{value:String(j)}});verify(h,digests[j]);result.seek_checks++;
      }
      h.el.prev.onclick();verify(h,digests[c.frames-1]);
      h.el.next.onclick();verify(h,digests[0]);
      assert.equal(h.io.requests,requests,'playback and seek must perform no IO');
      assert.ok(h.eval('cacheBytes <= CACHE_BYTES'));
      rows.push({path:c.path,frames:c.frames,ticks:c.frames*2,seek_checks:c.frames,blank_ticks:0,pixel_mismatches:0});
      if(n%50===0) console.log(page,n+'/'+clips.length);
    }
    const tests = await faults(h,clips);
    assert.ok(h.io.peak<=4,'bounded network concurrency');
    result.pages.push({page,clips:rows,faults:tests,peak_inflight:h.io.peak,cache_bytes:h.eval('cacheBytes')});
  }
  result.passed = true;
  fs.writeFileSync(OUT,JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({passed:true,ticks:result.playback_ticks,seek:result.seek_checks,blank_ticks:0,pixel_mismatches:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
