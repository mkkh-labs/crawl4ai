# Close-out evidence — v0.9.4 gateway (final, 2026-10-11)

Machine-readable evidence lives in [`evidence-0.9.4/`](evidence-0.9.4/) (see its
README for provenance). Values below either cite a file there or a command run
on 2026-10-11 against the deployed image. Earlier numbers from 2026-10-10 that
were only transcribed are marked *(transcribed)*.

## Artifacts

| Item | Value |
|---|---|
| Release image | `crawl4ai-self-hosted:0.9.4` = `sha256:459878969baf…` (v0.9.4 + pool fix + renderer sandbox) |
| Rollback image | `crawl4ai-self-hosted:0.9.4-known-safe` = `sha256:4e291bacd07d…` (v0.9.4 + pool fix; validated 2026-10-10) |
| Console image | `crawl4ai-console:0.9.4` |
| Seccomp profile | `deploy/docker/seccomp/chromium.json`, generated from moby `docker-v29.8.2` default (sha256 `536529b6…`) |
| n8n workflow | `deploy/n8n/workflow/crawl4ai-crawl.workflow.json` (generated) |
| PR | [mkkh-labs/crawl4ai#1](https://github.com/mkkh-labs/crawl4ai/pull/1) into the fork's `main` (nothing sent to unclecode) |

## Acceptance criteria

| AC | Criterion | Result | Evidence |
|---|---|---|---|
| AC-01 | v0.9.4-derived or newer-safe | **PASS** | `/health` 0.9.4 = latest upstream release (v0.9.4, 2026-09-23); `e2e-n8n-netns.json` version floor |
| AC-02 | Security regression families pass | **PASS** | offline suite 673 passed, 6 skipped (Python 3.14-only robots cases), 1 xfailed; CI `blocker-families` green |
| AC-03 | No unauthenticated crawl access | **PASS** | `console-selftest.json` (no token 401, wrong token 401); bad Host 400; 0 host ports |
| AC-04 | Private/metadata destinations denied | **PASS** | `console-selftest.json`: GHSA-5w5p probe 400, metadata 400 |
| AC-05 | Memory and PID limits | **PASS** | live `memory.max` 4294967296, `pids.max` 512 |
| AC-06 | Non-zero wall clock | **PASS** | `wall_clock_s: 300` in `/app/config.yml` |
| AC-07 | No `latest`; no upstream fallback | **PASS** | compose requires `IMAGE`; CI fail-closed render checks |
| AC-08 | Deploy-equivalent suite | **PASS** | as AC-02; upstream live-Docker suites `test_[0-9]_*.py` and `test_monitor_demo.py` excluded (pre-existing) |
| AC-09 | Provenance across 20 runs | **PASS** | `e2e-n8n-netns.json`: 20/20, provenance complete, checksums verify |
| AC-10 | Forced failures not silent | **PASS** | `e2e-n8n-netns.json` forced cases; `n8n-workflow-e2e.json` S2–S4 |
| AC-11 | Processes return to stable band | **PASS** | `soak-60x4.json`: baseline 7 → post 8 (band 14), RSS falling, 0 unhealthy |
| AC-12 | Fidelity corpus | **PASS** | production LXML filter; LXML ≡ legacy on all fixtures |
| AC-13 | P0/P1 findings zero | **PASS (1 waiver)** | `pip-audit-*.json`: gateway 1 finding (nltk PYSEC-2026-3740, no fix, unreachable, lapses 2026-11-09); console 0 |
| AC-14 | Rollback tested | **PASS** | `rollback-drill.json`: 7.1 s to healthy, n8n 200; roll-forward 6.8 s |
| AC-15 | Production score ≥ 90/100 | **PASS: 98.0** | scorecard below; rubric fixed in `production-score.md` before scoring |

## F-04 closed: Chromium renderer sandbox

`--no-sandbox` was hard-coded in every launch path, and Playwright adds it again
unless asked not to, so the old opt-in never worked. The gateway now runs the
sandbox under a seccomp profile derived from Docker's default. That profile
adds only clone/unshare for USER/PID/NET namespaces and chroot, and denies
netfilter netlink. Mount, UTS, IPC and cgroup namespaces stay blocked.

`sandbox-verify.json`, identifying processes by `/proc/<pid>/exe`:

- no Chromium process has `--no-sandbox`;
- zygotes and renderers run in their own user namespace;
- the renderer is at PID-namespace depth 3, with Seccomp 2.

## Docker Desktop instability (environment, not the gateway)

On 2026-10-11 Docker Desktop on this host was repeatedly stopped or unreachable:

- the VM was stopped at 15:05;
- the host could not reach the VM from 15:11 to 15:17, from 15:35 to 15:45, and from 15:57 to 16:00;
- an external Docker Desktop CLI client sent `POST /app/quit` at 16:03:41;
- a graceful `SIGTERM` stopped the gateway at 16:05:20, and it was started again at 16:08:17.

This work issued none of these. The first unreachable window began before the
custom seccomp profile was first used. From 16:05 onwards, with the sandbox on
and two isolated runs starting extra sandboxed gateways, there were no
host-unreachable events. An in-VM heartbeat returned 200 continuously once the
gateway was restarted.

Effect on evidence: the soak harness now scores a sample whose `docker exec`
fails as *unobserved*, not as gateway health, and fails a phase where more than
20% of samples are unobserved. The final soak had 5/64 unobserved.

## n8n

- **Production wiring** (n8n-docker): n8n joins `automation_internal`, with
  `N8N_SSRF_ALLOWED_HOSTNAMES=crawl4ai`. Merged into the repo's local `main`;
  not pushed, because the remote belongs to another organization.
- **Workflow** (`deploy/n8n/workflow`): proven in a real n8n 2.41.6
  (`n8n-workflow-e2e.json`), called through *Execute Workflow*, the production
  path:

  | Scenario | Result |
  |---|---|
  | S1 success | succeeded; checksum = `contract.raw_checksum(raw.encode())`; fingerprint matches; token redacted |
  | S2 wrong token | `auth`, 1 attempt |
  | S3 gateway down | `network`, 3 attempts |
  | S4 invalid URL | fails visibly |
  | S5 SSRF scope | `crawl4ai` by name allowed; gateway by IP and 169.254.169.254 blocked |

## Pool-signature fix (same 60 × 4 workload)

| Metric | Before fix *(transcribed)* | After fix *(transcribed)* | Final image (`soak-60x4.json`) |
|---|---|---|---|
| Browser used | second Chromium, 60/60 | permanent | permanent |
| Median latency | 1.85 s | 0.47 s | 0.89 s |
| Throughput | 81.9 jobs/min | 391.2 jobs/min | 177.2 jobs/min |
| Peak browser processes | 14 | 6 | 13 |
| Verdict | FAIL | PASS | PASS |

The final run was taken on a host under heavy memory pressure (about 8 GB
compressed) with Docker Desktop flapping. The sandbox adds per-renderer zygote
processes, which explains the higher process peak. Latency and throughput are
not comparable across these runs, so no performance claim is made from them.

## Production score (AC-15)

Rubric: `production-score.md` (committed in `a833b16`, before scoring). Gate:
no release blocker is present.

| Dim | Checks passed | Score | Failing check |
|---|---|---|---|
| D1 Supply-chain currency | 5/5 | 10.0 | |
| D2 Exposure and authN | 5/5 | 10.0 | |
| D3 Untrusted input and egress | 4/4 | 10.0 | |
| D4 Runtime isolation | 5/5 | 10.0 | |
| D5 Resource bounds | 4/4 | 10.0 | |
| D6 Integration | 4/5 | 8.0 | (e) no execution of the **production** n8n workflow with the **production** credential: entering the token into n8n is an owner action |
| D7 Fidelity and provenance | 4/4 | 10.0 | |
| D8 Operability | 4/4 | 10.0 | |
| D9 Verification and CI | 4/4 | 10.0 | (a) is recorded against the final release head in the PR |
| D10 Evidence and governance | 4/4 | 10.0 | |
| **Total** | | **98.0 / 100** | |

**Confidence: high.** Every passing check has a live command, test, CI job or
JSON file behind it, and the one failing check is reported as failing. The
score would rise to 100 once the owner configures the credential and runs the
smoke test in `deploy/n8n/workflow/README.md`.
