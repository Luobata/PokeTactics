/* Phone / installed-app layer for /play (docs/72).
 *
 * - registers /play/sw.js (secure contexts only: https or localhost) and shows an
 *   "已更新" notice when a new version takes over;
 * - "安装" HUD button wired to beforeinstallprompt (Chrome/Android), hidden when the
 *   page already runs as an installed app;
 * - Screen Wake Lock while the battle dialog is open (re-acquired after the tab
 *   comes back), released when it closes;
 * - navigator.vibrate on battle cues (signature moves, super-effective hits) and on
 *   feedback errors, switchable with #vibrate-button (localStorage poketactics.vibrate);
 * - unlocks WebAudio on the first tap (iOS needs the context resumed inside a gesture);
 * - marks <html> with display-mode / orientation classes for the CSS.
 * It never calls the game API.
 */
(function () {
  "use strict";
  const VIBRATE_KEY = "poketactics.vibrate";
  const PATTERNS = {ult: [40, 30, 70], ult_enemy: [25, 40, 25], super: [28], error: [20, 40, 20]};
  const root = document.documentElement;
  const status = {sw: "unsupported", swVersion: null, wakeLock: false, wakeLockError: null, installable: false,
                  installed: false, audioUnlocked: false, vibrations: [], cues: 0};
  let installEvent = null, sentinel = null, wantWake = false, lastBuzz = 0;

  const store = () => { try { return window.localStorage; } catch (_) { return null; } };
  const canVibrate = () => typeof navigator.vibrate === "function";
  function vibrationEnabled() {
    const value = store()?.getItem(VIBRATE_KEY);
    return value !== "off";
  }
  function displayMode() {
    for (const mode of ["fullscreen", "standalone", "minimal-ui"]) {
      if (window.matchMedia?.(`(display-mode: ${mode})`).matches) return mode;
    }
    return navigator.standalone ? "standalone" : "browser";
  }
  const standalone = () => displayMode() !== "browser";

  // ------------------------------------------------------------ vibration
  function buzz(kind, {force = false} = {}) {
    if (!canVibrate() || (!force && !vibrationEnabled()) || document.hidden) return false;
    const now = performance.now();
    if (!force && now - lastBuzz < 160) return false;  // a burst of hits is one buzz
    lastBuzz = now;
    try {
      const ok = navigator.vibrate(PATTERNS[kind] || PATTERNS.super);
      status.vibrations.push(kind);
      if (status.vibrations.length > 50) status.vibrations.shift();
      return ok !== false;
    } catch (_) { return false; }
  }
  function setVibration(on) {
    try { store()?.setItem(VIBRATE_KEY, on ? "on" : "off"); } catch (_) { /* private mode */ }
    syncVibrateButton();
    if (on) buzz("super", {force: true});
  }
  function syncVibrateButton() {
    const button = document.getElementById("vibrate-button");
    if (!button) return;
    button.hidden = !canVibrate();
    const on = vibrationEnabled();
    button.setAttribute("aria-pressed", String(on));
    button.classList.toggle("muted", !on);
    button.title = on ? "震动反馈：开（点击关闭）" : "震动反馈：关（点击开启）";
  }
  // battle_renderer.js dispatches these while the replay plays forward.
  window.addEventListener("battle:cue", (event) => {
    const cue = event.detail || {};
    status.cues += 1;
    if (cue.kind === "ult") buzz(cue.team === 0 ? "ult" : "ult_enemy");
    else if (cue.kind === "super") buzz("super");
  });

  // ------------------------------------------------------------ wake lock
  async function acquireWake() {
    if (!wantWake || sentinel || document.hidden || !navigator.wakeLock?.request) return;
    try {
      sentinel = await navigator.wakeLock.request("screen");
      status.wakeLock = true;
      status.wakeLockError = null;
      sentinel.addEventListener("release", () => { sentinel = null; status.wakeLock = false; });
      if (!wantWake) releaseWake();
    } catch (error) {
      status.wakeLockError = String(error?.name || error);
    }
  }
  function releaseWake() {
    const held = sentinel;
    sentinel = null;
    status.wakeLock = false;
    held?.release().catch(() => {});
  }
  function watchBattle() {
    const dialog = document.getElementById("battle-dialog");
    if (!dialog || typeof MutationObserver !== "function") return;
    const sync = () => {
      wantWake = dialog.hasAttribute("open");
      if (wantWake) acquireWake(); else releaseWake();
    };
    new MutationObserver(sync).observe(dialog, {attributes: true, attributeFilter: ["open"]});
    sync();
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) acquireWake(); });

  // ------------------------------------------------------------ audio unlock
  function unlockAudio() {
    const music = window.PlayMusic?.unlock?.();
    const effects = window.PlayFeedback?.unlockAudio?.();
    status.audioUnlocked = Boolean(music || effects);
    return status.audioUnlocked;
  }
  // Bubble on window: runs after the game's own delegated click handlers, still
  // inside the user gesture that browsers require to start audio.
  const onGesture = () => {
    if (unlockAudio()) {
      window.removeEventListener("click", onGesture);
      window.removeEventListener("touchend", onGesture);
    }
  };
  window.addEventListener("click", onGesture);
  window.addEventListener("touchend", onGesture, {passive: true});

  // ------------------------------------------------------------ install + service worker
  function syncInstallButton() {
    const button = document.getElementById("install-button");
    if (!button) return;
    button.hidden = !installEvent || standalone();
  }
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installEvent = event;
    status.installable = true;
    syncInstallButton();
  });
  window.addEventListener("appinstalled", () => {
    installEvent = null;
    status.installed = true;
    syncInstallButton();
  });
  async function promptInstall() {
    if (!installEvent) return "unavailable";
    const event = installEvent;
    installEvent = null;
    syncInstallButton();
    await event.prompt();
    const choice = await event.userChoice.catch(() => null);
    return choice?.outcome || "dismissed";
  }

  function showUpdated() {
    if (document.getElementById("app-update")) return;
    const bar = document.createElement("div");
    bar.id = "app-update";
    bar.className = "app-update";
    bar.setAttribute("role", "status");
    bar.innerHTML = '<span>新版本已就绪</span><button type="button" data-app-reload>刷新</button>'
      + '<button type="button" data-app-dismiss aria-label="稍后">×</button>';
    document.body.append(bar);
  }
  async function registerWorker() {
    if (!("serviceWorker" in navigator) || !window.isSecureContext) {
      status.sw = window.isSecureContext ? "unsupported" : "insecure-context";
      return;
    }
    const hadController = Boolean(navigator.serviceWorker.controller);
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      status.sw = "active";
      if (hadController) showUpdated();
    });
    navigator.serviceWorker.addEventListener("message", (event) => {
      if (event.data?.type === "pt-sw-version") status.swVersion = event.data.version;
    });
    try {
      const registration = await navigator.serviceWorker.register("/play/sw.js", {scope: "/play"});
      status.sw = "registered";
      await navigator.serviceWorker.ready;
      status.sw = "active";
      (navigator.serviceWorker.controller || registration.active)?.postMessage("version");
      // Long sessions: look for a new version whenever the app comes back.
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) registration.update().catch(() => {});
      });
    } catch (error) {
      status.sw = "error: " + (error?.message || error);
    }
  }

  // ------------------------------------------------------------ display mode + orientation
  function syncClasses() {
    const mode = displayMode();
    root.classList.toggle("app-installed", mode !== "browser");
    root.dataset.displayMode = mode;
    const portrait = window.matchMedia?.("(orientation: portrait)").matches ?? true;
    root.classList.toggle("orient-portrait", portrait);
    root.classList.toggle("orient-landscape", !portrait);
  }
  for (const query of ["(display-mode: fullscreen)", "(display-mode: standalone)", "(orientation: portrait)"]) {
    window.matchMedia?.(query).addEventListener?.("change", () => { syncClasses(); syncInstallButton(); });
  }
  // Rotating can leave a stale scroll offset in fullscreen; snap back to the stage.
  window.addEventListener("orientationchange", () => setTimeout(() => window.scrollTo(0, 0), 250));

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (target.closest?.("#vibrate-button")) setVibration(!vibrationEnabled());
    else if (target.closest?.("#install-button")) promptInstall();
    else if (target.closest?.("[data-app-reload]")) location.reload();
    else if (target.closest?.("[data-app-dismiss]")) document.getElementById("app-update")?.remove();
  });

  function boot() {
    syncClasses();
    syncVibrateButton();
    syncInstallButton();
    watchBattle();
    registerWorker();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  window.PlayMobile = {status, displayMode, standalone, vibrationEnabled, setVibration, buzz, promptInstall,
                       unlockAudio, wakeLockHeld: () => Boolean(sentinel)};
})();
