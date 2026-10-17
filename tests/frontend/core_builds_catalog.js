/* Run the shipped catalog through real input/select/click handlers. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const original = JSON.stringify(data);
const source = fs.readFileSync(process.argv[2], 'utf8');
const familyMode = data.version === 'families_v2';
const expected = familyMode ? {covered: 150, species: 151, traits: 153} : {covered: 62, species: 62, traits: 65};
const decode = value => value.replace(/&amp;/g, '&');
async function page(search) {
  search += '&pool=' + data.version;
  const elements = new Map(), urls = [];
  class Element {
    constructor(id) { this.id = id; this.listeners = {}; this.buttons = []; this.value = ''; this.textContent = ''; this._html = ''; }
    get innerHTML() { return this._html; }
    set innerHTML(value) {
      this._html = value;
      this.buttons = [...value.matchAll(/<button[^>]*data-filter="([^"]+)"[^>]*aria-pressed="([^"]+)"/g)].map(match => ({
        dataset: {filter: match[1]}, pressed: match[2], closest: () => this.buttons.find(b => b.dataset.filter === match[1]),
        setAttribute(name, value) { if (name === 'aria-pressed') this.pressed = value; },
      }));
      if (this.id === 'hub-app') for (const id of ['library-filters', 'dex-filters', 'dex-generations', 'dex-traits']) {
        const section = value.match(new RegExp('<div id="' + id + '"[^>]*>([\\s\\S]*?)</div>'));
        if (section) element(id).innerHTML = section[1];
      }
    }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    focus() { this.focused = true; }
    filter(value) {
      const target = this.buttons.find(button => button.dataset.filter === value);
      assert.ok(target, value); this.listeners.click({target});
    }
    input(value) { this.value = value; this.listeners.input({target: this}); }
    change(value) { this.value = value; this.listeners.change({target: this}); }
  }
  function element(id) { if (!elements.has(id)) elements.set(id, new Element(id)); return elements.get(id); }
  const context = vm.createContext({
    location: {pathname: '/pokedex', search}, URLSearchParams, AbortController, setTimeout, clearTimeout,
    history: {replaceState: (_state, _title, url) => urls.push(url)},
    document: {getElementById: element, querySelector: () => element('head-mark'),
      querySelectorAll: selector => element(selector.split(' ')[0].slice(1)).buttons},
    fetch: async url => {assert.equal(url, '/api/portal/catalog?pool=' + data.version); return {ok: true, json: async () => data};},
  });
  vm.runInContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  const ids = () => [...element('library-results').innerHTML.matchAll(/<article class="build-card[^>]* id="build-([^"]+)"/g)].map(row => row[1]);
  const clear = () => element('hub-app').listeners.click({target: {closest: selector => selector === '[data-clear]' ? {} : null}});
  return {element, urls, ids, clear};
}
(async () => {
  const exact = await page('?tab=builds&core=34');
  const nidoking = data.builds.filter(build => build.core === 34).map(build => build.id);
  assert.deepEqual(exact.ids(), nidoking);
  assert.match(exact.element('library-results').innerHTML, /class="build-compare"/);
  assert.match(exact.element('build-core').innerHTML, /喷火龙 · 3 条核心路线/);
  assert.equal(exact.element('build-core').value, '34');
  assert.ok(data.builds.some(build => build.core !== 34 && [...build.teammates, ...build.gen2_partners].includes(34)) || nidoking.length >= 3);
  exact.element('build-core').change('6');
  assert.deepEqual(exact.ids(), data.builds.filter(build => build.core === 6).map(build => build.id));
  assert.equal(new URL('http://local' + exact.urls.at(-1)).searchParams.get('core'), '6');
  exact.element('library-filters').filter('startup');
  assert.deepEqual(exact.ids(), data.builds.filter(build => build.core === 6 && build.category === 'startup').map(build => build.id));
  exact.element('library-search').input('不存在的组合');
  assert.equal(exact.ids().length, 0);
  assert.match(exact.element('library-results').innerHTML, /由它担当核心/);
  exact.clear();
  assert.equal(exact.element('build-core').value, '');
  assert.equal(exact.element('library-search').value, '');
  assert.equal(exact.ids().length, data.builds.length);
  assert.equal(new URL('http://local' + exact.urls.at(-1)).searchParams.has('core'), false);
  const selected = await page('?tab=builds&core=6&build=charizard_inspiration');
  assert.match(selected.element('library-results').innerHTML, /class="build-card selected-build" id="build-charizard_inspiration"/);
  assert.equal(selected.ids().length, 3);
  const unknown = await page('?tab=builds&core=999');
  assert.equal(unknown.ids().length, 0);
  assert.match(unknown.element('build-core').innerHTML, /未收录核心 #999/);
  const legacy = await page('?tab=builds&q=喷火龙');
  assert.ok(legacy.ids().length > 3, 'legacy text search still finds teammate references');
  const pokedex = await page('?q=喷火龙');
  const html = pokedex.element('dex-results').innerHTML;
  assert.match(html, /作为核心 · 3 条路线/);
  assert.match(html, /参与队友联动/);
  const hrefs = [...html.matchAll(/href="([^"]+)"/g)].map(match => decode(match[1]));
  for (const id of ['charizard_attrition', 'charizard_growth', 'charizard_inspiration']) {
    const href = hrefs.find(href => new URL('http://local' + href).searchParams.get('build') === id);
    assert.ok(href, id);
    const url = new URL('http://local' + href);
    assert.equal(url.searchParams.get('core'), '6'); assert.equal(url.hash, '#build-' + id);
  }
  const supportOnly = await page('?q=电龙');
  assert.match(supportOnly.element('dex-results').innerHTML, /作为核心 · 0 条路线/);
  assert.match(supportOnly.element('dex-results').innerHTML, /参与队友联动/);
  assert.match(exact.element('library-results').innerHTML, /基础战法 · 本命启动/);
  assert.match(exact.element('library-results').innerHTML, /可选海克斯增益/);
  assert.match(exact.element('library-results').innerHTML, /进阶转化 · 需要这项强化/);
  const stageCards = [...exact.element('library-results').innerHTML.matchAll(/<article class="build-card[\s\S]*?<\/article>/g)];
  assert.equal(stageCards.length, data.builds.length);
  for (const [card] of stageCards) {
    assert.match(card, /class="build-base-stage"/);
    assert.match(card, /class="build-upgrade-stage"/);
    assert.match(card, /class="build-augment-stage"/);
  }
  const bonds = await page('?tab=bonds&category=tactic');
  const bondIds = () => [...bonds.element('library-results').innerHTML.matchAll(/id="entry-([^"]+)"/g)].map(row => row[1]);
  assert.deepEqual(bondIds(), data.bonds.filter(row => row.category === 'tactic').map(row => row.id));
  assert.match(bonds.element('library-results').innerHTML, new RegExp(`2<small>${familyMode ? '个不同家族' : '位不同伙伴'}`));
  assert.match(bonds.element('library-results').innerHTML, new RegExp(`4<small>${familyMode ? '个不同家族' : '位不同伙伴'}`));
  assert.match(bonds.element('library-results').innerHTML, /arena_bond_erosion/);
  bonds.element('library-search').input('喷火龙');
  assert.deepEqual(bondIds(), ['bond_erosion', 'bond_combo']);
  bonds.clear();
  assert.equal(bondIds().length, 25);
  assert.match(bonds.element('library-results').innerHTML, /羁绊战法与反制/);
  assert.match(bonds.element('library-results').innerHTML, /如何反制/);
  assert.match(bonds.element('library-results').innerHTML, /arena_bond_mindsong/);
  bonds.element('library-filters').filter('element');
  assert.equal(bondIds().length, 17);
  bonds.element('library-search').input('冰系');
  assert.deepEqual(bondIds(), ['ICE']);
  assert.match(bonds.element('library-results').innerHTML, familyMode ? /羁绊成员 · 5 个家族 · 6 个可用形态/ : /羁绊成员 · 5 位/);
  const pokemonBonds = await page('?q=连击');
  assert.match(pokemonBonds.element('dex-results').innerHTML, /巨钳螳螂/);
  assert.match(pokemonBonds.element('dex-results').innerHTML, /class="pokemon-bonds"/);
  assert.doesNotMatch(pokemonBonds.element('dex-results').innerHTML, /<h2>吉利蛋<\/h2>/);
  const covered = await page('?trait=covered');
  assert.equal([...covered.element('dex-results').innerHTML.matchAll(/<article class="pokemon-card"/g)].length, expected.covered);
  assert.match(covered.element('dex-results').innerHTML, /固定竞技特性 · 条件触发/);
  assert.match(covered.element('dex-results').innerHTML, /不消耗能量 · 不占本命或学习位/);
  assert.doesNotMatch(covered.element('dex-results').innerHTML, /尚未配置 ·/);
  covered.element('dex-traits').filter('uncovered');
  assert.equal([...covered.element('dex-results').innerHTML.matchAll(/<article class="pokemon-card"/g)].length, expected.species - expected.covered);
  assert.match(covered.element('dex-results').innerHTML, familyMode ? /鲤鱼王/ : /换个名称、属性、世代或定位试试/);
  if (familyMode) assert.match(covered.element('dex-results').innerHTML, /尚未配置 · 不会随机获得特性/);
  covered.clear();
  assert.equal([...covered.element('dex-results').innerHTML.matchAll(/<article class="pokemon-card"/g)].length, expected.species);
  assert.equal(covered.element('dex-traits').buttons.find(button => button.dataset.filter === 'all').pressed, 'true');
  const traits = await page('?tab=traits&category=attack');
  const traitIds = () => [...traits.element('library-results').innerHTML.matchAll(/id="entry-([^"]+)"/g)].map(row => row[1]);
  assert.deepEqual(traitIds(), data.traits.filter(row => row.category === 'attack').map(row => `${row.id}-${row.sid ?? row.species}`));
  assert.match(traits.element('trait-rules').innerHTML, new RegExp(`${expected.covered} / ${expected.species}`));
  traits.element('library-search').input('怪力');
  assert.deepEqual(traitIds(), ['trait_guts-68']);
  assert.match(traits.element('library-results').innerHTML, /本命仍然保留/);
  traits.clear();
  assert.equal(traitIds().length, expected.traits);
  const force = await page('?tab=builds&core=34&build=nidoking_force');
  const forceHtml = force.element('library-results').innerHTML;
  const forceCard = forceHtml.match(/<article class="build-card selected-build" id="build-nidoking_force"[\s\S]*?<\/article>/)?.[0];
  assert.ok(forceCard, 'the selected alternative trait build is linked directly');
  assert.match(forceCard, /本路线选择.*强行/);
  assert.doesNotMatch(forceCard.match(/<p class="build-trait-note">[\s\S]*?<\/p>/)[0], /毒刺/);
  assert.match(forceCard, /生命之玉/);
  assert.match(forceCard, /伙伴各自装配/);
  assert.match(forceCard, /宝石海星/);
  assert.match(forceCard, /接力线圈/);
  assert.match(forceHtml, /特性选择/);
  assert.match(forceHtml, /可选特性：毒刺 \/ 强行/);
  const rain = await page('?tab=builds&core=9&build=blastoise_rain_sustain');
  const rainCard = rain.element('library-results').innerHTML.match(/<article class="build-card selected-build" id="build-blastoise_rain_sustain"[\s\S]*?<\/article>/)?.[0];
  assert.ok(rainCard);
  assert.match(rainCard, /本路线选择.*雨盘/);
  assert.doesNotMatch(rainCard.match(/<p class="build-trait-note">[\s\S]*?<\/p>/)[0], /激流/);
  assert.match(rainCard, /潮湿岩石/);
  assert.match(rainCard, /打雷/);
  assert.match(rainCard, /涌流宝珠/);
  const optionalTraits = await page('?tab=traits&q=水箭龟');
  assert.match(optionalTraits.element('library-results').innerHTML, /只能选择一项/);
  assert.match(optionalTraits.element('library-results').innerHTML, /激流/);
  assert.match(optionalTraits.element('library-results').innerHTML, /雨盘/);
  const machamp = await page('?tab=builds&core=68');
  assert.deepEqual(machamp.ids(), ['machamp_sustain', 'machamp_cadence']);
  assert.match(machamp.element('library-results').innerHTML, /汲取之牙/);
  assert.match(machamp.element('library-results').innerHTML, /脉冲腕带/);
  assert.match(machamp.element('library-results').innerHTML, /固定特性 ·/);
  assert.equal(JSON.stringify(data), original, 'catalog browsing is read-only');
})().catch(error => {console.error(error); process.exitCode = 1;});
