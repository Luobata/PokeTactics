/* Themed dropdowns (docs/66). Every single-choice <select> on the page gets a
 * button + listbox popover (a bottom sheet on phones). The native <select>
 * stays in the DOM, hidden, and remains the source of truth: same id, same
 * value, and a real bubbling `change` event on every pick, so existing
 * handlers (onchange, delegated listeners) and tests keep working.
 *
 * Optional per-option decoration: data-chip="#hex" (colour chip, e.g. type
 * colours) and data-icon="glyph". Selects added later (re-rendered panels)
 * are picked up by a MutationObserver; programmatic `.value =` / option
 * changes update the button. Opt out with data-native on the select. */
(function () {
  "use strict";
  const PHONE = "(max-width: 760px), (max-height: 520px) and (orientation: landscape)";
  let seq = 0;
  let open = null;      // {select, button, list, backdrop, active, typed, typedAt}
  const doc = document;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const isPhone = () => Boolean(window.PlayLayout?.isPhone?.() ?? window.matchMedia?.(PHONE)?.matches);
  const chevron = '<svg class="ps-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';

  const optionsOf = (select) => [...(select.options || select.querySelectorAll("option"))];
  const optValue = (o) => o.value ?? o.getAttribute?.("value") ?? o.textContent;
  function currentIndex(select) {
    const options = optionsOf(select);
    const byValue = options.findIndex((o) => String(optValue(o)) === String(select.value));
    if (byValue >= 0 && select.value !== "") return byValue;
    const marked = options.findIndex((o) => o.selected || o.hasAttribute?.("selected"));
    return marked >= 0 ? marked : byValue >= 0 ? byValue : 0;
  }
  const deco = (o) => {
    const chip = o.getAttribute?.("data-chip");
    const icon = o.getAttribute?.("data-icon");
    return `${chip && /^#[0-9a-f]{3,8}$/i.test(chip) ? `<i class="ps-chip" style="background:${chip}"></i>` : ""}${icon ? `<b class="ps-icon" aria-hidden="true">${esc(icon)}</b>` : ""}`;
  };
  function labelOf(select) {
    const aria = select.getAttribute("aria-label");
    if (aria) return aria;
    const label = select.closest?.("label");
    // Only the label's own text (not the option texts or our button inside it).
    if (label) return [...(label.childNodes || label.children || [])]
      .filter((n) => n.nodeType === 3 || n.tagName === "#TEXT" || n.tagName === "SPAN")
      .map((n) => n.textContent).join("").trim();
    return "";
  }

  // ------------------------------------------------------------ button
  function sync(select) {
    const button = select.__psButton;
    if (!button) return;
    const options = optionsOf(select);
    const o = options[currentIndex(select)];
    const text = o ? o.textContent : "";
    const html = `${o ? deco(o) : ""}<span class="ps-value">${esc(text)}</span>${chevron}`;
    if (button.__html !== html) {
      button.innerHTML = html;
      button.__html = html;
    }
    button.disabled = Boolean(select.disabled) || !options.length;
    const label = labelOf(select);
    const aria = label ? `${label}：${text}` : text;
    if (button.getAttribute("aria-label") !== aria) button.setAttribute("aria-label", aria);
  }

  function watchValue(select) {
    // `select.value = x` does not fire any event: wrap the setters on this instance.
    const proto = Object.getPrototypeOf(select);
    for (const key of ["value", "selectedIndex", "disabled"]) {
      const desc = Object.getOwnPropertyDescriptor(proto, key)
        || Object.getOwnPropertyDescriptor(Object.getPrototypeOf(proto) || {}, key);
      if (!desc || !desc.set || !desc.get) continue;
      Object.defineProperty(select, key, {
        configurable: true,
        get() { return desc.get.call(this); },
        set(v) { desc.set.call(this, v); sync(this); },
      });
    }
    if (typeof MutationObserver === "function") {
      new MutationObserver(() => sync(select)).observe(select, {childList: true, subtree: true, attributes: true, characterData: true});
    }
  }

  function enhance(select) {
    if (!select || select.__psButton || select.multiple || Number(select.getAttribute("size")) > 1
        || select.hasAttribute("data-native")) return null;
    const id = select.id || `ps-select-${++seq}`;
    const button = doc.createElement("button");
    button.type = "button";
    button.setAttribute("type", "button");
    button.className = "ps-button";
    button.id = `${id}-ps`;
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("data-ps-for", id);
    select.__psButton = button;
    select.classList.add("ps-native");
    select.setAttribute("tabindex", "-1");
    select.setAttribute("aria-hidden", "true");
    select.insertAdjacentElement("afterend", button);
    button.onclick = (event) => {
      event?.preventDefault?.();
      if (open?.select === select) close(true);
      else show(select);
    };
    button.onkeydown = (event) => {
      if (["ArrowDown", "ArrowUp", "Enter", " ", "Spacebar"].includes(event.key)) {
        event.preventDefault?.();
        show(select);
      }
    };
    select.addEventListener("focus", () => button.focus?.());
    watchValue(select);
    sync(select);
    return button;
  }

  function enhanceAll(root = doc) {
    for (const select of root.querySelectorAll?.("select") || []) enhance(select);
  }

  // ------------------------------------------------------------ popover
  function show(select) {
    if (open) close(false);
    const button = select.__psButton;
    if (!button || button.disabled) return;
    const phone = isPhone();
    const list = doc.createElement("div");
    const listId = `${button.id}-list`;
    list.className = `ps-list${phone ? " ps-sheet" : ""}`;
    list.id = listId;
    list.setAttribute("role", "listbox");
    list.setAttribute("tabindex", "-1");
    const label = labelOf(select);
    if (label) list.setAttribute("aria-label", label);
    const options = optionsOf(select);
    const index = currentIndex(select);
    list.innerHTML = `${phone && label ? `<div class="ps-sheet-title">${esc(label)}</div>` : ""}${options.map((o, i) => `<div class="ps-option${i === index ? " selected" : ""}${o.disabled || o.hasAttribute?.("disabled") ? " disabled" : ""}" role="option" id="${listId}-${i}" data-ps-index="${i}" aria-selected="${i === index}"${o.disabled || o.hasAttribute?.("disabled") ? ' aria-disabled="true"' : ""}>${deco(o)}<span>${esc(o.textContent)}</span>${i === index ? '<em class="ps-check" aria-hidden="true">✓</em>' : ""}</div>`).join("")}`;
    // Modal dialogs live in the top layer: the popover must be inside the dialog to show above it.
    const host = select.closest?.("dialog[open]") || doc.body;
    let backdrop = null;
    if (phone) {
      backdrop = doc.createElement("div");
      backdrop.className = "ps-backdrop";
      host.append(backdrop);
    }
    host.append(list);
    open = {select, button, list, backdrop, active: index, typed: "", typedAt: 0};
    button.setAttribute("aria-expanded", "true");
    button.setAttribute("aria-controls", listId);
    button.classList.add("open");
    if (!phone) place();
    setActive(index, false);
    list.onclick = (event) => {
      const row = event.target?.closest?.("[data-ps-index]");
      if (row) choose(Number(row.getAttribute("data-ps-index")));
    };
    list.onkeydown = onKey;
    list.focus?.({preventScroll: true});
  }

  function place() {
    if (!open) return;
    const r = open.button.getBoundingClientRect();
    const list = open.list;
    const vh = window.innerHeight || 800;
    const below = vh - r.bottom - 8, above = r.top - 8;
    const height = Math.min(300, Math.max(below, above));
    list.style.minWidth = `${Math.round(r.width)}px`;
    list.style.left = `${Math.round(Math.max(8, Math.min(r.left, (window.innerWidth || 1200) - Math.max(r.width, 160) - 8)))}px`;
    list.style.maxHeight = `${Math.round(height)}px`;
    if (below >= Math.min(220, above) || below >= 180) {
      list.style.top = `${Math.round(r.bottom + 4)}px`;
      list.style.bottom = "";
    } else {
      list.style.top = "";
      list.style.bottom = `${Math.round(vh - r.top + 4)}px`;
    }
  }

  function setActive(i, scroll = true) {
    if (!open) return;
    const rows = open.list.querySelectorAll("[data-ps-index]");
    if (!rows.length) return;
    const n = rows.length;
    let next = Math.max(0, Math.min(n - 1, i));
    open.active = next;
    rows.forEach((row, k) => row.classList.toggle("active", k === next));
    open.list.setAttribute("aria-activedescendant", rows[next].id);
    if (scroll) rows[next].scrollIntoView?.({block: "nearest"});
  }

  function step(delta) {
    if (!open) return;
    const options = optionsOf(open.select);
    let i = open.active;
    for (let k = 0; k < options.length; k++) {
      i = Math.max(0, Math.min(options.length - 1, i + delta));
      if (!(options[i].disabled || options[i].hasAttribute?.("disabled"))) break;
    }
    setActive(i);
  }

  function typeahead(key) {
    const now = Date.now();
    open.typed = now - open.typedAt < 600 ? open.typed + key.toLowerCase() : key.toLowerCase();
    open.typedAt = now;
    const options = optionsOf(open.select);
    const start = open.typed.length === 1 ? open.active + 1 : open.active;
    for (let k = 0; k < options.length; k++) {
      const i = (start + k) % options.length;
      if (options[i].textContent.trim().toLowerCase().startsWith(open.typed)) return setActive(i);
    }
  }

  function onKey(event) {
    if (!open) return;
    const key = event.key;
    if (key === "ArrowDown" || key === "ArrowUp") { event.preventDefault?.(); step(key === "ArrowDown" ? 1 : -1); }
    else if (key === "Home" || key === "End") { event.preventDefault?.(); setActive(key === "Home" ? 0 : optionsOf(open.select).length - 1); }
    else if (key === "Enter" || key === " ") { event.preventDefault?.(); choose(open.active); }
    else if (key === "Escape") { event.preventDefault?.(); event.stopPropagation?.(); close(true); }
    else if (key === "Tab") close(false);
    else if (key && key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) typeahead(key);
  }

  function choose(i) {
    if (!open) return;
    const {select} = open;
    const options = optionsOf(select);
    const o = options[i];
    if (!o || o.disabled || o.hasAttribute?.("disabled")) return;
    const changed = String(select.value) !== String(optValue(o));
    select.value = optValue(o);
    close(true);
    sync(select);
    if (changed) fire(select, "change");
  }

  function fire(select, type) {
    let event;
    if (typeof Event === "function") event = new Event(type, {bubbles: true});
    else event = {type, bubbles: true, target: select};
    if (typeof select.dispatchEvent === "function") select.dispatchEvent(event);
  }

  function close(refocus) {
    if (!open) return;
    const {button, list, backdrop} = open;
    open = null;
    list.remove?.();
    backdrop?.remove?.();
    button.setAttribute("aria-expanded", "false");
    button.removeAttribute?.("aria-controls");
    button.classList.remove("open");
    if (refocus) button.focus?.();
  }

  // ------------------------------------------------------------ global wiring
  doc.addEventListener("pointerdown", (event) => {
    if (!open) return;
    const t = event.target;
    if (open.list.contains?.(t) || open.button.contains?.(t)) return;
    close(false);
  }, true);
  if (typeof window.addEventListener === "function") {
    window.addEventListener("resize", () => close(false));
    window.addEventListener("scroll", (event) => {
      if (open && !open.list.contains?.(event.target)) place();
    }, true);
  }
  if (typeof MutationObserver === "function") {
    let queued = false;
    const observer = new MutationObserver((records) => {
      if (queued) return;
      if (!records.some((r) => [...r.addedNodes].some((n) => n.nodeType === 1 && (n.tagName === "SELECT" || n.querySelector?.("select"))))) return;
      queued = true;
      queueMicrotask(() => { queued = false; enhanceAll(); });
    });
    const start = () => { enhanceAll(); observer.observe(doc.body, {childList: true, subtree: true}); };
    if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start);
    else start();
  } else {
    enhanceAll();
  }

  window.PlaySelect = {enhance, enhanceAll, sync, close, open: (select) => show(select), current: () => open};
})();
