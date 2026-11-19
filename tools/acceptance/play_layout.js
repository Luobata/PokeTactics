/* Board-centric prep layout (docs/61-play-ui-redesign.md).
 *
 * play.html keeps every panel in static DOM inside the drawer; this module only
 * decides which panel is visible, mirrors state into the HUD / dock badges, and
 * draws board cues (attack range, opening-target lines, contextual action bar).
 * All game mutations still go through play.js / play_depth.js handlers via the
 * same data-* attributes, so nothing here talks to the server.
 *
 * play.js calls PlayLayout.render(ctx) after every render, with
 * ctx = {state, api, canPrep, playable, pieceAt, selected(), shopSelected(),
 *        equipItem(), busy()}. Without this file the page still works (panels
 * simply stay in their static order). */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  // Keyed writes (docs/66): touch the DOM only when the markup/text changed.
  const setHTML = (el, html) => {
    if (!el || (el.__src === html && el.__first === el.firstChild)) return;
    el.innerHTML = html;
    el.__src = html;
    el.__first = el.firstChild;
  };
  const setText = (el, text) => { if (el && el.textContent !== String(text)) el.textContent = text; };
  const setClass = (el, name) => { if (el && el.className !== name) el.className = name; };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  const PANELS = {
    shop: "商店", detail: "精灵情报", bag: "背包 · 装备", boost: "强化 · 技能",
    bonds: "队伍羁绊", scout: "对手 · 侦察", orders: "地形 · 指令 · 模拟", journal: "战报 · 记录",
  };
  const SIZES = ["peek", "half", "full"];
  const PHONE_QUERY = "(max-width: 760px), (max-height: 520px) and (orientation: landscape)";
  const PREF_KEY = "poketactics.play.panel";
  const roleNames = {attack: "攻击型", defense: "防守型", support: "辅助型"};

  let ctx = null;
  let current = null;
  let size = "half";
  let started = false;
  let draftDeferred = null;
  let augmentShownRound = null;
  let hoverEnemy = null;
  let showAllThreat = false;

  const isPhone = () => Boolean(window.matchMedia?.(PHONE_QUERY)?.matches);
  const state = () => ctx?.state || null;
  function readPref() {
    try { return localStorage.getItem(PREF_KEY) || ""; } catch (_) { return ""; }
  }
  function writePref(value) {
    try { localStorage.setItem(PREF_KEY, value); } catch (_) { /* private mode */ }
  }

  // ------------------------------------------------------------ panels
  function applyPanel() {
    const shell = $("stage-shell");
    const drawer = $("stage-drawer");
    if (!shell || !drawer) return;
    shell.setAttribute("data-panel", current || "");
    drawer.setAttribute("data-size", size);
    document.body.classList.toggle("drawer-open", Boolean(current));
    for (const section of $("drawer-body").querySelectorAll("[data-panel]"))
      section.hidden = section.getAttribute("data-panel") !== current;
    if (current) $("drawer-title").textContent = PANELS[current];
    for (const button of $("stage-dock").querySelectorAll("[data-open-panel]")) {
      const on = button.getAttribute("data-open-panel") === current;
      button.classList.toggle("active", on);
      button.setAttribute("aria-expanded", String(on));
    }
    const grow = drawer.querySelector("[data-drawer-size]");
    if (grow) grow.setAttribute("aria-label", size === "full" ? "收起面板高度" : "展开面板高度");
    measurePeek();
  }

  function open(panel, options = {}) {
    if (!Object.hasOwn(PANELS, panel)) return false;
    const changed = panel !== current;
    current = panel;
    size = options.size || (isPhone() ? (panel === "shop" ? "peek" : "half") : "half");
    if (!isPhone() && !options.transient) writePref(panel);
    applyPanel();
    // A different panel starts at its top. Reset after showing the drawer: a
    // display:none scroller ignores scrollTop and later restores its old offset.
    if (changed && $("drawer-body")) $("drawer-body").scrollTop = 0;
    if (options.focus) $("drawer-title")?.focus?.();
    drawBoardCues();
    return true;
  }

  function close() {
    current = null;
    if (!isPhone()) writePref("closed");
    applyPanel();
    drawBoardCues();
  }

  function toggle(panel) {
    if (current === panel) close();
    else open(panel);
  }

  function resize(direction) {
    const index = SIZES.indexOf(size);
    const next = index + direction;
    if (next < 0) return close();
    size = SIZES[Math.min(SIZES.length - 1, next)];
    applyPanel();
  }

  // The phone "peek" height leaves board and bench visible above the sheet,
  // which sits on top of the fixed tab bar.
  function measurePeek() {
    const drawer = $("stage-drawer");
    const bench = document.querySelector(".bench-area");
    if (!drawer || !bench || typeof innerHeight !== "number") return;
    const bottom = bench.getBoundingClientRect?.().bottom;
    if (!Number.isFinite(bottom) || bottom <= 0) return;
    const dockTop = isPhone() ? $("stage-dock")?.getBoundingClientRect?.().top : innerHeight;
    const floor = Number.isFinite(dockTop) && dockTop > bottom ? dockTop : innerHeight;
    const peek = Math.max(180, Math.min(innerHeight * 0.62, floor - bottom - 2));
    drawer.style.setProperty("--sheet-peek", `${Math.round(peek)}px`);
  }

  // The terrain / order / sim / draft chips ride in the board's top strip; only
  // landscape phones (short board, wide HUD) move them into the HUD row.
  function placeChips(inBoard) {
    const chips = $("hud-chips");
    const host = inBoard ? document.querySelector(".board-topline") : document.querySelector(".stage-hud");
    const before = inBoard ? host?.querySelector(".scout-resume") : host?.querySelector(".hud-tools");
    if (!chips || !host || typeof host.insertBefore !== "function" || chips.parentElement === host) return;
    host.insertBefore(chips, before || null);
  }

  function applyLayoutClass() {
    const phone = isPhone();
    document.body.classList.toggle("layout-phone", phone);
    document.body.classList.toggle("layout-desktop", !phone);
    placeChips(!(phone && window.matchMedia?.("(orientation: landscape)")?.matches));
    return phone;
  }

  // ------------------------------------------------------------ HUD + badges
  function setBadge(name, value, accent = false) {
    const badge = $("stage-dock")?.querySelector(`[data-badge="${name}"]`);
    if (!badge) return;
    const show = value !== null && value !== undefined && value !== 0 && value !== "";
    badge.hidden = !show;
    setText(badge, show ? String(value) : "");
    badge.classList.toggle("accent", Boolean(show && accent));
  }

  function chip(id, html, title, extraClass = "") {
    const node = $(id);
    if (!node) return;
    node.hidden = !html;
    if (!html) return;
    setHTML(node, html);
    if (node.title !== (title || "")) node.title = title || "";
    setClass(node, `hud-chip ${id}${extraClass ? " " + extraClass : ""}`);
  }

  function renderHud(s) {
    const streak = Number(s.you?.streak) || 0;
    const streakNode = $("hud-streak");
    if (streakNode) {
      streakNode.hidden = Math.abs(streak) < 2;
      setText(streakNode, streak >= 2 ? `连胜 ${streak}` : streak <= -2 ? `连败 ${-streak}` : "");
      setClass(streakNode, `hud-stat hud-streak ${streak > 0 ? "win" : "loss"}`);
      streakNode.title = streak ? "连胜或连败达到 2 场起，每轮额外获得金币" : "";
    }
    const depth = s.depth;
    const terrain = depth?.terrain;
    const glyph = (name, label) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg><b class="sr-only">${label}</b>`;
    chip("hud-terrain", terrain ? `${glyph("mountain", "地形")}${esc(terrain.name)}` : "",
      terrain ? `${terrain.name}：${terrain.description}${terrain.next && terrain.next.id !== terrain.id ? `（第 ${Number(terrain.stage_end) + 1} 轮起：${terrain.next.name}）` : ""}` : "",
      terrain ? `terrain-${esc(terrain.id)}` : "");
    const order = depth ? (depth.orders || []).find((o) => o.id === (depth.order || "none")) : null;
    chip("hud-order", order ? `${glyph("flag", "指令")}${esc(order.name)}` : "", order ? order.brief || order.description : "",
      order && order.id !== "none" ? "on" : "");
    const sim = depth?.simulation;
    chip("hud-sim", depth ? sim ? `${glyph("swords", "模拟")}${Number(sim.wins)}胜${Number(sim.losses)}负` : `${glyph("swords", "模拟")}模拟 ×${Number(depth.simulations_left) || 0}` : "",
      depth ? "对本轮对手模拟 6 场，不影响正式结果" : "");
    const pendingDraft = depth?.draft?.status === "pending";
    chip("hud-draft", pendingDraft ? `${glyph("users", "共享")}选秀待选` : "", "共享选秀：点击打开", "accent");
    const benchCount = $("bench-count");
    if (benchCount) benchCount.textContent = `${(s.bench || []).length} / ${s.you?.bench_cap || 8}`;
  }

  function renderBadges(s) {
    const prep = ctx.canPrep();
    const gold = Number(s.you?.gold) || 0;
    setBadge("shop", prep ? (s.shop || []).filter((p) => p && Number(p.price) <= gold).length : 0);
    const supply = (Array.isArray(s.component_choices) ? s.component_choices : []).filter((r) => r.status === "pending").length;
    const gear = (s.items?.finished || []).length + (s.items?.craftable || []).length;
    setBadge("bag", supply ? `${supply}!` : gear, Boolean(supply));
    const owned = [...(s.board || []).flat(), ...(s.bench || [])].filter(Boolean);
    const mods = owned.filter((p) => (p.mod_options || []).length).length;
    const augments = (s.augments?.pending || []).length;
    setBadge("boost", augments + mods ? `${augments + mods}!` : 0, true);
    const bonds = Array.isArray(s.bonds?.entries) ? s.bonds.entries : s.synergies || [];
    setBadge("bonds", bonds.filter((row) => Number(row.tier) > 0).length);
    const threatened = Object.values(s.depth?.threat?.counts || {}).reduce((max, n) => Math.max(max, Number(n) || 0), 0);
    const falls = Object.values(s.depth?.threat?.early || {}).filter((row) => Number(row.falls) > 0).length;
    setBadge("scout", falls ? `${falls}!` : threatened >= 3 ? `⚔${threatened}` : 0, true);
    setBadge("orders", s.depth ? Number(s.depth.simulations_left) || 0 : 0);
    setBadge("journal", (Array.isArray(s.battle_history) ? s.battle_history : []).length);
    $("fight-button")?.classList.toggle("needs-choice", augments > 0);
  }

  // ------------------------------------------------------------ context bar
  function selectionSummary(p) {
    const range = Number(p.range) || 1;
    return `${roleNames[p.role_key] || "攻击型"} · ${p.ranged ? "远程" : "近战"} ${range}格${p.item_name ? ` · ◆${esc(p.item_name)}` : ""}${p.extra_item_name ? ` · ◆${esc(p.extra_item_name)}` : ""}`;
  }

  function renderContext(s) {
    const bar = $("context-bar");
    if (!bar) return;
    const prep = ctx.canPrep();
    const equip = ctx.equipItem?.();
    const shopIndex = ctx.shopSelected?.();
    const loc = ctx.selected?.();
    const sprite = (p) => window.pokeSpriteUrl ? window.pokeSpriteUrl(p.sid, p.shiny) : `/demo/sprite/${Number(p.sid)}.png`;
    let html = "";
    let mode = "";
    if (equip) {
      const item = (s.items?.finished || []).find((row) => row.key === equip);
      mode = "equip";
      html = `<span class="context-main"><b>装备「${esc(item?.name || equip)}」</b><small>点选棋盘或备战席上的精灵装上</small></span><span class="context-actions"><button type="button" data-action="cancel-select">取消</button></span>`;
    } else if (shopIndex != null && s.shop?.[shopIndex]) {
      const p = s.shop[shopIndex];
      const gold = Number(s.you?.gold) || 0;
      const short = Number(p.price) > gold;
      mode = "shop";
      const merge = p.merge_note || (p.star_progress?.merges_now ? `买下即升 ${Number(p.star_progress.next_star) || 2}★` : "");
      html = `<img src="${sprite(p)}" alt=""><span class="context-main"><b>${esc(p.name)} <em>${Number(p.price)} 金</em></b><small>${merge ? `<span class="context-merge">⇪ ${esc(merge)}</span> · ` : ""}${selectionSummary(p)}${p.trait ? ` · ◎${esc(p.trait.name)}` : ""}</small></span><span class="context-actions"><button type="button" data-layout-detail>详情</button><button type="button" class="context-primary" data-shop-buy="${Number(shopIndex)}" ${!prep || short ? "disabled" : ""}>${short ? `还差 ${Number(p.price) - gold} 金` : `招募 · ${Number(p.price)} 金`}</button><button type="button" class="context-close" data-action="cancel-select" aria-label="取消选择">×</button></span>`;
    } else if (loc) {
      const p = ctx.pieceAt(loc);
      if (p) {
        const onBoard = loc.startsWith("g");
        const depth = s.depth;
        const mods = (p.mod_options || []).length;
        mode = "unit";
        // Short version of the item advisor: the best item in the bag for this unit.
        const tip = (s.interactions?.item_advice?.suggestions || []).find((row) => row.action === "equip" && row.uid === p.uid);
        const early = onBoard ? s.depth?.threat?.early?.[p.uid] : null;
        const hits = onBoard ? Number(s.depth?.threat?.counts?.[p.uid]) || 0 : 0;
        const pressure = early ? ` · ${hits ? `⚔${hits} · ` : ""}${Number(s.depth.threat.window) || 5}秒承伤 ${Math.round((Number(early.share) || 0) * 100)}%${Number(early.falls) ? " · 可能倒下" : ""}` : "";
        html = `<img src="${sprite(p)}" alt=""><span class="context-main"><b>${p.is_core ? "♛ " : ""}${esc(p.name)} <em>${"★".repeat(Math.max(1, Math.min(3, Number(p.star) || 1)))}</em></b><small>${onBoard ? "" : "备战席 · "}${selectionSummary(p)}${pressure}</small></span><span class="context-actions"><button type="button" data-layout-detail>详情</button>${tip ? `<button type="button" class="context-advice" data-ix-advice="equip" data-item="${esc(tip.item)}" data-uid="${esc(p.uid)}" ${!prep ? "disabled" : ""} title="${esc((tip.why || []).join("；"))}">◆ 推荐 ${esc(tip.name)}</button>` : ""}${mods ? `<button type="button" class="context-primary" data-layout-detail>技能强化 ${mods}</button>` : ""}${depth ? `<button type="button" data-depth-core ${!prep || (!onBoard && !p.is_core) ? "disabled" : ""}>${p.is_core ? "取消核心" : "设为核心"}</button>` : ""}${p.item ? `<button type="button" data-action="unequip" ${!prep ? "disabled" : ""}>卸装${depth ? ` · ${Number(depth.items?.unequip_cost) || 1}金` : ""}</button>` : ""}<button type="button" class="context-sell" data-action="sell" ${!prep ? "disabled" : ""}>出售 +${Number(p.sell) || 0}</button><button type="button" class="context-close" data-action="cancel-select" aria-label="取消选择">×</button></span>`;
      }
    }
    bar.hidden = !html;
    bar.className = `context-bar${mode ? " context-" + mode : ""}`;
    setHTML(bar, html);
  }

  // ------------------------------------------------------------ board cues
  const LOC = /^g([0-2]),([0-5])$/;
  // Battle coordinates: enemy rows 0..2 (2 = front), own rows 3..5 (3 = front).
  function battlePoint(loc, enemy) {
    const m = LOC.exec(loc || "");
    if (!m) return null;
    return {row: enemy ? Number(m[1]) : Number(m[1]) + 3, col: Number(m[2])};
  }

  function center(tile, origin) {
    const box = tile.getBoundingClientRect();
    return {x: box.left - origin.left + box.width / 2, y: box.top - origin.top + box.height / 2};
  }

  // Geometry reads force a full layout; batch them into the next frame so a
  // render + cue update costs one layout (shared with paint) instead of two.
  let cueFrame = 0;
  function drawBoardCues() {
    if (typeof requestAnimationFrame !== "function") return drawBoardCuesNow();
    if (cueFrame) cancelAnimationFrame(cueFrame);
    cueFrame = requestAnimationFrame(() => { cueFrame = 0; drawBoardCuesNow(); });
  }

  function drawBoardCuesNow() {
    const s = state();
    const ally = $("ally-board");
    const enemy = $("enemy-board");
    const overlay = $("board-overlay");
    if (!s || !ally || !enemy) return;
    const allyTiles = ally.querySelectorAll("[data-loc]");
    const enemyTiles = enemy.querySelectorAll("button");
    const loc = ctx.selected?.();
    const piece = loc && loc.startsWith("g") ? ctx.pieceAt(loc) : null;
    const home = piece ? battlePoint(loc, false) : null;
    const range = piece ? Math.max(1, Number(piece.range) || 1) : 0;
    enemyTiles.forEach((tile, i) => {
      const point = {row: Math.floor(i / 6), col: i % 6};
      tile.classList.toggle("in-range", Boolean(home)
        && Math.abs(point.row - home.row) + Math.abs(point.col - home.col) <= range);
    });
    const threat = s.depth?.threat?.enemies || [];
    const uidLoc = new Map();
    for (const tile of allyTiles) {
      const p = ctx.pieceAt(tile.getAttribute("data-loc"));
      if (p?.uid) uidLoc.set(p.uid, tile);
    }
    const lines = threat.filter((row) => showAllThreat || row.loc === hoverEnemy || (piece && row.target_uid === piece.uid));
    const enemyByLoc = new Map();
    enemyTiles.forEach((tile, i) => enemyByLoc.set(`g${Math.floor(i / 6)},${i % 6}`, tile));
    const from = new Set(lines.map((row) => enemyByLoc.get(row.loc)));
    const to = new Set(lines.map((row) => uidLoc.get(row.target_uid)));
    for (const tile of enemyTiles) tile.classList.toggle("threat-from", from.has(tile));
    for (const tile of allyTiles) tile.classList.toggle("threat-target", to.has(tile));
    if (!overlay) return;
    if (!lines.length) {
      setHTML(overlay, "");
      return;
    }
    const field = $("battlefield");
    const origin = field?.getBoundingClientRect?.();
    if (!origin || !origin.width) {
      setHTML(overlay, "");
      return;
    }
    overlay.setAttribute("viewBox", `0 0 ${Math.round(origin.width)} ${Math.round(origin.height)}`);
    const segments = lines.map((row) => {
      const from = enemyByLoc.get(row.loc);
      const to = uidLoc.get(row.target_uid);
      if (!from || !to) return "";
      const a = center(from, origin);
      const b = center(to, origin);
      // Stop short of the target so the arrow head sits on the tile edge.
      const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1;
      const end = {x: b.x - dx / length * 16, y: b.y - dy / length * 16};
      return `<line class="threat-line" x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${end.x.toFixed(1)}" y2="${end.y.toFixed(1)}" marker-end="url(#threat-arrow)"><title>${esc(row.name)} 开战首先攻击 ${esc(row.target)}</title></line>`;
    }).join("");
    setHTML(overlay, `<defs><marker id="threat-arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 10 5 0 10Z"/></marker></defs>${segments}`);
  }

  function renderThreatSummary(s) {
    const box = $("threat-summary");
    if (!box) return;
    const threat = s.depth?.threat;
    if (!threat || !(threat.enemies || []).length) {
      box.hidden = true;
      setHTML(box, "");
      return;
    }
    const groups = new Map();
    for (const row of threat.enemies) {
      const entry = groups.get(row.target_uid) || {target: row.target, from: []};
      entry.from.push(`${row.name}${row.ranged ? "（远程）" : ""}`);
      groups.set(row.target_uid, entry);
    }
    const early = threat.early || {};
    const windowSec = Number(threat.window) || 5;
    const names = new Map((s.board || []).flat().filter(Boolean).map((p) => [p.uid, p.name]));
    const pressure = Object.entries(early).filter(([, row]) => Number(row.taken) > 0 || Number(row.falls) > 0)
      .sort((a, b) => Number(b[1].falls) - Number(a[1].falls) || Number(b[1].share) - Number(a[1].share));
    box.hidden = false;
    setHTML(box, `<div class="section-heading"><h2>开战威胁预测</h2><span class="tiny-label">THREAT</span></div><p class="section-note">按当前站位推演每名敌人的首个目标${Number(threat.ranged_past_front) ? `；其中 ${Number(threat.ranged_past_front)} 名远程敌人越过前排瞄准后方` : ""}。调整站位后自动刷新。</p><ul class="threat-list">${[...groups.values()].sort((a, b) => b.from.length - a.from.length).map((g) => `<li><strong>${esc(g.target)}</strong><span>← ${g.from.map(esc).join("、")}</span><em>⚔${g.from.length}</em></li>`).join("")}</ul>${pressure.length ? `<h3 class="threat-subhead">前 ${windowSec} 秒承伤</h3><ul class="pressure-list">${pressure.map(([uid, row]) => {
      const share = Math.round(Math.max(0, Math.min(1, Number(row.share) || 0)) * 100);
      const falls = Number(row.falls) || 0;
      return `<li class="${falls ? "falls" : share >= 50 ? "heavy" : ""}"><strong>${esc(names.get(uid) || "伙伴")}</strong><span class="pressure-bar" aria-hidden="true"><i style="width:${share}%"></i></span><span>${share}% 生命${falls ? ` · <b>3 次中 ${falls} 次倒下</b>` : ""}</span></li>`;
    }).join("")}</ul>` : ""}${threat.note ? `<p class="section-note threat-note">${esc(threat.note)}</p>` : ""}<button type="button" class="secondary-button threat-toggle" data-threat-all aria-pressed="${showAllThreat}">${showAllThreat ? "隐藏棋盘连线" : "在棋盘上显示全部连线"}</button>`);
  }

  function renderBoostMods(s) {
    const box = $("boost-mods");
    if (!box) return;
    const rows = [];
    s.board?.forEach((row, r) => row.forEach((p, c) => { if (p && (p.mod_options || []).length) rows.push([`g${r},${c}`, p]); }));
    (s.bench || []).forEach((p, i) => { if (p && (p.mod_options || []).length) rows.push([`b${i}`, p]); });
    box.hidden = !rows.length;
    setHTML(box, rows.length
      ? `<p class="boost-mods-title">待选技能强化 · ${rows.length}</p>${rows.map(([loc, p]) => `<button type="button" class="boost-mod-row" data-layout-select="${esc(loc)}"><strong>${esc(p.name)} ${"★".repeat(Math.max(1, Math.min(3, Number(p.star) || 1)))}</strong><span>${(p.mod_options || []).map((m) => esc(m.name)).join(" / ")}</span><em>选择 →</em></button>`).join("")}`
      : "");
  }

  // ------------------------------------------------------------ draft sheet
  function renderDraft(s) {
    const overlay = $("draft-overlay");
    if (!overlay) return;
    const draft = s.depth?.draft;
    const pending = draft?.status === "pending" && ctx.playable();
    const show = Boolean(pending && draftDeferred !== s.round);
    overlay.hidden = !show;
    document.body.classList.toggle("draft-open", show);
    if (pending && $("draft-title")) $("draft-title").textContent = `共享选秀 · 第 ${Number(draft.round)} 轮`;
  }

  // ------------------------------------------------------------ render
  function render(context) {
    ctx = context;
    const s = context.state;
    const phone = applyLayoutClass();
    if (!s) return;
    if (!started) {
      started = true;
      const pref = readPref();
      if (!phone && pref !== "closed") open(Object.hasOwn(PANELS, pref) ? pref : "shop", {transient: true});
      else applyPanel();
    }
    if (context.reason === "selection") {
      renderContext(s);
      drawBoardCues();
      return;
    }
    renderHud(s);
    renderBadges(s);
    renderContext(s);
    renderThreatSummary(s);
    renderBoostMods(s);
    renderDraft(s);
    const augments = (s.augments?.pending || []).length;
    // With the interaction layer loaded, a pending augment opens its own pick moment instead.
    if (augments && !window.PlayInteractions && ctx.playable() && augmentShownRound !== s.round
        && !document.body.classList.contains("draft-open")) {
      augmentShownRound = s.round;
      open("boost", {transient: true});
    }
    drawBoardCues();
  }

  // ------------------------------------------------------------ events
  // One selector at a time keeps this compatible with minimal DOMs (tests).
  const closestOf = (node, selectors) => {
    for (const selector of selectors) {
      const hit = node?.closest?.(selector);
      if (hit) return hit;
    }
    return null;
  };
  const CONTROLS = ["[data-open-panel]", "[data-close-panel]", "[data-drawer-size]", "[data-drawer-grip]",
    "[data-open-draft]", "[data-draft-later]", "[data-layout-detail]", "[data-layout-select]", "[data-threat-all]"];
  document.addEventListener("click", (event) => {
    const target = closestOf(event.target, CONTROLS)
      || (event.target?.id === "draft-overlay" ? event.target : null);
    if (!target || target.disabled) return;
    if (target.hasAttribute("data-open-panel")) {
      const panel = target.getAttribute("data-open-panel");
      if (target.closest("#stage-dock")) toggle(panel);
      else open(panel);
    } else if (target.hasAttribute("data-close-panel")) close();
    else if (target.hasAttribute("data-drawer-size") || target.hasAttribute("data-drawer-grip")) resize(size === "full" ? -1 : 1);
    else if (target.hasAttribute("data-open-draft")) {
      draftDeferred = null;
      if (state()) renderDraft(state());
    } else if (target.hasAttribute("data-draft-later") || target.id === "draft-overlay") {
      draftDeferred = state()?.round ?? null;
      if (state()) renderDraft(state());
    } else if (target.hasAttribute("data-layout-detail")) open("detail");
    else if (target.hasAttribute("data-layout-select")) {
      const loc = target.getAttribute("data-layout-select");
      if (ctx?.selected?.() !== loc) document.querySelector(`[data-loc="${loc}"]`)?.click?.();
      open("detail");
    } else if (target.hasAttribute("data-threat-all")) {
      showAllThreat = !showAllThreat;
      if (state()) renderThreatSummary(state());
      drawBoardCues();
    }
  });

  const enemyHover = (event) => {
    const tile = event.target?.closest?.("[data-enemy-loc]");
    const next = tile ? tile.getAttribute("data-enemy-loc") : null;
    if (next === hoverEnemy) return;
    hoverEnemy = next;
    drawBoardCues();
  };
  document.addEventListener("mouseover", enemyHover);
  document.addEventListener("focusin", enemyHover);
  document.addEventListener("dragstart", (event) => {
    if (event.target?.closest?.("[data-owned]")) document.body.classList.add("is-dragging");
  });
  for (const type of ["dragend", "drop"])
    document.addEventListener(type, () => document.body.classList.remove("is-dragging"));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !current || !isPhone()) return;
    if (document.querySelector("dialog[open]")) return;
    close();
  });

  // Swipe the sheet grip/header: up grows, down shrinks (and finally closes).
  let swipe = null;
  document.addEventListener("pointerdown", (event) => {
    const grip = closestOf(event.target, [".drawer-grip", ".drawer-header"]);
    if (!grip || !isPhone() || event.target.closest("button")) return;
    swipe = {y: event.clientY, t: Date.now()};
  });
  document.addEventListener("pointerup", (event) => {
    if (!swipe) return;
    const dy = event.clientY - swipe.y;
    swipe = null;
    if (Math.abs(dy) > 40) resize(dy > 0 ? -1 : 1);
  });

  if (typeof window.addEventListener === "function") {
    window.addEventListener("resize", () => {
      if (!ctx) return;
      const phone = applyLayoutClass();
      if (phone && size === "half" && current === "shop") size = "peek";
      applyPanel();
      drawBoardCues();
    });
  }

  window.PlayLayout = {render, open, close, toggle, current: () => current, size: () => size, isPhone};
})();
