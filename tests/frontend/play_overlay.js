/* Overlay stack (docs/74 §4): play_overlay.js closes exactly the topmost open layer
 * for the shell back key and Esc, respects modal dialogs, never closes the battle.
 * usage: node play_overlay.js <tools/acceptance dir> <scenario> */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const [dir, scenario] = process.argv.slice(2);

function makePage() {
  const listeners = {};
  const dialogs = [];
  const els = {};
  const element = (id, extra = {}) => (els[id] = {id, hidden: true, open: false, classList: new Set(),
    getClientRects() { return this.hidden ? [] : [{}]; }, ...extra});
  element('ix-augment');
  element('draft-sheet');
  element('scout-dialog', {classList: {set: new Set(), contains(c) { return this.set.has(c); }, add(c) { this.set.add(c); }}});
  const buttons = {'[data-ix-augment-later]': [], '[data-draft-later]': []};
  const document = {
    getElementById: (id) => els[id] || null,
    querySelectorAll(sel) {
      if (sel === 'dialog[open]') return dialogs.filter((d) => d.open);
      return buttons[sel] || [];
    },
  };
  const log = [];
  const mod = (name, open = false) => ({open, isOpen() { return this.open; }, close() { this.open = false; log.push(name); }});
  const window = {
    addEventListener(type, fn, capture) { (listeners[type] ||= []).push(fn); },
    PlayContext: mod('context-menu'),
    PlayPreview: {open: false, isOpen() { return this.open; }, hide() { this.open = false; log.push('term-card'); }},
    PlaySelect: {open: null, current() { return this.open; }, close() { this.open = null; log.push('select'); }},
    PlayGuide: {s: -1, step() { return this.s; }, finish() { this.s = -1; log.push('guide'); }},
    PlayInteractions: {sh: null, md: null, sheet() { return this.sh; }, mode() { return this.md; },
      dismiss() { if (this.sh) { this.sh = null; log.push('ix-sheet'); return true; } if (this.md) { this.md = null; log.push('target-mode'); return true; } return false; }},
    PlayTree: mod('tree'),
    PlayBranch: mod('branch'),
    PlayWeather: mod('weather'),
    PlayLayout: {cur: null, phone: true, current() { return this.cur; }, isPhone() { return this.phone; }, close() { this.cur = null; log.push('sheet'); }},
  };
  const dialog = (id) => {
    const d = {id, open: false, classList: {contains: () => false}, listeners: {},
      addEventListener(t, f) { (this.listeners[t] ||= []).push(f); },
      dispatchEvent(e) { for (const f of this.listeners[e.type] || []) f(e); return true; },
      close() { this.open = false; log.push(`dialog:${id}`); }};
    dialogs.push(d);
    return d;
  };
  class Event { constructor(type, init = {}) { this.type = type; this.cancelable = init.cancelable; this.defaultPrevented = false; } preventDefault() { this.defaultPrevented = true; } }
  const context = vm.createContext({window, document, Event, console});
  vm.runInContext(fs.readFileSync(path.join(dir, 'play_overlay.js'), 'utf8'), context);
  const O = window.PlayOverlay;
  let selection = null;
  O.render({selected: () => selection, shopSelected: () => null, equipItem: () => null,
    actions: {clear() { selection = null; log.push('selection'); }}});
  const esc = (target = {tagName: 'DIV'}) => {
    const event = {key: 'Escape', target, defaultPrevented: false, stopped: false,
      preventDefault() { this.defaultPrevented = true; }, stopImmediatePropagation() { this.stopped = true; }};
    for (const fn of listeners.keydown || []) fn(event);
    return event;
  };
  return {window, O, log, els, buttons, dialog, esc, select(v) { selection = v; }};
}

const scenarios = {
  orderTopFirst() {
    const p = makePage();
    p.select('g0,1');
    p.window.PlayLayout.cur = 'shop';
    p.window.PlayInteractions.md = {kind: 'item'};
    p.window.PlayPreview.open = true;
    p.window.PlayContext.open = true;
    assert.deepEqual([...p.O.stack()], ['context-menu', 'term-card', 'target-mode', 'sheet', 'selection']);
    const closed = [];
    let id;
    while ((id = p.O.closeTop('back'))) closed.push(id);
    assert.deepEqual(closed, ['context-menu', 'term-card', 'target-mode', 'sheet', 'selection']);
    assert.equal(p.O.closeTop('back'), null, 'nothing left: the shell asks to exit');
  },
  modalHidesWhatIsBelow() {
    const p = makePage();
    p.window.PlayLayout.cur = 'bag';
    p.select('b0');
    const help = p.dialog('help-dialog');
    help.open = true;
    p.window.PlayPreview.open = true; // a glossary card opened inside the help dialog
    assert.deepEqual([...p.O.stack()], ['term-card', 'dialog']);
    assert.equal(p.O.closeTop('back'), 'term-card');
    assert.equal(p.O.closeTop('back'), 'dialog');
    assert.equal(help.open, false);
    assert.equal(p.O.closeTop('back'), 'sheet', 'then the sheet that was under the dialog');
  },
  battleIsNeverClosedByBack() {
    const p = makePage();
    p.window.PlayLayout.cur = 'shop';
    const battle = p.dialog('battle-dialog');
    battle.open = true;
    let advanced = false;
    battle.addEventListener('cancel', (e) => { e.preventDefault(); advanced = true; });
    assert.equal(p.O.closeTop('back'), null, 'back on the battle closes nothing');
    assert.equal(p.O.status.last.top, 'phase-dialog');
    assert.equal(advanced, false);
    assert.equal(p.window.PlayLayout.cur, 'shop', 'the sheet under the battle stays');
    p.window.PlayGuide.s = 2; // the guide renders above the battle
    assert.equal(p.O.closeTop('back'), 'guide');
    // Esc on the battle falls through to the dialog's own cancel handling.
    const event = p.esc();
    assert.equal(event.defaultPrevented, false);
    assert.equal(event.stopped, false);
  },
  escapeUsesTheSameStack() {
    const p = makePage();
    p.window.PlayInteractions.sh = {kind: 'equip'};
    p.window.PlayInteractions.md = {kind: 'item'};
    let event = p.esc();
    assert.ok(event.defaultPrevented && event.stopped);
    assert.deepEqual(p.log, ['ix-sheet']);
    event = p.esc();
    assert.deepEqual(p.log, ['ix-sheet', 'target-mode']);
    // typing in a field: Esc never clears the board selection
    p.select('g1,1');
    event = p.esc({tagName: 'INPUT'});
    assert.equal(event.defaultPrevented, false);
    assert.equal(p.log.includes('selection'), false);
    p.esc();
    assert.equal(p.log.at(-1), 'selection');
  },
  laterButtonsAndRegister() {
    const p = makePage();
    let pressed = 0;
    p.els['ix-augment'].hidden = false;
    p.buttons['[data-ix-augment-later]'].push({hidden: false, getClientRects: () => [{}], click() { pressed += 1; p.els['ix-augment'].hidden = true; }});
    assert.equal(p.O.closeTop('back'), 'augment');
    assert.equal(pressed, 1, 'augment moment closes through 「先看看棋盘」');
    let menu = true;
    p.O.register({id: 'menu', layer: 84, above: true, isOpen: () => menu, close: () => { menu = false; }});
    const help = p.dialog('help-dialog');
    help.open = true;
    assert.deepEqual([...p.O.stack()], ['menu', 'dialog']);
    assert.equal(p.O.closeTop('back'), 'menu');
    assert.ok(p.O.entries().some((e) => e.id === 'menu' && e.above));
  },
  desktopDrawerIsNotAnOverlay() {
    const p = makePage();
    p.window.PlayLayout.phone = false;
    p.window.PlayLayout.cur = 'shop';
    assert.equal(p.O.closeTop('escape'), null, 'the desktop side drawer stays open');
  },
};

if (!scenarios[scenario]) throw new Error(`unknown scenario ${scenario}`);
scenarios[scenario]();
console.log(`${scenario} ok`);
