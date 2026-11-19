/* arena_v2 stage weather (docs/69): HUD chip, forecast popover, swap, board ambience
 * and "favoured by this weather" badges on board/bench/shop units.
 * Driven by state.depth.climate; play.js calls PlayWeather.render(ctx) after each render. */
(() => {
  "use strict";
  let ctx = null;
  let open = false;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const climate = () => ctx?.state?.depth?.climate || null;
  const now = () => climate()?.forecast?.[0] || null;

  function chip(cl) {
    const label = $("weather-label");
    if (!label) return;
    const pill = label.closest(".weather-pill");
    if (!cl) {
      pill?.classList.remove("wx-live");
      return;
    }
    const cur = cl.forecast[0];
    const shift = cur.shift ? ` → ${cur.shift.glyph}${cur.shift.name}` : "";
    label.textContent = `${cur.glyph} ${cur.name}${shift}`;
    if (pill) {
      pill.className = pill.className.replace(/\bwx-\S+/g, "").trim() + ` wx-live wx-${cur.id}`;
      pill.setAttribute("role", "button");
      pill.setAttribute("tabindex", "0");
      pill.setAttribute("aria-haspopup", "dialog");
      pill.setAttribute("aria-expanded", open ? "true" : "false");
      pill.dataset.weatherToggle = "1";
      pill.title = `本轮天气：${cur.name}${cur.boost.length ? ` · ${cur.boost.join("、")}系强化` : ""}（点击查看预报）`;
      const svg = pill.querySelector("svg");
      if (svg) svg.style.display = "none";
    }
  }

  function overlay(cl) {
    const field = $("battlefield");
    if (!field) return;
    let layer = field.querySelector(":scope > .field-weather");
    const cur = cl?.forecast?.[0];
    const show = cur && cur.id !== "calm" && ctx?.state?.phase !== "over";
    if (!show) {
      if (layer) layer.hidden = true;
      return;
    }
    if (!layer) {
      layer = document.createElement("div");
      layer.className = "field-weather";
      layer.setAttribute("aria-hidden", "true");
      layer.innerHTML = "<i></i><i></i><i></i>";
      field.prepend(layer);
    }
    layer.hidden = false;
    const cls = `field-weather fw-${cur.id}`;
    if (layer.className !== cls) layer.className = cls;
  }

  function mark(el, row) {
    el.classList.toggle("wx-boost", !!row?.boost);
    el.classList.toggle("wx-weak", !!row?.weak && !row?.boost);
    if (row && (row.boost || row.weak)) el.dataset.wx = row.boost ? now()?.glyph || "▲" : "▼";
    else delete el.dataset.wx;
  }

  function badges(cl) {
    const units = new Map((cl?.favoured || []).map((r) => [r.uid, r]));
    document.querySelectorAll("[data-uid].wx-boost, [data-uid].wx-weak").forEach((el) => { if (!units.has(el.dataset.uid)) mark(el, null); });
    for (const [uid, row] of units) document.querySelectorAll(`[data-uid="${CSS.escape(uid)}"]`).forEach((el) => mark(el, row));
    const shop = new Map((cl?.shop || []).map((r) => [String(r.slot), r]));
    document.querySelectorAll("#shop [data-shop]").forEach((el) => mark(el, shop.get(el.dataset.shop) || null));
  }

  function card(row, current) {
    const rules = (row.lines || []).map((x) => `<li>${esc(x)}</li>`).join("");
    const types = row.boost?.length ? `<span class="wx-types">强化：${row.boost.map(esc).join("、")}${row.weak?.length ? ` · 削弱：${row.weak.map(esc).join("、")}` : ""}</span>` : "";
    const shift = row.shift ? `<p class="wx-shift">第 ${Number(row.shift.at)} 秒转为 <b>${esc(row.shift.glyph)} ${esc(row.shift.name)}</b>：${esc(row.shift.lines?.[0] || "")}</p>` : "";
    return `<article class="wx-card wx-${esc(row.id)}${current ? " current" : ""}">
      <header><span class="wx-glyph" aria-hidden="true">${esc(row.glyph)}</span><b>${esc(row.name)}</b><small>${current ? "本轮" : `第 ${Number(row.round)} 轮`}${row.swapped ? " · 已祈天" : ""}</small></header>
      ${types}${current || row.id !== "calm" ? `<ul>${rules}</ul>` : ""}${shift}
    </article>`;
  }

  function popover() {
    const cl = climate();
    let box = $("weather-pop");
    if (!open || !cl) {
      if (box) box.hidden = true;
      return;
    }
    const pill = $("weather-label")?.closest(".weather-pill");
    if (!box) {
      box = document.createElement("section");
      box.id = "weather-pop";
      box.className = "weather-pop";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-label", "天气预报");
      document.body.appendChild(box);
    }
    const swap = cl.swap || {};
    const prep = ctx?.canPrep?.();
    const gold = Number(ctx?.state?.you?.gold) || 0;
    const swapHtml = !swap.available ? "" : swap.used
      ? `<p class="wx-swap-note">已祈天：本轮你的战斗改为 ${esc(swap.to.glyph)} ${esc(swap.to.name)}。</p>`
      : `<div class="wx-swap"><div><b>祈天</b><span>本轮你的战斗改为 ${esc(swap.to.glyph)} ${esc(swap.to.name)}（${esc(swap.to.boost?.length ? swap.to.boost.join("、") + "系强化" : swap.to.lines?.[0] || "")}），不受转天气影响。</span></div><button type="button" class="primary-button" data-weather-swap ${prep && gold >= swap.cost ? "" : "disabled"}>${Number(swap.cost)} 金 · 祈天</button></div>`;
    box.innerHTML = `<header><h3>天气预报</h3><button type="button" class="wx-close" data-weather-close aria-label="关闭">×</button></header>
      <p class="wx-note">双方共享同一天气；求雨 / 晴天技能机可临时覆盖，结束后恢复本轮天气。</p>
      <div class="wx-cards">${cl.forecast.map((row, i) => card(row, i === 0)).join("")}</div>${swapHtml}`;
    box.hidden = false;
    // Anchor next to the chip that opened it (fits within the viewport).
    const r = pill?.getBoundingClientRect();
    const w = Math.min(380, window.innerWidth - 16);
    box.style.width = `${w}px`;
    if (r) {
      box.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - w - 8))}px`;
      box.style.top = `${Math.min(r.bottom + 8, window.innerHeight - 120)}px`;
    }
    box.style.maxHeight = `${Math.max(200, window.innerHeight - (r ? r.bottom + 16 : 16))}px`;
  }

  function setOpen(value) {
    open = value;
    $("weather-label")?.closest(".weather-pill")?.setAttribute("aria-expanded", open ? "true" : "false");
    popover();
  }

  document.addEventListener("click", async (event) => {
    const t = event.target;
    if (t?.closest?.("[data-weather-toggle]")) {
      if (!climate()) return;
      event.preventDefault();
      setOpen(!open);
      return;
    }
    if (t?.closest?.("[data-weather-close]")) { setOpen(false); return; }
    const swap = t?.closest?.("[data-weather-swap]");
    if (swap && !swap.disabled && ctx) {
      swap.disabled = true;
      await ctx.api("climate_swap", {});
      return;
    }
    if (open && !t?.closest?.("#weather-pop")) setOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && open) setOpen(false);
    if ((event.key === "Enter" || event.key === " ") && event.target?.dataset?.weatherToggle && climate()) {
      event.preventDefault();
      setOpen(!open);
    }
  });
  window.addEventListener("resize", () => { if (open) popover(); });

  function render(context) {
    ctx = context;
    const cl = climate();
    chip(cl);
    overlay(cl);
    badges(cl);
    if (open) popover();
  }
  window.PlayWeather = {render, isOpen: () => open, close: () => setOpen(false)};
})();
