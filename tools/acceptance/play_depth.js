/* arena_v2 depth edition UI: terrain, draft, targeted refresh, item economy,
 * skill modifiers, core unit, bond breakpoints and the battle benefit ledger.
 * play.js calls PlayDepth.render(ctx) after each render and
 * PlayDepth.renderLedger(meta) when a battle report is shown. Everything here
 * is additive: arena_v1 states (no state.depth) leave the page untouched. */
(function () {
  "use strict";
  let ctx = null;
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));

  function ensure(id, tag, anchor, where = "afterend", className = "") {
    let node = $(id);
    if (!node && anchor) {
      node = document.createElement(tag);
      node.id = id;
      if (className) node.className = className;
      anchor.insertAdjacentElement(where, node);
    }
    return node;
  }

  function sourceLabel(source) {
    return {augment: "海克斯", bond: "羁绊断点", item: "装备", skill_mod: "技能强化",
            terrain: "地形", edition: "规则", depth: "规则"}[source] || source;
  }

  // ------------------------------------------------------------ terrain + draft
  function renderTerrain(depth) {
    const scene = document.querySelector(".board-scene");
    const strip = ensure("depth-strip", "section", scene, "beforebegin", "depth-strip");
    if (!strip) return;
    const terrain = depth.terrain;
    const next = terrain.next && terrain.next.id !== terrain.id
      ? `<span class="depth-next">第 ${Number(terrain.stage_end) + 1} 轮起：${esc(terrain.next.name)}</span>` : "";
    const draftRounds = (depth.draft_rounds || []).join(" / ");
    const sim = depth.simulation;
    const simCard = sim
      ? `<div class="depth-sim-result"><b>模拟 ${Number(sim.battles)} 场：胜 ${Number(sim.wins)} · 负 ${Number(sim.losses)}${sim.draws ? ` · 平 ${Number(sim.draws)}` : ""}</b>${sim.carry ? `<span>主要输出 ${esc(sim.carry.name)} · 场均 ${Number(sim.carry.damage)}</span>` : ""}${(sim.ledger || []).map((row) => `<span>${esc(row.name)} · 场均触发 ${row.triggers} · 收益 ${Number(row.value)}</span>`).join("")}</div>`
      : "";
    strip.innerHTML = `<div class="depth-terrain terrain-${esc(terrain.id)}" title="${esc(terrain.description)}"><b>地形 · ${esc(terrain.name)}</b><span>${esc(terrain.description)}</span>${next}</div><div class="depth-rules-hint"><span>选秀轮：${esc(draftRounds)}</span><span>升 2★/3★ 选择技能强化</span><span>可指定 1 名核心</span><button type="button" class="depth-sim-button" data-depth-simulate ${!ctx.canPrep() || depth.simulations_left <= 0 ? "disabled" : ""} title="对本轮对手模拟 6 场（固定的独立种子，调整阵容前后可直接对比），不影响正式结果">模拟对战 · 剩 ${Number(depth.simulations_left)} 次</button></div>${orderBar(depth)}${simCard}${depth.streak_pve ? '<p class="depth-note depth-warn">你正在连胜：野怪轮的每只野怪都会 +1 星。</p>' : ""}`;
    const cells = new Set((terrain.cells || []).map(([r, c]) => `g${r},${c}`));
    document.querySelectorAll("#ally-board [data-loc]").forEach((tile) => {
      tile.classList.toggle("terrain-cell", cells.has(tile.dataset.loc));
      tile.classList.toggle(`terrain-${terrain.id}`, cells.has(tile.dataset.loc));
    });
  }

  function orderBar(depth) {
    const current = depth.order || "none";
    const options = depth.orders || [];
    const chosen = options.find((o) => o.id === current);
    return `<div class="depth-orders" role="group" aria-label="战术指令"><b>战术指令</b>${options.map((o) => `<button type="button" class="depth-order${o.id === current ? " on" : ""}" data-depth-order="${esc(o.id)}" title="${esc(o.description)}" ${!ctx.canPrep() ? "disabled" : ""}>${esc(o.name)}</button>`).join("")}<span class="depth-order-brief">${esc(chosen?.brief || "")}</span></div>`;
  }

  function renderThreat(depth) {
    const threat = depth.threat;
    document.querySelectorAll("#ally-board [data-loc]").forEach((tile) => {
      tile.querySelector(".depth-threat")?.remove();
      const p = ctx.pieceAt(tile.dataset.loc);
      const n = p && threat?.counts?.[p.uid];
      if (n) tile.insertAdjacentHTML("beforeend", `<span class="depth-threat" title="开战时有 ${n} 名敌人首先攻击它">⚔${n}</span>`);
    });
    const byLoc = new Map((threat?.enemies || []).map((e) => [e.loc, e]));
    document.querySelectorAll("#enemy-board [data-enemy-loc]").forEach((tile) => {
      const row = byLoc.get(tile.dataset.enemyLoc);
      tile.classList.toggle("depth-threat-source", Boolean(row));
      if (row) tile.title = `${row.name} 开战首先攻击：${row.target}`;
    });
  }

  function renderDraft(depth) {
    const strip = $("depth-strip");
    const panel = ensure("depth-draft", "section", strip, "afterend", "depth-draft");
    if (!panel) return;
    const draft = depth.draft;
    if (!draft || draft.status !== "pending") {
      panel.hidden = true;
      panel.innerHTML = "";
      return;
    }
    panel.hidden = false;
    const mine = draft.options.find((o) => o.taken_by_you);
    panel.innerHTML = `<div class="depth-draft-head"><b>共享选秀 · 第 ${Number(draft.round)} 轮</b><span>血量低者先选。你是第 ${draft.your_position ?? "—"} 位；顺序：${draft.order.map(esc).join(" → ")}</span></div><div class="depth-draft-options">${draft.options.map((o) => {
      const taken = o.taken_by && !o.taken_by_you;
      return `<button type="button" class="depth-draft-card${taken ? " taken" : ""}${o.taken_by_you ? " mine" : ""}" data-depth-draft="${o.index}" ${taken || mine || !ctx.canPrep() ? "disabled" : ""}><img src="${window.pokeSpriteUrl ? window.pokeSpriteUrl(o.species) : `/demo/sprite/${Number(o.species)}.png`}" alt=""><strong>${esc(o.name)}</strong><small>${Number(o.cost)} 费</small><span class="depth-draft-reward">+ ${esc(o.reward?.name || "")}</span>${taken ? `<em>${esc(o.taken_by)} 已选</em>` : ""}</button>`;
    }).join("")}</div><p class="depth-note">未选择时，开战会自动拿走剩余第一个选项。</p>`;
  }

  // ------------------------------------------------------------ shop
  function renderShop(state, depth) {
    document.querySelectorAll("#shop [data-shop]").forEach((card) => {
      const p = state.shop[Number(card.dataset.shop)];
      if (!p) return;
      card.querySelector(".depth-copies")?.remove();
      if (p.owned_copies) {
        const badge = document.createElement("span");
        badge.className = "depth-copies";
        badge.textContent = `已有 ${p.owned_copies}/3`;
        card.querySelector(".shop-art")?.append(badge);
      }
      if (p.blocked) {
        card.classList.add("blocked");
        card.title = p.blocked;
      }
      card.querySelector(".depth-merge")?.remove();
      if (p.merge_note) card.querySelector(".shop-info")?.insertAdjacentHTML("beforeend", `<div class="depth-merge">${esc(p.merge_note)}</div>`);
    });
    const refresh = $("refresh-button");
    if (refresh && depth.refresh.free > 0)
      refresh.querySelector("span") && (refresh.querySelector("span").textContent = `免费 ×${depth.refresh.free}`);
    const host = ensure("depth-targeted", "div", refresh, "afterend", "depth-targeted");
    if (!host) return;
    const current = host.querySelector("select")?.value || "";
    host.innerHTML = `<select aria-label="定向刷新属性" ${!ctx.canPrep() ? "disabled" : ""}>${depth.refresh.types.map((t) => `<option value="${esc(t.id)}" ${t.id === current ? "selected" : ""}>${esc(t.name)}系</option>`).join("")}</select><button type="button" data-depth-refresh-type ${!ctx.canPrep() || state.you.gold < depth.refresh.targeted_cost ? "disabled" : ""}>定向刷新 · ${Number(depth.refresh.targeted_cost)} 金</button>`;
  }

  // ------------------------------------------------------------ inventory
  function renderInventory(state, depth) {
    const stats = depth.items.stats || {};
    document.querySelectorAll("#inventory [data-equip]").forEach((button) => {
      const key = button.dataset.equip;
      if (button.nextElementSibling?.classList.contains("depth-item-actions")) button.nextElementSibling.remove();
      if (stats[key] && !button.querySelector(".depth-item-stats")) {
        const line = document.createElement("span");
        line.className = "depth-item-stats";
        line.textContent = `组件属性：${stats[key]}`;
        button.querySelector(".item-description")?.after(line);
      }
      const actions = document.createElement("div");
      actions.className = "depth-item-actions";
      actions.innerHTML = `<button type="button" data-depth-dismantle="${esc(key)}" ${!ctx.canPrep() ? "disabled" : ""}>拆解${depth.items.dismantle_cost ? ` · ${depth.items.dismantle_cost} 金` : "（免费）"}</button><button type="button" data-depth-sell-item="${esc(key)}" ${!ctx.canPrep() ? "disabled" : ""}>出售 +${Number(depth.items.sell_value)} 金</button>`;
      button.after(actions);
    });
  }

  // ------------------------------------------------------------ unit detail
  function renderDetail(state, depth) {
    const card = document.querySelector("#unit-detail .unit-detail-card:not(.shop-detail)");
    const p = ctx.selected() ? ctx.pieceAt(ctx.selected()) : null;
    if (!card || !p) return;
    card.querySelector(".depth-unit")?.remove();
    const mods = (p.skill_mods || []).map((m) => `<span class="depth-mod" title="${esc(m.description)}">${esc(m.name)}</span>`).join("");
    const options = (p.mod_options || []).map((m) => `<button type="button" class="depth-mod-option" data-depth-mod="${esc(m.id)}" ${!ctx.canPrep() ? "disabled" : ""}><strong>${esc(m.name)}</strong><span>${esc(m.description)}</span></button>`).join("");
    const onBoard = ctx.selected()?.startsWith("g");
    const extra = p.extra_item
      ? `<div class="detail-item depth-extra"><p class="detail-item-heading"><span class="detail-item-badge">◆</span><strong>第二装备位：${esc(p.extra_item_name)}</strong></p><button type="button" data-depth-unequip-extra ${!ctx.canPrep() ? "disabled" : ""}>卸下 · ${Number(depth.items.unequip_cost)} 金</button></div>`
      : p.item_slots >= 2 ? '<p class="depth-note">第二装备位空闲：在仓库选择装备后点它即可装上。</p>' : "";
    const section = document.createElement("section");
    section.className = "depth-unit";
    section.innerHTML = `<div class="depth-unit-head"><span>本命强化</span>${mods || '<em>升到 2★ 时可选第一项强化</em>'}</div>${options ? `<p class="depth-note">选择一项本命技能强化（永久）：</p><div class="depth-mod-options">${options}</div>` : ""}${extra}<div class="detail-actions"><button type="button" data-depth-core ${!ctx.canPrep() || (!onBoard && !p.is_core) ? "disabled" : ""}>${p.is_core ? "♛ 取消核心" : "♛ 设为核心"}</button></div><p class="depth-note">核心：第二装备位、自身属性羁绊计数 +1、生命攻击 +15%；但敌方俯冲单位会优先扑向核心。卸下装备在本规则下花费 ${Number(depth.items.unequip_cost)} 金。</p>`;
    card.querySelector(".detail-actions")?.before(section);
  }

  function decorateCells(state) {
    const all = [...state.board.flat(), ...state.bench];
    document.querySelectorAll("#ally-board [data-loc], #bench [data-loc]").forEach((tile) => {
      const p = ctx.pieceAt(tile.dataset.loc);
      tile.querySelector(".depth-core-mark")?.remove();
      tile.querySelector(".depth-mod-pips")?.remove();
      if (!p) return;
      if (p.is_core) tile.insertAdjacentHTML("beforeend", '<span class="depth-core-mark" title="核心">♛</span>');
      if ((p.skill_mods || []).length || (p.mod_options || []).length)
        tile.insertAdjacentHTML("beforeend", `<span class="depth-mod-pips${(p.mod_options || []).length ? " pending" : ""}" title="${(p.mod_options || []).length ? "可选择技能强化" : "已强化"}">${"◆".repeat((p.skill_mods || []).length)}${(p.mod_options || []).length ? "?" : ""}</span>`);
    });
    return all;
  }

  // ------------------------------------------------------------ bond breakpoints
  function renderBondRules(depth) {
    const list = $("synergy-list");
    const box = ensure("depth-bond-rules", "div", list, "afterend", "depth-bond-rules");
    if (!box) return;
    const quests = (depth.quests || []).map((q) => `<span class="depth-quest${q.done ? " done" : ""}">${esc(q.name)} ${q.done ? "✓ 已完成" : `${Number(q.progress)}/${Number(q.goal)}`}</span>`).join("");
    const questBox = `<p class="depth-note">羁绊任务：断点在本场产生收益并获胜计 1 次，满 ${Number(depth.quest_goal || 3)} 次奖励 2 金 + 1 组件（每个断点一次）。</p>${quests ? `<div class="depth-quests">${quests}</div>` : ""}`;
    const relevant = depth.bond_rules.filter((r) => r.current > 0);
    box.innerHTML = relevant.length
      ? `<p class="bond-group-title">深度断点 · 改变打法</p>${relevant.map((r) => `<div class="depth-bond${r.active ? " on" : ""}"><strong>${esc(r.type_name)} ${Number(r.current)}/${Number(r.count)} · ${esc(r.name)}</strong><span>${esc(r.effect)}</span></div>`).join("")}`
      : '<p class="depth-note">上场同属性伙伴达到门槛后，会解锁改变战斗行为的深度断点（如飞行 4 俯冲后排、岩石 4 掩护邻格）。</p>';
    box.insertAdjacentHTML("beforeend", questBox);
  }

  // ------------------------------------------------------------ battle ledger
  function renderLedger(meta) {
    const host = $("battle-rewards-panel");
    const box = ensure("battle-ledger", "div", $("battle-combinations") || host?.lastElementChild, "afterend", "depth-ledger");
    if (!box) return;
    const rows = Array.isArray(meta?.ledger) ? meta.ledger : [];
    if (!rows.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    const fmt = (row) => [
      row.damage ? `伤害 ${row.damage}` : "", row.estimated ? `增伤≈${row.estimated}` : "",
      row.heal ? `治疗 ${row.heal}` : "", row.shield ? `护盾 ${row.shield}` : "",
      row.energy ? `能量 ${row.energy}` : "", row.prevented ? `减伤≈${row.prevented}` : "",
    ].filter(Boolean).join(" · ") || (row.idle ? "未触发（条件未满足或站位不在范围内）" : row.passive ? "常驻加成（已计入面板）" : "已触发");
    const side = (team) => rows.filter((r) => r.team === team).map((r) => `<tr><td><i class="buff-src">${esc(r.source_name || sourceLabel(r.source))}</i>${esc(r.name)}</td><td>${Number(r.triggers) || "—"}</td><td>${esc(fmt(r))}</td></tr>`).join("");
    box.hidden = false;
    box.innerHTML = `<h3>收益账本${meta.terrain ? ` · 地形「${esc(meta.terrain.name)}」` : ""}</h3><p class="depth-note">每个规则来源在本场实际做了什么；“≈”为按真实伤害推算的被动加成。</p><table><thead><tr><th>我方来源</th><th>次数</th><th>收益</th></tr></thead><tbody>${side(0) || '<tr><td colspan="3">本场没有触发</td></tr>'}</tbody></table><table><thead><tr><th>敌方来源</th><th>次数</th><th>收益</th></tr></thead><tbody>${side(1) || '<tr><td colspan="3">本场没有触发</td></tr>'}</tbody></table>`;
  }

  // ------------------------------------------------------------ events
  document.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-depth-order],[data-depth-simulate],[data-depth-draft],[data-depth-refresh-type],[data-depth-dismantle],[data-depth-sell-item],[data-depth-mod],[data-depth-core],[data-depth-unequip-extra]");
    if (!target || !ctx || !ctx.canPrep()) return;
    event.preventDefault();
    event.stopPropagation();
    if (target.dataset.depthOrder) await ctx.api("order", {key: target.dataset.depthOrder});
    else if (target.hasAttribute("data-depth-simulate")) await ctx.api("simulate");
    else if (target.dataset.depthDraft != null) await ctx.api("draft", {index: target.dataset.depthDraft});
    else if (target.hasAttribute("data-depth-refresh-type")) await ctx.api("refresh_type", {type: target.previousElementSibling.value});
    else if (target.dataset.depthDismantle) await ctx.api("dismantle", {item: target.dataset.depthDismantle});
    else if (target.dataset.depthSellItem) await ctx.api("sell_item", {item: target.dataset.depthSellItem});
    else if (target.dataset.depthMod) await ctx.api("choose_mod", {loc: ctx.selected(), mod: target.dataset.depthMod});
    else if (target.hasAttribute("data-depth-core")) await ctx.api("core", {loc: ctx.selected()});
    else if (target.hasAttribute("data-depth-unequip-extra")) await ctx.api("unequip", {loc: ctx.selected(), slot: "1"});
  }, true);

  function render(context) {
    ctx = context;
    const state = context.state;
    const depth = state?.depth;
    document.body.classList.toggle("depth-edition", Boolean(depth));
    if (!depth) {
      for (const id of ["depth-strip", "depth-draft", "depth-targeted", "depth-bond-rules"]) $(id)?.remove();
      return;
    }
    renderTerrain(depth);
    renderDraft(depth);
    renderShop(state, depth);
    renderInventory(state, depth);
    decorateCells(state);
    renderDetail(state, depth);
    renderBondRules(depth);
    renderThreat(depth);
    const level = $("levelup-button");
    if (level && depth.xp_gold != null) level.title = `升到下一级还需约 ${depth.xp_gold} 金币的经验`;
    const xp = $("xp-text");
    if (xp && depth.xp_gold != null && !xp.textContent.includes("金")) xp.textContent += ` · 约 ${depth.xp_gold} 金升级`;
  }

  window.PlayDepth = {render, renderLedger};
})();
