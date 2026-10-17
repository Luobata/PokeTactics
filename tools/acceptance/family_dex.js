/* Family field guide: the API and live battle use the same stat calculation. */
window.FamilyDex = (() => {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const sprite = (p, small=false) => `<img src="/demo/sprite/${p.sid}.png${p.shiny?'?shiny=1':''}" alt="${esc(p.name)}" width="${small?40:88}" height="${small?40:88}" loading="lazy">`;
  const fields = [['max_hp','生命'],['atk','攻击'],['sp_atk','特攻'],['defense','防御'],['sp_defense','特防'],['attack_interval','攻击间隔']];
  const fmt = (k,v) => k==='attack_interval' ? `${Number(v).toFixed(2)} 秒` : Math.round(v);
  function mount(root, navigation) {
    const params = new URLSearchParams(location.search);
    if (params.get('view') === 'all') { window.ReferenceDex.mount(root, navigation); return; }
    const pool = params.get('pool') || 'families_v2';
    const state = {data:null,q:params.get('q')||'',cost:['1','2','3','4','5'].includes(params.get('cost'))?params.get('cost'):'all',role:['attack','defense','support'].includes(params.get('role'))?params.get('role'):'all',generation:params.get('generation')||'all',stage:['1','2','3'].includes(params.get('stage'))?Number(params.get('stage')):1,sort:'cost',branches:{},activeBranch:Number(params.get('branch'))||null,compare:[]};
    root.innerHTML = `<header class="fd-head"><div><p class="eyebrow">TACTICAL DEX / 竞技选卡</p><h1>竞技精灵图鉴</h1><p class="lead">按费用挑选伙伴，查看特性、技能、羁绊与培养后的战斗面板。</p></div><a class="primary-link" href="/play">前往竞技场 →</a></header>${navigation}<div class="fd-loading" role="status">正在读取家族与战斗面板…</div>`;
    async function load() {
      const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),15000);
      try {
        const response=await fetch('/api/portal/families?pool='+encodeURIComponent(pool),{signal:controller.signal});
        if(!response.ok) throw Error('HTTP '+response.status);
        const data=await response.json(); if(!data.ok||!Array.isArray(data.families))throw Error('目录格式无效');
        state.data=data;
        const branched=data.families.find(f=>f.branches.some(b=>b.id===state.activeBranch));
        if(branched)state.branches[branched.id]=state.activeBranch;else state.activeBranch=null;
        renderShell();
      } catch(e) {
        root.querySelector('.fd-loading').innerHTML='<p role="alert">家族资料加载失败，请确认站点连接后重试。</p><button class="filter-button" data-fd-retry>重新加载</button>';
      } finally {clearTimeout(timeout);}
    }
    function pick(f) {const branch=f.branches.find(b=>b.id===state.branches[f.id])||f.branches[0];return {f,branch,p:branch.stages[Math.min(state.stage-1,branch.stages.length-1)]};}
    function renderShell() {
      const d=state.data;
      root.querySelector('.fd-loading').outerHTML=`${pool==='families_v1'?'<aside class="fd-rules">正在查看旧对局的 56 家族卡池。<a href="/pokedex">查看新局丰缘卡池 →</a></aside>':''}<section class="fd-overview"><div><b>${d.families.length}</b><span>可抽家族</span></div><div><b>${d.forms}</b><span>战斗形态</span></div><div><b>1 / 3 / 9</b><span>累计培养张数</span></div><div><b>${d.total_stock}</b><span>全场共享基础牌</span></div></section><aside class="fd-rules"><strong>商店只卖初始形态，家族费用固定。</strong><span>两段与无进化家族同样可满培养；稀有单位只需一张、全队限一。伊布集齐三只后主动选择五条路线之一。</span><small>${esc(d.note)} 费用与数值为首轮试玩初值。</small></aside><section class="fd-controls" aria-label="图鉴筛选"><label class="search-field"><span aria-hidden="true">⌕</span><input id="fd-search" type="search" aria-label="搜索精灵、特性、技能或羁绊" placeholder="搜索水箭龟、激流、治疗、水系…" value="${esc(state.q)}"></label><div class="fd-control-row"><fieldset><legend>比较培养档</legend>${[1,2,3].map((n)=>`<button type="button" data-fd-stage="${n}" aria-pressed="${state.stage===n}">${['1 张 · 初始','3 张 · 进阶','9 张 · 满培养'][n-1]}</button>`).join('')}</fieldset><label>家族世代<select id="fd-generation"><option value="all">全部世代</option><option value="1">第一世代</option><option value="2">第二世代</option><option value="3">第三世代</option></select></label><label>定位<select id="fd-role"><option value="all">全部定位</option><option value="attack">攻击</option><option value="defense">防守</option><option value="support">辅助</option></select></label><label>排序<select id="fd-sort"><option value="cost">费用 · 从低到高</option><option value="max_hp">生命 · 从高到低</option><option value="atk">攻击 · 从高到低</option><option value="sp_atk">特攻 · 从高到低</option><option value="defense">防御 · 从高到低</option><option value="attack_interval">攻击间隔 · 从短到长</option></select></label></div><fieldset class="fd-costs"><legend>招募费用</legend><button data-fd-cost="all" aria-pressed="true">全部</button>${[1,2,3,4,5].map(c=>`<button data-fd-cost="${c}" aria-pressed="false">${c} 费 <small>${d.distribution[c]||0} 族</small></button>`).join('')}</fieldset></section><div class="fd-result-meta"><span id="fd-count" role="status" aria-live="polite"></span><span>选择「加入比较」，并排查看最多 3 只</span></div><section class="fd-research-guide" aria-label="本局战术研习"><details><summary>把本场配合积累成整局成长 · 战术研习</summary><p>指定特性产生实际贡献后，每轮每路线最多积累 1 层，各最多 5 层，下轮全队受益。出售或进化保留，新局清零。</p><div>${(d.research_catalog||[]).map(r=>`<article><strong>${esc(r.name)}</strong><p>${esc(r.condition)}</p><b>${esc(r.reward)} · 上限 ${r.limit} 层</b></article>`).join('')}</div><a href="/play">在战前准备的「本局研习」查看进度 →</a></details></section><section id="fd-branch-guide" aria-label="进化战术决策"></section><section id="fd-compare" aria-label="宝可梦强度对照"></section><section id="fd-grid" class="fd-grid" aria-label="家族名册"></section><footer class="hub-footer"><span>竞技规则 · ${esc(d.version)}</span><details class="fd-reference"><summary>原作参考资料</summary><a href="/pokedex?view=all&pool=${esc(pool)}">前三世代资料库 ↗</a></details><a href="/pokedex?tab=items&pool=${esc(pool)}">查看道具与搭配 →</a></footer>`;
      root.querySelector('#fd-search').addEventListener('input',e=>{state.q=e.target.value;renderGrid();});
      root.querySelector('#fd-generation').value=state.generation;
      root.querySelector('#fd-generation').addEventListener('change',e=>{state.generation=e.target.value;renderGrid();});
      root.querySelector('#fd-role').value=state.role;
      root.querySelectorAll('[data-fd-cost]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.fdCost===state.cost)));
      root.querySelector('#fd-role').addEventListener('change',e=>{state.role=e.target.value;renderGrid();});
      root.querySelector('#fd-sort').addEventListener('change',e=>{state.sort=e.target.value;renderGrid();});
      renderGrid();
    }
    const directoryLink = (tab, q) => '/pokedex?' + new URLSearchParams({tab, q, pool});
    function bondNames(p) {
      return (p.bonds || []).map(id => ({id, name:state.data.bond_catalog?.find(b=>b.id===id)?.name || id}));
    }
    function bonds(p) {
      return bondNames(p).map(b=>`<a href="${esc(directoryLink('bonds',b.id))}">${esc(b.name)}</a>`).join('');
    }
    function tacticNotes(t) {
      if (!t?.playstyle) return '';
      return `<div class="fd-tactics"><strong>${esc(t.playstyle)}</strong><p><b>搭配</b>${(t.synergy || []).map(esc).join('；')}</p><p><b>反制</b>${esc(t.counterplay)}</p></div>`;
    }
    function branchGuide(rows) {
      return rows.filter(({f})=>f.branches.length>1).map(({f})=>`<details class="fd-branch-guide" ${state.q || state.activeBranch ? 'open' : ''}><summary>${esc(f.name)}的 ${f.branches.length} 条战术路线 <span>同为 ${f.cost} 费 · 三张进化 · 按阵容选分支</span></summary><p>进化后路线锁定。先比较当前队伍缺少的能力，再选择进化；切换预览不会修改对局。</p><div class="fd-branch-options" style="--branch-count:${f.branches.length}">${f.branches.map(b=>{const p=b.stages[1],t=p.trait;return `<article>${sprite(p,true)}<h3>${esc(p.name)}</h3><strong>${esc(t?.playstyle || p.role_name)}</strong><p>${esc(t?.name)} · ${esc(t?.trigger)}</p><button type="button" data-fd-preview="${f.id}:${b.id}" aria-pressed="${(state.branches[f.id] || f.branches[0].id)===b.id && state.stage>1}">查看${esc(p.name)}面板 →</button></article>`;}).join('')}</div></details>`).join('');
    }
    function traitPanel(p) {
      const options = p.trait_options?.length ? p.trait_options : p.trait ? [p.trait] : [];
      if (!options.length) return `<section class="fd-traits" aria-label="竞技特性"><span class="fd-section-label">被动特性</span><strong>当前形态无特性</strong><p>进化后可获得新特性，查看培养路线比较。</p></section>`;
      return `<section class="fd-traits" aria-label="竞技特性"><span class="fd-section-label">${options.length>1?'可选特性 · 每只同时启用一项':'固定特性 · 自动触发'}</span>${options.map(t=>`<div class="fd-trait"><a href="${esc(directoryLink('traits',t.name))}">${esc(t.name)} ↗</a>${options.length>1&&t.default?'<small>默认</small>':''}${t.unlock_challenge?'<small>挑战解锁</small>':''}<p>${esc(t.description)}</p>${tacticNotes(t)}<span class="fd-trigger">${t.cooldown?`冷却 ${t.cooldown} 秒`:'无额外冷却'}${t.limit?` · ${esc(t.limit_scope||'')}每战最多 ${t.limit} 次`:''}</span></div>`).join('')}</section>`;
    }
    function card({f,branch,p}) {
      const key=`${f.id}:${branch.id}:${p.star}`,chosen=state.compare.some(x=>x.key===key);
      const route=branch.stages.map(s=>`<span class="fd-route-step ${s.star===p.star?'current':''}">${sprite(s,true)}<small>${esc(s.name)}</small><em>${s.copies} 张</em></span>`).join('<i aria-hidden="true">›</i>');
      return `<article class="fd-card" data-family="${f.id}">
        <div class="fd-card-top"><span class="fd-number">${f.rare?'稀有 · 限一':'家族固定费用'}</span><span class="fd-cost">${f.cost}<small>费</small></span></div>
        <div class="fd-identity">${sprite(p)}<div><h2>${esc(p.name)}</h2><p>${esc(p.role_name)} · ${esc(p.attack_style)} · 射程 ${p.range} 格</p><div class="fd-types">${p.types.map((t,i)=>`<span style="--type-color:${p.colors[i]}">${esc(t)}</span>`).join('')}</div></div></div>
        <div class="fd-investment"><strong>${esc(p.growth_label)}</strong><span>累计 ${p.copies} 张 · 购卡 ${p.total_cost} 金</span><small>每族 ${f.stock} 张</small><p>商店招募 <b>${esc(f.name)}</b> · 每张 ${f.cost} 金</p></div>
        <div class="fd-bonds"><span>羁绊</span>${bonds(p)}</div>
        ${traitPanel(p)}
        <section class="fd-skill" aria-label="本命技能"><span class="fd-section-label">本命技能 · ${esc(p.native_skill.behavior)}</span><strong>${esc(p.skill_name)}</strong><span>${esc(p.skill_type)} · ${p.native_skill.power?`威力 ${p.native_skill.power} · `:''}80 能量</span><p>${esc(p.skill_description)}</p></section>
        <section class="fd-panel" aria-label="部署战斗面板"><span class="fd-section-label">部署面板 · 已计培养与定位</span><dl class="fd-stats">${fields.map(([k,n])=>`<div><dt>${n}</dt><dd>${fmt(k,p.stats[k])}</dd></div>`).join('')}</dl></section>
        ${f.branches.length>1?`<label class="fd-branch-label">战术分支<select data-fd-branch="${f.id}" aria-label="${esc(f.name)}进化路线">${f.branches.map(b=>`<option value="${b.id}" ${b.id===branch.id?'selected':''}>${esc(b.name)} · ${esc(b.stages[1].role_name)}</option>`).join('')}</select></label>`:''}
        <details class="fd-growth"><summary>培养路线 · 从 ${esc(f.name)} 开始</summary><div class="fd-route">${route}</div><p>商店始终出售 ${esc(f.name)}，每张 ${f.cost} 金。${f.rare?'本单位限一，不参与合成。':f.branches.length>1?'三个初始形态手动选择路线；进化后仅同分支可合并。':'三个同档实例合成下一档。'}</p></details>
        <button class="fd-compare-button" data-fd-add="${f.id}" aria-pressed="${chosen}" ${!chosen&&state.compare.length>=3?'disabled':''}>${chosen?'✓ 已加入 · 点击移除':'＋ 加入比较'}</button>
      </article>`;
    }
    function renderGrid() {
      if(!state.data)return;
      const q=state.q.trim().toLowerCase();
      const rows=state.data.families.map(pick).filter(({f,p})=>(state.generation==='all'||f.generation===Number(state.generation))&&(state.cost==='all'||f.cost===Number(state.cost))&&(state.role==='all'||p.role_key===state.role)&&(!q||(JSON.stringify(f)+' '+bondNames(p).map(b=>b.name).join(' ')).toLowerCase().includes(q)));
      rows.sort((a,b)=>state.sort==='cost'?a.f.cost-b.f.cost||a.f.id-b.f.id:state.sort==='attack_interval'?a.p.stats.attack_interval-b.p.stats.attack_interval:b.p.stats[state.sort]-a.p.stats[state.sort]);
      root.querySelector('#fd-count').textContent=`${rows.length} / ${state.data.families.length} 个家族 · 当前按 ${[1,3,9][state.stage-1]} 张培养查看，稀有保持单张`;
      root.querySelector('#fd-branch-guide').innerHTML=branchGuide(rows);
      root.querySelector('#fd-grid').innerHTML=rows.length?rows.map(card).join(''):'<div class="status-box"><h2>没有匹配的家族</h2><p>试试其他形态名称或清除筛选。</p><button data-fd-clear>清除筛选</button></div>';
      const qp=new URLSearchParams();if(state.q)qp.set('q',state.q);if(state.cost!=='all')qp.set('cost',state.cost);if(state.role!=='all')qp.set('role',state.role);qp.set('stage',state.stage);if(state.activeBranch)qp.set('branch',state.activeBranch);if(state.generation!=='all')qp.set('generation',state.generation);if(pool==='families_v1')qp.set('pool',pool);history.replaceState(null,'','/pokedex?'+qp);
      renderCompare();
    }
    function renderCompare() {
      const rows=state.compare;
      const target=root.querySelector('#fd-compare');if(!rows.length){target.innerHTML='';return;}
      const cells=fn=>rows.map(r=>`<td>${fn(r)}</td>`).join('');
      target.innerHTML=`<div class="fd-compare-heading"><h2>并肩比较 <small>${rows.length} / 3</small></h2><button data-fd-empty>清空</button></div><p class="fd-compare-note">保留加入时的培养档，可跨档比较。总购卡成本不含刷新；阵容、克制与控制效果仍会改变实战结果。</p><div class="fd-table-scroll"><table><caption class="sr-only">选中宝可梦战斗面板和培养成本</caption><thead><tr><th scope="col">战斗面板</th>${rows.map(r=>`<th scope="col">${sprite(r.p,true)}<span>${esc(r.p.name)}</span><small>${r.p.copies} 张 · ${r.f.cost} 费</small><button data-fd-remove="${r.key}" aria-label="移除${esc(r.p.name)}">×</button></th>`).join('')}</tr></thead><tbody><tr><th scope="row">招募费用</th>${cells(r=>`${r.f.cost} 金 / 张`)}</tr><tr><th scope="row">定位与羁绊</th>${cells(r=>`${esc(r.p.role_name)}<p>${bondNames(r.p).map(b=>esc(b.name)).join(' · ')}</p>`)}</tr><tr><th scope="row">总购卡成本</th>${cells(r=>`${r.p.total_cost} 金`)}</tr>${fields.map(([k,n])=>`<tr><th scope="row">${n}</th>${cells(r=>fmt(k,r.p.stats[k]))}</tr>`).join('')}<tr><th scope="row">射程</th>${cells(r=>`${r.p.range} 格`)}</tr><tr><th scope="row">本命技能</th>${cells(r=>`<strong>${esc(r.p.skill_name)}</strong><p>${esc(r.p.skill_description)}</p>`)}</tr><tr><th scope="row">战术方向</th>${cells(r=>esc(r.p.trait?.playstyle||r.p.role_name))}</tr><tr><th scope="row">被动特性</th>${cells(r=>`<strong>${esc(r.p.trait?.name||'无')}</strong><p>${esc(r.p.trait?.description||'')}</p>`)}</tr></tbody></table></div>`;
    }
    root.addEventListener('change',e=>{const id=e.target.dataset.fdBranch;if(id){state.branches[id]=Number(e.target.value);state.activeBranch=state.branches[id];renderGrid();}});
    root.addEventListener('click',e=>{
      const b=e.target.closest('button');if(!b||b.disabled)return;
      if(b.hasAttribute('data-fd-retry')){load();return;}
      if(b.dataset.fdStage){state.stage=Number(b.dataset.fdStage);root.querySelectorAll('[data-fd-stage]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));}
      else if(b.dataset.fdPreview){const [id,branch]=b.dataset.fdPreview.split(':').map(Number);state.branches[id]=branch;state.activeBranch=branch;state.stage=2;root.querySelectorAll('[data-fd-stage]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.fdStage==='2')));}
      else if(b.dataset.fdCost){state.cost=b.dataset.fdCost;root.querySelectorAll('[data-fd-cost]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));}
      else if(b.dataset.fdAdd){const f=state.data.families.find(f=>f.id===Number(b.dataset.fdAdd)),r=pick(f);r.key=`${f.id}:${r.branch.id}:${r.p.star}`;const i=state.compare.findIndex(x=>x.key===r.key);if(i>=0)state.compare.splice(i,1);else if(state.compare.length<3)state.compare.push(r);}
      else if(b.dataset.fdRemove)state.compare=state.compare.filter(r=>r.key!==b.dataset.fdRemove);
      else if(b.hasAttribute('data-fd-empty'))state.compare=[];
      else if(b.hasAttribute('data-fd-clear')){state.q='';state.cost=state.role=state.generation='all';root.querySelector('#fd-generation').value='all';root.querySelector('#fd-search').value='';root.querySelector('#fd-role').value='all';root.querySelectorAll('[data-fd-cost]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.fdCost==='all')));}
      else return;
      renderGrid();
    });
    load();
  }
  return {mount};
})();
