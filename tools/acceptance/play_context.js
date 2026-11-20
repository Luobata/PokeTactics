/* Context menu for the prep screen (docs/70).
 *
 * Right-click (desktop), long press LONG_PRESS_MS (touch), the Menu key or
 * Shift+F10 on a focused unit / shop card / item / machine / board cell opens
 * one small themed menu with the actions that make sense there. On phones the
 * same entries open as a bottom action sheet, headed by the preview card.
 *
 * Every entry the client can already judge (phase, gold, slots, population,
 * bench room) is shown disabled with the reason instead of letting the server
 * reject it. Mutations go through ctx.api, so optimistic UI and the action
 * feedback layer behave exactly as for the regular buttons.
 *
 * play.js calls PlayContext.render(ctx) after every render; ctx.actions holds
 * the selection helpers (selectUnit, quickPlace, buyAndPlace, …). */
(function () {
  "use strict";
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  const LONG_PRESS_MS = 450;
  const ROWS = ["前排", "中排", "后排"];
  let ctx = null;
  let menu = null;
  let backdrop = null;
  let view = null;        // {target, title, entries, stack: [{title, entries}], anchor, returnFocus, at}
  let suppressClickUntil = 0;
  let eatClick = false;
  let longPressAt = 0;

  const S = () => ctx?.state || null;
  const IX = () => S()?.interactions || null;
  const isPhone = () => Boolean(window.PlayLayout?.isPhone?.());
  const stars = (p) => "★".repeat(Math.max(1, Math.min(3, Number(p?.star) || 1)));
  const short = (text, n = 22) => {
    const value = String(text || "");
    return value.length > n ? `${value.slice(0, n - 1)}…` : value;
  };
  function pieceAt(loc) {
    const s = S();
    if (!s || !loc) return null;
    if (loc[0] === "b") return s.bench?.[Number(loc.slice(1))] || null;
    const m = /^g(\d),(\d)$/.exec(loc);
    return m ? s.board?.[Number(m[1])]?.[Number(m[2])] || null : null;
  }
  function enemyAt(loc) {
    const m = /^g(\d),(\d)$/.exec(loc || "");
    return m ? S()?.opponent?.rows?.[Number(m[1])]?.[Number(m[2])] || null : null;
  }
  function owned() {
    const s = S();
    const rows = [];
    (s?.board || []).forEach((row, r) => row.forEach((p, c) => p && rows.push({p, loc: `g${r},${c}`})));
    (s?.bench || []).forEach((p, i) => p && rows.push({p, loc: `b${i}`}));
    return rows;
  }
  const locOf = (uid) => owned().find((row) => row.p.uid === uid)?.loc || null;
  const techniques = () => {
    const t = S()?.techniques;
    return Array.isArray(t) ? t : t?.inventory || [];
  };

  // ------------------------------------------------------------ targets
  /** {kind, key, el} for a node: unit / cell / enemy / shop / item / tm, or null. */
  function targetOf(node) {
    if (!node?.closest || !S()) return null;
    let el;
    if ((el = node.closest("[data-enemy-loc]"))) {
      const loc = el.getAttribute("data-enemy-loc");
      return enemyAt(loc) ? {kind: "enemy", key: loc, el} : null;
    }
    if ((el = node.closest("[data-loc]"))) {
      const loc = el.getAttribute("data-loc");
      return {kind: pieceAt(loc) ? "unit" : "cell", key: loc, el};
    }
    if ((el = node.closest("[data-shop]"))) {
      const i = Number(el.getAttribute("data-shop"));
      return S().shop?.[i] ? {kind: "shop", key: i, el} : null;
    }
    if ((el = node.closest(".ix-item-card"))) {
      const key = el.querySelector("[data-ix-equip]")?.getAttribute("data-ix-equip") || (el.getAttribute("data-ix-drag") || "").split(":")[1];
      return key ? {kind: "item", key, el} : null;
    }
    if ((el = node.closest("[data-equip]"))) return {kind: "item", key: el.getAttribute("data-equip"), el};
    if ((el = node.closest("[data-ix-tm]"))) return {kind: "tm", key: el.getAttribute("data-ix-tm"), el};
    return null;
  }

  // ------------------------------------------------------------ entries
  /** Why nothing can be changed right now, or "". */
  function lockedReason() {
    const s = S();
    if (!s) return "正在连接冒险…";
    if (ctx.busy?.()) return "正在处理上一步…";
    if (ctx.playable?.()) return "";
    if (s.phase === "over") return "冒险已经结束";
    if (!s.you?.alive) return "你已结束这场冒险";
    if (s.phase !== "prep") return "准备阶段才能操作";
    return "请先点「继续存档」核对进度";
  }
  const call = (cmd, params) => () => ctx.api(cmd, params);
  // Menu equips skip the confirm sheet; the next few seconds offer a free undo instead
  // (the server refunds an unequip that directly follows the equip, docs/70).
  let undoTimer = 0;
  function equipNow(item, loc) {
    return async () => {
      const before = pieceAt(loc);
      const slot = before?.item ? "1" : "0";
      const name = itemName(item);   // resolve before the item leaves the bag
      const result = await ctx.api("equip", {item, loc});
      if (!result?.ok) return;
      let bar = document.getElementById("cx-undo");
      if (!bar) {
        bar = document.createElement("div");
        bar.id = "cx-undo";
        bar.className = "cx-undo";
        bar.setAttribute("role", "status");
        document.body.append(bar);
      }
      bar.innerHTML = `<span>已装备 ◆${String(name).replace(/[<>&"]/g, "")}</span><button type="button">撤销</button>`;
      bar.hidden = false;
      bar.querySelector("button").onclick = async () => {
        bar.hidden = true;
        clearTimeout(undoTimer);
        await ctx.api("unequip", {loc, slot});
      };
      clearTimeout(undoTimer);
      undoTimer = setTimeout(() => { bar.hidden = true; }, 5000);
    };
  }
  // Any other action ends the free-undo window on the server; hide the chip too.
  document.addEventListener("pointerdown", (event) => {
    const bar = document.getElementById("cx-undo");
    if (bar && !bar.hidden && !bar.contains(event.target)) bar.hidden = true;
  }, true);
  const benchFull = () => (S().bench || []).filter(Boolean).length >= (Number(S().you?.bench_cap) || 8);
  const popFull = () => Number(S().you?.on_board) >= Number(S().you?.pop);
  const popReason = () => `上场人口已满（${Number(S().you.on_board)}/${Number(S().you.pop)}）`;
  function slotsOf(p) {
    const slot = IX()?.equip?.slots?.[p.uid];
    if (slot) return slot;
    return {total: p.is_core && S()?.depth ? 2 : 1, used: (p.item ? 1 : 0) + (p.extra_item ? 1 : 0)};
  }
  function itemKeys() {
    const keys = [];
    for (const item of S()?.items?.finished || []) if (!keys.includes(item.key)) keys.push(item.key);
    return keys;
  }
  const itemName = (key) => IX()?.equip?.items?.[key]?.name || (S()?.items?.finished || []).find((x) => x.key === key)?.name || key;
  const itemEffect = (key) => {
    const row = IX()?.equip?.items?.[key];
    return row?.lines?.[0] || row?.effect || (S()?.items?.finished || []).find((x) => x.key === key)?.effect || "";
  };
  function awakenOptions(filter) {
    return (IX()?.item_synergy?.awaken?.options || []).filter((o) => o.ready && filter(o));
  }
  const awakenEntry = (o, why) => ({label: `觉醒 ${o.name}`, hint: o.unit || "仓库", tone: "primary", disabled: why,
    run: call("awaken", {item: o.key, uid: o.uid || "", component: o.have?.[0] || ""})});

  function equipMenu(p, loc, why) {
    const advice = (IX()?.item_advice?.suggestions || []).find((row) => row.action === "equip" && row.uid === p.uid);
    const rank = (key) => {
      if (advice?.item === key) return -1;
      const i = (IX()?.equip?.items?.[key]?.carriers || []).findIndex((c) => c.uid === p.uid);
      return i < 0 ? 99 : i;
    };
    const keys = itemKeys().sort((a, b) => rank(a) - rank(b));
    return {title: `为 ${p.name} 装备`, entries: keys.map((key) => {
      const r = rank(key);
      return {label: `◆ ${itemName(key)}`, hint: r === -1 ? "最佳" : r < 99 ? `适配 #${r + 1}` : "", note: short(itemEffect(key), 26),
        tone: r === -1 ? "primary" : "", disabled: why, run: equipNow(key, loc)};
    })};
  }
  function learnMenu(p, loc, list, why) {
    const gold = Number(S().you?.gold) || 0;
    return {title: `为 ${p.name} 学习`, entries: list.map((t) => {
      const count = Number(t.count) || 0;
      const cost = Number(t.cost) || 2;
      const best = IX()?.techniques?.[t.id]?.best?.uid === p.uid;
      return {label: t.name, hint: `${count ? `仓库 ×${count}` : `${cost} 金`}${best ? " · 推荐" : ""}`, note: short(t.description, 26),
        tone: best ? "primary" : "", disabled: why || (!count && gold < cost ? `金币不足（需要 ${cost} 金）` : ""),
        run: () => window.PlayInteractions?.learn ? window.PlayInteractions.learn(t.id, p.uid) : ctx.api("learn", {loc, technique: t.id})};
    })};
  }

  function unitMenu(loc, p) {
    const s = S();
    const why = lockedReason();
    const onBoard = loc[0] === "g";
    const gold = Number(s.you?.gold) || 0;
    const entries = [{label: "详情", hint: "技能 · 特性 · 装备", run: () => { ctx.actions?.selectUnit(loc); ctx.actions?.openDetail(); }}];
    if (onBoard) {
      entries.push({label: "下场到备战席", hint: "双击", disabled: why || (benchFull() ? "备战席已满" : ""), run: () => ctx.actions?.quickPlace(loc)});
    } else {
      const cell = ctx.actions?.bestBoardCell?.(p);
      entries.push({label: "上场", hint: cell ? `→ ${ROWS[Number(cell[1])] || "棋盘"} · 双击` : "双击", tone: "primary",
        disabled: why || (popFull() ? popReason() : !cell ? "棋盘没有空位" : ""), run: () => ctx.actions?.quickPlace(loc)});
    }
    if ((p.mod_options || []).length)
      entries.push({label: "选择技能强化", hint: `${p.mod_options.length} 选 1`, tone: "primary", disabled: why,
        run: () => window.PlayInteractions?.openMods?.(p.uid) || (ctx.actions?.selectUnit(loc), ctx.actions?.openDetail())});
    const keys = itemKeys();
    if (keys.length) {
      const slot = slotsOf(p);
      const full = slot.used >= slot.total;
      entries.push({label: "装备…", hint: `${keys.length} 件`, disabled: why || (full ? `装备位已满（${slot.used}/${slot.total}）` : ""),
        submenu: () => equipMenu(p, loc, why)});
    }
    const unequipCost = s.depth ? Number(IX()?.equip?.unequip_cost ?? s.depth.items?.unequip_cost ?? 1) : 0;
    const unequipWhy = why || (gold < unequipCost ? `金币不足（需要 ${unequipCost} 金）` : "");
    if (p.item) entries.push({label: "卸下装备", hint: `◆${short(p.item_name || p.item, 8)}${unequipCost ? ` · ${unequipCost} 金` : ""}`,
      disabled: unequipWhy, run: call("unequip", {loc})});
    if (p.extra_item_name || p.extra_item) entries.push({label: "卸下第二装备", hint: `◆${short(p.extra_item_name || p.extra_item, 8)}${unequipCost ? ` · ${unequipCost} 金` : ""}`,
      disabled: unequipWhy, run: call("unequip", {loc, slot: "1"})});
    for (const o of awakenOptions((o) => o.uid === p.uid)) entries.push(awakenEntry(o, why));
    const data = IX()?.techniques || null;
    const learnable = techniques().filter((t) => data ? data[t.id]?.compatible?.includes(p.uid) && !data[t.id]?.known_by?.includes(p.uid)
      : (t.eligible || []).includes(p.uid));
    if (learnable.length) entries.push({label: "学习技能机…", hint: p.technique?.name ? `替换 ${short(p.technique.name, 6)}` : `${learnable.length} 种`,
      disabled: why, submenu: () => learnMenu(p, loc, learnable, why)});
    if (s.depth) entries.push({label: p.is_core ? "取消核心" : "设为核心", hint: "♛",
      disabled: why || (!onBoard && !p.is_core ? "核心需要在场上" : ""), run: call("core", {loc})});
    entries.push({label: "出售", hint: `+${Number(p.sell) || 0} 金`, tone: "danger", disabled: why, run: call("sell", {loc})});
    if (ctx.selected?.() === loc) entries.push({label: "取消选择", hint: "Esc", run: () => ctx.actions?.clear()});
    return {title: `${p.is_core ? "♛ " : ""}${p.name} ${stars(p)}`, sub: onBoard ? `${ROWS[Number(loc[1])] || ""}` : "备战席", entries};
  }

  function cellMenu(loc) {
    const s = S();
    const why = lockedReason();
    const board = loc[0] === "g";
    const sel = ctx.selected?.();
    const moving = sel && sel !== loc ? pieceAt(sel) : null;
    const entries = [];
    if (moving) {
      const needsPop = board && sel[0] === "b";
      entries.push({label: `把 ${moving.name} ${board ? "放到这里" : "撤到这里"}`, tone: "primary",
        disabled: why || (needsPop && popFull() ? popReason() : ""), run: call("move", {from: sel, to: loc})});
    }
    if (board) {
      const bench = (s.bench || []).map((p, i) => p ? {p, i} : null).filter(Boolean);
      if (bench.length) entries.push({label: "放置备战席精灵…", hint: `${bench.length} 只`, disabled: why || (popFull() ? popReason() : ""),
        submenu: () => ({title: `放到${ROWS[Number(loc[1])] || "这里"}`, entries: bench.map(({p, i}) => ({label: `${p.name} ${stars(p)}`,
          hint: p.ranged ? "远程" : "近战", disabled: why, run: call("move", {from: `b${i}`, to: loc})}))})});
      entries.push({label: "一键上场", hint: "E", disabled: why || (!bench.length ? "备战席是空的" : popFull() ? popReason() : ""),
        run: () => ctx.actions?.autoDeploy()});
    }
    if (!entries.length) return null;
    return {title: board ? `空格 · ${ROWS[Number(loc[1])] || ""}` : "备战席空位", entries};
  }

  function shopMenu(i, p) {
    const s = S();
    const why = lockedReason();
    const gold = Number(s.you?.gold) || 0;
    const price = Number(p.price) || 0;
    const merges = Boolean(p.star_progress?.merges_now || p.merge_note);
    const buyWhy = why || (gold < price ? `金币不足，还差 ${price - gold} 金` : p.blocked ? (typeof p.blocked === "string" ? p.blocked : "暂时不能招募")
      : benchFull() && !merges ? "备战席已满" : "");
    const entries = [
      {label: "购买", hint: `${price} 金${merges ? " · 升星" : ""} · 双击`, tone: "primary", disabled: buyWhy, run: call("buy", {i})},
      {label: "购买并上场", hint: `${price} 金`, disabled: buyWhy || (popFull() ? popReason() : ""), run: () => ctx.actions?.buyAndPlace(i)},
      {label: "详情", hint: "技能 · 特性 · 卡池", run: () => { ctx.actions?.selectShop(i); ctx.actions?.openDetail(); }},
      {label: s.you?.shop_locked ? "解除商店锁定" : "锁定商店", hint: s.you?.shop_locked ? "已锁定" : "下轮保留", disabled: why, run: call("lock", {})},
      {label: "刷新商店", hint: `${Number(s.you?.refresh_cost) || 0} 金 · R`, disabled: why || (gold < Number(s.you?.refresh_cost) ? "金币不足" : ""), run: call("refresh", {})},
    ];
    if (ctx.shopSelected?.() === i) entries.push({label: "取消选择", hint: "Esc", run: () => ctx.actions?.clear()});
    return {title: `${p.name} ${stars(p)}`, sub: `${Number(p.tier || price)} 费 · 商店`, entries};
  }

  function enemyMenu(loc, p, el) {
    const seat = (S().scouting || []).find((row) => row.current_opponent)?.seat ?? -1;
    return {title: `${p.name} ${stars(p)}`, sub: "敌方", entries: [
      {label: "侦察详情", hint: "技能 · 装备 · 属性", tone: "primary", run: () => ctx.actions?.openEnemy(loc, el)},
      {label: "查看对手整队", hint: "侦察", run: () => ctx.actions?.openScout(seat)},
    ]};
  }

  function itemMenu(key) {
    const s = S();
    const why = lockedReason();
    const gold = Number(s.you?.gold) || 0;
    const slots = IX()?.equip?.slots || {};
    const free = (uid) => {
      const slot = slots[uid];
      if (slot) return slot.used < slot.total;
      const loc = locOf(uid);
      return Boolean(loc && !pieceAt(loc)?.item);
    };
    const carriers = (IX()?.equip?.items?.[key]?.carriers || []).filter((c) => free(c.uid) && locOf(c.uid));
    const entries = [];
    const best = carriers[0];
    if (IX()?.equip) entries.push(best
      ? {label: `装给 ${best.name}`, hint: "推荐", tone: "primary", note: short(best.reason, 26), disabled: why, run: () => equipNow(key, locOf(best.uid))()}
      : {label: "装给推荐携带者", disabled: why || "没有空装备位的合适伙伴"});
    entries.push({label: "选择携带者…", hint: "点亮可装的伙伴", disabled: why,
      run: () => window.PlayInteractions?.target ? window.PlayInteractions.target("equip", key) : ctx.actions?.selectEquip(key)});
    for (const o of awakenOptions((o) => o.key === key)) entries.push(awakenEntry(o, why));
    const depth = s.depth?.items;
    if (depth) {
      const cost = Number(depth.dismantle_cost) || 0;
      entries.push({label: "拆解", hint: cost ? `${cost} 金 · 返还组件` : "返还组件", disabled: why || (gold < cost ? `金币不足（需要 ${cost} 金）` : ""), run: call("dismantle", {item: key})});
      entries.push({label: "出售", hint: `+${Number(depth.sell_value) || 0} 金`, tone: "danger", disabled: why, run: call("sell_item", {item: key})});
    }
    return {title: `◆ ${itemName(key)}`, sub: "装备", entries};
  }

  function tmMenu(key) {
    const why = lockedReason();
    const t = techniques().find((x) => x.id === key);
    const row = IX()?.techniques?.[key];
    if (!t || !row) return null;
    const entries = [];
    if (row.best) entries.push({label: `学给 ${row.best.name}`, hint: "推荐", tone: "primary", note: short(row.best.reasons?.[0], 26), disabled: why,
      run: () => window.PlayInteractions?.learn?.(key, row.best.uid)});
    entries.push({label: "选择学习者…", hint: `可学 ${(row.compatible || []).length} 只`, disabled: why || (!(row.compatible || []).length ? "当前没有能学的伙伴" : ""),
      run: () => window.PlayInteractions?.target?.("tm", key)});
    return {title: t.name, sub: "技能机", entries};
  }

  function build(target) {
    switch (target.kind) {
      case "unit": return unitMenu(target.key, pieceAt(target.key));
      case "cell": return cellMenu(target.key);
      case "shop": return shopMenu(target.key, S().shop[target.key]);
      case "enemy": return enemyMenu(target.key, enemyAt(target.key), target.el);
      case "item": return itemMenu(target.key);
      case "tm": return tmMenu(target.key);
      default: return null;
    }
  }

  // ------------------------------------------------------------ view
  function ensure() {
    if (menu) return;
    backdrop = document.createElement("div");
    backdrop.className = "ctx-backdrop";
    backdrop.hidden = true;
    menu = document.createElement("div");
    menu.id = "ctx-menu";
    menu.className = "ctx-menu";
    menu.setAttribute("role", "menu");
    menu.hidden = true;
    document.body.append(backdrop);
    document.body.append(menu);
    menu.addEventListener("click", onMenuClick);
    menu.addEventListener("keydown", onMenuKey);
    backdrop.addEventListener("click", () => close());
  }
  function items() {
    return [...menu.querySelectorAll("[data-ctx]")];
  }
  function draw() {
    const page = view.stack.length ? view.stack[view.stack.length - 1] : view;
    const sheet = isPhone();
    const preview = sheet && !view.stack.length && window.PlayPreview?.describe ? window.PlayPreview.describe(view.target) : "";
    const rows = page.entries.map((entry, i) => `<button type="button" role="menuitem" class="ctx-item${entry.tone ? " ctx-" + entry.tone : ""}${entry.disabled ? " is-disabled" : ""}${entry.submenu ? " has-sub" : ""}" data-ctx="${i}" tabindex="-1"${entry.disabled ? ` aria-disabled="true" title="${esc(entry.disabled)}"` : ""}${entry.submenu ? ' aria-haspopup="menu"' : ""}><span class="ctx-label">${esc(entry.label)}</span>${entry.hint ? `<span class="ctx-hint">${esc(entry.hint)}</span>` : ""}${entry.submenu ? '<span class="ctx-more" aria-hidden="true">›</span>' : ""}${entry.disabled ? `<small class="ctx-reason">${esc(entry.disabled)}</small>` : entry.note ? `<small class="ctx-note">${esc(entry.note)}</small>` : ""}</button>`).join("");
    menu.innerHTML = `${preview ? `<div class="ctx-preview">${preview}</div>` : ""}<header class="ctx-head">${view.stack.length ? '<button type="button" class="ctx-back" data-ctx-back aria-label="返回上一级">‹</button>' : ""}<b>${esc(page.title)}</b>${page.sub && !view.stack.length ? `<small>${esc(page.sub)}</small>` : ""}</header><div class="ctx-items">${rows || '<p class="ctx-empty">这里暂时没有可用操作</p>'}</div>${sheet ? '<button type="button" class="ctx-cancel" data-ctx-close>取消</button>' : ""}`;
    menu.setAttribute("aria-label", page.title);
    menu.className = `ctx-menu${sheet ? " as-sheet" : ""}`;
    backdrop.hidden = !sheet;
  }
  function position(x, y) {
    if (isPhone()) {
      menu.style.left = "";
      menu.style.top = "";
      return;
    }
    const w = menu.offsetWidth || 220, h = menu.offsetHeight || 240;
    const vw = window.innerWidth || 1280, vh = window.innerHeight || 800;
    menu.style.left = `${Math.round(Math.max(4, x + w > vw - 4 ? x - w : x))}px`;
    menu.style.top = `${Math.round(Math.max(4, y + h > vh - 4 ? Math.max(4, vh - h - 4) : y))}px`;
  }
  function focusItem(index) {
    const list = items();
    if (!list.length) return menu.querySelector("[data-ctx-back]")?.focus?.();
    const i = (index + list.length) % list.length;
    for (const [n, el] of list.entries()) el.tabIndex = n === i ? 0 : -1;
    list[i].focus?.();
  }
  function firstUsable() {
    const list = items();
    const i = list.findIndex((el) => el.getAttribute("aria-disabled") !== "true");
    return i < 0 ? 0 : i;
  }
  /** Open the menu for a target at viewport point (x, y). Returns false when there is nothing to offer. */
  function open(target, x, y, {keyboard = false} = {}) {
    if (!ctx || !target) return false;
    const page = build(target);
    if (!page) return false;
    ensure();
    window.PlayPreview?.hide?.();
    window.PlaySelect?.close?.(false);
    view = {target, ...page, stack: [], at: Date.now(), returnFocus: keyboard ? document.activeElement : target.el, point: {x, y}};
    draw();
    menu.hidden = false;
    document.body.classList.add("ctx-open");
    target.el?.classList?.add?.("ctx-target");
    position(x, y);
    focusItem(firstUsable());
    return true;
  }
  function close({restore = true} = {}) {
    if (!view) return;
    const back = view.returnFocus;
    view.target?.el?.classList?.remove?.("ctx-target");
    view = null;
    if (menu) menu.hidden = true;
    if (backdrop) backdrop.hidden = true;
    document.body.classList.remove("ctx-open");
    if (restore && back?.isConnected !== false) back?.focus?.({preventScroll: true});
  }
  function enter(entry) {
    view.stack.push(entry.submenu());
    draw();
    position(view.point.x, view.point.y);
    focusItem(firstUsable());
  }
  function back() {
    if (!view?.stack.length) return close();
    view.stack.pop();
    draw();
    position(view.point.x, view.point.y);
    focusItem(firstUsable());
  }
  async function activate(index) {
    if (!view) return;
    const page = view.stack.length ? view.stack[view.stack.length - 1] : view;
    const entry = page.entries[index];
    if (!entry || entry.disabled) {
      // Keep the menu open: the reason is printed under the entry.
      items()[index]?.classList?.add?.("ctx-shake");
      return;
    }
    if (entry.submenu) return enter(entry);
    close({restore: false});
    await entry.run?.();
  }
  function onMenuClick(event) {
    event.stopPropagation?.();
    const target = event.target;
    if (target?.closest?.("[data-ctx-back]")) return back();
    if (target?.closest?.("[data-ctx-close]")) return close();
    const item = target?.closest?.("[data-ctx]");
    if (item) activate(Number(item.getAttribute("data-ctx")));
  }
  function onMenuKey(event) {
    const list = items();
    const index = list.indexOf(document.activeElement);
    const key = event.key;
    if (key === "ArrowDown") focusItem(index + 1);
    else if (key === "ArrowUp") focusItem(index < 0 ? list.length - 1 : index - 1);
    else if (key === "Home") focusItem(0);
    else if (key === "End") focusItem(list.length - 1);
    else if (key === "Enter" || key === " ") { if (index >= 0) activate(index); else return; }
    else if (key === "ArrowRight") {
      const page = view.stack.length ? view.stack[view.stack.length - 1] : view;
      if (index >= 0 && page.entries[index]?.submenu && !page.entries[index].disabled) enter(page.entries[index]);
    } else if (key === "ArrowLeft" || key === "Backspace") back();
    else if (key === "Escape") close();
    else if (key === "Tab") { close(); return; }
    else return;
    event.preventDefault?.();
    event.stopPropagation?.();
  }

  // ------------------------------------------------------------ triggers
  document.addEventListener("contextmenu", (event) => {
    if (event.target?.closest?.("#ctx-menu")) { event.preventDefault?.(); return; }
    const target = targetOf(event.target);
    if (!target) return;
    event.preventDefault?.();
    // A touch long press already opened it (Android also fires contextmenu then).
    if (view && Date.now() - longPressAt < 1000) return;
    const keyboard = !event.clientX && !event.clientY;
    const box = target.el.getBoundingClientRect?.();
    open(target, keyboard && box ? box.left + box.width / 2 : event.clientX, keyboard && box ? box.bottom : event.clientY, {keyboard});
  });
  document.addEventListener("keydown", (event) => {
    if (view) {
      if (event.key === "Escape") { close(); event.preventDefault?.(); event.stopImmediatePropagation?.(); }
      return;
    }
    if (!(event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey))) return;
    const target = targetOf(document.activeElement);
    if (!target) return;
    event.preventDefault?.();
    const box = target.el.getBoundingClientRect?.() || {left: 0, width: 0, bottom: 0};
    open(target, box.left + box.width / 2, box.bottom, {keyboard: true});
  }, true);
  // Outside press / scroll / resize closes the menu.
  document.addEventListener("pointerdown", (event) => {
    if (view && !event.target?.closest?.("#ctx-menu") && !event.target?.closest?.(".ctx-backdrop")) close({restore: false});
  }, true);
  if (typeof window.addEventListener === "function") {
    window.addEventListener("scroll", (event) => {
      if (view && !(event.target?.closest?.("#ctx-menu"))) close({restore: false});
    }, true);
    window.addEventListener("resize", () => close({restore: false}));
    window.addEventListener("blur", () => close({restore: false}));
  }

  // Touch long press: same menu, as a bottom sheet on phones. Movement cancels (that is a drag or scroll).
  let press = null;
  document.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" || event.button > 0 || view) return;
    const target = targetOf(event.target);
    if (!target) return;
    press = {target, x: event.clientX, y: event.clientY, timer: setTimeout(() => {
      const current = press;
      press = null;
      if (!current) return;
      longPressAt = Date.now();
      if (open(current.target, current.x, current.y)) {
        // The finger is still down: the click its release produces may land on the sheet that just
        // slid under it. Eat exactly that click (see pointerup below).
        eatClick = true;
        if (typeof navigator !== "undefined") navigator.vibrate?.(8);
      }
    }, LONG_PRESS_MS)};
  });
  document.addEventListener("pointerup", () => {
    if (eatClick) suppressClickUntil = Date.now() + 400;
    eatClick = false;
  }, true);
  const cancelPress = (event) => {
    if (!press) return;
    if (event?.type === "pointermove" && Math.hypot(event.clientX - press.x, event.clientY - press.y) < 10) return;
    clearTimeout(press.timer);
    press = null;
  };
  for (const type of ["pointerup", "pointercancel", "pointermove"]) document.addEventListener(type, cancelPress);
  // The click that ends a long press must not also select / buy.
  document.addEventListener("click", (event) => {
    if (Date.now() < suppressClickUntil) {
      suppressClickUntil = 0;
      event.preventDefault?.();
      event.stopImmediatePropagation?.();
    }
  }, true);
  document.addEventListener("dragstart", (event) => {
    if (view || Date.now() - longPressAt < 1000) event.preventDefault?.();
  }, true);

  function render(context) {
    ctx = context;
    if (!view) return;
    // Rebuild against the new state; a target that vanished closes the menu.
    const still = view.target.kind === "unit" ? pieceAt(view.target.key) : view.target.kind === "shop" ? S()?.shop?.[view.target.key] : true;
    if (!still) close({restore: false});
  }

  window.PlayContext = {render, open, close, targetOf, build, isOpen: () => Boolean(view), view: () => view, LONG_PRESS_MS};
})();
