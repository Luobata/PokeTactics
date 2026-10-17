/* Family field guide: the API and live battle use the same stat calculation. */
window.FamilyDex = (() => {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const sprite = (p, small=false) => `<img src="/demo/sprite/${p.sid}.png${p.shiny?'?shiny=1':''}" alt="${esc(p.name)}" width="${small?40:88}" height="${small?40:88}" loading="lazy">`;
  const fields = [['max_hp','生命'],['atk','攻击'],['sp_atk','特攻'],['defense','防御'],['sp_defense','特防'],['attack_interval','攻击间隔']];
  const fmt = (k,v) => k==='attack_interval' ? `${Number(v).toFixed(2)} 秒` : Math.round(v);
  function mount(root, navigation) {
    const params = new URLSearchParams(location.search);
    const state = {data:null,q:params.get('q')||'',cost:'all',role:'all',stage:['1','2','3'].includes(params.get('stage'))?Number(params.get('stage')):1,sort:'cost',branches:{},compare:[]};
    root.innerHTML = `<header class="fd-head"><div><p class="eyebrow">FIELD GUIDE / 家族培养 · 第一版</p><h1>从相遇，到并肩作战。</h1><p class="lead">看清每个家族的成长，再决定把金币交给谁。</p></div><a class="primary-link" href="/play">前往竞技场 →</a></header>${navigation}<div class="fd-loading" role="status">正在读取家族与战斗面板…</div>`;
    async function load() {
      const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),15000);
      try {
        const response=await fetch('/api/portal/families',{signal:controller.signal});
        if(!response.ok) throw Error('HTTP '+response.status);
        const data=await response.json(); if(!data.ok||!Array.isArray(data.families))throw Error('目录格式无效');
        state.data=data; renderShell();
      } catch(e) {
        root.querySelector('.fd-loading').innerHTML='<p role="alert">家族资料加载失败，请确认站点连接后重试。</p><button class="filter-button" data-fd-retry>重新加载</button>';
      } finally {clearTimeout(timeout);}
    }
    function pick(f) {const branch=f.branches.find(b=>b.id===state.branches[f.id])||f.branches[0];return {f,branch,p:branch.stages[Math.min(state.stage-1,branch.stages.length-1)]};}
    function renderShell() {
      const d=state.data;
      root.querySelector('.fd-loading').outerHTML=`<section class="fd-overview"><div><b>${d.families.length}</b><span>可抽家族</span></div><div><b>${d.forms}</b><span>战斗形态</span></div><div><b>1 / 3 / 9</b><span>累计培养张数</span></div><div><b>${d.total_stock}</b><span>全场共享基础牌</span></div></section><aside class="fd-rules"><strong>商店只卖初始形态，家族费用固定。</strong><span>两段与无进化家族同样可满培养；稀有单位只需一张、全队限一。伊布集齐三只后主动选择五条路线之一。</span><small>${esc(d.note)} 费用与数值为首轮试玩初值。</small></aside><section class="fd-controls" aria-label="图鉴筛选"><label class="search-field"><span aria-hidden="true">⌕</span><input id="fd-search" type="search" aria-label="搜索家族、形态或技能" placeholder="搜索小火龙、喷火龙、伊布、技能…" value="${esc(state.q)}"></label><div class="fd-control-row"><fieldset><legend>比较培养档</legend>${[1,2,3].map((n)=>`<button type="button" data-fd-stage="${n}" aria-pressed="${state.stage===n}">${['1 张 · 初始','3 张 · 进阶','9 张 · 满培养'][n-1]}</button>`).join('')}</fieldset><label>定位<select id="fd-role"><option value="all">全部定位</option><option value="attack">攻击</option><option value="defense">防守</option><option value="support">辅助</option></select></label><label>排序<select id="fd-sort"><option value="cost">费用 · 从低到高</option><option value="max_hp">生命 · 从高到低</option><option value="atk">攻击 · 从高到低</option><option value="sp_atk">特攻 · 从高到低</option><option value="defense">防御 · 从高到低</option><option value="attack_interval">攻击间隔 · 从短到长</option></select></label></div><fieldset class="fd-costs"><legend>家族费用</legend><button data-fd-cost="all" aria-pressed="true">全部</button>${[1,2,3,4,5].map(c=>`<button data-fd-cost="${c}" aria-pressed="false">${c} 费 <small>${d.distribution[c]||0} 族</small></button>`).join('')}</fieldset></section><div class="fd-result-meta"><span id="fd-count" role="status" aria-live="polite"></span><span>选择「加入比较」，并排查看最多 3 只</span></div><section id="fd-compare" aria-label="宝可梦强度对照"></section><section id="fd-grid" class="fd-grid" aria-label="家族名册"></section><footer class="hub-footer"><span>FAMILY NOTES / ${esc(d.version)}</span><a href="/pokedex?tab=items">查看道具与搭配 →</a></footer>`;
      root.querySelector('#fd-search').addEventListener('input',e=>{state.q=e.target.value;renderGrid();});
      root.querySelector('#fd-role').addEventListener('change',e=>{state.role=e.target.value;renderGrid();});
      root.querySelector('#fd-sort').addEventListener('change',e=>{state.sort=e.target.value;renderGrid();});
      renderGrid();
    }
    function card({f,branch,p}) {
      const key=`${f.id}:${branch.id}:${p.star}`,chosen=state.compare.some(x=>x.key===key);
      const route=branch.stages.map(s=>`<span class="fd-route-step ${s.star===p.star?'current':''}">${sprite(s,true)}<small>${esc(s.name)}</small><em>${s.copies} 张</em></span>`).join('<i aria-hidden="true">›</i>');
      return `<article class="fd-card" data-family="${f.id}"><div class="fd-card-top"><span class="fd-number">#${String(f.id).padStart(3,'0')} · ${f.rare?'稀有单位':'家族卡'}</span><span class="fd-cost">${f.cost}<small>费</small></span></div><div class="fd-identity">${sprite(p)}<div><h2>${esc(p.name)}</h2><p>${esc(p.role_name)} · ${esc(p.attack_style)}</p><div class="fd-types">${p.types.map((t,i)=>`<span style="--type-color:${p.colors[i]}">${esc(t)}</span>`).join('')}</div></div></div><div class="fd-investment"><strong>${esc(p.growth_label)}</strong><span>${p.copies} 张 · 共 ${p.total_cost} 金</span><small>家族库存 ${f.stock} 张</small></div><dl class="fd-stats">${fields.map(([k,n])=>`<div><dt>${n}</dt><dd>${fmt(k,p.stats[k])}</dd></div>`).join('')}</dl><div class="fd-skill"><strong>${esc(p.skill_name)}</strong><span>${esc(p.skill_type)} · ${p.native_skill.power?`威力 ${p.native_skill.power} · `:''}80 能量</span><p>${esc(p.skill_description)}</p></div>${f.branches.length>1?`<label class="fd-branch-label">战术分支<select data-fd-branch="${f.id}" aria-label="${esc(f.name)}进化路线">${f.branches.map(b=>`<option value="${b.id}" ${b.id===branch.id?'selected':''}>${esc(b.name)} · ${esc(b.stages[1].role_name)}</option>`).join('')}</select></label>`:''}<details class="fd-growth"><summary>培养路线 · 从 ${esc(f.name)} 开始</summary><div class="fd-route">${route}</div><p>商店始终出售 ${esc(f.name)}，每张 ${f.cost} 金。${f.rare?'本单位限一，不参与合成。':f.branches.length>1?'三个初始形态手动选择路线；进化后仅同分支可合并。':'三个同档实例合成下一档。'}</p><p>特性：${esc(p.trait?.name||'无被动特性')}。${esc(p.trait?.description||'鲤鱼王通过培养获得暴鲤龙形态与威吓。')}</p></details><button class="fd-compare-button" data-fd-add="${f.id}" aria-pressed="${chosen}" ${!chosen&&state.compare.length>=3?'disabled':''}>${chosen?'✓ 已加入 · 点击移除':'＋ 加入比较'}</button></article>`;
    }
    function renderGrid() {
      if(!state.data)return;
      const q=state.q.trim().toLowerCase();
      const rows=state.data.families.map(pick).filter(({f,p})=>(state.cost==='all'||f.cost===Number(state.cost))&&(state.role==='all'||p.role_key===state.role)&&(!q||JSON.stringify(f).toLowerCase().includes(q)));
      rows.sort((a,b)=>state.sort==='cost'?a.f.cost-b.f.cost||a.f.id-b.f.id:state.sort==='attack_interval'?a.p.stats.attack_interval-b.p.stats.attack_interval:b.p.stats[state.sort]-a.p.stats[state.sort]);
      root.querySelector('#fd-count').textContent=`${rows.length} / ${state.data.families.length} 个家族 · 当前按 ${[1,3,9][state.stage-1]} 张培养查看，稀有保持单张`;
      root.querySelector('#fd-grid').innerHTML=rows.length?rows.map(card).join(''):'<div class="status-box"><h2>没有匹配的家族</h2><p>试试其他形态名称或清除筛选。</p><button data-fd-clear>清除筛选</button></div>';
      const qp=new URLSearchParams();if(state.q)qp.set('q',state.q);qp.set('stage',state.stage);history.replaceState(null,'','/pokedex?'+qp);
      renderCompare();
    }
    function renderCompare() {
      const rows=state.compare;
      const target=root.querySelector('#fd-compare');if(!rows.length){target.innerHTML='';return;}
      const cells=fn=>rows.map(r=>`<td>${fn(r)}</td>`).join('');
      target.innerHTML=`<div class="fd-compare-heading"><h2>并肩比较 <small>${rows.length} / 3</small></h2><button data-fd-empty>清空</button></div><p class="fd-compare-note">保留加入时的培养档，可跨档比较。总购卡成本不含刷新；阵容、克制与控制效果仍会改变实战结果。</p><div class="fd-table-scroll"><table><caption class="sr-only">选中宝可梦战斗面板和培养成本</caption><thead><tr><th scope="col">战斗面板</th>${rows.map(r=>`<th scope="col">${sprite(r.p,true)}<span>${esc(r.p.name)}</span><small>${r.p.copies} 张 · ${r.f.cost} 费</small><button data-fd-remove="${r.key}" aria-label="移除${esc(r.p.name)}">×</button></th>`).join('')}</tr></thead><tbody><tr><th scope="row">总购卡成本</th>${cells(r=>`${r.p.total_cost} 金`)}</tr>${fields.map(([k,n])=>`<tr><th scope="row">${n}</th>${cells(r=>fmt(k,r.p.stats[k]))}</tr>`).join('')}<tr><th scope="row">射程</th>${cells(r=>`${r.p.range} 格`)}</tr><tr><th scope="row">本命技能</th>${cells(r=>`<strong>${esc(r.p.skill_name)}</strong><p>${esc(r.p.skill_description)}</p>`)}</tr><tr><th scope="row">被动特性</th>${cells(r=>`<strong>${esc(r.p.trait?.name||'无')}</strong><p>${esc(r.p.trait?.description||'')}</p>`)}</tr></tbody></table></div>`;
    }
    root.addEventListener('change',e=>{const id=e.target.dataset.fdBranch;if(id){state.branches[id]=Number(e.target.value);renderGrid();}});
    root.addEventListener('click',e=>{
      const b=e.target.closest('button');if(!b||b.disabled)return;
      if(b.hasAttribute('data-fd-retry')){load();return;}
      if(b.dataset.fdStage){state.stage=Number(b.dataset.fdStage);root.querySelectorAll('[data-fd-stage]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));}
      else if(b.dataset.fdCost){state.cost=b.dataset.fdCost;root.querySelectorAll('[data-fd-cost]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));}
      else if(b.dataset.fdAdd){const f=state.data.families.find(f=>f.id===Number(b.dataset.fdAdd)),r=pick(f);r.key=`${f.id}:${r.branch.id}:${r.p.star}`;const i=state.compare.findIndex(x=>x.key===r.key);if(i>=0)state.compare.splice(i,1);else if(state.compare.length<3)state.compare.push(r);}
      else if(b.dataset.fdRemove)state.compare=state.compare.filter(r=>r.key!==b.dataset.fdRemove);
      else if(b.hasAttribute('data-fd-empty'))state.compare=[];
      else if(b.hasAttribute('data-fd-clear')){state.q='';state.cost=state.role='all';root.querySelector('#fd-search').value='';root.querySelector('#fd-role').value='all';root.querySelectorAll('[data-fd-cost]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.fdCost==='all')));}
      else return;
      renderGrid();
    });
    load();
  }
  return {mount};
})();
