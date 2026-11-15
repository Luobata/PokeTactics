// Node check for tools/acceptance/play_feedback.js: every action leaves a visible trace.
// Minimal DOM stub: elements report a fixed rect, the layer collects effects.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function element(tag = "div", id = null) {
  const el = {
    tagName: tag.toUpperCase(), id, children: [], className: "", textContent: "", innerHTML: "", isConnected: true,
    style: {}, attrs: {},
    classList: {
      set: new Set(),
      add(...c) { c.forEach((x) => this.set.add(x)); }, remove(...c) { c.forEach((x) => this.set.delete(x)); },
      contains(c) { return this.set.has(c); },
    },
    append(child) { this.children.push(child); child.parent = this; },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); },
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; },
    getBoundingClientRect() { return {left: 100, top: 100, width: 40, height: 40}; },
    closest() { return this; }, get offsetWidth() { return 40; },
    animate() { return {finished: Promise.resolve()}; },
  };
  return el;
}

function load() {
  const registry = new Map();
  const byId = new Map();
  const body = element("body");
  const document = {
    body,
    createElement: (tag) => element(tag),
    getElementById: (id) => byId.get(id) || body.children.find((c) => c.id === id) || null,
    querySelector: (sel) => { for (const [key, el] of registry) if (sel.includes(key)) return el; return null; },
    querySelectorAll: () => [],
    addEventListener() {},
    activeElement: null,
  };
  for (const id of ["gold", "level", "xp-fill", "xp-text", "hud-order", "hud-sim", "lock-button", "ix-augment-strip", "toast"]) byId.set(id, element("div", id));
  const window = {CSS: {escape: (s) => String(s)}, PlaySound: {enabled: () => false}};
  const sandbox = {window, document, navigator: {}, setTimeout: (fn) => 0, requestAnimationFrame: () => 0,
                   performance: {now: () => 0}, matchMedia: () => ({matches: false}), CSS: window.CSS,
                   Element: function () {}, console};
  sandbox.Element.prototype = {animate() {}};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../tools/acceptance/play_feedback.js"), "utf8"), sandbox);
  return {fb: window.PlayFeedback, registry, byId, layer: () => byId.get("fb-layer") || body.children.find((c) => c.id === "fb-layer")};
}

function floats(env) {
  const layer = env.layer();
  return layer ? layer.children.filter((c) => String(c.className).includes("fb-float")).map((c) => c.textContent) : [];
}

const base = {you: {gold: 10, level: 2, pop: 4, shop_locked: false}, board: [[null], [null], [null]], bench: [],
              items: {finished: [], components: [], craftable: []}, techniques: [], augments: {selected: []}, depth: {order: "none"}};
const unit = (uid, extra = {}) => ({uid, sid: 25, name: "皮卡丘", star: 1, ...extra});

(async () => {
  // buy: a new unit and a gold decrease
  {
    const env = load();
    env.registry.set('data-uid="u1"', element());
    env.registry.set('data-shop="0"', element());
    const token = env.fb.before("buy", {i: 0}, base);
    env.fb.after(token, {ok: true}, {...base, you: {...base.you, gold: 9}, bench: [unit("u1")]});
    await new Promise((r) => setImmediate(r));
    const texts = floats(env);
    assert.ok(texts.includes("−1 金"), texts);
    assert.ok(texts.some((t) => t.includes("皮卡丘")), texts);
  }
  // equip: an item appears on a unit
  {
    const env = load();
    env.registry.set('data-uid="u1"', element());
    const prev = {...base, bench: [unit("u1")]};
    const token = env.fb.before("equip", {item: "choice_band"}, prev);
    env.fb.after(token, {ok: true}, {...base, bench: [unit("u1", {item: "choice_band", item_name: "专爱头巾"})]});
    await new Promise((r) => setImmediate(r));
    assert.ok(floats(env).some((t) => t.includes("专爱头巾")), floats(env));
  }
  // learn + core + level up
  {
    const env = load();
    env.registry.set('data-uid="u1"', element());
    const prev = {...base, board: [[unit("u1")], [null], [null]]};
    const token = env.fb.before("learn", {}, prev);
    env.fb.after(token, {ok: true}, {...base, you: {...base.you, level: 3, pop: 5},
      board: [[unit("u1", {technique: {id: "cut", name: "居合斩"}, is_core: true})], [null], [null]]});
    const texts = floats(env);
    assert.ok(texts.some((t) => t.includes("学会 居合斩")), texts);
    assert.ok(texts.some((t) => t.includes("核心")), texts);
    assert.ok(env.layer().children.some((c) => String(c.className).includes("fb-banner")), "level-up banner");
  }
  // an action with no visible state change still confirms on the clicked control
  {
    const env = load();
    const token = env.fb.before("simulate_noop", {}, base);
    token.clickRect = {x: 0, y: 0, w: 20, h: 20};
    token.click = element();
    env.fb.after(token, {ok: true}, base);
    assert.ok(floats(env).includes("✓"), floats(env));
  }
  // errors shake and never float success text
  {
    const env = load();
    const token = env.fb.before("buy", {i: 0}, base);
    token.click = element();
    env.fb.after(token, {ok: false, error: "金币不足"}, base);
    assert.deepStrictEqual(floats(env), []);
    assert.ok(token.click.classList.contains("fb-shake"));
  }
  // read-only commands are not intercepted
  assert.strictEqual(load().fb.before("state", {}, base), null);
  console.log("play_feedback: ok");
})().catch((error) => { console.error(error); process.exit(1); });
