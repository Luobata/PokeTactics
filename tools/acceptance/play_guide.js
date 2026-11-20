/* First-run guide (docs/70): five short coach marks that point at the real
 * controls — recruit, deploy, three-of-a-kind, items, start the battle.
 *
 * Starts once on the first prep screen without other overlays, can be skipped
 * at any step, and is remembered in localStorage (GUIDE_KEY). The "?" button in
 * the HUD (#guide-button) and the help dialog ([data-guide-start]) replay it.
 * The overlay never blocks the board: the ring is click-through, so the player
 * can do what the step says, and the first two steps advance by themselves
 * once it is done. Automation (navigator.webdriver) never auto-starts it;
 * ?guide=1 forces the auto-start, ?guide=0 disables it. */
(function () {
  "use strict";
  const GUIDE_KEY = "poketactics.play.guide";
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  const owned = (s) => [...(s?.board || []).flat(), ...(s?.bench || [])].filter(Boolean).length;
  const STEPS = [
    {title: "招募伙伴", targets: ["#shop .shop-card[data-shop]", '#stage-dock [data-open-panel="shop"]'],
      text: "点商店卡片查看它的技能和特性，双击卡片直接招募。金币每轮发放，存着还有利息。",
      done: (s, start) => owned(s) > start.owned},
    {title: "上场布阵", targets: ["#bench [data-owned]", "#bench"],
      text: "点备战席的精灵，再点棋盘格上场；双击精灵直接上到合适的位置，也可以拖动。再点一次取消选择。",
      done: (s, start) => Number(s?.you?.on_board) > start.onBoard},
    {title: "三合一升星", targets: ["#bench", "#ally-board"],
      text: "集齐 3 只相同的精灵会自动合成为更高一星，属性大幅提升。商店卡片出现「⇪」时，买下就能升星。"},
    {title: "装备道具", targets: ['#stage-dock [data-open-panel="bag"]'],
      text: "战斗结算会掉落组件，两个组件合成一件装备。右键（手机长按）精灵或装备，可以一键装给推荐的携带者。"},
    {title: "开始战斗", targets: ["#fight-button"],
      text: "阵容满意就开战（空格键）。鼠标悬停或手机长按精灵、装备、羁绊都能看到说明；点右上角「?」随时重看本引导。"},
  ];
  let ctx = null;
  let step = -1;
  let start = null;
  let ring = null;
  let bubble = null;
  let autoChecked = false;
  let frame = 0;

  const store = () => window.localStorage || localStorage;
  const read = () => { try { return store().getItem(GUIDE_KEY); } catch (_) { return "done"; } };
  const write = (value) => { try { store().setItem(GUIDE_KEY, value); } catch (_) { /* private mode */ } };
  function autoAllowed() {
    let forced = null;
    try { forced = new URLSearchParams(location.search).get("guide"); } catch (_) { /* no location */ }
    if (forced === "0") return false;
    if (forced === "1") return true;
    return !(typeof navigator !== "undefined" && navigator.webdriver);
  }
  function quiet() {
    const body = document.body;
    if (["ix-augment-open", "draft-open", "ix-sheet-open", "ctx-open"].some((name) => body.classList.contains(name))) return false;
    return !document.querySelector("dialog[open]");
  }
  function visible(el) {
    if (!el || el.hidden) return false;
    for (let node = el; node && node !== document.body; node = node.parentElement) if (node.hidden) return false;
    const box = el.getBoundingClientRect?.();
    if (!box || box.width <= 0 || box.height <= 0) return false;
    const vw = window.innerWidth || 1280, vh = window.innerHeight || 800;
    return box.bottom > 0 && box.right > 0 && box.top < vh && box.left < vw;
  }
  function find(selectors) {
    for (const selector of selectors) {
      let list = [];
      try { list = [...document.querySelectorAll(selector)]; } catch (_) { list = []; }
      const hit = list.find(visible);
      if (hit) return hit;
    }
    return null;
  }
  function ensure() {
    if (ring) return;
    ring = document.createElement("div");
    ring.className = "guide-ring";
    ring.setAttribute("aria-hidden", "true");
    bubble = document.createElement("div");
    bubble.className = "guide-bubble";
    bubble.id = "guide-bubble";
    bubble.setAttribute("role", "dialog");
    bubble.setAttribute("aria-labelledby", "guide-title");
    ring.hidden = bubble.hidden = true;
    document.body.append(ring);
    document.body.append(bubble);
    bubble.addEventListener("click", (event) => {
      const button = event.target?.closest?.("[data-guide]");
      if (!button) return;
      event.stopPropagation?.();
      const action = button.getAttribute("data-guide");
      if (action === "next") go(step + 1);
      else if (action === "prev") go(step - 1);
      else finish();
    });
  }
  function draw() {
    const s = STEPS[step];
    const last = step === STEPS.length - 1;
    bubble.innerHTML = `<span class="guide-count">新手引导 ${step + 1} / ${STEPS.length}</span><h3 id="guide-title">${esc(s.title)}</h3><p aria-live="polite">${esc(s.text)}</p><div class="guide-actions"><button type="button" class="guide-skip" data-guide="skip">${last ? "关闭" : "跳过引导"}</button>${step ? '<button type="button" data-guide="prev">上一步</button>' : ""}<button type="button" class="guide-next" data-guide="${last ? "done" : "next"}">${last ? "开始冒险" : "下一步"}</button></div>`;
  }
  function place() {
    frame = 0;
    if (step < 0 || !ring) return;
    const target = find(STEPS[step].targets);
    const vw = window.innerWidth || 1280, vh = window.innerHeight || 800;
    ring.hidden = !target;
    let box = null;
    if (target) {
      box = target.getBoundingClientRect();
      const pad = 6;
      ring.style.left = `${Math.round(box.left - pad)}px`;
      ring.style.top = `${Math.round(box.top - pad)}px`;
      ring.style.width = `${Math.round(box.width + pad * 2)}px`;
      ring.style.height = `${Math.round(box.height + pad * 2)}px`;
    }
    const w = bubble.offsetWidth || 300, h = bubble.offsetHeight || 150;
    let x = vw / 2 - w / 2, y = vh / 2 - h / 2;
    if (box) {
      const below = box.bottom + 14, above = box.top - h - 14;
      x = Math.max(8, Math.min(vw - w - 8, box.left + box.width / 2 - w / 2));
      if (below + h <= vh - 8) y = below;
      else if (above >= 8) y = above;
      else {
        // Tall target (e.g. the drawer): sit beside it.
        y = Math.max(8, Math.min(vh - h - 8, box.top));
        x = box.left - w - 14 >= 8 ? box.left - w - 14 : Math.min(vw - w - 8, box.right + 14);
      }
    }
    bubble.style.left = `${Math.round(x)}px`;
    bubble.style.top = `${Math.round(y)}px`;
  }
  const schedule = () => {
    if (step < 0 || frame) return;
    frame = typeof requestAnimationFrame === "function" ? requestAnimationFrame(place) : (place(), 0);
  };
  function go(index) {
    if (index >= STEPS.length) return finish();
    step = Math.max(0, index);
    start = {owned: owned(ctx?.state), onBoard: Number(ctx?.state?.you?.on_board) || 0};
    ensure();
    draw();
    ring.hidden = bubble.hidden = false;
    document.body.classList.add("guide-open");
    place();
    bubble.querySelector?.(".guide-next")?.focus?.({preventScroll: true});
  }
  function finish() {
    write("done");
    step = -1;
    if (ring) ring.hidden = bubble.hidden = true;
    document.body.classList.remove("guide-open");
  }
  function begin() {
    autoChecked = true;
    window.PlayContext?.close?.({restore: false});
    go(0);
  }

  document.addEventListener("click", (event) => {
    if (!event.target?.closest?.("#guide-button") && !event.target?.closest?.("[data-guide-start]")) return;
    const help = document.getElementById("help-dialog");
    if (help?.open && event.target.closest("[data-guide-start]")) help.close?.();
    begin();
  });
  document.addEventListener("keydown", (event) => {
    if (step < 0 || event.key !== "Escape") return;
    finish();
    event.stopImmediatePropagation?.();
  }, true);
  if (typeof window.addEventListener === "function") {
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
  }

  function render(context) {
    ctx = context;
    const s = context.state;
    if (step >= 0) {
      // Steps 1–2 advance by themselves once the player has done them.
      const current = STEPS[step];
      if (current.done && s && start && current.done(s, start)) go(step + 1);
      else schedule();
      return;
    }
    if (autoChecked || !s) return;
    if (read() === "done") { autoChecked = true; return; }
    if (s.phase !== "prep" || !context.playable?.() || !quiet()) return;
    autoChecked = true;
    if (!autoAllowed()) return;
    setTimeout(() => {
      if (step >= 0) return;
      if (quiet() && ctx?.playable?.()) go(0);
      else autoChecked = false;  // an overlay opened meanwhile: try again on a later render
    }, 600);
  }

  window.PlayGuide = {render, start: begin, finish, step: () => step, steps: STEPS, KEY: GUIDE_KEY};
})();
