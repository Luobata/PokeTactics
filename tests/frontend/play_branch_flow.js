/* Branch families (docs/70): buying the third un-evolved copy prompts the route choice.
 * usage: node play_branch_flow.js <base-url> <sid>   (needs the `playwright` package) */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

const [base, sid] = process.argv.slice(2);

async function launch() {
  try { return await chromium.launch(); } catch (error) {
    const root = path.join(process.env.HOME || '', '.cache/ms-playwright');
    const dir = fs.existsSync(root) && fs.readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort().pop();
    const bin = dir && ['chrome-linux64/chrome', 'chrome-linux/chrome'].map((p) => path.join(root, dir, p)).find((p) => fs.existsSync(p));
    if (!bin) throw error;
    return chromium.launch({executablePath: bin});
  }
}

(async () => {
  const browser = await launch();
  const errors = [];
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 900}});
    page.on('pageerror', (e) => errors.push(e.message));
    await page.addInitScript(([k, v]) => localStorage.setItem(k, v), ['poketactics.play.arena.slot', sid]);
    await page.goto(`${base}/play?guide=0`);
    await page.waitForSelector('#shop [data-shop="0"]');
    await page.waitForTimeout(600);
    assert.equal(await page.locator('#branch-sheet').isVisible().catch(() => false), false, 'no prompt with two copies');
    await page.locator('#shop [data-shop="0"]').dblclick();
    await page.waitForSelector('#branch-sheet:not([hidden])', {timeout: 5000});
    assert.equal(await page.locator('[data-branch-pick]').count(), 2, 'one button per route');
    await page.locator('[data-branch-close]').first().click();
    assert.match(await page.locator('#hud-branch').innerText(), /选择进化/, 'HUD chip stays while pending');
    assert.ok(await page.locator('#bench [data-uid].branch-ready').count() >= 3, 'the three copies are badged');
    await page.locator('#bench [data-loc="b0"]').click({button: 'right'});
    const entry = page.locator('[role="menuitem"]', {hasText: '选择进化路线'});
    assert.equal(await entry.count(), 1, 'context menu offers the route choice');
    await entry.click();
    await page.waitForSelector('#branch-sheet:not([hidden])');
    await page.locator('[data-branch-pick]').last().click();
    await page.waitForFunction(() => document.querySelectorAll('#bench [data-uid]').length === 1, null, {timeout: 5000});
    assert.equal(await page.locator('#hud-branch').isVisible().catch(() => false), false, 'chip clears after the choice');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
