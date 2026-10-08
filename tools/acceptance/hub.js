(() => {
  'use strict';
  const root = document.getElementById('hub-app');
  const path = location.pathname.replace(/\/+$/, '') || '/';
  const titles = { '/': '冒险入口', '/pokedex': '战术图鉴', '/guide': '玩法指南', '/tools': '开发与验收工具' };
  document.title = `PokeTactics · ${titles[path] || titles['/']}`;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const text = (value, fallback = '') => typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
  const arr = value => Array.isArray(value) ? value : [];
  const sprite = (sid, name = '', className = '') => /^\d+$/.test(String(sid)) ? `<img class="${escape(className)}" src="/demo/sprite/${encodeURIComponent(sid)}.png" alt="${escape(name)}" loading="lazy" width="96" height="96">` : '';
  const arrow = '<span class="arrow" aria-hidden="true">↗</span>';
  const footer = () => `<footer class="hub-footer"><span>POKETACTICS / FIELD NOTES</span><a class="text-link" href="/play">进入 / 继续冒险 ${arrow}</a></footer>`;
  const pageHead = (eyebrow, title, lead, number) => `<div class="page-head"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="lead">${lead}</p></div><span class="head-mark" aria-hidden="true">${number}</span></div>`;
  const loading = label => `<div class="page-loading" role="status"><span class="loading-ball" aria-hidden="true"></span><p>${escape(label)}</p></div>`;
  const failure = (message, retryName) => `<div class="status-box" role="alert"><h2>资料暂时没有送达</h2><p>${escape(message)}</p><button type="button" class="retry-button" data-retry="${escape(retryName)}">重新加载</button></div>`;
  const empty = (message, clear = true) => `<div class="status-box"><h2>没有找到匹配项</h2><p>${escape(message)}</p>${clear ? '<button type="button" class="clear-button" data-clear>清除筛选</button>' : ''}</div>`;
  const typeNames = { normal: '一般', fire: '火', water: '水', electric: '电', grass: '草', ice: '冰', fighting: '格斗', poison: '毒', ground: '地面', flying: '飞行', psychic: '超能力', bug: '虫', rock: '岩石', ghost: '幽灵', dragon: '龙', dark: '恶', steel: '钢', fairy: '妖精' };
  const roleNames = { tank: '坦克', frontline: '前排', bruiser: '战士', fighter: '战士', physical: '物理', physical_dps: '物理', ranged: '远程', ranged_dps: '远程', caster: '法师', mage: '法师', special: '法师', special_dps: '法师', assassin: '刺客', support: '辅助', healer: '辅助', control: '控制', carry: '输出', dps: '输出' };
  const targetingNames = { enemy: '对敌施放', ally: '对友援护', self: '自身姿态', field: '布置地形' };
  const translatedType = value => typeNames[text(value).toLowerCase()] || text(value);
  const roleKey = p => text(p.role_key, text(p.role, 'other'));
  const roleName = p => text(p.role_name, roleNames[roleKey(p)] || roleKey(p));
  let catalogPromise;
  async function fetchJson(url) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally { clearTimeout(timeout); }
  }
  function catalog(force = false) {
    if (force || !catalogPromise) catalogPromise = fetchJson('/api/portal/catalog').then(data => {
      if (data?.ok !== true || !['pokemon', 'techniques', 'augments', 'items', 'components', 'builds'].every(key => Array.isArray(data[key]))) throw new Error('Invalid catalog');
      return data;
    }).catch(error => { catalogPromise = undefined; throw error; });
    return catalogPromise;
  }
  function searchField(id, placeholder) {
    return `<label class="search-field" for="${id}"><span aria-hidden="true">⌕</span><span class="sr-only">${placeholder}</span><input id="${id}" type="search" placeholder="${placeholder}" autocomplete="off" spellcheck="false"></label>`;
  }
  function filterButton(value, label, active = false) {
    return `<button class="filter-button" type="button" data-filter="${escape(value)}" aria-pressed="${active}">${escape(label)}</button>`;
  }
  function statusCount(element, count, total, unit) {
    element.textContent = `${count} / ${total} ${unit}`;
  }

  function renderHome() {
    root.innerHTML = `<section class="welcome" aria-labelledby="welcome-title"><div class="welcome-copy"><p class="eyebrow">POKETACTICS · 准备出发</p><h1 id="welcome-title">小小阵容，<br><em>大大的冒险。</em></h1><p class="lead">收集宝可梦，搭配技能，排出你的小队。下一场自动战斗，就从这里开始。</p><a class="primary-link" href="/play">进入 / 继续冒险 <span aria-hidden="true">→</span></a><span class="welcome-note">已有进度会自动恢复 · 随时回来继续</span></div><div class="welcome-art" aria-label="宝可梦小队整装待发"><div class="art-grid"></div><div class="field-orbit"></div><div class="sprite-stage left">${sprite(6, '喷火龙')}</div><div class="sprite-stage right">${sprite(9, '水箭龟')}</div><div class="sprite-stage main">${sprite(26, '雷丘')}</div><div class="sprite-stage bottom">${sprite(94, '耿鬼')}</div><span class="art-spark one" aria-hidden="true">✦</span><span class="art-spark two" aria-hidden="true">+</span><span class="art-spark three" aria-hidden="true">✧</span><span class="art-tag">YOUR NEXT TEAM IS WAITING</span></div></section><div class="home-strip" aria-label="玩法速览"><div class="home-fact"><strong id="home-roster-count">48</strong><span>两代竞技宝可梦</span></div><div class="home-fact"><strong>3 × 6</strong><span>部署棋盘</span></div><div class="home-fact"><strong>7</strong><span>AI 对手</span></div><div class="home-fact"><strong>80</strong><span>满能量自动施放</span></div></div><section aria-labelledby="home-explore"><div class="section-heading"><h2 id="home-explore">先逛逛，再出发</h2><small>为下一场做好准备</small></div><div class="entry-list"><a class="entry" href="/pokedex"><span class="entry-no">01 / POKÉDEX</span><h2>翻开战术图鉴</h2><p>精灵、道具、技能机与海克斯，一起找到你的搭配。</p><span class="entry-arrow" aria-hidden="true">↗</span></a><a class="entry" href="/guide"><span class="entry-no">02 / FIELD GUIDE</span><h2>翻开冒险手册</h2><p>从购买与升星，到技能和强化。几分钟弄懂一局。</p><span class="entry-arrow" aria-hidden="true">↗</span></a><a class="entry" href="/tools"><span class="entry-no">03 / WORKSHOP</span><h2>走进训练工坊</h2><p>动画、对战模拟、数据与验收入口，都在这里。</p><span class="entry-arrow" aria-hidden="true">↗</span></a></div></section><div class="home-dex-preview"><div><p class="preview-label">下一位队友，会是谁？</p><a class="text-link" href="/pokedex">打开竞技图鉴 ${arrow}</a></div><div id="home-sprites" class="preview-sprites" aria-live="polite">${loading('正在集合小队…')}</div></div>${footer()}`;
    loadHomePreview();
  }
  async function loadHomePreview(force = false) {
    const target = document.getElementById('home-sprites');
    if (!target) return;
    target.innerHTML = '<span class="preview-label" role="status">正在集合小队…</span>';
    try {
      const data = await catalog(force);
      document.getElementById('home-roster-count').textContent = data.pokemon.length;
      target.innerHTML = data.pokemon.length ? data.pokemon.slice(0, 8).map(p => sprite(p.sid, text(p.name))).join('') : '<span class="preview-label">小队名单尚未收录</span>';
    } catch {
      target.innerHTML = '<span class="preview-label">小队名单加载失败</span><button type="button" class="retry-button" data-retry="home">重试</button>';
    }
  }

  const queryParams = new URLSearchParams(location.search);
  const sections = { pokemon: '精灵', traits: '特性', bonds: '羁绊', items: '道具', techniques: '技能机', augments: '海克斯', builds: '搭配参考' };
  const catalogKind = Object.hasOwn(sections, queryParams.get('tab')) ? queryParams.get('tab') : 'pokemon';
  const categoryNames = { attack: '攻击特性', defense: '防守特性', support: '辅助特性', damage: '输出', survival: '生存', startup: '启动', recovery: '回复', control: '状态 / 控制', economy: '经济', counter: '反制', element: '属性羁绊', tactic: '战术羁绊' };
  const categorySymbols = { damage: '↗', survival: '◇', startup: 'ϟ', recovery: '+', control: '◎', economy: '₊', counter: '⊘', element: '◇', tactic: '↔' };
  const catalogLink = (kind, query = '') => `/pokedex${kind === 'pokemon' && !query ? '' : '?' + new URLSearchParams({ ...(kind !== 'pokemon' ? {tab: kind} : {}), ...(query ? {q: query} : {}) })}`;
  const buildLink = (core, id = '') => '/pokedex?' + new URLSearchParams({ tab: 'builds', core: String(core), ...(id ? { build: id } : {}) }) + (id ? '#build-' + encodeURIComponent(id) : '');
  function catalogNavigation(active) {
    return `<nav class="catalog-navigation" aria-label="图鉴栏目">${Object.entries(sections).map(([kind, name]) => `<a href="${escape(catalogLink(kind))}"${active === kind ? ' aria-current="page"' : ''}>${name}</a>`).join('')}</nav>`;
  }
  const dexState = {
    query: queryParams.get('q') || '',
    role: ['attack', 'defense', 'support'].includes(queryParams.get('role')) ? queryParams.get('role') : 'all',
    generation: ['1', '2'].includes(queryParams.get('generation')) ? queryParams.get('generation') : 'all',
    trait: ['covered', 'uncovered'].includes(queryParams.get('trait')) ? queryParams.get('trait') : 'all',
    data: [], techniques: [], builds: [], bonds: [],
  };
  const buildSpecies = build => [build.core, ...arr(build.teammates), ...arr(build.gen2_partners)];
  function pokemonBuildRoutes(p) {
    const own = dexState.builds.filter(build => build.core === p.sid);
    const teammates = dexState.builds.filter(build => build.core !== p.sid && buildSpecies(build).includes(p.sid));
    return `<section class="pokemon-core-routes" aria-label="${escape(p.name)}的核心路线"><div class="pokemon-route-heading"><h3>作为核心 · ${own.length} 条路线</h3>${own.length > 1 ? `<a href="${escape(buildLink(p.sid))}">比较路线 ↗</a>` : ''}</div>${own.length ? own.map(build => `<a class="build-reference" href="${escape(buildLink(p.sid, build.id))}"><span>搭配参考 · ${escape(build.name)}<small>${escape(arr(build.tags).slice(0, 2).join(' · '))}</small></span>${arrow}</a>`).join('') : '<p class="route-empty">当前尚未收录专属核心构筑，可先查看本命技能与队友联动。</p>'}</section>${teammates.length ? `<details class="pokemon-teammate-routes"><summary>搭配参考 · 参与队友联动 · ${teammates.length} 套</summary>${teammates.map(build => { const core = dexState.data.find(row => row.sid === build.core); return `<a class="build-reference" href="${escape(buildLink(build.core, build.id))}"><span>${escape(build.name)}<small>核心：${escape(core?.name || build.core)}</small></span>${arrow}</a>`; }).join('')}</details>` : ''}`;
  }
  function pokemonBonds(p) {
    const rows = dexState.bonds.filter(bond => arr(p.bonds).includes(bond.id));
    return rows.length ? `<div class="pokemon-bonds" aria-label="${escape(p.name)}的羁绊">${rows.map(bond => `<a href="${escape(catalogLink('bonds', bond.name))}" title="${escape(bond.description)}">${escape(bond.name)}<small>${arr(bond.thresholds).map(tier => Number(tier.count)).join(' / ')}</small></a>`).join('')}</div>` : '';
  }
  function pokemonTrait(p) {
    const trait = p.trait;
    const options = arr(p.trait_options);
    if (!trait) return '<section class="trait-block pending-trait" aria-label="竞技特性"><p class="skill-label">竞技特性</p><p class="skill-description">尚未配置 · 不会随机获得特性。</p></section>';
    const selectable = options.length > 1;
    return `<section class="trait-block" aria-label="竞技特性"><p class="skill-label"><span class="trait-mark" aria-hidden="true">◎</span>${selectable ? "互斥可选特性 · 准备期免费切换" : "固定竞技特性 · 条件触发"}</p>${(selectable ? options : [trait]).map(option => `<div class="trait-option"><a class="trait-name" href="${escape(catalogLink('traits', option.name))}">${escape(option.name)} ${option.id === trait.id && selectable ? '<small>默认</small>' : ''} ${arrow}</a><p class="skill-description">${escape(option.description)}</p></div>`).join('')}<small>不消耗能量 · 不占本命或学习位${selectable ? ' · 每只同时只启用一项，实际选择在试玩详情中查看' : ''}</small></section>`;
  }
  function pokemonCard(p) {
    const skill = p.native_skill && typeof p.native_skill === 'object' ? p.native_skill : {};
    const name = text(p.name, `宝可梦 ${text(p.sid)}`);
    const skillName = text(skill.name, text(p.skill_name, text(p.move, '原生技能')));
    const skillType = translatedType(skill.type || p.skill_type);
    const skillDescription = text(skill.description, text(p.skill_description, '能量积累至 80 时自动释放。'));
    const cost = Number.isFinite(Number(p.cost)) ? `${Number(p.cost)} 金币` : '费用待收录';
    const ranged = p.ranged === true || p.ranged === 1 || p.ranged === 'true';
    const learnable = dexState.techniques.filter(t => arr(p.learnable).includes(t.id)).map(t => t.name).join('、');
    return `<article class="pokemon-card"><div class="pokemon-card-top"><div class="pokemon-portrait">${sprite(p.sid, name)}<span class="pokemon-id">#${escape(String(p.sid).padStart(3,'0'))}</span></div><div><h2>${escape(name)}</h2><div class="type-tags">${arr(p.types).map(type => `<span class="type-tag">${escape(translatedType(type))}</span>`).join('')}</div><div class="card-facts"><span class="fact-tag">${escape(cost)}</span><span class="fact-tag">${ranged ? '远程' : '近战'} · ${escape(p.range)} 格</span><span class="fact-tag">${escape(roleName(p))}</span><span class="fact-tag">${escape(text(p.generation_name))}</span>${p.pool_group === "第一世代独立精灵" ? '<span class="fact-tag">首代独立精灵</span>' : ""}</div></div></div><p class="role-note">${escape(text(p.role_description, '依照属性与技能安排站位，搭配你的小队。'))}</p>${pokemonTrait(p)}<div class="skill-block"><p class="skill-label">原生技能（80 能量，按条件施放）</p><p class="skill-name">${escape(skillName)}<span>${escape(skillType)}${Number(skill.power) > 0 ? ` · 威力 ${escape(skill.power)}` : ''} · 能量 80</span></p><div class="type-tags"><span class="fact-tag">${escape(targetingNames[skill.targeting] || '对敌施放')}</span>${skill.behavior ? `<span class="fact-tag">${escape(skill.behavior)}</span>` : ''}</div><p class="skill-description">${escape(skillDescription)}</p></div><div class="skill-block"><p class="skill-label">学习技能（可更换，一场一次）</p><p class="learned-note">独立学习槽 · 可通过技能机装配</p><p class="skill-description">可学：${escape(learnable || '暂无相容技能')}。个体已学习的技能请在冒险中查看。</p></div><a class="build-reference" href="${escape('/animation-lab?' + new URLSearchParams({mode:'arena',species:p.sid}))}">预览动作 · 竞技战场 ${arrow}</a>${pokemonBonds(p)}${pokemonBuildRoutes(p)}</article>`;
  }
  function renderPokedex() {
    root.innerHTML = `${pageHead('POKÉDEX / COMPETITIVE', '每一位，都有自己的战法。', '第一世代30种，加上18种第二世代伙伴。查看48位队员的属性、定位与本命技能与可用特性，按世代、定位和特性覆盖组合筛选。', '048')}${catalogNavigation('pokemon')}<div class="search-panel">${searchField('dex-search', '搜索宝可梦、属性、特性或技能')}<div id="dex-generations" class="filter-list" role="group" aria-label="按世代筛选">${filterButton('all', '全部世代', dexState.generation === 'all')}${filterButton('1', '第一世代', dexState.generation === '1')}${filterButton('2', '第二世代', dexState.generation === '2')}</div><div id="dex-filters" class="filter-list" role="group" aria-label="按定位筛选">${filterButton('all', '全部定位', dexState.role === 'all')}</div><div id="dex-traits" class="filter-list" role="group" aria-label="按特性覆盖筛选">${filterButton('all', '全部精灵', dexState.trait === 'all')}${filterButton('covered', '已配置特性', dexState.trait === 'covered')}${filterButton('uncovered', '尚未配置特性', dexState.trait === 'uncovered')}</div></div><div class="result-meta"><span id="dex-count" role="status" aria-live="polite">正在读取竞技名册…</span><span>每只宝可梦拥有两个独立技能槽</span></div><div id="dex-results">${loading('正在读取宝可梦资料…')}</div><div class="catalog-note"><p>这是当前竞技池。原生技能跟随种类，学习技能跟随你在冒险中培养的个体；图鉴不代表当前存档的学习状态。</p><a class="secondary-link" href="/roster">84 只经典宝可梦 ${arrow}</a></div>${footer()}`;
    document.getElementById('dex-search').value = dexState.query;
    document.getElementById('dex-search').addEventListener('input', event => { dexState.query = event.target.value; updatePokedex(); });
    document.getElementById('dex-filters').addEventListener('click', event => {
      const button = event.target.closest('[data-filter]');
      if (!button) return;
      dexState.role = button.dataset.filter;
      document.querySelectorAll('#dex-filters [data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      updatePokedex();
    });
    document.getElementById('dex-generations').addEventListener('click', event => {
      const button = event.target.closest('[data-filter]');
      if (!button) return;
      dexState.generation = button.dataset.filter;
      document.querySelectorAll('#dex-generations [data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      updatePokedex();
    });
    document.getElementById('dex-traits').addEventListener('click', event => {
      const button = event.target.closest('[data-filter]');
      if (!button) return;
      dexState.trait = button.dataset.filter;
      document.querySelectorAll('#dex-traits [data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      updatePokedex();
    });
    loadPokedex();
  }
  async function loadPokedex(force = false) {
    const target = document.getElementById('dex-results');
    target.innerHTML = loading('正在读取宝可梦资料…');
    try {
      const data = await catalog(force);
      document.querySelector('.head-mark').textContent = String(data.pokemon.length).padStart(3, '0');
      dexState.data = data.pokemon;
      dexState.techniques = data.techniques;
      dexState.builds = data.builds;
      dexState.bonds = arr(data.bonds);
      const roles = [...new Map(data.pokemon.map(p => [roleKey(p), roleName(p)])).entries()];
      document.getElementById('dex-filters').innerHTML = filterButton('all', '全部定位', dexState.role === 'all') + roles.map(([key, label]) => filterButton(key, label, dexState.role === key)).join('');
      updatePokedex();
    } catch {
      document.getElementById('dex-count').textContent = '竞技名册加载失败';
      target.innerHTML = failure('检查服务连接后重试，或先打开经典图鉴。', 'pokedex');
    }
  }
  function updatePokedex() {
    const query = dexState.query.trim().toLocaleLowerCase();
    const filtered = dexState.data.filter(p => {
      const skill = p.native_skill || {};
      const search = [...arr(p.trait_options).flatMap(option => [option.id, option.name, option.description, ...arr(option.tags)]), p.trait?.id, p.trait?.name, p.trait?.description, ...arr(p.trait?.tags), p.name, p.sid, p.cost, p.role_description, roleName(p), p.generation_name, p.pool_group, ...arr(p.types).map(translatedType), skill.name, skill.description, skill.behavior, ...dexState.bonds.filter(bond => arr(p.bonds).includes(bond.id)).map(bond => bond.name), ...arr(skill.tags), targetingNames[skill.targeting], p.skill_name, p.skill_description, ...dexState.builds.filter(build => build.core === p.sid).flatMap(build => [build.name, build.trigger, ...arr(build.tags)]), ...dexState.techniques.filter(t => arr(p.learnable).includes(t.id)).map(t => t.name)].map(value => text(value)).join(' ').toLocaleLowerCase();
      return (dexState.role === 'all' || roleKey(p) === dexState.role) && (dexState.generation === 'all' || String(p.generation) === dexState.generation) && (dexState.trait === 'all' || (dexState.trait === 'covered' ? Boolean(p.trait) : !p.trait)) && (!query || search.includes(query));
    });
    statusCount(document.getElementById('dex-count'), filtered.length, dexState.data.length, '位宝可梦');
    document.getElementById('dex-results').innerHTML = filtered.length ? `<div class="pokemon-grid">${filtered.map(pokemonCard).join('')}</div>` : empty(dexState.data.length ? '换个名称、属性、世代或定位试试。' : '竞技名册暂时为空。', dexState.data.length > 0);
  }

  const libraryState = {
    query: queryParams.get('q') || '', category: categoryNames[queryParams.get('category')] ? queryParams.get('category') : 'all',
    core: /^\d+$/.test(queryParams.get('core') || '') ? String(Number(queryParams.get('core'))) : '',
    selectedBuild: /^[a-z][a-z0-9_]*$/.test(queryParams.get('build') || '') ? queryParams.get('build') : '',
    data: [], catalog: null,
  };
  function recordBuildFilters() {
    if (catalogKind !== 'builds' || typeof history === 'undefined' || !history.replaceState) return;
    const params = new URLSearchParams({ tab: 'builds' });
    if (libraryState.core) params.set('core', libraryState.core);
    if (libraryState.query) params.set('q', libraryState.query);
    if (libraryState.category !== 'all') params.set('category', libraryState.category);
    if (libraryState.selectedBuild) params.set('build', libraryState.selectedBuild);
    history.replaceState(null, '', '/pokedex?' + params);
  }
  function buildCoreSelector() {
    return '<label class="build-core-filter" for="build-core"><span>作为核心的宝可梦</span><select id="build-core"><option value="">全部核心</option></select></label>';
  }

  const recipeState = {
    view: queryParams.get('view') === 'recipes' ? 'recipes' : 'directory',
    component: queryParams.get('component') || '', a: queryParams.get('a') || '', b: queryParams.get('b') || '',
    mounted: false, matches: new Set(),
  };
  const componentSymbols = { band: '↗', hardstone: '◆', magnet: 'ϟ', shoes: '➜', bell: '♧', charcoal: '♨', mysticwater: '◒', spark: '✶' };
  const recipeKey = (a, b) => [a, b].sort().join(':');
  function recipeLink(options = {}) {
    return '/pokedex?' + new URLSearchParams({ tab: 'items', view: 'recipes', ...options });
  }
  function recipePairs(data) {
    const components = new Set(data.components.map(part => part.id));
    return data.items.flatMap(item => arr(item.recipes).filter(pair => pair.length === 2 && pair.every(part => components.has(part.id))).map(pair => ({ item, pair })));
  }
  function recipeLookup(data) {
    const lookup = new Map();
    for (const { item, pair } of recipePairs(data)) {
      const key = recipeKey(pair[0].id, pair[1].id);
      const results = lookup.get(key) || [];
      if (!results.some(row => row.id === item.id)) results.push(item);
      lookup.set(key, results);
    }
    return lookup;
  }
  function recipeIngredients(pair) {
    return pair[0].id === pair[1].id ? `<span>${escape(pair[0].name)} <strong>× 2</strong></span>` : pair.map(part => `<span>${escape(part.name)}</span>`).join('<span class="recipe-plus" aria-hidden="true">＋</span>');
  }
  function itemViewSwitch() {
    return `<div class="item-view-switch" role="group" aria-label="道具浏览方式"><button type="button" data-item-view="directory" aria-pressed="${recipeState.view === 'directory'}">道具目录</button><button type="button" data-item-view="recipes" aria-pressed="${recipeState.view === 'recipes'}">装备合成图 <span aria-hidden="true">↗</span></button></div>`;
  }
  function recipeMatrix() {
    const data = libraryState.catalog, lookup = recipeLookup(data);
    const header = part => `<button type="button" class="recipe-component" data-recipe-component="${escape(part.id)}" aria-pressed="${recipeState.component === part.id}" aria-label="查看${escape(part.name)}的全部合成配方"><span class="component-symbol" aria-hidden="true">${escape(componentSymbols[part.id] || '+')}</span><span>${escape(part.name)}</span></button>`;
    return `<section class="recipe-workspace" aria-labelledby="recipe-title"><div class="recipe-workspace-heading"><div><p class="eyebrow">CRAFTING / FIELD TABLE</p><h2 id="recipe-title">两件组件，一件装备。</h2><p>点行列上的组件查看所有去向；点交叉格查看具体成品。行列顺序不影响结果。</p></div><div class="recipe-facts"><span><strong>${data.components.length} × ${data.components.length}</strong>组件矩阵</span><span><strong>${lookup.size}</strong>有效配方</span><span><strong>${data.items.length}</strong>成品装备</span></div></div><div class="recipe-legend"><span><i class="recipe-legend-filled" aria-hidden="true"></i>有配方</span><span><i class="recipe-legend-empty" aria-hidden="true">—</i>无竞技配方</span><span>对角线需同组件 <strong>× 2</strong></span><span class="recipe-scroll-hint">↔ 左右滑动查看全部组件</span></div><div id="recipe-filter-note" class="recipe-filter-note" hidden></div><div class="recipe-scroll" role="region" aria-label="装备合成矩阵，可横向滚动" tabindex="0"><table id="recipe-matrix" class="recipe-matrix"><caption class="sr-only">${data.components.length}种组件的完整对称合成图。空白组合没有当前竞技配方，不会合成进化石。</caption><thead><tr><th scope="col" class="recipe-corner"><span>组件</span><span aria-hidden="true">＋</span></th>${data.components.map(part => `<th scope="col">${header(part)}</th>`).join('')}</tr></thead><tbody>${data.components.map(a => `<tr><th scope="row">${header(a)}</th>${data.components.map(b => {
      const results = lookup.get(recipeKey(a.id, b.id)) || [];
      const names = results.map(item => item.name).join('、');
      const repeat = a.id === b.id;
      return `<td><button type="button" class="recipe-cell${results.length ? ' has-recipe' : ' no-recipe'}${results.some(item => item.global_cap != null) ? ' limited-recipe' : ''}" data-recipe-a="${escape(a.id)}" data-recipe-b="${escape(b.id)}" data-recipe-items="${escape(results.map(item => item.id).join(' '))}" aria-pressed="false" aria-label="${escape(a.name)}${repeat ? '两件' : '加' + escape(b.name)}：${escape(names || '无竞技配方')}">${results.length ? `<span class="recipe-result-symbol" aria-hidden="true">${escape(categorySymbols[results[0].category] || '◇')}</span><span class="recipe-cell-name">${escape(names)}</span>` : '<span class="recipe-dash" aria-hidden="true">—</span>'}${repeat ? '<span class="recipe-double">× 2</span>' : ''}${results.some(item => item.global_cap != null) ? '<span class="recipe-limit-dot" aria-hidden="true"></span>' : ''}</button></td>`;
    }).join('')}</tr>`).join('')}</tbody></table></div><section id="recipe-detail" class="recipe-detail" tabindex="-1" aria-live="polite" aria-label="选中配方详情"></section><p class="recipe-footnote">这里查阅配方与效果。在试玩的「战前准备 → 道具装备」中，备齐组件后合成；同组件配方需要两份库存。</p></section>`;
  }
  function recipeDetailCard(item, pair = null) {
    return `<article class="recipe-result-card ${escape(item.category)}"><div class="recipe-result-heading"><span class="resource-icon" aria-hidden="true">${escape(categorySymbols[item.category] || '◇')}</span><div><span class="catalog-kind">${escape(categoryNames[item.category])}装备${item.global_cap != null ? ` · 全场最多 ${escape(item.global_cap)} 件` : ''}</span><h3>${escape(item.name)}</h3></div></div>${pair ? `<p class="recipe-selected-pair">${recipeIngredients(pair)}</p>` : ''}<p class="recipe-result-effect">${escape(item.description)}</p><div class="recipe-all-pairs"><h4>这件装备的全部配方</h4>${arr(item.recipes).map(parts => `<button type="button" data-recipe-a="${escape(parts[0].id)}" data-recipe-b="${escape(parts[1].id)}" aria-label="查看${escape(parts[0].name)}与${escape(parts[1].name)}的合成格">${recipeIngredients(parts)}<span aria-hidden="true">↗</span></button>`).join('')}</div><p class="resource-source">${escape(item.source)}<br>${escape(item.copy_rule)}</p><a class="text-link" href="${escape(catalogLink('items', item.name))}#entry-${escape(item.id)}" data-recipe-item="${escape(item.id)}">查看完整道具卡片 ${arrow}</a></article>`;
  }
  function updateRecipeSelection() {
    const data = libraryState.catalog;
    if (!data) return;
    const lookup = recipeLookup(data), selected = recipeState.a && recipeState.b ? recipeKey(recipeState.a, recipeState.b) : '';
    document.querySelectorAll('#recipe-matrix [data-recipe-a]').forEach(button => {
      const { recipeA: a, recipeB: b, recipeItems = '' } = button.dataset;
      const isSelected = selected === recipeKey(a, b);
      button.setAttribute('aria-pressed', String(isSelected));
      button.classList.toggle('is-selected', isSelected);
      button.classList.toggle('is-related', Boolean(recipeState.component && (a === recipeState.component || b === recipeState.component)));
      button.classList.toggle('is-muted', Boolean(recipeItems && !recipeItems.split(' ').some(id => recipeState.matches.has(id))));
    });
    document.querySelectorAll('#recipe-matrix [data-recipe-component]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.recipeComponent === recipeState.component)));
    const filterNote = document.getElementById('recipe-filter-note');
    filterNote.hidden = recipeState.matches.size === data.items.length;
    filterNote.innerHTML = filterNote.hidden ? '' : `<p>匹配 ${recipeState.matches.size} / ${data.items.length} 件成品；其他配方淡化显示，仍可点选查看。</p><button type="button" class="recipe-reset" data-clear>清除筛选</button>`;
    const target = document.getElementById('recipe-detail');
    if (selected) {
      const pair = [recipeState.a, recipeState.b].map(id => data.components.find(part => part.id === id));
      if (pair.some(part => !part)) { recipeState.a = ''; recipeState.b = ''; return updateRecipeSelection(); }
      const results = lookup.get(selected) || [];
      target.innerHTML = `<div class="recipe-detail-heading"><div><span class="catalog-kind">已选择组件组合</span><h3>${escape(pair[0].name)} ${pair[0].id === pair[1].id ? '× 2' : '＋ ' + escape(pair[1].name)}</h3></div><button type="button" class="recipe-reset" data-recipe-reset>清除选择</button></div>${results.length ? `<div class="recipe-detail-grid">${results.map(item => recipeDetailCard(item, pair)).join('')}</div>` : '<div class="recipe-no-result"><span aria-hidden="true">—</span><div><h3>这个组合没有竞技配方</h3><p>当前竞技规则不会用这两件组件生成成品，也不合成进化石。保留组件，换一个组合看看。</p></div></div>'}`;
    } else if (recipeState.component) {
      const part = data.components.find(row => row.id === recipeState.component);
      if (!part) { recipeState.component = ''; return updateRecipeSelection(); }
      const pairs = recipePairs(data).filter(row => row.pair.some(ingredient => ingredient.id === part.id));
      target.innerHTML = `<div class="recipe-detail-heading"><div><span class="catalog-kind">选中组件 · ${pairs.length} 条可用配方</span><h3>${escape(part.name)}，可以这样用。</h3></div><button type="button" class="recipe-reset" data-recipe-reset>清除选择</button></div><div class="recipe-detail-grid">${pairs.map(({ item, pair }) => recipeDetailCard(item, pair)).join('')}</div>`;
    } else {
      target.innerHTML = '<div class="recipe-instruction"><span aria-hidden="true">＋</span><div><h3>选中一格，查它的配方与效果。</h3><p>也可以先点一个组件，查看它能合成的所有装备。搜索和用途筛选会淡化不匹配的成品，矩阵仍保留完整组合。</p></div></div>';
    }
  }
  function recordItemView() {
    if (typeof history === 'undefined') return;
    const params = new URLSearchParams({ tab: 'items' });
    if (recipeState.view === 'recipes') {
      params.set('view', 'recipes');
      if (recipeState.component) params.set('component', recipeState.component);
      if (recipeState.a && recipeState.b) { params.set('a', recipeState.a); params.set('b', recipeState.b); }
    }
    if (libraryState.query) params.set('q', libraryState.query);
    history.replaceState(null, '', '/pokedex?' + params);
  }
  function setItemView(view) {
    recipeState.view = view === 'recipes' ? 'recipes' : 'directory';
    document.querySelectorAll('[data-item-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.itemView === recipeState.view)));
    document.getElementById('component-directory').hidden = recipeState.view === 'recipes';
    updateResourceCatalog();
    recordItemView();
  }
  const libraryCopy = {
    items: ['ITEMS / ONE SLOT, MANY CHOICES', '为队员选一件趁手的道具。', '输出、启动、生存或反制。普通装备可重复获得，多名精灵可携带同名装备；每只精灵一个装备位，可以卸下转移。', '27', '搜索道具、效果、组件或推荐精灵'],
    traits: ['TRAITS / SPECIES IDENTITY', '特性，让同伴多一份本领。', '当前14位精灵共有16项竞技特性。尼多王与水箭龟可在准备期免费选择一项，其余已配置伙伴保留固定特性；满足条件生效，不占本命或学习槽。', '16', '搜索特性、触发条件或精灵'],
    bonds: ['BONDS / TEAM BEFORE LOADOUT', '不同伙伴，拼出一套战法。', '属性提供队伍基础，战术羁绊按2 / 4位不同伙伴分档。冰、龙、幽灵可从1位启动轻量专长；其他属性按各自门槛激活。同物种不同星级不会重复计数。', '↔', '搜索羁绊、门槛、效果或成员'],
    augments: ['AUGMENTS / STRENGTHEN YOUR TEAM', '基础阵容先启动，再选一份强化。', '第 1、7、13 轮从三个选项中选择一个，本局最多三次选择。数值增益加强现有阵容；特定效果转化仍需相应海克斯，同一强化不能重复选择。', '11', '搜索海克斯、效果或推荐精灵'],
    techniques: ['TECHNIQUES / COMPLETE THE LOADOUT', '补上核心需要的那一招。', '有库存时消耗一台技能机免费学习，没有库存时花 2 金币；替换不返还旧技能。独立学习位不覆盖原生技能，每场最多一次。', '09', '搜索技能机、触发条件或可学精灵'],
    builds: ['BUILD NOTES / MAKE IT WORK TOGETHER', '先让伙伴配合，再把路线强化。', '每条路线先列本命技能能组成的基础战法，再列装备、学习技能与海克斯强化。基础阵容不必等待整套推荐齐全；反击、传播和效果转化仍需各自明确的道具或海克斯条件。', '↔', '搜索组合、精灵、道具、技能或海克斯'],
  };
  function renderResourceCatalog() {
    const [eyebrow, title, lead, mark, placeholder] = libraryCopy[catalogKind];
    document.title = `PokeTactics · ${sections[catalogKind]}目录`;
    root.innerHTML = `${pageHead(eyebrow, title, lead, mark)}${catalogNavigation(catalogKind)}${catalogKind === 'traits' ? '<aside id="trait-rules" class="trait-rules" aria-label="竞技特性规则"></aside>' : ''}${catalogKind === 'items' ? itemViewSwitch() + '<aside id="equipment-rules" class="equipment-rules" aria-label="装备数量与装备位规则"></aside>' : ''}<div class="search-panel">${searchField('library-search', placeholder)}${catalogKind === 'builds' ? buildCoreSelector() : ''}<div id="library-filters" class="filter-list" role="group" aria-label="按用途筛选">${filterButton('all', '全部', true)}</div></div><div class="result-meta"><span id="library-count" role="status" aria-live="polite">正在整理${sections[catalogKind]}…</span><span>${catalogKind === 'builds' ? '按对手和站位灵活调整' : '当前竞技规则'}</span></div><div id="component-directory"></div><div id="library-results">${loading('正在读取目录…')}</div><div class="catalog-note"><p>${catalogKind === 'items' ? '胜利获得 2 份随机战利品，失利或平局 1 份，可能是成品、组件或技能机。第3、6轮实际结算后额外提供组件八选一，可定向补配方。幸运蛋只能合成，当前竞技池不包含进化石。' : catalogKind === 'builds' ? '这些是组队思路。先看本轮对手的免疫、站位与治疗，再选装备、学习技能或调整阵容。对比场景会加入其他合法伙伴与装配，用于观察相关联动；与卡片推荐不一定完全一致。' : '图鉴用于查阅和比较。当前拥有的技能机、装备与已选海克斯，请在试玩的战前准备中查看。'}</p><a class="secondary-link" href="${catalogKind === 'builds' ? '/play' : '/pokedex?tab=builds'}">${catalogKind === 'builds' ? '去试玩这套思路' : '查看搭配参考'} ${arrow}</a></div>${footer()}`;
    document.getElementById('library-search').value = libraryState.query;
    document.getElementById('library-search').addEventListener('input', event => { libraryState.query = event.target.value; libraryState.selectedBuild = ''; recordBuildFilters(); updateResourceCatalog(); });
    if (catalogKind === 'builds') document.getElementById('build-core').addEventListener('change', event => {
      libraryState.core = event.target.value; libraryState.selectedBuild = ''; recordBuildFilters(); updateResourceCatalog();
    });
    document.getElementById('library-filters').addEventListener('click', event => {
      const button = event.target.closest('[data-filter]');
      if (!button) return;
      libraryState.category = button.dataset.filter;
      libraryState.selectedBuild = ''; recordBuildFilters();
      document.querySelectorAll('#library-filters [data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      updateResourceCatalog();
    });
    loadResourceCatalog();
  }
  function pokemonReferences(ids, data) {
    return arr(ids).map(sid => data.pokemon.find(p => p.sid === sid)).filter(Boolean).map(p => `<a class="pokemon-reference" href="${escape(catalogLink('pokemon', p.name))}">${sprite(p.sid, '')}<span>${escape(p.name)}</span></a>`).join('');
  }
  function resourceName(kind, id) {
    const row = arr(libraryState.catalog?.[kind]).find(row => row.id === id);
    return row?.name || '';
  }
  function resourceReference(kind, id, label) {
    const name = resourceName(kind, id);
    return `<a href="${escape(catalogLink(kind, name))}"><small>${label}</small><strong>${escape(name)}</strong><span aria-hidden="true">↗</span></a>`;
  }
  function buildTrait(core, build) {
    return arr(core?.trait_options).find(option => option.id === build.trait) || core?.trait;
  }
  function teammateLoadouts(build) {
    const data = libraryState.catalog;
    return arr(build.teammate_loadouts).map(loadout => {
      const teammate = data.pokemon.find(p => p.sid === loadout.sid);
      if (!teammate) return '';
      const trait = arr(teammate.trait_options).find(option => option.id === loadout.trait);
      return `<div class="teammate-loadout"><a class="pokemon-reference" href="${escape(catalogLink('pokemon', teammate.name))}">${sprite(teammate.sid, '')}<strong>${escape(teammate.name)}</strong></a>${trait ? `<p class="build-trait-note">选择 ${escape(trait.name)}</p>` : ''}<div class="build-loadout">${loadout.item ? resourceReference('items', loadout.item, '该伙伴的装备') : ''}${loadout.technique ? resourceReference('techniques', loadout.technique, '该伙伴的学习位') : ''}</div></div>`;
    }).join('');
  }
  function buildCard(build) {
    const data = libraryState.catalog;
    const core = data.pokemon.find(p => p.sid === build.core);
    const base = build.base_stage || {};
    const trait = buildTrait(core, build);
    const upgrades = build.upgrades || {};
    const transition = build.transition;
    const transitionHtml = transition ? `<section class="build-transition-stage"><h3>低费过渡 · 先上1费伙伴</h3><div class="pokemon-references">${pokemonReferences(transition.members, data)}</div><p>${escape(transition.summary)}</p><div class="build-base-bonds">${arr(transition.bonds?.entries).filter(row => row.tier).map(row => `<a href="${escape(catalogLink('bonds', row.name))}" title="${escape(row.effect)}">${escape(row.name)} · ${Number(row.tier)}种档</a>`).join('')}</div></section>` : '';
    return `<article class="build-card${libraryState.selectedBuild === build.id ? ' selected-build' : ''}" id="build-${escape(build.id)}" tabindex="-1"><div class="build-card-header">${sprite(core.sid, core.name)}<div><span class="catalog-kind">${escape(categoryNames[build.category])}路线</span><h2>${escape(build.name)}</h2><a href="${escape(catalogLink('pokemon', core.name))}">${escape(core.name)} · ${Number(core.cost)}费 · ${escape(core.native_skill.name)} ↗</a></div></div>${trait ? `<p class="build-trait-note">${arr(core.trait_options).length > 1 ? "本路线选择" : "固定特性"} · <a href="${escape(catalogLink('traits', trait.name))}">${escape(trait.name)}</a> · ${escape(trait.trigger)}${arr(core.trait_options).length > 1 ? "。准备期免费切换，每只只启用一项。" : "。满足条件自动触发。"}</p>` : ""}${transitionHtml}<section class="build-base-stage"><h3><span>01</span>基础战法 · 本命启动</h3><p>${escape(base.summary)}</p><div class="pokemon-references">${pokemonReferences(base.members, data)}</div><div class="build-base-bonds">${arr(base.bonds?.entries).filter(row => row.tier).map(row => `<a href="${escape(catalogLink('bonds', row.name))}" title="${escape(row.effect)}">${escape(row.name)} · ${Number(row.tier)}种档</a>`).join('')}</div><p class="build-substitutes"><strong>可替代伙伴</strong>${escape(base.substitutes)}</p></section><section class="build-upgrade-stage"><h3><span>02</span>按战局补强</h3><p class="loadout-owner">${escape(core.name)}的一个装备位 + 一个学习位</p><div class="build-loadout">${resourceReference('items', build.item, '核心装备')}${resourceReference('techniques', build.technique, '核心学习位')}</div><p>${escape(upgrades.item)}</p><p>${escape(upgrades.technique)}</p></section><section class="build-augment-stage"><div class="build-loadout">${resourceReference('augments', build.augment, build.augment_conversion ? '进阶转化 · 需要这项强化' : '可选海克斯增益')}</div><p>${escape(upgrades.augment)}</p></section>${build.trigger ? `<p class="build-trigger"><strong>进阶路线的关键条件</strong>${escape(build.trigger)}</p>` : ''}<details class="build-mechanics"><summary>完整强化路线怎样生效</summary><ol class="build-steps">${arr(build.steps).map(step => `<li>${escape(step)}</li>`).join('')}</ol></details><div class="build-teammates"><h3>完整路线队友与站位</h3><div class="pokemon-references">${pokemonReferences(build.teammates, data)}</div><p>${escape(build.positioning)}</p>${arr(build.teammate_loadouts).length ? `<section class="build-teammate-loadouts" aria-label="伙伴装配"><h4>伙伴各自装配 · 不占核心的位置</h4>${teammateLoadouts(build)}</section>` : ""}</div><div class="build-response"><h3>对手怎么应对</h3><p>${escape(build.counter)}</p></div><details class="build-alternative"><summary>换一种取舍</summary><p>${escape(build.alternative)}</p></details>${build.scenario ? `<a class="build-reference" href="${escape('/anim?' + new URLSearchParams({mode:'arena',seed:7,scenario:build.scenario}))}">观看相关路线的对比场景 ${arrow}</a>` : ''}${arr(build.gen2_partners).length ? `<div class="build-teammates"><h3>第二世代搭配</h3><div class="pokemon-references">${pokemonReferences(build.gen2_partners, data)}</div><p>${escape(build.gen2_advice)}</p></div>` : ''}</article>`;
  }
  function traitCard(row) {
    const data = libraryState.catalog;
    const pokemon = data.pokemon.find(p => p.sid === (row.sid ?? row.species));
    return `<article class="resource-card trait-card ${escape(row.category || '')}" id="entry-${escape(row.id)}" tabindex="-1"><div class="resource-card-heading"><span class="resource-icon trait-mark" aria-hidden="true">◎</span><div><span class="catalog-kind">${arr(pokemon?.trait_options).length > 1 ? '互斥可选被动' : '固定被动'} · ${escape(pokemon?.name || '')} · ${escape(row.source_label || '本作改编')}</span><h2>${escape(row.name)}</h2></div></div><div class="resource-tags">${arr(row.tags).map(tag => `<span>${escape(tag)}</span>`).join('')}</div><p class="resource-effect">${escape(row.description)}</p><div class="pokemon-references">${pokemonReferences(pokemon ? [pokemon.sid] : [], data)}</div><div class="trait-contract"><p><strong>本命仍然保留</strong>${escape(pokemon?.native_skill?.name || '')} · 80能量，按条件施放</p><p><strong>特性独立触发</strong>满足条件自动生效 · 不占装备与学习位</p>${arr(pokemon?.trait_options).length > 1 ? `<p><strong>只能选择一项</strong>准备期免费切换：${arr(pokemon.trait_options).map(option => `<a href="${escape(catalogLink('traits', option.name))}">${escape(option.name)}</a>`).join(' / ')}；图鉴展示可选项，实际个体不会同时生效。</p>` : ''}</div><a class="build-reference" href="${escape(buildLink(pokemon?.sid || ''))}">比较同精灵的构筑方向 ${arrow}</a></article>`;
  }
  function bondCard(row) {
    const data = libraryState.catalog;
    return `<article class="resource-card bond-card ${escape(row.category)}" id="entry-${escape(row.id)}" tabindex="-1"><div class="resource-card-heading"><span class="resource-icon" aria-hidden="true">${escape(categorySymbols[row.category])}</span><div><span class="catalog-kind">${escape(categoryNames[row.category])}</span><h2>${escape(row.name)}</h2></div></div><p class="resource-effect">${escape(row.description)}</p><ol class="bond-thresholds">${arr(row.thresholds).map(tier => `<li><span>${Number(tier.count)}<small>位不同伙伴</small></span><p>${escape(tier.effect)}</p></li>`).join('')}</ol><p class="resource-source">${row.id === 'bond_inspiration' ? '成员援护的实际受益队友可获增益' : row.beneficiaries === 'team' ? '达到门槛后全队受益' : '达到门槛后相应羁绊成员受益'} · 同物种只计一次</p><details class="bond-members" open><summary>羁绊成员 · ${arr(row.members).length} 位</summary><div class="pokemon-references">${pokemonReferences(row.members, data)}</div></details>${row.category === 'tactic' ? `<a class="build-reference" href="/anim?mode=arena&scenario=arena_${escape(row.id)}&seed=7">观看无装备、技能机或海克斯的羁绊对战 ${arrow}</a>` : ''}<p class="resource-tradeoff">${escape(row.note || '只统计已部署精灵，备战席不计数；战术联动仍需真实的命中、状态与站位条件。')}</p></article>`;
  }
  function groupedBuilds(builds) {
    const groups = new Map();
    builds.forEach(build => { if (!groups.has(build.core)) groups.set(build.core, []); groups.get(build.core).push(build); });
    return [...groups].map(([sid, routes]) => {
      const core = libraryState.catalog.pokemon.find(p => p.sid === sid);
      if (!core) return '';
      const total = libraryState.data.filter(build => build.core === sid).length;
      const compare = routes.length > 1 ? `<div class="build-compare-scroll" tabindex="0" role="region" aria-label="${escape(core.name)}的路线比较"><table class="build-compare"><caption class="sr-only">${escape(core.name)}同核心路线：每个方案只用一个装备位和一个学习位</caption><thead><tr><th scope="col">路线</th><th scope="col">特性选择</th><th scope="col">基础战法</th><th scope="col">装备 / 学习补强</th><th scope="col">海克斯增益 / 转化</th><th scope="col">进阶条件</th></tr></thead><tbody>${routes.map(build => `<tr><th scope="row"><a href="#build-${escape(build.id)}">${escape(build.name)}</a><small>${escape(categoryNames[build.category])}</small></th><td>${escape(buildTrait(core, build)?.name || "尚未配置")}${arr(core.trait_options).length > 1 ? "<small>准备期二选一</small>" : ""}</td><td>${escape(build.base_stage?.summary)}${build.transition ? `<small>低费过渡：${build.transition.members.map(sid => escape(libraryState.catalog.pokemon.find(p => p.sid === sid)?.name)).join(" + ")}</small>` : ""}</td><td>${escape(resourceName('items', build.item))}<br>${escape(resourceName('techniques', build.technique))}</td><td><strong>${escape(resourceName('augments', build.augment))}</strong><small>${escape(build.upgrades?.augment)}</small></td><td>${escape(build.trigger || arr(build.tags).join(' · '))}</td></tr>`).join('')}</tbody></table></div>` : '';
      return `<section class="build-core-group" aria-labelledby="core-heading-${sid}"><div class="build-core-heading">${sprite(sid, '')}<div><p class="eyebrow">作为核心 / #${String(sid).padStart(3, '0')}</p><h2 id="core-heading-${sid}">${escape(core.name)} · ${routes.length} 条路线</h2><p>固定本命：${escape(core.native_skill?.name)}${core.trait ? ` · ${arr(core.trait_options).length > 1 ? '可选特性' : '固定特性'}：${arr(core.trait_options).map(option => escape(option.name)).join(' / ') || escape(core.trait.name)}` : ""} · 每只一个装备位与一个学习位</p></div>${total > routes.length || !libraryState.core ? `<a class="text-link" href="${escape(buildLink(sid))}">查看全部 ${total} 条路线 ${arrow}</a>` : ''}</div>${compare}<div class="build-grid${routes.length === 1 ? ' single' : ''}">${routes.map(buildCard).join('')}</div></section>`;
    }).join('');
  }
  function resourceCard(row, index) {
    const data = libraryState.catalog;
    const advice = catalogKind === 'techniques' ? data.technique_advice?.[row.id] || {} : row;
    const relatedField = catalogKind === 'items' ? 'item' : catalogKind === 'techniques' ? 'technique' : 'augment';
    const related = data.builds.filter(build => build[relatedField] === row.id || arr(build.teammate_loadouts).some(loadout => loadout[relatedField] === row.id));
    const compatible = catalogKind === 'techniques' ? data.pokemon.filter(p => arr(p.learnable).includes(row.id)).map(p => p.sid) : [];
    return `<article class="resource-card ${escape(advice.category)}" id="entry-${escape(row.id)}" tabindex="-1"><div class="resource-card-heading"><span class="resource-icon" aria-hidden="true">${escape(categorySymbols[advice.category] || '✧')}</span><div><span class="catalog-kind">${escape(sections[catalogKind])} / ${String(index + 1).padStart(2, '0')} · ${escape(categoryNames[advice.category])}</span><h2>${escape(row.name)}</h2></div></div><div class="resource-tags">${arr(advice.tags).map(tag => `<span>${escape(tag)}</span>`).join('')}</div><p class="resource-effect">${escape(row.description)}</p>${catalogKind === 'items' ? `<div class="resource-recipes"><h3>合成配方</h3>${arr(row.recipes).map(pair => `<p>${pair.map(part => `<a href="${escape(catalogLink('items', part.name))}">${escape(part.name)}</a>`).join('<span class="recipe-plus">+</span>')}</p>`).join('')}</div><p class="resource-source">${escape(row.source)}</p><p class="resource-copy-rule">${escape(row.copy_rule)}</p>` : catalogKind === 'augments' ? `<p class="resource-source">${escape(row.scope)}</p>` : `<p class="resource-source">${escape(row.compatibility)} · 每场一次</p>`}<div class="resource-advice"><h3>怎么搭配</h3><p>${escape(advice.advice)}</p>${catalogKind !== 'techniques' ? `<div class="pokemon-references">${pokemonReferences(advice.recommended, data)}</div>` : `<details class="compatible-pokemon"><summary>可学习精灵 · ${compatible.length} 位</summary><div class="pokemon-references">${pokemonReferences(compatible, data)}</div></details>`}</div><div class="resource-tradeoff"><h3>取舍与边界</h3><p>${escape(advice.tradeoff)}</p></div>${related.map(build => `<a class="build-reference" href="${escape(buildLink(build.core, build.id))}">组合 · ${escape(build.name)} ${arrow}</a>`).join('')}</article>`;
  }
  async function loadResourceCatalog(force = false) {
    const target = document.getElementById('library-results');
    recipeState.mounted = false;
    target.innerHTML = loading('正在读取目录…');
    try {
      const data = await catalog(force);
      libraryState.catalog = data;
      libraryState.data = arr(data[catalogKind]);
      if (catalogKind !== 'builds') document.querySelector('.head-mark').textContent = String(libraryState.data.length).padStart(2, '0');
      const categories = [...new Set(libraryState.data.map(row => catalogKind === 'techniques' ? data.technique_advice?.[row.id]?.category : row.category))].filter(Boolean);
      document.getElementById('library-filters').innerHTML = filterButton('all', '全部', libraryState.category === 'all') + categories.map(category => filterButton(category, categoryNames[category], libraryState.category === category)).join('');
      if (catalogKind === 'builds') {
        const counts = new Map();
        data.builds.forEach(build => counts.set(build.core, (counts.get(build.core) || 0) + 1));
        const selector = document.getElementById('build-core');
        const known = data.pokemon.some(p => String(p.sid) === libraryState.core);
        selector.innerHTML = '<option value="">全部核心</option>' + data.pokemon.map(p => `<option value="${p.sid}">${escape(p.name)} · ${counts.get(p.sid) || 0} 条核心路线</option>`).join('') + (libraryState.core && !known ? `<option value="${escape(libraryState.core)}">未收录核心 #${escape(libraryState.core)}</option>` : '');
        selector.value = libraryState.core;
      }
      if (catalogKind === 'traits') {
        const rules = data.trait_rules || {};
        document.getElementById('trait-rules').innerHTML = `<strong>${Number(rules.covered_species) || libraryState.data.length} / ${data.pokemon.length} 位已配置特性 · ${Number(rules.available_traits) || libraryState.data.length} 项</strong><p>${escape(rules.description)} ${escape(rules.coverage_note)}</p><a href="/pokedex?trait=covered">查看已配置精灵 ↗</a>`;
      }
      if (catalogKind === 'items') {
        const rules = data.equipment_rules || {};
        document.getElementById('equipment-rules').innerHTML = `<div><strong>装备可以重复。</strong><p>${escape(rules.description)}</p></div><div class="equipment-exception"><strong>幸运蛋数量有上限。</strong><p>${escape(rules.exception)}</p></div>`;
        document.getElementById('component-directory').innerHTML = `<details class="component-directory"><summary>组件与配方 <span>${data.components.length} 种组件 · 点组件打开合成图</span></summary><div class="component-list">${data.components.map(part => `<a href="${escape(recipeLink({ component: part.id }))}" data-recipe-component="${escape(part.id)}"><strong>${escape(part.name)}</strong><span>${part.recipes.length} 种成品可合成 ↗</span></a>`).join('')}</div></details>`;
        document.getElementById('component-directory').hidden = recipeState.view === 'recipes';
      }
      updateResourceCatalog();
    } catch {
      document.getElementById('library-count').textContent = '目录加载失败';
      target.innerHTML = failure('检查服务连接后重试。', 'resources');
    }
  }
  function updateResourceCatalog() {
    const query = libraryState.query.trim().toLocaleLowerCase();
    const data = libraryState.catalog;
    if (!data) return;
    const filtered = libraryState.data.filter(row => {
      const advice = catalogKind === 'techniques' ? data.technique_advice?.[row.id] || {} : row;
      const ids = catalogKind === 'traits' ? [row.sid ?? row.species] : catalogKind === 'bonds' ? arr(row.members) : catalogKind === 'builds' ? [...buildSpecies(row), ...arr(row.base_stage?.members), ...arr(row.transition?.members)] : catalogKind === 'techniques' ? data.pokemon.filter(p => arr(p.learnable).includes(row.id)).map(p => p.sid) : arr(advice.recommended);
      const search = [row.id, row.name, row.description, ...arr(row.thresholds).map(tier => tier.effect), row.base_stage?.summary, row.base_stage?.substitutes, row.transition?.summary, ...Object.values(row.upgrades || {}), row.compatibility, row.copy_rule, row.source, advice.advice, advice.tradeoff, categoryNames[advice.category], ...arr(advice.tags), ...arr(row.steps), row.positioning, row.counter, row.alternative, row.trigger, row.gen2_advice, ...arr(row.recipes).flat().map(part => part.name), ...ids.map(sid => data.pokemon.find(p => p.sid === sid)?.name), ...(catalogKind === 'builds' ? [resourceName('items', row.item), resourceName('techniques', row.technique), resourceName('augments', row.augment), buildTrait(data.pokemon.find(p => p.sid === row.core), row)?.name, ...arr(row.teammate_loadouts).flatMap(loadout => [resourceName('items', loadout.item), resourceName('techniques', loadout.technique), arr(data.pokemon.find(p => p.sid === loadout.sid)?.trait_options).find(option => option.id === loadout.trait)?.name])] : [])].map(value => text(value)).join(' ').toLocaleLowerCase();
      return (catalogKind !== 'builds' || !libraryState.core || String(row.core) === libraryState.core) && (libraryState.category === 'all' || advice.category === libraryState.category) && (!query || search.includes(query));
    });
    statusCount(document.getElementById('library-count'), filtered.length, libraryState.data.length, `${sections[catalogKind]}条目`);
    if (catalogKind === 'items' && recipeState.view === 'recipes') {
      recipeState.matches = new Set(filtered.map(row => row.id));
      if (!recipeState.mounted) {
        document.getElementById('library-results').innerHTML = recipeMatrix();
        recipeState.mounted = true;
      }
      updateRecipeSelection();
      return;
    }
    recipeState.mounted = false;
    document.getElementById('library-results').innerHTML = filtered.length ? catalogKind === 'builds' ? groupedBuilds(filtered) : `<div class="resource-grid${filtered.length === 1 ? ' single' : ''}">${filtered.map(catalogKind === 'traits' ? traitCard : catalogKind === 'bonds' ? bondCard : resourceCard).join('')}</div>` : empty(catalogKind === 'builds' && libraryState.core ? '这位宝可梦在当前筛选下没有核心路线。核心筛选只显示由它担当核心的方案；队友联动请在精灵图鉴中查看。' : '换个名称、用途、效果或组件试试。');
  }

  function renderGuide() {
    const board = Array.from({ length: 18 }, (_, index) => `<div class="board-cell${[2, 8, 14].includes(index) ? ' occupied' : ''}">${index === 2 ? sprite(76, '') : index === 8 ? sprite(26, '') : index === 14 ? sprite(40, '') : ''}</div>`).join('');
    root.innerHTML = `${pageHead('FIELD GUIDE / START HERE', '你的第一本冒险手册。', '买下队员，安排阵容，然后让他们出战。把这几条记在心里，就能开始一局。', '01')}<section class="guide-summary" aria-label="基本规则"><div class="board-panel"><p class="eyebrow">战场速览</p><div class="board-layout"><div class="board-demo" role="img" aria-label="三行六列的棋盘，示例展示三只宝可梦站位">${board}</div><p class="board-label"><strong>3 × 6</strong>调整站位与小队搭配，<br>战斗开始后自动进行。</p></div></div><div class="quick-rules"><div class="quick-rule"><strong>5</strong><span>商店购买位</span></div><div class="quick-rule"><strong>8</strong><span>备战席位置</span></div><div class="quick-rule"><strong>3 → 1</strong><span>相同棋子合成升星</span></div><div class="quick-rule"><strong>80</strong><span>原生技能释放能量</span></div></div></section><section class="guide-section"><div class="guide-section-head"><span class="section-no">01</span><h2>从组队到下一轮</h2></div><div class="rule-grid"><article class="rule-item"><h3>两代伙伴，同池招募</h3><p id="guide-roster-summary">当前竞技池有48种精灵：第一世代30种，第二世代18种。每个费用档16种，八位训练家共享832张牌。</p><p><a href="/pokedex?generation=2">认识第二世代伙伴 ↗</a></p></article><article class="rule-item"><h3>购买与部署</h3><p>从 <strong>5 格商店</strong>挑选宝可梦，暂存到 <strong>8 格备战席</strong>，再部署到 <strong>3×6 棋盘</strong>。点击精灵再点击目标格，或拖动调整站位。上场数量受训练家等级限制，18 个格子提供布阵空间。</p></article><article class="rule-item"><h3>合成与闪光</h3><p><strong>3 只同种、同星精灵</strong>合成更高一星。累计 <strong>9 张一星</strong>即可得到三星宝可梦；三星会变成<strong>闪光形态</strong>。升星保留幸存主卡的特性选择，其他卡的选择不会覆盖它。</p></article><article class="rule-item"><h3>对局与奖励</h3><p>面对 <strong>7 名 AI 对手</strong>，可通过侦察观察他们的阵容。每轮随机获得道具或技能机：胜利 <strong>2 份</strong>，失败或平局 <strong>1 份</strong>。第3、6轮实际结算后另有一次<strong>组件八选一</strong>，在准备期领取，给所需装备补一块材料。败方会失去生命，最终按淘汰顺序产生排名。</p></article><article class="rule-item"><h3>金币与等级</h3><p>金币用于招募、刷新商店和购买经验。每轮都有收入，留存金币还会获得利息。升级能增加上场容量；八位训练家共享卡池，热门精灵会被其他人拿走。</p></article><article class="rule-item"><h3>定位与羁绊</h3><p>防守型优先放前排，近战输出靠近敌人，远程与辅助留在后排。上场精灵的属性计数达到门槛时激活羁绊；新竞技按上场的不同物种计数，同种不同星级不重复，备战席不计入。属性与战术羁绊都有门槛，可在准备页查看还差谁。<a href="/pokedex?tab=bonds">查看羁绊目录 ↗</a></p></article><article class="rule-item"><h3>合成与装备</h3><p>在「战前准备 → 道具装备」中用两个组件合成成品，或直接装备战利品。每只精灵只有一个装备位，卸下后回到仓库，可以换给其他伙伴。</p></article></div></section><section class="guide-section"><div class="guide-section-head"><span class="section-no">02</span><h2>本命、学习与特性，各有作用</h2></div><div class="skill-guide"><article class="skill-guide-item"><span class="guide-badge">自动施放 / 80 能量</span><h3>原生技能（80 能量，按条件施放）</h3><p>原生技能由宝可梦的种类决定。能量积累到 <strong>80</strong> 后，在有有效目标时自动释放。援护可以先对队友施放，无需命中敌人；暂时没有可治疗、保护或充能的目标时，会保留能量并继续普攻。</p></article><article class="skill-guide-item"><span class="guide-badge">独立技能槽 / 一场一次</span><h3>学习技能（可更换，一场一次）</h3><p>通过技能机为个体装配技能。它拥有独立的学习槽，可以替换；每场战斗只能使用一次。有库存时消耗一台技能机，没有库存时花费 2 金币学习；须满足相容条件。替换不返还旧技能，原生技能仍然保留。</p></article></div><article class="guide-trait-rule"><h3>竞技特性 · 准备期选择，不消耗能量</h3><p>当前14位精灵共有16项竞技特性。尼多王可在毒刺与强行中二选一，水箭龟可在激流与雨盘中二选一；准备期点击精灵可免费切换。妙蛙花的叶绿素配晴天，刺龙王的悠游自如配雨天。满足战斗条件才会触发，本命技能和学习槽仍然保留；其他精灵尚未配置，也不会随机获得。<a href="/pokedex?tab=traits">查看特性与触发条件 ↗</a></p></article></section><section class="guide-section" aria-label="技能分工"><div class="guide-section-head"><span class="section-no">◎</span><h2>同一定位，也有不同战法</h2></div><div class="rule-grid"><article class="rule-item"><h3>攻击 · 决定怎样赢</h3><p>雷丘打密集连锁，喷火龙轰炸邻格，胡地切入残血后排；大尾立负责残血追击，耿鬼专找射程内高能量敌人汲能。集火、站位与施法顺序决定收益。</p></article><article class="rule-item"><h3>防守 · 决定怎样守</h3><p>风速狗用嘲讽吸引火力，尼多后以毒甲受击反击，大岩蛇直接铺岩钉；水箭龟保留贯穿击退。护卫、反击与地形控制各有用途。</p></article><article class="rule-item"><h3>辅助 · 决定怎样配合</h3><p>吉利蛋急救，皮可西和拉普拉斯加盾，宝石海星和电灯怪充能，猫头夜鹰净化并充能，大舌头拉回队友。妙蛙花保留伤害转治疗。</p></article><article class="rule-item"><h3>组合有取舍</h3><p>竞技开场平静，战斗内由求雨/晴天改变天气，双方共享。辅助可行动时每秒回4能量，不再全员定时回血。纯护盾和充能不触发治疗道具；护心铃、守望回响要交给真正能治疗队友的角色。技能机补一次控制、伤害或自救。吼叫/高速旋转在普攻成功后可等铺钉或清场条件，开战6秒后不再等；无合法击退落点时吼叫始终保留。</p></article></div><p class="document-note"><a href="/reference?path=docs/38-skill-identities.md">查看技能分工、触发与反制 ↗</a></p></section><section class="guide-section"><div class="guide-section-head"><span class="section-no">＋</span><h2>把技能接成联动</h2><p><a href="/pokedex?tab=builds">查看当前搭配与队员替换 ↗</a></p></div><div class="rule-grid"><article class="rule-item"><h3>岩钉推阵</h3><p>大岩蛇或班基拉斯先铺岩钉，飞腿郎、水箭龟、大钢蛇或吼叫把敌人推进区域。只有真实入格才触发，站着不反复扣血；伤害按岩属性克制变化。厚底靴免疫入格伤害，高速旋转、化石翼龙和战舞郎可以清场。</p></article><article class="rule-item"><h3>控制接追击</h3><p>蔓藤怪先定身，飞天螳螂在原生主命中前识别定身、冰冻或麻痹，追加追击。雷丘或十万伏特先麻痹后，电击兽可以把电伤导向邻格敌人。前置状态、目标一致与施法顺序都重要。</p></article><article class="rule-item"><h3>毒性循环</h3><p>用污泥弹、尼多后或千针鱼先铺毒，大尾立可收割生命比例不高于35%的目标。选择毒性催化后，原生主命中对已中毒目标实际扣血，行动结束获得 8 能量；每只每战最多 3 次。毒与钢免疫、净化和护盾能拆掉条件。</p></article><article class="rule-item"><h3>护心守护</h3><p>两个贝壳铃合成护心铃。原生技能对其他队友实际回复达到 5% 最大生命，为一位患者提供 8% 护盾、持续 3 秒；携带者冷却 4 秒。自疗、被动和睡觉不触发。</p></article><article class="rule-item"><h3>护盾反击与回流</h3><p>给风速狗或怪力守势护腕，搭配皮可西单盾、拉普拉斯双人盾或魔墙人偶减伤盾；真正吸盾才蓄下一次普攻反击。屏障回流把实际能量交还原施盾者。盾到期、更强刷新、减伤与更换队员都会改变节奏。</p></article><article class="rule-item"><h3>净化护幕</h3><p>清明坠饰只在原生技能真的净化另一位队友后加盾。巴大蝶单净化，大竺葵最多净化两人，猫头夜鹰只解睡眠/麻痹并充能；净化范围与原生收益决定配队取舍。</p></article><article class="rule-item"><h3>推阵追击</h3><p>水箭龟、大钢蛇、飞腿郎或吼叫真正推开存活敌人，乘隙追击才给它12%易伤4秒。巨钳螳螂与太阳伊布随后对同一敌人施法，接上施法前已易伤的条件；推不动、输出转火或错过窗口都没有这条收益。</p></article><article class="rule-item"><h3>火种 / 毒潮扩散</h3><p>扩散宝珠认携带者自己施加的灼伤或毒。同一存活敌人承受3次真实DOT生命跳伤后，向其邻格空主要异常槽、非免疫敌人传播。持有人须存活，冷却4秒、每战最多2次；传播异常不再传播。护盾、净化和分散站位可拆条件。</p></article><article class="rule-item"><h3>同目标连奏</h3><p>两个力量头带合成节拍器。同目标每次有效生命普攻加15%攻速，最多3层45%，影响攻击与施法行动间隔；普攻转火或4秒断档清层。原生连击、技能机、DOT与纯吸盾不增层。喷火龙远程维持节奏，尼多王与巨钳螳螂近战更需要保护。</p></article><article class="rule-item"><h3>充能接爆发</h3><p>充能鼓舞把宝石海星、电灯怪和猫头夜鹰的本命实际回能接成3秒直接攻击+25%的窗口。每名受益队员冷却5秒、每战最多3次，不叠加。满能量、自回能、联动回能不触发；灼伤、中毒与岩钉不强化。站位和施法顺序决定能否打进窗口。</p></article><article class="rule-item"><h3>水电导流 / 水草滋养</h3><p>水本命或学习技能的主命中真正扣除生命后留下湿润4秒，雨中6秒。另一位电手主命中同一目标实伤，返还原水来源至多8能量；另一位草手则回复自身两格内最虚弱伤员最大生命6%。每位消费者冷却4秒、每战最多3次，同一湿润只消费一次，满能或无伤员不消费；反应产物不递归触发本命链。</p></article><article class="rule-item"><h3>阴晴争夺</h3><p>学习求雨/晴天的队员首次成功本命后申请12秒天气，随后一拍生效；潮湿岩石/炽热岩石将自己的对应申请延长到16秒。雨中水直接伤害+15%、火−10%，晴反向；叶绿素配晴、悠游自如配雨提高25%行动速度，雨盘每2秒自疗3%、每战最多6次。同天气不续时，异天气覆盖，同一拍晴雨相抵；到期恢复平静，不恢复旧天气。</p></article><article class="rule-item"><h3>强行与生命之玉</h3><p>强行尼多王的适用本命与十万伏特、冰冻光束、污泥弹、打雷直接伤害+30%，舍弃追加异常/畏缩和毒角40%追击。生命之玉直接进攻+20%，完整动作一次自扣最大生命5%，绕过护盾且可能倒下；只有适用强行动作免反噬，普攻仍有代价。两条特性路线可在准备期免费切换。</p></article><article class="rule-item"><h3>治愈接力</h3><p>胖可丁、幸福蛋和大竺葵能接上团队治疗，让辅助靠近输出。选择守望回响后，辅助原生技能有效治疗其他队友后，给两格内未满能量、能量最高的攻击型队友补 8 能量；每名辅助冷却 4 秒、每战最多 3 次。</p></article></div><p class="document-note">准备页会检查上场配置是否具备条件，战后可查看实际回能、护盾实吸、强化普攻的额外伤害、易伤次数与地形收益。<a href="/reference?path=docs/20-arena-gen2-design.md">第二世代与联动扩容说明 ↗</a>。<a href="/reference?path=docs/18-arena-combination-design.md">更多玩法设计：破冰、破盾等候选路线 ↗</a>（尚未加入当前战斗）。<a href="/reference?path=docs/40-attack-branches.md">攻击型的多核心路线、触发与反制 ↗</a>。<a href="/reference?path=docs/43-arena-synergy.md">可选特性、天气与水电水草联动说明 ↗</a>。<a href="/reference?path=docs/41-arena-bonds.md">羁绊、成型阶段与定向补给说明 ↗</a>（在现有原生技能、装备、技能机与海克斯之上联动，无需额外抽取独立系统）。</p></section><section class="guide-section"><div class="guide-section-head"><span class="section-no">03</span><h2>技能机名录</h2><p><a href="/pokedex?tab=techniques">搜索完整技能机目录 ↗</a></p></div><div id="guide-techniques">${loading('正在整理技能机…')}</div></section><section class="guide-section"><div class="guide-section-head"><span class="section-no">04</span><h2>选择你的强化路线</h2><p><a href="/pokedex?tab=augments">搜索完整海克斯目录 ↗</a></p></div><div id="guide-augments">${loading('正在整理强化方案…')}</div></section><section class="guide-section"><div class="guide-section-head"><span class="section-no">05</span><h2>放心离开，随时回来</h2></div><div class="rule-grid"><article class="rule-item"><h3>自动保存</h3><p>冒险会自动保存。再次打开游戏时，继续已有进度；无需每次从头创建对局。</p></article><article class="rule-item"><h3>重开一局</h3><p>需要换一种思路时，在游戏中选择重开。重开会重新开始冒险；当前这一局的进度会被新对局替代。</p></article><article class="rule-item"><h3>边打边查</h3><p>准备阵容时可打开竞技图鉴，查看精灵、道具、技能机与海克斯，再决定购买和部署。<a href="/pokedex?tab=items">打开道具目录 ↗</a></p></article></div></section><section class="guide-cta"><div><h2>手册读完了，小队该上场了。</h2><p>从第一轮开始，找到属于你的组合。</p></div><a class="primary-link" href="/play">进入 / 继续冒险 <span aria-hidden="true">→</span></a></section>${footer()}`;
    loadGuide();
  }
  function libraryCard(item, index, kind) {
    const name = text(item.name, text(item.title, text(item.id, kind === 'technique' ? '技能机' : '强化')));
    const description = text(item.description, text(item.effect_description, text(item.effect, text(item.desc, ''))));
    const type = translatedType(item.type || item.skill_type || item.move?.type);
    const power = item.power ?? item.move?.power;
    const meta = [type, Number.isFinite(Number(power)) ? `威力 ${power}` : '', kind === 'technique' ? '学习槽 · 一场一次' : text(item.rarity)].filter(Boolean).join(' · ');
    return `<article class="library-item"><span class="library-id">${kind === 'technique' ? 'TM' : 'AUG'} / ${String(index + 1).padStart(2, '0')}</span><h3>${escape(name)}</h3><p>${escape(description || (kind === 'technique' ? '装配到独立学习槽，可更换，每场战斗使用一次。' : '选择后为本局冒险提供强化。'))}</p>${kind === 'technique' && item.compatibility ? `<p class="library-compatibility">${escape(item.compatibility)}</p>` : ''}${meta ? `<span class="library-meta">${escape(meta)}</span>` : ''}</article>`;
  }
  async function loadGuide(force = false) {
    const techniques = document.getElementById('guide-techniques');
    const augments = document.getElementById('guide-augments');
    techniques.innerHTML = loading('正在整理技能机…');
    augments.innerHTML = loading('正在整理强化方案…');
    try {
      const data = await catalog(force);
      const gen1 = data.pokemon.filter(p => p.generation === 1).length;
      const gen2 = data.pokemon.filter(p => p.generation === 2).length;
      const stock = data.pokemon.reduce((sum, p) => sum + Number(p.pool_total || 0), 0);
      document.getElementById('guide-roster-summary').textContent = `当前竞技池有${data.pokemon.length}种精灵：第一世代${gen1}种，第二世代${gen2}种。八位训练家共享${stock}张牌，每只拥有原生技能与独立学习槽。`;
      techniques.innerHTML = data.techniques.length ? `<div class="library-grid">${data.techniques.map((item, index) => libraryCard(item, index, 'technique')).join('')}</div>` : empty('当前目录尚未收录技能机。', false);
      augments.innerHTML = data.augments.length ? `<div class="library-grid">${data.augments.map((item, index) => libraryCard(item, index, 'augment')).join('')}</div>` : empty('当前目录尚未收录强化。', false);
    } catch {
      techniques.innerHTML = failure('技能机与强化目录暂时不可用。重新加载即可再试。', 'guide');
      augments.innerHTML = '<p class="preview-label">强化方案将与技能机目录一起重新加载。</p>';
    }
  }

  const toolGroups = [
    { id: 'animation', name: '动画与演出', note: '查看动作，调试节奏', items: [
      { href: '/anim?mode=arena&seed=7', name: '竞技战斗预览', description: '试玩同款 960×640 战场与关节动作，固定种子 7。', symbol: '▶' },
      { href: '/animation-lab?mode=arena', name: '竞技动作实验室', description: '48 只当前竞技精灵，按需预览六种动作与原生技能。', symbol: 'FX' },
      { href: '/animation-editor?mode=arena', name: '竞技动作编辑器', description: '当前战场双栏调参对照、逐帧定位与预设导入导出。', symbol: '↝' }
    ] },
    { id: 'simulation', name: '模拟与对战', note: '验证阵容，复现战斗', items: [
      { href: '/scenarios?mode=arena', name: '竞技场景验收', description: '查看当前竞技的分件动作、岩钉击退、异常追击与治疗防守场景。', symbol: 'SC' },
      { href: '/match', name: '经典对局模拟', description: '经典规则的八人对局与战斗模拟。', symbol: 'VS' },
      { href: '/experiments', name: '经典对照实验台', description: '运行经典系统开关实验，读取已有规则验证结果。', symbol: 'EX' }
    ] },
    { id: 'classic', name: '经典资料库', note: '完整数据与组合参考', items: [
      { href: '/roster', name: '经典图鉴 · 84 只', description: '查看经典宝可梦资料；竞技池请使用新图鉴。', symbol: '84' },
      { href: '/synergy', name: '羁绊与组合', description: '查看属性与阵容组合的协同关系。', symbol: '＋' },
      { href: '/items', name: '道具资料', description: '浏览道具与相关效果资料。', symbol: 'IT' },
      { href: '/demo', name: '经典演示', description: '打开经典演示与数据浏览入口。', symbol: 'DM' }
    ] },
    { id: 'device', name: '设备与模式', note: '三键操作与远征挑战', items: [
      { href: '/animation-lab?mode=classic', name: '经典设备动画', description: '明确使用 240×320 device-v1 画面，保留经典动作预览。', symbol: 'PX' },
      { href: '/animation-editor?mode=classic', name: '经典设备编辑器', description: '经典动画参数与旧预设校验；未带 mode 的旧预设按经典模式导入。', symbol: 'ED' },
      { href: '/device', name: '设备模式', description: '使用 A / B / C 三键操作，检查设备界面与按键流程。', symbol: '▯' },
      { href: '/expedition', name: '远征模式', description: '进入远征模式的独立验收入口。', symbol: '↗' }
    ] },
    { id: 'resources', name: '参考与资源', note: '设计稿与验收证据', items: [
      { href: '/reference?path=docs%2F03-gameplay-and-ai.md', name: '经典玩法与 AI 设计', description: '经典规则与工程参考；当前竞技玩法以玩法指南为准。', symbol: 'GD' },
      { href: '/reference?path=docs%2F09-save-system.md', name: '存档系统说明', description: '自动保存、双槽恢复和备份设计。', symbol: 'SV' },
      { href: '/reference?path=docs%2F43-arena-synergy.md', name: '特性、天气与元素联动', description: '可选特性、雨晴争夺、水电导流、水草滋养与新装备配方。', symbol: '◎' },
      { href: '/reference?path=docs%2F34-unified-preview-tools.md', name: '统一预览与工具说明', description: '竞技 / 经典模式、实时预览、调参对照与离线生成工具。', symbol: 'FX' },
      { href: '/reference?path=docs%2F30-skill-machines-and-learning.md', name: '技能机器设计', description: '经典教学契约与学习设计参考；当前竞技技能请查看玩法指南。', symbol: 'TM' },
      { href: '/reports/evidence/unified-tools-2026-10-07/roster-showcase/mixed-battle.gif', name: '竞技 6v6 样片 · 当前', description: '当前竞技渲染器的六对六战斗离线样片，查看完整阵容与技能交错。', symbol: 'VS' },
      { href: '/reports/evidence/unified-tools-2026-10-07/showcase/contact-cast.png', name: '竞技大招样片 · 当前', description: '当前 960×640 渲染器的怪力、巨钳螳螂、雷丘与水箭龟五阶段分镜。', symbol: 'FX' },
      { href: '/reports/evidence/unified-tools-2026-10-07/showcase/manifest.json', name: '竞技样片生成记录', description: '本轮竞技样片的模式、版本、帧尺寸与实际事件记录。', symbol: 'MF' },
      { href: '/reports/evidence/unified-tools-2026-10-07/range/index.html', name: '竞技靶场 · 当前', description: '使用当前战斗渲染器的离线攻击、移动、大招、受击与退场样本。', symbol: 'RG' },
      { href: '/acceptance', name: '统一验收工作台', description: '当前竞技渲染版本、验收重点、经典工具与历史报告。', symbol: 'QA' },
      { href: '/range', name: '单宝可梦动作预览', description: '打开当前竞技动作实验室，按角色与动作生成实时预览。', symbol: 'RG' },
      { href: '/mockups/prep_hd6x.png', name: '历史准备稿 · 方案 C', description: '早期设备准备阶段的 HD 1440×1920 静态设计稿。', symbol: '01' },
      { href: '/mockups/battle_hd6x.png', name: '历史设备战斗稿 · 静态', description: '旧设备战斗画面的放大设计稿；当前战场请查看竞技战斗预览。', symbol: '02' },
      { href: '/mockups/cutin_hd6x.png', name: '历史设备特写稿 · 静态', description: '旧设备大招特写的放大参考图。', symbol: '03' },
      { href: '/mockups/battle_storyboard.png', name: '历史动画分镜 · 静态六格', description: '早期战斗演出的静态六格参考。', symbol: '06' }
    ] }
  ];
  const toolsState = { query: '', category: 'all', reports: [], reportsStatus: 'loading' };
  function renderTools() {
    root.innerHTML = `${pageHead('WORKSHOP / DEVELOP & VERIFY', '训练工坊，随手可达。', '动画、模拟、经典数据与验收参考。按类别浏览，或直接搜索你需要的入口。', 'TOOLS')}<div class="tools-intro"><span aria-hidden="true">✦</span><p><strong>想开始一局？</strong> 从<a href="/play">冒险入口</a>出发。这里收纳开发、演示与验收工具。</p></div><div class="search-panel">${searchField('tools-search', '搜索工具、资源或报告')}<div class="tools-categories" role="group" aria-label="按工具类别筛选">${filterButton('all', '全部', true)}${toolGroups.map(group => filterButton(group.id, { animation: '动画', simulation: '模拟', classic: '经典数据', device: '设备模式', resources: '参考资源' }[group.id])).join('')}</div></div><div class="result-meta"><span id="tools-count" role="status" aria-live="polite"></span><span>保留所有原有验收入口</span></div><div id="tools-results"></div>${footer()}`;
    document.getElementById('tools-search').addEventListener('input', event => { toolsState.query = event.target.value; updateTools(); });
    document.querySelector('.tools-categories').addEventListener('click', event => {
      const button = event.target.closest('[data-filter]');
      if (!button) return;
      toolsState.category = button.dataset.filter;
      document.querySelectorAll('.tools-categories [data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      updateTools();
    });
    updateTools();
    loadReports();
  }
  function toolCard(item) {
    return `<a class="tool-link" href="${escape(item.href)}"><span class="tool-symbol" aria-hidden="true">${escape(item.symbol)}</span><div><h3>${escape(item.name)}</h3><p>${escape(item.description)}</p></div><span class="tool-arrow" aria-hidden="true">↗</span></a>`;
  }
  function updateTools() {
    const query = toolsState.query.trim().toLocaleLowerCase();
    const groups = toolGroups.filter(group => toolsState.category === 'all' || toolsState.category === group.id).map(group => ({ ...group, items: group.items.filter(item => !query || `${group.name} ${item.name} ${item.description} ${item.href}`.toLocaleLowerCase().includes(query)) })).filter(group => group.items.length);
    const reportCategory = toolsState.category === 'all' || toolsState.category === 'resources';
    const reports = reportCategory ? toolsState.reports.filter(name => !query || `报告 reports ${name}`.toLocaleLowerCase().includes(query)) : [];
    const count = groups.reduce((total, group) => total + group.items.length, 0) + reports.length;
    const total = toolGroups.reduce((sum, group) => sum + group.items.length, 0) + toolsState.reports.length;
    statusCount(document.getElementById('tools-count'), count, total, '个入口');
    let html = groups.map(group => `<section class="tool-group" aria-labelledby="tools-${group.id}"><div class="section-heading"><h2 id="tools-${group.id}">${group.name}</h2><small>${group.note}</small></div><div class="tool-grid">${group.items.map(toolCard).join('')}</div></section>`).join('');
    if (reportCategory) {
      let reportContent = '';
      if (toolsState.reportsStatus === 'loading') reportContent = loading('正在读取验收报告…');
      else if (toolsState.reportsStatus === 'error') reportContent = failure('报告列表暂时不可用；其余工具入口可以正常使用。', 'reports');
      else if (reports.length) reportContent = `<div class="report-list">${reports.map((name, index) => `<a class="report-link" href="/reference?path=reports%2F${encodeURIComponent(name)}"><span class="report-counter">${String(index + 1).padStart(2, '0')}</span><span>${escape(name)}</span>${arrow}</a>`).join('')}</div>`;
      else if (!query && !toolsState.reports.length) reportContent = '<div class="status-box"><p>还没有生成验收报告。完成验收后，报告会出现在这里。</p></div>';
      if (reportContent) html += `<section class="tool-group" aria-labelledby="reports-title"><div class="section-heading"><h2 id="reports-title">验收报告</h2><small>来自本地报告目录</small></div>${reportContent}</section>`;
    }
    if (!count && toolsState.reportsStatus !== 'loading' && !(reportCategory && toolsState.reportsStatus === 'error')) html = empty('换个关键词或工具类别试试。');
    document.getElementById('tools-results').innerHTML = html;
  }
  async function loadReports() {
    toolsState.reportsStatus = 'loading';
    updateTools();
    try {
      const data = await fetchJson('/api/reports');
      if (!Array.isArray(data) || !data.every(name => typeof name === 'string')) throw new Error('Invalid report list');
      toolsState.reports = data;
      toolsState.reportsStatus = 'ready';
    } catch { toolsState.reportsStatus = 'error'; }
    updateTools();
  }

  root.addEventListener('click', event => {
    if (path === '/pokedex' && catalogKind === 'items' && libraryState.catalog) {
      const view = event.target.closest('[data-item-view]');
      const component = event.target.closest('[data-recipe-component]');
      const pair = event.target.closest('[data-recipe-a]');
      const item = event.target.closest('[data-recipe-item]');
      if (view) { event.preventDefault(); setItemView(view.dataset.itemView); return; }
      if (component) {
        event.preventDefault();
        if (!libraryState.catalog.components.some(part => part.id === component.dataset.recipeComponent)) return;
        const fromDirectory = recipeState.view === 'directory';
        recipeState.component = component.dataset.recipeComponent; recipeState.a = ''; recipeState.b = '';
        setItemView('recipes');
        const detail = document.getElementById('recipe-detail');
        if (fromDirectory) detail.focus({ preventScroll: true });
        detail.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
        return;
      }
      if (pair) {
        const ids = new Set(libraryState.catalog.components.map(part => part.id));
        if (!ids.has(pair.dataset.recipeA) || !ids.has(pair.dataset.recipeB)) return;
        const fromMatrix = pair.classList.contains('recipe-cell');
        recipeState.a = pair.dataset.recipeA; recipeState.b = pair.dataset.recipeB; recipeState.component = '';
        setItemView('recipes');
        const detail = document.getElementById('recipe-detail');
        if (!fromMatrix) detail.focus({ preventScroll: true });
        detail.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
        return;
      }
      if (item) {
        const row = libraryState.catalog.items.find(row => row.id === item.dataset.recipeItem);
        if (!row) return;
        event.preventDefault();
        libraryState.query = row.name; libraryState.category = 'all';
        document.getElementById('library-search').value = row.name;
        document.querySelectorAll('#library-filters [data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === 'all')));
        setItemView('directory');
        const card = document.getElementById('entry-' + row.id);
        card?.scrollIntoView?.({ behavior: 'smooth', block: 'center' }); card?.focus();
        return;
      }
      if (event.target.closest('[data-recipe-reset]')) {
        recipeState.a = ''; recipeState.b = ''; recipeState.component = '';
        updateRecipeSelection(); recordItemView(); return;
      }
    }
    const retry = event.target.closest('[data-retry]');
    if (retry) {
      const loaders = { home: () => loadHomePreview(true), pokedex: () => loadPokedex(true), resources: () => loadResourceCatalog(true), guide: () => loadGuide(true), reports: loadReports };
      loaders[retry.dataset.retry]?.();
    }
    if (event.target.closest('[data-clear]')) {
      if (path === '/pokedex') {
        if (catalogKind !== 'pokemon') {
          libraryState.query = ''; libraryState.category = 'all'; libraryState.core = ''; libraryState.selectedBuild = ''; document.getElementById('library-search').value = '';
          if (catalogKind === 'builds') { document.getElementById('build-core').value = ''; recordBuildFilters(); }
          document.querySelectorAll('#library-filters [data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === 'all')));
          updateResourceCatalog(); document.getElementById('library-search').focus();
          return;
        }
        dexState.query = ''; dexState.role = 'all'; dexState.generation = 'all'; dexState.trait = 'all'; document.getElementById('dex-search').value = '';
        document.querySelectorAll('#dex-generations [data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === 'all')));
        document.querySelectorAll('#dex-filters [data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === 'all')));
        document.querySelectorAll('#dex-traits [data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === 'all')));
        updatePokedex(); document.getElementById('dex-search').focus();
      } else if (path === '/tools') {
        toolsState.query = ''; toolsState.category = 'all'; document.getElementById('tools-search').value = '';
        document.querySelectorAll('.tools-categories [data-filter]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === 'all')));
        updateTools(); document.getElementById('tools-search').focus();
      }
    }
  });
  ({ '/': renderHome, '/pokedex': catalogKind === 'pokemon' ? renderPokedex : renderResourceCatalog, '/guide': renderGuide, '/tools': renderTools }[path] || renderHome)();
})();
