#!/usr/bin/env python3
"""Real HTTP restart/export/import test using only disposable save directories."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]


def main():
    with tempfile.TemporaryDirectory(prefix="poketactics-save-e2e-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        env = {**os.environ, "POKETACTICS_SAVE_DIR": directory}

        def get(path):
            with urllib.request.urlopen(base + path, timeout=10) as response:
                return response.read()

        def action(cmd, sid="", **params):
            result = json.loads(get("/api/demo/action?" + urllib.parse.urlencode({"cmd": cmd, "sid": sid, **params})))
            assert result["ok"], result
            return result

        def post(path, sid, raw):
            request = urllib.request.Request(base + path + "?sid=" + sid, data=raw,
                headers={"Content-Type": "application/json", "X-PokeTactics-Import": "1"})
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)

        def start():
            process = subprocess.Popen([sys.executable, "tools/acceptance/server.py", "--port", str(port)],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(process.stderr.read().decode())
                try:
                    get("/demo")
                    return process
                except OSError:
                    time.sleep(.05)
            process.terminate()
            process.wait(timeout=5)
            raise RuntimeError("server did not become ready")

        def stop(process):
            process.terminate()
            process.wait(timeout=5)
            process.stderr.close()

        process = start()
        try:
            sid = action("new", seed=7)["sid"]
            action("buy", sid, i=0)
            action("move", sid, **{"from": "b0", "to": "g0,5"})
            saved = action("lock", sid)["state"]
            backup = get("/api/demo/backup?sid=" + sid)
            stop(process)
            process = start()
            restored = action("resume", sid)["state"]
            for key in ("board", "bench", "shop", "items", "you", "round", "phase", "opponent"):
                assert restored[key] == saved[key], key
            changed = action("buy", sid, i=1)["state"]
            assert post("/api/demo/import/inspect", sid, backup)["ok"]
            rejected = post("/api/demo/import", sid, backup[:-5])
            assert not rejected["ok"], rejected
            assert action("state", sid)["state"]["you"] == changed["you"]
            imported = post("/api/demo/import", sid, backup)
            assert imported["ok"], imported
            assert imported["state"]["bench"] == saved["bench"]
            undone = action("restore_checkpoint", sid)["state"]
            assert undone["bench"] == changed["bench"]
            assert undone["you"] == changed["you"]
            fresh = post("/api/demo/import", "", backup)
            assert fresh["ok"] and fresh["sid"] != sid, fresh
            print(json.dumps({"status": "passed", "checks": ["real_process_restart",
                "no_duplicate_income", "grid_shop_inventory", "export_inspect_import",
                "corrupt_import_preserves_current", "restore_preimport_checkpoint", "first_import"],
                "backup_bytes": len(backup), "storage": "temporary_directory"}, ensure_ascii=False, indent=2))
        finally:
            if process.poll() is None:
                stop(process)


if __name__ == "__main__":
    main()
