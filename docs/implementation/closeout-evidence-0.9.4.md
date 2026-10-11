# Close-out evidence — v0.9.4 gateway (2026-10-09 → 2026-10-11)

**Provenance of this record.** Every value below was transcribed from command
output during the session that produced branch head `e94f670`. The raw
evidence JSON (`e2e-*.json`, `soak-*.json`) was written to a session scratchpad
that was cleared when the host restarted on 2026-10-11, so it is not attached.
To regenerate machine-readable evidence, run the gates in
`docs/RUNBOOK.md` → "Release gates to run before promotion".

## Artifacts

| Item | Value |
|---|---|
| Branch / PR | `build/crawl4ai-self-hosted-gateway` → [mkkh-labs/crawl4ai#1](https://github.com/mkkh-labs/crawl4ai/pull/1) (fork `main`; nothing sent to unclecode) |
| Upstream | v0.9.4 (`133e1d9`) merged; 44 upstream commits keep original signed SHAs |
| Gateway image | `crawl4ai-self-hosted:0.9.4` = `sha256:4e291bacd07d…` (includes the pool fix) |
| Rollback image | `crawl4ai-self-hosted:0.9.4-known-safe` = `sha256:a65730931d19…` (v0.9.4, pre pool fix; validated) |
| Console image | `crawl4ai-console:0.9.4` = `sha256:5a2ca37f9196…` |
| CI | Security + Supply chain: all 9 jobs green on `e94f670`; required on `main` via branch protection |

## Acceptance criteria

| AC | Criterion | Result | Evidence |
|---|---|---|---|
| AC-01 | v0.9.4-derived or newer-safe | **PASS** | `/health` → 0.9.4; E2E version-floor check passes |
| AC-02 | Security regression families pass | **PASS** | 639 passed, 6 skipped, 1 xfailed (offline docker + PDF + provenance + egress + robots + gateway suites) |
| AC-03 | No unauthenticated crawl access | **PASS** | no token 401, wrong token 401, bad Host 400; 0 host ports |
| AC-04 | Private/metadata destinations denied | **PASS** | metadata → 400 terminal; GHSA-5w5p laundering probe 200 on 0.9.3 → **400** on 0.9.4 |
| AC-05 | Memory and PID limits | **PASS** | cgroup `memory.max` 4294967296, `pids.max` 512 |
| AC-06 | Non-zero wall clock | **PASS** | `wall_clock_s: 300` in the shipped `/app/config.yml` |
| AC-07 | No `latest`; no upstream-image fallback | **PASS** | compose requires `IMAGE`; rendered-topology check rejects `unclecode/crawl4ai` |
| AC-08 | Deploy-equivalent suite | **PASS** | as AC-02; upstream live-Docker suites `test_[0-9]_*.py` and `test_monitor_demo.py` excluded (pre-existing, need a running server / async plugin) |
| AC-09 | Provenance across 20 runs | **PASS** | E2E from n8n's network namespace: 20/20, provenance complete, checksums verify |
| AC-10 | Forced failures not silent | **PASS** | empty urls 422, metadata 400, invalid URL 400 — all `failed_terminal/validation` |
| AC-11 | Processes return to a stable band | **PASS** | 60 jobs × concurrency 4, 720 s cooldown: baseline 6 → post 6 (band 12), RSS not rising, 0 unhealthy samples |
| AC-12 | Fidelity corpus | **PASS** | corpus runs the production `PruningContentFilterLXML`; LXML ≡ legacy output on all 5 fixtures (part of `tests/gateway`, 135 passed) |
| AC-13 | P0/P1 findings zero | **PASS (one documented waiver)** | Gateway image 26 → 1 finding: nltk PYSEC-2026-3740, no fix released, affected APIs never called; waiver lapses on fix or 2026-11-09. Console image 0 |
| AC-14 | Rollback tested | **PASS** | `0.9.4-known-safe` → healthy in 16.5 s; n8n reconnects |
| AC-15 | Production score ≥ 90/100 | **NOT SCORED** | no rubric supplied; not invented |

## Pool-signature fix (same 60 × 4 workload, n = 1 each)

| Metric | Before | After |
|---|---|---|
| Browser used | cold → hot second Chromium (60/60) | permanent browser (20/20 E2E) |
| Median / max latency | 1.85 s / 10.76 s | 0.47 s / 0.84 s |
| Throughput | 81.9 jobs/min | 391.2 jobs/min |
| Peak browser processes | 14 | 6 |
| Peak RSS | 638 MB | 569 MB |
| Soak verdict | FAIL (11 > band 10, 180 s cooldown) | PASS (6 ≤ band 12, 720 s cooldown) |

The two runs used different cooldowns. The latency and process-count deltas
come from the traffic phase, which the cooldown does not affect.

## n8n path (n8n-docker repo)

- n8n joins `automation_internal`, with `N8N_SSRF_ALLOWED_HOSTNAMES=crawl4ai`
  (exact name). Pre-change backup: `20261009-224919-pre-crawl4ai-network`.
- Isolated n8n 2.41.6 container, same SSRF env, HTTP Request node:
  `http://crawl4ai:11235/health` → 200; `http://169.254.169.254/…` →
  `SsrfBlockedIpError`; gateway by IP `172.26.0.2` → `SsrfBlockedIpError`.

## Image hygiene

| | 0.9.3 image | 0.9.4 image |
|---|---|---|
| Size | 7.84 GB | 5.9 GB |
| `/tmp/project` | 833 MB, incl. `.venv` + `.git` | 6.8 MB |
| Known vulns (`pip list --format=freeze`) | 26 in 5 packages | 1 (waived) |
