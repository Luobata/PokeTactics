/* Prep moments (docs/62) through the shipped handlers: augment pick, machine
 * targeting + confirm, recipe board, equip ranking + preview, skill-mod choice,
 * native skill card + learn socket. No server; mutations are recorded.
 * usage: node play_interactions_presentation.js <play_layout.js> <play_interactions.js> <play.js> <play.html> <scenario> */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const [layoutPath, interactionsPath, playPath, htmlPath, scenario] = process.argv.slice(2);
const combined = path.join(os.tmpdir(), `play_interactions_combined_${process.pid}.js`);
fs.writeFileSync(combined, [layoutPath, interactionsPath, playPath].map((file) => fs.readFileSync(file, 'utf8')).join('\n;\n'));
process.on('exit', () => fs.rmSync(combined, {force: true}));
process.argv[2] = combined;
process.argv[3] = htmlPath;
const {page, stateFixture} = require('./battle_report_presentation.js');

function unit(uid, name, extra = {}) {
  return {uid, sid: 25, name, star: 1, range: 1, ranged: false, types: ['电'], bonds: [], role_key: 'attack',
    sell: 1, learnable: true, native_skill: {name: '电击', type: '电', description: '放电。', tags: ['单体']}, ...extra};
}
function fixture(options = {}) {
  const s = stateFixture({round: 7});
  s.you.gold = 6;
  s.board[0][2] = unit('front', '小拳石', {role_key: 'defense'});
  s.board[2][4] = unit('back', '幸福蛋', {role_key: 'support', ranged: true, range: 3,
    technique: {id: 'rest', name: '睡觉', description: '回复。'}});
  s.bench = [unit('bench1', '皮卡丘')];
  s.you.on_board = 2;
  s.items = {components: [{key: 'band', name: '力量头带', n: 2}], finished: [{key: 'metronome', name: '节拍器', effect: '普攻叠攻速'}], craftable: []};
  s.techniques = [{id: 'cut', name: '居合斩', description: '追加斩击。', cost: 2, count: 1},
    {id: 'surf', name: '冲浪', description: '水浪。', cost: 2, count: 0}];
  s.augments = {pending: options.augments === false ? [] : [{id: 'augment-r7', round: 7, rerolled: false, options: [
    {id: 'charge_horn', name: '冲锋号', brief: '近战冲锋', description: '开战冲锋说明'},
    {id: 'interest_master', name: '理财专家', brief: '利息上限 5 → 8', description: '理财说明'},
    {id: 'poison_catalyst', name: '毒性催化', brief: '条件触发', description: '毒说明'}]}],
    selected: [{id: 'mana_siphon', name: '能量虹吸', description: '施放本命后邻格回能。'}]};
  if (options.depth) s.depth = {simulations_left: 0, items: {unequip_cost: 1, dismantle_cost: 1, sell_value: 2}};
  if (options.mod) s.board[0][2] = {...s.board[0][2], star: 2, mod_options: [{id: 'amplify', name: '强化'}, {id: 'spread', name: '扩散'}]};
  const mods = options.mod ? [{id: 'amplify', name: '强化', delta: '伤害·治疗 +30%', description: '强化说明'},
    {id: 'spread', name: '扩散', delta: '邻格 35% 溅射', description: '扩散说明'}] : [];
  s.interactions = {version: 1,
    augments: {pending: options.augments === false ? [] : [{id: 'augment-r7', round: 7, rarity: 'gold', rarity_name: '金', rerolls_left: 1, options: [
      {id: 'charge_horn', category: 'battle', category_name: '战斗', tags: ['近战'], score: 3, fit: 'high', best: true,
        reasons: [{text: '你有 3 只近战 → 全员触发', good: true}], changes: ['3 只近战开战冲锋'], condition: null},
      {id: 'interest_master', category: 'economy', category_name: '经济', tags: ['经济'], score: 1.5, fit: 'mid', best: false,
        reasons: [{text: 'Lv.3，经济收益还能滚很多轮', good: true}], changes: ['利息上限 5 → 8（现有 6 金：+0 → +0）'], condition: null},
      {id: 'poison_catalyst', category: 'condition', category_name: '条件', tags: [], score: 0.5, fit: 'low', best: false,
        reasons: [{text: '条件未满足：队里没有能施毒的本命', good: false}], changes: [], condition: {met: false, text: '队里没有能施毒的本命'}}]}],
      selected: [{id: 'mana_siphon', category: 'battle', category_name: '战斗', last: {round: 6, rows: [{triggers: 4, energy: 48}]}}]},
    techniques: {
      cut: {category: 'damage', category_name: '伤害', compatible: ['front', 'bench1'], known_by: [], cost: 2, count: 1,
        best: {uid: 'front', name: '小拳石', score: 3, reasons: ['伤害招式最适合攻击型'], replaces: null}},
      surf: {category: 'damage', category_name: '伤害', compatible: [], known_by: [], cost: 2, count: 0, best: null}},
    skills: {front: {category: 'shield', category_name: '护盾', glyph: '⛨', power: 40, targeting: 'ally', targeting_name: '友方', tags: [], technique: null, mods},
      back: {category: 'heal', category_name: '治疗', glyph: '✚', power: 0, targeting: 'ally', targeting_name: '友方', tags: [], technique: '睡觉', mods: []},
      bench1: {category: 'chain', category_name: '连锁', glyph: '⌁', power: 50, targeting: 'enemy', targeting_name: '敌方', tags: [], technique: null, mods: []}},
    recipes: {components: ['band', 'hardstone', 'magnet', 'shoes', 'bell', 'charcoal', 'mysticwater', 'spark']
      .map((key) => ({key, name: {band: '力量头带', hardstone: '硬石头', magnet: '磁铁线圈', shoes: '加速鞋', bell: '贝壳铃', charcoal: '木炭', mysticwater: '神秘水滴', spark: '雷之石碎片'}[key], n: key === 'band' ? 2 : 0, stats: ''})),
      cells: [
        {a: 'band', b: 'band', item: 'metronome', name: '节拍器', depth: false, dead: false, craftable: true, blocked: false, missing: [], stats: [], effect: '普攻叠攻速'},
        {a: 'band', b: 'magnet', item: 'choice_band', name: '专爱头巾', depth: false, dead: false, craftable: false, blocked: false, missing: ['磁铁线圈'], stats: [], effect: '攻击 +35%'},
        {a: 'magnet', b: 'shoes', item: null, name: null, depth: false, dead: true, craftable: false, blocked: false, missing: ['磁铁线圈', '加速鞋'], stats: [], effect: ''}]},
    equip: {unequip_cost: options.depth ? 1 : 0,
      items: {metronome: {name: '节拍器', lines: [], stats: ['攻击 +16%'], effect: '普攻叠攻速', recipe: '力量头带 + 力量头带',
        carriers: [{uid: 'bench1', name: '皮卡丘', score: 3, reason: '攻击型 · 攻击型普攻叠攻速 · 在备战席', free: true},
          {uid: 'front', name: '小拳石', score: 1.5, reason: '防守型 · 通用', free: true}], suits: '攻击型普攻叠攻速'}},
      slots: {front: {total: 1, used: 0, items: []}, back: {total: 1, used: 1, items: [{key: 'leftovers', name: '剩饭', lines: ['每秒回复最大生命 1.5%'], stats: []}]},
        bench1: {total: 1, used: 0, items: []}}},
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
const sheetOpen = (p) => p.element('ix-sheet').hidden === false;

function adviceFixture() {
  const s = fixture({augments: false});
  s.items.finished = [{key: 'metronome', name: '节拍器', effect: '普攻叠攻速'}, {key: 'taunt_bell', name: '挑衅铃', effect: '开战嘲讽'}];
  s.interactions.equip.items.taunt_bell = {name: '挑衅铃', lines: [], stats: [], effect: '开战嘲讽', recipe: '硬石头 + 硬石头',
    carriers: [{uid: 'front', name: '小拳石', score: 3, reason: '防守型 · 前排嘲讽', free: true}], suits: '前排嘲讽'};
  s.interactions.item_advice = {
    suggestions: [
      {action: 'equip', item: 'metronome', name: '节拍器', uid: 'bench1', unit: '皮卡丘', value: 5, why: ['攻击型普攻叠攻速', '电 4 电弧'], archetype: '输出'},
      {action: 'craft', item: 'metronome', name: '节拍器', uid: 'front', unit: '小拳石', value: 4, why: ['叠攻速'], archetype: '输出', recipe: ['力量头带', '力量头带']},
      {action: 'chase', item: 'choice_band', name: '专爱头巾', uid: 'bench1', unit: '皮卡丘', value: 3, why: ['输出'], archetype: '输出', recipe: ['力量头带', '磁铁线圈'], lacking: '磁铁线圈'}],
    guides: {
      metronome: {archetype: '输出', playstyle: '同目标叠攻速', active: ['电 4 电弧'], missing: ['连击'], mechanic: true, treasure: false},
      taunt_bell: {archetype: '坦克', playstyle: '开战嘲讽并减伤', active: [], missing: ['钢 2 反甲'], mechanic: true, treasure: false},
      choice_band: {archetype: '输出', playstyle: '攻击 +35%', active: [], missing: [], mechanic: false, treasure: false}},
    team_archetypes: {输出: 2}, archetype_order: ['输出', '坦克', '控制', '联动', '辅助', '经济']};
  return s;
}

const cases = {
  async itemAdvice() {
    const rec = recorder();
    const p = await page(adviceFixture(), rec.options);
    const box = p.element('ix-advice');
    assert.equal(box.hidden, false);
    const cards = box.querySelectorAll('article');
    assert.equal(cards.length, 3);
    assert.match(cards[0].textContent, /给 皮卡丘/);
    assert.match(cards[0].textContent, /电 4 电弧/);
    assert.match(cards[1].textContent, /力量头带 \+ 力量头带 → 给 小拳石/);
    assert.match(cards[2].textContent, /差 磁铁线圈/);
    assert.match(box.querySelector('.ix-team-arch').textContent, /缺少坦克、控制道具/);
    // Item cards: archetype, mechanic badge, playstyle, active / missing combos, filter chips.
    const items = p.element('ix-items');
    assert.equal(items.querySelectorAll('article').length, 2);
    assert.match(items.textContent, /同目标叠攻速/);
    assert.match(items.querySelector('.ix-combos').textContent, /✓电 4 电弧.*还差：连击/s);
    assert.ok(items.querySelector('.ix-kind.mech'));
    const filter = p.element('ix-item-filter');
    assert.equal(filter.hidden, false);
    await p.click(filter.querySelector('[data-ix-arch="坦克"]'));
    assert.equal(p.element('ix-items').querySelectorAll('article').length, 1);
    assert.match(p.element('ix-items').textContent, /挑衅铃/);
    await p.click(p.element('ix-item-filter').querySelector('[data-ix-arch=""]'));
    assert.equal(p.element('ix-items').querySelectorAll('article').length, 2);
    // Equip advice → the usual confirm sheet → equip on the suggested unit.
    await p.click(box.querySelector('[data-ix-advice="equip"]'));
    assert.equal(p.element('ix-sheet').hidden, false);
    assert.match(p.element('ix-sheet-body').textContent, /皮卡丘/);
    await p.click(p.element('ix-sheet-body').querySelector('[data-ix-confirm-equip]'));
    const equip = rec.calls.find((c) => c.cmd === 'equip');
    assert.deepEqual([equip.item, equip.loc], ['metronome', 'b0']);
    // Chase highlights the recipe and the missing component.
    await p.click(p.element('ix-advice').querySelector('[data-ix-advice="chase"]'));
    const recipes = p.element('ix-recipes');
    assert.match(recipes.querySelector('.ix-chase-note').textContent, /专爱头巾.*磁铁线圈/s);
    assert.ok(recipes.querySelector('[data-ix-cell="band|magnet"]').classList.contains('ix-chase'));
    assert.ok(recipes.querySelector('[data-ix-comp="magnet"]').classList.contains('ix-chase'));
    // Equip targeting shows the item's active combos.
    await p.click(p.element('ix-items').querySelector('[data-ix-equip="metronome"]'));
    assert.match(p.element('ix-target-bar').textContent, /✓ 电 4 电弧/);
  },

  async itemAdviceCraft() {
    const rec = recorder();
    const p = await page(adviceFixture(), rec.options);
    await p.click(p.element('ix-advice').querySelector('[data-ix-advice="craft"]'));
    assert.deepEqual(rec.calls.map((c) => [c.cmd, c.item]), [['craft', 'metronome']]);
    assert.equal(p.element('ix-sheet').hidden, false, 'after crafting the equip sheet for the suggested unit opens');
    assert.match(p.element('ix-sheet-body').textContent, /刚合成/);
    await p.click(p.element('ix-sheet-body').querySelector('[data-ix-confirm-equip]'));
    const equip = rec.calls.find((c) => c.cmd === 'equip');
    assert.deepEqual([equip.item, equip.loc], ['metronome', 'g0,2'], 'equips onto the suggested unit');
  },

  async augmentMoment() {
    const rec = recorder();
    const p = await page(fixture(), rec.options);
    const overlay = p.element('ix-augment');
    assert.equal(overlay.hidden, false, 'a pending augment opens the pick moment');
    assert.ok(overlay.classList.contains('rarity-gold'));
    const cards = p.element('ix-augment-cards').querySelectorAll('article');
    assert.equal(cards.length, 3);
    assert.ok(cards[0].classList.contains('best'));
    assert.ok(cards[0].classList.contains('fit-high'));
    assert.match(cards[0].textContent, /你有 3 只近战/);
    assert.match(cards[0].textContent, /3 只近战开战冲锋/);
    assert.match(cards[2].textContent, /触发条件：未满足/);
    assert.match(p.element('ix-augment-reroll').textContent, /剩 1 次/);
    await p.click(overlay.querySelector('[data-ix-augment-later]'));
    assert.equal(overlay.hidden, true, '先看看棋盘 defers the moment');
    assert.equal(p.element('hud-augment').hidden, false, 'a chip brings it back');
    await p.click(p.element('hud-augment'));
    assert.equal(overlay.hidden, false);
    // Picking goes through the established claim handler.
    await p.click(p.element('ix-augment-cards').querySelector('[data-augment="charge_horn"]'));
    assert.deepEqual([rec.calls[0].cmd, rec.calls[0].id, rec.calls[0].choice], ['claim_augment', 'augment-r7', 'charge_horn']);
    // The selected strip opens details with last-battle ledger numbers.
    const badge = p.element('ix-augment-strip').querySelector('[data-ix-augment-info="mana_siphon"]');
    assert.ok(badge);
    await p.click(badge);
    assert.ok(sheetOpen(p));
    assert.match(p.element('ix-sheet-body').textContent, /触发 4 次/);
    assert.match(p.element('ix-sheet-body').textContent, /能量 48/);
  },

  async tmTargeting() {
    const rec = recorder();
    const p = await page(fixture({augments: false}), rec.options);
    const rack = p.element('ix-tm-rack');
    const cut = rack.querySelector('[data-ix-tm="cut"]');
    assert.match(cut.textContent, /推荐 小拳石/);
    assert.equal(rack.querySelector('[data-ix-tm="surf"]').disabled, true, 'no compatible learner');
    await p.click(cut);
    assert.ok(p.document.body.classList.contains('ix-targeting'));
    assert.ok(tile(p, 'g0,2').classList.contains('ix-valid'));
    assert.ok(tile(p, 'g0,2').classList.contains('ix-best'));
    assert.ok(tile(p, 'g0,2').querySelector('.ix-rank'));
    assert.ok(tile(p, 'g2,4').classList.contains('ix-dim'), 'incompatible units grey out');
    assert.ok(tile(p, 'b0').classList.contains('ix-valid'));
    assert.equal(p.element('ix-target-bar').hidden, false);
    await p.click(tile(p, 'g2,4'));
    assert.match(p.element('ix-target-bar').textContent, /幸福蛋 学不了/);
    await p.click(tile(p, 'g0,2'));
    assert.ok(sheetOpen(p), 'tapping a lit unit opens the confirm sheet');
    const body = p.element('ix-sheet-body').textContent;
    assert.match(body, /空插槽/);
    assert.match(body, /消耗 1 台技能机/);
    assert.match(body, /推荐人选/);
    await p.click(p.element('ix-sheet-body').querySelector('[data-ix-confirm-learn]'));
    const learn = rec.calls.find((call) => call.cmd === 'learn');
    assert.deepEqual([learn.loc, learn.technique], ['g0,2', 'cut']);
  },

  async recipeBoard() {
    const rec = recorder();
    const p = await page(fixture({augments: false}), rec.options);
    const board = p.element('ix-recipes');
    const craftable = board.querySelectorAll('.craftable');
    assert.equal(craftable.length, 1, 'only band + band is craftable');
    assert.equal(craftable[0].getAttribute('data-ix-cell'), 'band|band');
    const near = board.querySelector('[data-ix-cell="band|magnet"]');
    assert.ok(near.classList.contains('near'));
    assert.match(near.textContent, /差1/);
    assert.ok(board.querySelector('[data-ix-cell="magnet|shoes"]').classList.contains('dead'));
    await p.click(near);
    assert.match(p.element('ix-sheet-body').textContent, /还差：磁铁线圈/);
    assert.equal(p.element('ix-sheet-body').querySelector('[data-ix-confirm-craft]').disabled, true);
    await p.click(craftable[0]);
    await p.click(p.element('ix-sheet-body').querySelector('[data-ix-confirm-craft]'));
    assert.deepEqual(rec.calls.map((call) => [call.cmd, call.item]), [['craft', 'metronome']]);
  },

  async equipPreview() {
    const rec = recorder();
    const p = await page(fixture({augments: false, depth: true}), rec.options);
    const card = p.element('ix-items').querySelector('article');
    assert.match(card.textContent, /适合：攻击型普攻叠攻速/);
    assert.match(card.textContent, /推荐 皮卡丘 › 小拳石/);
    assert.match(card.textContent, /组件 攻击 \+16%/);
    await p.click(card.querySelector('[data-ix-equip="metronome"]'));
    assert.match(tile(p, 'b0').querySelector('.ix-rank').textContent, /1/);
    assert.match(tile(p, 'g0,2').querySelector('.ix-rank').textContent, /2/);
    assert.ok(tile(p, 'g2,4').classList.contains('ix-dim'), 'a full slot cannot take more');
    await p.click(tile(p, 'b0'));
    const body = p.element('ix-sheet-body').textContent;
    assert.match(body, /推荐 #1/);
    assert.match(body, /装备位 0\/1/);
    assert.match(body, /装备后 1\/1/);
    await p.click(p.element('ix-sheet-body').querySelector('[data-ix-confirm-equip]'));
    const call = rec.calls.find((row) => row.cmd === 'equip');
    assert.deepEqual([call.item, call.loc], ['metronome', 'b0']);
  },

  async skillMod() {
    const rec = recorder();
    const p = await page(fixture({augments: false, depth: true, mod: true}), rec.options);
    assert.ok(sheetOpen(p), 'a pending star-up mod opens its choice');
    const body = p.element('ix-sheet-body');
    assert.equal(body.querySelectorAll('[data-ix-mod]').length, 2);
    assert.match(body.textContent, /伤害·治疗 \+30%/);
    await p.click(body.querySelector('[data-ix-mod-later]'));
    assert.equal(sheetOpen(p), false, '稍后 defers it');
    await p.click(p.element('stage-dock').querySelector('[data-open-panel="bonds"]'));
    assert.equal(sheetOpen(p), false, 'stays deferred across renders');
    assert.ok(tile(p, 'g0,2'), 'the unit stays on the board');
  },

  async skillModPick() {
    const rec = recorder();
    const p = await page(fixture({augments: false, depth: true, mod: true}), rec.options);
    await p.click(p.element('ix-sheet-body').querySelector('[data-ix-mod="spread"]'));
    const call = rec.calls.find((row) => row.cmd === 'choose_mod');
    assert.deepEqual([call.loc, call.mod], ['g0,2', 'spread']);
  },

  async skillCard() {
    const p = await page(fixture({augments: false}));
    await p.click(tile(p, 'g2,4'));
    const detail = p.element('unit-detail');
    assert.match(detail.querySelector('.ix-skill-card').textContent, /治疗/);
    const socket = detail.querySelector('[data-ix-socket="back"]');
    assert.match(socket.textContent, /更换技能机/);
    await new Promise((resolve) => setTimeout(resolve, 400));  // a slow second click deselects; a fast one is a double-click
    await p.click(tile(p, 'g2,4'));
    await p.click(tile(p, 'g0,2'));
    const front = p.element('unit-detail');
    assert.match(front.querySelector('.ix-skill-card').textContent, /护盾 · 威力 40 · 目标 友方/);
    await p.click(front.querySelector('[data-ix-socket="front"]'));
    assert.ok(sheetOpen(p));
    assert.ok(p.element('ix-sheet-body').querySelector('[data-ix-socket-pick="cut"]'), 'compatible machine listed');
    assert.equal(p.element('ix-sheet-body').querySelector('[data-ix-socket-pick="surf"]'), null);
    await p.click(p.element('ix-sheet-body').querySelector('[data-ix-socket-pick="cut"]'));
    assert.match(p.element('ix-sheet-body').textContent, /学习位 · 现在/);
    p.unchanged();
  },
};

(async () => {
  assert.ok(cases[scenario], `Unknown scenario ${scenario}`);
  await cases[scenario]();
})().catch((error) => {console.error(error); process.exitCode = 1;});
