#!/usr/bin/env python3
"""Run the selected acceptance checks and preserve their complete output as JSON.

This runner uses the standard library, installs nothing, and never repairs source
files. Passing it covers only the selected automated checks, not every system in
docs/14-system-optimization-acceptance.md or the manual player journeys.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
FAIL_MARKER = re.compile(r"\b(?:FAIL|FAILED|FAILURE|FAILURES)\b")
NO_TESTS = re.compile(r"\bRan 0 tests\b")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def stop_process(proc):
    """Stop the whole check, including a Demo server started by its self-test."""
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif proc.poll() is None:
        proc.terminate()
    try:
        return proc.communicate(timeout=5)[0]
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            proc.kill()
        return proc.communicate()[0]


def run_check(name, command, timeout, env):
    started = time.perf_counter()
    result = {"name": name, "command": command, "cwd": str(ROOT),
              "started_at": now(), "status": "failed", "returncode": None,
              "output": "", "reasons": []}
    interrupted = False
    print("\n[RUN] " + name + ": " + " ".join(command), flush=True)
    try:
        proc = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", start_new_session=os.name == "posix")
        try:
            output = proc.communicate(timeout=timeout)[0]
        except subprocess.TimeoutExpired:
            result["reasons"].append(f"timed out after {timeout} seconds")
            output = stop_process(proc)
        except KeyboardInterrupt:
            interrupted = True
            result["reasons"].append("interrupted by user")
            output = stop_process(proc)
        result["returncode"] = proc.returncode
        result["output"] = output or ""
        if proc.returncode != 0:
            result["reasons"].append(f"process exited with {proc.returncode}")
        failure_lines = [line for line in result["output"].splitlines()
                         if FAIL_MARKER.search(line)
                         or "存在未通过项" in line
                         or ("同种子重放自检" in line and "失败" in line)]
        if failure_lines:
            result["reasons"].append("failure verdict in command output")
            result["failure_lines"] = failure_lines
        if name == "unit_tests" and NO_TESTS.search(result["output"]):
            result["reasons"].append("unittest discovered zero tests")
        if not result["reasons"]:
            result["status"] = "passed"
    except OSError as exc:
        result["reasons"].append(f"could not start command: {exc}")
    result["finished_at"] = now()
    result["duration_seconds"] = round(time.perf_counter() - started, 3)
    if result["output"]:
        print(result["output"], end="" if result["output"].endswith("\n") else "\n",
              flush=True)
    print(f"[{result['status'].upper()}] {name}", flush=True)
    for reason in result["reasons"]:
        print("  " + reason, flush=True)
    return result, interrupted


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true",
                        help="also run Demo self-test with seeds 7,42 (requires existing assets/Pillow)")
    parser.add_argument("--presentation", action="store_true",
                        help="export animation samples and validate the current art manifest")
    parser.add_argument("--balance", action="store_true",
                        help="also run experiment_match, including its replay self-check")
    parser.add_argument("--balance-games", type=positive_int, default=40)
    parser.add_argument("--balance-seed", type=int, default=20261004)
    parser.add_argument("--timeout", type=positive_int, default=1800,
                        help="maximum seconds per command (default: 1800)")
    parser.add_argument("--output", type=Path,
                        default=Path(".build/system-acceptance.json"),
                        help="JSON report path; relative paths are resolved from the repository root")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if output.suffix.lower() != ".json":
        parser.error("--output must name a .json report")
    for name in ("sim", "tools", "tests", "docs", "data", ".git"):
        if ROOT / name in output.parents:
            parser.error("--output cannot be inside a source or Git metadata directory")

    python = sys.executable
    checks = [("unit_tests", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]),
              ("compile", [python, "-m", "compileall", "-q", "sim", "tools", "tests", "esp32_runtime"]),
              ("diff_check", ["git", "diff", "--check"]),
              ("persistence_restart", [python, "tools/acceptance/persistence_selftest.py"])]
    optional = [
        ("animation_samples", args.presentation, [python, "tools/mockups/animation_showcase.py", "--out", ".build/animation-b"]),
        ("art_export", args.presentation, [python, "tools/mockups/art_manifest.py", "--output", ".build/animation-b/art-manifest.json"]),
        ("art_verify", args.presentation, [python, "tools/mockups/art_manifest.py", "--verify", ".build/animation-b/art-manifest.json"]),
        ("demo", args.demo, [python, "tools/acceptance/demo_selftest.py", "--seeds", "7,42"]),
        ("device_controls", args.demo, [python, "tools/acceptance/device_selftest.py"]),
        ("balance", args.balance, [python, "sim/experiment_match.py", "--games",
                                   str(args.balance_games), "--seed", str(args.balance_seed)])]
    checks.extend((name, command) for name, selected, command in optional if selected)
    report = {"schema_version": 1, "started_at": now(), "repository": str(ROOT),
              "scope": "selected automated checks only; manual journeys and pending systems are not certified",
              "selected_checks": [name for name, _ in checks], "checks": []}
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(ROOT / ".build/system-acceptance-pycache")
    interrupted = False
    for name, command in checks:
        if interrupted:
            report["checks"].append({"name": name, "command": command,
                                     "status": "skipped", "reason": "run interrupted"})
            continue
        result, interrupted = run_check(name, command, args.timeout, env)
        report["checks"].append(result)
    for name, selected, command in optional:
        if not selected:
            report["checks"].append({"name": name, "command": command,
                                     "status": "skipped", "reason": "not requested"})
    failed = any(check["status"] == "failed" for check in report["checks"])
    report["status"] = "interrupted" if interrupted else "failed" if failed else "passed"
    report["finished_at"] = now()
    report["summary"] = {status: sum(c["status"] == status for c in report["checks"])
                         for status in ("passed", "failed", "skipped")}
    try:
        write_report(output, report)
    except OSError as exc:
        print(f"Could not write acceptance report: {exc}", file=sys.stderr)
        return 2
    print(f"\nSelected checks: {report['status']}; JSON: {output}", flush=True)
    return 130 if interrupted else 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
