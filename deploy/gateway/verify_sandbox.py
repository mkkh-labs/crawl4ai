#!/usr/bin/env python3
"""
Live Chromium renderer-sandbox verifier (F-04), run INSIDE the gateway.

    docker exec -i crawl4ai-crawl4ai-1 python3 - < deploy/gateway/verify_sandbox.py

Processes are identified by /proc/<pid>/exe, not by matching command-line text.
Text matching also catches the inspecting shell, whose arguments contain the
very flags being searched for.

Passes only when:
  * at least one Chromium browser process and one renderer are running,
  * no Chromium process has --no-sandbox on its command line,
  * every renderer runs in a user namespace other than the container's, and
    in a nested PID namespace,
  * every renderer is under a seccomp filter (Seccomp: 2).

Prints one JSON object; exit 0 = pass, 1 = fail, 2 = nothing to inspect.
"""

from __future__ import annotations

import json
import os
import sys

CHROME_EXE_NAMES = ("chrome-headless-shell", "chrome", "chromium")


def _read(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _status(pid: str) -> dict[str, str]:
    out = {}
    for line in _read(f"/proc/{pid}/status").splitlines():
        key, _, value = line.partition(":")
        out[key] = value.strip()
    return out


def chromium_processes() -> list[dict]:
    procs = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            continue
        if os.path.basename(exe) not in CHROME_EXE_NAMES:
            continue
        # Chromium rewrites its process title, so cmdline can be one
        # space-joined string instead of NUL-separated arguments.
        argv = _read(f"/proc/{pid}/cmdline").replace("\0", " ").split()
        ptype = next(
            (a.split("=", 1)[1] for a in argv if a.startswith("--type=")), "browser"
        )
        st = _status(pid)
        try:
            userns = os.readlink(f"/proc/{pid}/ns/user")
        except OSError:
            userns = None
        procs.append(
            {
                "pid": int(pid),
                "type": ptype,
                "no_sandbox_flag": "--no-sandbox" in argv,
                "userns": userns,
                "nspid_depth": len(st.get("NSpid", "").split()),
                "seccomp": st.get("Seccomp"),
            }
        )
    return procs


def main() -> int:
    container_userns = os.readlink("/proc/1/ns/user")
    procs = chromium_processes()
    browsers = [p for p in procs if p["type"] == "browser"]
    renderers = [p for p in procs if p["type"] == "renderer"]
    failures = []
    if not browsers or not renderers:
        print(json.dumps({"verdict": "nothing_to_inspect", "processes": procs}))
        return 2
    if any(p["no_sandbox_flag"] for p in procs):
        failures.append("a Chromium process runs with --no-sandbox")
    for r in renderers:
        if r["userns"] == container_userns:
            failures.append(f"renderer {r['pid']} shares the container user namespace")
        if r["nspid_depth"] < 2:
            failures.append(f"renderer {r['pid']} is not in a nested PID namespace")
        if r["seccomp"] != "2":
            failures.append(f"renderer {r['pid']} has no seccomp filter")
    print(
        json.dumps(
            {
                "verdict": "pass" if not failures else "fail",
                "container_userns": container_userns,
                "browsers": len(browsers),
                "renderers": len(renderers),
                "failures": failures,
                "processes": procs,
            },
            indent=2,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
