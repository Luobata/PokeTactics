/* Phone interaction layer of the play page (docs/74, mobile audit 2026-11-27).
 *
 * play_layout.js decides *what* is shown on a phone (body.layout-phone, sheets,
 * tab bar); this module owns *how it feels under a thumb*:
 *   - the HUD menu sheet: sound / vibration toggles, guide, rules, backup, new game
 *     and the site links, as labelled 48px rows (the HUD tools and site nav are
 *     hidden on phones) — rows proxy the original buttons, so play.js / play_mobile.js
 *     handlers stay the single source of truth;
 *   - touch drag of own units between board cells and the bench (pointer events,
 *     a ghost under the finger, drop targets highlighted, one move command);
 *   - a 「招募 · N 金」 button on the selected shop card, inside the sheet;
 *   - empty cells highlighted while an own unit is selected;
 *   - toast timing (play.js asks toastHold) and the toast's place under the HUD;
 *   - the portrait tile height, measured so the shop sheet never covers the bench;
 *   - sprite placeholders until thumbnails arrive; the lost-HP line on the verdict;
 *   - battle dialog copy for phones (「跳过」 instead of a bare ×).
 * All game mutations still go through play.js (ctx.actions / ctx.api / data-*).
 * play.js calls PlayPhone.render(ctx) after every render (renderHelpers).
 */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const DRAG_SLOP = 10;
  const SHEET_PEEK = 200; // shop sheet height the portrait layout keeps free under the bench
  let ctx = null;
  let phone = false;
  const status = {drags: 0, moves: 0, quickBuys: 0, lastToastHold: null, tileH: null};

  const isPhone = () => Boolean(window.PlayLayout?.isPhone?.());
  const isPortraitPhone = () => isPhone() && !window.PlayLayout?.isLandscape?.();
  const buzz = (pattern) => window.PlayMobile?.buzz?.(pattern);
  const S = () => ctx?.state || null;

  // ------------------------------------------------------------ menu sheet
  const menu = () => $("phone-menu");
  const menuOpen = () => Boolean(menu() && !menu().hidden);
  function syncMenu() {
    for (const row of document.querySelectorAll("[data-menu-proxy]")) {
      const source = $(row.dataset.menuProxy);
      // The source keeps its own visibility rules (e.g. no vibration on iOS).
      row.hidden = !source || source.hidden;
      if (!source) continue;
      if (row.classList.contains("menu-toggle")) {
        const on = source.getAttribute("aria-pressed") === "true";
        row.setAttribute("aria-pressed", String(on));
        row.querySelector(".menu-switch")?.setAttribute("data-on", String(on));
      }
      row.disabled = Boolean(source.disabled);
    }
  }
  function buildLinks() {
    const host = $("phone-menu-links");
    if (!host || host.dataset.built) return;
    host.dataset.built = "1";
    const keep = ["营地首页", "战术图鉴", "玩法指南"];
    const links = [...document.querySelectorAll(".portal-nav a")]
      .filter((a) => keep.includes(a.textContent.trim()));
    for (const link of links) {
      const row = document.createElement("a");
      row.className = "menu-row menu-link";
      row.href = link.getAttribute("href");
      row.innerHTML = `<span>${link.textContent.trim()}</span><small>离开对局，进度已保存</small>`;
      host.append(row);
    }
    host.hidden = !links.length;
  }
  function openMenu() {
    if (!menu()) return;
    buildLinks();
    syncMenu();
    window.PlayContext?.close?.({restore: false});
    window.PlayPreview?.hide?.();
    menu().hidden = false;
    $("menu-button")?.setAttribute("aria-expanded", "true");
    document.body.classList.add("phone-menu-open");
    menu().querySelector(".phone-menu-head .icon-button")?.focus?.({preventScroll: true});
  }
  function closeMenu() {
    if (!menuOpen()) return;
    menu().hidden = true;
    $("menu-button")?.setAttribute("aria-expanded", "false");
    document.body.classList.remove("phone-menu-open");
  }
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (target.closest?.("#menu-button")) { menuOpen() ? closeMenu() : openMenu(); return; }
    if (!menuOpen()) return;
    if (target.closest?.("[data-menu-close]")) { closeMenu(); return; }
    const row = target.closest?.("[data-menu-proxy]");
    if (row && !row.disabled) {
      const source = $(row.dataset.menuProxy);
      const toggle = row.classList.contains("menu-toggle");
      // Dialog-opening actions close the menu first so the dialog is on top.
      if (!toggle) closeMenu();
      source?.click();
      if (toggle) setTimeout(syncMenu, 0);
      return;
    }
    if (target.closest?.(".menu-link")) closeMenu();
  });
  window.PlayOverlay?.register?.({id: "menu", layer: 84, above: true, isOpen: menuOpen, close: closeMenu});

  // ------------------------------------------------------------ touch drag
  let press = null;
  let drag = null;
  let swallowClickUntil = 0;
  const dropTarget = (x, y) => {
    const el = document.elementFromPoint?.(x, y);
    const cell = el?.closest?.("#ally-board [data-loc], #bench [data-loc]");
    return cell && cell !== drag?.tile ? cell : null;
  };
  function startDrag(event) {
    const {tile, from} = press;
    const img = tile.querySelector("img");
    const ghost = document.createElement("div");
    ghost.className = "touch-drag-ghost";
    ghost.setAttribute("aria-hidden", "true");
    if (img) ghost.append(Object.assign(document.createElement("img"), {src: img.currentSrc || img.src, alt: ""}));
    document.body.append(ghost);
    drag = {...press, ghost, over: null};
    press = null;
    tile.classList.add("drag-source");
    document.body.classList.add("is-dragging", "touch-dragging");
    try { tile.setPointerCapture?.(event.pointerId); } catch (_) { /* already released */ }
    window.PlayContext?.close?.({restore: false});
    window.PlayPreview?.hide?.();
    status.drags += 1;
    buzz([8]);
    moveGhost(event.clientX, event.clientY);
  }
  function moveGhost(x, y) {
    if (!drag) return;
    drag.ghost.style.transform = `translate(${Math.round(x - 32)}px, ${Math.round(y - 70)}px)`;
    const over = dropTarget(x, y);
    if (over !== drag.over) {
      drag.over?.classList.remove("drop-target");
      over?.classList.add("drop-target");
      drag.over = over;
    }
  }
  function endDrag(commit) {
    if (!drag) return;
    const {tile, from, over, ghost} = drag;
    drag = null;
    ghost.remove();
    tile.classList.remove("drag-source");
    over?.classList.remove("drop-target");
    document.body.classList.remove("is-dragging", "touch-dragging");
    swallowClickUntil = Date.now() + 350;
    const to = over?.getAttribute("data-loc");
    if (commit && to && to !== from && ctx?.actions?.move) {
      status.moves += 1;
      ctx.actions.move(from, to);
    }
  }
  document.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" || event.button > 0 || drag) return;
    const tile = event.target?.closest?.("#ally-board [data-loc][data-owned], #bench [data-loc][data-owned]");
    if (!tile || !ctx?.canPrep?.() || window.PlayInteractions?.mode?.()) return;
    press = {id: event.pointerId, x: event.clientX, y: event.clientY, tile, from: tile.getAttribute("data-loc"),
      bench: tile.closest("#bench") != null};
  }, true);
  document.addEventListener("pointermove", (event) => {
    if (drag && event.pointerId === drag.id) { event.preventDefault?.(); moveGhost(event.clientX, event.clientY); return; }
    if (!press || event.pointerId !== press.id) return;
    const dx = event.clientX - press.x;
    const dy = event.clientY - press.y;
    if (Math.hypot(dx, dy) < DRAG_SLOP) return;
    // The bench row scrolls sideways (touch-action: pan-x): like the browser, treat a
    // mostly-horizontal start as a scroll; a mostly-vertical one picks the unit up.
    if (press.bench && Math.abs(dx) >= Math.abs(dy)) { press = null; return; }
    startDrag(event);
  }, {capture: true, passive: false});
  document.addEventListener("pointerup", (event) => {
    if (drag && event.pointerId === drag.id) { moveGhost(event.clientX, event.clientY); endDrag(true); }
    press = null;
  }, true);
  document.addEventListener("pointercancel", () => { press = null; endDrag(false); }, true);
  // A drag ends without a click; if a browser still sends one, it must not select the drop cell.
  document.addEventListener("click", (event) => {
    if (Date.now() < swallowClickUntil && event.target?.closest?.("[data-loc]")) {
      swallowClickUntil = 0;
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener("dragstart", (event) => { if (drag) event.preventDefault(); }, true);

  // ------------------------------------------------------------ shop quick buy
  function quickBuy() {
    const shop = $("shop");
    if (!shop) return;
    let button = shop.querySelector(".shop-quick-buy");
    const index = ctx?.shopSelected?.();
    const p = index != null ? S()?.shop?.[index] : null;
    const card = index != null ? shop.querySelector(`[data-shop="${index}"]`) : null;
    if (!phone || !p || !card || window.PlayLayout?.current?.() !== "shop") { button?.remove(); return; }
    if (!button) {
      button = document.createElement("button");
      button.type = "button";
      button.className = "shop-quick-buy";
      shop.append(button);
    } else if (button !== shop.lastElementChild) {
      shop.append(button); // keep it after the cards so play.js keyed writes see their first child
    }
    const gold = Number(S()?.you?.gold) || 0;
    const short = Math.max(0, Number(p.price) - gold);
    const prep = Boolean(ctx.canPrep?.());
    button.setAttribute("data-shop-buy", String(index));
    button.disabled = !prep || short > 0;
    button.textContent = short ? `还差 ${short} 金` : `招募 · ${Number(p.price)} 金`;
    button.setAttribute("aria-label", short ? `还差 ${short} 金币` : `招募${p.name}，${p.price}金币`);
    button.style.left = `${card.offsetLeft + 6}px`;
    button.style.width = `${Math.max(60, card.offsetWidth - 12)}px`;
    button.style.top = `${card.offsetTop + card.offsetHeight - 46}px`;
  }
  document.addEventListener("click", (event) => {
    if (event.target?.closest?.(".shop-quick-buy")) status.quickBuys += 1;
  }, true);

  // ------------------------------------------------------------ toasts
  /** How long play.js should show a toast on this device (ms); 0 = skip it. */
  function toastHold(message, error) {
    if (!isPhone()) return 3600;
    let hold = error ? 3000 : 1800;
    // Pure confirmations already shown by the board / banner: the piece moved, the level-up banner.
    if (!error && (/ 移动$/.test(message) || /^升级！/.test(message))) hold = 0;
    status.lastToastHold = hold;
    return hold;
  }
  function placeToast() {
    const hud = document.querySelector(".stage-hud");
    const bottom = hud?.getBoundingClientRect?.().bottom;
    if (Number.isFinite(bottom)) document.body.style.setProperty("--toast-top", `${Math.max(6, Math.round(bottom + 6))}px`);
  }

  // ------------------------------------------------------------ portrait tile height
  // Rows get whatever height is left after the HUD, top strip, bench and a shop
  // sheet's worth of space, so opening the shop never covers the bench.
  function fitTiles() {
    const body = document.body;
    if (!isPortraitPhone()) {
      if (status.tileH != null) {
        body.style.removeProperty("--tile-h");
        status.tileH = null;
        window.PlayLayout?.measure?.();
      }
      return;
    }
    const grid = document.querySelector("#ally-board");
    const bench = document.querySelector(".bench-area");
    const dock = $("stage-dock");
    if (!grid || !bench || !dock || typeof innerHeight !== "number") return;
    const tile = grid.querySelector(".tile")?.getBoundingClientRect?.();
    const benchBox = bench.getBoundingClientRect();
    const dockTop = dock.getBoundingClientRect().top;
    if (!tile?.height || !(dockTop > 0)) return;
    const scroll = window.scrollY || 0;
    // Everything above the bench's bottom that is not one of the 6 rows.
    const rows = tile.height * 6;
    const fixed = benchBox.bottom + scroll - rows;
    const width = tile.width || 54;
    const room = dockTop - SHEET_PEEK - fixed;
    const h = Math.floor(Math.max(34, Math.min(width, room / 6)));
    if (h !== status.tileH && Math.abs(h - tile.height) >= 1) {
      body.style.setProperty("--tile-h", `${h}px`);
      status.tileH = h;
      // The sheet heights are measured from the board / bench: measure again on the new rows.
      window.PlayLayout?.measure?.();
    } else if (status.tileH == null) {
      status.tileH = Math.round(tile.height);
    }
  }

  // ------------------------------------------------------------ sprite placeholders
  const SPRITES = ".tile img, .bench-slot img, .shop-art img";
  function markImages(root = document) {
    for (const img of root.querySelectorAll?.(SPRITES) || []) {
      if (img.complete && img.naturalWidth > 0) img.classList.add("img-ready");
    }
  }
  document.addEventListener("load", (event) => {
    if (event.target?.matches?.(SPRITES)) event.target.classList.add("img-ready");
  }, true);
  document.addEventListener("error", (event) => {
    if (event.target?.matches?.(SPRITES)) event.target.classList.add("img-ready", "img-failed");
  }, true);

  // ------------------------------------------------------------ verdict: lost HP
  let hpBefore = null;
  let hpRound = null;
  function trackHp() {
    const s = S();
    if (!s?.you) return;
    if (s.phase === "prep") { hpBefore = Number(s.you.hp); hpRound = s.round; }
  }
  function showHpDelta() {
    const line = $("battle-verdict-hp");
    const s = S();
    if (!line || !s?.you || hpBefore == null) return;
    const now = Number(s.you.hp);
    if (!Number.isFinite(now)) return;
    const lost = hpBefore - now;
    line.textContent = lost > 0 ? `生命 ${hpBefore} → ${now}（−${lost}）` : `生命无损 · ${now}`;
    line.classList.toggle("lost", lost > 0);
    line.hidden = false;
  }
  function watchVerdict() {
    const verdict = $("battle-verdict");
    if (!verdict || typeof MutationObserver !== "function") return;
    new MutationObserver(() => {
      if (verdict.hidden) { const line = $("battle-verdict-hp"); if (line) line.hidden = true; }
      else showHpDelta();
    }).observe(verdict, {attributes: true, attributeFilter: ["hidden"]});
  }

  // ------------------------------------------------------------ battle dialog copy
  function battleCopy() {
    const close = $("battle-close");
    if (!close) return;
    const want = phone ? "skip" : "close";
    if (close.dataset.phoneCopy === want) return;
    close.dataset.phoneCopy = want;
    if (phone) {
      close.innerHTML = '跳过<span aria-hidden="true">›</span>';
      close.setAttribute("aria-label", "跳过回放，进入下一轮");
      close.classList.add("battle-skip");
    } else {
      close.textContent = "×";
      close.setAttribute("aria-label", "收起战斗回放");
      close.classList.remove("battle-skip");
    }
  }

  // ------------------------------------------------------------ render
  function render(context) {
    ctx = context;
    phone = isPhone();
    const body = document.body;
    const selected = ctx?.selected?.();
    body.classList.toggle("unit-picked", Boolean(phone && selected && ctx?.canPrep?.() && ctx.pieceAt?.(selected)));
    const y = S()?.you;
    const xp = $("hud-xp-compact");
    if (xp) {
      const text = y && y.xp_next != null ? `${Number(y.xp) || 0}/${Number(y.xp_next)}` : y ? "MAX" : "";
      if (xp.textContent !== text) xp.textContent = text;
    }
    trackHp();
    quickBuy();
    battleCopy();
    markImages();
    if (menuOpen()) syncMenu();
    scheduleMeasure();
  }
  // Geometry reads (HUD bottom, tile fit) once per frame after the render's DOM writes,
  // not inside every render (docs/66: keep re-renders free of forced layouts).
  let measureQueued = false;
  function scheduleMeasure() {
    if (measureQueued) return;
    measureQueued = true;
    const run = () => {
      measureQueued = false;
      if (isPhone()) placeToast();
      fitTiles();
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(run);
    else run();
  }

  function boot() {
    watchVerdict();
    markImages();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  if (typeof window.addEventListener === "function") {
    window.addEventListener("resize", () => {
      if (!ctx) return;
      phone = isPhone();
      battleCopy();
      scheduleMeasure();
      quickBuy();
    });
  }

  window.PlayPhone = {render, toastHold, openMenu, closeMenu, menuOpen, status,
    dragging: () => Boolean(drag), fitTiles};
})();
