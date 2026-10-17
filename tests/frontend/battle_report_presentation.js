/* Execute the shipped play page through its DOM handlers; no server or saves. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const markup = fs.readFileSync(process.argv[3], 'utf8');
const scenario = process.argv[4];
const metrics = ['damage_dealt', 'healing_done', 'damage_taken', 'shield_absorbed'];
const clone = value => JSON.parse(JSON.stringify(value));
const decode = text => text.replace(/&(amp|lt|gt|quot|#39);/g, (_, entity) =>
  ({amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'"})[entity]);
function freeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
function statistics() {
  const units = [
    {idx: 3, team: 0, sid: 6, name: '阵亡喷火龙', star: 2, role: 'attack', item: null,
      alive: false, damage_dealt: 220, healing_done: 0, self_healing: 0, damage_taken: 80, shield_absorbed: 0},
    {idx: 1, team: 0, sid: 143, name: '卡比<&"\'>兽', star: 3, role: 'defense', item: 'leftovers',
      damage_dealt: 220, healing_done: 50, self_healing: 50, damage_taken: 600, shield_absorbed: 70},
    {idx: 2, team: 0, sid: 242, name: '幸福蛋', star: 1, role: 'support', item: null,
      damage_dealt: 40, healing_done: 90, self_healing: 10, damage_taken: 100, shield_absorbed: 20},
    {idx: 0, team: 0, sid: 149, name: '快龙', star: 2, role: 'attack', item: null,
      damage_dealt: 300, healing_done: 0, self_healing: 0, damage_taken: 200, shield_absorbed: 10},
    {idx: 5, team: 1, sid: 160, name: '敌方大力鳄', star: 2, role: 'attack', item: null,
      damage_dealt: 400, healing_done: 20, self_healing: 20, damage_taken: 500, shield_absorbed: 0},
    {idx: 4, team: 1, sid: 212, name: '敌方巨钳螳螂', star: 1, role: 'defense', item: 'bramble',
      damage_dealt: 80, healing_done: 60, self_healing: 5, damage_taken: 100, shield_absorbed: 80},
  ];
  return {version: 1, units, totals: [0, 1].map(team => ({team,
    ...Object.fromEntries([...metrics, 'self_healing'].map(metric => [metric,
      units.filter(unit => unit.team === team).reduce((sum, unit) => sum + unit[metric], 0)]))}))};
}
function zeros() {
  const result = statistics();
  result.units = [result.units[3], result.units[4]];
  for (const row of [...result.units, ...result.totals])
    for (const metric of [...metrics, 'self_healing']) row[metric] = 0;
  return result;
}
function stateFixture(options = {}) {
  const history = Array.from({length: 31}, (_, i) => ({round: i + 1,
    winner: i === 0 ? 1 : i === 2 ? -1 : 0, duration: i === 0 ? null : i === 1 ? 0 : 12.35,
    pve: i === 1, ghost: i === 2, opp_name: i === 2 ? '镜像<&"\'>对手 L3' : `对手 ${i + 1}`,
    statistics: i === 0 ? null : i === 1 ? zeros() : statistics()}));
  return {sid: 'baa710070002', round: options.round ?? 31, phase: options.phase || 'prep',
    stats: {battles: options.battles ?? 0},
    you: {hp: 72, gold: 23, level: 7, on_board: 0, pop: 7, xp: 2, xp_next: 12,
      alive: true, bench_cap: 8, refresh_cost: 2, xp_cost: 4, combines: 3, shop_locked: false},
    weather: {zh: '无', note: '平静'}, opponent: {name: '当轮对手', rows: [[], [], []]},
    arena: {deployment_rows: 3, catalog: []}, board: Array.from({length: 3}, () => Array(6).fill(null)),
    bench: [], shop: [], synergies: [], items: {components: [], finished: [], craftable: []},
    augments: {pending: [], selected: []}, techniques: [], standings: [], log: [], scouting: [],
    round_rewards: [], save: {sequence: 99}, battle_history: options.emptyHistory ? [] : history,
    last_battle: {round: options.round ?? 31, n: 3, dt: .05, winner: 0, headline: '当前回合胜利',
      opp_name: '当轮对手', events: [{t: 0, text: '战斗开始'}, {t: .1, text: '战斗结束'}],
      statistics: Object.hasOwn(options, 'currentStats') ? options.currentStats : statistics()},
  };
}
async function page(fixture, options = {}) {
  const events = {fetches: [], renderStatusFetches: [], images: [], intervals: [], clearedIntervals: [],
    timeouts: [], clearedTimeouts: [], canvas: []};
  const storage = new Map([['poketactics.play.arena.slot', fixture.sid]]);
  let timerId = 0;
  const timers = new Map();
  const imageRecords = [];
  let document;
  const voidTags = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr', 'use']);
  class Element {
    constructor(tagName, attrs = {}) {
      this.tagName = tagName.toUpperCase(); this.attrs = attrs; this.children = [];
      this.parentElement = null; this.listeners = {}; this.dataset = {};
      this._html = ''; this._text = ''; this.style = {setProperty(key, value) {this[key] = value;}};
      this.hidden = Object.hasOwn(attrs, 'hidden'); this.disabled = Object.hasOwn(attrs, 'disabled');
      this.value = attrs.value || ''; this.scrollTop = 0; this.offsetTop = 0; this.clientHeight = 200; this.offsetHeight = 24;
      this.width = Number(attrs.width) || 300; this.height = Number(attrs.height) || 150;
      for (const [key, value] of Object.entries(attrs)) if (key.startsWith('data-'))
        this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
      this.classList = {
        add: name => this.className = [...new Set([...this.className.split(/\s+/), name])].join(' ').trim(),
        remove: name => this.className = this.className.split(/\s+/).filter(value => value !== name).join(' '),
        contains: name => this.className.split(/\s+/).includes(name),
        toggle: (name, on) => {on ??= !this.className.split(/\s+/).includes(name);
          on ? this.classList.add(name) : this.classList.remove(name); return on;},
      };
    }
    get id() {return this.attrs.id || '';}
    set id(value) {this.attrs.id = value;}
    get className() {return this.attrs.class || '';}
    set className(value) {this.attrs.class = value;}
    get textContent() {return this._text + this.children.map(child => child.textContent).join('');}
    set textContent(value) {this._text = String(value); this.children = []; this._html = '';}
    get innerHTML() {return this._html;}
    set innerHTML(value) {this._html = String(value); this._text = ''; this.children = []; parse(this._html, this);}
    get open() {return Object.hasOwn(this.attrs, 'open');}
    set open(value) {value ? this.attrs.open = '' : delete this.attrs.open;}
    setAttribute(key, value) {this.attrs[key] = String(value);}
    getAttribute(key) {return this.attrs[key] ?? null;}
    removeAttribute(key) {delete this.attrs[key];}
    hasAttribute(key) {return Object.hasOwn(this.attrs, key);}
    addEventListener(type, handler) {(this.listeners[type] ||= []).push(handler);}
    append(child) {child.parentElement = this; this.children.push(child);}
    insertAdjacentHTML(position, html) {assert.equal(position, 'beforeend'); this.innerHTML += html;}
    contains(node) {return node === this || this.children.some(child => child.contains(node));}
    showModal() {this.open = true;}
    close() {this.open = false; for (const handler of this.listeners.close || []) handler({target: this});}
    focus() {document.activeElement = this;}
    scrollIntoView() {}
    getBoundingClientRect() {return {left: 0, top: 0, bottom: 24, width: 24, height: 24};}
    matches(selector) {
      const attrs = [...selector.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g)];
      const simple = selector.replace(/\[[^\]]+\]/g, '');
      const tag = simple.match(/^[a-z][\w-]*/i)?.[0];
      if (tag && this.tagName !== tag.toUpperCase()) return false;
      const id = simple.match(/#([\w-]+)/)?.[1];
      if (id && this.id !== id) return false;
      if ([...simple.matchAll(/\.([\w-]+)/g)].some(match => !this.className.split(/\s+/).includes(match[1]))) return false;
      return attrs.every(([, key, value]) => this.hasAttribute(key) && (value === undefined || this.getAttribute(key) === value));
    }
    closest(selector) {return this.matches(selector) ? this : this.parentElement?.closest(selector) || null;}
    querySelectorAll(selector) {
      const result = [];
      for (const child of this.children) {
        if (child.matches(selector)) result.push(child);
        result.push(...child.querySelectorAll(selector));
      }
      return result;
    }
    querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}
    getContext(kind) {
      assert.equal(this.tagName, 'CANVAS'); assert.equal(kind, '2d');
      this.context ||= Object.fromEntries(['clearRect', 'drawImage', 'fillRect', 'fillText'].map(method => [method,
        (...args) => events.canvas.push([method, ...args.map(value => typeof value === 'object' ? value.src : value)])]));
      return this.context;
    }
  }
  function parse(html, parent) {
    const stack = [parent];
    const tokens = /<!--[\s\S]*?-->|<![^>]+>|<\/?([\w:-]+)([^>]*?)\/?>|([^<]+)/g;
    for (const match of html.matchAll(tokens)) {
      if (match[0].startsWith('<!')) continue;
      if (match[3]) {
        const text = new Element('#text'); text._text = decode(match[3]); stack.at(-1).append(text);
      } else if (match[0].startsWith('</')) {
        const index = stack.findLastIndex(node => node.tagName === match[1].toUpperCase());
        if (index > 0) stack.length = index;
      } else {
        const attrs = Object.fromEntries([...match[2].matchAll(/([^\s=\/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)]
          .map(([, key, a, b, c]) => [key, decode(a ?? b ?? c ?? '')]));
        const element = new Element(match[1], attrs); stack.at(-1).append(element);
        if (!voidTags.has(match[1].toLowerCase()) && !match[0].endsWith('/>')) stack.push(element);
      }
    }
  }
  const root = new Element('document');
  document = {hidden: false, activeElement: null, listeners: {},
    getElementById: id => root.querySelector(`#${id}`),
    querySelector: selector => root.querySelector(selector),
    querySelectorAll: selector => root.querySelectorAll(selector),
    createElement: tag => new Element(tag),
    addEventListener(type, handler) {(this.listeners[type] ||= []).push(handler);},
  };
  parse(markup, root); document.body = root.querySelector('body');
  const serialized = JSON.stringify(fixture); freeze(fixture);
  const context = vm.createContext({document, window: {matchMedia: () => ({matches: !!options.mobile})}, innerHeight: 900, URLSearchParams, Date: {now: options.clock || Date.now},
    localStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value)},
    AbortController,
    fetch: async (url, init = {}) => {
      const request = new URL(url, 'http://fixture.invalid');
      const query = request.searchParams;
      if (request.pathname.startsWith('/demo/render-status/')) {
        events.renderStatusFetches.push({url, signal: init.signal});
        const result = options.renderStatusResponder
          ? await options.renderStatusResponder(request, events.renderStatusFetches.length, init)
          : {ok: true, status: 'ready', frames: 9, total: 9, updated_at: 1, queued: false, error: null};
        return {ok: true, json: async () => result};
      }
      assert.equal(request.pathname, '/api/demo/action');
      assert.equal(query.get('sid'), fixture.sid); events.fetches.push(url);
      if (query.get('cmd') !== 'resume') {
        assert.equal(typeof options.mutationResponder, 'function', 'Viewing a report must not call a mutation API');
        if (options.pendingMutation) return new Promise((_, reject) => {
          init.signal?.addEventListener('abort', () => {
            const error = new Error('aborted');
            error.name = 'AbortError';
            reject(error);
          });
        });
        const result = options.mutationResponder(query);
        return {ok: true, json: async () => result};
      }
      return {ok: true, json: async () => ({ok: true, sid: fixture.sid, state: fixture})};
    },
    setTimeout: (callback, delay) => {const id = ++timerId; events.timeouts.push({id, delay});
      timers.set(id, {kind: 'timeout', callback, delay}); return id;},
    clearTimeout: id => {events.clearedTimeouts.push(id); timers.delete(id);},
    setInterval: (callback, delay) => {const id = ++timerId; events.intervals.push({id, delay});
      timers.set(id, {kind: 'interval', callback, delay}); return id;},
    clearInterval: id => {events.clearedIntervals.push(id); timers.delete(id);},
    Image: class {
      set src(value) {
        this._src = value; events.images.push(value); this.naturalWidth = 0; this.naturalHeight = 0;
        const record = {image: this, src: value, settled: false, load: () => {
          if (record.settled) return;
          record.settled = true; this.naturalWidth = options.imageWidth || 240;
          this.naturalHeight = options.imageHeight || 320; this.onload?.();
        }, fail: () => {if (!record.settled) {record.settled = true; this.onerror?.();}}};
        imageRecords.push(record);
        if (!options.manualImages) queueMicrotask(record.load);
      }
      get src() {return this._src;}
    },
  });
  vm.runInContext(source, context);
  const settle = async () => {for (let i = 0; i < 3; i++) await new Promise(resolve => setImmediate(resolve));};
  await settle();
  const element = id => {const found = document.getElementById(id); assert.ok(found, `Missing page ID ${id}`); return found;};
  assert.equal(events.fetches.length, 1, 'Fixture resumes once at startup');
  async function startClick(button) {
    assert.ok(button, 'Missing button'); assert.equal(button.tagName, 'BUTTON'); assert.equal(button.disabled, false);
    const pending = [];
    if (button.onclick) pending.push(button.onclick({target: button}));
    for (const handler of document.listeners.click || []) pending.push(handler({target: button}));
    const done = Promise.all(pending); await settle(); return {done};
  }
  async function click(button) {const started = await startClick(button); await started.done; await settle();}
  async function change(id, value) {
    const select = element(id); select.value = String(value);
    assert.equal(typeof select.onchange, 'function'); await select.onchange({target: select}); await settle();
  }
  async function dispatch(id, type, extra = {}) {
    const target = element(id); const event = {target, preventDefault() {}, ...extra};
    const pending = [];
    if (target['on' + type]) pending.push(target['on' + type](event));
    for (const handler of target.listeners[type] || []) pending.push(handler(event));
    for (const handler of document.listeners[type] || []) pending.push(handler(event));
    await Promise.all(pending); await settle();
  }
  async function tick(count = 1) {
    for (let i = 0; i < count; i++) {
      for (const [id, timer] of [...timers])
        if (timer.kind === 'interval' && timers.has(id)) timer.callback();
      await settle();
    }
  }
  async function expireTimeouts(delay) {
    for (const [id, timer] of [...timers]) if (timer.kind === 'timeout' && timer.delay === delay) {
      timers.delete(id); timer.callback();
    }
    await settle();
  }
  function snapshot() {
    return JSON.stringify({events, state: fixture, storage: [...storage],
      round: element('round-number').textContent, phase: element('phase-label').textContent,
      currentStats: element('battle-statistics').innerHTML, battleOpen: element('battle-dialog').open,
      playbackStatus: element('battle-status').textContent, pause: element('battle-pause').textContent,
      canvasWidth: element('battle-canvas').width, canvasHeight: element('battle-canvas').height,
      saveStatus: element('save-status').textContent});
  }
  return {element, click, startClick, change, dispatch, tick, expireTimeouts, settle, timers, imageRecords,
    pendingImages: () => imageRecords.filter(record => !record.settled),
    document, events, snapshot, fixture, serialized, focused: () => document.activeElement,
    unchanged: () => assert.equal(JSON.stringify(fixture), serialized, 'Report viewing changed the authoritative state')};
}
function button(page, scope, attr, value) {
  return page.element(scope === 'history' ? 'history-statistics' : 'battle-statistics')
    .querySelector(`[data-stat-${attr}="${value}"]`);
}
function ranking(page, scope = 'history') {
  return page.element(scope === 'history' ? 'history-statistics' : 'battle-statistics')
    .querySelectorAll('[data-stat-unit]').map(row => Number(row.dataset.statUnit));
}
function selected(page, scope, attr, value) {
  assert.equal(button(page, scope, attr, value).getAttribute('aria-pressed'), 'true');
}
async function openHistory(page, round) {
  await page.click(page.element('battle-history').querySelector(`[data-battle-report="${round}"]`));
  assert.equal(page.element('history-report-dialog').open, true);
  assert.equal(page.element('history-report-title').textContent, `第 ${round} 轮 · 战报`);
}
const cases = {
  async attackBranches() {
    const fixture = stateFixture({phase: 'battle'});
    const zero = {triggers: 0, energy: 0, shield: 0, absorbed: 0, charges: 0, damage: 0,
      damage_absorbed: 0, vulnerable: 0, spreads: 0, tempo_stacks: 0, offense_buffs: 0};
    fixture.last_battle.combinations = {triggers: 6, total_energy: 0, total_shield: 0, absorbed: 0,
      total_charges: 0, total_damage: 0, damage_absorbed: 0, total_vulnerable: 0,
      total_spreads: 2, total_tempo_stacks: 3, total_offense_buffs: 1,
      by_key: [{...zero, id: 'contagion_orb', name: '扩散宝珠', triggers: 2, spreads: 2},
        {...zero, id: 'metronome', name: '节拍器', triggers: 3, tempo_stacks: 3},
        {...zero, id: 'native_inspiration', name: '充能鼓舞', triggers: 1, offense_buffs: 1}]};
    const p = await page(fixture);
    await p.click(p.element('fight-button')); await p.click(p.element('battle-skip'));
    const panel = p.element('battle-combinations');
    const tiles = panel.querySelector('.combination-totals').querySelectorAll('div');
    assert.equal(tiles.length, 10);
    assert.deepEqual(tiles.slice(-3).map(tile => tile.querySelector('b').textContent), ['2', '3', '1']);
    const benefits = panel.querySelectorAll('.combination-benefit');
    assert.equal(benefits.length, 3);
    assert.match(benefits[0].textContent, /成功传播 2 次/);
    assert.match(benefits[1].textContent, /有效普攻增层 3 次/);
    assert.match(benefits[1].textContent, /清层后可重新累计/);
    assert.match(benefits[2].textContent, /鼓舞 1 次/);
    assert.match(benefits[2].textContent, /每次3秒直接攻击\+25%/);
    assert.match(panel.textContent, /不推算额外伤害/);
    assert.match(panel.textContent, /鼓舞不强化毒\/灼伤或岩钉/);
    p.unchanged();
  },
  async comboBranches() {
    const fixture = stateFixture({phase: 'battle'});
    const metrics = {energy: 0, shield: 0, absorbed: 0, charges: 0, damage: 0, damage_absorbed: 0, vulnerable: 0};
    fixture.last_battle.combinations = {
      triggers: 4, total_energy: 3, total_shield: 80, absorbed: 50,
      total_charges: 2, total_damage: 11, damage_absorbed: 7, total_vulnerable: 1,
      by_key: [
        {id: 'ward_bracer', name: '守势护腕', ...metrics, triggers: 1, charges: 2, damage: 11, damage_absorbed: 7},
        {id: 'clarity_charm', name: '清明坠饰', ...metrics, triggers: 1, shield: 80, absorbed: 50},
        {id: 'barrier_feedback', name: '屏障回流', ...metrics, triggers: 1, energy: 3},
        {id: 'breach_momentum', name: '乘隙追击', ...metrics, triggers: 1, vulnerable: 1},
      ],
    };
    const p = await page(fixture);
    await p.click(p.element('fight-button'));
    assert.equal(p.element('battle-combinations').hidden, true, 'Rewards remain hidden before replay is settled');
    await p.click(p.element('battle-skip'));
    const panel = p.element('battle-combinations');
    assert.equal(panel.hidden, false);
    const tiles = panel.querySelectorAll('.combination-totals').flatMap(row => row.querySelectorAll('div'));
    assert.deepEqual(tiles.map(tile => tile.querySelector('b').textContent), ['3', '80', '50', '11', '7', '2', '1']);
    const benefits = panel.querySelectorAll('.combination-benefit');
    assert.equal(benefits.length, 4);
    assert.match(benefits[0].textContent, /蓄力 2 次/);
    assert.match(benefits[0].textContent, /强化普攻 1 次/);
    assert.match(benefits[0].textContent, /额外生命损失 11/);
    assert.match(benefits[0].textContent, /强化部分被盾吸收 7/);
    assert.match(benefits[1].textContent, /新增盾 80/);
    assert.match(benefits[1].textContent, /护盾实吸 50/);
    assert.match(benefits[2].textContent, /回能 3/);
    assert.match(benefits[3].textContent, /成功易伤 1 次/);
    assert.match(panel.textContent, /不重复计入整次普攻/);
    p.unchanged();
    const old = stateFixture({phase: 'battle'});
    old.last_battle.combinations = {triggers: 1, total_energy: 8, total_shield: 0, absorbed: 0,
      by_key: [{id: 'watch_echo', name: '守望回响', triggers: 1, energy: 8, shield: 0, absorbed: 0}]};
    const legacy = await page(old);
    await legacy.click(legacy.element('fight-button')); await legacy.click(legacy.element('battle-skip'));
    const oldTotals = legacy.element('battle-combinations').querySelector('.combination-totals');
    assert.equal(oldTotals.querySelectorAll('div').length, 3, 'Old reports do not invent four new zero counters');
    assert.match(legacy.element('battle-combinations').textContent, /守望回响/);
    legacy.unchanged();
  },
  async traitsGear() {
    const fixture = stateFixture({phase: 'battle'});
    const metrics = {energy: 0, shield: 0, absorbed: 0, charges: 0, damage: 0, damage_absorbed: 0,
      vulnerable: 0, spreads: 0, tempo_stacks: 0, offense_buffs: 0, healing: 0, cleanses: 0,
      statuses: 0, mitigated: 0, accuracy_saves: 0, weakens: 0};
    fixture.last_battle.combinations = {triggers: 5, total_energy: 0, total_shield: 0, absorbed: 0,
      total_charges: 0, total_damage: 4, damage_absorbed: 0, total_vulnerable: 0,
      total_spreads: 0, total_tempo_stacks: 0, total_offense_buffs: 1,
      total_healing: 17, total_cleanses: 1, total_statuses: 0, total_mitigated: 0,
      total_accuracy_saves: 0, total_weakens: 0,
      by_key: [
        {id: 'trait_guts', name: '毅力', ...metrics, triggers: 1, offense_buffs: 1, damage: 4},
        {id: 'trait_magic_guard', name: '魔法防守', ...metrics, triggers: 2},
        {id: 'dew_charm', name: '甘露坠饰', ...metrics, triggers: 1, healing: 17},
        {id: 'grounding_cloak', name: '接地斗篷', ...metrics, triggers: 1, cleanses: 1},
      ]};
    const p = await page(fixture);
    await p.click(p.element('fight-button')); await p.click(p.element('battle-skip'));
    const panel = p.element('battle-combinations');
    const tiles = panel.querySelectorAll('.combination-totals').flatMap(row => row.querySelectorAll('div'));
    assert.deepEqual(tiles.slice(-6).map(tile => tile.querySelector('b').textContent), ['17','0','1','0','0','0']);
    const benefits = panel.querySelectorAll('.combination-benefit');
    assert.match(benefits[0].textContent, /特性 · 毅力/);
    assert.match(benefits[0].textContent, /物理直接伤害\+20%/);
    assert.doesNotMatch(benefits[0].textContent, /直接攻击\+25%/);
    assert.match(benefits[1].textContent, /实际避免生命损失 0/);
    assert.doesNotMatch(benefits[1].textContent, /护盾实吸|实际治疗/);
    assert.match(benefits[2].textContent, /实际治疗 17/);
    assert.match(benefits[3].textContent, /实际净化 1 次/);
    assert.match(panel.textContent, /记录数不等于触发机会数/);
    p.unchanged();
  },
  async metrics() {
    const p = await page(stateFixture()); const before = p.snapshot();
    await openHistory(p, 3); const stats = p.element('history-statistics');
    assert.deepEqual(ranking(p), [0, 1, 3, 2]); // Equal damage uses the unit index, regardless of input order.
    assert.match(stats.innerHTML, /阵亡喷火龙/); assert.match(stats.innerHTML, /含阵亡精灵/);
    assert.match(stats.innerHTML, /卡比&lt;&amp;&quot;&#39;&gt;兽/); assert.doesNotMatch(stats.innerHTML, /卡比<&/);
    assert.match(stats.innerHTML, /\/demo\/sprite\/143\.png\?shiny=1/); assert.match(stats.innerHTML, /携带装备/);
    assert.deepEqual(metrics.map(metric => button(p, 'history', 'metric', metric).querySelector('strong').textContent),
      ['780', '140', '980', '100']);
    selected(p, 'history', 'team', '0'); selected(p, 'history', 'metric', 'damage_dealt');
    await p.click(button(p, 'history', 'metric', 'healing_done')); assert.deepEqual(ranking(p), [2, 1, 0, 3]);
    const healer = stats.querySelector('[data-stat-unit="2"]');
    assert.equal(healer.querySelector('.stat-unit-value').querySelector('strong').textContent, '90');
    assert.equal(healer.querySelector('.stat-self-heal').textContent, '其中自疗 10');
    assert.equal(stats.querySelector('[data-stat-unit="1"]').querySelector('.stat-self-heal').textContent, '其中自疗 50');
    selected(p, 'history', 'metric', 'healing_done');
    assert.equal(p.focused(), button(p, 'history', 'metric', 'healing_done'), 'Recreated control retains keyboard focus');
    await p.click(button(p, 'history', 'metric', 'damage_taken')); assert.deepEqual(ranking(p), [1, 0, 2, 3]);
    assert.equal(stats.querySelector('.stat-self-heal'), null);
    await p.click(button(p, 'history', 'metric', 'shield_absorbed')); assert.deepEqual(ranking(p), [1, 2, 0, 3]);
    const shield = stats.querySelector('[data-stat-unit="1"]');
    assert.equal(shield.querySelector('.stat-unit-value').querySelector('strong').textContent, '70');
    assert.equal(shield.querySelector('.stat-bar').querySelector('span').getAttribute('style'), 'width:100.00%');
    assert.equal(stats.querySelector('[data-stat-unit="2"]').querySelector('.stat-bar').querySelector('span').getAttribute('style'), 'width:28.57%');
    assert.equal(stats.querySelector('[data-stat-unit="3"]').querySelector('.stat-bar').querySelector('span').getAttribute('style'), 'width:0.00%');
    await p.click(button(p, 'history', 'team', '1')); assert.deepEqual(ranking(p), [4, 5]);
    selected(p, 'history', 'team', '1'); selected(p, 'history', 'metric', 'shield_absorbed');
    assert.equal(stats.dataset.team, '1');
    assert.deepEqual(metrics.map(metric => button(p, 'history', 'metric', metric).querySelector('strong').textContent),
      ['480', '80', '600', '80']);
    await p.click(button(p, 'history', 'metric', 'healing_done')); assert.deepEqual(ranking(p), [4, 5]);
    await p.click(button(p, 'history', 'metric', 'damage_dealt')); assert.deepEqual(ranking(p), [5, 4]);
    assert.equal(p.snapshot(), before); p.unchanged();
  },
  async history() {
    const fixture = stateFixture(); const p = await page(fixture); const before = p.snapshot();
    assert.equal(p.element('battle-history-count').textContent, '31 场');
    const entries = p.element('battle-history').querySelectorAll('[data-battle-report]');
    assert.deepEqual(entries.map(entry => Number(entry.dataset.battleReport)), Array.from({length: 31}, (_, i) => 31 - i));
    assert.equal(entries.at(-1).getAttribute('aria-haspopup'), 'dialog');
    assert.match(entries.at(-1).textContent, /失利.*时长未记录.*统计未记录/);
    assert.match(p.element('battle-history').innerHTML, /镜像&lt;&amp;&quot;&#39;&gt;对手/);
    await openHistory(p, 1);
    assert.equal(p.element('history-report-result').textContent, '失利');
    assert.equal(p.element('history-report-round').querySelectorAll('option').length, 31);
    assert.match(p.element('history-statistics').innerHTML, /这份旧战果未记录单位统计/);
    assert.equal(p.element('history-statistics').querySelectorAll('button').length, 0);
    assert.equal(p.element('history-statistics').querySelectorAll('[data-stat-unit]').length, 0);
    await p.change('history-report-round', 2);
    assert.match(p.element('history-report-subtitle').textContent, /野生遭遇.*0\.0 秒/);
    assert.deepEqual(metrics.map(metric => button(p, 'history', 'metric', metric).querySelector('strong').textContent), ['0', '0', '0', '0']);
    assert.match(p.element('history-statistics').innerHTML, /width:0\.00%/);
    assert.doesNotMatch(p.element('history-statistics').innerHTML, /NaN|Infinity|未记录单位统计/);
    await p.click(button(p, 'history', 'team', '1')); assert.deepEqual(ranking(p), [5]);
    assert.equal(p.element('history-statistics').querySelector('.stat-unit-value').querySelector('strong').textContent, '0');
    await p.change('history-report-round', 3);
    assert.equal(p.element('history-report-title').textContent, '第 3 轮 · 战报');
    assert.equal(p.element('history-report-result').textContent, '平局');
    assert.match(p.element('history-report-subtitle').textContent, /镜像<&"'>对手.*（镜像）.*12\.3 秒/);
    selected(p, 'history', 'team', '0'); selected(p, 'history', 'metric', 'damage_dealt');
    await p.click(p.element('history-report-close')); assert.equal(p.element('history-report-dialog').open, false);
    assert.equal(p.snapshot(), before); p.unchanged();
    await p.click(p.element('resume-button'));
    assert.equal(p.events.fetches.length, 2); assert.equal(p.element('battle-history-count').textContent, '31 场');
    await openHistory(p, 3); assert.deepEqual(ranking(p), [0, 1, 3, 2]); p.unchanged();
    const refreshed = await page(clone(fixture));
    assert.equal(refreshed.element('battle-history-count').textContent, '31 场');
    await openHistory(refreshed, 3); assert.deepEqual(ranking(refreshed), [0, 1, 3, 2]); refreshed.unchanged();
  },
  async playback() {
    const p = await page(stateFixture({phase: 'battle'}));
    await p.click(p.element('fight-button'));
    assert.equal(p.element('battle-dialog').open, true); assert.equal(p.element('battle-pause').textContent, '暂停');
    assert.equal(p.events.fetches.length, 1); assert.equal(p.events.images.length, 3); assert.equal(p.events.intervals.length, 1);
    assert.equal(p.element('battle-statistics').querySelectorAll('[data-stat-unit]').length, 0, 'Final statistics must wait for the end of playback');
    await p.click(p.element('battle-skip'));
    assert.deepEqual(ranking(p, 'battle'), [0, 1, 3, 2]);
    await p.click(button(p, 'battle', 'team', '1')); await p.click(button(p, 'battle', 'metric', 'shield_absorbed'));
    assert.deepEqual(ranking(p, 'battle'), [4, 5]); const before = p.snapshot();
    await openHistory(p, 3); selected(p, 'history', 'team', '0'); selected(p, 'history', 'metric', 'damage_dealt');
    await p.click(button(p, 'history', 'team', '1')); await p.click(button(p, 'history', 'metric', 'healing_done'));
    assert.deepEqual(ranking(p), [4, 5]);
    await p.change('history-report-round', 1); await p.click(p.element('history-report-close'));
    assert.equal(p.snapshot(), before, 'Historical controls changed current playback, statistics, timers, frames, or resources');
    selected(p, 'battle', 'team', '1'); selected(p, 'battle', 'metric', 'shield_absorbed'); p.unchanged();
    await p.click(button(p, 'battle', 'team', '0')); await p.click(button(p, 'battle', 'metric', 'healing_done'));
    assert.deepEqual(ranking(p, 'battle'), [2, 1, 0, 3]);
    await p.click(button(p, 'battle', 'metric', 'damage_taken')); assert.deepEqual(ranking(p, 'battle'), [1, 0, 2, 3]);
    assert.equal(p.events.fetches.length, 1); assert.equal(p.events.images.length, 3); assert.equal(p.events.intervals.length, 1); p.unchanged();
  },
  async emptyHistory() {
    for (const [round, battles, expected] of [
      [1, 0, '完成第一场战斗后，这里会留下每轮战报。'],
      [2, 0, '旧回合未记录统计，从下一场战斗开始保留每轮战报。'],
      [1, 1, '旧回合未记录统计，从下一场战斗开始保留每轮战报。'],
    ]) {
      const p = await page(stateFixture({round, battles, emptyHistory: true}));
      assert.equal(p.element('battle-history-count').textContent, '0 场');
      assert.equal(p.element('battle-history').querySelector('.history-empty').textContent, expected);
      assert.equal(p.element('battle-history').querySelectorAll('[data-battle-report]').length, 0);
      assert.equal(p.events.fetches.length, 1); assert.equal(p.events.images.length, 0);
      p.unchanged();
    }
  },
  async missing() {
    const p = await page(stateFixture({phase: 'battle', currentStats: null, emptyHistory: true}));
    assert.equal(p.element('battle-history-count').textContent, '0 场'); assert.match(p.element('battle-history').textContent, /旧回合未记录统计/);
    await p.click(p.element('fight-button'));
    assert.equal(p.element('battle-statistics').querySelectorAll('[data-stat-unit]').length, 0);
    await p.click(p.element('battle-skip'));
    assert.match(p.element('battle-statistics').innerHTML, /未记录单位统计/);
    assert.equal(p.element('battle-statistics').querySelectorAll('button').length, 0);
    assert.equal(p.element('battle-statistics').querySelectorAll('[data-stat-unit]').length, 0); p.unchanged();
    const empty = zeros(); empty.units = [];
    const current = await page(stateFixture({phase: 'battle', currentStats: empty}));
    await current.click(current.element('fight-button'));
    await current.click(current.element('battle-skip'));
    assert.match(current.element('battle-statistics').textContent, /我方没有上阵精灵/);
    assert.deepEqual(metrics.map(metric => button(current, 'battle', 'metric', metric).querySelector('strong').textContent), ['0', '0', '0', '0']);
    await current.click(button(current, 'battle', 'team', '1'));
    assert.match(current.element('battle-statistics').textContent, /敌方没有上阵精灵/); current.unchanged();
    const malformed = statistics(); malformed.units[0].healing_done = '17';
    const unknown = await page(stateFixture({phase: 'battle', currentStats: malformed}));
    await unknown.click(unknown.element('fight-button')); await unknown.click(unknown.element('battle-skip'));
    await unknown.click(button(unknown, 'battle', 'metric', 'healing_done'));
    assert.equal(unknown.element('battle-statistics').querySelector('[data-stat-unit="3"]').querySelector('.stat-unit-value').querySelector('strong').textContent, '—');
    unknown.unchanged();
  },
  async familyBondSpark() {
    const fixture = stateFixture({phase: 'battle'});
    fixture.arena.pool_version = 'families_v2';
    const bond = (id, name, members, identities, count) => ({id, name, category: 'tactic',
      members, count_unit: '家族', identity_by_species: Object.fromEntries(members.map((sid, i) => [sid, identities[i]])),
      thresholds: [{count, effect: name + '已生效'}]});
    fixture.arena.bond_catalog = [
      bond('bond_mindsong', '脑波', [280, 281, 196], [280, 280, 133], 2),
      bond('bond_dragon_pressure', '龙威', [334], [333], 1),
      bond('DARK', '恶系', [197], [133], 2),
    ];
    const stats = sids => {
      const data = statistics();
      const template = data.units[0];
      data.units = sids.map((sid, idx) => ({...template, sid, idx, name: String(sid)}));
      return data;
    };
    fixture.last_battle.statistics = stats([280, 281, 334]);
    fixture.battle_history[2].statistics = stats([280, 196, 197, 334]);
    const p = await page(fixture);
    await p.click(p.element('fight-button'));
    await p.click(p.element('battle-skip'));
    const panel = p.element('battle-bonds');
    assert.match(panel.textContent, /按上场不同家族计数/);
    const currentRows = panel.querySelectorAll('.bond-spark-row');
    const psychic = currentRows.find(row => row.textContent.includes('脑波'));
    assert.match(psychic.textContent, /1 \/ 2 个家族/);
    assert.doesNotMatch(psychic.textContent, /已激活/, 'same-family forms must not activate a two-family bond');
    assert.match(currentRows.find(row => row.textContent.includes('龙威')).textContent, /已激活 1 家族档/);
    await openHistory(p, 3);
    const historyRows = p.element('history-bonds').querySelectorAll('.bond-spark-row');
    assert.match(historyRows.find(row => row.textContent.includes('脑波')).textContent, /已激活 2 家族档/);
    assert.match(historyRows.find(row => row.textContent.includes('恶系')).textContent, /1 \/ 2 个家族/);
    p.unchanged();
    const missingMapping = clone(fixture);
    delete missingMapping.arena.bond_catalog[0].identity_by_species;
    const old = await page(missingMapping);
    await old.click(old.element('fight-button'));
    await old.click(old.element('battle-skip'));
    assert.equal(old.element('battle-bonds').hidden, true, 'missing family mapping must not fabricate species counts');
  },
  async bondSpark() {
    const fixture = stateFixture({phase: 'battle'});
    fixture.arena.bond_catalog = [
      {id: 'bond_flame', name: '火系', category: 'element', members: [6, 149],
        thresholds: [{count: 2, effect: '成员攻击与特攻+10%'}, {count: 4, effect: '成员攻击与特攻+20%'}]},
      {id: 'bond_guard', name: '守护', category: 'tactic', members: [143, 242, 500],
        thresholds: [{count: 3, effect: '成员物防与特防+15%'}]},
      {id: 'bond_absent', name: '冰系', category: 'element', members: [900],
        thresholds: [{count: 1, effect: '成员攻速+5%'}]},
    ];
    fixture.last_battle.statistics.units.push({idx: 7, team: 0, sid: 6, name: '喷火龙二号', star: 1,
      role: 'attack', item: null, damage_dealt: 10, healing_done: 0, self_healing: 0,
      damage_taken: 10, shield_absorbed: 0});
    const p = await page(fixture);
    await p.click(p.element('fight-button'));
    assert.equal(p.element('battle-bonds').hidden, true, '羁绊点亮要等回放结算后才出现');
    await p.click(p.element('battle-skip'));
    const panel = p.element('battle-bonds');
    assert.equal(panel.hidden, false);
    const rows = panel.querySelectorAll('.bond-spark-row');
    assert.equal(rows.length, 2, '同种重复棋子只计一次，未代表的羁绊不出现');
    assert.match(rows[0].textContent, /火系/);
    assert.match(rows[0].textContent, /已激活 2 种档/);
    assert.match(rows[0].textContent, /成员攻击与特攻\+10%/);
    assert.match(rows[0].textContent, /再补 2 位升 4 档/);
    assert.match(rows[1].textContent, /守护/);
    assert.match(rows[1].textContent, /2 \/ 3 种/);
    assert.match(rows[1].textContent, /还差 1 位不同伙伴点亮：成员物防与特防\+15%/);
    assert.doesNotMatch(panel.textContent, /冰系/);
    await openHistory(p, 3);
    assert.equal(p.element('history-bonds').hidden, false);
    assert.match(p.element('history-bonds').textContent, /已激活 2 种档/);
    await p.change('history-report-round', 2);
    assert.match(p.element('history-bonds').textContent, /本场没有点亮任何羁绊档位/);
    assert.match(p.element('history-bonds').textContent, /火系 1 \/ 2 种/);
    await p.change('history-report-round', 1);
    assert.equal(p.element('history-bonds').hidden, true, '旧战报未记录统计时不伪造羁绊');
    await p.click(p.element('history-report-close'));
    p.unchanged();
    const noCatalog = await page(stateFixture({phase: 'battle'}));
    await noCatalog.click(noCatalog.element('fight-button'));
    await noCatalog.click(noCatalog.element('battle-skip'));
    assert.equal(noCatalog.element('battle-bonds').hidden, true, '没有羁绊目录的旧存档优雅降级');
    noCatalog.unchanged();
  },
  async comboGuidance() {
    const empty = {triggers: 0, total_energy: 0, total_shield: 0, absorbed: 0, by_key: []};
    const fixture = stateFixture({phase: 'battle'});
    fixture.last_battle.combinations = clone(empty);
    fixture.last_battle.enemy_combinations = clone(empty);
    fixture.arena.catalog = [{sid: 7, name: '杰尼龟', tier: 1, types: ['水'], role_key: 'defense'}];
    fixture.bench = [{sid: 7, name: '杰尼龟', star: 1, types: ['水'], role_key: 'defense', ranged: false, sell: 1}];
    fixture.bonds = {note: '', entries: [
      {id: 'bond_water', name: '水系', category: 'element', n: 1, tier: 0, next: 2, need: 1,
        effect: '', thresholds: [{count: 2, effect: '成员每秒回复2%最大生命'}],
        candidates: [7, 60], members: [7]},
      {id: 'bond_flame', name: '火系', category: 'element', n: 2, tier: 2, next: 4, need: 2,
        effect: '成员攻击与特攻+10%',
        thresholds: [{count: 2, effect: '成员攻击与特攻+10%'}, {count: 4, effect: '成员攻击与特攻+25%'}],
        candidates: [], members: [6]},
    ]};
    const p = await page(fixture);
    await p.click(p.element('fight-button'));
    await p.click(p.element('battle-skip'));
    const panel = p.element('battle-combinations');
    assert.match(panel.textContent, /本轮未触发联动/);
    const friendly = panel.querySelector('.combination-team.friendly');
    const tips = friendly.querySelector('.combination-guide').querySelectorAll('li');
    assert.equal(tips.length, 2, '空态给一到两条可操作引导，按缺口排序');
    assert.match(tips[0].textContent, /当前阵容再上场 1 位不同伙伴即可点亮「水系」：成员每秒回复2%最大生命（杰尼龟在备战席）/);
    assert.match(tips[1].textContent, /「火系」已激活 2 种档，再补 2 位不同伙伴点亮 4 种档/);
    const enemy = panel.querySelector('.combination-team.enemy');
    assert.doesNotMatch(enemy.textContent, /联动检查|即可点亮/, '空态引导只给我方，不污染敌方面板');
    p.unchanged();
    const legacy = stateFixture({phase: 'battle'});
    legacy.last_battle.combinations = clone(empty);
    legacy.synergies = [{type: 'fire', zh: '火系', n: 1, tier: 0, next: 2, need: 1, effect: '', color: '#ffffff'}];
    const q = await page(legacy);
    await q.click(q.element('fight-button'));
    await q.click(q.element('battle-skip'));
    assert.match(q.element('battle-combinations').textContent, /当前阵容再上场 1 位不同伙伴即可点亮「火系」/,
      '旧存档缺 bonds 时用 synergies 兜底');
    q.unchanged();
    const maxed = stateFixture({phase: 'battle'});
    maxed.last_battle.combinations = clone(empty);
    maxed.bonds = {note: '', entries: [{id: 'bond_flame', name: '火系', category: 'element', n: 4,
      tier: 4, next: null, need: 0, effect: '成员攻击与特攻+25%',
      thresholds: [{count: 4, effect: '成员攻击与特攻+25%'}], candidates: [], members: []}]};
    const m = await page(maxed);
    await m.click(m.element('fight-button'));
    await m.click(m.element('battle-skip'));
    assert.match(m.element('battle-combinations').textContent, /羁绊已点亮到当前可达档位/);
    m.unchanged();
  },
  async loadoutHighlights() {
    const fixture = stateFixture({phase: 'battle'});
    fixture.last_battle.combatants = [
      {idx: 0, team: 0, sid: 149, name: '快龙', star: 2, role: 'attack', range: 1, max_hp: 100,
        item: 'sash', item_name: '气势披带', technique: 'surf', technique_name: '冲浪'},
      {idx: 1, team: 0, sid: 143, name: '卡比兽', star: 3, role: 'defense', range: 1, max_hp: 100,
        item: 'leftovers', item_name: '剩饭', technique: null, technique_name: null},
    ];
    fixture.last_battle.loadout_highlights = [
      {kind: 'sash', team: 0, unit: '快龙', name: '气势披带', text: '致命伤保留 1 HP（1 次）'},
      {kind: 'technique', team: 0, unit: '快龙', name: '冲浪（技能机）', text: '1 次施放 · 共 35 伤害'},
      {kind: 'item', team: 1, unit: '敌方怪力', name: '专爱头巾', text: '攻击与特攻+35%'},
    ];
    const p = await page(fixture);
    await p.click(p.element('fight-button')); await p.click(p.element('battle-skip'));
    const stats = p.element('battle-statistics');
    const highlights = stats.querySelector('.loadout-highlights');
    assert.ok(highlights, '结算区展示装备与技能高光');
    const rows = highlights.querySelectorAll('.loadout-highlight');
    assert.equal(rows.length, 2, '敌方装备不进我方高光区');
    assert.match(highlights.querySelector('.loadout-highlights-title').textContent, /装备与技能高光/);
    assert.match(rows[0].querySelector('.buff-src').textContent, /披带/);
    assert.match(rows[0].textContent, /快龙 · 气势披带/);
    assert.match(rows[0].textContent, /致命伤保留 1 HP（1 次）/);
    assert.match(rows[1].querySelector('.buff-src').textContent, /技能机/);
    assert.match(rows[1].textContent, /冲浪（技能机）/);
    assert.match(rows[1].textContent, /1 次施放 · 共 35 伤害/);
    assert.doesNotMatch(highlights.textContent, /敌方怪力|专爱头巾/);
    const dragon = stats.querySelector('[data-stat-unit="0"]');
    assert.match(dragon.querySelector('.stat-loadout-item').textContent, /气势披带/, '统计行装备徽标用真实装备名');
    assert.match(dragon.querySelector('.stat-loadout-tm').textContent, /冲浪/, '统计行标注技能机');
    const snorlax = stats.querySelector('[data-stat-unit="1"]');
    assert.match(snorlax.querySelector('.stat-loadout-item').textContent, /剩饭/);
    assert.equal(snorlax.querySelector('.stat-loadout-tm'), null, '未学技能不出技能机徽标');
    assert.equal(stats.querySelector('[data-stat-unit="2"]').querySelector('.stat-loadouts'), null,
      '无装备无技能的单位不出徽标区');
    await p.click(button(p, 'battle', 'team', '1'));
    assert.match(stats.querySelector('[data-stat-unit="4"]').querySelector('.stat-loadout-item').textContent,
      /携带装备/, '缺少 combatants 记录时回退到通用装备标注');
    p.unchanged();
    const plain = stateFixture({phase: 'battle'});
    const q = await page(plain);
    await q.click(q.element('fight-button')); await q.click(q.element('battle-skip'));
    assert.equal(q.element('battle-statistics').querySelector('.loadout-highlights'), null,
      '没有高光数据时不渲染高光区');
    q.unchanged();
  },
  async lastResult() {
    const p = await page(stateFixture());
    const entry = p.element('last-result-button');
    assert.equal(entry.hidden, false, '存在已完成轮次时显示上轮战果入口');
    assert.match(entry.textContent, /上轮战果.*第 31 轮/);
    const before = p.snapshot();
    await p.click(entry);
    assert.equal(p.element('history-report-dialog').open, true, '入口重新打开最近一轮结算面板');
    assert.equal(p.element('history-report-title').textContent, '第 31 轮 · 战报');
    assert.match(p.element('history-statistics').innerHTML, /战斗统计/);
    assert.equal(p.element('history-report-round').value, '31');
    await p.click(p.element('history-report-close'));
    assert.equal(p.element('history-report-dialog').open, false);
    assert.equal(p.snapshot(), before);
    p.unchanged();
    const fresh = await page(stateFixture({round: 1, battles: 0, emptyHistory: true}));
    assert.equal(fresh.element('last-result-button').hidden, true, '第一轮之前隐藏入口');
    assert.equal(fresh.element('last-result-round').textContent, '');
    fresh.unchanged();
    const legacy = await page(stateFixture({round: 2, battles: 1, emptyHistory: true}));
    assert.equal(legacy.element('last-result-button').hidden, true, '旧存档没有战报记录时同样隐藏');
    legacy.unchanged();
  },
};
module.exports = {page, stateFixture, statistics, zeros, clone, ranking, button, selected, openHistory};
if (require.main === module)
  (async () => {assert.ok(cases[scenario], `Unknown scenario ${scenario}`); await cases[scenario]();})()
    .catch(error => {console.error(error); process.exitCode = 1;});
