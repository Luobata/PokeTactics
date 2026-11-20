/* Crafting tree (docs/71): components → finished items → awakened, plus treasures.
 * Data: state.interactions.item_tree. One overlay, nodes are buttons over an SVG edge layer.
 * Click / tap a node to focus it: its whole chain lights up and a detail card shows actions. */
(() => {
  "use strict";
  let ctx = null;
  let open = false;
  let focus = null;           // {kind: "comp" | "item" | "awk" | "treasure", key}
  let filter = "all";         // all | craftable | held | <tag name>
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const tree = () => ctx?.state?.interactions?.item_tree || null;
  const ARCH = {"输出": "dps", "坦克": "tank", "控制": "ctrl", "联动": "combo", "辅助": "sup", "经济": "eco"};
  const TAGS = ["异常", "冲击", "奥术", "守护", "连击"];
  const ROW = 40, TOP = 44;
  const icon = (key, size) => window.ItemIcons ? window.ItemIcons.html(key, {size}) : "";

  function model(t) {
    const st = t.static;
    const comps = st.components.map((c, i) => ({...c, n: Number(t.components?.[c.key] || 0), i}));
    const compIndex = Object.fromEntries(comps.map((c) => [c.key, c.i]));
    const craftable = new Set(t.craftable || []);
    const held = t.held || {};
    const ready = new Set(t.awaken_ready || []);
    const items = st.items.map((it, i) => ({...it, i, craftable: craftable.has(it.key), held: Number(held[it.key] || 0),
      awakenHeld: it.awaken ? Number(held[it.awaken.key] || 0) : 0, awakenReady: ready.has(it.key)}));
    const awks = items.filter((it) => it.awaken);
    return {comps, compIndex, items, awks, treasures: st.treasures.map((x) => ({...x, held: Number(held[x.key] || 0)})), st, t};
  }

  function visible(m, it) {
    if (filter === "all") return true;
    if (filter === "craftable") return it.craftable || it.awakenReady;
    if (filter === "held") return it.held > 0 || it.awakenHeld > 0;
    return (it.tags || []).includes(filter);
  }

  // Which nodes belong to the focused chain.
  function chain(m) {
    const on = new Set();
    if (!focus) return on;
    const add = (k) => on.add(k);
    if (focus.kind === "comp") {
      add("c:" + focus.key);
      for (const it of m.items) {
        if (it.recipe.includes(focus.key)) { add("i:" + it.key); if (it.awaken) add("a:" + it.key); }
        if (it.awaken?.components?.includes(focus.key)) { add("i:" + it.key); add("a:" + it.key); }
      }
    } else if (focus.kind === "item" || focus.kind === "awk") {
      const it = m.items.find((x) => x.key === focus.key);
      if (it) {
        add("i:" + it.key); it.recipe.forEach((c) => add("c:" + c));
        if (it.awaken) { add("a:" + it.key); it.awaken.components.forEach((c) => add("c:" + c)); }
        for (const d of it.duos || []) add("i:" + d.partner);
      }
    } else if (focus.kind === "treasure") add("t:" + focus.key);
    return on;
  }

  function layout(m, width) {
    const narrow = width < 560;
    const inner = width - 64 - 2 * 12 - 4;   // narrow: component column + two gaps + scrollbar slack
    const colW = narrow ? [64, inner * 0.54, inner * 0.46] : [96, Math.min(240, width * 0.36), Math.min(230, width * 0.34)];
    const gap = narrow ? 12 : Math.max(18, (width - colW[0] - colW[1] - colW[2]) / 2);
    const x = [0, colW[0] + gap, colW[0] + gap + colW[1] + gap];
    const rows = m.items.filter((it) => visible(m, it));
    const height = Math.max(m.comps.length, rows.length) * ROW + TOP + 12;
    const compStep = (height - TOP - 12) / m.comps.length;
    const pos = {};
    m.comps.forEach((c, i) => { pos["c:" + c.key] = {x: x[0], y: TOP + i * compStep + (compStep - 64) / 2, w: colW[0], h: 64}; });
    rows.forEach((it, i) => {
      pos["i:" + it.key] = {x: x[1], y: TOP + i * ROW, w: colW[1]};
      if (it.awaken) pos["a:" + it.key] = {x: x[2], y: TOP + i * ROW, w: colW[2]};
    });
    return {pos, rows, height, x, colW, narrow};
  }

  function edge(a, b, cls) {
    const x1 = a.x + a.w, y1 = a.y + (a.h || ROW - 6) / 2, x2 = b.x, y2 = b.y + (b.h || ROW - 6) / 2;
    const mid = (x1 + x2) / 2;
    return `<path class="${cls}" d="M${x1.toFixed(1)},${y1.toFixed(1)} C${mid.toFixed(1)},${y1.toFixed(1)} ${mid.toFixed(1)},${y2.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}"/>`;
  }

  function nodeHtml(id, p, inner, cls, attrs) {
    return `<button type="button" class="tr-node ${cls}" style="left:${p.x.toFixed(1)}px;top:${p.y.toFixed(1)}px;width:${p.w.toFixed(1)}px${p.h ? `;height:${p.h}px` : ""}" data-tree-node="${id}" ${attrs || ""}>${inner}</button>`;
  }

  function detail(m) {
    if (!focus) return `<p class="tr-hint">点组件看它能合成什么；点成品看完整的合成链、觉醒和双持搭档。</p>`;
    const prep = ctx?.canPrep?.();
    const compName = (k) => m.comps.find((c) => c.key === k)?.name || k;
    if (focus.kind === "comp") {
      const c = m.comps.find((x) => x.key === focus.key);
      const makes = m.items.filter((it) => it.recipe.includes(focus.key));
      return `<h4>${icon(c?.key, 40)}${esc(c?.name)} <small>库存 ${Number(c?.n || 0)}</small></h4>${c?.stats ? `<p class="tr-stats">组件属性：${esc(c.stats)}</p>` : ""}
        <p>可以合成 ${makes.length} 件成品：</p><div class="tr-makes">${makes.map((it) => `<button type="button" class="tr-mini" data-tree-focus="item:${esc(it.key)}">${icon(it.key, 30)}<span>${esc(it.name)}</span></button>`).join("")}</div>
        ${m.items.some((it) => it.awaken?.components?.includes(focus.key)) ? `<p>也是这些装备的觉醒材料：${m.items.filter((it) => it.awaken?.components?.includes(focus.key)).map((it) => esc(it.name)).join("、")}</p>` : ""}`;
    }
    if (focus.kind === "treasure") {
      const x = m.treasures.find((r) => r.key === focus.key);
      return `<h4>${icon(x?.key, 40)}${esc(x?.name)} ${x?.held ? `<span class="tr-chip held">已拥有 ×${x.held}</span>` : ""}</h4><p>${esc(x?.effect)}</p><p class="tr-muted">宝物不能合成：${esc(m.st.treasure_source)}。</p>`;
    }
    const it = m.items.find((x) => x.key === focus.key);
    if (!it) return "";
    const [a, b] = it.recipe;
    const aw = it.awaken;
    return `<h4>${icon(it.key, 40)}${esc(it.name)} ${it.archetype ? `<span class="tr-arch arch-${ARCH[it.archetype] || "x"}">${esc(it.archetype)}</span>` : ""}${(it.tags || []).map((g) => `<span class="tr-tag">${esc(g)}</span>`).join("")}${it.held ? `<span class="tr-chip held">已拥有 ×${it.held}</span>` : ""}</h4>
      <div class="tr-formula">${icon(a, 34)}<b>+</b>${icon(b, 34)}<b>→</b>${icon(it.key, 34)}${aw ? `<b>+</b>${icon(aw.components[0], 26)}<b>→</b>${icon(aw.key, 34)}` : ""}</div>
      <p class="tr-recipe">${esc(compName(a))} + ${esc(compName(b))} → ${esc(it.name)}${aw ? ` → ${esc(aw.name)}` : ""}</p>
      ${it.stats?.length ? `<p class="tr-stats">组件属性：${it.stats.map(esc).join("、")}</p>` : ""}
      <p>${esc(it.effect)}</p>
      ${aw ? `<p class="tr-awaken"><b>觉醒</b>（第 ${Number(m.st.awaken_round)} 轮起，+ ${aw.components.map((c) => esc(compName(c))).join(" 或 ")}）：${esc(aw.clause)}</p>` : ""}
      ${it.duos?.length ? `<p class="tr-duo"><b>双持</b>：${it.duos.map((d) => `${icon(it.key, 22)}+<button type="button" class="tr-link" data-tree-focus="item:${esc(d.partner)}">${icon(d.partner, 22)}${esc(m.items.find((x) => x.key === d.partner)?.name || d.partner)}</button> → ${esc(d.name)}`).join("；")}</p>` : ""}
      <div class="tr-actions">
        ${it.craftable ? `<button type="button" class="primary-button" data-tree-craft="${esc(it.key)}" ${prep ? "" : "disabled"}>合成</button>` : `<span class="tr-muted">${it.held ? "" : "组件不足"}</span>`}
        ${it.awakenReady ? `<button type="button" class="primary-button tr-gold" data-tree-awaken="${esc(it.key)}" ${prep ? "" : "disabled"}>觉醒</button>` : ""}
      </div>`;
  }

  function draw() {
    const box = $("tree-overlay");
    const t = tree();
    if (!open || !t) { if (box) box.hidden = true; return; }
    const m = model(t);
    box.hidden = false;   // measure the real width (a hidden overlay reports 0)
    const canvas = box.querySelector(".tr-canvas");
    const scroller = box.querySelector(".tr-scroll");
    const width = Math.max(300, (scroller?.clientWidth || 748) - 28);
    const L = layout(m, width);
    const on = chain(m);
    const hot = (id) => (on.size ? (on.has(id) ? " hot" : " dim") : "");
    let edges = "";
    for (const it of L.rows) {
      const ip = L.pos["i:" + it.key];
      const doubled = it.recipe[0] === it.recipe[1];
      for (const c of doubled ? [it.recipe[0]] : it.recipe) {
        const id = on.has("c:" + c) && on.has("i:" + it.key) ? " hot" : on.size ? " dim" : "";
        edges += edge(L.pos["c:" + c], ip, "tr-e" + (doubled ? " double" : "") + (it.craftable ? " ready" : "") + id);
      }
      if (it.awaken) {
        const ap = L.pos["a:" + it.key];
        edges += edge(ip, ap, "tr-e awk" + (on.has("a:" + it.key) ? " hot" : on.size ? " dim" : ""));
      }
    }
    if (focus && (focus.kind === "item" || focus.kind === "awk")) {
      const it = m.items.find((x) => x.key === focus.key);
      for (const c of it?.awaken?.components || []) {
        const ap = L.pos["a:" + it.key];
        if (ap) edges += `<path class="tr-e mat hot" d="M${(L.pos["c:" + c].x + L.pos["c:" + c].w).toFixed(1)},${(L.pos["c:" + c].y + 32).toFixed(1)} L${ap.x.toFixed(1)},${(ap.y + 17).toFixed(1)}"/>`;
      }
    }
    const nodes = [
      ...m.comps.map((c) => nodeHtml("c:" + c.key, L.pos["c:" + c.key], `${icon(c.key, L.narrow ? 30 : 34)}<b>${esc(L.narrow ? c.name.slice(0, 2) : c.name)}</b><i>${c.n}</i>`, "comp" + (c.n ? " have" : "") + hot("c:" + c.key), `aria-label="${esc(c.name)}，库存 ${c.n}"`)),
      ...L.rows.map((it) => nodeHtml("i:" + it.key, L.pos["i:" + it.key],
        `${icon(it.key, 28)}<span class="tr-dot arch-${ARCH[it.archetype] || "x"}"></span><b>${esc(it.name)}</b>${it.held ? `<i class="held">×${it.held}</i>` : it.craftable ? `<i class="ready">${L.narrow ? "✓" : "可合成"}</i>` : ""}`,
        "item" + (it.craftable ? " ready" : "") + (it.held ? " owned" : "") + (it.mechanic ? " mech" : "") + hot("i:" + it.key), `aria-label="${esc(it.name)}"`)),
      ...L.rows.filter((it) => it.awaken).map((it) => nodeHtml("a:" + it.key, L.pos["a:" + it.key],
        `${icon(it.awaken.key, 28)}<b>${esc(L.narrow ? it.awaken.name.replace("·觉醒", "") : it.awaken.name)}</b>${it.awakenHeld ? `<i class="held">×${it.awakenHeld}</i>` : it.awakenReady ? `<i class="ready">${L.narrow ? "✓" : "可觉醒"}</i>` : ""}`,
        "awk" + (it.awakenReady ? " ready" : "") + (it.awakenHeld ? " owned" : "") + hot("a:" + it.key), `aria-label="${esc(it.awaken.name)}"`)),
    ].join("");
    const chips = [["all", "全部"], ["craftable", "能做的"], ["held", "已拥有"], ...TAGS.map((g) => [g, g])]
      .map(([k, label]) => `<button type="button" data-tree-filter="${esc(k)}" aria-pressed="${filter === k}">${esc(label)}</button>`).join("");
    box.querySelector(".tr-filters").innerHTML = chips;
    canvas.style.height = `${L.height}px`;
    canvas.innerHTML = `<div class="tr-heads"><span style="left:${L.x[0]}px">组件</span><span style="left:${L.x[1]}px">成品</span><span style="left:${L.x[2]}px">觉醒 · 第 ${Number(m.st.awaken_round || 12)} 轮起</span></div>
      <svg class="tr-edges" width="${width}" height="${L.height}" aria-hidden="true">${edges}</svg>${nodes}`;
    box.querySelector(".tr-treasures").innerHTML = m.treasures.length ? `<h4>★ 宝物 <small>不可合成 · ${esc(m.st.treasure_source)}</small></h4><div>${m.treasures.map((x) =>
      `<button type="button" class="tr-treasure${x.held ? " owned" : ""}${on.has("t:" + x.key) ? " hot" : ""}" data-tree-node="t:${esc(x.key)}">${icon(x.key, 34)}<b>${esc(x.name)}</b>${x.held ? `<i class="held">×${x.held}</i>` : ""}<small>${esc(x.archetype)}${(x.tags || []).length ? " · " + x.tags.map(esc).join("/") : ""}</small></button>`).join("")}</div>` : "";
    box.querySelector(".tr-detail").innerHTML = detail(m);
    box.hidden = false;
  }

  function ensure() {
    let box = $("tree-overlay");
    if (box) return box;
    box = document.createElement("section");
    box.id = "tree-overlay";
    box.className = "tree-overlay";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "装备合成树");
    box.hidden = true;
    box.innerHTML = `<div class="tr-panel"><header><h3>装备合成树</h3><div class="tr-filters" role="group" aria-label="筛选"></div><button type="button" class="tr-close" data-tree-close aria-label="关闭">×</button></header>
      <div class="tr-body"><div class="tr-scroll"><div class="tr-canvas"></div><div class="tr-treasures"></div></div><aside class="tr-detail" aria-live="polite"></aside></div></div>`;
    document.body.appendChild(box);
    return box;
  }

  function show(target) {
    if (!tree()) return;
    ensure();
    open = true;
    if (target) {
      const [kind, key] = target.split(":");
      focus = {kind, key};
    }
    draw();
    const node = focus && $("tree-overlay").querySelector(`[data-tree-node="${focus.kind === "item" ? "i" : focus.kind === "awk" ? "a" : focus.kind === "comp" ? "c" : "t"}:${CSS.escape(focus.key)}"]`);
    node?.scrollIntoView?.({block: "center"});
  }
  function hide() { open = false; draw(); }

  document.addEventListener("click", async (event) => {
    const t = event.target;
    const opener = t?.closest?.("[data-tree-open]");
    if (opener) { event.preventDefault(); show(opener.getAttribute("data-tree-open") || null); return; }
    if (!open) return;
    if (t?.closest?.("[data-tree-close]") || t?.id === "tree-overlay") { hide(); return; }
    const node = t?.closest?.("[data-tree-node]");
    if (node) {
      const [p, key] = node.getAttribute("data-tree-node").split(":");
      const kind = {c: "comp", i: "item", a: "awk", t: "treasure"}[p];
      focus = focus && focus.kind === kind && focus.key === key ? null : {kind, key};   // re-click clears
      draw();
      return;
    }
    const link = t?.closest?.("[data-tree-focus]");
    if (link) { const [kind, key] = link.getAttribute("data-tree-focus").split(":"); focus = {kind, key}; draw(); return; }
    const f = t?.closest?.("[data-tree-filter]");
    if (f) { filter = f.getAttribute("data-tree-filter"); draw(); return; }
    const craft = t?.closest?.("[data-tree-craft]");
    if (craft && !craft.disabled && ctx) { craft.disabled = true; await ctx.api("craft", {item: craft.getAttribute("data-tree-craft")}); return; }
    const awaken = t?.closest?.("[data-tree-awaken]");
    if (awaken && !awaken.disabled && ctx) {
      awaken.disabled = true;
      const key = awaken.getAttribute("data-tree-awaken");
      const rows = ctx.state?.interactions?.item_synergy?.awaken?.options || [];
      const row = rows.find((o) => o.key === key && o.ready && o.where === "inventory") || rows.find((o) => o.key === key && o.ready);
      await ctx.api("awaken", {item: key, uid: row?.uid || "", component: row?.have?.[0] || ""});
    }
  });
  document.addEventListener("keydown", (event) => { if (open && event.key === "Escape") { event.stopPropagation(); hide(); } }, true);
  window.addEventListener("resize", () => { if (open) draw(); });

  function render(context) {
    ctx = context;
    if (open) draw();
  }
  window.PlayTree = {render, open: show, close: hide, isOpen: () => open};
})();
