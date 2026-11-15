/* Action feedback layer (docs/63).
 *
 * play.js calls PlayFeedback.before(cmd, params, state) at the start of every
 * api() call and PlayFeedback.after(token, result, state) once the page has
 * re-rendered. The module diffs the old and new state and plays feedback at the
 * place where the change happened: flying sprites/items, rings, floating
 * numbers, HUD bumps, shop deal-in, error shake, optional sound and haptics.
 * Every successful action gets at least a confirmation ring on the control that
 * triggered it, so nothing ever happens silently. Selection changes get a
 * pick-up bounce via PlayFeedback.selection(). Reduced-motion users get static
 * glows and fading text instead of motion.
 */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const coarse = () => typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
  const SKIP = new Set(["state", "resume", "save", "end_prep", "next", "finish"]);
  let lastClick = null;
  let lastSelection = {selected: null, shopSelected: null, equipItem: null};
  let audio = null;

  // ------------------------------------------------------------- capture
  document.addEventListener("pointerdown", (event) => {
    const el = event.target?.closest?.("button, [data-loc], [data-shop], [data-equip], [data-ix-cell], .shop-card, .tile, .bench-slot");
    if (el) lastClick = el;
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") lastClick = document.activeElement;
  }, true);

  const rectOf = (el) => {
    if (!el || typeof el.getBoundingClientRect !== "function" || !el.isConnected) return null;
    const r = el.getBoundingClientRect();
    return r.width || r.height ? {x: r.left, y: r.top, w: r.width, h: r.height} : null;
  };
  const centre = (r) => r && {x: r.x + r.w / 2, y: r.y + r.h / 2};
  const unitEl = (uid) => uid && document.querySelector(`#ally-board [data-uid="${CSS.escape(uid)}"], #bench [data-uid="${CSS.escape(uid)}"]`);

  function units(state) {
    const out = new Map();
    (state?.board || []).forEach((row, r) => (row || []).forEach((p, c) => p?.uid && out.set(p.uid, {...p, loc: `g${r},${c}`})));
    (state?.bench || []).forEach((p, i) => p?.uid && out.set(p.uid, {...p, loc: `b${i}`}));
    return out;
  }
  const countBy = (rows, key = "key", n = null) => {
    const map = new Map();
    for (const row of rows || []) map.set(row[key], (map.get(row[key]) || 0) + (n ? Number(row[n]) || 0 : 1));
    return map;
  };
  const techCount = (state) => {
    const list = Array.isArray(state?.techniques) ? state.techniques : state?.techniques?.inventory || [];
    return new Map(list.map((t) => [t.id, Number(t.count) || 0]));
  };

  function before(cmd, params, state) {
    if (SKIP.has(cmd) || !state) return null;
    const unitRects = new Map();
    for (const [uid] of units(state)) unitRects.set(uid, rectOf(unitEl(uid)));
    const shopRect = params?.i != null ? rectOf(document.querySelector(`#shop [data-shop="${CSS.escape(String(params.i))}"]`)) : null;
    const itemKey = params?.item;
    const itemRect = itemKey ? rectOf(document.querySelector(`[data-ix-equip="${CSS.escape(itemKey)}"], [data-equip="${CSS.escape(itemKey)}"], [data-ix-cell][data-item="${CSS.escape(itemKey)}"]`)) : null;
    const clickRect = rectOf(lastClick);
    return {cmd, params: {...params}, prev: state, unitRects, shopRect, itemRect,
            click: lastClick, clickRect, pending: pendingMark(clickRect)};
  }

  /** Immediate press acknowledgement, independent of re-rendering, until the server answers. */
  function pendingMark(rect) {
    if (!rect) return null;
    const el = document.createElement("div");
    el.className = "fb-pending";
    el.style.left = `${rect.x}px`;
    el.style.top = `${rect.y}px`;
    el.style.width = `${rect.w}px`;
    el.style.height = `${rect.h}px`;
    layer().append(el);
    return el;
  }

  // ------------------------------------------------------------- effects
  function layer() {
    let el = $("fb-layer");
    if (!el) {
      el = document.createElement("div");
      el.id = "fb-layer";
      el.setAttribute("aria-hidden", "true");
      document.body.append(el);
    }
    return el;
  }

  function float(point, text, kind = "info", delay = 0) {
    if (!point) return;
    const el = document.createElement("div");
    el.className = `fb-float fb-${kind}`;
    el.textContent = text;
    el.style.left = `${point.x}px`;
    el.style.top = `${point.y}px`;
    el.style.animationDelay = `${delay}ms`;
    layer().append(el);
    setTimeout(() => el.remove(), 1500 + delay);
  }

  function ring(el, kind = "good") {
    if (!el?.classList) return;
    const cls = `fb-ring-${kind}`;
    el.classList.remove("fb-ring", cls);
    void el.offsetWidth;
    el.classList.add("fb-ring", cls);
    setTimeout(() => el.classList?.remove("fb-ring", cls), 900);
  }

  function bump(el) {
    if (!el?.classList) return;
    el.classList.remove("fb-bump");
    void el.offsetWidth;
    el.classList.add("fb-bump");
    setTimeout(() => el.classList?.remove("fb-bump"), 600);
  }

  function shake(el) {
    if (!el?.classList || reduced()) return;
    el.classList.remove("fb-shake");
    void el.offsetWidth;
    el.classList.add("fb-shake");
    setTimeout(() => el.classList?.remove("fb-shake"), 500);
  }

  /** Fly a sprite or a chip from one rect to another along a short arc. */
  function fly(from, to, {sprite = null, label = "", kind = "item"} = {}) {
    if (!from || !to || reduced() || typeof Element === "undefined" || !Element.prototype.animate) return Promise.resolve();
    const el = document.createElement("div");
    el.className = `fb-fly fb-fly-${kind}`;
    el.innerHTML = sprite ? `<img src="${esc(sprite)}" alt="">` : `<span>${esc(label)}</span>`;
    layer().append(el);
    const a = centre(from), b = centre(to);
    const lift = Math.min(120, Math.max(40, Math.hypot(b.x - a.x, b.y - a.y) * .25));
    const mid = {x: (a.x + b.x) / 2, y: Math.min(a.y, b.y) - lift};
    const anim = el.animate([
      {transform: `translate(${a.x}px, ${a.y}px) translate(-50%, -50%) scale(1)`, opacity: .95},
      {transform: `translate(${mid.x}px, ${mid.y}px) translate(-50%, -50%) scale(1.15)`, opacity: 1, offset: .5},
      {transform: `translate(${b.x}px, ${b.y}px) translate(-50%, -50%) scale(.8)`, opacity: .9},
    ], {duration: 520, easing: "cubic-bezier(.3,.7,.4,1)"});
    return anim.finished.catch(() => {}).then(() => el.remove());
  }

  function ghost(rect, sprite) {
    if (!rect || reduced()) return;
    const el = document.createElement("div");
    el.className = "fb-ghost";
    el.innerHTML = sprite ? `<img src="${esc(sprite)}" alt="">` : "";
    el.style.left = `${rect.x}px`;
    el.style.top = `${rect.y}px`;
    el.style.width = `${rect.w}px`;
    el.style.height = `${rect.h}px`;
    layer().append(el);
    setTimeout(() => el.remove(), 700);
  }

  function banner(text, sub = "") {
    const el = document.createElement("div");
    el.className = "fb-banner";
    el.innerHTML = `<strong>${esc(text)}</strong>${sub ? `<span>${esc(sub)}</span>` : ""}`;
    layer().append(el);
    setTimeout(() => el.remove(), 1700);
  }

  function tween(el, from, to) {
    if (!el || from === to || reduced() || !Number.isFinite(from) || !Number.isFinite(to)) return;
    const start = performance.now(), span = 420;
    const step = (now) => {
      const k = Math.min(1, (now - start) / span);
      el.textContent = String(k < 1 ? Math.round(from + (to - from) * k) : to);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function vibrate(pattern) {
    if (coarse() && navigator.vibrate) {
      try { navigator.vibrate(pattern); } catch (_) { /* unsupported */ }
    }
  }

  const SOUNDS = {
    buy: [[880, .05], [1175, .07]], sell: [[660, .05], [440, .09]], equip: [[520, .04], [780, .04], [1040, .08]],
    learn: [[523, .05], [659, .05], [784, .09]], level: [[523, .06], [659, .06], [784, .06], [1046, .12]],
    craft: [[700, .04], [940, .1]], move: [[600, .04]], select: [[900, .025]], error: [[220, .12], [180, .14]],
    good: [[740, .06], [988, .08]],
  };
  function sound(kind) {
    if (!window.PlaySound?.enabled?.()) return;
    try {
      audio ||= new (window.AudioContext || window.webkitAudioContext)();
      audio.resume().catch(() => {});
      let at = audio.currentTime;
      for (const [freq, len] of SOUNDS[kind] || SOUNDS.good) {
        const osc = audio.createOscillator(), gain = audio.createGain();
        osc.type = kind === "error" ? "square" : "triangle";
        osc.frequency.setValueAtTime(freq, at);
        gain.gain.setValueAtTime(.05, at);
        gain.gain.exponentialRampToValueAtTime(.001, at + len);
        osc.connect(gain).connect(audio.destination);
        osc.start(at);
        osc.stop(at + len + .01);
        at += len * .8;
      }
    } catch (_) { /* audio unavailable */ }
  }

  const spriteOf = (p) => p && (window.pokeSpriteUrl ? window.pokeSpriteUrl(p.sid, p.shiny) : `/demo/sprite/${Number(p.sid)}.png`);
  const dock = (panel) => document.querySelector(`[data-open-panel="${panel}"].dock-button, [data-open-panel="${panel}"]`);
  const itemName = (state, key) => (state?.items?.finished || []).find((row) => row.key === key)?.name
    || (state?.items?.craftable || []).find((row) => row.key === key)?.name || key;

  // ------------------------------------------------------------- after
  function after(token, result, state) {
    if (!token) return;
    token.pending?.remove();
    const clickEl = token.click?.isConnected ? token.click : null;
    if (!result || result.ok === false) {
      shake(clickEl || $("toast"));
      vibrate([20, 40, 20]);
      sound("error");
      return;
    }
    if (!state) return;
    const prev = token.prev;
    const before = units(prev), now = units(state);
    let fired = false, kind = null;
    const mark = (k) => { fired = true; kind ||= k; };

    // units entering, leaving, moving, changing
    for (const [uid, p] of now) {
      const old = before.get(uid);
      const el = unitEl(uid);
      const rect = rectOf(el);
      if (!old) {
        const from = token.cmd === "buy" ? token.shopRect : token.clickRect;
        fly(from, rect, {sprite: spriteOf(p), kind: "unit"}).then(() => { ring(unitEl(uid), "good"); float(centre(rectOf(unitEl(uid))), `+ ${p.name}`, "good"); });
        mark(token.cmd === "buy" ? "buy" : "good");
        continue;
      }
      if (old.loc !== p.loc) {
        ring(el, "move");
        if (old.loc[0] !== p.loc[0]) float(centre(rect), p.loc[0] === "g" ? "上场" : "回到备战席", "info");
        mark("move");
      }
      if (old.item !== p.item || old.extra_item !== p.extra_item) {
        const added = [p.item, p.extra_item].filter((k) => k && k !== old.item && k !== old.extra_item);
        const removed = [old.item, old.extra_item].filter((k) => k && k !== p.item && k !== p.extra_item);
        for (const key of added) {
          const name = key === p.item ? p.item_name : p.extra_item_name;
          fly(token.itemRect || token.clickRect, rect, {label: `◆ ${name || key}`, kind: "item"})
            .then(() => { ring(unitEl(uid), "item"); float(centre(rectOf(unitEl(uid))), `◆ ${name || key}`, "item"); });
          mark("equip");
        }
        for (const key of removed) {
          const name = key === old.item ? old.item_name : old.extra_item_name;
          if (token.cmd === "sell") continue;
          fly(rect || token.unitRects.get(uid), rectOf(dock("bag")), {label: `◆ ${name || key}`, kind: "item"});
          float(centre(rect), `卸下 ${name || key}`, "info");
          bump(dock("bag"));
          mark("equip");
        }
      }
      if ((old.technique?.id || null) !== (p.technique?.id || null) && p.technique) {
        ring(el, "skill");
        float(centre(rect), `学会 ${p.technique.name}`, "skill");
        mark("learn");
      }
      const oldMods = (old.skill_mods || []).map((m) => m.id), newMods = (p.skill_mods || []).map((m) => m.id);
      if (newMods.length > oldMods.length) {
        const mod = (p.skill_mods || [])[newMods.length - 1];
        ring(el, "gold");
        float(centre(rect), `本命强化 · ${mod?.name || ""}`, "gold");
        mark("learn");
      }
      if (Boolean(old.is_core) !== Boolean(p.is_core)) {
        ring(el, "gold");
        float(centre(rect), p.is_core ? "♛ 成为核心" : "取消核心", p.is_core ? "gold" : "info");
        mark("good");
      }
      if (Number(p.star) > Number(old.star)) mark("level");  // merge animation is play.js animateUpgrade
    }
    for (const [uid, old] of before) {
      if (now.has(uid)) continue;
      const rect = token.unitRects.get(uid);
      if (token.cmd === "sell") {
        ghost(rect, spriteOf(old));
        mark("sell");
      }
    }

    // economy
    const goldEl = $("gold");
    const dGold = (Number(state.you?.gold) || 0) - (Number(prev.you?.gold) || 0);
    if (dGold) {
      tween(goldEl, Number(prev.you?.gold) || 0, Number(state.you?.gold) || 0);
      bump(goldEl?.closest(".hud-stat") || goldEl);
      float(centre(rectOf(goldEl)), `${dGold > 0 ? "+" : "−"}${Math.abs(dGold)} 金`, dGold > 0 ? "gold" : "spend");
      if (token.cmd === "sell" && token.clickRect) float(centre(token.clickRect), `+${dGold} 金`, "gold");
      fired = true;
    }
    if ((Number(state.you?.level) || 0) > (Number(prev.you?.level) || 0)) {
      bump($("level")?.closest(".hud-stat"));
      banner(`升级！Lv.${state.you.level}`, `上场人口 ${state.you.pop}`);
      mark("level");
    } else if (token.cmd === "levelup") {
      const xpEl = $("xp-fill")?.closest(".hud-stat") || $("xp-fill");
      ring(xpEl, "gold");
      float(centre(rectOf($("xp-text") || xpEl)), "+4 XP", "gold");
      mark("good");
    }

    // inventory
    const fBefore = countBy(prev.items?.finished), fNow = countBy(state.items?.finished);
    for (const [key, n] of fNow) {
      if (n > (fBefore.get(key) || 0)) {
        const name = itemName(state, key);
        if (token.cmd === "craft") {
          ring(clickEl, "item");
          float(centre(token.clickRect), `合成 ${name}`, "item");
          fly(token.clickRect, rectOf(dock("bag")), {label: `◆ ${name}`, kind: "item"});
        } else {
          float(centre(rectOf(dock("bag"))), `+ ${name}`, "item");
        }
        bump(dock("bag"));
        mark("craft");
      }
    }
    for (const [key, n] of fBefore) {
      if (n > (fNow.get(key) || 0) && ["sell_item", "dismantle"].includes(token.cmd)) {
        float(centre(token.clickRect), token.cmd === "dismantle" ? `拆解 ${itemName(prev, key)}` : `出售 ${itemName(prev, key)}`, "info");
        mark(token.cmd === "dismantle" ? "craft" : "sell");
      }
    }
    const cBefore = countBy(prev.items?.components, "key", "n"), cNow = countBy(state.items?.components, "key", "n");
    for (const [key, n] of cNow) {
      if (n > (cBefore.get(key) || 0) && token.cmd !== "craft") {
        const name = (state.items?.components || []).find((row) => row.key === key)?.name || key;
        float(centre(rectOf(dock("bag"))), `+ ${name}`, "item", 120);
        bump(dock("bag"));
        mark("craft");
      }
    }
    const tBefore = techCount(prev), tNow = techCount(state);
    for (const [id, n] of tNow) if (n > (tBefore.get(id) || 0)) { bump(dock("boost")); mark("good"); }

    // shop and rules
    if (["refresh", "refresh_type"].includes(token.cmd)) {
      document.querySelectorAll("#shop .shop-card").forEach((card, i) => {
        card.classList.add("fb-deal");
        card.style.animationDelay = `${i * 60}ms`;
        setTimeout(() => card.classList?.remove("fb-deal"), 900);
      });
      mark("good");
    }
    if (token.cmd === "lock") {
      const lock = $("lock-button");
      bump(lock);
      float(centre(rectOf(lock)), state.you?.shop_locked ? "已锁定" : "已解锁", "info");
      mark("good");
    }
    const augBefore = (prev.augments?.selected || []).length, augNow = state.augments?.selected || [];
    if (augNow.length > augBefore) {
      const picked = augNow[augNow.length - 1];
      banner(`获得海克斯 · ${picked.name}`, picked.brief || "");
      const strip = $("ix-augment-strip");
      if (strip) fly(token.clickRect, rectOf(strip), {label: `✦ ${picked.name}`, kind: "augment"}).then(() => bump(strip));
      mark("level");
    }
    if (token.cmd === "reroll_augment") {
      document.querySelectorAll("#ix-augment-cards article, .augment-card").forEach((card, i) => {
        card.classList.add("fb-deal");
        card.style.animationDelay = `${i * 80}ms`;
        setTimeout(() => card.classList?.remove("fb-deal"), 1000);
      });
      mark("good");
    }
    if ((prev.depth?.order || "none") !== (state.depth?.order || "none")) {
      const chip = $("hud-order");
      bump(chip);
      ring(chip, "gold");
      mark("good");
    }
    if (token.cmd === "simulate") {
      bump($("hud-sim"));
      ring($("hud-sim"), "good");
      mark("good");
    }

    if (!fired) {
      ring(clickEl, "good");
      if (clickEl) float(centre(rectOf(clickEl)), "✓", "good");
      kind = "good";
    }
    sound(kind || "good");
    vibrate(kind === "level" ? [12, 30, 12] : 10);
  }

  // ------------------------------------------------------------- selection
  function selection(next) {
    const changed = ["selected", "shopSelected", "equipItem"].find((key) => next[key] != null && next[key] !== lastSelection[key]);
    lastSelection = {...next};
    if (!changed) return;
    const el = changed === "selected"
      ? document.querySelector(`#ally-board [data-loc="${CSS.escape(next.selected)}"], #bench [data-loc="${CSS.escape(next.selected)}"]`)
      : changed === "shopSelected"
        ? document.querySelector(`#shop [data-shop="${CSS.escape(String(next.shopSelected))}"]`)
        : document.querySelector(`[data-equip="${CSS.escape(next.equipItem)}"]`);
    if (!el) return;
    el.classList.remove("fb-picked");
    void el.offsetWidth;
    el.classList.add("fb-picked");
    setTimeout(() => el.classList?.remove("fb-picked"), 500);
    sound("select");
    vibrate(8);
  }

  window.PlayFeedback = {before, after, selection, float, ring, bump, fly, banner};
})();
