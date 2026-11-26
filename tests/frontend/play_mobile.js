/* Installed-app layer (docs/72): play_mobile.js, play_sw.js and the renderer's
 * battle cues, run against small fakes of the browser APIs they touch.
 * usage: node play_mobile.js <tools/acceptance dir> <scenario> */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const [dir, scenario] = process.argv.slice(2);
const read = (name) => fs.readFileSync(path.join(dir, name), 'utf8');
const tick = () => new Promise((resolve) => setImmediate(resolve));
const plain = (value) => JSON.parse(JSON.stringify(value));  // values from the vm realm

// ------------------------------------------------------------------ fake DOM
function classList() {
  const set = new Set();
  return {add: (c) => set.add(c), remove: (c) => set.delete(c), contains: (c) => set.has(c),
    toggle: (c, on) => { const want = on === undefined ? !set.has(c) : !!on; if (want) set.add(c); else set.delete(c); return want; }};
}
const observers = [];
class El {
  constructor(id) { this.id = id; this.attrs = {}; this.hidden = false; this.classList = classList(); this.dataset = {}; this.children = []; }
  setAttribute(k, v) { this.attrs[k] = String(v); observers.forEach((o) => o.notify(this, k)); }
  removeAttribute(k) { delete this.attrs[k]; observers.forEach((o) => o.notify(this, k)); }
  hasAttribute(k) { return k in this.attrs; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  closest(sel) { return sel === `#${this.id}` || (sel.startsWith('[') && this.attrs[sel.slice(1, -1)] !== undefined) ? this : null; }
  append(child) { this.children.push(child); elements[child.id] = child; }
  remove() { delete elements[this.id]; }
}
let elements = {};

function mobileEnv({secure = true, vibrate = true, wakeLock = true, mode = 'browser', shell = false, globals = {}} = {}) {
  observers.length = 0;
  elements = Object.fromEntries(['vibrate-button', 'install-button', 'battle-dialog'].map((id) => [id, new El(id)]));
  elements['vibrate-button'].hidden = true;
  elements['install-button'].hidden = true;
  const windowListeners = {}, documentListeners = {};
  const on = (bag) => (type, fn) => { (bag[type] ||= []).push(fn); };
  const storage = new Map();
  const log = {vibrate: [], wakeRequests: 0, released: 0, registered: [], prompts: 0, posted: []};
  let now = 1000;
  const sentinels = [];
  const navigator = {
    serviceWorker: {controller: null, ready: Promise.resolve(),
      addEventListener() {},
      register: async (url, options) => { log.registered.push(plain([url, options]));
        return {active: {postMessage: (m) => log.posted.push(m)}, update: async () => {}}; }},
  };
  if (vibrate) navigator.vibrate = (pattern) => { log.vibrate.push(plain(pattern)); return true; };
  if (wakeLock) navigator.wakeLock = {request: async (kind) => {
    assert.equal(kind, 'screen');
    log.wakeRequests += 1;
    const listeners = [];
    const sentinel = {addEventListener: (t, fn) => listeners.push(fn),
      release: async () => { log.released += 1; listeners.forEach((fn) => fn()); },
      drop: () => listeners.forEach((fn) => fn())};  // the OS releasing it (tab hidden)
    sentinels.push(sentinel);
    return sentinel;
  }};
  const document = {
    readyState: 'complete', hidden: false,
    documentElement: {classList: classList(), dataset: {}},
    body: new El('body'),
    getElementById: (id) => elements[id] || null,
    createElement: (tag) => new El(tag),
    addEventListener: on(documentListeners),
  };
  document.body.append = (child) => { elements[child.id] = child; };
  const window = {
    isSecureContext: secure, localStorage: {getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, String(v))},
    matchMedia: (q) => ({matches: q === `(display-mode: ${mode})` || q === '(orientation: portrait)', addEventListener() {}}),
    addEventListener: on(windowListeners), removeEventListener: (type, fn) => {
      windowListeners[type] = (windowListeners[type] || []).filter((f) => f !== fn); },
    scrollTo() {},
  };
  log.native = [];
  log.unlocks = 0;
  // Android shell App (docs/73): WebMessageListener object + autoplay-capable WebView.
  if (shell) window.PokeTacticsNative = {postMessage: (message) => log.native.push(JSON.parse(message))};
  window.PlayMusic = {unlock: () => { log.unlocks += 1; return true; }};
  class MutationObserver {
    constructor(fn) { this.fn = fn; }
    observe(target, opts) { observers.push({notify: (el, attr) => {
      if (el === target && opts.attributeFilter.includes(attr)) this.fn([{attributeName: attr}]); }}); }
  }
  const context = {window, document, navigator, MutationObserver, performance: {now: () => now}, location: {reload() {}},
    setTimeout, console, CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
    ...globals};
  window.window = window;
  vm.createContext(context);
  vm.runInContext(read('play_mobile.js'), context);
  const api = window.PlayMobile;
  const fireWindow = (type, event = {}) => (windowListeners[type] || []).forEach((fn) => fn({type, ...event}));
  const click = (el) => (documentListeners.click || []).forEach((fn) => fn({target: el}));
  return {api, log, window, document, elements, storage, fireWindow, click, sentinels,
    advance: (ms) => { now += ms; }, documentListeners};
}

// ------------------------------------------------------------------ fake service worker scope
function swEnv(config = {version: 'v2', media: 'm1', precache: ['/play/assets/play.js', '/play/icons/icon-192.png']}) {
  const source = read('play_sw.js').replace(/\/\*__PT_CONFIG__\*\/.*?\/\*__PT_CONFIG_END__\*\//s,
    () => JSON.stringify(config));
  const handlers = {};
  const stores = new Map();
  const log = {fetches: [], deleted: [], skipped: false, claimed: false};
  const keyOf = (request) => typeof request === 'string' ? request : request.url;
  const cacheFor = (name) => {
    if (!stores.has(name)) {
      const map = new Map();
      stores.set(name, {map,
        match: async (r) => map.get(new URL(keyOf(r), 'https://phone.test').pathname + (new URL(keyOf(r), 'https://phone.test').search)),
        put: async (r, res) => { map.set(new URL(keyOf(r), 'https://phone.test').pathname, res); },
        add: async (r) => { const res = await self.fetch(r); map.set(new URL(keyOf(r), 'https://phone.test').pathname, res); }});
    }
    return stores.get(name);
  };
  let offline = false, pageVersion = null;
  const self = {
    location: {origin: 'https://phone.test'},
    addEventListener: (type, fn) => { handlers[type] = fn; },
    skipWaiting: async () => { log.skipped = true; },
    clients: {claim: async () => { log.claimed = true; }},
    fetch: async (request) => {
      const url = keyOf(request);
      log.fetches.push(url);
      if (offline) throw new TypeError('offline');
      const headers = {get: (name) => name === 'X-PT-Shell-Version' && url.includes('/play?') || url.endsWith('/play')
        ? pageVersion : null};
      return {ok: true, type: 'basic', url, headers, clone() { return this; }};
    },
  };
  const caches = {open: async (name) => cacheFor(name), keys: async () => [...stores.keys()],
    delete: async (name) => { log.deleted.push(name); return stores.delete(name); },
    match: async (r, opts) => cacheFor(opts.cacheName).match(r)};
  class Request { constructor(url, init) { this.url = url; this.init = init; } }
  const context = {self, caches, Request, URL, fetch: (r) => self.fetch(r), console, Promise};
  vm.createContext(context);
  vm.runInContext(source, context);
  const run = async (type, event) => {
    let waited = null, responded = null;
    handlers[type]({...event, waitUntil: (p) => { waited = p; }, respondWith: (p) => { responded = p; }});
    if (waited) await waited;
    return responded;
  };
  const request = (url, extra = {}) => ({request: {url: new URL(url, 'https://phone.test').href, method: 'GET', mode: 'cors', ...extra}});
  return {run, request, log, stores, cacheFor, setOffline: (v) => { offline = v; },
    setPageVersion: (v) => { pageVersion = v; }, config};
}

const scenarios = {
  async vibration() {
    const env = mobileEnv();
    assert.equal(env.elements['vibrate-button'].hidden, false, 'phones with vibration show the switch');
    assert.equal(env.elements['vibrate-button'].attrs['aria-pressed'], 'true', 'on by default');
    env.fireWindow('battle:cue', {detail: {kind: 'ult', team: 0}});
    assert.deepEqual(env.log.vibrate, [[40, 30, 70]], 'own signature move: strong pattern');
    env.fireWindow('battle:cue', {detail: {kind: 'super', team: 1}});
    assert.equal(env.log.vibrate.length, 1, 'a burst inside 160ms is one buzz');
    env.advance(200);
    env.fireWindow('battle:cue', {detail: {kind: 'ult', team: 1}});
    assert.deepEqual(env.log.vibrate.at(-1), [25, 40, 25], 'enemy signature move: lighter pattern');
    env.advance(200);
    env.fireWindow('battle:cue', {detail: {kind: 'super', team: 0}});
    assert.deepEqual(env.log.vibrate.at(-1), [28], 'super-effective hit: short tick');
    assert.equal(env.api.status.cues, 4);

    env.click(env.elements['vibrate-button']);
    assert.equal(env.storage.get('poketactics.vibrate'), 'off', 'switch persists');
    assert.equal(env.elements['vibrate-button'].attrs['aria-pressed'], 'false');
    assert.ok(env.elements['vibrate-button'].classList.contains('muted'));
    const before = env.log.vibrate.length;
    env.advance(500);
    env.fireWindow('battle:cue', {detail: {kind: 'ult', team: 0}});
    assert.equal(env.log.vibrate.length, before, 'switched off: no buzz');
    assert.equal(env.api.vibrationEnabled(), false);
    env.click(env.elements['vibrate-button']);
    assert.equal(env.log.vibrate.length, before + 1, 'switching back on gives one confirmation buzz');

    env.document.hidden = true;
    env.advance(500);
    env.fireWindow('battle:cue', {detail: {kind: 'super', team: 0}});
    assert.equal(env.log.vibrate.length, before + 1, 'no buzz while the app is in the background');

    const silent = mobileEnv({vibrate: false});
    assert.equal(silent.elements['vibrate-button'].hidden, true, 'no switch without navigator.vibrate (iOS)');
    silent.fireWindow('battle:cue', {detail: {kind: 'ult', team: 0}});
  },

  async shellBack() {
    // A tiny page: one drawer closed by an Escape handler, modal dialogs, and the
    // battle dialog (a game phase the back key must never close).
    const mutations = [];
    class ShellObserver {
      observe(target, opts) {
        if (target?.id === 'battle-dialog') return;  // watchBattle()'s own observer
        assert.ok(opts.subtree && opts.attributes && opts.childList, 'watches the whole page');
        this.on = true;
      }
      takeRecords() { return this.on ? mutations.splice(0) : []; }
      disconnect() { this.on = false; }
    }
    class Event { constructor(type, init = {}) { this.type = type; this.cancelable = !!init.cancelable; this.defaultPrevented = false; }
      preventDefault() { if (this.cancelable) this.defaultPrevented = true; } }
    class KeyboardEvent extends Event { constructor(type, init) { super(type, init); this.key = init.key; this.code = init.code; } }
    const env = mobileEnv({shell: true, globals: {MutationObserver: ShellObserver, Event, KeyboardEvent}});
    const doc = env.document;
    let drawerOpen = false, keys = 0;
    doc.body.dispatchEvent = (event) => {
      keys += 1;
      assert.equal(event.key, 'Escape');
      for (const fn of env.documentListeners.keydown || []) fn(event);
      return !event.defaultPrevented;
    };
    // The page's own Escape handler (like play_layout.js closing the phone drawer).
    doc.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && drawerOpen) { drawerOpen = false; mutations.push({attributeName: 'class'}); }
    });
    const dialogs = [];
    const dialog = (id, onCancel) => {
      const d = {id, open: false, cancels: 0, dispatchEvent(event) { this.cancels += 1; onCancel?.(event, this); },
        close() { this.open = false; }};
      dialogs.push(d);
      return d;
    };
    doc.querySelectorAll = (sel) => { assert.equal(sel, 'dialog[open]'); return dialogs.filter((d) => d.open); };
    const help = dialog('help-dialog');
    const scout = dialog('scout-dialog', (event, d) => { event.preventDefault(); d.open = false; });
    const battle = dialog('battle-dialog', () => assert.fail('back must not cancel the battle dialog'));
    const shellApi = env.window.PokeTacticsShell;
    assert.equal(typeof shellApi.onBack, 'function', 'hook installed for the shell');
    assert.equal(env.document.documentElement.classList.contains('in-shell'), true);

    assert.equal(shellApi.onBack(), false, 'nothing open: the shell asks to exit');
    drawerOpen = true;
    assert.equal(shellApi.onBack(), true, 'an open drawer closes first');
    assert.equal(drawerOpen, false);
    assert.equal(shellApi.onBack(), false, 'then nothing is left');
    help.open = true;
    assert.equal(shellApi.onBack(), true, 'a modal dialog closes');
    assert.equal(help.open, false);
    assert.equal(help.cancels, 1, 'through its cancel event');
    scout.open = true;
    assert.equal(shellApi.onBack(), true);
    assert.equal(scout.open, false, 'a dialog with its own cancel handler closes through it');
    battle.open = true;
    assert.equal(shellApi.onBack(), false, 'the battle dialog is a game phase: ask to exit instead');
    assert.equal(battle.open, true);
    help.open = true;
    assert.equal(shellApi.onBack(), true, 'an overlay above the battle still closes');
    assert.equal(help.open, false);
    assert.equal(battle.open, true);
    drawerOpen = true;
    assert.equal(shellApi.onBack(), true, 'Escape-closed overlays come before dialogs');
    assert.equal(shellApi.status.backs, 8);
    assert.equal(shellApi.status.closed, 5);
    assert.equal(keys, 8, 'every back tries the page\'s Escape handlers once');

    // Vibration goes to the native bridge, never navigator.vibrate.
    env.fireWindow('battle:cue', {detail: {kind: 'ult', team: 0}});
    assert.deepEqual(env.log.native, [{type: 'vibrate', pattern: [40, 30, 70]}]);
    assert.deepEqual(env.log.vibrate, []);
    assert.equal(env.elements['vibrate-button'].hidden, false, 'switch shown in the shell');
    // Audio starts at boot, no tap needed.
    assert.equal(env.log.unlocks, 1);
    assert.equal(env.elements['install-button'].hidden, true);

    const browser = mobileEnv();
    assert.equal(browser.log.unlocks, 0, 'browsers still wait for the first tap');
    assert.equal(browser.document.documentElement.classList.contains('in-shell'), false);
    browser.fireWindow('battle:cue', {detail: {kind: 'ult', team: 0}});
    assert.deepEqual(browser.log.vibrate, [[40, 30, 70]], 'browsers keep navigator.vibrate');
    assert.deepEqual(browser.log.native, []);
  },

  async wakeLock() {
    const env = mobileEnv();
    const dialog = env.elements['battle-dialog'];
    assert.equal(env.log.wakeRequests, 0, 'no lock while preparing');
    dialog.setAttribute('open', '');
    await tick();
    assert.equal(env.log.wakeRequests, 1, 'battle opens: screen lock requested');
    assert.equal(env.api.wakeLockHeld(), true);
    assert.equal(env.api.status.wakeLock, true);
    // The OS drops the lock when the app goes to the background; coming back re-acquires it.
    env.sentinels[0].drop();
    assert.equal(env.api.wakeLockHeld(), false);
    env.document.hidden = false;
    for (const fn of env.documentListeners.visibilitychange || []) fn();
    await tick();
    assert.equal(env.log.wakeRequests, 2, 're-acquired after returning to the battle');
    dialog.removeAttribute('open');
    await tick();
    assert.equal(env.log.released, 1, 'battle closes: lock released');
    assert.equal(env.api.wakeLockHeld(), false);
    for (const fn of env.documentListeners.visibilitychange || []) fn();
    await tick();
    assert.equal(env.log.wakeRequests, 2, 'no lock outside battles');

    const none = mobileEnv({wakeLock: false});
    none.elements['battle-dialog'].setAttribute('open', '');
    await tick();
    assert.equal(none.api.wakeLockHeld(), false, 'browsers without the API simply skip it');
  },

  async install() {
    const env = mobileEnv();
    await tick();
    assert.deepEqual(env.log.registered, [['/play/sw.js', {scope: '/play'}]], 'secure page registers the worker');
    assert.equal(env.api.status.sw, 'active');
    assert.deepEqual(env.log.posted, ['version'], 'asks the worker for its version');
    assert.equal(env.elements['install-button'].hidden, true, 'no install button before Chrome offers it');
    let prevented = false, prompted = 0;
    env.fireWindow('beforeinstallprompt', {preventDefault: () => { prevented = true; },
      prompt: async () => { prompted += 1; }, userChoice: Promise.resolve({outcome: 'accepted'})});
    assert.ok(prevented, 'the mini-infobar is replaced by our own button');
    assert.equal(env.elements['install-button'].hidden, false);
    env.click(env.elements['install-button']);
    await tick();
    assert.equal(prompted, 1, 'tapping the button shows Chrome\'s install dialog');
    assert.equal(env.elements['install-button'].hidden, true, 'one prompt per event');
    env.fireWindow('appinstalled');
    assert.equal(env.api.status.installed, true);

    const insecure = mobileEnv({secure: false});
    await tick();
    assert.deepEqual(insecure.log.registered, [], 'plain http on a LAN address cannot use a worker');
    assert.equal(insecure.api.status.sw, 'insecure-context');

    const app = mobileEnv({mode: 'fullscreen'});
    assert.equal(app.api.displayMode(), 'fullscreen');
    assert.ok(app.document.documentElement.classList.contains('app-installed'), 'CSS hook for the installed app');
    app.fireWindow('beforeinstallprompt', {preventDefault() {}, prompt: async () => {}, userChoice: Promise.resolve({})});
    assert.equal(app.elements['install-button'].hidden, true, 'never offer to install from inside the app');
  },

  async serviceWorkerRoutes() {
    const sw = swEnv();
    const respond = async (url, extra) => sw.run('fetch', sw.request(url, extra));
    assert.equal(await respond('/api/demo/action?cmd=state'), null, 'game API stays on the network');
    assert.equal(await respond('/api/battle/script?sid=x&round=1'), null, 'battle scripts are not cached');
    assert.equal(await respond('/api/demo/backup?sid=x'), null, 'backups are not cached');
    assert.equal(await respond('/play/assets/play.js', {method: 'POST'}), null, 'only GET');
    assert.equal(await respond('https://elsewhere.test/play/assets/play.js'), null, 'only same origin');
    assert.equal(await respond('/play/sw.js'), null, 'the worker script itself is never cached');
    assert.equal(await respond('/pokedex', {mode: 'navigate'}), null, 'other pages are left alone');

    sw.log.fetches.length = 0;
    const first = await respond('/play/assets/play.js');
    assert.ok(first, 'static asset answered by the worker');
    await first;
    await respond('/play/assets/play.js').then((p) => p);
    assert.equal(sw.log.fetches.filter((u) => u.endsWith('/play/assets/play.js')).length, 1, 'second load comes from the cache');
    await (await respond('/pmd/0025.png'));
    assert.ok(sw.stores.get('pt-media-m1').map.has('/pmd/0025.png'), 'sprite atlases go to the media cache');
    await (await respond('/demo/sprite/25.png'));
    assert.ok(sw.stores.get('pt-shell-v2').map.has('/demo/sprite/25.png'), 'small sprites follow the code version');
    assert.equal(await respond('/pmd/index.json'), null, 'the sprite index is not pinned');
  },

  async serviceWorkerLifecycle() {
    const sw = swEnv();
    await sw.cacheFor('pt-shell-old');
    await sw.cacheFor('pt-media-m0');
    await sw.cacheFor('someone-else');
    await sw.run('install', {});
    assert.ok(sw.log.skipped, 'a new version takes over without waiting for every tab to close');
    const shell = sw.stores.get('pt-shell-v2').map;
    for (const url of ['/play', '/play/assets/play.js', '/play/icons/icon-192.png']) assert.ok(shell.has(url), `precached ${url}`);
    await sw.run('activate', {});
    assert.deepEqual([...sw.stores.keys()].sort(), ['pt-media-m1', 'pt-shell-v2', 'someone-else'].sort().filter((k) => sw.stores.has(k)));
    assert.ok(sw.log.deleted.includes('pt-shell-old') && sw.log.deleted.includes('pt-media-m0'), 'old versions are dropped');
    assert.ok(!sw.log.deleted.includes('someone-else'), 'foreign caches are left alone');
    assert.ok(sw.log.claimed);

    // Navigations: network first, cached shell when the dev machine is unreachable.
    const page = await sw.run('fetch', sw.request('/play', {mode: 'navigate'}));
    assert.ok((await page).ok);
    sw.setOffline(true);
    const offline = await (await sw.run('fetch', sw.request('/play?source=pwa', {mode: 'navigate'})));
    assert.ok(offline && offline.url.endsWith('/play'), 'offline launch opens the cached shell');
  },

  async serviceWorkerHandoff() {
    // A deploy: the page now says shell v3 while this (old) worker caches v2.
    const sw = swEnv();
    await sw.run('install', {});
    await sw.run('activate', {});
    sw.setPageVersion('v2');
    await (await sw.run('fetch', sw.request('/play', {mode: 'navigate'})));
    sw.log.fetches.length = 0;
    await (await sw.run('fetch', sw.request('/play/assets/play.js')));
    assert.deepEqual(sw.log.fetches, [], 'same version: shell files from the cache');
    sw.setPageVersion('v3');
    await (await sw.run('fetch', sw.request('/play?source=pwa', {mode: 'navigate'})));
    sw.log.fetches.length = 0;
    await (await sw.run('fetch', sw.request('/play/assets/play.js')));
    assert.equal(sw.log.fetches.length, 1, 'newer page: an old worker fetches shell files from the network');
    await (await sw.run('fetch', sw.request('/pmd/0025.png')));
    await (await sw.run('fetch', sw.request('/pmd/0025.png')));
    assert.equal(sw.log.fetches.filter((u) => u.endsWith('/pmd/0025.png')).length, 1, 'sprite atlases still cached');
  },

  async battleCues() {
    const R = require(path.resolve(dir, 'battle_renderer.js'));
    const events = [];
    global.window = {dispatchEvent: (event) => events.push(event.detail)};
    global.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init.detail; } };
    try {
      const plan = {duration: 10, warp: null, units: {0: {team: 0}, 1: {team: 1}},
        actions: [{ult: true, impact: 2, actor: 0, skill: {name: '火焰旋涡'}}, {ult: false, impact: 2.5, actor: 1},
                  {ult: true, impact: 6, actor: 1, skill: {name: '水炮'}}],
        numbers: [{kind: 'super', t: 3, unit: 1}, {kind: 'damage', t: 3.2, unit: 0}]};
      const emit = (a, b) => R.BattleRenderer.prototype._emitCues.call({plan}, a, b);
      emit(0, 1.9);
      assert.deepEqual(events, [], 'nothing before the first impact');
      emit(1.9, 2.1);
      assert.deepEqual(events, [{kind: 'ult', team: 0, name: '火焰旋涡'}], 'signature move cue at its impact');
      emit(2.1, 3.1);
      assert.deepEqual(events.at(-1), {kind: 'super', team: 1}, 'super-effective hit cue');
      const count = events.length;
      emit(3.1, 3.1);
      emit(5, 3);
      emit(3.1, 9);
      assert.equal(events.length, count, 'pauses, rewinds and seeks stay silent');
      emit(null, 6.5);
      assert.equal(events.length, count, 'the first frame after opening is silent');
      emit(5.8, 6.2);
      assert.deepEqual(events.at(-1), {kind: 'ult', team: 1, name: '水炮'});
    } finally {
      delete global.window;
      delete global.CustomEvent;
    }
  },
};

if (!scenarios[scenario]) {
  console.error(`unknown scenario ${scenario}; known: ${Object.keys(scenarios).join(', ')}`);
  process.exit(2);
}
scenarios[scenario]().then(() => console.log(`ok ${scenario}`), (error) => { console.error(error); process.exit(1); });
