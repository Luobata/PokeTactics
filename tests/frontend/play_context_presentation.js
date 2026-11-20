/* docs/70 interaction shortcuts through the shipped handlers: context menu per
 * target kind, re-click deselect rules, preview card / glossary content and the
 * first-run guide. No server; mutations are recorded.
 * usage: node play_context_presentation.js <acceptance dir> <play.html> <scenario> */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const [dir, htmlPath, scenario] = process.argv.slice(2);
const scripts = ['play_layout.js', 'play_preview.js', 'play_context.js', 'play_guide.js', 'play_interactions.js', 'play.js'];
const combined = path.join(os.tmpdir(), `play_context_combined_${process.pid}.js`);
fs.writeFileSync(combined, scripts.map((file) => fs.readFileSync(path.join(dir, file), 'utf8')).join('\n;\n'));
process.on('exit', () => fs.rmSync(combined, {force: true}));
process.argv[2] = combined;
process.argv[3] = htmlPath;
const {page, stateFixture} = require('./battle_report_presentation.js');

function unit(uid, name, extra = {}) {
  return {uid, sid: 25, name, star: 1, range: 1, ranged: false, types: ['电'], bonds: [], role_key: 'attack', sell: 1,
    native_skill: {name: '电击', type: '电', description: '放电，命中时有几率麻痹目标。', tags: ['单体']},
    trait: {id: 't', name: '静电', description: '被近战攻击时使攻击者麻痹。'}, ...extra};
}
function fixture(options = {}) {
  const s = stateFixture({round: 5});
  s.you.gold = options.gold ?? 6;
  s.you.pop = options.pop ?? 3;
  s.board[0][2] = unit('front', '小拳石', {role_key: 'defense', item: 'leftovers', item_name: '吃剩的东西', item_effect: '每秒回复生命。'});
  s.bench = [unit('bench1', '皮卡丘'), unit('bench2', '波波', {ranged: true, range: 3})];
  s.you.on_board = 1;
  s.shop = [{...unit(null, '小火龙'), uid: undefined, price: 3, tier: 3, sid: 4}, {...unit(null, '超梦'), uid: undefined, price: 9, tier: 5, sid: 150}];
  s.opponent = {name: '对手', rows: [[null, unit('e1', '大岩蛇'), null, null, null, null], [null, null, null, null, null, null], [null, null, null, null, null, null]]};
  s.items = {components: [], finished: [{key: 'metronome', name: '节拍器', effect: '普攻叠攻速'}], craftable: []};
  s.techniques = [{id: 'cut', name: '居合斩', description: '追加斩击。', cost: 2, count: 1}];
  s.bonds = {entries: [{id: 'ELECTRIC', name: '电', category: 'type', tier: 0, n: 1, next: 2,
    thresholds: [{count: 2, effect: '电系招式附带麻痹。'}, {count: 4, effect: '电系攻速提高。'}]}]};
  if (options.depth) s.depth = {simulations_left: 0, items: {unequip_cost: 1, dismantle_cost: 1, sell_value: 2}};
  s.interactions = {version: 1,
    augments: {pending: [], selected: []},
    techniques: {cut: {category: 'damage', category_name: '伤害', compatible: ['front', 'bench1'], known_by: [], cost: 2, count: 1,
      best: {uid: 'bench1', name: '皮卡丘', reasons: ['伤害招式最适合攻击型']}}},
    skills: {front: {mods: []}, bench1: {mods: []}, bench2: {mods: []}},
    equip: {unequip_cost: 1,
      items: {metronome: {name: '节拍器', lines: ['普攻叠攻速'], stats: [], effect: '同一目标叠攻速。', recipe: '力量头带 + 力量头带',
        carriers: [{uid: 'front', name: '小拳石', reason: '已满'}, {uid: 'bench2', name: '波波', reason: '远程 · 普攻多'}], suits: '普攻型'}},
      slots: {front: {total: 1, used: 1, items: []}, bench1: {total: 1, used: 0, items: []}, bench2: {total: 1, used: 0, items: []}}},
    item_advice: {suggestions: [{action: 'equip', item: 'metronome', name: '节拍器', uid: 'bench1', unit: '皮卡丘', why: ['叠攻速']}],
      guides: {metronome: {archetype: '输出', playstyle: '同目标叠攻速', active: [], missing: [], mechanic: true}}},
    item_synergy: {awaken: {round: 5, left: 1, limit: 2, options: [{key: 'metronome', name: '节拍器', uid: '', unit: '', ready: true, have: ['band'], components: ['band'], component_names: ['力量头带'], clause: '觉醒'}]}},
  };
  return s;
}
function recorder() {
  const calls = [];
  return {calls, options: {mutationResponder: (query) => {
    calls.push(Object.fromEntries(query));
    return {ok: true, msg: 'ok'};
  }}};
}
const tile = (p, loc) => p.element(loc[0] === 'b' ? 'bench' : 'ally-board').querySelector(`[data-loc="${loc}"]`);
const settle = async (p, n = 3) => { for (let i = 0; i < n; i++) await p.settle(); };
/** Run the document-level listeners for one event, honouring stopImmediatePropagation. */
async function fire(p, type, target, extra = {}) {
  const event = {type, target, stopped: false, defaultPrevented: false, clientX: 120, clientY: 140, button: 2,
    preventDefault() {this.defaultPrevented = true;}, stopPropagation() {}, stopImmediatePropagation() {this.stopped = true;}, ...extra};
  for (const handler of p.document.listeners[type] || []) {
    if (event.stopped) break;
    await handler(event);
  }
  await settle(p);
  return event;
}
const menu = (p) => p.document.getElementById('ctx-menu');
const menuOpen = (p) => Boolean(menu(p)) && menu(p).hidden === false;
const entries = (p) => menu(p).querySelectorAll('[data-ctx]');
const entry = (p, label) => entries(p).find((el) => el.querySelector('.ctx-label').textContent.includes(label));
async function pick(p, label) {
  const el = entry(p, label);
  assert.ok(el, `menu entry ${label}: ${entries(p).map((e) => e.textContent).join(' | ')}`);
  el.dispatchEvent({type: 'click', target: el});
  await settle(p, 6);
}

const cases = {
  async unitMenu() {
    const rec = recorder();
    const p = await page(fixture(), rec.options);
    const event = await fire(p, 'contextmenu', tile(p, 'b0'));
    assert.ok(event.defaultPrevented, 'native menu suppressed on a unit');
    assert.ok(menuOpen(p));
    assert.match(menu(p).querySelector('.ctx-head').textContent, /皮卡丘/);
    for (const label of ['详情', '上场', '装备…', '学习技能机…', '出售'])
      assert.ok(entry(p, label), `unit menu offers ${label}`);
    assert.match(entry(p, '出售').textContent, /\+1 金/);
    // 装备… submenu: the advisor's pick first.
    await pick(p, '装备…');
    assert.match(menu(p).querySelector('.ctx-head').textContent, /为 皮卡丘 装备/);
    assert.match(entries(p)[0].textContent, /节拍器.*最佳/);
    await pick(p, '节拍器');
    assert.equal(menuOpen(p), false, 'running an entry closes the menu');
    assert.deepEqual([rec.calls.at(-1).cmd, rec.calls.at(-1).item, rec.calls.at(-1).loc], ['equip', 'metronome', 'b0']);
    // 上场 goes to the best free cell for the role.
    await fire(p, 'contextmenu', tile(p, 'b0'));
    await pick(p, '上场');
    assert.deepEqual([rec.calls.at(-1).cmd, rec.calls.at(-1).from], ['move', 'b0']);
    assert.match(rec.calls.at(-1).to, /^g[0-2],[0-5]$/);
    // Board unit: 下场, 卸下装备 (equipped), 装备… disabled with the reason (slot full).
    await fire(p, 'contextmenu', tile(p, 'g0,2'));
    assert.ok(entry(p, '下场到备战席'));
    assert.ok(entry(p, '卸下装备'));
    const equip = entry(p, '装备…');
    assert.equal(equip.getAttribute('aria-disabled'), 'true');
    assert.match(equip.textContent, /装备位已满/);
    await pick(p, '装备…');
    assert.match(menu(p).querySelector('.ctx-head').textContent, /小拳石/, 'a disabled entry keeps the menu as it is');
    await pick(p, '卸下装备');
    assert.deepEqual([rec.calls.at(-1).cmd, rec.calls.at(-1).loc], ['unequip', 'g0,2']);
    p.unchanged();
  },

  async populationAndPhase() {
    const p = await page(fixture({pop: 1}), recorder().options);
    await fire(p, 'contextmenu', tile(p, 'b0'));
    const deploy = entry(p, '上场');
    assert.equal(deploy.getAttribute('aria-disabled'), 'true');
    assert.match(deploy.textContent, /上场人口已满（1\/1）/);
    await pick(p, '上场');
    assert.equal(p.events.fetches.length, 1, 'disabled entries never call the server');
    // Battle phase: everything that mutates is disabled with the phase reason; 详情 stays.
    const q = await page({...fixture(), phase: 'battle'});
    await fire(q, 'contextmenu', tile(q, 'g0,2'));
    assert.equal(entry(q, '出售').getAttribute('aria-disabled'), 'true');
    assert.match(entry(q, '出售').textContent, /准备阶段才能操作/);
    assert.equal(entry(q, '详情').hasAttribute('aria-disabled'), false);
  },

  async shopMenu() {
    const rec = recorder();
    const p = await page(fixture(), rec.options);
    await fire(p, 'contextmenu', p.element('shop').querySelector('[data-shop="1"]'));
    const buy = entry(p, '购买');
    assert.equal(buy.getAttribute('aria-disabled'), 'true');
    assert.match(buy.textContent, /金币不足，还差 3 金/);
    for (const label of ['购买并上场', '详情', '锁定商店', '刷新商店']) assert.ok(entry(p, label), label);
    await pick(p, '锁定商店');
    assert.equal(rec.calls.at(-1).cmd, 'lock');
    await fire(p, 'contextmenu', p.element('shop').querySelector('[data-shop="0"]'));
    await pick(p, '购买');
    assert.deepEqual([rec.calls.at(-1).cmd, rec.calls.at(-1).i], ['buy', '0']);
    await fire(p, 'contextmenu', p.element('shop').querySelector('[data-shop="0"]'));
    await pick(p, '详情');
    assert.ok(p.element('shop').querySelector('[data-shop="0"]').classList.contains('selected'), '详情 selects the card');
    assert.match(p.element('unit-detail').textContent, /小火龙/);
  },

  async itemAndMachineMenus() {
    const rec = recorder();
    const p = await page(fixture({depth: true}), rec.options);
    const card = p.element('ix-items').querySelector('.ix-item-card');
    await fire(p, 'contextmenu', card);
    assert.match(menu(p).querySelector('.ctx-head').textContent, /节拍器/);
    // Recommended carrier with a free slot: 小拳石 is full, so 波波.
    assert.match(entries(p)[0].textContent, /装给 波波/);
    for (const label of ['选择携带者…', '觉醒 节拍器', '拆解', '出售']) assert.ok(entry(p, label), label);
    await pick(p, '装给 波波');
    assert.deepEqual([rec.calls.at(-1).cmd, rec.calls.at(-1).item, rec.calls.at(-1).loc], ['equip', 'metronome', 'b1']);
    await fire(p, 'contextmenu', card);
    await pick(p, '拆解');
    assert.deepEqual([rec.calls.at(-1).cmd, rec.calls.at(-1).item], ['dismantle', 'metronome']);
    await fire(p, 'contextmenu', card);
    await pick(p, '选择携带者…');
    assert.equal(p.window.PlayInteractions.mode()?.kind, 'equip', 'enters the item targeting mode');
    // Machine card: learn for the recommended unit opens the confirm sheet.
    await fire(p, 'contextmenu', p.element('ix-tm-rack').querySelector('[data-ix-tm="cut"]'));
    await pick(p, '学给 皮卡丘');
    assert.equal(p.element('ix-sheet').hidden, false);
    assert.match(p.element('ix-sheet-title').textContent, /学习 居合斩/);
  },

  async enemyAndCellMenus() {
    const rec = recorder();
    const p = await page(fixture(), rec.options);
    const enemy = p.element('enemy-board').querySelector('[data-enemy-loc="g0,1"]');
    await fire(p, 'contextmenu', enemy);
    assert.ok(entry(p, '侦察详情') && entry(p, '查看对手整队'));
    await pick(p, '侦察详情');
    assert.equal(p.element('scout-dialog').open, true);
    assert.ok(p.element('enemy-board').querySelector('[data-enemy-loc="g0,1"]').classList.contains('selected'), 'scouted enemy is marked');
    p.element('scout-dialog').close();
    // Empty cell: 放置备战席精灵… and 一键上场; with a selected bench unit, a direct move.
    await fire(p, 'contextmenu', tile(p, 'g1,1'));
    assert.ok(entry(p, '放置备战席精灵…') && entry(p, '一键上场'));
    await pick(p, '放置备战席精灵…');
    await pick(p, '波波');
    assert.deepEqual([rec.calls.at(-1).cmd, rec.calls.at(-1).from, rec.calls.at(-1).to], ['move', 'b1', 'g1,1']);
    await p.click(tile(p, 'b0'));
    await fire(p, 'contextmenu', tile(p, 'g2,5'));
    await pick(p, '把 皮卡丘 放到这里');
    assert.deepEqual([rec.calls.at(-1).from, rec.calls.at(-1).to], ['b0', 'g2,5']);
  },

  async keyboardMenu() {
    const p = await page(fixture(), recorder().options);
    tile(p, 'b0').focus();
    const event = await fire(p, 'keydown', p.document.activeElement, {key: 'F10', shiftKey: true});
    assert.ok(event.defaultPrevented);
    assert.ok(menuOpen(p));
    assert.equal(p.document.activeElement, entries(p)[0], 'focus moves into the menu');
    const key = async (name) => { menu(p).dispatchEvent({type: 'keydown', key: name, preventDefault() {}, stopPropagation() {}}); await settle(p); };
    await key('ArrowDown');
    assert.equal(p.document.activeElement, entries(p)[1]);
    await key('End');
    assert.equal(p.document.activeElement, entries(p).at(-1));
    await key('Home');
    await key('ArrowDown');
    await key('ArrowDown');  // 装备…
    await key('ArrowRight');
    assert.match(menu(p).querySelector('.ctx-head').textContent, /为 皮卡丘 装备/);
    await key('ArrowLeft');
    assert.match(menu(p).querySelector('.ctx-head').textContent, /皮卡丘 ★/);
    await key('Escape');
    assert.equal(menuOpen(p), false);
    assert.equal(p.document.activeElement, tile(p, 'b0'), 'focus returns to the unit');
    // Menu key works too; outside press closes.
    await fire(p, 'keydown', tile(p, 'b0'), {key: 'ContextMenu'});
    assert.ok(menuOpen(p));
    await fire(p, 'pointerdown', p.element('fight-button'), {pointerType: 'mouse', button: 0});
    assert.equal(menuOpen(p), false);
  },

  async longPress() {
    const p = await page(fixture(), recorder().options);
    await fire(p, 'pointerdown', tile(p, 'b0'), {pointerType: 'touch', button: 0});
    await p.expireTimeouts(p.window.PlayContext.LONG_PRESS_MS);
    assert.ok(menuOpen(p), 'long press opens the menu');
    // The click produced by lifting the finger is eaten (it would land on the sheet).
    await fire(p, 'pointerup', tile(p, 'b0'), {pointerType: 'touch'});
    const click = await fire(p, 'click', tile(p, 'b0'), {button: 0});
    assert.ok(click.stopped);
    assert.equal(tile(p, 'b0').classList.contains('selected'), false, 'long press does not select');
    p.window.PlayContext.close();
    // Moving the finger cancels (that is a scroll or a drag).
    await fire(p, 'pointerdown', tile(p, 'b0'), {pointerType: 'touch', button: 0, clientX: 10, clientY: 10});
    await fire(p, 'pointermove', tile(p, 'b0'), {pointerType: 'touch', clientX: 40, clientY: 10});
    await p.expireTimeouts(p.window.PlayContext.LONG_PRESS_MS);
    assert.equal(menuOpen(p), false);
  },

  async reclickDeselect() {
    let now = 1_000_000;
    const rec = recorder();
    const p = await page(fixture(), {...rec.options, clock: () => now});
    const t = () => tile(p, 'b0');
    // Unit: click selects, a slow second click (≥ 300 ms) deselects.
    await p.click(t());
    assert.ok(t().classList.contains('selected'));
    now += 450;
    await p.click(t());
    assert.equal(t().classList.contains('selected'), false, 'slow re-click deselects');
    // Unit: a fast second click is a double-click → quick deploy.
    now += 1000;
    await p.click(t());
    now += 180;
    await p.click(t());
    assert.deepEqual([rec.calls.at(-1).cmd, rec.calls.at(-1).from], ['move', 'b0']);
    // Shop: click selects, slow re-click deselects (no purchase), fast double-click buys.
    const card = () => p.element('shop').querySelector('[data-shop="0"]');
    const calls = rec.calls.length;
    now += 1000;
    await p.click(card());
    assert.ok(card().classList.contains('selected'));
    now += 450;
    await p.click(card());
    assert.equal(card().classList.contains('selected'), false, 'slow re-click on a shop card deselects');
    assert.equal(rec.calls.length, calls, 'no purchase on a slow re-click');
    now += 1000;
    await p.click(card());
    now += 150;
    await p.click(card());
    assert.deepEqual([rec.calls.at(-1).cmd, rec.calls.at(-1).i], ['buy', '0'], 'double-click recruits');
    // Enemy: click opens the scout view on it, clicking it again closes it.
    const enemy = () => p.element('enemy-board').querySelector('[data-enemy-loc="g0,1"]');
    await p.click(enemy());
    assert.equal(p.element('scout-dialog').open, true);
    assert.ok(enemy().classList.contains('selected'));
    await p.click(enemy());
    assert.equal(p.element('scout-dialog').open, false);
    assert.equal(enemy().classList.contains('selected'), false);
    // Item / machine targeting modes toggle off on a second click.
    const tm = () => p.element('ix-tm-rack').querySelector('[data-ix-tm="cut"]');
    await p.click(tm());
    assert.equal(p.window.PlayInteractions.mode()?.kind, 'tm');
    await p.click(tm());
    assert.equal(p.window.PlayInteractions.mode(), null);
    const item = () => p.element('ix-items').querySelector('[data-ix-equip="metronome"]');
    await p.click(item());
    assert.equal(p.window.PlayInteractions.mode()?.kind, 'equip');
    await p.click(item());
    assert.equal(p.window.PlayInteractions.mode(), null);
    // Esc clears a selection even while the tile button keeps focus.
    now += 1000;
    await p.click(t());
    t().focus();
    assert.ok(t().classList.contains('selected'));
    await fire(p, 'keydown', t(), {key: 'Escape', code: 'Escape', button: 0});
    assert.equal(t().classList.contains('selected'), false, 'Esc on a focused tile deselects');
  },

  async previewAndGlossary() {
    let now = 1_000_000;
    const p = await page(fixture(), {...recorder().options, clock: () => now});
    const G = p.window.PlayGlossary;
    assert.match(G.define('麻痹'), /攻击速度降低/);
    assert.equal(G.define('原生技能'), G.define('本命技能'), 'aliases share one definition');
    const marked = G.mark('命中时麻痹目标，再次麻痹 <b>');
    assert.equal((marked.match(/class="gl-term"/g) || []).length, 1, 'first occurrence only');
    assert.match(marked, /data-gl="麻痹"/);
    assert.match(marked, /&lt;b&gt;/, 'escapes the rest');
    const P = p.window.PlayPreview;
    const unitHtml = P.describe({kind: 'unit', key: 'b0'});
    for (const copy of ['皮卡丘', '备战席', '攻击型', '本命', '电击', '特性', '静电', '麻痹', '双击上场'])
      assert.match(unitHtml, new RegExp(copy), `unit preview shows ${copy}`);
    assert.match(unitHtml, /<dt>麻痹<\/dt>/, 'keyword explained in the card');
    assert.match(P.describe({kind: 'unit', key: 'g0,2'}), /吃剩的东西.*每秒回复生命/s);
    assert.match(P.describe({kind: 'shop', key: 0}), /3 金.*双击招募/s);
    assert.match(P.describe({kind: 'enemy', key: 'g0,1'}), /敌方.*大岩蛇|大岩蛇[\s\S]*敌方/);
    assert.match(P.describe({kind: 'item', key: 'metronome'}), /节拍器[\s\S]*同目标叠攻速[\s\S]*小拳石 › 波波/);
    assert.match(P.describe({kind: 'tm', key: 'cut'}), /居合斩[\s\S]*推荐[\s\S]*皮卡丘/);
    assert.match(P.describe({kind: 'bond', key: '电'}), /电系招式附带麻痹/);
    assert.match(P.describe({kind: 'term', key: '共鸣'}), /2 件 \/ 4 件/);
    // Hover: one floating card after HOVER_MS, no section rebuild, no network.
    const before = p.element('bench').children[0];
    await fire(p, 'pointerover', tile(p, 'b0'), {pointerType: 'mouse'});
    assert.equal(p.document.getElementById('pv-card'), null, 'waits for the hover delay');
    await p.expireTimeouts(P.HOVER_MS);
    const card = p.document.getElementById('pv-card');
    assert.equal(card.hidden, false);
    assert.match(card.textContent, /电击/);
    assert.equal(p.element('bench').children[0], before, 'bench untouched');
    await fire(p, 'pointerout', tile(p, 'b0'), {pointerType: 'mouse', relatedTarget: p.element('fight-button')});
    assert.equal(card.hidden, true);
    // Touch pointerover never opens it.
    await fire(p, 'pointerover', tile(p, 'b0'), {pointerType: 'touch'});
    await p.expireTimeouts(P.HOVER_MS);
    assert.equal(card.hidden, true);
    // Selection info strip: the hint line shows the native skill with glossary terms.
    await p.click(tile(p, 'b0'));
    const hint = p.element('tutorial-hint');
    assert.match(hint.textContent, /皮卡丘.*本命「电击」.*特性「静电」/);
    assert.ok(hint.querySelector('.gl-term'), 'keywords are explained inline');
    assert.match(p.document.querySelector('.hint-step').textContent, /双击上场 · 再点取消/);
    assert.equal(p.events.fetches.length, 1);
    p.unchanged();
  },

  async guide() {
    const p = await page(fixture(), recorder().options);
    const G = p.window.PlayGuide;
    // First prep screen: auto-start after a short delay.
    assert.equal(G.step(), -1);
    await p.expireTimeouts(600);
    assert.equal(G.step(), 0);
    const bubble = () => p.document.getElementById('guide-bubble');
    assert.match(bubble().textContent, /新手引导 1 \/ 5.*招募伙伴/);
    const press = async (action) => { const b = bubble().querySelector(`[data-guide="${action}"]`); b.dispatchEvent({type: 'click', target: b}); await settle(p); };
    await press('next');
    assert.match(bubble().textContent, /2 \/ 5.*上场布阵/);
    await press('prev');
    assert.equal(G.step(), 0);
    await press('skip');
    assert.equal(G.step(), -1);
    assert.equal(bubble().hidden, true);
    const stored = new Map(JSON.parse(p.snapshot()).storage);
    assert.equal(stored.get(G.KEY), 'done', 'skipping is remembered');
    // Re-open from the "?" button; Esc closes it.
    await p.click(p.element('guide-button'));
    assert.equal(G.step(), 0);
    await fire(p, 'keydown', p.element('guide-button'), {key: 'Escape', code: 'Escape'});
    assert.equal(G.step(), -1);
    // Steps 1–2 advance by themselves once done (owned count / board count grows).
    await p.click(p.element('guide-button'));
    p.window.PlayGuide.render({state: {...p.fixture, bench: [...p.fixture.bench, p.fixture.bench[0]]}, playable: () => true});
    assert.equal(G.step(), 1, 'buying advances the recruit step');
    G.finish();
    // A returning player (flag stored) never gets the auto-start.
    const fx = fixture();
    const q = await page(fx, {...recorder().options, window: {localStorage: {getItem: (k) => k === G.KEY ? 'done' : null, setItem() {}}}});
    await q.expireTimeouts(600);
    assert.equal(q.window.PlayGuide.step(), -1);
  },
};

(async () => {
  assert.ok(cases[scenario], `Unknown scenario ${scenario}`);
  await cases[scenario]();
})().catch((error) => {console.error(error); process.exitCode = 1;});
