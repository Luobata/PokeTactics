/* Scene layout geometry (docs/68-scene-layout.md), measured in a real browser.
 * Rule: a panel opens right next to the dock button that opened it, and never
 * hides the board (or, in portrait, the board's own rows) it edits.
 * usage: node play_scene_geometry.js <base-url>   (needs the `playwright` package) */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

const base = process.argv[2];
const GAP = 16;  // max distance between a dock button and the edge of its panel

async function launch() {
  try { return await chromium.launch(); } catch (error) {
    // Fall back to the newest locally installed Chromium build.
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

const overlaps = (a, b) => a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
const spans = (a, b) => a.top < b.bottom && b.top < a.bottom;  // vertical spans intersect

async function rects(page, panel) {
  return page.evaluate((panel) => {
    const r = (el) => {
      if (!el) return null;
      const b = el.getBoundingClientRect();
      return {left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height};
    };
    // What a tap on the centre of an element hits: proves it is not covered.
    const hit = (el) => {
      if (!el) return false;
      const b = el.getBoundingClientRect();
      const top = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
      return Boolean(top && (el === top || el.contains(top)));
    };
    const tile = document.querySelector('#ally-board [data-loc="g0,0"]');
    return {
      button: r(document.querySelector(`#stage-dock [data-open-panel="${panel}"]`)),
      drawer: r(document.getElementById('stage-drawer')),
      board: r(document.getElementById('battlefield')),
      fight: r(document.getElementById('fight-button')),
      tileHit: hit(tile), fightHit: hit(document.getElementById('fight-button')),
      panel: document.getElementById('stage-shell').getAttribute('data-panel'),
      size: document.getElementById('stage-drawer').getAttribute('data-size'),
      classes: document.body.className,
      vw: innerWidth, vh: innerHeight,
    };
  }, panel);
}

async function openPanel(page, panel) {
  const shell = page.locator('#stage-shell');
  if (await shell.getAttribute('data-panel') !== panel) await page.click(`#stage-dock [data-open-panel="${panel}"]`);
  await page.waitForFunction((p) => document.getElementById('stage-shell').getAttribute('data-panel') === p, panel);
  await page.waitForTimeout(60);
  return rects(page, panel);
}

const checks = {
  // board | drawer | dock: the drawer's right edge meets the dock; the board stays usable.
  async desktop(page, tag) {
    for (const panel of ['shop', 'bag', 'boost', 'journal']) {
      const g = await openPanel(page, panel);
      assert.match(g.classes, /layout-desktop/, tag);
      const gap = g.button.left - g.drawer.right;
      assert.ok(gap >= 0 && gap <= GAP, `${tag} ${panel}: drawer ends ${gap}px before its dock button`);
      assert.ok(spans(g.button, g.drawer), `${tag} ${panel}: button sits beside the drawer`);
      assert.ok(!overlaps(g.board, g.drawer), `${tag} ${panel}: drawer leaves the board visible`);
      assert.ok(g.tileHit, `${tag} ${panel}: a board tile is still clickable`);
      assert.ok(g.fightHit, `${tag} ${panel}: start battle stays reachable`);
    }
  },
  // scene | side sheet | rail; the shop is a bottom tray ending at the 商店 rail button.
  async landscape(page, tag) {
    for (const panel of ['bag', 'boost', 'bonds']) {
      const g = await openPanel(page, panel);
      assert.match(g.classes, /layout-landscape/, tag);
      const gap = g.button.left - g.drawer.right;
      assert.ok(gap >= 0 && gap <= GAP, `${tag} ${panel}: sheet ends ${gap}px before its rail button`);
      assert.ok(spans(g.button, g.drawer), `${tag} ${panel}: rail button sits beside the sheet`);
      assert.ok(!overlaps(g.board, g.drawer), `${tag} ${panel}: side sheet leaves the board visible`);
      assert.ok(g.tileHit, `${tag} ${panel}: a board tile is still tappable`);
      assert.ok(g.fightHit, `${tag} ${panel}: start battle stays reachable`);
    }
    const g = await openPanel(page, 'shop');
    assert.equal(g.size, 'peek', `${tag}: the shop is a tray`);
    assert.ok(g.vh - g.drawer.bottom <= GAP, `${tag}: the tray rises from the bottom edge`);
    assert.ok(g.drawer.width > g.vw * 0.6, `${tag}: the tray runs along the bottom`);
    const gap = g.button.left - g.drawer.right;
    assert.ok(gap >= 0 && gap <= GAP && spans(g.button, g.drawer), `${tag}: the tray ends at the 商店 rail button (${gap}px)`);
    assert.ok(g.board.top < g.drawer.top - 100, `${tag}: the enemy half stays visible above the tray`);
  },
  // bottom tab bar + sheet: the default sheet keeps the board's own rows visible.
  async portrait(page, tag) {
    for (const panel of ['bag', 'boost']) {
      const g = await openPanel(page, panel);
      assert.match(g.classes, /layout-phone/, tag);
      assert.equal(g.size, 'half', `${tag} ${panel}: half sheet by default`);
      assert.ok(g.drawer.top >= g.board.bottom - 2, `${tag} ${panel}: sheet top ${g.drawer.top} under the board ${g.board.bottom}`);
      const gap = g.button.top - g.drawer.bottom;
      assert.ok(gap >= -1 && gap <= GAP, `${tag} ${panel}: sheet sits right on the tab bar (${gap}px)`);
      assert.ok(g.tileHit, `${tag} ${panel}: a board tile is still tappable`);
    }
    await page.click('#stage-drawer [data-drawer-size]');
    await page.waitForTimeout(260);
    const full = await rects(page, 'boost');
    assert.equal(full.size, 'full', `${tag}: the sheet still expands`);
    assert.ok(full.drawer.top < 120, `${tag}: expanded sheet covers most of the screen`);
  },
};

(async () => {
  const sid = await newGame();
  const browser = await launch();
  const errors = [];
  try {
    for (const [width, height, kind] of [[1440, 900, 'desktop'], [1280, 720, 'desktop'], [844, 390, 'landscape'], [390, 844, 'portrait']]) {
      const page = await browser.newPage({viewport: {width, height}, hasTouch: kind !== 'desktop'});
      page.on('pageerror', (error) => errors.push(`${width}x${height}: ${error}`));
      await page.addInitScript((slot) => {
        localStorage.setItem('poketactics.play.arena.slot', slot);
        localStorage.setItem('poketactics.play.panel', 'closed');
      }, sid);
      await page.goto(`${base}/play`);
      await page.waitForSelector('#ally-board [data-loc="g0,0"]');
      await page.waitForTimeout(300);
      await checks[kind](page, `${width}x${height}`);
      await page.close();
    }
  } finally {
    await browser.close();
  }
  assert.deepEqual(errors, [], 'no page errors');
  console.log('scene geometry ok');
})().catch((error) => { console.error(error); process.exitCode = 1; });
