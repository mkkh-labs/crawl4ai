#!/usr/bin/env python3
"""
Prove the generated n8n workflow end to end in full isolation.

Starts a throwaway gateway (same image, seccomp profile and sandbox switch as
production) and a throwaway n8n (same image and SSRF settings as production,
its own SQLite, nothing shared with the live instance) on a private test
network. The token is generated for this run and discarded. Then it executes
the real workflow with the n8n CLI:

  S1 success      URL carries `?token=...`: succeeded, 1 attempt, token redacted,
                  checksum = contract.raw_checksum(raw.encode()), fingerprint matches
  S2 wrong token  failed_terminal/auth after exactly 1 attempt (no retry)
  S3 gateway down failed_terminal/network after exactly 3 attempts (bounded)
  S4 invalid URL  the run fails visibly and never calls the gateway

Usage:
    python deploy/n8n/workflow/isolated_e2e.py \
        --gateway-image crawl4ai-self-hosted:0.9.4 \
        --n8n-image lab/n8n:2.41.6-custom3 \
        --out docs/implementation/evidence-0.9.4/n8n-workflow-e2e.json

Exit 0 only when every scenario passes. Always removes what it created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import build_workflow as bw  # noqa: E402
import contract as c  # noqa: E402

RUN = "c4ai-wf-e2e-" + secrets.token_hex(3)
NET = RUN + "-net"
GW = RUN + "-gw"
N8N = RUN + "-n8n"
GOOD_CRED, BAD_CRED = "c4aiE2eGoodCred", "c4aiE2eBadCred1"


def sh(*args, check=True, timeout=600, stdin=None):
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
        input=stdin,
    )


def docker(*args, **kw):
    return sh("docker", *args, **kw)


def start_gateway(image: str, token: str) -> None:
    tmpfs = [
        "/tmp",
        "/var/lib/redis:uid=999,gid=999,mode=0700",
        "/var/lib/crawl4ai/outputs:uid=999,gid=999,mode=0700",
        "/home/appuser/.crawl4ai:uid=999,gid=999,mode=0700",
        "/home/appuser/.cache/url_seeder:uid=999,gid=999,mode=0700",
        "/home/appuser/.gunicorn:uid=999,gid=999,mode=0700",
    ]
    args = [
        "run",
        "-d",
        "--name",
        GW,
        "--network",
        NET,
        "--network-alias",
        "crawl4ai",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--security-opt",
        f"seccomp={os.path.join(REPO, 'deploy/docker/seccomp/chromium.json')}",
        "--shm-size",
        "1g",
        "--memory",
        "4g",
        "--pids-limit",
        "512",
        "-e",
        f"CRAWL4AI_API_TOKEN={token}",
        "-e",
        "CRAWL4AI_CHROMIUM_SANDBOX=true",
        "--user",
        "appuser",
    ]
    for t in tmpfs:
        args += ["--tmpfs", t]
    docker(*args, image)
    for _ in range(60):
        st = docker(
            "inspect", "-f", "{{.State.Health.Status}}", GW, check=False
        ).stdout.strip()
        if st == "healthy":
            return
        time.sleep(3)
    raise RuntimeError(f"test gateway never became healthy ({st})")


def start_n8n(image: str) -> None:
    docker(
        "run",
        "-d",
        "--name",
        N8N,
        "--network",
        NET,
        # Not read-only: the throwaway n8n *server* must start once to apply
        # publications, and it cannot under a read-only rootfs. This container
        # is an ephemeral test fixture; the production n8n is not changed.
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/home/node/.n8n:uid=1000,gid=1000",
        "-e",
        "DB_TYPE=sqlite",
        "-e",
        "N8N_DIAGNOSTICS_ENABLED=false",
        "-e",
        "N8N_SSRF_PROTECTION_ENABLED=true",
        "-e",
        "N8N_SSRF_ALLOWED_HOSTNAMES=crawl4ai",
        "-e",
        "N8N_RUNNERS_ENABLED=true",
        "--entrypoint",
        "sleep",
        image,
        "infinity",
    )


def n8n_cli(*args, stdin=None, check=True, timeout=600):
    return docker(
        "exec", "-i", N8N, "n8n", *args, stdin=stdin, check=check, timeout=timeout
    )


def put_file(path_in_container: str, content: str) -> None:
    docker("exec", "-i", N8N, "sh", "-c", f"cat > {path_in_container}", stdin=content)


def import_fixtures(token: str) -> None:
    creds = [
        {
            "id": cid,
            "name": f"Crawl4AI Gateway ({label})",
            "type": "httpHeaderAuth",
            "data": {"name": "Authorization", "value": f"Bearer {value}"},
        }
        for cid, label, value in (
            (GOOD_CRED, "good", token),
            (BAD_CRED, "wrong", "not-the-token"),
        )
    ]
    put_file("/tmp/creds.json", json.dumps(creds))
    n8n_cli("import:credentials", "--input=/tmp/creds.json")
    docker("exec", N8N, "rm", "-f", "/tmp/creds.json")
    for wid, cred, url in SCENARIOS:
        target = bw.build(cred)
        target["id"], target["active"] = wid, False
        put_file(f"/tmp/{wid}.json", json.dumps(target))
        n8n_cli("import:workflow", f"--input=/tmp/{wid}.json")
        # n8n 2.x only lets Execute Workflow call a published sub-workflow.
        n8n_cli("publish:workflow", f"--id={wid}")
        caller = caller_workflow(wid, url)
        put_file(f"/tmp/{caller['id']}.json", json.dumps(caller))
        n8n_cli("import:workflow", f"--input=/tmp/{caller['id']}.json")


#: (target workflow id, credential, url passed by the caller)
SCENARIOS = (
    (
        "c4aiE2eSuccess01",
        GOOD_CRED,
        "https://example.com/?token=SHOULD-BE-REDACTED&page=1",
    ),
    ("c4aiE2eWrongTok1", BAD_CRED, "https://example.com/"),
    ("c4aiE2eNoGateway", GOOD_CRED, "https://example.com/"),
    ("c4aiE2eInvalidUr", GOOD_CRED, "not-a-url"),
)


def caller_workflow(target_id: str, url: str) -> dict:
    """The production call path: a parent workflow runs the crawl workflow
    through an Execute Workflow node and receives the CrawlRun back."""
    return {
        "id": target_id[:-2] + "Cl",
        "name": f"caller for {target_id}",
        "active": False,
        "nodes": [
            {
                "parameters": {},
                "id": "start",
                "name": "Start",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [0, 0],
            },
            {
                "parameters": {
                    "workflowId": {"__rl": True, "value": target_id, "mode": "id"},
                    "workflowInputs": {
                        "mappingMode": "defineBelow",
                        "value": {"url": url},
                        "matchingColumns": [],
                        "schema": [
                            {
                                "id": "url",
                                "displayName": "url",
                                "required": False,
                                "defaultMatch": False,
                                "display": True,
                                "canBeUsedToMatch": True,
                                "type": "string",
                                "removed": False,
                            }
                        ],
                        "attemptToConvertTypes": False,
                        "convertFieldsToString": True,
                    },
                    "options": {},
                },
                "id": "call",
                "name": "Call crawl4ai",
                "type": "n8n-nodes-base.executeWorkflow",
                "typeVersion": 1.2,
                "position": [220, 0],
            },
        ],
        "connections": {
            "Start": {"main": [[{"node": "Call crawl4ai", "type": "main", "index": 0}]]}
        },
        "settings": {"executionOrder": "v1"},
    }


def process_publications() -> None:
    """Let the throwaway n8n server process the publication outbox.

    n8n 2.x records `publish:workflow` in an outbox that only the running
    server applies (polled every 15 s), and an Execute Workflow node can only
    call a published version. Start the server, wait for it to answer and for
    one poll cycle, then stop it before running executions from the CLI.
    """
    docker("exec", "-d", N8N, "sh", "-c", "n8n start > /tmp/n8n-server.log 2>&1")
    probe = (
        "fetch('http://127.0.0.1:5678/healthz')"
        ".then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
    )
    for _ in range(60):
        if docker("exec", N8N, "node", "-e", probe, check=False).returncode == 0:
            break
        time.sleep(3)
    else:
        raise RuntimeError("throwaway n8n server never became healthy")
    time.sleep(25)  # > one publication-outbox poll (15 s)
    docker("exec", N8N, "sh", "-c", "pkill -f 'n8n start' || true", check=False)
    for _ in range(20):
        if (
            docker(
                "exec", N8N, "sh", "-c", "pgrep -f 'n8n start'", check=False
            ).returncode
            != 0
        ):
            return
        time.sleep(1)
    raise RuntimeError("throwaway n8n server did not stop")


def execute(wid: str) -> tuple[int, dict | None, str]:
    """Run the caller for `wid`; return (exit code, CrawlRun or None, output tail)."""
    p = n8n_cli(
        "execute", f"--id={wid[:-2]}Cl", "--rawOutput", check=False, timeout=900
    )
    out = p.stdout
    start = out.find("{")
    record = None
    if start >= 0:
        try:
            data = json.loads(out[start:])
            run = data.get("data", {}).get("resultData", {}).get("runData", {})
            items = (
                run.get("Call crawl4ai", [{}])[-1].get("data", {}).get("main", [[]])[0]
            )
            record = items[0]["json"] if items else None
        except (ValueError, KeyError, IndexError, TypeError):
            record = None
    return p.returncode, record, (out + p.stderr)[-1500:]


def check(name: str, ok: bool, detail: str, results: list, tail: str = "") -> None:
    entry = {"scenario": name, "passed": bool(ok), "detail": detail}
    if not ok and tail:
        entry["cli_tail"] = tail  # n8n CLI output: execution data, never credentials
    results.append(entry)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gateway-image", required=True)
    ap.add_argument("--n8n-image", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    token = secrets.token_urlsafe(32)
    results: list = []
    records: dict = {}
    try:
        docker("network", "create", NET)
        start_gateway(args.gateway_image, token)
        start_n8n(args.n8n_image)
        import_fixtures(token)
        process_publications()
        expected_fp = c.config_fingerprint(bw.BROWSER_CONFIG, bw.CRAWLER_CONFIG)

        rc, rec, tail = execute("c4aiE2eSuccess01")
        records["S1"] = rec
        ok = bool(rec) and rec["status"] == c.SUCCEEDED and rec["attempts"] == 1
        if ok:
            raw = rec["raw_response"]
            want = "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
            ok = (
                rec["raw_checksum"] == want == c.raw_checksum(raw.encode("utf-8"))
                and rec["config_fingerprint"] == expected_fp
                and "SHOULD-BE-REDACTED" not in rec["source_url"]
                and "token=%5BREDACTED%5D" in rec["source_url"]
                and rec["crawler_version"] not in ("", "unknown")
                and bool((rec.get("markdown") or {}).get("text"))
            )
        check(
            "S1 success + provenance + redaction",
            ok,
            json.dumps(
                {
                    k: (rec or {}).get(k)
                    for k in ("status", "attempts", "source_url", "crawler_version")
                }
            ),
            results,
            tail,
        )

        rc, rec, tail = execute("c4aiE2eWrongTok1")
        records["S2"] = rec
        ok = (
            bool(rec)
            and rec["status"] == c.FAILED_TERMINAL
            and rec["failure_class"] == "auth"
            and rec["attempts"] == 1
        )
        check(
            "S2 wrong token: terminal auth, no retry",
            ok,
            json.dumps(
                {k: (rec or {}).get(k) for k in ("status", "failure_class", "attempts")}
            ),
            results,
            tail,
        )

        docker("stop", GW)
        t0 = time.time()
        rc, rec, tail = execute("c4aiE2eNoGateway")
        elapsed = round(time.time() - t0, 1)
        records["S3"] = rec
        ok = (
            bool(rec)
            and rec["status"] == c.FAILED_TERMINAL
            and rec["failure_class"] == "network"
            and rec["attempts"] == c.MAX_ATTEMPTS
            and len(rec["failures"]) == c.MAX_ATTEMPTS
            and rec["raw_response"] is None
            and rec["raw_checksum"] == c.raw_checksum(None)
        )
        check(
            "S3 gateway down: bounded retries then terminal network",
            ok,
            json.dumps(
                {k: (rec or {}).get(k) for k in ("status", "failure_class", "attempts")}
                | {"elapsed_s": elapsed}
            ),
            results,
            tail,
        )

        rc, rec, tail = execute("c4aiE2eInvalidUr")
        records["S4"] = rec
        ok = rc != 0 and rec is None and "absolute http(s) URL" in tail
        check("S4 invalid URL fails visibly", ok, f"exit={rc}", results)
    except Exception as exc:  # setup failure is a failed run, never a silent one
        check("setup", False, f"{type(exc).__name__}: {exc}", results)
    finally:
        for name in (N8N, GW):
            docker("rm", "-f", name, check=False)
        docker("network", "rm", NET, check=False)

    for rec in records.values():
        if isinstance(rec, dict) and isinstance(rec.get("raw_response"), str):
            rec["raw_response"] = (
                rec["raw_response"][:400] + "...(truncated in evidence)"
            )
    passed = bool(results) and all(r["passed"] for r in results)
    evidence = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gateway_image": args.gateway_image,
        "n8n_image": args.n8n_image,
        "isolation": "throwaway gateway + throwaway n8n (SQLite) on a private test network; one-time token, discarded",
        "verdict": "pass" if passed else "fail",
        "scenarios": results,
        "records": records,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(evidence, fh, indent=2)
    print(f"[n8n-e2e] {'all scenarios passed' if passed else 'FAILED'} -> {args.out}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
