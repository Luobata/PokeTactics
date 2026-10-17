/* Exercise the shipped play handlers using immutable snapshots, no real saves. */
const assert = require('node:assert/strict');
const {page, stateFixture, clone} = require('./battle_report_presentation.js');
const componentIds = ['sash', 'band', 'magnet', 'charcoal', 'bell', 'shoes', 'stone', 'lens'];
const reward = (id = 'supply3') => ({id, round: 3, seat: 0, status: 'pending', choice: null,
  options: componentIds.map(key => ({id: key, name: `材料 ${key}`, recipe_details: key === 'band'
    ? [{id: 'metronome', name: '节拍器', recipes: [['band', 'band']]}]
    : key === 'bell' ? [{id: 'lucky_egg', name: '幸运蛋', recipes: [['band', 'bell']]}]
    : key === 'charcoal' ? [{id: 'contagion_orb', name: '扩散宝珠', recipes: [['shoes', 'charcoal']]}] : []}))});
(async () => {
  const base = stateFixture({round: 4});
  base.items.components = [{key: 'band', name: '力量头带', n: 1}];
  base.component_choices = [reward()];
  base.combinations = {entries: [
    {id: 'native_energy', name: '本命充能接力', stage: 'base', status: 'ready', detail: '本命实际回能', units: [], missing: [], present: ['已上场水、电伙伴'], battle_conditions: ['同目标真实命中'], conflicts: ['一次湿润只消费一次']},
    {id: 'native_inspiration', name: '充能鼓舞', stage: 'upgrade', status: 'missing', detail: '需要海克斯的转化', units: [], missing: ['尚未选择充能鼓舞海克斯']},
    {id: 'trait_sheer_force', name: '强行', stage: 'trait', source_kind: 'trait', status: 'ready', detail: '放弃追加异常', present: ['已选择：尼多王 · 强行'], missing: [], battle_conditions: ['适用的直接进攻动作'], conflicts: ['与毒刺互斥']},
  ]};
  base.bonds = {entries: [{id: 'bond_combo', name: '连击', category: 'tactic', n: 1, tier: 0,
    next: 2, need: 1, effect: '还需一位不同伙伴', candidates: [212, 34, 26]}], note: '只计上场的不同物种'};
  base.arena.catalog = [{sid: 212, name: '巨钳螳螂'}, {sid: 34, name: '尼多王'}, {sid: 26, name: '雷丘'}];
  base.bench = [{sid: 34, uid: 'unit34', name: '尼多王', range: 1, types: ['毒'], bonds: ['bond_erosion', 'bond_combo'], role_key: 'attack'}];
  base.arena.bond_catalog = [{id: 'bond_erosion', name: '侵蚀'}, {id: 'bond_combo', name: '连击'}];
  const p = await page(base);
  assert.equal(p.element('component-choices').hidden, false);
  const choices = p.element('component-choices').querySelectorAll('[data-component-choice]');
  assert.equal(choices.length, 8); assert.ok(choices.every(button => !button.disabled));
  assert.match(choices.find(button => button.dataset.componentChoice === 'band').textContent, /领取后可合成：节拍器/);
  assert.doesNotMatch(choices.find(button => button.dataset.componentChoice === 'charcoal').textContent, /领取后可合成/);
  assert.match(p.element('combination-count').textContent, /1 条基础配合已具备 · 0 项补强已具备/);
  assert.match(p.element('combinations').querySelector('.base').textContent, /配置已具备/);
  assert.match(p.element('combinations').querySelector('.upgrade').textContent, /尚缺配置/);
  const facts = p.element('combinations').querySelector('.base');
  assert.match(facts.textContent, /已具备.*已上场水、电伙伴/s);
  assert.match(facts.textContent, /需战斗时机 \/ 对手条件.*同目标真实命中/s);
  assert.match(facts.textContent, /互斥 \/ 取舍.*一次湿润只消费一次/s);
  assert.match(p.element('combinations').querySelector('.upgrade').textContent, /缺组件 \/ 配置.*尚未选择充能鼓舞海克斯/s);
  assert.match(p.element('combinations').querySelector('.trait').textContent, /已选择 · 条件触发/);
  assert.match(p.element('combinations').querySelector('.trait').textContent, /尼多王 · 强行/);
  const candidates = p.element('synergy-list').querySelector('.bond-candidates').querySelectorAll('a');
  assert.match(candidates[0].textContent, /尼多王.*备战席/);
  await p.click(p.element('bench').querySelector('[data-loc="b0"]'));
  assert.match(p.element('unit-detail').textContent, /所属羁绊.*侵蚀.*连击/s);
  assert.doesNotMatch(p.element('unit-detail').textContent, /bond_erosion/);
  assert.equal(p.events.fetches.length, 1); p.unchanged();

  const battle = clone(base); battle.phase = 'battle'; battle.bench = [];
  const b = await page(battle);
  const unavailable = b.element('component-choices').querySelectorAll('[data-component-choice]');
  assert.ok(unavailable.every(button => button.disabled));
  assert.match(b.element('component-choices').textContent, /下一准备期可领取/);
  for (const handler of b.document.listeners.click || []) await handler({target: unavailable[0]});
  assert.equal(b.events.fetches.length, 1); b.unchanged();

  const claimed = clone(base); claimed.component_choices[0].status = 'claimed'; claimed.component_choices[0].choice = 'band';
  const c = await page(claimed);
  assert.equal(c.element('component-choices').querySelectorAll('[data-component-choice]').length, 0);
  assert.match(c.element('component-choices').textContent, /已领取 材料 band/); c.unchanged();

  const capped = clone(base); capped.items.crafting_blocked = ['lucky_egg'];
  const capPage = await page(capped);
  const egg = capPage.element('component-choices').querySelector('[data-component-choice="bell"]');
  assert.match(egg.textContent, /可合成：幸运蛋/);
  assert.doesNotMatch(egg.textContent, /领取后可合成/);
  capPage.unchanged();

  const nextState = clone(claimed); nextState.save.sequence++;
  const mutations = [];
  const active = await page(clone(base), {mutationResponder: query => {
    assert.equal(query.get('cmd'), 'claim_component'); assert.equal(query.get('reward_id'), 'supply3');
    assert.equal(query.get('choice'), 'band'); assert.equal(query.get('expected_sequence'), '99');
    mutations.push(query.toString()); return {ok: true, sid: base.sid, state: nextState};
  }});
  await active.click(active.element('component-choices').querySelector('[data-component-choice="band"]'));
  assert.equal(mutations.length, 1); assert.equal(active.events.fetches.length, 2);
  assert.match(active.element('component-choices').textContent, /已领取 材料 band/);
  assert.equal(active.element('component-choices').querySelectorAll('[data-component-choice]').length, 0);
  active.unchanged();
})().catch(error => {console.error(error); process.exitCode = 1;});
