/* Prep "moments" (docs/62): augment pick, machine learning, star-up skill
 * mods, recipe board and equipping. Reads state.interactions (server-side,
 * read-only explanations) and drives the existing commands through
 * ctx.api / the established data-* handlers:
 *   claim_augment & reroll_augment  → play.js handlers (data-augment, data-augment-reroll)
 *   learn / equip / craft / choose_mod → ctx.api(...) from confirm sheets
 * play.js calls PlayInteractions.render(ctx) after every render. Works by tap
 * everywhere; desktop additionally drags machines / items onto units and one
 * component onto another. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  // Keyed writes (docs/66): rebuild a block only when its markup changed.
  const memo = (el) => ({set innerHTML(html) {
    if (!el || (el.__src === html && el.__first === el.firstChild)) return;
    el.innerHTML = html;
    el.__src = html;
    el.__first = el.firstChild;
  }});
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  const CATEGORY_GLYPH = {economy: "◎", rule: "§", battle: "⚔", condition: "⚡", growth: "↗"};
  const FIT_LABEL = {high: "很适配", mid: "一般", low: "勉强"};
  let ctx = null;
  let mode = null;            // {kind: "tm" | "equip", key, drag?}
  let sheet = null;           // {kind, ...} currently shown in #ix-sheet
  let augmentDeferred = null; // round the player chose 「先看看棋盘」
  let augmentSig = "";
  let drag = null;            // {kind: "tm" | "item" | "comp", key}
  let flash = "";
  const modDeferred = new Set();

  const S = () => ctx?.state || null;
  const IX = () => S()?.interactions || null;
  const stop = (event) => {
    event.preventDefault?.();
    event.stopPropagation?.();
    event.stopImmediatePropagation?.();
  };
  const canPrep = () => Boolean(ctx?.canPrep?.());
  const sprite = (p) => window.pokeSpriteUrl ? window.pokeSpriteUrl(p.sid, p.shiny) : `/demo/sprite/${Number(p.sid)}.png`;
  const stars = (p) => "★".repeat(Math.max(1, Math.min(3, Number(p?.star) || 1)));
  const isPhone = () => Boolean(window.PlayLayout?.isPhone?.());

  // ------------------------------------------------------------ owned lookup
  function owned() {
    const s = S();
    const rows = [];
    (s?.board || []).forEach((row, r) => row.forEach((p, c) => p && rows.push({p, loc: `g${r},${c}`, board: true})));
    (s?.bench || []).forEach((p, i) => p && rows.push({p, loc: `b${i}`, board: false}));
    return rows;
  }
  const byUid = (uid) => owned().find((row) => row.p.uid === uid) || null;
  const byLoc = (loc) => owned().find((row) => row.loc === loc) || null;

  // ------------------------------------------------------------ augments
  function renderAugments(s, ix) {
    const overlay = $("ix-augment");
    if (!overlay) return;
    const raw = (s.augments?.pending || [])[0];
    const view = (ix?.augments?.pending || []).find((row) => row.id === raw?.id) || null;
    const chip = $("hud-augment");
    if (chip) {
      chip.hidden = !raw;
      memo(chip).innerHTML = raw ? '<svg aria-hidden="true"><use href="#i-spark"/></svg>海克斯待选' : "";
    }
    const open = Boolean(raw && ctx.playable() && augmentDeferred !== s.round);
    overlay.hidden = !open;
    document.body.classList.toggle("ix-augment-open", open);
    if (!open) return;
    const rarity = view?.rarity || "silver";
    overlay.className = `ix-augment rarity-${rarity}`;
    $("ix-augment-eyebrow").textContent = `第 ${Number(raw.round)} 轮 · ${view?.rarity_name || "银"}色海克斯`;
    $("ix-augment-title").textContent = "选择一项海克斯强化";
    $("ix-augment-note").textContent = owned().length
      ? "适配度按你现在的棋盘、备战席和仓库实时计算；本局持续生效。"
      : "你还没有伙伴：适配度按空阵容计算，经济与成长类更稳妥。";
    const left = view ? view.rerolls_left : raw.rerolled ? 0 : 1;
    memo($("ix-augment-reroll")).innerHTML = `<button type="button" class="ix-reroll" data-augment-reroll="${esc(raw.id)}" ${!canPrep() || !left ? "disabled" : ""}>换一批 ↻ <small>剩 ${left} 次</small></button>`;
    const sig = `${raw.id}:${raw.options.map((o) => o.id).join(",")}`;
    const reveal = sig !== augmentSig;
    augmentSig = sig;
    memo($("ix-augment-cards")).innerHTML = raw.options.map((option, i) => {
      const insight = view?.options?.find((row) => row.id === option.id) || {};
      const fit = insight.fit || "mid";
      const pct = Math.max(6, Math.min(100, Math.round((Number(insight.score) || 1) / 5 * 100)));
      const reasons = (insight.reasons || []).map((row) => `<li class="${row.good ? "good" : "bad"}"><span aria-hidden="true">${row.good ? "✓" : "✗"}</span>${esc(row.text)}</li>`).join("");
      const changes = (insight.changes || []).map((text) => `<em>${esc(text)}</em>`).join("");
      const tags = (insight.tags || option.tags || []).map((tag) => `<span>${esc(tag)}</span>`).join("");
      return `<article class="ix-aug-card fit-${fit}${insight.best ? " best" : ""}${reveal ? " reveal" : ""}" style="--i:${i}">
        <div class="ix-aug-face">
          <header><span class="ix-aug-cat cat-${esc(insight.category || "battle")}"><b aria-hidden="true">${CATEGORY_GLYPH[insight.category] || "✦"}</b>${esc(insight.category_name || "战斗")}</span>${insight.best ? '<span class="ix-aug-best">推荐</span>' : ""}</header>
          <h3>${esc(option.name)}</h3>
          <p class="ix-aug-brief">${esc(option.brief || option.description || "")}</p>
          ${tags ? `<div class="ix-aug-tags">${tags}</div>` : ""}
          <div class="ix-fit" aria-label="适配度：${FIT_LABEL[fit]}"><span>适配度</span><i class="ix-fit-meter"><b style="width:${pct}%"></b></i><strong>${FIT_LABEL[fit]}</strong></div>
          ${reasons ? `<ul class="ix-aug-reasons">${reasons}</ul>` : ""}
          ${changes ? `<div class="ix-aug-changes"><span>选择后</span>${changes}</div>` : ""}
          ${insight.condition ? `<p class="ix-aug-condition ${insight.condition.met ? "met" : "unmet"}">触发条件：${insight.condition.met ? "已满足" : "未满足"}</p>` : ""}
          <details class="ix-aug-more"><summary>完整说明</summary><p>${esc(option.description || "")}</p></details>
          <button type="button" class="ix-aug-pick" data-augment="${esc(option.id)}" data-reward="${esc(raw.id)}" ${!canPrep() ? "disabled" : ""}>选择「${esc(option.name)}」</button>
        </div>
      </article>`;
    }).join("");
  }

  function renderStrip(s, ix) {
    const strip = $("ix-augment-strip");
    if (!strip) return;
    const host = isPhone() ? document.querySelector(".bench-heading") : $("stage-dock");
    if (host && strip.parentElement !== host && typeof host.append === "function") host.append(strip);
    const picked = s.augments?.selected || [];
    strip.hidden = !picked.length;
    const cats = new Map((ix?.augments?.selected || []).map((row) => [row.id, row]));
    memo(strip).innerHTML = picked.map((a) => {
      const cat = cats.get(a.id)?.category || "battle";
      return `<button type="button" class="ix-strip-badge cat-${esc(cat)}" data-ix-augment-info="${esc(a.id)}" title="${esc(a.name)}" aria-label="海克斯：${esc(a.name)}"><b aria-hidden="true">${CATEGORY_GLYPH[cat] || "✦"}</b><span>${esc(a.name)}</span></button>`;
    }).join("");
  }

  // Server-side (interactions.augments.selected[].last) because the client state
  // does not carry the battle ledger; fall back to a ledger on last_battle if present.
  function ledgerRows(s, augment) {
    const last = (IX()?.augments?.selected || []).find((row) => row.id === augment.id)?.last;
    if (last) return last.rows || [];
    const rows = Array.isArray(s.last_battle?.ledger) ? s.last_battle.ledger : [];
    return rows.filter((row) => Number(row.team) === 0 && row.source === "augment" && row.id === augment.id);
  }

  function augmentInfo(id) {
    const s = S();
    const a = (s.augments?.selected || []).find((row) => row.id === id);
    if (!a) return;
    const cat = (IX()?.augments?.selected || []).find((row) => row.id === id);
    const rows = ledgerRows(s, a);
    const lastRound = Number(cat?.last?.round) || Number(s.last_battle?.round) || 0;
    const fmt = (row) => [row.damage ? `伤害 ${row.damage}` : "", row.estimated ? `增伤≈${row.estimated}` : "",
      row.heal ? `治疗 ${row.heal}` : "", row.shield ? `护盾 ${row.shield}` : "", row.energy ? `能量 ${row.energy}` : "",
      row.prevented ? `减伤≈${row.prevented}` : ""].filter(Boolean).join(" · ") || (row.passive ? "常驻加成（已计入面板）" : "未触发");
    openSheet({kind: "info"}, `${CATEGORY_GLYPH[cat?.category] || "✦"} ${a.name}`, `
      <p class="ix-sheet-tag">${esc(cat?.category_name || "海克斯")}</p>
      <p>${esc(a.description || a.brief || "")}</p>
      ${a.current ? `<p class="ix-current">${esc(a.current)}</p>` : ""}
      <h4>上一战${lastRound ? `（第 ${lastRound} 轮）` : ""}</h4>
      ${rows.length ? `<ul class="ix-ledger">${rows.map((row) => `<li><strong>触发 ${Number(row.triggers) || 0} 次</strong><span>${esc(fmt(row))}</span></li>`).join("")}</ul>`
        : `<p class="ix-muted">${lastRound ? "上一战没有这条海克斯的收益记录（经济、规则类与未触发的不进战斗账本）。" : (s.battle_history || []).length ? "收益账本只保留本次打开页面后结算的战斗；下一场结束后显示。" : "还没有结算过战斗。"}</p>`}`);
  }

  function openAugments() {
    const s = S();
    if (!s?.augments?.pending?.length) return false;
    augmentDeferred = null;
    renderAugments(s, IX());
    return true;
  }

  // ------------------------------------------------------------ techniques
  function renderTmRack(s, ix) {
    const rack = $("ix-tm-rack");
    if (!rack) return;
    const list = Array.isArray(s.techniques) ? s.techniques : s.techniques?.inventory || [];
    const data = ix?.techniques || {};
    if (!list.length || !ix) {
      memo(rack).innerHTML = "";
      return;
    }
    const gold = Number(s.you?.gold) || 0;
    const card = (t) => {
      const row = data[t.id] || {};
      const count = Number(t.count) || 0;
      const compatible = (row.compatible || []).length;
      const affordable = count > 0 || gold >= (Number(t.cost) || 2);
      const disabled = !canPrep() || !compatible || !affordable;
      return `<button type="button" class="ix-tm-card${count ? " stocked" : ""}${mode?.kind === "tm" && mode.key === t.id ? " active" : ""}" data-ix-tm="${esc(t.id)}" ${disabled ? "disabled" : ""} ${disabled ? "" : `draggable="true" data-ix-drag="tm:${esc(t.id)}"`}>
        <span class="ix-tm-disc" aria-hidden="true">${count ? `×${count}` : "TM"}</span>
        <span class="ix-tm-main"><strong>${esc(t.name)}</strong><small>${esc(row.category_name || "技能")} · ${count ? `技能机 ×${count}` : `${Number(t.cost) || 2} 金学习`} · 可学 ${compatible} 只</small>
        ${row.best ? `<small class="ix-tm-best">推荐 ${esc(row.best.name)}：${esc(row.best.reasons?.[0] || "")}</small>` : `<small class="ix-muted">${compatible ? "暂无明显适配者" : "当前没有能学的伙伴"}</small>`}</span>
      </button>`;
    };
    const stocked = list.filter((t) => Number(t.count) > 0);
    const others = list.filter((t) => !(Number(t.count) > 0));
    memo(rack).innerHTML = `<p class="ix-rack-note">点一台技能机，棋盘上能学的伙伴会亮起；${isPhone() ? "再点伙伴确认。" : "也可以直接把它拖到伙伴身上。"}每只伙伴只有一个学习位，替换不返还。</p>
      ${stocked.length ? `<h4>仓库技能机</h4><div class="ix-tm-grid">${stocked.map(card).join("")}</div>` : ""}
      <details class="ix-tm-more"${stocked.length ? "" : " open"}><summary>花 2 金学习（${others.length} 种）</summary><div class="ix-tm-grid">${others.map(card).join("")}</div></details>`;
  }

  function tmConfirm(key, uid) {
    const s = S();
    const row = IX()?.techniques?.[key];
    const target = byUid(uid);
    const t = (Array.isArray(s.techniques) ? s.techniques : []).find((x) => x.id === key);
    if (!row || !target || !t) return;
    const count = Number(t.count) || 0;
    const gold = Number(s.you?.gold) || 0;
    const cost = Number(t.cost) || 2;
    const current = target.p.technique?.name || null;
    const blocked = !row.compatible.includes(uid) ? "这只伙伴学不了这台技能机" : target.p.technique?.id === key ? "已经学会了"
      : !count && gold < cost ? `金币不足（需要 ${cost} 金）` : "";
    const dual = (s.augments?.selected || []).some((a) => a.id === "dual_wield");
    const recommended = row.best?.uid === uid;
    openSheet({kind: "learn", key, uid}, `学习 ${t.name}`, `
      <div class="ix-unit-line"><img src="${sprite(target.p)}" alt=""><strong>${esc(target.p.name)} ${stars(target.p)}</strong>${recommended ? '<span class="ix-chip good">推荐人选</span>' : ""}</div>
      ${recommended && row.best.reasons?.length ? `<p class="ix-good">${row.best.reasons.map(esc).join("；")}</p>` : ""}
      <div class="ix-ba"><section><h4>学习位 · 现在</h4><p class="${current ? "" : "ix-muted"}">${esc(current || "空插槽")}</p></section><span aria-hidden="true">→</span><section class="after"><h4>学习后</h4><p><strong>${esc(t.name)}</strong></p><small>${esc(t.description || "")}</small></section></div>
      <p class="ix-cost">${count ? `消耗 1 台技能机（仓库 ${count} 台）` : `花费 ${cost} 金（现有 ${gold} 金）`}</p>
      ${current ? `<p class="ix-warn">替换会覆盖「${esc(current)}」，旧技能不返还。原生技能保留。</p>` : ""}
      ${dual ? '<p class="ix-warn">你选了「双持专精」：技能机在战斗中不会触发。</p>' : ""}
      ${blocked ? `<p class="ix-warn">${esc(blocked)}</p>` : ""}
      <div class="ix-sheet-actions"><button type="button" class="secondary-button" data-ix-close>取消</button><button type="button" class="primary-button" data-ix-confirm-learn ${blocked || !canPrep() ? "disabled" : ""}>确认学习</button></div>`);
  }

  function socketPicker(uid) {
    const target = byUid(uid);
    const data = IX()?.techniques || {};
    const s = S();
    if (!target) return;
    const list = (Array.isArray(s.techniques) ? s.techniques : []).filter((t) => data[t.id]?.compatible?.includes(uid));
    openSheet({kind: "socket", uid}, `为 ${target.p.name} 选择技能机`, list.length
      ? `<p class="ix-rack-note">学习位：${esc(target.p.technique?.name || "空插槽")}</p><div class="ix-tm-grid">${list.map((t) => `<button type="button" class="ix-tm-card${Number(t.count) ? " stocked" : ""}" data-ix-socket-pick="${esc(t.id)}" data-uid="${esc(uid)}"><span class="ix-tm-disc" aria-hidden="true">${Number(t.count) ? `×${Number(t.count)}` : "TM"}</span><span class="ix-tm-main"><strong>${esc(t.name)}</strong><small>${esc(data[t.id]?.category_name || "")} · ${Number(t.count) ? "技能机" : `${Number(t.cost) || 2} 金`}${data[t.id]?.best?.uid === uid ? " · 推荐" : ""}</small></span></button>`).join("")}</div>`
      : '<p class="ix-muted">这只伙伴目前没有可学的技能机。</p>');
  }

  // ------------------------------------------------------------ skills
  function decorateDetail(s, ix) {
    const detail = $("unit-detail");
    const loc = ctx.selected?.();
    const row = loc ? byLoc(loc) : null;
    if (!detail || !row) return;
    const skill = ix?.skills?.[row.p.uid];
    const native = detail.querySelector(".native-skill-slot");
    if (native && skill && !native.querySelector(".ix-skill-card")) {
      native.classList.add("ix-native-card");
      native.insertAdjacentHTML("beforeend", `<div class="ix-skill-card"><span class="ix-skill-glyph" aria-hidden="true">${esc(skill.glyph)}</span><span><b>${esc(skill.category_name)}</b>${skill.power ? ` · 威力 ${Number(skill.power)}` : ""}${skill.targeting_name ? ` · 目标 ${esc(skill.targeting_name)}` : ""}</span></div>`);
    }
    const learned = detail.querySelector(".learned-skill-slot");
    if (learned && !learned.querySelector(".ix-socket-button")) {
      learned.classList.add("ix-socket");
      learned.insertAdjacentHTML("beforeend", `<button type="button" class="ix-socket-button" data-ix-socket="${esc(row.p.uid)}" ${!canPrep() ? "disabled" : ""}>${row.p.technique ? "更换技能机" : "◌ 插入技能机"}</button>`);
    }
  }

  function pendingMods(s, ix) {
    if (!s.depth) return null;
    for (const row of owned()) {
      const mods = ix?.skills?.[row.p.uid]?.mods || [];
      if (mods.length && !modDeferred.has(`${s.round}:${row.p.uid}:${row.p.star}`)) return {row, mods};
    }
    return null;
  }

  function modChoice(row, mods) {
    openSheet({kind: "mod", uid: row.p.uid, star: row.p.star}, `${row.p.name} 升到 ${stars(row.p)}：选择技能强化`, `
      <div class="ix-unit-line"><img src="${sprite(row.p)}" alt=""><strong>${esc(row.p.name)} ${stars(row.p)}</strong><span class="ix-chip">永久 · 二选一</span></div>
      <div class="ix-mod-cards">${mods.map((m, i) => `<button type="button" class="ix-mod-card" style="--i:${i}" data-ix-mod="${esc(m.id)}" data-uid="${esc(row.p.uid)}" ${!canPrep() ? "disabled" : ""}><strong>${esc(m.name)}</strong><em>${esc(m.delta)}</em><small>${esc(m.description)}</small></button>`).join("")}</div>
      <div class="ix-sheet-actions"><button type="button" class="secondary-button" data-ix-mod-later data-uid="${esc(row.p.uid)}">稍后再选</button></div>`);
  }

  // ------------------------------------------------------------ item advice (docs/65 data, docs/66 UI)
  const ARCH = {"输出": "dps", "坦克": "tank", "控制": "ctrl", "联动": "combo", "辅助": "sup", "经济": "eco"};
  const ARCH_GLYPH = {"输出": "⚔", "坦克": "⛨", "控制": "❄", "联动": "⚙", "辅助": "✚", "经济": "◎"};
  let archFilter = null;     // item card filter (archetype name) or null = all
  let chase = null;          // item key highlighted on the recipe board
  const advice = () => IX()?.item_advice || null;
  const guideOf = (key) => advice()?.guides?.[key] || null;
  const archBadge = (a) => a ? `<span class="ix-arch arch-${ARCH[a] || "x"}"><b aria-hidden="true">${ARCH_GLYPH[a] || "◆"}</b>${esc(a)}</span>` : "";
  const kindBadge = (g) => !g ? "" : g.treasure ? '<span class="ix-kind treasure">宝物</span>'
    : g.mechanic ? '<span class="ix-kind mech">机制</span>' : '<span class="ix-kind stat">数值</span>';
  function combos(g, {limit = 3, short = false} = {}) {
    if (!g) return "";
    const on = (g.active || []).slice(0, limit).map((x) => `<li class="on"><span aria-hidden="true">✓</span>${esc(x)}</li>`).join("");
    const off = (g.missing || []).slice(0, short ? 1 : limit).map((x) => `<li class="off"><span aria-hidden="true">○</span>还差：${esc(x)}</li>`).join("");
    return on || off ? `<ul class="ix-combos">${on}${off}</ul>` : "";
  }
  const ACTION = {equip: ["装备", "装上"], craft: ["合成", "合成并装给"], chase: ["凑齐", "在合成图中查看"]};

  function renderAdvice(s, ix) {
    const box = $("ix-advice");
    if (!box) return;
    const adv = ix?.item_advice;
    box.hidden = !adv;
    if (!adv) { memo(box).innerHTML = ""; return; }
    const order = adv.archetype_order || Object.keys(ARCH);
    const team = adv.team_archetypes || {};
    const total = Object.values(team).reduce((n, v) => n + Number(v || 0), 0);
    const lacking = total >= 2 ? ["坦克", "输出", "控制"].filter((a) => order.includes(a) && !team[a]) : [];
    const rows = adv.suggestions || [];
    const card = (row) => {
      const [label, cta] = ACTION[row.action] || ["建议", "查看"];
      const target = row.action === "chase" ? `差 <b>${esc(row.lacking)}</b> · 合成后给 ${esc(row.unit)}`
        : row.action === "craft" ? `${(row.recipe || []).map(esc).join(" + ")} → 给 ${esc(row.unit)}` : `给 ${esc(row.unit)}`;
      return `<article class="ix-advice-card act-${esc(row.action)}">
        <header><span class="ix-act">${label}</span><b>${esc(row.name)}</b>${archBadge(row.archetype)}</header>
        <p class="ix-advice-target">${target}</p>
        ${(row.why || []).length ? `<ul class="ix-combos">${row.why.slice(0, 3).map((x) => `<li class="on"><span aria-hidden="true">✓</span>${esc(x)}</li>`).join("")}</ul>` : ""}
        <button type="button" class="${row.action === "chase" ? "secondary-button" : "primary-button"}" data-ix-advice="${esc(row.action)}" data-item="${esc(row.item)}" data-uid="${esc(row.uid || "")}" ${row.action !== "chase" && !canPrep() ? "disabled" : ""}>${cta}${row.action === "craft" ? ` ${esc(row.unit)}` : ""}</button>
      </article>`;
    };
    memo(box).innerHTML = `<div class="section-heading"><h2>配装建议</h2><span class="tiny-label">${rows.length ? `${rows.length} 条 · 按收益排序` : "ADVISOR"}</span></div>
      <div class="ix-team-arch" aria-label="已装备道具类型"><span class="ix-team-label">队伍道具</span>${order.map((a) => `<span class="ix-arch arch-${ARCH[a] || "x"}${team[a] ? "" : " zero"}"><b aria-hidden="true">${ARCH_GLYPH[a] || "◆"}</b>${esc(a)} ${Number(team[a]) || 0}</span>`).join("")}${lacking.length ? `<em class="ix-team-hint">缺少${lacking.join("、")}道具</em>` : ""}</div>
      ${rows.length ? `<div class="ix-advice-list">${rows.map(card).join("")}</div>` : '<p class="empty-copy">暂时没有能马上执行的配装：继续收集组件，或看下方合成图。</p>'}`;
  }

  function renderArchFilter(s, ix, keys) {
    const box = $("ix-item-filter");
    if (!box) return;
    const order = ix?.item_advice?.archetype_order || [];
    const counts = new Map();
    for (const key of keys) {
      const a = guideOf(key)?.archetype;
      if (a) counts.set(a, (counts.get(a) || 0) + 1);
    }
    if (archFilter && !counts.has(archFilter)) archFilter = null;
    box.hidden = counts.size < 2;
    memo(box).innerHTML = counts.size < 2 ? "" : `<button type="button" data-ix-arch="" aria-pressed="${!archFilter}">全部 ${keys.length}</button>${order.filter((a) => counts.has(a)).map((a) => `<button type="button" class="arch-${ARCH[a] || "x"}" data-ix-arch="${esc(a)}" aria-pressed="${archFilter === a}"><b aria-hidden="true">${ARCH_GLYPH[a] || "◆"}</b>${esc(a)} ${counts.get(a)}</button>`).join("")}`;
  }

  // ------------------------------------------------------------ items
  function renderItems(s, ix) {
    const box = $("ix-items");
    if (!box) return;
    const data = ix?.equip?.items || {};
    const finished = s.items?.finished || [];
    const counts = new Map();
    for (const item of finished) counts.set(item.key, (counts.get(item.key) || 0) + 1);
    const depth = s.depth?.items;
    renderArchFilter(s, ix, [...counts.keys()]);
    const shown = [...counts].filter(([key]) => !archFilter || guideOf(key)?.archetype === archFilter);
    memo(box).innerHTML = counts.size ? shown.map(([key, n]) => {
      const row = data[key] || {};
      const item = finished.find((x) => x.key === key);
      const guide = guideOf(key);
      const lines = [...(row.lines || []), ...(row.stats || []).map((x) => `组件 ${x}`)];
      return `<article class="ix-item-card" data-arch="${esc(ARCH[guide?.archetype] || "")}" ${canPrep() ? `draggable="true" data-ix-drag="item:${esc(key)}"` : ""}>
        <header><b>◆ ${esc(row.name || item?.name || key)}</b>${n > 1 ? `<span class="ix-chip">×${n}</span>` : ""}${archBadge(guide?.archetype)}${kindBadge(guide)}${row.recipe ? `<small>${esc(row.recipe)}</small>` : ""}</header>
        ${guide?.playstyle ? `<p class="ix-playstyle">${esc(guide.playstyle)}</p>` : ""}
        ${combos(guide)}
        ${lines.length ? `<div class="ix-item-lines">${lines.map((x) => `<span>${esc(x)}</span>`).join("")}</div>` : ""}
        <p>${esc(row.effect || item?.effect || "")}</p>
        ${row.suits ? `<p class="ix-item-suits">适合：${esc(row.suits)}${row.carriers?.length ? ` · 推荐 ${row.carriers.map((c) => esc(c.name)).join(" › ")}` : ""}</p>` : '<p class="ix-item-suits ix-muted">队里暂时没有特别适合的携带者</p>'}
        <div class="ix-item-actions"><button type="button" class="primary-button" data-ix-equip="${esc(key)}" ${!canPrep() ? "disabled" : ""}>选择携带者</button>${depth ? `<button type="button" data-depth-dismantle="${esc(key)}" ${!canPrep() ? "disabled" : ""}>拆解${depth.dismantle_cost ? ` · ${Number(depth.dismantle_cost)} 金` : ""}</button><button type="button" data-depth-sell-item="${esc(key)}" ${!canPrep() ? "disabled" : ""}>出售 +${Number(depth.sell_value)}</button>` : ""}</div>
      </article>`;
    }).join("") : '<p class="empty-copy">还没有成品装备：在下面的合成图里把两个组件合成一件。</p>';
  }

  function equipConfirm(key, uid) {
    const s = S();
    const ix = IX();
    const row = ix?.equip?.items?.[key];
    const target = byUid(uid);
    if (!row || !target) return;
    const slots = ix.equip.slots?.[uid] || {total: 1, used: target.p.item ? 1 : 0, items: []};
    const full = slots.used >= slots.total;
    const rank = (row.carriers || []).findIndex((c) => c.uid === uid);
    const held = (slots.items || []).map((item) => `<li><b>◆ ${esc(item.name)}</b>${[...(item.lines || []), ...(item.stats || [])].map((x) => `<span>${esc(x)}</span>`).join("")}</li>`).join("");
    const added = [...(row.lines || []), ...(row.stats || []).map((x) => `组件 ${x}`)];
    openSheet({kind: "equip", key, uid}, `装备 ${row.name}`, `
      <div class="ix-unit-line"><img src="${sprite(target.p)}" alt=""><strong>${esc(target.p.name)} ${stars(target.p)}</strong>${rank >= 0 ? `<span class="ix-chip good">推荐 #${rank + 1}</span>` : ""}</div>
      ${rank >= 0 ? `<p class="ix-good">${esc(row.carriers[rank].reason)}</p>` : row.suits ? `<p class="ix-muted">更适合：${esc(row.suits)}</p>` : ""}
      <div class="ix-ba"><section><h4>装备位 ${slots.used}/${slots.total}</h4>${held ? `<ul class="ix-held">${held}</ul>` : '<p class="ix-muted">空装备位</p>'}</section><span aria-hidden="true">→</span><section class="after"><h4>装备后 ${Math.min(slots.total, slots.used + 1)}/${slots.total}</h4><ul class="ix-held">${held}<li class="new"><b>◆ ${esc(row.name)}</b>${added.map((x) => `<span>${esc(x)}</span>`).join("")}</li></ul></section></div>
      ${row.effect ? `<p>${esc(row.effect)}</p>` : ""}
      ${slots.total > 1 && slots.used === 1 && !full ? '<p class="ix-good">装进第二装备位（核心 / 双持）。</p>' : ""}
      ${full ? `<p class="ix-warn">装备位已满：先卸下${s.depth ? `（每件 ${Number(ix.equip.unequip_cost)} 金）` : ""}再换。</p>` : ""}
      <div class="ix-sheet-actions"><button type="button" class="secondary-button" data-ix-close>取消</button><button type="button" class="primary-button" data-ix-confirm-equip ${full || !canPrep() ? "disabled" : ""}>确认装备</button></div>`);
  }

  // ------------------------------------------------------------ recipes
  const shortName = (name) => String(name || "").replace(/(之|石碎片|线圈|头带|水滴)$/, "").slice(0, 3);
  function cellFor(a, b) {
    const cells = IX()?.recipes?.cells || [];
    return cells.find((c) => (c.a === a && c.b === b) || (c.a === b && c.b === a)) || null;
  }
  function renderRecipes(s, ix) {
    const box = $("ix-recipes");
    if (!box) return;
    const data = ix?.recipes;
    if (!data) {
      memo(box).innerHTML = "";
      return;
    }
    const comps = data.components || [];
    const ready = (data.cells || []).filter((c) => c.craftable).length;
    const chasing = chase ? (ix?.item_advice?.suggestions || []).find((r) => r.item === chase) || null : null;
    if (chase && !chasing) chase = null;
    const head = comps.map((c) => `<span class="ix-mx-head${c.n ? " have" : ""}" title="${esc(c.name)}${c.stats ? `：${esc(c.stats)}` : ""}">${esc(shortName(c.name))}<b>${Number(c.n)}</b></span>`).join("");
    const rows = comps.map((ra) => `<span class="ix-mx-head row${ra.n ? " have" : ""}">${esc(shortName(ra.name))}<b>${Number(ra.n)}</b></span>${comps.map((cb) => {
      const cell = cellFor(ra.key, cb.key);
      if (!cell) return '<span class="ix-mx-cell dead"></span>';
      const cls = cell.dead ? "dead" : cell.craftable ? "craftable" : cell.blocked ? "blocked" : cell.missing.length === 1 ? "near" : "missing";
      const label = cell.dead ? "—" : esc(shortName(cell.name));
      const g = cell.item ? guideOf(cell.item) : null;
      const arch = g?.archetype ? ` arch-${ARCH[g.archetype] || "x"}` : "";
      const mark = g?.treasure ? "★" : g?.mechanic ? "⚙" : "";
      const sub = cell.dead ? "" : cell.craftable ? "可合成" : cell.blocked ? "已达上限" : `差${cell.missing.length}`;
      return `<button type="button" class="ix-mx-cell ${cls}${cell.depth ? " depth" : ""}${arch}${chase && cell.item === chase ? " ix-chase" : ""}" data-ix-cell="${esc(cell.a)}|${esc(cell.b)}" aria-label="${esc(ra.name)} + ${esc(cb.name)}：${cell.dead ? "无配方" : `${esc(cell.name)}，${sub}`}"${cell.dead ? " disabled" : ""}>${mark ? `<i class="ix-mech" aria-hidden="true">${mark}</i>` : ""}<b>${label}</b>${sub ? `<small>${sub}</small>` : ""}</button>`;
    }).join("")}`).join("");
    memo(box).innerHTML = `<div class="section-heading"><h2>组件合成图</h2><span class="tiny-label">${ready ? `${ready} 件可合成` : "RECIPES"}</span></div>
      <p class="section-note">行列是 8 种组件（右下数字 = 库存）。亮起的格子现在就能合成；${isPhone() ? "点格子查看并合成。" : "点格子合成，或把一个组件拖到另一个组件上。"}${s.depth ? "金框为深度版新增配方。" : "灰色为无配方的组合。"}</p>
      ${chasing ? `<p class="ix-chase-note">正在凑：<b>${esc(chasing.name)}</b> · 还差 <b>${esc(chasing.lacking || "—")}</b> · 合成后给 ${esc(chasing.unit)}<button type="button" data-ix-chase-clear>取消</button></p>` : ""}
      <div class="ix-comp-row">${comps.map((c) => `<span class="ix-comp${c.n ? " have" : ""}${chase && chaseLacking() === c.key ? " ix-chase" : ""}" data-ix-comp="${esc(c.key)}" ${c.n && canPrep() ? `draggable="true" data-ix-drag="comp:${esc(c.key)}"` : ""} title="${esc(c.stats || c.name)}"><b>${esc(c.name)}</b><small>×${Number(c.n)}${c.stats ? ` · ${esc(c.stats)}` : ""}</small></span>`).join("")}</div>
      <div class="ix-matrix-scroll"><div class="ix-matrix"><span class="ix-mx-corner" aria-hidden="true">＋</span>${head}${rows}</div></div>`;
  }

  function chaseLacking() {
    const row = (IX()?.item_advice?.suggestions || []).find((r) => r.item === chase && r.action === "chase");
    return row ? (IX()?.recipes?.components || []).find((c) => c.name === row.lacking)?.key || null : null;
  }

  function cellSheet(a, b) {
    const cell = cellFor(a, b);
    const s = S();
    if (!cell || cell.dead) return;
    const names = new Map((IX()?.recipes?.components || []).map((c) => [c.key, c.name]));
    openSheet({kind: "craft", item: cell.item}, `合成 ${cell.name}`, `
      <p class="ix-recipe-line">${esc(names.get(cell.a))} <span>+</span> ${esc(names.get(cell.b))} <span>→</span> <strong>${esc(cell.name)}</strong>${cell.depth ? ' <span class="ix-chip gold">深度版</span>' : ""}</p>
      ${cell.stats?.length ? `<div class="ix-item-lines">${cell.stats.map((x) => `<span>组件 ${esc(x)}</span>`).join("")}</div>` : ""}
      ${guideOf(cell.item) ? `<p class="ix-sheet-tag">${archBadge(guideOf(cell.item).archetype)}${kindBadge(guideOf(cell.item))}</p>${guideOf(cell.item).playstyle ? `<p class="ix-playstyle">${esc(guideOf(cell.item).playstyle)}</p>` : ""}${combos(guideOf(cell.item), {limit: 4})}` : ""}
      <p>${esc(cell.effect)}</p>
      ${cell.craftable ? "" : `<p class="ix-warn">${cell.blocked ? "幸运蛋已达全场上限" : `还差：${cell.missing.map(esc).join("、")}`}</p>`}
      <div class="ix-sheet-actions"><button type="button" class="secondary-button" data-ix-close>关闭</button><button type="button" class="primary-button" data-ix-confirm-craft="${esc(cell.item)}" ${!cell.craftable || !canPrep() || !s ? "disabled" : ""}>合成</button></div>`);
  }

  // ------------------------------------------------------------ targeting mode
  function enterMode(kind, key, options = {}) {
    mode = {kind, key, ...options};
    flash = "";
    closeSheet();
    if (isPhone() && !options.drag) window.PlayLayout?.close?.();
    decorateBoard();
  }
  function exitMode() {
    mode = null;
    flash = "";
    decorateBoard();
  }

  function validity(uid) {
    const ix = IX();
    if (!mode || !ix) return null;
    if (mode.kind === "tm") {
      const row = ix.techniques?.[mode.key];
      const ok = Boolean(row?.compatible?.includes(uid) && !row.known_by?.includes(uid));
      return {ok, rank: ok && row.best?.uid === uid ? 1 : 0};
    }
    const row = ix.equip?.items?.[mode.key];
    const slot = ix.equip?.slots?.[uid];
    const ok = Boolean(slot && slot.used < slot.total);
    const rank = (row?.carriers || []).findIndex((c) => c.uid === uid);
    return {ok, rank: ok && rank >= 0 ? rank + 1 : 0};
  }

  function decorateBoard() {
    const tiles = [...($("ally-board")?.querySelectorAll("[data-loc]") || []), ...($("bench")?.querySelectorAll("[data-loc]") || [])];
    document.body.classList.toggle("ix-targeting", Boolean(mode));
    for (const card of $("ix-items")?.querySelectorAll("[data-ix-equip]") || [])
      card.closest?.(".ix-item-card")?.classList.toggle("active", mode?.kind === "equip" && mode.key === card.getAttribute("data-ix-equip"));
    for (const tile of tiles) {
      tile.classList.remove("ix-valid", "ix-dim", "ix-best");
      tile.querySelector(".ix-rank")?.remove?.();
      if (!mode) continue;
      const row = byLoc(tile.getAttribute("data-loc"));
      if (!row) {
        tile.classList.add("ix-dim");
        continue;
      }
      const v = validity(row.p.uid);
      tile.classList.add(v?.ok ? "ix-valid" : "ix-dim");
      if (v?.rank) {
        tile.classList.add("ix-best");
        tile.insertAdjacentHTML("beforeend", `<span class="ix-rank" aria-label="推荐第 ${v.rank}">${v.rank}</span>`);
      }
    }
    const bar = $("ix-target-bar");
    if (!bar) return;
    bar.hidden = !mode;
    if (!mode) {
      memo(bar).innerHTML = "";
      return;
    }
    const ix = IX();
    let text = "";
    if (mode.kind === "tm") {
      const t = (Array.isArray(S().techniques) ? S().techniques : []).find((x) => x.id === mode.key);
      const best = ix?.techniques?.[mode.key]?.best;
      text = `<b>学习「${esc(t?.name || mode.key)}」</b><small>点亮起的伙伴${best ? ` · 推荐 ${esc(best.name)}` : ""}</small>`;
    } else {
      const row = ix?.equip?.items?.[mode.key];
      const top = row?.carriers?.[0];
      const active = guideOf(mode.key)?.active || [];
      text = `<b>装备「${esc(row?.name || mode.key)}」</b><small>${top ? `推荐 1.${esc(top.name)}：${esc(top.reason.split(" · ").slice(1).join(" · ") || top.reason)}${row.carriers.length > 1 ? ` · ${row.carriers.slice(1).map((c, i) => `${i + 2}.${esc(c.name)}`).join(" ")}` : ""}` : "点亮起的伙伴"}</small>${active.length ? `<small class="ix-bar-combos">✓ ${active.slice(0, 2).map(esc).join(" · ")}</small>` : ""}`;
    }
    memo(bar).innerHTML = `<span class="ix-bar-main">${text}${flash ? `<em>${esc(flash)}</em>` : ""}</span><button type="button" data-ix-cancel-mode>取消</button>`;
  }

  function targetUnit(loc) {
    const row = byLoc(loc);
    if (!mode) return;
    if (!row) {
      flash = "这里没有伙伴";
      decorateBoard();
      return;
    }
    const v = validity(row.p.uid);
    if (!v?.ok) {
      flash = mode.kind === "tm" ? `${row.p.name} 学不了这台技能机` : `${row.p.name} 的装备位已满`;
      decorateBoard();
      return;
    }
    const {kind, key} = mode;
    exitMode();
    if (kind === "tm") tmConfirm(key, row.p.uid);
    else equipConfirm(key, row.p.uid);
  }

  // ------------------------------------------------------------ sheet
  function openSheet(meta, title, html) {
    sheet = meta;
    $("ix-sheet").hidden = false;
    $("ix-sheet").className = `ix-sheet kind-${meta.kind}`;
    $("ix-sheet-title").textContent = title;
    memo($("ix-sheet-body")).innerHTML = html;
    document.body.classList.add("ix-sheet-open");
  }
  function closeSheet() {
    sheet = null;
    if ($("ix-sheet")) $("ix-sheet").hidden = true;
    document.body.classList.remove("ix-sheet-open");
  }

  async function run(cmd, params) {
    const result = await ctx.api(cmd, params);
    if (result?.ok) closeSheet();
    return result;
  }

  // ------------------------------------------------------------ render
  function render(context) {
    ctx = context;
    const s = context.state;
    if (!s) return;
    const ix = s.interactions || null;
    document.body.classList.toggle("ix-ready", Boolean(ix && !ix.error));
    if (!ctx.playable()) {
      mode = null;
      if (sheet && sheet.kind !== "info") closeSheet();
    }
    if (context.reason === "selection") {
      decorateDetail(s, ix);
      decorateBoard();
      return;
    }
    renderAugments(s, ix);
    renderStrip(s, ix);
    renderTmRack(s, ix);
    renderAdvice(s, ix);
    renderItems(s, ix);
    renderRecipes(s, ix);
    decorateDetail(s, ix);
    // A sheet built from stale data is refreshed with the new state.
    if (sheet?.kind === "learn") tmConfirm(sheet.key, sheet.uid);
    else if (sheet?.kind === "equip") equipConfirm(sheet.key, sheet.uid);
    else if (sheet?.kind === "mod" && !byUid(sheet.uid)?.p?.mod_options?.length) closeSheet();
    const overlays = document.body.classList.contains("ix-augment-open") || document.body.classList.contains("draft-open");
    if (!sheet && !mode && !overlays && ctx.playable()) {
      const pending = pendingMods(s, ix);
      if (pending) modChoice(pending.row, pending.mods);
    }
    decorateBoard();
  }

  // ------------------------------------------------------------ events
  const closestOf = (node, selectors) => {
    for (const selector of selectors) {
      const hit = node?.closest?.(selector);
      if (hit) return hit;
    }
    return null;
  };
  const CONTROLS = ["[data-ix-tm]", "[data-ix-equip]", "[data-ix-cell]", "[data-ix-socket]", "[data-ix-socket-pick]",
    "[data-ix-confirm-learn]", "[data-ix-confirm-equip]", "[data-ix-confirm-craft]", "[data-ix-mod]", "[data-ix-mod-later]",
    "[data-ix-close]", "[data-ix-cancel-mode]", "[data-ix-advice]", "[data-ix-arch]", "[data-ix-chase-clear]", "[data-ix-augment-later]", "[data-ix-open-augment]", "[data-ix-augment-info]"];

  document.addEventListener("click", async (event) => {
    if (!ctx) return;
    // Targeting mode owns board taps so play.js does not move / select.
    const tile = mode ? event.target?.closest?.("[data-loc]") : null;
    if (tile) {
      stop(event);
      targetUnit(tile.getAttribute("data-loc"));
      return;
    }
    const target = closestOf(event.target, CONTROLS) || (event.target?.id === "ix-sheet" ? event.target : null);
    if (!target || target.disabled) return;
    const attr = (name) => target.getAttribute(name);
    if (target.id === "ix-sheet" || target.hasAttribute("data-ix-close")) {
      if (sheet?.kind === "mod") modDeferred.add(`${S().round}:${sheet.uid}:${sheet.star}`);
      closeSheet();
    } else if (target.hasAttribute("data-ix-tm")) {
      if (mode?.kind === "tm" && mode.key === attr("data-ix-tm")) exitMode();
      else enterMode("tm", attr("data-ix-tm"));
    } else if (target.hasAttribute("data-ix-equip")) {
      if (mode?.kind === "equip" && mode.key === attr("data-ix-equip")) exitMode();
      else enterMode("equip", attr("data-ix-equip"));
    } else if (target.hasAttribute("data-ix-cancel-mode")) exitMode();
    else if (target.hasAttribute("data-ix-advice")) await followAdvice(attr("data-ix-advice"), attr("data-item"), attr("data-uid"));
    else if (target.hasAttribute("data-ix-arch")) {
      archFilter = attr("data-ix-arch") || null;
      renderItems(S(), IX());
    } else if (target.hasAttribute("data-ix-chase-clear")) {
      chase = null;
      renderRecipes(S(), IX());
    }
    else if (target.hasAttribute("data-ix-cell")) {
      const [a, b] = attr("data-ix-cell").split("|");
      cellSheet(a, b);
    } else if (target.hasAttribute("data-ix-socket")) socketPicker(attr("data-ix-socket"));
    else if (target.hasAttribute("data-ix-socket-pick")) tmConfirm(attr("data-ix-socket-pick"), attr("data-uid"));
    else if (target.hasAttribute("data-ix-confirm-learn") && sheet?.kind === "learn" && canPrep()) {
      const row = byUid(sheet.uid);
      if (row) await run("learn", {loc: row.loc, technique: sheet.key});
    } else if (target.hasAttribute("data-ix-confirm-equip") && sheet?.kind === "equip" && canPrep()) {
      const row = byUid(sheet.uid);
      if (row) await run("equip", {item: sheet.key, loc: row.loc});
    } else if (target.hasAttribute("data-ix-confirm-craft") && canPrep()) await run("craft", {item: attr("data-ix-confirm-craft")});
    else if (target.hasAttribute("data-ix-mod") && canPrep()) {
      const row = byUid(attr("data-uid"));
      if (row) await run("choose_mod", {loc: row.loc, mod: attr("data-ix-mod")});
    } else if (target.hasAttribute("data-ix-mod-later")) {
      const row = byUid(attr("data-uid"));
      modDeferred.add(`${S().round}:${attr("data-uid")}:${row?.p?.star}`);
      closeSheet();
    } else if (target.hasAttribute("data-ix-augment-later")) {
      augmentDeferred = S()?.round ?? null;
      renderAugments(S(), IX());
    } else if (target.hasAttribute("data-ix-open-augment")) openAugments();
    else if (target.hasAttribute("data-ix-augment-info")) augmentInfo(attr("data-ix-augment-info"));
  }, true);

  /** One-tap advice: equip opens the usual confirm, craft crafts then offers the carrier, chase points at the board. */
  async function followAdvice(action, item, uid) {
    if (action === "equip") return equipConfirm(item, uid);
    if (action === "craft") {
      if (!canPrep()) return;
      const result = await ctx.api("craft", {item});
      if (result?.ok && byUid(uid) && IX()?.equip?.items?.[item]) {
        equipConfirm(item, uid);
        const head = $("ix-sheet-body")?.querySelector(".ix-unit-line");
        head?.insertAdjacentHTML?.("beforeend", '<span class="ix-chip gold">刚合成</span>');
      }
      return;
    }
    chase = item;
    window.PlayLayout?.open?.("bag", window.PlayLayout?.isPhone?.() ? {size: "full"} : {});
    renderRecipes(S(), IX());
    $("ix-recipes")?.querySelector(".ix-chase")?.scrollIntoView?.({block: "center", behavior: "smooth"});
  }

  // Desktop drag: machines / items onto units, one component onto another.
  document.addEventListener("dragstart", (event) => {
    const source = event.target?.closest?.("[data-ix-drag]");
    if (!source || !canPrep()) return;
    event.stopPropagation?.();
    const [kind, key] = source.getAttribute("data-ix-drag").split(":");
    drag = {kind, key};
    try { event.dataTransfer.setData("text/plain", `ix:${kind}:${key}`); event.dataTransfer.effectAllowed = "copy"; } catch (_) { /* old browsers */ }
    document.body.classList.add("ix-dragging", `ix-drag-${kind}`);
    if (kind === "tm") enterMode("tm", key, {drag: true});
    if (kind === "item") enterMode("equip", key, {drag: true});
  }, true);
  document.addEventListener("dragover", (event) => {
    if (!drag) return;
    const hit = drag.kind === "comp" ? event.target?.closest?.("[data-ix-comp]") : event.target?.closest?.("[data-loc]");
    if (!hit) return;
    stop(event);
    try { event.dataTransfer.dropEffect = "copy"; } catch (_) { /* ignore */ }
  }, true);
  document.addEventListener("drop", async (event) => {
    if (!drag) return;
    const current = drag;
    if (current.kind === "comp") {
      const hit = event.target?.closest?.("[data-ix-comp]");
      if (!hit) return;
      stop(event);
      endDrag();
      const cell = cellFor(current.key, hit.getAttribute("data-ix-comp"));
      if (cell?.craftable && canPrep()) await ctx.api("craft", {item: cell.item});
      else if (cell) cellSheet(cell.a, cell.b);
      return;
    }
    const tile = event.target?.closest?.("[data-loc]");
    if (!tile) return;
    stop(event);
    endDrag(false);
    targetUnit(tile.getAttribute("data-loc"));
  }, true);
  function endDrag(clearMode = true) {
    drag = null;
    document.body.classList.remove("ix-dragging", "ix-drag-tm", "ix-drag-item", "ix-drag-comp");
    if (clearMode && mode?.drag) exitMode();
  }
  document.addEventListener("dragend", () => { if (drag) endDrag(); }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (sheet) {
      if (sheet.kind === "mod") modDeferred.add(`${S().round}:${sheet.uid}:${sheet.star}`);
      closeSheet();
      stop(event);
    } else if (mode) {
      exitMode();
      stop(event);
    }
  }, true);

  window.PlayInteractions = {render, openAugments, mode: () => mode, sheet: () => sheet};
})();
