/* Board-centric layout (docs/61): dock, drawer / sheet, badges, HUD chips,
 * contextual bar and board cues, executed through the shipped play.js handlers
 * with play_layout.js loaded first. No server, no saves.
 * usage: node play_layout_presentation.js <play_layout.js> <play.js> <play.html> <scenario> [play_depth.js] */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const [layoutPath, playPath, htmlPath, scenario, depthPath] = process.argv.slice(2);
// The shared harness reads argv[2]/argv[3] at load time: hand it layout + play as one script.
const combined = path.join(os.tmpdir(), `play_layout_combined_${process.pid}.js`);
fs.writeFileSync(combined, `${fs.readFileSync(layoutPath, 'utf8')}\n;\n${fs.readFileSync(playPath, 'utf8')}`);
process.on('exit', () => fs.rmSync(combined, {force: true}));
process.argv[2] = combined;
process.argv[3] = htmlPath;
const {page, stateFixture} = require('./battle_report_presentation.js');

const PANELS = ['shop', 'detail', 'bag', 'boost', 'bonds', 'scout', 'orders', 'journal'];
function shopPiece(sid, name, price, extra = {}) {
  return {sid, name, tier: price, price, star: 1, shiny: false, range: 1, ranged: false,
    types: ['火'], colors: ['#f08030'], role_key: 'attack', role_description: '冲在最前面输出。',
    native_skill: {name: '火花', type: '火', description: '吐出火花。', tags: []}, bonds: [], learnable: [], ...extra};
}
function unit(uid, name, extra = {}) {
  return {uid, sid: 25, name, star: 1, range: 1, ranged: false, types: ['电'], bonds: [], role_key: 'attack',
    sell: 1, learnable: [], ...extra};
}
function fixture(options = {}) {
  const s = stateFixture({round: 4});
  s.you.gold = 3;
  s.shop = [shopPiece(4, '小火龙', 3), shopPiece(7, '杰尼龟', 2), shopPiece(150, '超梦', 5), null];
  s.bench = [unit('b-unit', '皮卡丘')];
  s.board[0][2] = unit('front', '小拳石', {range: 2, ranged: true, item: 'leftovers', item_name: '吃剩的东西'});
  s.board[2][4] = unit('back', '幸福蛋', {role_key: 'support', range: 3, ranged: true});
  s.you.on_board = 2;
  s.opponent = {name: '对手 L2', rows: [[null, unit('e1', '大岩蛇'), null, null, null, null],
    [null, null, null, null, null, null], [null, null, unit('e2', '腕力'), null, null, null]]};
  s.component_choices = [{id: 'supply3', round: 3, status: 'pending', options: []}];
  s.items = {components: [], finished: [{key: 'band', name: '力量头带', effect: '攻击 +10%'}], craftable: []};
  s.augments = {pending: options.augments ? [{id: 'aug4', round: 4, options: [{id: 'a', name: '海克斯甲', description: '说明'}]}] : [], selected: []};
  s.bonds = {entries: [{id: 'b1', name: '电气', tier: 2, n: 2}, {id: 'b2', name: '岩石', tier: 0, n: 1}]};
  if (options.depth) s.depth = {
    terrain: {id: 'embers', name: '余烬', description: '前排受灼烧。', cells: [[0, 1]], stage_end: 5, next: null},
    order: 'focus_fire', orders: [{id: 'none', name: '自由作战', brief: '不下达指令'}, {id: 'focus_fire', name: '集火', brief: '锁定目标'}],
    simulations_left: 2, simulation: null,
    draft: {status: 'pending', round: 4, order: ['你'], your_position: 1, options: []},
    threat: {counts: {front: 2}, window: 5, ranged_past_front: 1, note: '仅供参考。',
      enemies: [{loc: 'g0,1', name: '大岩蛇', ranged: true, target_uid: 'front', target: '小拳石'},
        {loc: 'g2,2', name: '腕力', ranged: false, target_uid: 'front', target: '小拳石'}],
      early: {front: {taken: 120, share: 0.45, falls: 1}, back: {taken: 0, share: 0, falls: 0}}},
  };
  return s;
}
const dock = (p, name) => p.element('stage-dock').querySelector(`[data-open-panel="${name}"]`);
const badge = (p, name) => p.element('stage-dock').querySelector(`[data-badge="${name}"]`);
function openPanel(p) {return p.element('stage-shell').getAttribute('data-panel');}
function assertOnlyVisible(p, name) {
  for (const panel of PANELS) {
    const section = p.element('drawer-body').querySelector(`[data-panel="${panel}"]`);
    assert.ok(section, `drawer panel ${panel} exists`);
    assert.equal(section.hidden, panel !== name, `panel ${panel} hidden=${panel !== name}`);
  }
}

const cases = {
  // Every element id the scripts look up must exist in the static page.
  async ids() {
    const p = await page(fixture());
    const dynamic = new Set(['empty-board-message', 'depth-strip', 'depth-draft', 'depth-targeted',
      'depth-bond-rules', 'battle-ledger', 'scout-unit-detail', 'scout-statistics', 'scout-combinations', 'trait-choice', 'battle-sprite-style']);
    const sources = [playPath, layoutPath, depthPath].filter(Boolean).map((file) => fs.readFileSync(file, 'utf8'));
    const ids = new Set();
    for (const text of sources)
      for (const match of text.matchAll(/(?:\$|getElementById)\("([a-z0-9-]+)"\)/g)) ids.add(match[1]);
    assert.ok(ids.size > 80, `collected ${ids.size} ids`);
    for (const id of ids) if (!dynamic.has(id)) assert.ok(p.document.getElementById(id), `page keeps #${id}`);
    for (const name of ['augments', 'techniques', 'items', 'research', 'growth'])
      for (const suffix of ['tab', 'panel', 'count'])
        assert.ok(p.document.getElementById(`${name}-${suffix}`), `page keeps #${name}-${suffix}`);
    // Legacy hooks queried by class stay present.
    for (const cls of ['.game-layout', '.center-column', '.board-scene', '.preparation-section', '.system-tabs', '.battle-report-tabs'])
      assert.ok(p.document.querySelector(cls), `page keeps ${cls}`);
  },

  async desktopDrawer() {
    const p = await page(fixture());
    const body = p.document.body;
    assert.ok(body.classList.contains('layout-desktop'));
    assert.equal(body.classList.contains('layout-phone'), false);
    assert.equal(openPanel(p), 'shop', 'desktop opens the shop drawer by default');
    assert.ok(body.classList.contains('drawer-open'));
    assertOnlyVisible(p, 'shop');
    assert.equal(dock(p, 'shop').getAttribute('aria-expanded'), 'true');
    assert.ok(dock(p, 'shop').classList.contains('active'));
    await p.click(dock(p, 'bag'));
    assert.equal(openPanel(p), 'bag');
    assertOnlyVisible(p, 'bag');
    assert.equal(p.element('drawer-title').textContent, '背包 · 装备');
    assert.equal(dock(p, 'shop').getAttribute('aria-expanded'), 'false');
    // The inventory, component supply and items count live in the bag panel.
    for (const id of ['inventory', 'component-choices', 'items-count', 'round-loot'])
      assert.ok(p.element('panel-bag').querySelector(`#${id}`), `#${id} inside the bag panel`);
    await p.click(dock(p, 'bag'));
    assert.equal(openPanel(p), '', 'clicking the active entry closes the drawer');
    assert.equal(body.classList.contains('drawer-open'), false);
    assertOnlyVisible(p, null);
    await p.click(dock(p, 'journal'));
    assertOnlyVisible(p, 'journal');
    await p.click(p.element('stage-drawer').querySelector('[data-close-panel]'));
    assert.equal(openPanel(p), '');
    // Opening a panel never calls the server.
    assert.equal(p.events.fetches.length, 1);
    p.unchanged();
  },

  async badges() {
    const p = await page(fixture({augments: true}));
    assert.equal(openPanel(p), 'boost', 'a pending augment opens the 强化 panel once');
    assert.equal(badge(p, 'shop').hidden, false);
    assert.equal(badge(p, 'shop').textContent, '2', 'two shop cards are affordable with 3 gold');
    assert.equal(badge(p, 'bag').textContent, '1!', 'pending component supply');
    assert.ok(badge(p, 'bag').classList.contains('accent'));
    assert.equal(badge(p, 'boost').textContent, '1!', 'pending augment');
    assert.equal(badge(p, 'bonds').textContent, '1', 'one active bond');
    assert.equal(badge(p, 'journal').textContent, '31');
    assert.equal(badge(p, 'orders').hidden, true, 'no depth: no simulation count');
    assert.equal(p.element('bench-count').textContent, '1 / 8');
    // Fight with a pending augment reveals the 强化 panel instead of scrolling.
    await p.click(p.element('stage-drawer').querySelector('[data-close-panel]'));
    assert.equal(openPanel(p), '');
    await p.click(p.element('fight-button'));
    assert.equal(openPanel(p), 'boost');
    assert.equal(p.events.fetches.length, 1, 'no end_prep while an augment is pending');
    p.unchanged();
  },

  async phoneSheet() {
    const p = await page(fixture(), {mobile: true});
    const body = p.document.body;
    assert.ok(body.classList.contains('layout-phone'));
    assert.equal(body.classList.contains('layout-desktop'), false);
    assert.equal(openPanel(p), '', 'phones start with the board only');
    await p.click(dock(p, 'shop'));
    assert.equal(openPanel(p), 'shop');
    assert.equal(p.element('stage-drawer').getAttribute('data-size'), 'peek', 'the shop sheet only peeks');
    assert.ok(/\d+px/.test(p.element('stage-drawer').style['--sheet-peek'] || ''), 'peek height is measured');
    assert.ok(/\d+px/.test(p.element('stage-drawer').style['--sheet-half'] || ''), 'half height (stops under the board rows) is measured');
    assert.equal(body.classList.contains('layout-landscape'), false, 'portrait is not the landscape scene');
    // Buying keeps the sheet open: preview + recruit happen while the shop stays visible.
    await p.click(p.element('shop').querySelector('[data-shop="1"]'));
    assert.equal(openPanel(p), 'shop');
    await p.click(dock(p, 'bonds'));
    assert.equal(p.element('stage-drawer').getAttribute('data-size'), 'half');
    await p.click(p.element('stage-drawer').querySelector('[data-drawer-size]'));
    assert.equal(p.element('stage-drawer').getAttribute('data-size'), 'full');
    await p.click(p.element('stage-drawer').querySelector('[data-drawer-size]'));
    assert.equal(p.element('stage-drawer').getAttribute('data-size'), 'half');
    await p.click(p.element('stage-drawer').querySelector('[data-close-panel]'));
    assert.equal(openPanel(p), '');
    p.unchanged();
  },

  // docs/68: landscape phones = in-scene HUD; side sheets beside the rail, shop as a bottom tray.
  async landscapeSheet() {
    const p = await page(fixture(), {landscape: true});
    const body = p.document.body;
    assert.ok(body.classList.contains('layout-phone'));
    assert.ok(body.classList.contains('layout-landscape'));
    assert.equal(openPanel(p), '', 'the scene starts with every panel closed');
    await p.click(dock(p, 'shop'));
    assert.equal(p.element('stage-drawer').getAttribute('data-size'), 'peek', 'the shop opens as the bottom tray');
    await p.click(dock(p, 'bag'));
    assert.equal(openPanel(p), 'bag');
    assert.equal(p.element('stage-drawer').getAttribute('data-size'), 'half', 'other panels are side sheets');
    // Side sheets have one height: the size control never grows them to a full-screen sheet.
    await p.click(p.element('stage-drawer').querySelector('[data-drawer-size]'));
    assert.equal(p.element('stage-drawer').getAttribute('data-size'), 'half');
    await p.click(dock(p, 'bag'));
    assert.equal(openPanel(p), '', 'the rail button toggles its sheet');
    assert.equal(p.events.fetches.length, 1);
    p.unchanged();
  },

  async contextBar() {
    const p = await page(fixture(), {mobile: true});
    const bar = p.element('context-bar');
    assert.equal(bar.hidden, true);
    await p.click(dock(p, 'shop'));
    await p.click(p.element('shop').querySelector('[data-shop="0"]'));
    assert.equal(bar.hidden, false);
    assert.match(bar.textContent, /小火龙/);
    const recruit = bar.querySelector('[data-shop-buy="0"]');
    assert.ok(recruit, 'quick recruit on the board');
    assert.equal(recruit.disabled, false);
    const short = await page(fixture(), {mobile: true});
    await short.click(short.element('shop').querySelector('[data-shop="2"]'));
    assert.equal(short.element('context-bar').querySelector('[data-shop-buy="2"]').disabled, true);
    assert.match(short.element('context-bar').textContent, /还差 2 金/);
    // Selecting a unit swaps in unit actions; 详情 opens the detail sheet.
    await p.click(p.element('ally-board').querySelector('[data-loc="g0,2"]'));
    assert.match(bar.textContent, /小拳石/);
    assert.ok(bar.querySelector('[data-action="sell"]'));
    assert.ok(bar.querySelector('[data-action="unequip"]'), 'equipped unit offers 卸装');
    assert.equal(bar.querySelector('[data-depth-core]'), null, 'no core action without the depth edition');
    await p.click(bar.querySelector('[data-layout-detail]'));
    assert.equal(openPanel(p), 'detail');
    assert.match(p.element('unit-detail').textContent, /小拳石/);
    // The detail's 学习技能 entry jumps to the 强化 panel.
    await p.click(p.element('unit-detail').querySelector('[data-open-system="techniques"]'));
    assert.equal(openPanel(p), 'boost');
    assert.equal(p.element('techniques-panel').hidden, false);
    await p.click(bar.querySelector('[data-action="cancel-select"]'));
    assert.equal(bar.hidden, true);
    // Equip mode explains itself on the board.
    await p.click(dock(p, 'bag'));
    await p.click(p.element('inventory').querySelector('[data-equip="band"]'));
    assert.equal(bar.hidden, false);
    assert.match(bar.textContent, /装备「力量头带」/);
    assert.equal(p.events.fetches.length, 1);
    p.unchanged();
  },

  async depthHud() {
    const p = await page(fixture({depth: true}));
    assert.equal(p.element('hud-terrain').hidden, false);
    assert.match(p.element('hud-terrain').textContent, /余烬/);
    assert.ok(p.element('hud-terrain').classList.contains('terrain-embers'));
    assert.match(p.element('hud-order').textContent, /集火/);
    assert.ok(p.element('hud-order').classList.contains('on'));
    assert.match(p.element('hud-sim').textContent, /×2/);
    assert.equal(p.element('hud-draft').hidden, false);
    assert.equal(badge(p, 'orders').textContent, '2', 'simulations left');
    assert.equal(badge(p, 'scout').textContent, '1!', 'one unit may fall in the first seconds');
    // A pending draft opens the sheet; 稍后 defers it for this round; the chip reopens it.
    assert.equal(p.element('draft-overlay').hidden, false);
    await p.click(p.element('draft-overlay').querySelector('[data-draft-later]'));
    assert.equal(p.element('draft-overlay').hidden, true);
    await p.click(dock(p, 'shop'));
    await p.click(dock(p, 'shop'));
    assert.equal(p.element('draft-overlay').hidden, true, 'stays deferred across renders');
    await p.click(p.element('hud-draft'));
    assert.equal(p.element('draft-overlay').hidden, false);
    // HUD chips open the 指令 panel.
    await p.click(p.element('hud-order'));
    assert.equal(openPanel(p), 'orders');
    // Threat summary lists first targets, early pressure and the backend note.
    const summary = p.element('threat-summary');
    assert.equal(summary.hidden, false);
    assert.match(summary.textContent, /小拳石/);
    assert.match(summary.textContent, /大岩蛇（远程）/);
    assert.match(summary.textContent, /45% 生命/);
    assert.match(summary.textContent, /3 次中 1 次倒下/);
    assert.match(summary.textContent, /1 名远程敌人越过前排/);
    assert.match(summary.textContent, /仅供参考/);
    p.unchanged();
  },

  async rangeThreat() {
    const p = await page(fixture({depth: true}));
    await p.click(p.element('draft-overlay').querySelector('[data-draft-later]'));
    assert.equal(p.element('enemy-board').querySelectorAll('button').length, 18);
    await p.click(p.element('ally-board').querySelector('[data-loc="g0,2"]'));
    // play.js re-renders the boards on every render: query the fresh tiles.
    const enemyTiles = p.element('enemy-board').querySelectorAll('button');
    // Own front row g0,2 is battle row 3; range 2 reaches enemy rows 1–2 around column 2.
    const inRange = enemyTiles.map((tile, i) => tile.classList.contains('in-range') ? `g${Math.floor(i / 6)},${i % 6}` : null).filter(Boolean);
    assert.deepEqual(inRange.sort(), ['g1,2', 'g2,1', 'g2,2', 'g2,3'].sort());
    // Both enemies target the selected unit: they are marked and connected.
    const from = enemyTiles.map((tile, i) => tile.classList.contains('threat-from') ? `g${Math.floor(i / 6)},${i % 6}` : null).filter(Boolean);
    assert.deepEqual(from.sort(), ['g0,1', 'g2,2']);
    assert.equal((p.element('board-overlay').innerHTML.match(/<line /g) || []).length, 2);
    assert.match(p.element('context-bar').textContent, /⚔2 · 5秒承伤 45% · 可能倒下/);
    // The back-row support is not targeted: no lines.
    await new Promise((resolve) => setTimeout(resolve, 400));  // slow second click deselects (fast = double-click)
    await p.click(p.element('ally-board').querySelector('[data-loc="g0,2"]'));
    await p.click(p.element('ally-board').querySelector('[data-loc="g2,4"]'));
    assert.equal((p.element('board-overlay').innerHTML.match(/<line /g) || []).length, 0);
    // "Show all" draws every opening target without hover.
    await p.click(p.element('threat-summary').querySelector('[data-threat-all]'));
    assert.equal((p.element('board-overlay').innerHTML.match(/<line /g) || []).length, 2);
    assert.equal(p.events.fetches.length, 1);
    p.unchanged();
  },

  // docs/66: pure selection never rebuilds keyed sections; it only toggles classes.
  async keyedSelection() {
    const p = await page(fixture());
    const board = p.element('ally-board'), bench = p.element('bench'), shop = p.element('shop');
    const nodes = () => [board.children[0], board.children[2], bench.children[0], shop.children[0], shop.children[1],
      p.element('synergy-list').children[0], p.element('enemy-board').children[0]];
    const before = nodes();
    const benchTile = bench.querySelector('[data-loc="b0"]');
    await p.click(benchTile);
    assert.deepEqual(nodes(), before, 'selecting a unit keeps every tile / card node');
    assert.ok(benchTile.classList.contains('selected'));
    assert.equal(benchTile.getAttribute('aria-pressed'), 'true');
    await p.click(shop.querySelector('[data-shop="1"]'));
    assert.deepEqual(nodes(), before, 'shop preview keeps them too');
    assert.equal(benchTile.classList.contains('selected'), false);
    assert.equal(benchTile.hasAttribute('aria-pressed'), false);
    assert.ok(shop.querySelector('[data-shop="1"]').classList.contains('selected'));
    await p.click(p.element('context-bar').querySelector('[data-action="cancel-select"]'));
    assert.deepEqual(nodes(), before);
    assert.equal(shop.querySelector('[aria-pressed="true"]'), null);
    // Equip target mode marks owned units by class only.
    await p.click(p.element('stage-dock').querySelector('[data-open-panel="bag"]'));
    await p.click(p.element('inventory').querySelector('[data-equip="band"]'));
    assert.deepEqual(nodes(), before);
    assert.ok(board.querySelector('[data-loc="g0,2"]').classList.contains('equip-target'));
    assert.equal(board.querySelector('[data-loc="g0,0"]').classList.contains('equip-target'), false, 'empty cells are not targets');
    assert.equal(p.events.fetches.length, 1);
    p.unchanged();
  },

  // docs/66: a purchase shows its likely result at once and the server answer reconciles it.
  async optimisticBuy() {
    const p = await page(fixture(), {pendingMutation: true, mutationResponder: () => ({ok: true})});
    const card = p.element('shop').querySelector('[data-shop="1"]');
    await p.click(card);
    await p.startClick(p.element('shop').querySelector('[data-shop="1"]'));
    assert.equal(p.events.fetches.length, 2, 'the buy request is in flight');
    const pending = p.element('bench').querySelector('[data-uid="optimistic-1"]');
    assert.ok(pending, 'the bought unit is already on the bench');
    assert.ok(pending.classList.contains('opt-arriving'));
    assert.match(pending.getAttribute('aria-label'), /杰尼龟/);
    assert.equal(p.element('shop').querySelector('[data-shop="1"]'), null, 'its shop slot shows as sold');
    assert.equal(p.element('gold').textContent, '1', 'gold already paid');
    p.unchanged();
  },

  async optimisticRollback() {
    const p = await page(fixture(), {mutationResponder: () => ({ok: false, error: '金币不足'})});
    const bench = p.element('bench');
    await p.click(p.element('shop').querySelector('[data-shop="1"]'));
    await p.click(p.element('shop').querySelector('[data-shop="1"]'));
    assert.equal(bench.querySelector('[data-uid="optimistic-1"]'), null, 'rejected purchase rolls back');
    assert.ok(p.element('shop').querySelector('[data-shop="1"]'), 'the card is back');
    assert.equal(p.element('gold').textContent, '3');
    assert.match(p.element('toast').textContent, /金币不足/);
    // A move that the server rejects puts the unit back where it was.
    await p.click(p.element('ally-board').querySelector('[data-loc="g0,2"]'));
    await p.click(p.element('ally-board').querySelector('[data-loc="g1,2"]'));
    assert.ok(p.element('ally-board').querySelector('[data-loc="g0,2"]').hasAttribute('data-owned'));
    assert.equal(p.element('ally-board').querySelector('[data-loc="g1,2"]').hasAttribute('data-owned'), false);
    p.unchanged();
  },

  // arena_v1 saves have no state.depth: no chips, no threat, no draft.
  async legacy() {
    const p = await page(fixture());
    for (const id of ['hud-terrain', 'hud-order', 'hud-sim', 'hud-draft', 'threat-summary', 'draft-overlay'])
      assert.equal(p.element(id).hidden, true, `#${id} hidden without the depth edition`);
    assert.equal(p.element('hud-streak').hidden, true);
    await p.click(p.element('ally-board').querySelector('[data-loc="g0,2"]'));
    assert.equal(p.element('board-overlay').innerHTML, '', 'no threat data, no lines');
    assert.ok(p.element('enemy-board').querySelectorAll('button').some((tile) => tile.classList.contains('in-range')),
      'attack range still highlights without depth data');
    p.unchanged();
  },
};

(async () => {
  assert.ok(cases[scenario], `Unknown scenario ${scenario}`);
  await cases[scenario]();
})().catch((error) => {console.error(error); process.exitCode = 1;});
