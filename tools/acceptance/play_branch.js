/* Branch families (伊布 / 无畏小子 …, docs/70): three un-evolved copies never merge on their
 * own, the player picks a route. This module makes that choice impossible to miss:
 *   - a route-choice sheet opens once when a family first reaches 3 copies;
 *   - a HUD chip stays while a choice is pending; the copies get a ⇪ badge;
 *   - PlayBranch.ready(uid) / open(fid) for the context menu.
 * Data comes from state (piece.family: id, step, routes); no extra server calls. */
(() => {
  "use strict";
  let ctx = null;
  let openFid = null;
  const prompted = new Set();           // "fid:count" groups already auto-prompted this session
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const ROLE = {attack: "攻击型", defense: "防守型", support: "辅助型"};

  function owned() {
    const s = ctx?.state;
    if (!s) return [];
    const out = [];
    (s.board || []).forEach((row, r) => (row || []).forEach((p, c) => { if (p) out.push({p, loc: `g${r},${c}`}); }));
    (s.bench || []).forEach((p, i) => { if (p) out.push({p, loc: `b${i}`}); });
    return out;
  }

  /** [{fid, name, count, units:[{p, loc}], routes}] for families with ≥3 un-chosen copies. */
  function groups() {
    const by = new Map();
    for (const row of owned()) {
      const f = row.p.family;
      if (!f || f.step !== 1 || !Array.isArray(f.routes) || f.routes.length < 2 || f.rare) continue;
      if (!by.has(f.id)) by.set(f.id, {fid: f.id, name: row.p.name, units: [], routes: f.routes});
      by.get(f.id).units.push(row);
    }
    return [...by.values()].filter((g) => g.units.length >= 3).map((g) => ({...g, count: g.units.length}));
  }

  function chip(list) {
    const host = $("hud-chips");
    if (!host) return;
    let el = $("hud-branch");
    if (!list.length) { if (el) el.hidden = true; return; }
    if (!el) {
      el = document.createElement("button");
      el.type = "button";
      el.id = "hud-branch";
      el.className = "hud-chip hud-branch";
      host.prepend(el);
    }
    const g = list[0];
    el.hidden = false;
    el.dataset.branchOpen = String(g.fid);
    el.textContent = `⇪ ${g.name} ×${g.count} · 选择进化${list.length > 1 ? ` (+${list.length - 1})` : ""}`;
    el.title = "凑齐三只，选择进化路线后才会合成";
  }

  function badges(list) {
    const ready = new Set(list.flatMap((g) => g.units.map((u) => u.p.uid)));
    document.querySelectorAll("[data-uid].branch-ready").forEach((el) => { if (!ready.has(el.dataset.uid)) el.classList.remove("branch-ready"); });
    for (const uid of ready) document.querySelectorAll(`[data-uid="${CSS.escape(uid)}"]`).forEach((el) => el.classList.add("branch-ready"));
  }

  function sheet() {
    let box = $("branch-sheet");
    const g = groups().find((x) => x.fid === openFid);
    if (openFid == null || !g) {
      if (box) box.hidden = true;
      if (openFid != null && !g) openFid = null;
      return;
    }
    if (!box) {
      box = document.createElement("section");
      box.id = "branch-sheet";
      box.className = "branch-sheet";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      document.body.append(box);
    }
    const prep = ctx?.canPrep?.();
    const art = (p) => p.sprite || p.image || "";
    box.innerHTML = `<div class="br-panel">
      <header><h3>选择 ${esc(g.name)} 的进化路线</h3><button type="button" class="br-close" data-branch-close aria-label="稍后再选">×</button></header>
      <p class="br-note">已集齐 ${g.count} 只${esc(g.name)}。选定路线后三只立即合成，之后只有同一路线可以继续培养。</p>
      <div class="br-routes">${g.routes.map((r) => `<article class="br-route">
        <h4>${r.names.map(esc).join(" → ")}</h4>
        <p class="br-role">${esc(ROLE[r.role] || r.role || "")}${r.skill ? ` · ${esc(r.skill)}` : ""}</p>
        ${r.description ? `<p>${esc(r.description)}</p>` : ""}
        ${r.trait?.name ? `<p class="br-trait">特性 · ${esc(r.trait.name)}${r.trait.description ? `：${esc(r.trait.description)}` : ""}</p>` : ""}
        <button type="button" class="primary-button" data-branch-pick="${esc(r.branch)}" ${prep ? "" : "disabled"}>进化为 ${esc(r.names[r.names.length - 1])}</button>
      </article>`).join("")}</div>
      <div class="br-actions"><button type="button" class="secondary-button" data-branch-close>稍后再选</button></div>
    </div>`;
    box.hidden = false;
  }

  function open(fid) { openFid = Number(fid); sheet(); }
  function close() { openFid = null; sheet(); }

  document.addEventListener("click", async (event) => {
    const t = event.target;
    const opener = t?.closest?.("[data-branch-open]");
    if (opener) { event.preventDefault(); open(opener.dataset.branchOpen); return; }
    if (openFid == null) return;
    if (t?.closest?.("[data-branch-close]") || t?.id === "branch-sheet") { close(); return; }
    const pick = t?.closest?.("[data-branch-pick]");
    if (pick && !pick.disabled && ctx) {
      const g = groups().find((x) => x.fid === openFid);
      if (!g) return close();
      pick.disabled = true;
      const result = await ctx.api("family_evolve", {loc: g.units[0].loc, branch: pick.dataset.branchPick});
      if (result?.ok !== false) close();
      else pick.disabled = false;
    }
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && openFid != null) { event.stopPropagation(); close(); } }, true);

  function render(context) {
    ctx = context;
    const list = ctx?.state?.phase === "prep" ? groups() : [];
    chip(list);
    badges(list);
    // Prompt once per family per copy count, only while the player can act.
    if (openFid == null && ctx?.canPrep?.()) {
      const fresh = list.find((g) => !prompted.has(`${g.fid}:${g.count}`));
      if (fresh) {
        list.forEach((g) => prompted.add(`${g.fid}:${g.count}`));
        open(fresh.fid);
        return;
      }
    }
    if (openFid != null) sheet();
  }
  window.PlayBranch = {render, open, close, groups, isOpen: () => openFid != null,
    readyFor: (uid) => groups().find((g) => g.units.some((u) => u.p.uid === uid)) || null};
})();
