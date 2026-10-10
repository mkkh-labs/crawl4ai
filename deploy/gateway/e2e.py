#!/usr/bin/env python3
"""
n8n-equivalent end-to-end validation against a running gateway.

Exercises exactly the production call path described in deploy/n8n/README.md --
bearer auth, POST /crawl at the internal service DNS, response classification,
bounded retries, and a complete CrawlRun provenance record per run -- using the
same deploy/n8n/contract.py the workflow contract is specified by. Testing a
reimplementation of the contract would prove nothing about the contract.

Covers the DEPLOY acceptance items:
  AC-01  the live service reports a version at or above MIN_SAFE_VERSION
  AC-03  unauthenticated and bad-token requests are refused
  AC-04  a dict-wrapped forbidden config (GHSA-5w5p-vcv6-mm3f) is refused
  AC-09  every run carries the required provenance fields
  AC-10  forced retryable and terminal failures produce no silent success

Usage:
    export CRAWL4AI_API_TOKEN=...
    python deploy/gateway/e2e.py --base-url http://127.0.0.1:11235 --runs 20 \
        --out docs/implementation/e2e-evidence.json

Exit status is 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "n8n")
)
import contract as c  # noqa: E402

REQUIRED_PROVENANCE = (
    "run_id",
    "source_url",
    "started_at",
    "finished_at",
    "crawler_version",
    "config_fingerprint",
    "raw_response",
    "raw_checksum",
    "status",
    "failure_class",
)

#: Oldest release carrying every known security fix (v0.9.4 closes
#: GHSA-5w5p-vcv6-mm3f, GHSA-wh5w-hmj3-vgg7 and GHSA-f77g-77vp-r96v).
MIN_SAFE_VERSION = (0, 9, 4)

#: GHSA-5w5p-vcv6-mm3f probe: a forbidden LLMConfig hidden behind the
#: {"type": "dict"} envelope. A vulnerable server rebuilds it as trusted and
#: resolves api_token from its own environment. base_url is a closed loopback
#: port, so even a vulnerable server sends nothing off-box.
LAUNDERING_PROBE_CONFIG = {
    "type": "CrawlerRunConfig",
    "extraction_strategy": {
        "type": "dict",
        "value": {
            "type": "LLMExtractionStrategy",
            "params": {
                "llm_config": {
                    "type": "dict",
                    "value": {
                        "type": "LLMConfig",
                        "params": {
                            "provider": "openai/gpt-4o-mini",
                            "api_token": "env:CRAWL4AI_API_TOKEN",
                            "base_url": "http://127.0.0.1:9/",
                        },
                    },
                }
            },
        },
    },
}

REPRESENTATIVE_URLS = [
    "https://example.com/",
    "https://www.iana.org/help/example-domains",
]


def version_tuple(version: str) -> tuple:
    """'0.9.4' -> (0, 9, 4); anything unparseable sorts below every release."""
    try:
        return tuple(int(part) for part in version.split(".")[:3])
    except (AttributeError, ValueError):
        return (-1,)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _request(
    base_url: str,
    path: str,
    token: str | None,
    payload: dict | None,
    timeout: int,
    method: str = "POST",
):
    """Return (status_code, parsed_body_or_None, error_name_or_None)."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{base_url}{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw or b"{}"), None
            except json.JSONDecodeError:
                return resp.status, None, "malformed_json"
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}"), None
        except json.JSONDecodeError:
            return exc.code, None, "malformed_json"
    except Exception as exc:
        return None, None, type(exc).__name__


def crawl_once(base_url, token, url, timeout, crawler_config):
    payload = {"urls": [url], "browser_config": {}, "crawler_config": crawler_config}
    return _request(base_url, c.CRAWL_ENDPOINT, token, payload, timeout)


def run_with_retries(
    base_url,
    token,
    url,
    timeout,
    crawler_config,
    crawler_version,
    sleeper=time.sleep,
):
    """One logical run: attempts, classification, bounded retries, provenance."""
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    started = _now()
    failures, attempt = [], 1
    status_code = body = None

    while True:
        status_code, body, transport_error = crawl_once(
            base_url, token, url, timeout, crawler_config
        )
        if transport_error is not None and status_code is None:
            cls = c.classify_exception(Exception(transport_error))
        elif transport_error == "malformed_json":
            cls = c.Classification(c.FAILED_TERMINAL, "content_contract", False)
        else:
            cls = c.classify_response(status_code, body)

        if cls.status != c.SUCCEEDED:
            failures.append(
                c.failure_record(
                    run_id=run_id,
                    classification=cls,
                    attempt=attempt,
                    http_status=status_code,
                    message=str(transport_error or status_code),
                )
            )

        if not c.should_retry(cls, attempt):
            break
        sleeper(min(c.retry_delay_seconds(attempt), 5.0))
        attempt += 1

    # Budget spent on a retryable failure => terminal for the operator.
    final = cls
    if cls.status == c.FAILED_RETRYABLE:
        final = c.Classification(c.FAILED_TERMINAL, cls.failure_class, False)

    run = c.build_crawl_run(
        run_id=run_id,
        source_url=url,
        started_at=started,
        finished_at=_now(),
        crawler_version=crawler_version,
        browser_config={},
        crawler_config=crawler_config,
        raw_response=body,
        classification=final,
        attempts=attempt,
        failures=failures,
    )
    return run, status_code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:11235")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--timeout-s", type=int, default=180)
    ap.add_argument("--urls", nargs="*", default=REPRESENTATIVE_URLS)
    ap.add_argument("--out", default="docs/implementation/e2e-evidence.json")
    args = ap.parse_args(argv)

    token = os.environ.get("CRAWL4AI_API_TOKEN")
    if not token:
        print("CRAWL4AI_API_TOKEN is not set.", file=sys.stderr)
        return 2

    cfg = {"stream": False, "cache_mode": "bypass"}
    checks: dict[str, object] = {}
    failures: list[str] = []

    # Provenance must carry the version that actually served the run, so read it
    # from the live service rather than assuming the local checkout's version.
    health_status, health_body, _ = _request(
        args.base_url, "/health", None, None, 30, method="GET"
    )
    crawler_version = (
        (health_body or {}).get("version") if health_status == 200 else None
    )
    checks["health_status"] = health_status
    checks["crawler_version"] = crawler_version
    if not crawler_version:
        failures.append(
            f"could not read crawler version from /health (status {health_status})"
        )
        crawler_version = "unknown"
    else:
        print(f"[e2e] gateway reports version {crawler_version}")
        if version_tuple(crawler_version) < MIN_SAFE_VERSION:
            failures.append(
                f"AC-01: gateway reports {crawler_version}, below the minimum safe "
                f"{'.'.join(map(str, MIN_SAFE_VERSION))}"
            )

    # ── AC-03: authentication is mandatory ──────────────────────────────────
    print("[e2e] negative auth tests")
    no_tok, _, _ = crawl_once(args.base_url, None, args.urls[0], 30, cfg)
    bad_tok, _, _ = crawl_once(args.base_url, "not-the-token", args.urls[0], 30, cfg)
    checks["no_token_status"] = no_tok
    checks["bad_token_status"] = bad_tok
    if no_tok not in (401, 403):
        failures.append(
            f"AC-03: request with no token returned {no_tok}, expected 401/403"
        )
    if bad_tok not in (401, 403):
        failures.append(
            f"AC-03: request with a bad token returned {bad_tok}, expected 401/403"
        )

    # ── AC-04: the untrusted-config gate refuses laundered types ────────────
    print("[e2e] GHSA-5w5p laundering probe")
    probe_status, _, _ = crawl_once(
        args.base_url, token, args.urls[0], 60, LAUNDERING_PROBE_CONFIG
    )
    checks["laundering_probe_status"] = probe_status
    if probe_status != 400:
        failures.append(
            f"AC-04: dict-wrapped LLMConfig returned {probe_status}, expected 400 "
            "(GHSA-5w5p-vcv6-mm3f not closed)"
        )

    # ── representative workload ─────────────────────────────────────────────
    print(f"[e2e] {args.runs} representative runs")
    runs = []
    for i in range(args.runs):
        run, _ = run_with_retries(
            args.base_url,
            token,
            args.urls[i % len(args.urls)],
            args.timeout_s,
            cfg,
            crawler_version,
        )
        runs.append(run.to_dict())
        print(f"  {i + 1:>2}/{args.runs} {run.status:<16} {run.source_url}")

    succeeded = [r for r in runs if r["status"] == c.SUCCEEDED]
    checks["runs_total"] = len(runs)
    checks["runs_succeeded"] = len(succeeded)
    if len(succeeded) != len(runs):
        bad = [
            (r["status"], r["failure_class"])
            for r in runs
            if r["status"] != c.SUCCEEDED
        ]
        failures.append(
            f"{len(runs) - len(succeeded)} representative run(s) failed: {bad[:5]}"
        )

    # ── AC-09: provenance completeness ──────────────────────────────────────
    missing = [
        (r["run_id"], f)
        for r in runs
        for f in REQUIRED_PROVENANCE
        if f != "failure_class" and not r.get(f)
    ]
    checks["provenance_complete"] = not missing
    stale = {r["crawler_version"] for r in runs} - {crawler_version}
    if stale or crawler_version == "unknown":
        failures.append(
            f"AC-09: crawler_version not resolved from the service: {stale or crawler_version}"
        )
    if missing:
        failures.append(f"AC-09: provenance fields missing: {missing[:5]}")
    if len({r["run_id"] for r in runs}) != len(runs):
        failures.append("AC-09: run_ids are not unique")
    for r in runs:
        if c.raw_checksum(r["raw_response"]) != r["raw_checksum"]:
            failures.append(f"AC-09: checksum does not verify for {r['run_id']}")
            break

    # ── AC-10: forced failures are classified, never silent ─────────────────
    print("[e2e] forced failure tests")
    forced = {}

    # Terminal, non-retryable: a request the schema must reject.
    st, body, _ = _request(args.base_url, c.CRAWL_ENDPOINT, token, {"urls": []}, 30)
    cls = c.classify_response(st, body)
    forced["empty_urls"] = {
        "status": st,
        "class": cls.failure_class,
        "run_status": cls.status,
        "retryable": cls.retryable,
    }
    if cls.status != c.FAILED_TERMINAL or cls.retryable:
        failures.append(f"AC-10: empty urls list was not terminal (got {st}, {cls})")

    # Terminal: SSRF target must be refused, not crawled.
    run, st = run_with_retries(
        args.base_url,
        token,
        "http://169.254.169.254/latest/meta-data/",
        60,
        cfg,
        crawler_version,
        sleeper=lambda _s: None,
    )
    forced["ssrf_metadata"] = {
        "status": st,
        "run_status": run.status,
        "class": run.failure_class,
    }
    if run.status == c.SUCCEEDED:
        failures.append("AC-04/AC-10: cloud metadata endpoint was crawled successfully")

    # Terminal: malformed target URL.
    run, st = run_with_retries(
        args.base_url,
        token,
        "not-a-url",
        60,
        cfg,
        crawler_version,
        sleeper=lambda _s: None,
    )
    forced["invalid_url"] = {
        "status": st,
        "run_status": run.status,
        "class": run.failure_class,
    }
    if run.status == c.SUCCEEDED:
        failures.append("AC-10: an invalid URL reported success")

    checks["forced_failures"] = forced

    evidence = {
        "generated_at": _now(),
        "base_url": args.base_url,
        "checks": checks,
        "failures": failures,
        "runs": runs,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(evidence, fh, indent=2)

    print(f"\n[e2e] evidence -> {args.out}")
    print(f"[e2e] {len(succeeded)}/{len(runs)} representative runs succeeded")
    for f in failures:
        print(f"[e2e] FAIL: {f}")
    if failures:
        return 1
    print("[e2e] all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
