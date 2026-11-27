/* Phone UX layer (docs/74, mobile audit 2026-11-27) in Chromium with touch:
 * one-row HUD + menu sheet, shop sheet that leaves the bench visible with an inline
 * recruit button, touch drag, the long-press click-swallow regression, toast timing,
 * and the desktop layout untouched.
 * usage: node play_phone_flow.js <base-url>   (needs the `playwright` package) */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

const base = process.argv[2];

async function launch() {
  try { return await chromium.launch(); } catch (error) {
    const root = path.join(process.env.HOME || '', '.cache/ms-playwright');
    const dir = fs.existsSync(root) && fs.readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort().pop();
    const bin = dir && ['chrome-linux64/chrome', 'chrome-linux/chrome'].map((p) => path.join(root, dir, p)).find((p) => fs.existsSync(p));
    if (!bin) throw error;
    return chromium.launch({executablePath: bin});
  }
}

async function newGame() {
  const api = async (q) => (await (await fetch(`${base}/api/demo/action?${new URLSearchParams(q)}`)).json());
  let r = await api({cmd: 'new', mode: 'arena', seed: '515'});
  const sid = r.sid;
  let s = r.state;
  for (const p of s.augments?.pending || []) {
    r = await api({cmd: 'claim_augment', id: p.id, choice: p.options[0].id, sid, expected_sequence: String(s.save?.sequence ?? '')});
    if (r.ok) s = r.state;
  }
  return sid;
}

async function openPage(browser, sid, viewport, touch) {
  const context = await browser.newContext({viewport, hasTouch: touch, isMobile: touch, deviceScaleFactor: touch ? 2 : 1});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  await page.addInitScript((slot) => {
    localStorage.setItem('poketactics.play.arena.slot', slot);
    localStorage.setItem('poketactics.play.panel', 'closed');
    localStorage.setItem('poketactics.play.guide', 'done');
  }, sid);
  await page.goto(`${base}/play`);
  await page.waitForSelector('#ally-board [data-loc="g0,0"]');
  await page.evaluate(() => { if (window.PlayGuide?.step() >= 0) window.PlayGuide.finish(); });
  await page.waitForTimeout(400);
  return {page, context, errors};
}

const center = (page, selector) => page.evaluate((sel) => {
  const el = document.querySelector(sel);
  const r = el.getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2};
}, selector);

async function touchDrag(page, from, to) {
  const cdp = await page.context().newCDPSession(page);
  const point = (p) => ({x: p.x, y: p.y, radiusX: 4, radiusY: 4, force: 1, id: 1});
  await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [point(from)]});
  const steps = [{x: from.x, y: from.y - 14}, {x: from.x + 1, y: from.y - 34}];
  for (let k = 1; k <= 6; k++) steps.push({x: from.x + (to.x - from.x) * k / 6, y: from.y - 34 + (to.y - from.y + 34) * k / 6});
  for (const p of steps) {
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [point(p)]});
    await page.waitForTimeout(16);
  }
  const ghost = await page.evaluate(() => Boolean(document.querySelector('.touch-drag-ghost')));
  await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
  return ghost;
}

async function phone(browser, sid, viewport) {
  const tag = `${viewport.width}x${viewport.height}`;
  const {page, context, errors} = await openPage(browser, sid, viewport, true);
  const layout = await page.evaluate(() => ({
    nav: getComputedStyle(document.querySelector('.portal-nav')).display,
    tools: getComputedStyle(document.querySelector('.hud-tools')).display,
    hud: document.querySelector('.stage-hud').getBoundingClientRect().height,
    menu: getComputedStyle(document.getElementById('menu-button')).display,
  }));
  assert.equal(layout.nav, 'none', `${tag}: site nav hidden on phones`);
  assert.equal(layout.tools, 'none', `${tag}: HUD tool row moved into the menu`);
  assert.ok(layout.hud <= 58, `${tag}: one-row HUD (${layout.hud}px)`);
  assert.notEqual(layout.menu, 'none', `${tag}: menu button shown`);

  // Menu sheet: rows mirror and drive the original buttons; back closes it.
  await page.tap('#menu-button');
  await page.waitForFunction(() => window.PlayPhone.menuOpen());
  const music = () => page.evaluate(() => [document.getElementById('music-button').getAttribute('aria-pressed'),
    document.querySelector('[data-menu-proxy="music-button"]').getAttribute('aria-pressed')]);
  const [m0, row0] = await music();
  assert.equal(m0, row0, `${tag}: music row mirrors the HUD button`);
  await page.tap('[data-menu-proxy="music-button"]');
  await page.waitForTimeout(80);
  const [m1, row1] = await music();
  assert.notEqual(m1, m0, `${tag}: the row toggles the real music button`);
  assert.equal(m1, row1);
  await page.tap('[data-menu-proxy="music-button"]');
  await page.waitForTimeout(80);
  assert.equal(await page.evaluate(() => window.PokeTacticsShell.onBack()), true, `${tag}: back closes the menu`);
  assert.equal(await page.evaluate(() => window.PlayPhone.menuOpen()), false);

  // Shop: the sheet stops under the bench; the selected card carries 「招募」.
  await page.tap('#stage-dock [data-open-panel="shop"]');
  await page.waitForFunction(() => document.body.classList.contains('drawer-open'));
  await page.waitForTimeout(260);
  const benchBefore = await page.evaluate(() => document.querySelectorAll('#bench [data-uid]').length);
  const card = await page.evaluate(() => [...document.querySelectorAll('#shop [data-shop]')].find((c) => !c.classList.contains('unaffordable'))?.dataset.shop);
  assert.ok(card != null, `${tag}: an affordable shop card`);
  await page.tap(`#shop [data-shop="${card}"]`);
  await page.waitForSelector('.shop-quick-buy');
  const geo = await page.evaluate(() => ({
    bench: document.querySelector('.bench-area').getBoundingClientRect().bottom,
    fight: document.getElementById('fight-button').getBoundingClientRect().bottom,
    sheet: document.getElementById('stage-drawer').getBoundingClientRect().top,
    button: document.querySelector('.shop-quick-buy').getBoundingClientRect().top,
    text: document.querySelector('.shop-quick-buy').textContent,
  }));
  assert.ok(geo.bench <= geo.sheet + 1, `${tag}: shop sheet (top ${geo.sheet}) leaves the bench (bottom ${geo.bench}) visible`);
  assert.ok(geo.fight <= geo.sheet + 1, `${tag}: and the start-battle button`);
  assert.ok(geo.button >= geo.sheet, `${tag}: recruit button is inside the sheet`);
  assert.match(geo.text, /^招募 · \d+ 金$/);
  await page.tap('.shop-quick-buy');
  await page.waitForFunction((n) => document.querySelectorAll('#bench [data-uid]').length > n, benchBefore);

  // Toast timing on phones: confirmations of a move are dropped, errors stay longer.
  assert.equal(await page.evaluate(() => window.PlayPhone.toastHold('绿毛虫 移动', false)), 0);
  assert.equal(await page.evaluate(() => window.PlayPhone.toastHold('金币不足', true)), 3000);
  const toastTop = await page.evaluate(() => parseFloat(getComputedStyle(document.getElementById('toast')).top));
  const hudBottom = await page.evaluate(() => document.querySelector('.stage-hud').getBoundingClientRect().bottom);
  assert.ok(toastTop >= hudBottom, `${tag}: toasts appear under the HUD (${toastTop} >= ${hudBottom})`);

  // Touch drag: bench → an empty board cell.
  await page.tap('[data-close-panel]');
  await page.waitForFunction(() => !document.body.classList.contains('drawer-open'));
  await page.waitForTimeout(250);
  const unit = await page.evaluate(() => [...document.querySelectorAll('#bench [data-uid]')].pop().dataset.loc);
  const target = await page.evaluate(() => [...document.querySelectorAll('#ally-board [data-loc]:not([data-uid])')][7].dataset.loc);
  const ghost = await touchDrag(page, await center(page, `#bench [data-loc="${unit}"]`), await center(page, `[data-loc="${target}"]`));
  assert.ok(ghost, `${tag}: a ghost follows the finger`);
  await page.waitForFunction((loc) => Boolean(document.querySelector(`[data-loc="${loc}"]`).dataset.uid), target, {timeout: 8000});
  assert.equal(await page.evaluate(() => document.querySelector('.touch-drag-ghost')), null, 'ghost removed');

  // Selecting an own unit highlights where it can go.
  await page.waitForTimeout(400);
  await page.tap(`[data-loc="${target}"]`);
  await page.waitForTimeout(350);
  assert.ok(await page.evaluate(() => document.body.classList.contains('unit-picked')), `${tag}: empty cells highlighted`);
  const bar = await page.evaluate(() => {
    const actions = document.querySelector('.context-actions');
    return [...actions.querySelectorAll('button')].filter((b) => b.getClientRects().length).every((b) => {
      const r = b.getBoundingClientRect();
      return r.right <= innerWidth + 1 && r.height >= 40;
    });
  });
  assert.ok(bar, `${tag}: every action bar button is on screen and ≥ 40px tall`);
  await page.evaluate(() => window.PlayOverlay.closeTop('back'));

  // Long press that the browser cancels (text selection) must not eat the next tap (audit H4).
  const swallowed = await page.evaluate(async (loc) => {
    const tile = document.querySelector(`[data-loc="${loc}"]`);
    const r = tile.getBoundingClientRect();
    const at = {clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, pointerType: 'touch', pointerId: 7, bubbles: true, isPrimary: true};
    tile.dispatchEvent(new PointerEvent('pointerdown', at));
    await new Promise((done) => setTimeout(done, (window.PlayContext.LONG_PRESS_MS || 450) + 120));
    const opened = window.PlayContext.isOpen();
    document.dispatchEvent(new PointerEvent('pointercancel', at));
    window.PlayOverlay.closeTop('back');
    let clicked = false;
    const probe = document.querySelector('#stage-dock [data-open-panel="bonds"]');
    probe.addEventListener('click', () => { clicked = true; }, {once: true});
    probe.click();
    await new Promise((done) => setTimeout(done, 50));
    return {opened, clicked, panel: window.PlayLayout.current()};
  }, target);
  assert.ok(swallowed.opened, `${tag}: long press opened the menu`);
  assert.ok(swallowed.clicked && swallowed.panel === 'bonds', `${tag}: the next tap after a cancelled long press works (${JSON.stringify(swallowed)})`);
  assert.equal(await page.evaluate(() => getComputedStyle(document.body).userSelect), 'none', `${tag}: no text selection on long press`);

  assert.deepEqual(errors, [], `${tag}: no page errors`);
  await context.close();
}

async function desktop(browser, sid) {
  const {page, context, errors} = await openPage(browser, sid, {width: 1280, height: 760}, false);
  const d = await page.evaluate(() => ({
    nav: getComputedStyle(document.querySelector('.portal-nav')).display,
    tools: getComputedStyle(document.querySelector('.hud-tools')).display,
    menu: getComputedStyle(document.getElementById('menu-button')).display,
    close: document.getElementById('battle-close').textContent.trim(),
    hold: window.PlayPhone.toastHold('绿毛虫 移动', false),
  }));
  assert.notEqual(d.nav, 'none', 'desktop keeps the site nav');
  assert.notEqual(d.tools, 'none', 'desktop keeps the HUD tools');
  assert.equal(d.menu, 'none', 'desktop has no menu button');
  assert.equal(d.close, '×', 'desktop battle dialog keeps its ×');
  assert.equal(d.hold, 3600, 'desktop toasts unchanged');
  assert.deepEqual(errors, [], 'desktop: no page errors');
  await context.close();
}

(async () => {
  const browser = await launch();
  try {
    await desktop(browser, await newGame());
    for (const viewport of [{width: 390, height: 844}, {width: 360, height: 740}]) await phone(browser, await newGame(), viewport);
  } finally {
    await browser.close();
  }
  console.log('phone flow ok');
})().catch((error) => { console.error(error); process.exitCode = 1; });
