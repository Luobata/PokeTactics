/* One overlay stack for the play page (docs/74 §4).
 *
 * Every layer the player can dismiss — long-press menu, glossary card, custom
 * select, first-run guide, phone menu, modal dialogs, confirm sheets, the
 * crafting tree / evolution-branch sheets, the augment moment, the draft sheet,
 * targeting mode, the docked scout panel, the phone sheet and finally the
 * current selection — is listed here once, with its stacking layer, how to tell
 * it is open and how to dismiss it. The Android shell's back key
 * (PlayMobile → PokeTacticsShell.onBack) and the Esc key both close exactly the
 * topmost open entry and report which one, instead of faking an Esc keypress
 * and guessing from DOM mutations.
 *
 * Rules:
 *  - Higher `layer` is on top. An open `blocking` entry (a modal dialog) hides
 *    everything below it: only entries marked `above` (they render over
 *    dialogs: menus, cards, the guide) can be closed while it is open.
 *  - The battle / result dialogs are blocking but not closable here: back on
 *    them returns false (the shell asks 「退出游戏？」) so a stray back never
 *    skips a battle; Esc falls through to the dialog's own cancel handler
 *    (desktop: Esc on the battle dialog still goes to the next round).
 *  - Modules may add entries with PlayOverlay.register({...}); the built-in
 *    adapters below only use each module's public API or its visible
 *    「稍后 / 先看看」 button, so the modules keep working without this file.
 */
(function () {
  "use strict";
  const PHASE_DIALOGS = new Set(["battle-dialog", "result-dialog"]);
  const visible = (el) => Boolean(el && !el.hidden && el.getClientRects?.().length);
  const byId = (id) => document.getElementById(id);
  let ctx = null;
  const status = {closed: 0, last: null};

  function topDialog(phase) {
    const open = [...document.querySelectorAll("dialog[open]")].filter((dialog) =>
      PHASE_DIALOGS.has(dialog.id) === phase && !(dialog.id === "scout-dialog" && dialog.classList.contains("docked")));
    return open.pop() || null;
  }
  function cancelDialog(dialog) {
    if (!dialog) return;
    const cancel = new Event("cancel", {cancelable: true});
    dialog.dispatchEvent(cancel);
    if (!cancel.defaultPrevented && dialog.open) dialog.close();
  }
  function press(selector) {
    const button = [...document.querySelectorAll(selector)].find(visible);
    button?.click();
  }

  const entries = [
    {id: "context-menu", layer: 95, above: true,
      isOpen: () => Boolean(window.PlayContext?.isOpen?.()), close: () => window.PlayContext.close()},
    {id: "term-card", layer: 92, above: true,
      isOpen: () => Boolean(window.PlayPreview?.isOpen?.()), close: () => window.PlayPreview.hide()},
    {id: "select", layer: 90, above: true,
      isOpen: () => Boolean(window.PlaySelect?.current?.()), close: () => window.PlaySelect.close(true)},
    {id: "guide", layer: 88, above: true,
      isOpen: () => (window.PlayGuide?.step?.() ?? -1) >= 0, close: () => window.PlayGuide.finish()},
    {id: "dialog", layer: 80, blocking: true,
      isOpen: () => Boolean(topDialog(false)), close: () => cancelDialog(topDialog(false))},
    {id: "phase-dialog", layer: 78, blocking: true, closable: false,
      isOpen: () => Boolean(topDialog(true))},
    {id: "ix-sheet", layer: 60,
      isOpen: () => Boolean(window.PlayInteractions?.sheet?.()), close: () => window.PlayInteractions.dismiss()},
    {id: "tree", layer: 58,
      isOpen: () => Boolean(window.PlayTree?.isOpen?.()), close: () => window.PlayTree.close()},
    {id: "branch", layer: 57,
      isOpen: () => Boolean(window.PlayBranch?.isOpen?.()), close: () => window.PlayBranch.close()},
    {id: "weather", layer: 55,
      isOpen: () => Boolean(window.PlayWeather?.isOpen?.()), close: () => window.PlayWeather.close()},
    {id: "augment", layer: 50,
      isOpen: () => visible(byId("ix-augment")), close: () => press("[data-ix-augment-later]")},
    {id: "draft", layer: 48,
      isOpen: () => visible(byId("draft-sheet")), close: () => press("[data-draft-later]")},
    {id: "target-mode", layer: 45,
      isOpen: () => Boolean(window.PlayInteractions?.mode?.()), close: () => window.PlayInteractions.dismiss()},
    {id: "scout", layer: 40,
      isOpen: () => Boolean(byId("scout-dialog")?.open && byId("scout-dialog").classList.contains("docked")),
      close: () => cancelDialog(byId("scout-dialog"))},
    // Desktop keeps its drawer as a side panel; only the phone sheet is an overlay.
    {id: "sheet", layer: 20,
      isOpen: () => Boolean(window.PlayLayout?.current?.() && window.PlayLayout.isPhone?.()),
      close: () => window.PlayLayout.close()},
    {id: "selection", layer: 10, keyboardInput: false,
      isOpen: () => Boolean(ctx && (ctx.selected?.() || ctx.shopSelected?.() != null || ctx.equipItem?.())),
      close: () => ctx.actions?.clear?.()},
  ];

  function register(entry) {
    if (!entry?.id || typeof entry.isOpen !== "function") throw new Error("PlayOverlay.register needs {id, isOpen}");
    const index = entries.findIndex((e) => e.id === entry.id);
    if (index >= 0) entries.splice(index, 1);
    entries.push({layer: 30, ...entry});
    return () => { const i = entries.indexOf(entry); if (i >= 0) entries.splice(i, 1); };
  }

  function safeOpen(entry) {
    try { return Boolean(entry.isOpen()); } catch (_) { return false; }
  }
  /** Open entries a dismiss would consider, topmost first (hidden ones under a modal are dropped). */
  function stack() {
    const open = entries.filter(safeOpen).sort((a, b) => b.layer - a.layer);
    const block = open.find((e) => e.blocking);
    return block ? open.filter((e) => e.layer >= block.layer || e.above) : open;
  }
  /** The entry a dismiss would act on, or null. */
  function top({keyboardInput = false} = {}) {
    for (const entry of stack()) {
      if (keyboardInput && entry.keyboardInput === false) continue;
      return entry;
    }
    return null;
  }
  /** Close the topmost entry. Returns its id, or null when nothing (closable) is open. */
  function closeTop(via = "api", options = {}) {
    const entry = top(options);
    if (!entry || entry.closable === false || typeof entry.close !== "function") {
      status.last = {via, closed: null, top: entry?.id || null};
      return null;
    }
    entry.close();
    status.closed += 1;
    status.last = {via, closed: entry.id};
    return entry.id;
  }

  // Esc: the same stack. Typing in a field never clears the board selection.
  window.addEventListener?.("keydown", (event) => {
    if (event.key !== "Escape" || event.isComposing || event.defaultPrevented) return;
    const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(event.target?.tagName);
    const entry = top({keyboardInput: typing});
    if (!entry || entry.closable === false) return; // phase dialogs keep their own cancel handling
    closeTop("escape", {keyboardInput: typing});
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);

  window.PlayOverlay = {
    register, closeTop, top, status,
    stack: () => stack().map((e) => e.id),
    entries: () => entries.map(({id, layer, blocking = false, above = false}) => ({id, layer, blocking, above})),
    render(context) { ctx = context; },
  };
})();
