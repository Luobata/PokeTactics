/* Native canvas acceptance capture. NODE_PATH must provide installed Playwright. */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { chromium } = require('playwright');
let captureBrowser;
(async()=>{
 const root=process.cwd(), source=path.resolve(process.argv[2]||'.build/evolution-device-2026-10-05/snapshots');
 const out=path.resolve(process.argv[3]||'reports/evidence/evolution-device-2026-10-05');
 fs.mkdirSync(out,{recursive:true});
 const sources=['tools/acceptance/device_renderer.js','tools/acceptance/device_controls.py','tests/test_evolution_device.py','tools/acceptance/demo.py','tools/acceptance/evolution_device_capture.js'];
 const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
 const renderer=fs.readFileSync(path.join(root,sources[0]),'utf8');
 const browser=await chromium.launch({headless:true}); captureBrowser=browser;
 const page=await browser.newPage({viewport:{width:620,height:760},deviceScaleFactor:1});
 const captureHTML=('<html><head><base href="http://127.0.0.1:8807/"><meta charset="utf-8"></head><body><canvas id="screen" width="240" height="320"></canvas><div id="screen-text"></div><div id="context-hint"></div><div id="status"></div></body></html>');
 await page.route('http://127.0.0.1:8807/device-capture',route=>route.fulfill({contentType:'text/html',body:captureHTML}));
 await page.goto('http://127.0.0.1:8807/device-capture');
 await page.addScriptTag({content:renderer});
 const outputs=[], errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 for(const name of fs.readdirSync(source).filter(s=>s.endsWith('.json')).sort()){
   const data=JSON.parse(fs.readFileSync(path.join(source,name),'utf8'));
   const viewData=data.screen?.screen?data.screen:(data.screen?data:(data.result||data.view||data.snapshot));
   if(!viewData?.screen)throw new Error('Unknown snapshot format '+name+' '+Object.keys(data));
   await page.evaluate(d=>{view=d; notice={text:'',until:0}; draw();},viewData);
   await page.waitForFunction(()=>[...sprites.values()].every(i=>i.complete));
   await page.evaluate(()=>draw());
   const url=await page.locator('#screen').evaluate(c=>c.toDataURL('image/png'));
   const pixels=Buffer.from(url.split(',')[1],'base64'), png=name.replace('.json','.png');
   fs.writeFileSync(path.join(out,png),pixels);
   fs.copyFileSync(path.join(source,name),path.join(out,name));
   outputs.push({snapshot:name,snapshot_sha256:sha(fs.readFileSync(path.join(source,name))),png,png_sha256:sha(pixels),width:240,height:320,page:viewData.screen.page});
 }
 await browser.close();
 if(errors.length)throw new Error(errors.join('\n'));
 fs.writeFileSync(path.join(out,'visual.json'),JSON.stringify({kind:'native-canvas-from-three-key-snapshots',sources_sha256:Object.fromEntries(sources.map(s=>[s,sha(fs.readFileSync(path.join(root,s)))])),outputs,errors,limits:['Production renderer of captured three-key state; screenshots replay snapshots and do not perform new game actions.','PC presentation only; no physical-device or human timed-play claim.','Sprites loaded through read-only local server; no real save changes.']},null,2)+'\n');
 console.log(JSON.stringify({output:out,count:outputs.length,errors}));
})().catch(async e=>{console.error(e);if(captureBrowser)await captureBrowser.close();process.exitCode=1});
