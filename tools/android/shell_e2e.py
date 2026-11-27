#!/usr/bin/env python3
"""Real-phone E2E of the Android shell App (apps/android, docs/73) over adb.

1. Downloads the APK from the preview's /app (proves the distribution path) and
   `adb install -r`s it; clears the App's data so the run starts as a new player.
2. Launches it. When the built-in address is not reachable from the phone (cloud
   phones only see the dev machine's VPN address), the App shows its error page:
   the run taps 「设置地址」, types --url into the hidden settings page and saves.
3. Attaches to the App's WebView over its DevTools socket
   (localabstract:webview_devtools_remote_<pid>, debug build) and checks the
   native layer: system bars hidden (window insets + `dumpsys window`), screen kept
   on, portrait locked even with rotation forced to landscape, gesture-exclusion
   bands, audio context running without any tap, vibration through the native bridge.
4. One full round through android_e2e.Run.play_round: augment → shop → recruit →
   bench → board → battle (back during the battle shows the dialog, never skips the
   battle) → verdict → round 2.
5. Back key (KEYCODE_BACK), in round 2's preparation: with the shop drawer open it
   closes the drawer; with nothing open it shows 「退出游戏？」, whose 「继续游戏」
   returns to the game. The App never leaves the game and the WebView never goes
   back in history.
6. Edge back swipe (gesture navigation switched on for the run and restored). In
   immersive mode one edge swipe only reveals the system bars; the back gesture is a
   second swipe while they show. In the guarded band of the edge even that does
   nothing; elsewhere it behaves like the back key (drawer first, then the dialog;
   back on the dialog dismisses it).
7. Finally back → 「退出」 really closes the App (so the dialog is not a trap).

Evidence (screenshots, screenrecord.mp4, logcat, summary.json) goes to
reports/evidence/android-shell-<time>/.

  python3 tools/android/shell_e2e.py --serial <adb-serial> --url https://10.4.63.169:8821/play \
      --download-page http://10.4.63.169:8820/app
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "acceptance"))
import android_e2e as base  # noqa: E402  (Adb, Cdp, Page, Run.play_round, WebSocket)
from android_e2e import E2EFailure, Page, VISIBLE  # noqa: E402

PKG = "com.poketactics.shell"
ACTIVITY = f"{PKG}/.MainActivity"
TAG = "PokeTacticsShell"
# play_layout.js marks the open phone drawer on its dock button (and body.drawer-open).
SHOP_OPEN = ("(document.querySelector('.dock-button[data-open-panel=\"shop\"]')?.getAttribute('aria-expanded') === 'true'"
             " && document.body.classList.contains('drawer-open'))")


class WebViewCdp(base.Cdp):
    """Cdp on the App's WebView DevTools socket instead of Chrome's."""

    def __init__(self, adb: base.Adb, socket_name: str):  # noqa: D107 - mirrors base.Cdp
        sock = adb.open_stream(f"localabstract:{socket_name}")
        self.ws = base.WebSocket(sock, "/devtools/browser")
        self.next_id = 0
        self.pending = {}
        self.listeners = []
        self.lock = base.threading.Lock()
        base.threading.Thread(target=self._reader, daemon=True).start()


class ShellRun(base.Run):
    def __init__(self, args):
        args.via = "shell"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        args.out = args.out or str(ROOT / "reports" / "evidence" / f"android-shell-{stamp}")
        super().__init__(args)
        self.summary.update({"app": PKG, "checks": {}})
        self.checks = self.summary["checks"]
        self.seen_lines: set[str] = set()
        self.all_lines: list[str] = []
        self.nav_restore = None
        self.rotation_restore = None
        self.battle_back_done = False

    # ------------------------------------------------------------ device helpers
    def check(self, name: str, ok: bool, **detail) -> None:
        self.checks[name] = {"ok": bool(ok), **detail}
        self.log(("ok  " if ok else "BAD ") + name, **detail)
        if not ok:
            raise E2EFailure(f"check failed: {name} {json.dumps(detail, ensure_ascii=False)}")

    def shell_log(self) -> list[str]:
        out = self.adb.shell(f"logcat -d -v time -s {TAG}:*", check=False)
        return [line for line in out.splitlines() if TAG in line]

    def new_log(self) -> list[str]:
        """App log lines not returned before. By content, not position: the logcat ring
        buffer drops old lines while the run goes on."""
        fresh = [line for line in self.shell_log() if line not in self.seen_lines]
        self.seen_lines.update(fresh)
        self.all_lines += fresh
        return fresh

    def wait_log(self, pattern: str, timeout: float = 20) -> str:
        rx = re.compile(pattern)
        deadline = time.monotonic() + timeout
        seen: list[str] = []
        while time.monotonic() < deadline:
            seen += self.new_log()
            for line in seen:
                if rx.search(line):
                    return line
            time.sleep(0.4)
        raise E2EFailure(f"no App log line matching {pattern!r} (saw {seen[-5:]})")

    def focus(self) -> str:
        # Several displays each print a line; a cloud phone's virtual display reports null first.
        out = self.adb.shell("dumpsys window | grep -E 'mCurrentFocus='", check=False)
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        return next((ln for ln in lines if not ln.endswith("=null")), lines[0] if lines else "")

    def in_game(self) -> bool:
        return f"{PKG}/" in self.focus() or f"{PKG}/{PKG}" in self.focus()

    def window_dump(self) -> str:
        return self.adb.shell("dumpsys window", timeout=40, check=False)

    def bars_hidden(self) -> dict:
        dump = self.window_dump()
        state = {}
        for kind in ("statusBars", "navigationBars"):
            m = re.search(rf"InsetsSource id=\S+ type={kind} .*?visible=(true|false)", dump)
            state[kind] = m.group(1) if m else None
        return state

    def tap_view(self, view_id: str, activity: str, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            point = self.adb.find_view(f"id/{view_id}", activity=activity)
            if point:
                self.adb.shell(f"input tap {point[0]} {point[1]}")
                return
            time.sleep(0.5)
        raise E2EFailure(f"view {view_id} not found in {activity}")

    def back_key(self) -> None:
        self.adb.shell("input keyevent KEYCODE_BACK")

    def edge_swipe(self, y: int, side: str = "left") -> None:
        width = int(self.summary["device"]["screen"].split("x")[0])
        x0, x1 = (2, width // 2) if side == "left" else (width - 3, width // 2)
        self.adb.shell(f"input swipe {x0} {y} {x1} {y} 250")

    def wait_bars(self, visible: bool, timeout: float) -> bool:
        want = "true" if visible else "false"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.bars_hidden()["statusBars"] == want:
                return True
            time.sleep(0.3)
        return False

    def back_swipe(self, y: int, side: str) -> str:
        """The back gesture in immersive mode: reveal the bars, then swipe again."""
        if not self.wait_bars(False, 15):
            raise E2EFailure("system bars did not hide before the swipe")
        self.new_log()
        self.edge_swipe(y, side)
        if not self.wait_bars(True, 4):
            raise E2EFailure(f"edge swipe at y={y} ({side}) did not reveal the bars")
        # Swipe again at once: the revealed bars only stay for about two seconds.
        self.edge_swipe(y, side)
        line = self.wait_log(r"back -> ", 8)
        return line

    def page_state(self) -> dict:
        return self.page.eval("({url: location.href, history: history.length,"
                              " shop: " + SHOP_OPEN + ", battle: document.getElementById('battle-dialog').open,"
                              " backs: window.PokeTacticsShell?.status.backs, closed: window.PokeTacticsShell?.status.closed})")

    # ------------------------------------------------------------ phases
    def install_app(self) -> None:
        url = self.args.apk_url
        tmp = Path(tempfile.mkdtemp(prefix="pt-shell-")) / "PokeTactics.apk"
        with urllib.request.urlopen(url, timeout=60) as response:
            ctype = response.headers.get("Content-Type")
            tmp.write_bytes(response.read())
        self.check("apk downloadable from the preview", ctype == "application/vnd.android.package-archive"
                   and tmp.stat().st_size > 100_000, url=url, bytes=tmp.stat().st_size, contentType=ctype)
        self.adb.run("install", "-r", str(tmp), timeout=180)
        info = self.adb.shell(f"dumpsys package {PKG}", check=False)
        version = re.search(r"versionName=(\S+)", info)
        self.summary["app_version"] = version.group(1) if version else None
        self.log("installed", version=self.summary["app_version"])
        if self.args.fresh:
            self.adb.shell(f"pm clear {PKG}", check=False)  # new player: no saved game, default address

    def download_page(self) -> None:
        """The phone's own Chrome opens the preview's download page (proves the phone path)."""
        url = self.args.download_page
        parsed = urllib.parse.urlparse(url)
        reach = self.adb.shell(f"toybox nc -z -w 5 {parsed.hostname} {parsed.port or 80} && echo OK", check=False)
        self.adb.shell(f"am start -a android.intent.action.VIEW -d '{url}' -n com.android.chrome/com.google.android.apps.chrome.Main",
                       check=False)
        time.sleep(6)
        self.check("download page opens in the phone's Chrome", "OK" in reach, url=url, shot=self.shot("download-page"))
        self.adb.shell("input keyevent KEYCODE_HOME", check=False)

    def gesture_navigation(self) -> None:
        mode = self.adb.shell("settings get secure navigation_mode", check=False).strip()
        self.summary["navigation_mode_before"] = mode
        if mode != "2":
            self.nav_restore = "threebutton" if mode == "0" else "twobutton"
            self.adb.shell("cmd overlay enable-exclusive --category com.android.internal.systemui.navbar.gestural", check=False)
            time.sleep(3)
        mode_now = self.adb.shell("settings get secure navigation_mode", check=False).strip()
        self.check("gesture navigation on for the swipe tests", mode_now == "2", before=mode, now=mode_now)

    def launch(self) -> None:
        self.adb.shell("logcat -c", check=False)
        self.adb.shell(f"am start -W -n {ACTIVITY}", timeout=60)
        line = self.wait_log(r"page ready|error page", 40)
        if "error page" in line:
            self.log("error page", line=line.split(": ", 1)[-1], shot=self.shot("error-page"))
            self.tap_view("error_settings", PKG + "/")
            time.sleep(1.5)
            self.check("settings page opened from the error page", "SettingsActivity" in self.focus(), focus=self.focus())
            # The field opens focused with its text selected; Ctrl+A again in case focus moved.
            self.adb.shell("input keycombination KEYCODE_CTRL_LEFT KEYCODE_A", check=False)
            self.adb.shell(f"input text '{self.args.url}'")
            time.sleep(0.6)
            self.log("settings", url=self.args.url, shot=self.shot("settings"))
            self.tap_view("settings_save", PKG + "/")
            self.wait_log(r"load " + re.escape(self.args.url), 15)
            self.wait_log(r"page ready", 60)
        self.summary["loaded_via_settings"] = "error page" in line

    def attach(self) -> Page:
        pid = self.adb.shell(f"pidof {PKG}", check=False).strip().split()[0]
        sockets = self.adb.shell("cat /proc/net/unix", check=False)
        name = f"webview_devtools_remote_{pid}"
        if name not in sockets:
            raise E2EFailure(f"no WebView DevTools socket {name} (debug build?)")
        self.cdp = WebViewCdp(self.adb, name)
        target = None
        for _ in range(30):
            pages = [t for t in self.cdp.call("Target.getTargets")["targetInfos"] if t["type"] == "page"]
            target = next((t["targetId"] for t in pages if "/play" in t["url"]), None)
            if target:
                break
            time.sleep(0.5)
        if not target:
            raise E2EFailure("the WebView has no /play page")
        page = Page(self.cdp, target)
        self.loaded(page, "game page")
        page.wait("document.getElementById('gold')?.textContent.trim() !== '—'", 40, "game state")
        self.page = page
        return page

    def native_checks(self, page: Page) -> None:
        # Audio, before any tap: the WebView lets media start without a gesture.
        audio = page.wait("window.PlayMusic && window.PlayMobile ? {music: PlayMusic.state(), enabled: PlayMusic.enabled(),"
                          " unlocked: PlayMobile.status.audioUnlocked, inShell: PlayMobile.inShell(),"
                          " shellClass: document.documentElement.classList.contains('in-shell'),"
                          " ua: navigator.userAgent.includes('PokeTacticsShell/')} : null", 20, "phone layer")
        if audio["enabled"] and audio["music"] != "running":
            time.sleep(2)
            audio["music"] = page.eval("PlayMusic.state()")
        self.check("audio running without a tap", audio["inShell"] and audio["unlocked"] and
                   (audio["music"] == "running" or not audio["enabled"]), **audio)
        self.log("game opened", shot=self.shot("game-opened"))

        bars = self.bars_hidden()
        inset_line = [l for l in self.shell_log() if "insets " in l][-1:]
        self.check("status bar and navigation bar hidden", bars == {"statusBars": "false", "navigationBars": "false"},
                   window=bars, app=inset_line[0].split(": ", 1)[-1] if inset_line else None)
        dump = self.window_dump()
        flags = None
        windows = self.adb.shell("dumpsys window windows", timeout=40, check=False).splitlines()
        for i, row in enumerate(windows):
            if re.match(r"\s*Window #\d+ Window\{\S+ u0 " + re.escape(PKG) + r"/\S*MainActivity\}:", row):
                flags = next((r.split("fl=", 1)[1].strip() for r in windows[i:i + 12] if "fl=" in r), None)
                if flags and "FULLSCREEN" in flags:  # the activity window, not the exit dialog
                    break
        self.check("screen kept on", bool(flags and "KEEP_SCREEN_ON" in flags), flags=flags)
        exclusion = re.search(r"mSystemGestureExclusion=(SkRegion\([^\n]*\))", dump)
        self.summary["gesture_exclusion"] = exclusion.group(1) if exclusion else None
        bands = [tuple(map(int, m)) for m in re.findall(r"\((\d+),(\d+),(\d+),(\d+)\)", self.summary["gesture_exclusion"] or "")]
        self.check("edge guard bands set", len(bands) == 2, bands=bands)
        self.bands = bands

        # Vibration through the native bridge (a forced buzz on the App's own path).
        page.eval("PlayMobile.buzz('super', {force: true})")
        line = self.wait_log(r"vibrate \[", 10)
        self.check("vibration reaches the native Vibrator", True, log=line.split(": ", 1)[-1])

        # Portrait lock: force the display to landscape; the App must stay portrait.
        self.rotation_restore = (self.adb.shell("settings get system accelerometer_rotation", check=False).strip(),
                                 self.adb.shell("settings get system user_rotation", check=False).strip())
        self.adb.shell("settings put system accelerometer_rotation 0", check=False)
        self.adb.shell("settings put system user_rotation 1", check=False)
        time.sleep(2.5)
        size = page.eval("[innerWidth, innerHeight, screen.orientation?.type]")
        shot = self.shot("forced-landscape")
        self.adb.shell("settings put system user_rotation 0", check=False)
        time.sleep(2.5)
        # The display may turn; the App stays portrait (letterboxed), never re-laid out wide.
        self.check("portrait locked under forced rotation", size[1] > size[0], viewport=size[:2],
                   display=size[2], shot=shot)
        page.wait("innerHeight > innerWidth && innerWidth > 300", 10, "full-size portrait again")

    def guide_back(self, page: Page) -> None:
        """A new player gets the first-run guide; back closes it like any overlay."""
        time.sleep(1)
        step = page.eval("window.PlayGuide ? PlayGuide.step() : -1")
        if step >= 0:
            self.new_log()
            self.back_key()
            line = self.wait_log(r"back -> ", 8)
            time.sleep(0.4)
            after = page.eval("PlayGuide.step()")
            self.check("back key closes the first-run guide", "closed an overlay" in line and after < 0 and self.in_game(),
                       step=[step, after], closed=page.eval("window.PokeTacticsShell.status.last"))
        # Keep it closed for the rest of the run (it would cover the bench taps).
        page.eval("localStorage.setItem(PlayGuide.KEY, 'done'), PlayGuide.step() >= 0 && PlayGuide.finish(), true")

    def open_shop(self, page: Page) -> None:
        if not page.eval(SHOP_OPEN):
            page.tap('.dock-button[data-open-panel="shop"]')
        page.wait(SHOP_OPEN, 10, "shop drawer open")
        time.sleep(0.5)

    def expect_dialog(self, what: str, after: str | None = None) -> None:
        """「退出游戏？」 shown (after the given back line, if the caller already read it)."""
        if after and after in self.all_lines:
            self.new_log()
            later = self.all_lines[self.all_lines.index(after):]
            if not any("exit dialog shown" in l for l in later):
                self.wait_log(r"exit dialog shown", 8)
        else:
            self.wait_log(r"exit dialog shown", 8)
        time.sleep(0.6)
        self.check(f"{what}: 「退出游戏？」 shown, App still in front", self.in_game(), focus=self.focus())

    def settle(self, page: Page) -> None:
        """Round-start choices (augment / draft) out of the way, as play_round does."""
        time.sleep(1.5)
        if page.eval(f"!!{VISIBLE}('.ix-aug-pick')"):
            page.tap(".ix-aug-pick:not([disabled])")
            page.wait(f"!{VISIBLE}('.ix-aug-pick')", 15, "augment closed")
        if page.eval(f"!!{VISIBLE}('#draft-sheet [data-depth-draft]')"):
            page.tap("#draft-sheet:not([hidden]) [data-depth-draft]:not([disabled])")
            time.sleep(1.5)
        page.wait("!document.querySelector('dialog[open]')", 15, "no dialog open")

    # ------------------------------------------------------------ phone UX (docs/74)
    def screen_point(self, page: Page, selector: str) -> tuple[int, int]:
        """Centre of an element in physical screen pixels (WebView fills the window under the cutout band)."""
        box = page.eval(f"(() => {{ const el = {VISIBLE}({json.dumps(selector)}); if (!el) return null;"
                        " const r = el.getBoundingClientRect();"
                        " return {x: r.left + r.width / 2, y: r.top + r.height / 2, dpr: devicePixelRatio, ih: innerHeight}; })()")
        if not box:
            raise E2EFailure(f"no visible {selector}")
        screen_h = int(self.summary["device"]["screen"].split("x")[1])
        offset = round(screen_h - box["ih"] * box["dpr"])
        return round(box["x"] * box["dpr"]), round(box["y"] * box["dpr"]) + offset

    def finger_drag(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        """A real finger drag (input motionevent): straight up first, then over to the target."""
        (x0, y0), (x1, y1) = start, end
        steps = [(x0, y0 - 25), (x0 + 2, y0 - 55), (x0 + 6, y0 - 90)]
        steps += [(round(x0 + (x1 - x0) * k / 6), round(y0 - 90 + (y1 - y0 + 90) * k / 6)) for k in range(1, 7)]
        cmds = [f"input motionevent DOWN {x0} {y0}"] + [f"input motionevent MOVE {x} {y}" for x, y in steps]
        self.adb.shell("; ".join(cmds))
        time.sleep(0.25)
        self.shot("drag-in-flight")
        self.adb.shell(f"input motionevent MOVE {x1} {y1}; input motionevent UP {x1} {y1}")

    def phone_ux_tests(self, page: Page) -> None:
        layout = page.eval("""(() => {
          const hud = document.querySelector('.stage-hud').getBoundingClientRect();
          const menu = document.getElementById('menu-button').getBoundingClientRect();
          return {nav: getComputedStyle(document.querySelector('.portal-nav') || document.body).display,
                  tools: getComputedStyle(document.querySelector('.hud-tools')).display,
                  hudHeight: Math.round(hud.height), menu: [Math.round(menu.width), Math.round(menu.height)],
                  tileH: window.PlayPhone?.status.tileH};
        })()""")
        self.check("phone HUD: site nav and tool row hidden, one-row HUD with a menu button",
                   layout["nav"] == "none" and layout["tools"] == "none" and layout["hudHeight"] <= 58
                   and layout["menu"][0] >= 40 and layout["menu"][1] >= 36, **layout)
        # Shop: the sheet stops under the bench; the selected card carries its own recruit button.
        self.open_shop(page)
        gold = int(page.eval("document.getElementById('gold').textContent"))
        index = page.eval(f"(() => {{ const cards = [...document.querySelectorAll('#shop [data-shop]')];"
                          f" const ok = cards.find((c) => !c.disabled && Number((c.getAttribute('aria-label') || '').match(/(\\d+)金币/)?.[1] ?? 99) <= {gold});"
                          " return ok ? ok.dataset.shop : null; })()")
        if index is None:
            raise E2EFailure("no affordable shop card for the quick-buy check")
        bench_before = page.eval("document.querySelectorAll('#bench [data-uid]').length")
        page.tap(f'#shop [data-shop="{index}"]')
        page.wait(f"!!{VISIBLE}('.shop-quick-buy')", 8, "recruit button on the selected shop card")
        geo = page.eval("""(() => { const b = document.querySelector('.shop-quick-buy').getBoundingClientRect();
          const sheet = document.getElementById('stage-drawer').getBoundingClientRect();
          const bench = document.querySelector('.bench-area').getBoundingClientRect();
          return {button: [Math.round(b.width), Math.round(b.height)], inSheet: b.top >= sheet.top,
                  benchBottom: Math.round(bench.bottom), sheetTop: Math.round(sheet.top)}; })()""")
        self.check("shop sheet leaves the bench uncovered; recruit button sits in the sheet",
                   geo["inSheet"] and geo["benchBottom"] <= geo["sheetTop"] + 1 and geo["button"][1] >= 40,
                   **geo, shot=self.shot("ux-shop-quick-buy"))
        page.tap(".shop-quick-buy")
        page.wait(f"document.querySelectorAll('#bench [data-uid]').length > {bench_before}", 15, "quick-buy recruited")
        self.log("quick buy", gold=[gold, page.eval("document.getElementById('gold').textContent")])
        # Touch drag with a real finger: bench → an empty board cell (or another bench slot when the board is full).
        unit = page.eval("[...document.querySelectorAll('#bench [data-uid]')].pop().dataset.loc")
        full = page.eval("(() => { const [a, b] = document.getElementById('pop').textContent.split('/').map(Number); return a >= b; })()")
        target = page.eval("(() => { const cells = [...document.querySelectorAll(" + json.dumps(
            "#bench [data-loc]:not([data-uid])" if full else "#ally-board [data-loc]:not([data-uid])")
            + ")]; return cells[Math.floor(cells.length / 2)]?.dataset.loc || null; })()")
        page.tap("[data-close-panel]")
        page.wait("!document.body.classList.contains('drawer-open')", 8, "shop closed for the drag")
        time.sleep(0.4)
        self.finger_drag(self.screen_point(page, f'#bench [data-loc="{unit}"]'), self.screen_point(page, f'[data-loc="{target}"]'))
        page.wait(f"!!document.querySelector('[data-loc=\"{target}\"]').dataset.uid", 10, "unit dropped by touch drag")
        self.check("touch drag moves a unit with a real finger", page.eval("PlayPhone.status.moves") >= 1,
                   source=unit, target=target, status=page.eval("PlayPhone.status"), shot=self.shot("ux-dragged"))
        # Long press → menu, no text selection; back closes it; the very next tap works (audit H4).
        x, y = self.screen_point(page, f'[data-loc="{target}"]')
        self.adb.shell(f"input swipe {x} {y} {x} {y} 1100")
        page.wait("window.PlayContext?.isOpen()", 6, "long-press menu")
        selected = page.eval("getSelection().toString()")
        shot = self.shot("ux-long-press")
        self.new_log()
        self.back_key()
        self.wait_log(r"back -> ", 8)
        time.sleep(0.5)
        closed = page.eval("PokeTacticsShell.status.last")
        bx, by = self.screen_point(page, '.dock-button[data-open-panel="bonds"]')
        self.adb.shell(f"input tap {bx} {by}")
        time.sleep(1.0)
        opened = page.eval("PlayLayout.current()")
        self.check("long press: menu without text selection; back closes it; next tap is not swallowed",
                   selected == "" and closed.get("changed") == ["context-menu"] and opened == "bonds",
                   selection=selected, closed=closed, opened=opened, shot=shot)
        self.back_key()
        self.wait_log(r"back -> ", 8)
        # Menu sheet: labelled rows, toggles mirror the HUD buttons, back closes it.
        mx, my = self.screen_point(page, "#menu-button")
        self.adb.shell(f"input tap {mx} {my}")
        page.wait("PlayPhone.menuOpen()", 6, "menu sheet")
        before = page.eval("document.getElementById('vibrate-button')?.getAttribute('aria-pressed')")
        shot = self.shot("ux-menu")
        if page.eval(f"!!{VISIBLE}('[data-menu-proxy=\"vibrate-button\"]')"):
            page.tap('[data-menu-proxy="vibrate-button"]')
            time.sleep(0.4)
            flipped = page.eval("document.getElementById('vibrate-button').getAttribute('aria-pressed')")
            page.tap('[data-menu-proxy="vibrate-button"]')
            time.sleep(0.4)
        else:
            flipped = None
        self.new_log()
        self.back_key()
        line = self.wait_log(r"back -> ", 8)
        time.sleep(0.4)
        self.check("menu sheet: toggles drive the real buttons; back closes it",
                   not page.eval("PlayPhone.menuOpen()") and "closed an overlay" in line
                   and (flipped is None or flipped != before)
                   and page.eval("document.getElementById('vibrate-button')?.getAttribute('aria-pressed')") == before,
                   vibrate=[before, flipped], closed=page.eval("PokeTacticsShell.status.last"), shot=shot)

    def back_tests(self, page: Page) -> None:
        start = self.page_state()
        self.new_log()
        # Key: drawer first.
        self.open_shop(page)
        self.log("shop drawer open", shot=self.shot("back-shop-open"))
        self.back_key()
        line = self.wait_log(r"back -> ", 8)
        time.sleep(0.5)
        state = self.page_state()
        self.check("back key closes the shop drawer", "closed an overlay" in line and not state["shop"] and self.in_game(),
                   log=line.split(": ", 1)[-1], state=state, closed=self.page.eval("window.PokeTacticsShell.status.last"))
        self.log("after back", shot=self.shot("back-shop-closed"))
        # Key: nothing open → dialog; back on the dialog dismisses it.
        self.back_key()
        self.expect_dialog("back key with nothing open")
        self.log("exit dialog", shot=self.shot("back-exit-dialog"))
        self.dialog_button("继续游戏")
        self.wait_log(r"exit dialog dismissed", 5)
        state = self.page_state()
        self.check("「继续游戏」 dismisses the dialog and stays in the game",
                   self.in_game() and state["url"] == start["url"] and state["history"] == start["history"],
                   state=state, focus=self.focus())

        # Edge swipe (gesture navigation). In immersive mode an edge swipe first only
        # reveals the system bars (transiently); a swipe while they show is the back
        # gesture. They hide again by themselves.
        top, bottom = self.bands[0][1], self.bands[0][3]
        inside = (top + bottom) // 2
        outside = max(top // 2, 300)
        self.open_shop(page)
        self.wait_bars(False, 10)
        self.new_log()
        self.edge_swipe(outside, "left")
        shown = self.wait_bars(True, 4)
        shot = self.shot("swipe-once-bars")
        swallowed = [l for l in self.new_log() if "back -> " in l]
        state = self.page_state()
        self.check("one edge swipe only reveals the bars (no back)", shown and not swallowed and state["shop"]
                   and self.in_game(), y=outside, state=state, shot=shot)
        t0 = time.monotonic()
        hidden = self.wait_bars(False, 15)
        self.check("revealed bars hide again by themselves", hidden, seconds=round(time.monotonic() - t0, 1))
        for attempt in (1, 2):
            self.edge_swipe(inside, "left")
            time.sleep(1.2)
        swallowed = [l for l in self.new_log() if "back -> " in l]
        state = self.page_state()
        self.check("edge swipes inside the guard band neither reveal bars nor go back", not swallowed and state["shop"]
                   and self.in_game() and self.bars_hidden()["statusBars"] == "false", y=inside, state=state)
        line = self.back_swipe(outside, "left")
        time.sleep(0.5)
        state = self.page_state()
        self.check("edge back swipe closes the shop drawer first", "closed an overlay" in line and not state["shop"]
                   and self.in_game(), y=outside, log=line.split(": ", 1)[-1], state=state,
                   closed=page.eval("window.PokeTacticsShell.status.last"))
        self.log("after swipe", shot=self.shot("swipe-shop-closed"))
        line = self.back_swipe(outside, "right")
        self.check("edge back swipe with nothing open asks to exit", "exit dialog" in line, log=line.split(": ", 1)[-1])
        self.expect_dialog("edge back swipe with nothing open", after=line)
        self.log("swipe exit dialog", shot=self.shot("swipe-exit-dialog"))
        self.back_key()
        self.wait_log(r"exit dialog dismissed", 5)
        time.sleep(0.5)
        state = self.page_state()
        self.check("back on the dialog dismisses it; same page, no history navigation", self.in_game()
                   and state["url"] == start["url"] and state["history"] == start["history"], state=state)

    def log(self, name: str, **detail) -> None:
        super().log(name, **detail)
        # Hook into play_round: while the battle plays, back must not skip it.
        if name == "battle playing" and not self.battle_back_done:
            self.battle_back_done = True
            # A glossary card / menu over the battle closes first; then the dialog.
            closed = []
            for _ in range(4):
                self.back_key()
                line = self.wait_log(r"back -> ", 8)
                if "exit dialog" in line:
                    break
                closed.append(self.page.eval("window.PokeTacticsShell.status.last"))
                time.sleep(0.4)
            self.summary["battle_back_closed_first"] = closed
            self.expect_dialog("back during the battle", after=line)
            state = self.page_state()
            self.log("battle exit dialog", shot=self.shot("battle-back-dialog"))
            self.back_key()
            time.sleep(0.8)
            self.check("back during the battle keeps the battle", state["battle"] and self.page_state()["battle"]
                       and self.in_game(), state=state)

    def dialog_button(self, label: str) -> None:
        """Press a dialog button by keyboard focus (cloud phones have no uiautomator):
        the buttons are [退出][继续游戏]; TAB once focuses 退出, twice 继续游戏."""
        tabs = {"退出": 1, "继续游戏": 2}[label]
        for _ in range(tabs):
            self.adb.shell("input keyevent KEYCODE_TAB")
            time.sleep(0.3)
        self.adb.shell("input keyevent KEYCODE_ENTER")
        time.sleep(1)

    def exit_for_real(self) -> None:
        """The dialog's 「退出」 really closes the App, so the dialog is not a trap."""
        self.back_key()
        self.expect_dialog("final back")
        self.dialog_button("退出")
        self.wait_log(r"exit confirmed", 5)
        time.sleep(1.5)
        self.check("「退出」 closes the App", not self.in_game(), focus=self.focus())
        self.shot("exited")

    # ------------------------------------------------------------ run
    def execute(self) -> int:
        try:
            self.summary["device"] = self.device_info()
            self.log("device", **self.summary["device"])
            self.prepare_device()
            if self.args.download_page:
                self.download_page()
            self.install_app()
            self.gesture_navigation()
            self.launch()
            page = self.attach()
            self.summary["base"] = page.eval("location.origin")
            self.native_checks(page)
            self.guide_back(page)
            self.play_round(page)
            self.settle(page)
            self.phone_ux_tests(page)
            self.back_tests(page)
            self.new_log()
            vibes = [l.split(": ", 1)[-1] for l in self.all_lines if "vibrate [" in l]
            self.summary["native_vibrations"] = vibes
            self.summary["back_log"] = [l.split(": ", 1)[-1] for l in self.all_lines if "back -> " in l]
            self.exit_for_real()
            errors = page.errors
            self.summary["errors"] = errors
            if errors:
                raise E2EFailure("page errors: " + "; ".join(errors[:10]))
            self.summary["ok"] = True
            return 0
        except (E2EFailure, OSError, subprocess.SubprocessError) as exc:
            self.summary["failure"] = str(exc)
            self.log("FAILED", error=str(exc))
            try:
                self.shot("failure")
            except Exception:
                pass
            return 1
        finally:
            self.summary["recording"] = self.stop_recording()
            try:
                self.new_log()
            except Exception:
                pass
            (self.out / "logcat.txt").write_text("\n".join(self.all_lines) + "\n")
            if self.rotation_restore:
                auto, user = self.rotation_restore
                self.adb.shell(f"settings put system user_rotation {user if user != 'null' else 0}", check=False)
                self.adb.shell(f"settings put system accelerometer_rotation {auto if auto != 'null' else 1}", check=False)
            if self.nav_restore and not self.args.keep_gestures:
                self.adb.shell(f"cmd overlay enable-exclusive --category com.android.internal.systemui.navbar.{self.nav_restore}",
                               check=False)
            self.restore_device()
            self.summary["seconds"] = round(time.monotonic() - self.started, 1)
            self.summary["screenshots"] = sorted(p.name for p in self.out.glob("*.png"))
            (self.out / "summary.json").write_text(json.dumps(self.summary, ensure_ascii=False, indent=2))
            print(("PASS" if self.summary["ok"] else "FAIL") + f"  evidence: {self.out}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--serial", help="adb serial (default: the only connected device)")
    ap.add_argument("--url", required=True, help="/play address the phone can reach, typed into the App's settings"
                    " when the built-in default is unreachable (e.g. https://<VPN-IP>:8821/play)")
    ap.add_argument("--apk-url", default="http://127.0.0.1:8820/app/PokeTactics.apk",
                    help="where to download the APK (default: this machine's preview service)")
    ap.add_argument("--download-page", help="also open this /app page in the phone's Chrome and screenshot it"
                    " (e.g. http://<VPN-IP>:8820/app)")
    ap.add_argument("--no-fresh", dest="fresh", action="store_false", help="keep the App's data (address, saved game)")
    ap.add_argument("--no-record", dest="record", action="store_false", help="skip the screen recording")
    ap.add_argument("--keep-gestures", action="store_true", help="leave gesture navigation on afterwards")
    ap.add_argument("--out", help="evidence directory (default reports/evidence/android-shell-<time>)")
    return ShellRun(ap.parse_args()).execute()


if __name__ == "__main__":
    sys.exit(main())
