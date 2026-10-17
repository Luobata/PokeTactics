/* 下局建议区块：结算弹窗与回合战果都给数据驱动的调整建议，数据不足时不出现空块。 */
const assert = require('node:assert/strict');
const {page, stateFixture, clone} = require('./battle_report_presentation.js');
const scenario = process.argv[4];
function statsWith(team0Units, team1Units) {
  const metrics = ['damage_dealt', 'healing_done', 'damage_taken', 'shield_absorbed'];
  const units = [...team0Units.map((unit, i) => ({idx: i, team: 0, star: 1, role: 'attack', item: null, ...unit})),
    ...team1Units.map((unit, i) => ({idx: 10 + i, team: 1, star: 1, role: 'attack', item: null, ...unit}))];
  return {version: 1, units, totals: [0, 1].map(team => ({team,
    ...Object.fromEntries(metrics.map(metric => [metric,
      units.filter(unit => unit.team === team).reduce((sum, unit) => sum + (unit[metric] || 0), 0)]))}))};
}
function historyRow(round, winner, oppName, statistics) {
  return {round, winner, duration: 12, pve: false, ghost: false, opp_name: oppName, statistics};
}
function overFixture(fixture, rank, defeat) {
  fixture.phase = 'over';
  fixture.you.alive = rank !== 1 && false;
  fixture.you.combines = 3;
  fixture.over = {ranking: [
    {name: '火系对手 L2', rank: 1, is_you: false, hp: 20, rounds: 27},
    {name: '新叶训练家', rank: rank, is_you: true, hp: 0, rounds: 27},
  ]};
  fixture.player_result = {rank, round: 27, team: [], defeat};
  return fixture;
}
const cases = {
  /* 淘汰结算：败因两行扩成建议，引用淘汰轮扣血、累计掉血与跨轮承伤占比，连败经济收尾。 */
  async defeatAdvice() {
    const fixture = overFixture(stateFixture({emptyHistory: true}), 2, {
      defeated_by: {name: '火系对手 L2', damage: 14, round: 27, synergy: '火系④'},
      top_threat: {name: '火系对手 L2', damage: 31},
    });
    fixture.you.streak = -3;
    fixture.you.gold = 23;
    const carry = name => statsWith([{sid: 25, name, damage_dealt: 10, healing_done: 50}],
      [{sid: 6, name: '敌方喷火龙', damage_dealt: 300}]);
    fixture.battle_history = [
      historyRow(25, 1, '火系对手 L2', carry('皮卡丘')),
      historyRow(26, 1, '草系对手 L1', statsWith([{sid: 25, name: '皮卡丘', damage_dealt: 10, healing_done: 50}],
        [{sid: 1, name: '敌方妙蛙种子', damage_dealt: 100}])),
      historyRow(27, 1, '火系对手 L2', carry('皮卡丘')),
    ];
    const p = await page(fixture);
    assert.equal(p.element('result-dialog').open, true, '淘汰后自动打开结算弹窗');
    assert.match(p.element('result-defeat').textContent, /败于 火系对手/);
    const advice = p.element('result-advice');
    assert.equal(advice.hidden, false);
    const tips = advice.querySelectorAll('.advice-list').flatMap(list => list.querySelectorAll('li'));
    assert.equal(tips.length, 3, '败因 > 归因 > 羁绊 > 经济，最多取 3 条');
    assert.match(advice.querySelector('.bond-spark-heading').textContent, /下局建议.*短板归因/);
    assert.match(tips[0].textContent, /败于 火系对手（火系④主羁绊），第 27 轮被扣 14 血/);
    assert.match(tips[0].textContent, /克制其主羁绊|护盾/);
    assert.match(tips[1].textContent, /最大威胁 火系对手 累计打掉你 31 血/);
    assert.match(tips[1].textContent, /占我方总承伤 86%/, '跨轮战报按对手聚合输出占比（600/700）');
    assert.match(tips[2].textContent, /已连败 3 场，连败补贴每轮 \+1 金；现有 23 金，再攒 7 金利息再 \+1/);
    p.unchanged();
  },
  /* 回合战败：输出集中 + 零治疗 + 羁绊缺口各一条，引用真实百分比与缺口数。 */
  async verdictLossAdvice() {
    const fixture = stateFixture({phase: 'battle', emptyHistory: true});
    fixture.last_battle.winner = 1;
    fixture.last_battle.headline = '本回合失利';
    fixture.last_battle.statistics = statsWith(
      [{sid: 149, name: '快龙', damage_dealt: 300, healing_done: 0},
        {sid: 143, name: '卡比兽', damage_dealt: 100, healing_done: 0}],
      [{sid: 6, name: '敌方喷火龙', damage_dealt: 400}]);
    fixture.battle_history = [historyRow(1, 1, '火系对手 L2', statsWith(
      [{sid: 149, name: '快龙', damage_dealt: 200, healing_done: 0}],
      [{sid: 6, name: '敌方喷火龙', damage_dealt: 300}]))];
    fixture.arena.catalog = [{sid: 7, name: '杰尼龟', tier: 1, types: ['水'], role_key: 'defense'}];
    fixture.bench = [{sid: 7, name: '杰尼龟', star: 1, types: ['水'], role_key: 'defense', ranged: false, sell: 1}];
    fixture.bonds = {note: '', entries: [
      {id: 'bond_water', name: '水系', category: 'element', n: 1, tier: 0, next: 2, need: 1,
        effect: '', thresholds: [{count: 2, effect: '成员每秒回复2%最大生命'}], candidates: [7, 60], members: [7]},
    ]};
    const p = await page(fixture);
    await p.click(p.element('fight-button'));
    assert.equal(p.element('battle-advice').hidden, true, '回放未结算时不给建议');
    await p.click(p.element('battle-skip'));
    const advice = p.element('battle-advice');
    assert.equal(advice.hidden, false);
    const tips = advice.querySelectorAll('.advice-list').flatMap(list => list.querySelectorAll('li'));
    assert.equal(tips.length, 3);
    assert.match(tips[0].textContent, /输出过度集中在 快龙 身上（占全队 75%）/);
    assert.match(tips[0].textContent, /保护型装备|第二输出点/);
    assert.match(tips[1].textContent, /近 2 场失利我方有效治疗为 0/, '本场与历史失利轮合并计数');
    assert.match(tips[2].textContent, /「水系」还差 1 位不同伙伴点亮 2 种档（成员每秒回复2%最大生命）；杰尼龟就在备战席/);
    p.unchanged();
  },
  /* 回合胜利：巩固方向——核心输出、已点亮羁绊、连胜经济。 */
  async verdictWinAdvice() {
    const fixture = stateFixture({phase: 'battle', emptyHistory: true});
    fixture.you.streak = 3;
    fixture.last_battle.winner = 0;
    fixture.last_battle.statistics = statsWith(
      [{sid: 6, name: '喷火龙', damage_dealt: 300, healing_done: 0},
        {sid: 149, name: '快龙', damage_dealt: 100, healing_done: 0}],
      [{sid: 1, name: '敌方妙蛙种子', damage_dealt: 200}]);
    fixture.arena.bond_catalog = [
      {id: 'bond_flame', name: '火系', category: 'element', members: [6],
        thresholds: [{count: 1, effect: '成员攻击与特攻+10%'}, {count: 3, effect: '成员攻击与特攻+25%'}]},
    ];
    const p = await page(fixture);
    await p.click(p.element('fight-button'));
    await p.click(p.element('battle-skip'));
    const advice = p.element('battle-advice');
    assert.equal(advice.hidden, false);
    assert.match(advice.querySelector('.bond-spark-heading').textContent, /巩固方向/);
    const tips = advice.querySelectorAll('.advice-list').flatMap(list => list.querySelectorAll('li'));
    assert.equal(tips.length, 3);
    assert.match(tips[0].textContent, /75% 的输出来自 喷火龙，是这支队伍的核心/);
    assert.match(tips[1].textContent, /「火系」已点亮 1 种档（成员攻击与特攻\+10%）：下局继续围绕它补强，再补 2 位升 3 档/);
    assert.match(tips[2].textContent, /已连胜 3 场，连胜奖励每轮 \+1 金/);
    assert.doesNotMatch(advice.textContent, /败于|有效治疗为 0/, '胜利局不出现败因与回复短板');
    p.unchanged();
  },
  /* 夺冠结算：没有败因数据时只给巩固类建议。 */
  async championAdvice() {
    const fixture = overFixture(stateFixture({emptyHistory: true}), 1, null);
    fixture.you.alive = true;
    fixture.you.streak = 5;
    fixture.battle_history = [historyRow(27, 0, '草系对手 L1', statsWith(
      [{sid: 6, name: '喷火龙', damage_dealt: 320, healing_done: 0},
        {sid: 143, name: '卡比兽', damage_dealt: 80, healing_done: 0}],
      [{sid: 1, name: '敌方妙蛙种子', damage_dealt: 150}]))];
    const p = await page(fixture);
    assert.equal(p.element('result-dialog').open, true);
    assert.equal(p.element('result-title').textContent, '森林的冠军，就是你。');
    const advice = p.element('result-advice');
    assert.equal(advice.hidden, false);
    assert.doesNotMatch(advice.textContent, /败于|最大威胁/);
    const tips = advice.querySelectorAll('.advice-list').flatMap(list => list.querySelectorAll('li'));
    assert.match(tips[0].textContent, /80% 的输出来自 喷火龙，是这支队伍的核心/);
    assert.match(tips.at(-1).textContent, /已连胜 5 场，连胜奖励每轮 \+2 金/);
    p.unchanged();
  },
  /* 数据不足：没有统计、没有羁绊缺口、没有连败时两个面板都不出现空建议块。 */
  async noEmptyAdvice() {
    const fixture = stateFixture({phase: 'battle', currentStats: null, emptyHistory: true});
    const p = await page(fixture);
    await p.click(p.element('fight-button'));
    await p.click(p.element('battle-skip'));
    const advice = p.element('battle-advice');
    assert.equal(advice.hidden, true);
    assert.equal(advice.innerHTML, '');
    p.unchanged();
    const over = overFixture(stateFixture({emptyHistory: true}), 3, null);
    const q = await page(over);
    assert.equal(q.element('result-dialog').open, true);
    assert.equal(q.element('result-advice').hidden, true, '没有败因、统计、羁绊与经济信号时不显示空块');
    assert.equal(q.element('result-advice').innerHTML, '');
    q.unchanged();
  },
};
if (require.main === module)
  (async () => {assert.ok(cases[scenario], `Unknown scenario ${scenario}`); await cases[scenario]();})()
    .catch(error => {console.error(error); process.exitCode = 1;});
