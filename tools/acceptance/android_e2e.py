#!/usr/bin/env python3
"""Real-phone end-to-end check of /play over adb (docs/72).

Drives Chrome on an Android phone (USB, wireless debugging or a Dora cloud phone)
through one full round: pick the round-1 augment, open the shop, recruit a
Pokémon from the context bar, put it from the bench onto the board, start the
battle, wait for the verdict and go on to round 2. Every step is asserted, page
errors / failed requests are collected, and screenshots plus a screen recording
land in reports/evidence/android-e2e-<time>/ with a summary.json.

Optionally (--install) it installs the page as an app from Chrome's own install
dialog, opens it from the launcher and checks it runs in fullscreen.

How the phone reaches the server:
  --via tether  (default) Chrome DevTools port forwarding: the phone opens
                http://localhost:<port>/play and every connection is carried over
                adb to this machine's server. localhost is a secure context, so the
                Service Worker, Wake Lock and installing the app all work. Needs no
                network path from the phone, and works where `adb reverse` does not
                (e.g. cloud phones behind an adb relay).
  --via direct  open --url as is (e.g. http://<LAN-IP>:8820/play): proves the phone
                reaches the preview over the network. Plain http on a LAN address is
                not a secure context, so the PWA checks are reported, not required.

Usage:
  python3 tools/acceptance/android_e2e.py --port 8820 --install
  python3 tools/acceptance/android_e2e.py --via direct --url http://10.0.0.5:8820/play
  python3 tools/acceptance/android_e2e.py --serial <adb-serial> ...

Only the standard library is used. adb must be on PATH with the phone listed by
`adb devices`, USB debugging enabled and Chrome installed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHROME = "com.android.chrome"
DEVTOOLS_SOCKET = "chrome_devtools_remote"
LAUNCHER_ADD = "/com.android.launcher3.dragndrop.AddItemActivity"  # launcher's "add to home screen" sheet
ADB_HOST, ADB_PORT = "127.0.0.1", int(os.environ.get("ANDROID_ADB_SERVER_PORT", "5037"))
# JS: the first *visible* element matching a selector (closed sheets keep their DOM).
VISIBLE = ("((sel) => [...document.querySelectorAll(sel)].find((el) => !el.disabled && el.getClientRects().length"
           " && getComputedStyle(el).visibility !== 'hidden' && el.getBoundingClientRect().width > 1) || null)")


class E2EFailure(AssertionError):
    pass


# ---------------------------------------------------------------- adb
class Adb:
    def __init__(self, serial: str | None):
        self.bin = shutil.which("adb") or "adb"
        if not serial:
            out = subprocess.run([self.bin, "devices"], capture_output=True, text=True, check=True).stdout
            serials = [line.split()[0] for line in out.splitlines()[1:] if line.strip().endswith("device")]
            if len(serials) != 1:
                raise E2EFailure(f"need exactly one adb device (found {serials}); pass --serial")
            serial = serials[0]
        self.serial = serial

    def run(self, *args: str, timeout: float = 60, check: bool = True) -> str:
        result = subprocess.run([self.bin, "-s", self.serial, *args], capture_output=True, timeout=timeout)
        if check and result.returncode != 0:
            raise E2EFailure(f"adb {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
        return result.stdout.decode(errors="replace")

    def shell(self, command: str, timeout: float = 60, check: bool = True) -> str:
        return self.run("shell", command, timeout=timeout, check=check)

    def screencap(self, path: Path) -> None:
        data = subprocess.run([self.bin, "-s", self.serial, "exec-out", "screencap", "-p"],
                              capture_output=True, timeout=30, check=True).stdout
        if not data.startswith(b"\x89PNG"):
            raise E2EFailure("screencap did not return a PNG")
        path.write_bytes(data)

    def open_stream(self, service: str, timeout: float = 15) -> socket.socket:
        """A raw adb stream to a device service (e.g. localabstract:<name>), no forward listener."""
        sock = socket.create_connection((ADB_HOST, ADB_PORT), timeout=timeout)
        for request in (f"host:transport:{self.serial}", service):
            payload = request.encode()
            sock.sendall(b"%04x" % len(payload) + payload)
            status = _recv_exact(sock, 4)
            if status != b"OKAY":
                length = int(_recv_exact(sock, 4), 16) if status == b"FAIL" else 0
                detail = _recv_exact(sock, length).decode(errors="replace") if length else status.decode(errors="replace")
                sock.close()
                raise E2EFailure(f"adb stream {request}: {detail}")
        sock.settimeout(None)
        return sock

    def ui_dump(self) -> ET.Element:
        for _ in range(3):
            out = self.shell("uiautomator dump /sdcard/pt-e2e-ui.xml >/dev/null 2>&1; cat /sdcard/pt-e2e-ui.xml",
                             timeout=40, check=False)
            start = out.find("<?xml")
            if start >= 0:
                try:
                    return ET.fromstring(out[start:].strip())
                except ET.ParseError:
                    pass
            time.sleep(1)
        raise E2EFailure("uiautomator dump failed")

    def find_node(self, patterns: list[str], clickable_only: bool = False):
        root = self.ui_dump()
        for pattern in patterns:
            rx = re.compile(pattern)
            for node in root.iter("node"):
                label = node.get("text") or node.get("content-desc") or ""
                if rx.fullmatch(label.strip()) and (not clickable_only or node.get("clickable") == "true"):
                    return node, label
        return None, None

    VIEW_LINE = re.compile(r"^(\s*)(\S+)\{[0-9a-f]+ (\S{9}) \S+ (-?\d+),(-?\d+)-(-?\d+),(-?\d+)(.*)\}\s*$")

    def views(self, activity: str) -> list[dict]:
        """Visible views of one activity with absolute screen boxes, from `dumpsys activity top`.

        Works where uiautomator is unavailable (some cloud phones kill it because
        their own automation agent owns the accessibility connection): the dump
        lists each view's bounds relative to its parent, so absolute positions are
        sums along the indentation path.
        """
        dump = self.shell("dumpsys activity top", timeout=40, check=False)
        section = next((part for part in re.split(r"\n\s*ACTIVITY ", dump)[1:] if activity in part.split(None, 1)[0]), "")
        stack: list[tuple[int, int, int, bool]] = []  # indent, abs left, abs top, visible
        out = []
        for line in section.splitlines():
            m = self.VIEW_LINE.match(line)
            if not m:
                continue
            indent, cls, flags = len(m.group(1)), m.group(2), m.group(3)
            l, t, r, b = map(int, m.group(4, 5, 6, 7))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            px, py, pvis = (stack[-1][1], stack[-1][2], stack[-1][3]) if stack else (0, 0, True)
            visible = pvis and flags[0] == "V"
            ax, ay = px + l, py + t
            stack.append((indent, ax, ay, visible))
            if visible and r > l and b > t:
                out.append({"indent": indent, "cls": cls, "box": (ax, ay, ax + r - l, ay + b - t), "tail": m.group(8),
                            "center": (ax + (r - l) // 2, ay + (b - t) // 2)})
        return out

    def find_view(self, view_id: str, activity: str = CHROME + "/", child: int | None = None):
        """Centre of the view with this resource id (or of its `child`-th direct child)."""
        nodes = self.views(activity)
        for i, node in enumerate(nodes):
            if view_id not in node["tail"]:
                continue
            if child is None:
                return node["center"]
            kids, depth = [], None
            for other in nodes[i + 1:]:
                if other["indent"] <= node["indent"]:
                    break
                depth = other["indent"] if depth is None else min(depth, other["indent"])
                kids.append(other)
            kids = [k for k in kids if k["indent"] == depth]
            return kids[child]["center"] if kids else None
        return None

    def tap_node(self, node) -> None:
        x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds")))
        self.shell(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("stream closed")
        data += chunk
    return data


# ---------------------------------------------------------------- websocket + CDP
class WebSocket:
    """Minimal RFC 6455 client over an already-open stream (text frames only)."""

    def __init__(self, sock: socket.socket, path: str):
        self.sock = sock
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                      "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(1)
            if not chunk:
                raise E2EFailure("DevTools socket closed during the handshake")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise E2EFailure("DevTools refused the websocket: " + head.split(b"\r\n", 1)[0].decode())
        self.lock = threading.Lock()

    def send(self, text: str) -> None:
        payload = text.encode()
        mask = os.urandom(4)
        n = len(payload)
        header = bytes([0x81])
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 1 << 16:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self.lock:
            self.sock.sendall(header + mask + body)

    def recv(self) -> str | None:
        message = b""
        while True:
            b0, b1 = _recv_exact(self.sock, 2)
            opcode, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", _recv_exact(self.sock, 2))[0]
            elif n == 127:
                n = struct.unpack(">Q", _recv_exact(self.sock, 8))[0]
            mask = _recv_exact(self.sock, 4) if b1 & 0x80 else None
            data = _recv_exact(self.sock, n) if n else b""
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:
                return None
            if opcode == 0x9:  # ping
                with self.lock:
                    self.sock.sendall(bytes([0x8A, 0x80 | len(data)]) + b"\0\0\0\0" + data)
                continue
            if opcode in (0x0, 0x1, 0x2):
                message += data
                if b0 & 0x80:
                    return message.decode(errors="replace")


class Cdp:
    def __init__(self, adb: Adb):
        sock = adb.open_stream(f"localabstract:{DEVTOOLS_SOCKET}")
        self.ws = WebSocket(sock, "/devtools/browser")
        self.next_id = 0
        self.pending: dict[int, queue.Queue] = {}
        self.listeners: list = []
        self.lock = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        while True:
            try:
                text = self.ws.recv()
            except (OSError, ConnectionError):
                text = None
            if text is None:
                for box in list(self.pending.values()):
                    box.put({"error": {"message": "DevTools connection closed"}})
                return
            message = json.loads(text)
            if "id" in message:
                box = self.pending.pop(message["id"], None)
                if box:
                    box.put(message)
            else:
                for listener in list(self.listeners):
                    try:
                        listener(message)
                    except Exception as exc:  # a listener bug must not kill the reader
                        print("listener error:", exc, file=sys.stderr)

    def call(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 30):
        with self.lock:
            self.next_id += 1
            mid = self.next_id
        box: queue.Queue = queue.Queue()
        self.pending[mid] = box
        message = {"id": mid, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        self.ws.send(json.dumps(message))
        try:
            reply = box.get(timeout=timeout)
        except queue.Empty:
            self.pending.pop(mid, None)
            raise E2EFailure(f"DevTools {method} timed out")
        if "error" in reply:
            raise E2EFailure(f"DevTools {method}: {reply['error'].get('message')}")
        return reply.get("result", {})


class Tether:
    """Chrome DevTools port forwarding: phone localhost:<port> -> this machine's server."""

    def __init__(self, adb: Adb, cdp: Cdp, port: int, target: tuple[str, int]):
        self.adb, self.cdp, self.port, self.target = adb, cdp, port, target
        self.connections = 0
        cdp.listeners.append(self._on_event)
        cdp.call("Tethering.bind", {"port": port})

    def _on_event(self, message: dict) -> None:
        if message.get("method") == "Tethering.accepted" and message["params"].get("port") == self.port:
            threading.Thread(target=self._bridge, args=(message["params"]["connectionId"],), daemon=True).start()

    def _bridge(self, connection_id: str) -> None:
        try:
            phone = self.adb.open_stream(f"localabstract:{connection_id}")
            server = socket.create_connection(self.target, timeout=10)
            server.settimeout(None)
        except (OSError, E2EFailure) as exc:
            print("tether connection failed:", exc, file=sys.stderr)
            return
        self.connections += 1

        def pump(src: socket.socket, dst: socket.socket) -> None:
            try:
                while chunk := src.recv(65536):
                    dst.sendall(chunk)
            except OSError:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        threading.Thread(target=pump, args=(phone, server), daemon=True).start()
        pump(server, phone)
        phone.close()
        server.close()

    def close(self) -> None:
        try:
            self.cdp.call("Tethering.unbind", {"port": self.port}, timeout=5)
        except E2EFailure:
            pass


class Page:
    """One Chrome tab attached through the browser DevTools connection (flat sessions)."""

    IGNORED_FAILURES = ("net::ERR_ABORTED",)  # replay prefetch cancels images on purpose

    def __init__(self, cdp: Cdp, target_id: str):
        self.cdp = cdp
        self.target_id = target_id
        self.session = cdp.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]
        self.errors: list[str] = []
        self.requests: dict[str, str] = {}
        cdp.listeners.append(self._on_event)
        for domain in ("Runtime", "Log", "Network", "Page"):
            self.send(f"{domain}.enable")

    def send(self, method: str, params: dict | None = None, timeout: float = 30):
        return self.cdp.call(method, params, session=self.session, timeout=timeout)

    def _on_event(self, message: dict) -> None:
        if message.get("sessionId") != self.session:
            return
        method, params = message.get("method"), message.get("params", {})
        if method == "Runtime.exceptionThrown":
            detail = params.get("exceptionDetails", {})
            self.errors.append("exception: " + (detail.get("exception", {}).get("description") or detail.get("text", "")))
        elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            self.errors.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args", [])))
        elif method == "Network.requestWillBeSent":
            self.requests[params["requestId"]] = params["request"]["url"]
        elif method == "Network.responseReceived":
            status = params["response"]["status"]
            if status >= 400 and not params["response"]["url"].endswith("/favicon.ico"):  # browser's own probe
                self.errors.append(f"HTTP {status}: {params['response']['url']}")
        elif method == "Network.loadingFailed":
            if params.get("canceled") or params.get("errorText") in self.IGNORED_FAILURES:
                return
            self.errors.append(f"request failed ({params.get('errorText')}): {self.requests.get(params['requestId'], '?')}")

    def eval(self, expression: str, timeout: float = 30):
        result = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                "awaitPromise": True, "userGesture": False}, timeout=timeout)
        if "exceptionDetails" in result:
            raise E2EFailure(f"evaluate failed: {result['exceptionDetails'].get('text')} in {expression[:80]}")
        return result.get("result", {}).get("value")

    def wait(self, expression: str, timeout: float = 30, what: str | None = None):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                last = self.eval(expression)
            except E2EFailure:
                last = None
            if last:
                return last
            time.sleep(0.3)
        raise E2EFailure(f"timed out waiting for {what or expression}")

    def tappable(self, selector: str) -> bool:
        return bool(self.eval(self._probe(selector)))

    def tap(self, selector: str, timeout: float = 15) -> dict:
        """A real touch (touchStart/touchEnd through Chrome's input pipeline) on the element centre."""
        box = self.wait(self._probe(selector), timeout, what=f"tappable {selector}")
        point = {"x": box["x"], "y": box["y"], "radiusX": 4, "radiusY": 4, "force": 1, "id": 1}
        self.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [point]})
        time.sleep(0.06)
        self.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        return box

    @staticmethod
    def _probe(selector: str) -> str:
        """JS: centre of the visible element if a tap there would land on it (not covered)."""
        return (f"(() => {{ const el = {VISIBLE}({json.dumps(selector)});"
                 " if (!el) return null; el.scrollIntoView({block: 'nearest', inline: 'nearest'});"
                 " const r = el.getBoundingClientRect();"
                 " if (r.width < 2 || r.height < 2) return null;"
                 " const x = r.left + r.width / 2, y = r.top + r.height / 2;"
                 " const top = document.elementFromPoint(x, y);"
                 " if (!top || !(top === el || el.contains(top) || top.contains(el))) return null;"
                 " return {x, y, w: r.width, h: r.height}; })()")


# ---------------------------------------------------------------- the run
class Run:
    def __init__(self, args):
        self.args = args
        self.adb = Adb(args.serial)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.out = Path(args.out or ROOT / "reports" / "evidence" / f"android-e2e-{stamp}")
        self.out.mkdir(parents=True, exist_ok=True)
        self.steps: list[dict] = []
        self.shots = 0
        self.started = time.monotonic()
        self.recorder = None
        self.cdp: Cdp | None = None
        self.tether: Tether | None = None
        self.summary: dict = {"ok": False, "serial": self.adb.serial, "via": args.via, "steps": self.steps}

    # -- helpers
    def log(self, name: str, **detail) -> None:
        row = {"step": name, "t": round(time.monotonic() - self.started, 1), **detail}
        self.steps.append(row)
        print(f"[{row['t']:6.1f}s] {name}" + (f"  {json.dumps(detail, ensure_ascii=False)}" if detail else ""), flush=True)

    def shot(self, name: str) -> str:
        self.shots += 1
        path = self.out / f"{self.shots:02d}-{name}.png"
        self.adb.screencap(path)
        return path.name

    def device_info(self) -> dict:
        prop = lambda key: self.adb.shell(f"getprop {key}").strip()
        chrome = re.search(r"versionName=(\S+)", self.adb.shell(f"dumpsys package {CHROME}", check=False))
        size = self.adb.shell("wm size").strip().split(":")[-1].strip()
        return {"model": prop("ro.product.model"), "manufacturer": prop("ro.product.manufacturer"),
                "android": prop("ro.build.version.release"), "sdk": prop("ro.build.version.sdk"),
                "chrome": chrome.group(1) if chrome else None, "screen": size}

    def prepare_device(self) -> None:
        self.stay_on = self.adb.shell("settings get global stay_on_while_plugged_in", check=False).strip()
        self.adb.shell("input keyevent KEYCODE_WAKEUP", check=False)
        self.adb.shell("wm dismiss-keyguard", check=False)
        self.adb.shell("svc power stayon true", check=False)
        if self.args.record:
            self.adb.shell("rm -f /sdcard/pt-e2e.mp4", check=False)
            self.recorder = subprocess.Popen(
                [self.adb.bin, "-s", self.adb.serial, "shell", "screenrecord", "--bit-rate", "6000000",
                 "--time-limit", "180", "/sdcard/pt-e2e.mp4"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop_recording(self) -> str | None:
        if not self.recorder:
            return None
        self.adb.shell("pkill -INT screenrecord", check=False)
        try:
            self.recorder.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.recorder.kill()
        time.sleep(2)
        target = self.out / "screenrecord.mp4"
        self.adb.run("pull", "/sdcard/pt-e2e.mp4", str(target), check=False, timeout=120)
        self.adb.shell("rm -f /sdcard/pt-e2e.mp4", check=False)
        return target.name if target.exists() and target.stat().st_size > 0 else None

    def restore_device(self) -> None:
        if getattr(self, "stay_on", "") in ("0", "null", ""):
            self.adb.shell("svc power stayon false", check=False)

    def wait_target(self, url_prefix: str, timeout: float = 30, exclude=()) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for info in self.cdp.call("Target.getTargets")["targetInfos"]:
                if info["type"] == "page" and info["url"].startswith(url_prefix) and info["targetId"] not in exclude:
                    return info["targetId"]
            time.sleep(0.5)
        raise E2EFailure(f"no Chrome tab for {url_prefix}")

    # -- phases
    def connect(self) -> str:
        args = self.args
        self.summary["device"] = self.device_info()
        self.log("device", **self.summary["device"])
        if not self.summary["device"]["chrome"]:
            raise E2EFailure("Chrome is not installed on the phone")
        # Chrome only opens its DevTools socket while it runs.
        self.adb.shell(f"monkey -p {CHROME} -c android.intent.category.LAUNCHER 1", check=False)
        for _ in range(20):
            try:
                self.cdp = Cdp(self.adb)
                break
            except (E2EFailure, OSError):
                time.sleep(0.5)
        else:
            raise E2EFailure("could not reach Chrome DevTools (is USB debugging on?)")
        version = self.cdp.call("Browser.getVersion")
        self.summary["browser"] = version.get("product")
        if args.via == "tether":
            phone_port = args.phone_port or args.port
            self.tether = Tether(self.adb, self.cdp, phone_port, ("127.0.0.1", args.port))
            base = f"http://localhost:{phone_port}"
        else:
            parsed = urllib.parse.urlparse(args.url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            host, port = parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
            reach = self.adb.shell(f"toybox nc -z -w 5 {host} {port} && echo OK", check=False)
            if "OK" not in reach:
                raise E2EFailure(f"the phone cannot reach {host}:{port} over the network")
        self.log("connected", base=base, browser=self.summary["browser"])
        self.summary["base"] = base
        return base

    def loaded(self, page: Page, what: str) -> None:
        """Wait for the page; reload once if a request stalls (lossy VPN / cloud-phone paths)."""
        ready = "document.readyState === 'complete' && !!document.getElementById('fight-button')"
        for attempt in range(3):
            try:
                page.wait(ready, 30, what)
                return
            except E2EFailure:
                if attempt == 2:
                    raise
                self.log("slow load, reloading", what=what, attempt=attempt + 1)
                page.errors.clear()  # the aborted load's failures are not page errors
                page.send("Page.reload", {"ignoreCache": False})
                time.sleep(1)

    def open_play(self, base: str) -> Page:
        url = f"{base}/play?guide=0&e2e={int(time.time())}"
        before = {t["targetId"] for t in self.cdp.call("Target.getTargets")["targetInfos"]}
        self.adb.shell(f"am start -a android.intent.action.VIEW -d '{url}' -n {CHROME}/com.google.android.apps.chrome.Main",
                       check=False)
        target = self.wait_target(f"{base}/play", exclude=before)
        page = Page(self.cdp, target)
        self.loaded(page, "page load")
        if self.args.fresh:
            # A first visit: no saved game, no Service Worker, no caches for this origin.
            page.send("Storage.clearDataForOrigin", {"origin": base, "storageTypes": "all"})
            page.send("Page.reload", {"ignoreCache": True})
            time.sleep(1)
            self.loaded(page, "page reload")
        page.wait("document.getElementById('gold')?.textContent.trim() !== '—'", 40, "game state")
        self.page = page
        return page

    def play_round(self, page: Page) -> None:
        state = page.eval("({round: document.getElementById('round-number').textContent, gold: document.getElementById('gold').textContent,"
                          " secure: window.isSecureContext, mode: window.PlayMobile?.displayMode(),"
                          " manifest: !!document.querySelector('link[rel=manifest]'), sw: window.PlayMobile?.status.sw})")
        self.log("opened", **state, shot=self.shot("opened"))
        if page.eval(f"!!{VISIBLE}('.ix-aug-pick')"):
            box = page.tap(".ix-aug-pick:not([disabled])")
            page.wait(f"!{VISIBLE}('.ix-aug-pick')", 15, "augment closed")
            self.log("augment picked", at=box, shot=self.shot("augment"))
        if page.eval(f"!!{VISIBLE}('#draft-sheet [data-depth-draft]')"):
            page.tap("#draft-sheet:not([hidden]) [data-depth-draft]:not([disabled])")
            time.sleep(1.5)
            self.log("draft picked", shot=self.shot("draft"))
        bench_before = page.eval("document.querySelectorAll('#bench [data-uid]').length")
        gold_before = int(page.eval("document.getElementById('gold').textContent"))
        page.tap('.dock-button[data-open-panel="shop"]')
        page.wait("!!document.querySelector('#shop [data-shop]') && document.querySelector('#shop [data-shop]').getBoundingClientRect().height > 20",
                  10, "shop panel")
        index = page.eval(f"(() => {{ const cards = [...document.querySelectorAll('#shop [data-shop]')];"
                          f" const ok = cards.find((c) => !c.disabled && Number((c.getAttribute('aria-label') || '').match(/(\\d+)金币/)?.[1] ?? 99) <= {gold_before});"
                          " return ok ? ok.dataset.shop : null; })()")
        if index is None:
            raise E2EFailure("no affordable shop card")
        page.tap(f'#shop [data-shop="{index}"]')
        page.wait(f"!!{VISIBLE}('[data-shop-buy]')", 10, "recruit button in the context bar")
        self.log("shop card selected", card=index, shot=self.shot("shop-selected"))
        page.tap("[data-shop-buy]")
        page.wait(f"document.querySelectorAll('#bench [data-uid]').length > {bench_before}", 15, "recruited onto the bench")
        gold_after = int(page.eval("document.getElementById('gold').textContent"))
        if gold_after >= gold_before:
            raise E2EFailure(f"gold did not drop after buying ({gold_before} -> {gold_after})")
        self.log("bought", gold=[gold_before, gold_after], shot=self.shot("bought"))
        bench = page.eval("document.querySelector('#bench [data-uid]').dataset.loc")
        cell = page.eval("[...document.querySelectorAll('[data-loc^=\"g\"]')].find((c) => !c.dataset.uid && !c.disabled)?.dataset.loc")
        if not cell:
            raise E2EFailure("no free board cell")
        pop_before = page.eval("document.getElementById('pop').textContent")
        covered = not page.tappable(f'#bench [data-loc="{bench}"]')
        if covered:
            # Small viewports: the shop sheet sits over the bench; close it like a player would.
            page.tap("[data-close-panel]")
            page.wait(f"!!({page._probe(f'#bench [data-loc="{bench}"]')})", 10, "bench uncovered")
        self.summary["shop_sheet_covered_bench"] = covered
        page.tap(f'#bench [data-loc="{bench}"]')
        time.sleep(0.4)
        page.tap(f'[data-loc="{cell}"]')
        page.wait(f"!!document.querySelector('[data-loc=\"{cell}\"]').dataset.uid", 15, "unit placed on the board")
        pop_after = page.eval("document.getElementById('pop').textContent")
        self.log("placed", bench=bench, cell=cell, pop=[pop_before, pop_after], shot=self.shot("placed"))

        page.tap("#fight-button")
        page.wait("document.getElementById('battle-dialog').open", 30, "battle dialog")
        page.wait("document.getElementById('battle-loading').hidden", 60, "battle renderer ready")
        time.sleep(2.5)
        battle = page.eval("({wakeLock: window.PlayMobile?.wakeLockHeld(), wakeLockError: window.PlayMobile?.status.wakeLockError,"
                           " canvas: (() => { const c = document.getElementById('battle-canvas'); return [c.width, c.height]; })(),"
                           " clock: document.getElementById('battle-clock').textContent})")
        self.summary["battle"] = battle
        self.log("battle playing", **battle, shot=self.shot("battle"))
        page.wait("!document.getElementById('battle-verdict').hidden", 150, "battle verdict")
        verdict = page.eval("document.querySelector('#battle-verdict strong')?.textContent || ''")
        cues = page.eval("window.PlayMobile ? {cues: PlayMobile.status.cues, vibrations: PlayMobile.status.vibrations} : null")
        self.summary["verdict"] = verdict
        self.summary["haptics"] = cues
        self.log("verdict", verdict=verdict, haptics=cues, shot=self.shot("verdict"))
        page.wait("!document.getElementById('battle-next').disabled", 30, "next-round button")
        page.tap("#battle-next")
        page.wait("!document.getElementById('battle-dialog').open", 30, "battle closed")
        page.wait("document.getElementById('round-number').textContent.trim() === '02'", 30, "round 2")
        wake_after = page.eval("window.PlayMobile?.wakeLockHeld()")
        self.summary["wake_lock_released_after_battle"] = wake_after is False
        self.log("round 2", wakeLockAfterBattle=wake_after, shot=self.shot("round2"))

    def check_pwa(self, page: Page) -> dict:
        info = page.eval("""(async () => {
          const reg = await navigator.serviceWorker?.getRegistration('/play');
          const keys = window.caches ? await caches.keys() : [];
          let manifest = null;
          const link = document.querySelector('link[rel=manifest]');
          try { if (link) manifest = await (await fetch(link.href)).json(); } catch (e) {}
          return {secure: isSecureContext, sw: window.PlayMobile?.status.sw, swVersion: window.PlayMobile?.status.swVersion,
                  scope: reg?.scope || null, controlled: !!navigator.serviceWorker?.controller, caches: keys,
                  manifest: manifest && {display: manifest.display, orientation: manifest.orientation, icons: manifest.icons.length},
                  installable: window.PlayMobile?.status.installable, vibrate: typeof navigator.vibrate === 'function',
                  wakeLockApi: !!navigator.wakeLock};
        })()""")
        self.summary["pwa"] = info
        self.log("pwa", **info)
        return info

    def home_activity(self) -> str:
        return self.adb.shell("cmd package resolve-activity --brief -c android.intent.category.HOME "
                              "-a android.intent.action.MAIN", check=False).strip().splitlines()[-1]

    def launcher_icons(self) -> list[tuple[int, int, int]]:
        """(page, x, y) of every workspace icon as it appears when that page is shown.

        The workspace is a horizontal pager: each page (CellLayout) sits one page
        width further right, so on-screen x = absolute x - (page left - first page left).
        Hotseat icons are skipped.
        """
        self.adb.shell("input keyevent KEYCODE_HOME")
        time.sleep(2)
        pages, icons, in_hotseat, hotseat_indent = [], [], False, 0
        for node in self.adb.views(self.home_activity()):
            if in_hotseat and node["indent"] <= hotseat_indent:
                in_hotseat = False
            if node["cls"].endswith("Hotseat"):
                in_hotseat, hotseat_indent = True, node["indent"]
            elif node["cls"].endswith(".CellLayout") and not in_hotseat:
                pages.append(node["box"][0])
            elif node["cls"].endswith("BubbleTextView") and pages and not in_hotseat:
                x, y = node["center"]
                icons.append((len(pages) - 1, x - (pages[-1] - pages[0]), y))
        return icons

    def open_launcher_icon(self, icon: tuple[int, int, int]) -> None:
        page, x, y = icon
        self.adb.shell("input keyevent KEYCODE_HOME")
        time.sleep(1.5)
        width, height = map(int, self.adb.shell("wm size").strip().split(":")[-1].strip().split("x"))
        for _ in range(page):
            self.adb.shell(f"input swipe {int(width * .85)} {height // 2} {int(width * .15)} {height // 2} 250")
            time.sleep(1)
        self.adb.shell(f"input tap {x} {y}")

    def webapks(self) -> list[str]:
        return [line.split(":", 1)[1] for line in self.adb.shell("pm list packages", check=False).split()
                if line.startswith("package:org.chromium.webapk")]

    def install(self, page: Page, base: str) -> None:
        """Install from Chrome's own dialog, then open it from the launcher and check fullscreen."""
        page.wait("window.PlayMobile?.status.installable", 90, "beforeinstallprompt (Chrome's install criteria)")
        webapks_before = self.webapks()
        icons_before = self.launcher_icons()
        self.adb.shell(f"am start -n {CHROME}/com.google.android.apps.chrome.Main", check=False)
        page.wait("document.visibilityState === 'visible'", 15, "Chrome back in front")
        page.tap("#install-button")
        button = None
        for _ in range(20):
            button = self.adb.find_view("app:id/positive_button")  # Chrome's modal install dialog
            if button:
                break
            time.sleep(0.5)
        if not button:
            raise E2EFailure("Chrome's install dialog did not appear")
        self.log("install dialog", button=button, shot=self.shot("install-dialog"))
        # Chrome ignores taps on fresh permission-style dialogs (anti tap-jacking): retry until it closes.
        for _ in range(10):
            time.sleep(1.2)
            self.adb.shell(f"input tap {button[0]} {button[1]}")
            time.sleep(1)
            if not self.adb.find_view("app:id/positive_button"):
                break
        else:
            raise E2EFailure("Chrome's install dialog did not accept the tap")
        # Without a WebAPK (localhost / no Play services) Chrome pins a home-screen shortcut and
        # the launcher asks to confirm it; with a WebAPK this sheet never appears.
        for _ in range(10):
            add = self.adb.find_view("app:id/actions_container", activity=LAUNCHER_ADD, child=-1)
            if add:
                self.log("launcher add-to-home sheet", button=add, shot=self.shot("add-to-home"))
                time.sleep(1)
                self.adb.shell(f"input tap {add[0]} {add[1]}")
                break
            if set(self.webapks()) - set(webapks_before):
                break
            time.sleep(1)
        outcome = page.wait("window.PlayMobile?.status.installed || null", 60, "appinstalled event")
        self.log("installed", appinstalled=outcome)
        time.sleep(2)
        packages = sorted(set(self.webapks()) - set(webapks_before))
        self.summary["webapk_packages"] = packages
        existing = {t["targetId"] for t in self.cdp.call("Target.getTargets")["targetInfos"]}
        if packages:
            # A minted WebAPK is a real installed app: launch it like the launcher icon does.
            self.adb.shell("input keyevent KEYCODE_HOME")
            time.sleep(1.5)
            self.log("home screen", webapk=packages, shot=self.shot("home-screen"))
            self.adb.shell(f"monkey -p {packages[-1]} -c android.intent.category.LAUNCHER 1", check=False)
        else:
            new_icons = [c for c in self.launcher_icons() if c not in icons_before]
            self.log("home screen", new_icons=new_icons, shot=self.shot("home-screen"))
            if not new_icons:
                raise E2EFailure("no new launcher icon after installing")
            self.open_launcher_icon(new_icons[0])
        target = self.wait_target(f"{base}/play", 40, exclude=existing)
        app = Page(self.cdp, target)
        app.wait("document.readyState === 'complete' && document.getElementById('gold')?.textContent.trim() !== '—'", 40,
                 "installed app loaded")
        time.sleep(1.5)
        mode = app.eval("({mode: window.PlayMobile.displayMode(), url: location.href, inner: [innerWidth, innerHeight],"
                        " screen: [screen.width, screen.height], dpr: devicePixelRatio,"
                        " insets: getComputedStyle(document.documentElement).getPropertyValue('--sat') || null,"
                        " sw: window.PlayMobile.status.sw, controlled: !!navigator.serviceWorker.controller})")
        activity = self.adb.shell("dumpsys activity activities | grep -m1 -E 'topResumedActivity|mResumedActivity'",
                                  check=False).strip()
        mode["activity"] = activity
        self.summary["installed_app"] = mode
        self.log("installed app", **mode, shot=self.shot("installed-fullscreen"))
        if mode["mode"] not in ("fullscreen", "standalone"):
            raise E2EFailure(f"installed app opened in display-mode {mode['mode']}")
        self.page_errors_extra = app.errors

    def execute(self) -> int:
        try:
            self.prepare_device()
            base = self.connect()
            page = self.open_play(base)
            self.play_round(page)
            pwa = self.check_pwa(page)
            if self.args.via == "tether":
                if pwa["sw"] != "active" or not pwa["controlled"]:
                    raise E2EFailure(f"Service Worker not active on a secure origin: {pwa}")
                if not self.summary["battle"].get("wakeLock"):
                    raise E2EFailure("Wake Lock was not held during the battle")
            if self.args.install:
                self.install(page, base)
            errors = page.errors + getattr(self, "page_errors_extra", [])
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
            if self.tether:
                self.tether.close()
                self.summary["tether_connections"] = self.tether.connections
            self.restore_device()
            self.summary["seconds"] = round(time.monotonic() - self.started, 1)
            self.summary["screenshots"] = sorted(p.name for p in self.out.glob("*.png"))
            (self.out / "summary.json").write_text(json.dumps(self.summary, ensure_ascii=False, indent=2))
            print(("PASS" if self.summary["ok"] else "FAIL") + f"  evidence: {self.out}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--serial", help="adb serial (default: the only connected device)")
    ap.add_argument("--via", choices=("tether", "direct"), default=None,
                    help="tether: phone localhost via DevTools port forwarding (default); direct: open --url")
    ap.add_argument("--port", type=int, default=8820, help="local server port to forward in tether mode")
    ap.add_argument("--phone-port", type=int, default=0,
                    help="tether mode: port the phone opens on its localhost (default --port). A new port is a"
                         " new origin, i.e. a fresh, not yet installed app on a phone that already has one")
    ap.add_argument("--url", help="direct mode: a /play URL the phone can reach, e.g. http://<LAN-IP>:8820/play")
    ap.add_argument("--install", action="store_true", help="also install the app and check it opens fullscreen")
    ap.add_argument("--no-fresh", dest="fresh", action="store_false", help="keep the origin's saved game / caches")
    ap.add_argument("--no-record", dest="record", action="store_false", help="skip the screen recording")
    ap.add_argument("--out", help="evidence directory (default reports/evidence/android-e2e-<time>)")
    args = ap.parse_args()
    args.via = args.via or ("direct" if args.url else "tether")
    if args.via == "direct" and not args.url:
        ap.error("--via direct needs --url")
    if args.install and args.via != "tether":
        ap.error("--install needs a secure origin: use --via tether")
    return Run(args).execute()


if __name__ == "__main__":
    sys.exit(main())
