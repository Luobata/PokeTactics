/* Themed dropdowns (docs/66) on the shipped page: the native <select> stays the
 * source of truth (id, value, change event); the button/listbox drive it.
 * usage: node play_select_presentation.js <play_select.js> <play.js> <play.html> <scenario> */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const [selectPath, playPath, htmlPath, scenario] = process.argv.slice(2);
const combined = path.join(os.tmpdir(), `play_select_combined_${process.pid}.js`);
fs.writeFileSync(combined, `${fs.readFileSync(selectPath, 'utf8')}\n;\n${fs.readFileSync(playPath, 'utf8')}`);
process.on('exit', () => fs.rmSync(combined, {force: true}));
process.argv[2] = combined;
process.argv[3] = htmlPath;
const {page, stateFixture, openHistory} = require('./battle_report_presentation.js');

const options = (p, id) => p.element(`${id}-ps-list`).querySelectorAll('[role="option"]');
const key = (p, id, k) => p.dispatch(`${id}-ps-list`, 'keydown', {key: k});

const cases = {
  async keyboard() {
    const p = await page(stateFixture());
    const select = p.element('battle-speed');
    const button = p.element('battle-speed-ps');
    assert.ok(select.classList.contains('ps-native'), 'native select stays, hidden');
    assert.equal(select.getAttribute('aria-hidden'), 'true');
    assert.equal(button.getAttribute('aria-haspopup'), 'listbox');
    assert.equal(button.getAttribute('aria-expanded'), 'false');
    assert.match(button.textContent, /1×/);
    assert.match(button.getAttribute('aria-label'), /速度：1×/);
    const changes = [];
    select.addEventListener('change', (event) => changes.push(event.target.value));
    await p.click(button);
    assert.equal(button.getAttribute('aria-expanded'), 'true');
    const list = p.element('battle-speed-ps-list');
    assert.equal(list.getAttribute('role'), 'listbox');
    assert.equal(button.getAttribute('aria-controls'), 'battle-speed-ps-list');
    assert.equal(options(p, 'battle-speed').length, 4);
    assert.equal(options(p, 'battle-speed')[1].getAttribute('aria-selected'), 'true');
    assert.match(list.getAttribute('aria-activedescendant'), /-1$/);
    await key(p, 'battle-speed', 'ArrowDown');
    assert.match(list.getAttribute('aria-activedescendant'), /-2$/);
    await key(p, 'battle-speed', 'ArrowUp');
    await key(p, 'battle-speed', 'ArrowUp');
    assert.match(list.getAttribute('aria-activedescendant'), /-0$/);
    await key(p, 'battle-speed', '4');          // type-ahead
    assert.match(list.getAttribute('aria-activedescendant'), /-3$/);
    await key(p, 'battle-speed', 'Enter');
    assert.equal(select.value, '4');
    assert.deepEqual(changes, ['4'], 'one real change event reaches listeners');
    assert.match(button.textContent, /4×/);
    assert.equal(button.getAttribute('aria-expanded'), 'false');
    assert.equal(p.document.getElementById('battle-speed-ps-list'), null, 'popover removed');
    // Escape closes without a change; re-picking the same value fires nothing.
    await p.click(button);
    await key(p, 'battle-speed', 'Escape');
    assert.equal(p.document.getElementById('battle-speed-ps-list'), null);
    await p.click(button);
    await key(p, 'battle-speed', 'Enter');
    assert.deepEqual(changes, ['4']);
    // Clicking the button again toggles the popover closed.
    await p.click(button);
    await p.click(button);
    assert.equal(p.document.getElementById('battle-speed-ps-list'), null);
    p.unchanged();
  },

  async phoneSheet() {
    const p = await page(stateFixture(), {mobile: true});
    await p.click(p.element('battle-speed-ps'));
    const list = p.element('battle-speed-ps-list');
    assert.ok(list.classList.contains('ps-sheet'), 'phones get a bottom sheet');
    assert.ok(p.document.querySelector('.ps-backdrop'));
    assert.match(list.querySelector('.ps-sheet-title').textContent, /速度/);
    const row = options(p, 'battle-speed')[2];
    await list.onclick({target: row});
    assert.equal(p.element('battle-speed').value, '2');
    assert.equal(p.document.querySelector('.ps-backdrop'), null, 'sheet and backdrop close');
    p.unchanged();
  },

  async dynamicOptions() {
    const p = await page(stateFixture());
    await openHistory(p, 2);
    const select = p.element('history-report-round');
    const sync = p.element('history-report-round-ps');
    assert.ok(sync, 'static select enhanced at load');
    // Options were rebuilt and the value set from code. The browser's
    // MutationObserver / value hook re-syncs; the harness has neither.
    p.window.PlaySelect.sync(select);
    await p.click(sync);
    const rows = options(p, 'history-report-round');
    assert.equal(rows.length, 31);
    assert.match(sync.textContent, /第 2 轮/);
    const third = rows.find((row) => /第 3 轮/.test(row.textContent));
    await p.element('history-report-round-ps-list').onclick({target: third});
    assert.equal(p.element('history-report-title').textContent, '第 3 轮 · 战报', 'change handler opened round 3');
    assert.match(sync.textContent, /第 3 轮/);
    p.unchanged();
  },
};

(async () => {
  assert.ok(cases[scenario], `Unknown scenario ${scenario}`);
  await cases[scenario]();
})().catch((error) => {console.error(error); process.exitCode = 1;});
