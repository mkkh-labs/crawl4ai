# DEPLOY evidence

Phase 5 of `docs/RUNBOOK.md`. Every result below was produced by running the
command, against the deployed artifact, on this host.

## Deployed artifact

| Item | Value |
|---|---|
| Branch | `build/crawl4ai-self-hosted-gateway` |
| Starting commit | `862f6bccb9c063f49b9d42701baa0eea17a4993f` |
| Final commit | `8f9349a0ee0adb13604dcac216d99379323f4716` |
| Image tag | `crawl4ai-self-hosted:0.9.3` |
| Image ID | `sha256:4e3ec44c1e538123318e0dc34bce79fe4e92db6c2d380b543ea38bff38f9d66f` |
| Rollback tag | `crawl4ai-self-hosted:0.9.3-known-safe` (same ID) |
| Version at `/health` | `0.9.3` |
| Network | `automation_internal` (bridge), service DNS `crawl4ai` |
| Config revision | `deploy/docker/config.yml` at the final commit |

Build: `docker build --build-arg C4AI_VER=0.9.3 --build-arg USE_LOCAL=true -t crawl4ai-self-hosted:0.9.3 .`

## Runtime posture (inspected, not asserted from the file)

```
memory_limit_bytes : 4294967296        cgroup memory.max : 4294967296
pids_limit         : 512               cgroup pids.max   : 512
read_only_rootfs   : true              privileged        : false
cap_drop           : [ALL]             cap_add           : []
security_opt       : [no-new-privileges:true]
user               : appuser           id                : uid=999 gid=999
restart_policy     : unless-stopped    docker socket     : not mounted
```

`docker port` reports no published ports; a host request to
`127.0.0.1:11235` gets no connection. A peer container on `automation_internal`
reaches `http://crawl4ai:11235/health` — the exact n8n path.

## Test results

| # | Command | Exit | Result |
|---|---|---:|---|
| 1 | `pytest deploy/docker/tests/test_security_*.py tests/unit/test_pdf_download_limits.py tests/unit/test_pdf_html_escaping.py -q` | 0 | 399 passed, 1 xfailed, 2.17s |
| 2 | `pytest tests/gateway -q` | 0 | 88 passed, 0.27s |
| 3 | `pytest tests/unit deploy/docker/tests -q` (7 daemon-dependent files ignored) | 1 | 479 passed, **1 failed**, 1 xfailed |
| 4 | `python -m compileall -q crawl4ai deploy/docker deploy/gateway deploy/n8n` | 0 | clean |
| 5 | `black --check` (gateway-owned files) | 0 | 10 files unchanged |
| 6 | `pip-audit --strict` | 1 | 1 finding (nltk, see below) |
| 7 | rendered-topology check | 0 | no host ports, private network, non-mutable tag |
| 8 | workflow pin scan | 0 | every action pinned to a 40-char SHA |

The single failure in (3) is `deploy/docker/tests/test_monitor_demo.py::test_dashboard`
(`async def` with no asyncio plugin config). It is **pre-existing**: it fails
identically on the unmodified tree with this build's changes stashed. Not caused
here and not fixed here (out of scope).

The 1 xfail is upstream's build-gated `test_no_no_sandbox_flag`. It is not one of
the five blocker families. See F-04 below.

## Five v0.9.3 security blocker families

| # | Family | Result |
|---|---|---|
| 1 | PDF arbitrary file/image write | **PASS** |
| 2 | PDF SSRF (redirect + final peer) | **PASS** |
| 3 | PDF DoS (byte / page / wall-clock caps) | **PASS** |
| 4 | PDF-generated HTML XSS escaping | **PASS** |
| 5 | Playground DOM XSS | **PASS** (test added by this build) |

No test was deleted, xfailed, weakened, or had a limit raised to make this green.
Family 5's new test was verified against the v0.9.2 asset: it fails 2 of 5 there
and passes 5 of 5 on the fixed asset, so it is a real guard.

## E2E (`deploy/gateway/e2e.py`, run from a peer on `automation_internal`)

```
gateway reports version 0.9.3
no token   -> 401        bad token -> 401
20/20 representative runs succeeded
provenance_complete: True    unique run_ids: 20/20
crawler_version in every run: 0.9.3
evidence contains "Bearer": False
```

Forced failures, none of which reported success:

| Forced case | HTTP | Run status | Class |
|---|---:|---|---|
| empty `urls` list | 422 | `failed_terminal` | `validation` |
| SSRF to `169.254.169.254` metadata | 400 | `failed_terminal` | `validation` |
| malformed URL | 400 | `failed_terminal` | `validation` |

Full record: `docs/implementation/e2e-evidence.json`.

## Soak (`deploy/gateway/soak.py`)

20 jobs, 4 baseline samples, 120s cooldown, 5s interval, `docker-exec` transport.

```
jobs 20 ok / 0 failed          latency_s min 0.242 median 0.284 max 0.371
browser processes: baseline 11 -> traffic 11 -> post-traffic 11
allowed post-traffic band (derived from this run's baseline): 22
RSS after traffic: 677 MB -> 645 MB   monotonic rising: False
unhealthy samples: 0            verdict: PASS
```

**Limitation, stated rather than glossed:** the process count was flat at 11
across all phases, so this run demonstrates no leak *under this workload* — 20
sequential jobs, 2 distinct URLs, no concurrency, ~5 minutes. It is not evidence
about behavior under production concurrency or over long duration. AC-11 is
recorded as PASS for the specified soak, and a concurrent/longer soak remains
worthwhile before heavy production load.

Full time series: `docs/implementation/soak-evidence.json`.

## Rollback drill

| Step | Result |
|---|---|
| Record safe artifact | `crawl4ai-self-hosted:0.9.3-known-safe` = `sha256:818e7236…` (pre-PyJWT-patch build) |
| Deploy a broken v0.9.3-derived variant | container `running`, health `unhealthy`, serves no traffic (curl 000) |
| Roll back to the safe artifact | completed in **9s** |
| Verify health | `{"status":"ok","version":"0.9.3"}` |
| Verify auth still enforced | no token -> 401 |
| Verify one crawl | HTTP 200, `"success":true` |

The rollback target was v0.9.3-derived. v0.9.2 was never a rollback target. The
broken drill image was deleted afterwards. The current safe tag was re-pointed to
the patched (PyJWT 2.13.0) image after the drill.

## Acceptance criteria

| ID | Criterion | Result | Evidence |
|---|---|---|---|
| AC-01 | Deployed code is v0.9.3 or newer-safe with all five fixes | **PASS** | `/health` reports 0.9.3; HEAD is v0.9.3 + docs-only commits |
| AC-02 | Five security regression families pass | **PASS** | 399 passed, families enumerated above |
| AC-03 | No unauthenticated production crawl access | **PASS** | no token 401, bad token 401; no host port published |
| AC-04 | Private/link-local/metadata destinations denied | **PASS** | metadata target refused (400) live; SSRF matrix in suite |
| AC-05 | Explicit memory and PID limits active | **PASS** | cgroup `memory.max` 4 GiB, `pids.max` 512 |
| AC-06 | Crawl wall-clock deadline non-zero | **PASS** | `wall_clock_s: 300` asserted in shipped config |
| AC-07 | Production does not use `latest` | **PASS** | rendered image `…:0.9.3`; compose default tag changed off `latest` |
| AC-08 | Deploy-equivalent suite passes | **PASS with one pre-existing failure** | see Test results (3) |
| AC-09 | Provenance fields present across 20 runs | **PASS** | 20/20 complete, checksums re-verify, version 0.9.3 |
| AC-10 | Forced failures create no silent path | **PASS** | three forced cases, all terminal and classified |
| AC-11 | Process count returns to stable band after soak | **PASS (limited workload)** | 11 → 11; see limitation above |
| AC-12 | Technical fixtures preserve critical code blocks | **PASS** | golden corpus, 88 tests |
| AC-13 | P0/P1 security findings are zero | **FAIL** | 19 findings (2026-10-01 re-audit); see correction below |
| AC-14 | Rollback to prior safe artifact tested | **PASS** | drill above, 9s |
| AC-15 | Revised production score ≥ 90/100 | **NOT SCORED** | no scoring rubric was supplied; not invented |

## AC-13 detail — the one failing gate

> **CORRECTION 2026-10-01.** The figures in this section were produced on 2026-09-06 by a
> `pip-audit` run that was partly served from a failing cache (it emitted
> `Cache entry deserialization failed, entry ignored`). A clean re-run on 2026-10-01 returned
> **19 findings across 4 packages**, including **13 against PyJWT 2.13.0 itself** — the version this
> build upgraded *to*. The analysis below is therefore superseded in its counts, though its
> reachability reasoning for nltk still holds. Current ground truth:
>
> | Package | Installed | Fix available | Findings |
> |---|---|---|---|
> | `pyjwt` | 2.13.0 | **2.15.0** | 13 (one, `CVE-2026-103001`, has no fix) |
> | `anyio` | 4.9.0 | **4.14.2** | 2 |
> | `urllib3` | 2.7.0 | **2.8.0** | 3 |
> | `nltk` | 3.10.3 | none | 1 (`PYSEC-2026-3740`) |
>
> AC-13 remains **FAIL**, now for a larger reason than recorded below. Remediation is task T1-1 of
> `CLOSEOUT-RUNBOOK.md`; the two unfixable advisories go to its owner-decision gate T2-GATE-1.
> This notice is deliberately additive — the original text is left intact so the correction is
> visible rather than silent.

`pip-audit --strict` originally reported **13 findings in 2 packages**.

**PyJWT 2.10.1 → 2.13.0 (12 findings, fixed).** Not dormant: `auth_gate._authenticate`
falls through to `jwt.decode()` with attacker-controlled bearer bytes on every
request whose token is not the static one, and `jwt_enabled: false` does not gate
that path (it gates `/token` minting). The advisories concern the
`PyJWK`/asymmetric verification path, which this codebase does not have — decode
uses a string secret with `algorithms` pinned to `["HS256"]` — so exploit
preconditions were not met, but running a known-vulnerable version on the auth
path was not defensible with a fix available. Security gate stays green on 2.13.0.

**nltk 3.10.3, PYSEC-2026-3740 — remains open.**

- `fix_versions` is empty. **No patched release exists**, so this cannot be
  remediated by upgrading. It is a genuine external blocker, not a deferral.
- Reachability checked, not assumed: the advisory affects `TransitionParser.train/parse`,
  `AveragedPerceptron.save/load`, `PerceptronTagger.save_to_json` and
  `save_maxent_params`, and requires the app to enable `pathsec` enforcement and
  let untrusted input choose model paths. **Zero references to any of those six
  APIs, or to `pathsec`, exist in `crawl4ai/` or `deploy/docker/`.** The codebase
  uses only `nltk.tokenize`, `nltk.stem`, `nltk.corpus`, `nltk.data.find` and
  `nltk.download`.
- Assessment: present in the image, not reachable from the gateway's request
  path. Residual risk accepted **as a documented decision, not a waiver**, and it
  must be re-evaluated when a patched nltk ships.

AC-13 as literally written ("P0/P1 findings are zero") is therefore **FAIL**, and
that is reported rather than reframed.

## Other open items

| ID | Item | Severity | State |
|---|---|---|---|
| F-04 | Chromium still runs with `--no-sandbox` (upstream xfail) | Medium, build-gated | Open. Needs an unprivileged userns or verified seccomp profile plus a build confirming Chromium starts. `CRAWL4AI_CHROMIUM_SANDBOX=true` is the opt-in; not flipped blind. |
| F-05 | `black --check crawl4ai deploy/docker tests` fails on pristine upstream (304/350 files) | Low | CI lint scoped to gateway-owned files; repo-wide reformat forbidden by the change policy. |
| F-06 | `test_monitor_demo.py::test_dashboard` fails (async plugin config) | Low | Pre-existing upstream; out of scope. |
| F-08 | Notion registry and Linear failure routing not configured | P1, not launch-blocking | `contract.py` produces the required data; no identifiers fabricated. |
| F-09 | M10 MCP pilot not attempted | P2 | Deferred by design; HTTP is the production path. |

## Scope note

The gateway was deployed and validated on this host. That is not the same as
promotion to the operator's production environment: n8n itself is not part of
this repository and was not connected. What is proven is that the artifact,
topology, auth, contract and rollback all behave as specified on the private
network the n8n stack is meant to share.
