/* Shop cards preview details first; recruiting stays an explicit detail action. */
const assert = require('node:assert/strict');
const {page, stateFixture, clone} = require('./battle_report_presentation.js');

function shopPiece(sid, name, price, extra = {}) {
  return {sid, name, tier: price, price, star: 1, shiny: false, range: 1, ranged: false,
    types: ['火'], colors: ['#f08030'], role_key: 'attack', role_description: '冲在最前面输出。',
    native_skill: {name: '火花', type: '火', description: '吐出火花灼烧对手。', tags: ['单体']},
    trait: {id: 'trait_guts', name: '毅力', description: '异常时攻击提高。'},
    bonds: [], learnable: [], ...extra};
}
function shopFixture() {
  const fixture = stateFixture({round: 1});
  fixture.shop = [shopPiece(4, '小火龙', 3), null,
    shopPiece(7, '杰尼龟', 2, {types: ['水'], colors: ['#6890f0']})];
  fixture.bench = [{sid: 34, uid: 'unit34', name: '尼多王', range: 1, types: ['毒'], bonds: [], role_key: 'attack'}];
  return fixture;
}
const card = (p, i) => p.element('shop').querySelector(`[data-shop="${i}"]`);
(async () => {
  // Clicking a card only previews; the detail panel carries the recruit action.
  const p = await page(shopFixture());
  assert.equal(p.element('shop').querySelectorAll('[data-shop]').length, 2, 'Sold slots stay unclickable');
  assert.equal(card(p, 0).querySelector('.shop-stock'), null, 'No pool fields, no stock badge');
  await p.click(card(p, 0));
  assert.equal(p.events.fetches.length, 1, 'Previewing a card must not call the buy API');
  assert.ok(card(p, 0).classList.contains('selected'));
  assert.equal(card(p, 0).getAttribute('aria-pressed'), 'true');
  const detail = p.element('unit-detail');
  assert.equal(detail.textContent.includes('共享池剩余'), false, 'No pool fields, no stock line');
  for (const copy of ['小火龙', '3 费', '冲在最前面输出', '火花', '吐出火花灼烧对手', '毅力', '异常时攻击提高'])
    assert.match(detail.textContent, new RegExp(copy));
  const recruit = detail.querySelector('[data-shop-buy="0"]');
  assert.ok(recruit, 'Detail panel must carry the recruit button');
  assert.equal(recruit.disabled, false);
  assert.equal(recruit.getAttribute('aria-label'), '招募小火龙，3金币');
  assert.ok(detail.querySelector('[data-action="cancel-select"]'));
  assert.match(p.element('tutorial-hint').textContent, /已选中商店伙伴/);
  // Shop selection and board/bench selection are mutually exclusive.
  await p.click(p.element('bench').querySelector('[data-loc="b0"]'));
  assert.match(p.element('unit-detail').textContent, /尼多王/);
  assert.equal(card(p, 0).classList.contains('selected'), false);
  assert.equal(p.element('shop').querySelector('[aria-pressed="true"]'), null);
  await p.click(card(p, 2));
  assert.match(p.element('unit-detail').textContent, /杰尼龟/);
  assert.equal(p.element('bench').querySelector('[data-loc="b0"]').classList.contains('selected'), false);
  assert.equal(card(p, 2).getAttribute('aria-pressed'), 'true');
  // Cancel clears the preview without any mutation.
  await p.click(p.element('unit-detail').querySelector('[data-action="cancel-select"]'));
  assert.match(p.element('unit-detail').innerHTML, /empty-detail/);
  assert.equal(p.element('shop').querySelector('[aria-pressed="true"]'), null);
  assert.equal(p.events.fetches.length, 1);
  p.unchanged();

  // Short gold dims the card but still opens the preview; only recruiting is blocked.
  const poor = shopFixture();
  poor.you.gold = 1;
  const q = await page(poor);
  assert.equal(card(q, 0).disabled, false, 'Unaffordable cards must stay clickable for preview');
  assert.ok(card(q, 0).classList.contains('unaffordable'));
  await q.click(card(q, 0));
  const blocked = q.element('unit-detail').querySelector('[data-shop-buy="0"]');
  assert.equal(blocked.disabled, true);
  assert.match(q.element('unit-detail').textContent, /金币不足，还差 2 金币/);
  assert.equal(blocked.getAttribute('aria-label'), '招募小火龙，3金币，金币不足，还差 2 金币');
  await q.click(card(q, 0));
  assert.equal(q.events.fetches.length, 1, 'Re-clicking an unaffordable card never buys');
  assert.ok(card(q, 0).classList.contains('selected'), 'Unaffordable re-click keeps the preview open');
  q.unchanged();
  // Outside the prep phase the preview still opens but recruiting is explained and disabled.
  const battling = shopFixture();
  battling.phase = 'battle';
  const b = await page(battling);
  await b.click(card(b, 2));
  const phased = b.element('unit-detail').querySelector('[data-shop-buy="2"]');
  assert.equal(phased.disabled, true);
  assert.match(b.element('unit-detail').textContent, /准备阶段才能招募/);
  assert.equal(b.events.fetches.length, 1);
  b.unchanged();

  // The detail recruit button buys once and clears the selection afterwards.
  const buying = shopFixture();
  const bought = clone(buying);
  bought.shop = [null, null, bought.shop[2]];
  bought.you.gold = 20;
  bought.save.sequence = 100;
  const buys = [];
  const r = await page(buying, {mutationResponder: query => {
    assert.equal(query.get('cmd'), 'buy');
    buys.push(query.get('i'));
    return {ok: true, sid: buying.sid, state: bought};
  }});
  await r.click(card(r, 0));
  await r.click(r.element('unit-detail').querySelector('[data-shop-buy="0"]'));
  assert.deepEqual(buys, ['0']);
  assert.equal(r.element('shop').querySelector('[data-shop="0"]'), null, 'Bought slot becomes a sold tile');
  assert.match(r.element('shop').textContent, /伙伴已加入/);
  assert.match(r.element('unit-detail').innerHTML, /empty-detail/, 'Buying clears the shop selection');
  r.unchanged();

  // Re-clicking the selected card keeps the old one-tap habit: it buys directly.
  const quick = shopFixture();
  const settled = clone(quick);
  settled.shop = [null, null, settled.shop[2]];
  settled.you.gold = 20;
  settled.save.sequence = 100;
  const taps = [];
  const d = await page(quick, {mutationResponder: query => {
    assert.equal(query.get('cmd'), 'buy');
    taps.push(query.get('i'));
    return {ok: true, sid: quick.sid, state: settled};
  }});
  await d.click(card(d, 0));
  await d.click(card(d, 0));
  assert.deepEqual(taps, ['0'], 'The second tap on a selected card buys it');
  assert.equal(d.element('shop').querySelector('[aria-pressed="true"]'), null);
  d.unchanged();

  // A refresh replacing the shop clears a selection whose slot content is gone.
  const rerolling = shopFixture();
  const rolled = clone(rerolling);
  rolled.shop = [shopPiece(19, '小拉达', 1), null, rolled.shop[2]];
  rolled.you.gold = 21;
  rolled.save.sequence = 100;
  const s = await page(rerolling, {mutationResponder: query => {
    assert.equal(query.get('cmd'), 'refresh');
    return {ok: true, sid: rerolling.sid, state: rolled};
  }});
  await s.click(card(s, 0));
  assert.match(s.element('unit-detail').textContent, /小火龙/);
  await s.click(s.element('refresh-button'));
  assert.equal(s.element('shop').querySelector('[aria-pressed="true"]'), null, 'Refreshing the shop clears the selection');
  assert.match(s.element('unit-detail').innerHTML, /empty-detail/);
  s.unchanged();

  // Arena pool fields render a stock badge on the card and a line in the detail.
  const stocked = shopFixture();
  stocked.shop[0].pool_remaining = 2; stocked.shop[0].pool_total = 12;
  stocked.shop[2].pool_remaining = 17; stocked.shop[2].pool_total = 18;
  const t = await page(stocked);
  const low = card(t, 0).querySelector('.shop-stock');
  assert.match(low.textContent, /剩 2/);
  assert.ok(low.classList.contains('shop-stock-low'), 'Stock of 3 or less reads as scarce');
  const ample = card(t, 2).querySelector('.shop-stock');
  assert.match(ample.textContent, /剩 17/);
  assert.equal(ample.classList.contains('shop-stock-low'), false);
  await t.click(card(t, 0));
  assert.match(t.element('unit-detail').textContent, /共享池剩余\s*2 \/ 12 张/);
  assert.equal(t.events.fetches.length, 1, 'Reading stock never mutates the session');
  t.unchanged();
})().catch(error => {console.error(error); process.exitCode = 1;});
