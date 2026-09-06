#!/usr/bin/env python3
"""
Resource soak + observability evidence for the private gateway (SPEC.md M8).

Runs the representative workload against a *running* container, keeps sampling
after traffic stops, and writes a time-series evidence file.

The failure it exists to catch is browser-lifecycle leakage: renderer processes
or page contexts that accumulate with request count and never come back down.
A healthy /health endpoint is not evidence of that -- the process and memory
series are.

No universal process-count or latency limit is invented. The post-traffic band
is derived from the run's own idle baseline, because the safe band depends on
pool size, concurrency and host, none of which this script gets to assume.

Usage
-----
    export CRAWL4AI_API_TOKEN=...            # same token the gateway requires
    python deploy/gateway/soak.py \
        --container crawl4ai \
        --jobs 20 \
        --cooldown-s 120 \
        --out docs/implementation/soak-evidence.json

Exit status is 0 only when every check passes, so it is usable as a gate.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict

DEFAULT_URLS = [
    "https://example.com/",
    "https://www.iana.org/help/example-domains",
]


# ── container sampling ───────────────────────────────────────────────────────


def _docker(*args: str, timeout: int = 30) -> str:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=True
    ).stdout.strip()


@dataclass
class Sample:
    t: float
    phase: str
    browser_processes: int
    rss_bytes: int
    health_ok: bool


def sample_container(container: str, phase: str, t0: float) -> Sample:
    """One observation of browser process count and container memory."""
    try:
        ps = _docker("exec", container, "ps", "-eo", "comm")
        procs = sum(
            1
            for line in ps.splitlines()
            if any(m in line for m in ("chrome", "chromium", "headless_shell"))
        )
    except Exception:
        procs = -1

    try:
        raw = (
            _docker("stats", "--no-stream", "--format", "{{.MemUsage}}", container)
            .split("/")[0]
            .strip()
        )
        rss = _parse_bytes(raw)
    except Exception:
        rss = -1

    try:
        _docker(
            "exec",
            container,
            "curl",
            "-fsS",
            "http://127.0.0.1:11235/health",
            timeout=20,
        )
        health = True
    except Exception:
        health = False

    return Sample(round(time.time() - t0, 2), phase, procs, rss, health)


_UNITS = {
    "b": 1,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
}


def _parse_bytes(text: str) -> int:
    text = text.strip().lower()
    for unit, mult in sorted(_UNITS.items(), key=lambda kv: -len(kv[0])):
        if text.endswith(unit):
            return int(float(text[: -len(unit)]) * mult)
    return int(float(text))


# ── workload ─────────────────────────────────────────────────────────────────


@dataclass
class JobResult:
    url: str
    http_status: int | None
    latency_s: float
    ok: bool
    error: str | None = None


def run_job(base_url: str, token: str, url: str, timeout: int) -> JobResult:
    payload = json.dumps(
        {
            "urls": [url],
            "browser_config": {},
            "crawler_config": {"stream": False, "cache_mode": "bypass"},
        }
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/crawl",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read() or b"{}")
            ok = bool(body.get("success")) and bool(body.get("results"))
            return JobResult(url, resp.status, round(time.time() - started, 3), ok)
    except urllib.error.HTTPError as exc:
        return JobResult(
            url, exc.code, round(time.time() - started, 3), False, f"HTTP {exc.code}"
        )
    except Exception as exc:  # transport
        return JobResult(
            url, None, round(time.time() - started, 3), False, type(exc).__name__
        )


# ── analysis ─────────────────────────────────────────────────────────────────


@dataclass
class Verdict:
    passed: bool
    checks: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def analyse(
    baseline: list[Sample], during: list[Sample], after: list[Sample]
) -> Verdict:
    """Fail on unbounded growth, crash/OOM, or a process count that never recovers."""
    v = Verdict(True)

    if not baseline or not during or not after:
        v.passed = False
        v.notes.append("insufficient samples in one or more phases")
        return v

    base_procs = statistics.median(s.browser_processes for s in baseline)
    tail = after[-max(3, len(after) // 3) :]
    tail_procs = statistics.median(s.browser_processes for s in tail)

    # The band is derived from this run's own idle baseline, not a fixed number.
    allowed = max(base_procs * 2, base_procs + 2)
    v.checks["baseline_browser_processes"] = base_procs
    v.checks["post_traffic_browser_processes"] = tail_procs
    v.checks["allowed_post_traffic_band"] = allowed
    if tail_procs > allowed:
        v.passed = False
        v.notes.append(
            f"browser processes did not return to a stable band: "
            f"{tail_procs} > {allowed} (baseline {base_procs})"
        )

    # Monotonic growth across the cooldown means nothing is being reclaimed.
    rss_after = [s.rss_bytes for s in after if s.rss_bytes >= 0]
    if len(rss_after) >= 4:
        strictly_rising = all(b > a for a, b in zip(rss_after, rss_after[1:]))
        v.checks["rss_monotonic_rising_after_traffic"] = strictly_rising
        if strictly_rising:
            v.passed = False
            v.notes.append("container RSS rose monotonically for the whole cooldown")
        v.checks["rss_first_after"] = rss_after[0]
        v.checks["rss_last_after"] = rss_after[-1]

    unhealthy = [s.t for s in (baseline + during + after) if not s.health_ok]
    v.checks["unhealthy_samples"] = len(unhealthy)
    if unhealthy:
        v.passed = False
        v.notes.append(f"/health failed at t={unhealthy[:5]}")

    return v


# ── main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--container", default="crawl4ai")
    ap.add_argument(
        "--base-url",
        default="http://127.0.0.1:11235",
        help="reachable gateway URL; from inside the private network "
        "this is http://crawl4ai:11235",
    )
    ap.add_argument("--jobs", type=int, default=20)
    ap.add_argument("--cooldown-s", type=int, default=120)
    ap.add_argument("--sample-interval-s", type=float, default=5.0)
    ap.add_argument("--baseline-samples", type=int, default=4)
    ap.add_argument("--timeout-s", type=int, default=300)
    ap.add_argument("--urls", nargs="*", default=DEFAULT_URLS)
    ap.add_argument("--out", default="docs/implementation/soak-evidence.json")
    args = ap.parse_args(argv)

    token = os.environ.get("CRAWL4AI_API_TOKEN")
    if not token:
        print(
            "CRAWL4AI_API_TOKEN is not set; the gateway requires it.", file=sys.stderr
        )
        return 2
    if shutil.which("docker") is None:
        print(
            "docker CLI not found; the soak samples a running container.",
            file=sys.stderr,
        )
        return 2

    t0 = time.time()
    baseline, during, after = [], [], []

    print(f"[soak] baseline: {args.baseline_samples} samples")
    for _ in range(args.baseline_samples):
        baseline.append(sample_container(args.container, "baseline", t0))
        time.sleep(args.sample_interval_s)

    print(f"[soak] workload: {args.jobs} jobs")
    jobs: list[JobResult] = []
    for i in range(args.jobs):
        url = args.urls[i % len(args.urls)]
        jobs.append(run_job(args.base_url, token, url, args.timeout_s))
        during.append(sample_container(args.container, "traffic", t0))

    print(f"[soak] cooldown: {args.cooldown_s}s")
    deadline = time.time() + args.cooldown_s
    while time.time() < deadline:
        after.append(sample_container(args.container, "cooldown", t0))
        time.sleep(args.sample_interval_s)

    verdict = analyse(baseline, during, after)
    latencies = [j.latency_s for j in jobs]
    evidence = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "container": args.container,
        "jobs_requested": args.jobs,
        "jobs_succeeded": sum(1 for j in jobs if j.ok),
        "jobs_failed": sum(1 for j in jobs if not j.ok),
        "latency_s": {
            "min": min(latencies) if latencies else None,
            "median": statistics.median(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "status_distribution": {
            str(s): sum(1 for j in jobs if j.http_status == s)
            for s in sorted({j.http_status for j in jobs}, key=lambda x: (x is None, x))
        },
        "verdict": asdict(verdict),
        "samples": [asdict(s) for s in (baseline + during + after)],
        "jobs": [asdict(j) for j in jobs],
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(evidence, fh, indent=2)

    print(f"[soak] evidence -> {args.out}")
    print(f"[soak] jobs ok {evidence['jobs_succeeded']}/{args.jobs}")
    for note in verdict.notes:
        print(f"[soak] FAIL: {note}")

    # Silent-failure guard: a soak whose jobs all failed is not a passing soak.
    if evidence["jobs_failed"]:
        print(f"[soak] FAIL: {evidence['jobs_failed']} job(s) did not succeed")
        return 1
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
