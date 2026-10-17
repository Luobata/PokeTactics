/* Historical reference coverage stays separate from the competitive pool. */
window.ReferenceDex = (() => {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const types = {NORMAL:'一般',FIRE:'火',WATER:'水',ELECTRIC:'电',GRASS:'草',ICE:'冰',FIGHTING:'格斗',POISON:'毒',GROUND:'地面',FLYING:'飞行',PSYCHIC:'超能',BUG:'虫',ROCK:'岩石',GHOST:'幽灵',DRAGON:'龙',DARK:'恶',STEEL:'钢'};
  const stats = [['hp','生命'],['attack','攻击'],['defense','防御'],['special_attack','特攻'],['special_defense','特防'],['speed','速度']];
  function mount(root, navigation) {
    const params = new URLSearchParams(location.search), pool = params.get('pool') || 'families_v2';
    const state = {rows:[], q:params.get('q')||'', generation:params.get('generation')||'all', status:'all', page:1};
    const pageSize = 24;
    root.innerHTML = `<header class="fd-head"><div><p class="eyebrow">NATIONAL FIELD NOTES / 前三世代资料</p><h1>三片地区，一本图鉴。</h1><p class="lead">关都、城都与丰缘的 386 位伙伴，逐一认识。</p></div><a class="primary-link" href="/pokedex?pool=${esc(pool)}">比较竞技强度 →</a></header>${navigation}<nav class="fd-view-switch" aria-label="资料范围"><a href="/pokedex?pool=${esc(pool)}">竞技强度与培养</a><a aria-current="page" href="/pokedex?view=all&pool=${esc(pool)}">前三世代资料 · 386 种</a></nav><div class="fd-loading" role="status">正在读取三世代资料…</div>`;
    async function load() {
      const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch('/api/portal/species?pool=' + encodeURIComponent(pool), {signal:controller.signal});
        if (!response.ok) throw Error('HTTP ' + response.status);
        const data = await response.json();
        if (!data.ok || !Array.isArray(data.species)) throw Error('资料格式无效');
        state.rows = data.species;
        root.querySelector('.fd-loading').outerHTML = `<aside class="fd-rules"><strong>资料已收录，不等于已加入商店。</strong><span>${esc(data.note)}</span></aside><section class="fd-controls" aria-label="资料筛选"><label class="search-field"><input type="search" id="ref-search" aria-label="搜索编号、名称或属性" placeholder="编号、中文名、英文名或属性…" value="${esc(state.q)}"></label><div class="fd-control-row"><label>世代<select id="ref-generation"><option value="all">全部世代</option><option value="1">第一世代 · 151 种</option><option value="2">第二世代 · 100 种</option><option value="3">第三世代 · 135 种</option></select></label><label>竞技收录<select id="ref-status"><option value="all">全部资料</option><option value="playable">已入当前竞技池</option><option value="reference">仅资料收录</option></select></label></div></section><p id="ref-count" class="fd-result-meta" role="status" aria-live="polite"></p><section id="ref-grid" class="fd-grid" aria-label="前三世代名册"></section><nav id="ref-pages" class="fd-pages" aria-label="图鉴分页"></nav>`;
        root.querySelector('#ref-generation').value = state.generation;
        root.querySelector('#ref-search').addEventListener('input', e => {state.q=e.target.value;state.page=1;render();});
        root.querySelector('#ref-generation').addEventListener('change', e => {state.generation=e.target.value;state.page=1;render();});
        root.querySelector('#ref-status').addEventListener('change', e => {state.status=e.target.value;state.page=1;render();});
        render();
      } catch (error) {
        root.querySelector('.fd-loading').innerHTML = '<p role="alert">资料加载失败，请重试。</p><button data-ref-retry>重新加载</button>';
      } finally {clearTimeout(timeout);}
    }
    const referenceLink = sid => {
      const p = state.rows.find(p => p.id === sid);
      return p ? `<a href="/pokedex?view=all&q=${sid}&pool=${esc(pool)}">${esc(p.name)}</a>` : '';
    };
    function card(p) {
      const ancestry = [...p.lineage].reverse().map(referenceLink).join(' → ');
      const total = stats.reduce((n,[key]) => n + p.base[key], 0);
      return `<article class="fd-card ref-card"><div class="fd-card-top"><span class="fd-number">#${String(p.id).padStart(3,'0')} · 第 ${p.generation} 世代</span><span class="ref-badge ${p.playable?'playable':''}">${p.playable?'已入竞技':'资料收录'}</span></div><div class="fd-identity"><img src="/demo/sprite/${p.id}.png" alt="${esc(p.name)}" width="88" height="88" loading="lazy"><div><h2>${esc(p.name)}</h2><p>${esc(p.name_en)}</p><span>${p.types.map(t=>types[t]||t).join(' / ')}</span></div></div><div class="fd-investment"><strong>原作种族值 · 第三世代</strong><small>合计 ${total}</small></div><dl class="fd-stats">${stats.map(([key,name])=>`<div><dt>${name}</dt><dd>${p.base[key]}</dd></div>`).join('')}</dl><div class="ref-route"><strong>自然进化关系</strong><p>${ancestry}</p><p>${p.evolves_to.length?'可进化为 '+p.evolves_to.map(referenceLink).join(' / '):'前三世代内无后续进化'}</p></div>${p.playable?`<a class="ref-play-link" href="/pokedex?q=${encodeURIComponent(p.family_name)}&pool=${esc(pool)}">查看 ${esc(p.family_name)} 家族 · ${p.cost} 费 →</a>`:'<p class="ref-unavailable">尚未配置为当前竞技家族；不参与抽卡。</p>'}</article>`;
    }
    function render() {
      const q=state.q.trim().toLowerCase();
      const rows=state.rows.filter(p=>(state.generation==='all'||p.generation===Number(state.generation))&&(state.status==='all'||p.playable===(state.status==='playable'))&&(!q||String(p.id)===q||`${p.name} ${p.name_en} ${p.types.map(t=>types[t]||t).join(' ')}`.toLowerCase().includes(q)));
      const pages=Math.max(1,Math.ceil(rows.length/pageSize));state.page=Math.min(state.page,pages);
      root.querySelector('#ref-count').textContent=`${rows.length} / ${state.rows.length} 种 · 第 ${state.page} / ${pages} 页`;
      root.querySelector('#ref-grid').innerHTML=rows.length?rows.slice((state.page-1)*pageSize,state.page*pageSize).map(card).join(''):'<p class="status-box">没有匹配的宝可梦，试试其他名称或筛选条件。</p>';
      root.querySelector('#ref-pages').innerHTML=`<button data-ref-page="-1" ${state.page===1?'disabled':''}>← 上一页</button><span>${state.page} / ${pages}</span><button data-ref-page="1" ${state.page===pages?'disabled':''}>下一页 →</button>`;
      const query=new URLSearchParams({view:'all'});if(state.q)query.set('q',state.q);if(state.generation!=='all')query.set('generation',state.generation);if(pool==='families_v1')query.set('pool',pool);
      history.replaceState(null,'','/pokedex?'+query);
    }
    root.addEventListener('click', e => {
      const button=e.target.closest('button');if(!button||button.disabled)return;
      if(button.hasAttribute('data-ref-retry'))load();
      else if(button.dataset.refPage){state.page+=Number(button.dataset.refPage);render();root.querySelector('#ref-count').scrollIntoView({block:'start'});}
    });
    load();
  }
  return {mount};
})();
