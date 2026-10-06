# CLOSE-OUT RUNBOOK — Crawl4AI Self-Hosted Gateway

**Audience:** a fresh autonomous coding session (Codex) with shell + git + Docker access.
**Repo:** `mkkh-labs/crawl4ai` · **Branch:** `build/crawl4ai-self-hosted-gateway` · **Head at authoring:** `ca18033` (10 commits, unpushed)
**Authored:** 2026-10-01 · **Refreshed:** 2026-10-06 · **Prior state:** M1–M9 complete, DEPLOY validated on host, verdict CONDITIONAL GO (13/15 AC pass)

---

## 0. READ THIS FIRST — what "100% done" means here

Three of the open items **cannot** be closed by writing code, and a runbook that tells you to
grind until they are "done" will make you either loop forever or fabricate evidence. Both are
worse than stopping. So this runbook defines completion in two tiers:

| Tier | Definition | Who closes it |
|---|---|---|
| **T1 — Autonomously closeable** | Code, config, tests, evidence, documentation. Finish all of it without asking. | You (Codex) |
| **T2 — Owner-decision gates** | Items where no technical action exists, or the action is outward-facing/irreversible. Bring each to a single decision-ready question with the decision pre-drafted, then STOP on that item only. | Mikkoh Chen |

**You are done when: every T1 task passes its acceptance check, AND every T2 gate has a written,
evidence-backed decision memo awaiting one yes/no.** Do not treat a T2 gate as a reason to stop
T1 work — carry on with everything else.

**Hard prohibitions (violating any of these fails the engagement):**

1. Never fabricate a test result, scan result, version, SHA, score, or measurement. If you did not run it, say so.
2. Never delete, `xfail`, weaken, or raise a limit in a security test to make a gate green.
3. Never push, force-push, open a PR, or publish anything until T2-GATE-3 is explicitly approved.
4. Never roll back to v0.9.2, enable hooks/`execute_js`, publish a host crawler port, or use a `latest` tag.
5. Never invent a Notion/Linear/Drive/n8n identifier, or a production score, to fill a field.
6. Never mass-reformat upstream source (`black --check` fails on 304/350 pristine files by design — do not "fix" it).
7. Do not `git reset --hard`, `git clean -fdx`, or rewrite any commit that has been pushed.

---

## 1. ENVIRONMENT BOOTSTRAP (run first, every session)

```bash
cd /Users/mikkohchen/Developer/mkkh-labs/crawl4ai
git rev-parse --abbrev-ref HEAD          # expect build/crawl4ai-self-hosted-gateway
git status --short                        # expect empty
git log --oneline -1                      # record this SHA in your notes

# Python 3.11 venv (system python is 3.9, below the project floor)
[ -d .venv ] || uv venv --python 3.11 .venv
VIRTUAL_ENV=.venv uv pip install -q -e .
VIRTUAL_ENV=.venv uv pip install -q -r deploy/docker/requirements.txt pytest pytest-asyncio black pip-audit
.venv/bin/python -c "import crawl4ai,pytest,black; print('ok')"

# Docker (needed for T1-5..T1-8). Start Desktop if the daemon is down.
docker info >/dev/null 2>&1 || open -a Docker
until docker info >/dev/null 2>&1; do sleep 5; done
```

**Baseline regression check — run before any edit, and treat as the "before" value:**

```bash
.venv/bin/python -m pytest deploy/docker/tests/test_security_*.py \
  tests/unit/test_pdf_download_limits.py tests/unit/test_pdf_html_escaping.py -q
# EXPECT: 399 passed, 1 xfailed, exit 0
.venv/bin/python -m pytest tests/gateway -q
# EXPECT: 88 passed, exit 0
```

If either differs from the expected counts, **stop and diagnose before editing anything** — the
baseline has drifted and every later comparison is invalid.

---

## 2. TASK GRAPH

```
T1-1 dependency remediation ──┬── T1-5 rebuild image ── T1-6 redeploy ──┬── T1-7 E2E
T1-2 pin new SHAs ────────────┘                                          ├── T1-8 concurrent soak
T1-3 evidence correction ─────────── T1-4 docs truth pass                └── T1-9 rollback re-drill
                                                                              │
T1-10 full-suite sweep ───────────────────────────────────────────────────────┤
T1-11 close-out evidence pack ────────────────────────────────────────────────┘
                                   │
                        T2-GATE-1/2/3/4 decision memos
```

Order matters: **T1-1 and T1-2 must land before T1-5**, or the rebuilt image ships known-vulnerable
dependencies and every downstream result has to be thrown away.

---

## 3. T1 TASKS

### T1-1 — Dependency remediation (**highest priority; blocks AC-13**)

**Context you need:** this table drifts fast. It read **19 findings / 4 packages** on 2026-10-01
and **28 findings / 6 packages** on 2026-10-06 — +9 findings in five days, including a package that
was not previously implicated at all. An earlier run on 2026-09-06 reported just 1 because it was
served from a failing cache (`Cache entry deserialization failed`). **Treat every number below as
already stale and re-derive it in step 1.** Do not plan the work from this table.

Snapshot as of 2026-10-06:

| Package | Installed | Fix available | Findings | Pinned in |
|---|---|---|---|---|
| `pyjwt` | 2.13.0 | **2.15.0** | 14 (one, `PYSEC-2026-4146`, has **no fix**) | `deploy/docker/requirements.txt:13` |
| `pypdf` | 6.17.0 | **6.19.0** | 7 | transitive (PDF processor) |
| `urllib3` | 2.7.0 | **2.8.0** | 3 | transitive |
| `anyio` | 4.9.0 | **4.14.2** | 2 | `deploy/docker/requirements.txt:12` |
| `multidict` | 6.7.1 | **6.9.1** | 1 | transitive |
| `nltk` | 3.10.3 | **none** | 1 (`PYSEC-2026-3740`) | `requirements.txt:25`, `pyproject.toml:37` |

**`pypdf` is the one to handle most carefully.** It is the parser behind
`crawl4ai/processors/pdf/`, which is exactly where four of the five v0.9.3 blocker families live
(arbitrary image write, SSRF, byte/page caps, HTML escaping). A pypdf major-minor bump can change
page-count and parsing behavior, so after bumping it you must re-run the PDF families specifically
and compare against the pre-bump baseline, not just the aggregate count:

```bash
.venv/bin/python -m pytest tests/unit/test_pdf_download_limits.py \
  tests/unit/test_pdf_html_escaping.py \
  deploy/docker/tests/test_security_pdf_image_write.py -q
```

If a PDF security test fails after the pypdf bump, that is a **blocking finding**, not a test to
adjust. Report it, pin pypdf at the last good version, and raise it at T2-GATE-1.

**Steps:**

1. Re-run the audit yourself and save the ground truth — never work from the table above:
   ```bash
   .venv/bin/pip-audit --strict --progress-spinner=off --format json \
     > docs/implementation/audit-before.json 2>/dev/null; echo "exit=$?"
   ```
2. Raise the three fixable pins. `pyjwt` and `anyio` are hard-pinned; edit them in
   `deploy/docker/requirements.txt`. `urllib3` is transitive — add an explicit floor
   (`urllib3>=2.8.0`) in the same file, with a one-line comment saying why.
3. Install and re-audit:
   ```bash
   VIRTUAL_ENV=.venv uv pip install -q -r deploy/docker/requirements.txt
   .venv/bin/pip-audit --strict --progress-spinner=off --format json \
     > docs/implementation/audit-after.json 2>/dev/null; echo "exit=$?"
   ```
4. **Full regression after the bump** (PyJWT is on the auth path — this is not cosmetic):
   ```bash
   .venv/bin/python -m pytest deploy/docker/tests/test_security_*.py \
     tests/unit/test_pdf_download_limits.py tests/unit/test_pdf_html_escaping.py -q
   .venv/bin/python -m pytest deploy/docker/tests/test_security_authz.py \
     deploy/docker/tests/test_security_default_posture.py -q
   ```
5. If PyJWT 2.15.0 breaks `decode_token` in `deploy/docker/auth.py`, **fix the call site, do not
   downgrade**. The decode is `jwt.decode(token, SECRET_KEY, algorithms=["HS256"])` with a string
   secret and no JWK path; a 2.x API change here is small and local.

**Acceptance (all must hold):**
- [ ] `audit-after.json` contains **only** advisories whose `fix_versions` is empty. Every finding
      with an available fix must be gone. Do not match against a hardcoded ID list — IDs change
      (the no-fix pyjwt advisory was `CVE-2026-103001` on 10-01 and `PYSEC-2026-4146` on 10-06).
- [ ] For each remaining finding, print its `fix_versions` to prove unfixability rather than asserting it.
- [ ] Security gate still 399 passed / 1 xfailed, exit 0.
- [ ] No test was altered.

**Then feed T2-GATE-1** with the two residual advisories.

**Failure mode:** a bump breaks an unrelated subsystem. Contingency — bump packages **one at a
time**, running the security gate between each, so you can attribute the break. If `anyio` conflicts
with the `fastapi>=0.115.12,<0.137` ceiling, report the conflict and leave `anyio` pinned rather
than widening the FastAPI ceiling.

### T1-2 — Re-verify and re-pin GitHub Action SHAs

Pins were resolved on 2026-09-06 and may be stale. For every `uses:` in every enabled workflow:

```bash
grep -rn 'uses:' .github/workflows/*.yml
# For each repo@sha, confirm the SHA still belongs to the tag it claims:
gh api repos/<owner>/<repo>/git/ref/tags/<tag> --jq '.object.sha'
gh api repos/<owner>/<repo>/tags --jq '[.[]|select(.commit.sha=="<sha>")|.name]|join(" ")'
```

**Acceptance:** every action pinned to a 40-char SHA; every SHA confirmed against a real tag via the
API; the trailing `# vX.Y.Z` comment matches what the API returned. **Never hand-write a SHA.**
`grep -rn 'uses:' .github/workflows/*.yml | grep -vE '@[0-9a-f]{40}'` returns nothing.

### T1-3 — Correct the stale AC-13 section in the evidence pack

`docs/implementation/deploy-evidence.md` currently states the PyJWT bump cleared the dependency
gate and that one finding remains. That was true against cached advisory data and is now **false**.
Rewrite the "AC-13 detail" section from `audit-before.json` / `audit-after.json`. State plainly that
the earlier figure came from a stale cache. Do not quietly overwrite the number — a reader comparing
versions must see that it was corrected and why.

**Acceptance:** no claim in that file contradicts `audit-after.json`; the correction is visible, not silent.

### T1-4 — Repository truth pass

Re-read `CLAUDE.md`, `SPEC.md`, `docs/RUNBOOK.md`, `deploy/n8n/README.md` and every file in
`docs/implementation/`. Fix any statement contradicted by the current tree. Known candidates:
the elapsed `2026-09-10` target date, AC counts, dependency versions, image IDs.

**Acceptance:** every version, SHA, count and date in docs matches a command you ran this session.

### T1-5 — Rebuild the image

```bash
docker build --build-arg C4AI_VER=0.9.3 --build-arg USE_LOCAL=true \
  -t crawl4ai-self-hosted:0.9.3 .
docker run --rm --entrypoint sh crawl4ai-self-hosted:0.9.3 \
  -c 'pip show pyjwt anyio urllib3 nltk | grep -E "^Name|^Version"'
```

**Acceptance:** the image reports the upgraded versions from T1-1. If it does not, the build used a
cached layer — rebuild with `--no-cache` on the dependency stage.

### T1-6 — Redeploy privately

```bash
export CRAWL4AI_API_TOKEN="$(openssl rand -hex 32)"   # never commit or echo this
docker network inspect automation_internal >/dev/null 2>&1 || docker network create automation_internal
IMAGE=crawl4ai-self-hosted:0.9.3 docker compose up -d crawl4ai
until [ "$(docker inspect -f '{{.State.Health.Status}}' crawl4ai-crawl4ai-1)" = healthy ]; do sleep 5; done
docker port crawl4ai-crawl4ai-1          # MUST be empty
docker run --rm --network automation_internal curlimages/curl:latest -fsS http://crawl4ai:11235/health
```

**Acceptance:** healthy; zero published ports; `crawl4ai:11235` reachable from a network peer and
reporting `0.9.3`; `docker compose config` fails with no token set.

### T1-7 — Re-run E2E

```bash
docker run --rm --network automation_internal -e CRAWL4AI_API_TOKEN \
  --user "$(id -u):$(id -g)" -v "$PWD:/w" -w /w python:3.11-slim \
  python deploy/gateway/e2e.py --base-url http://crawl4ai:11235 --runs 20 \
    --out docs/implementation/e2e-evidence.json
```

**Acceptance:** exit 0; 20/20 succeeded; `provenance_complete: true`; `crawler_version` = `0.9.3` in
every run; no-token and bad-token both 401/403; all three forced failures `failed_terminal`;
`"Bearer"` absent from the evidence file.

### T1-8 — Concurrent soak (**the one genuinely missing measurement**)

The soak that passed ran 20 *sequential* jobs over 2 URLs. Browser process count was flat at 11 the
whole time, which means the pool was never pressured — it is evidence of no leak **under no load**.
That is the weakest claim in the whole evidence pack.

Extend `deploy/gateway/soak.py` with a `--concurrency N` flag (default 1, preserving current
behavior) that issues N crawls in flight via a thread pool, then:

```bash
.venv/bin/python deploy/gateway/soak.py --container crawl4ai-crawl4ai-1 \
  --jobs 60 --concurrency 5 --cooldown-s 300 --sample-interval-s 5 --baseline-samples 6 \
  --out docs/implementation/soak-evidence-concurrent.json
```

**Acceptance:** exit 0; **browser process count must actually rise above baseline during traffic**
(if it stays flat at 5-way concurrency the harness is not pressuring the pool — fix the harness, do
not accept the pass); count returns inside the baseline-derived band during cooldown; RSS not
monotonically rising; zero unhealthy samples; `jobs_failed == 0`.

Keep the existing sequential evidence file. Two data points beat one overwritten one.

**Failure mode:** processes do **not** return to band → that is a real leak and a P0 production
blocker. Do not relax the band. Capture the series, file it as a finding, raise it at T2-GATE-4, and
record AC-11 as FAIL.

### T1-9 — Rollback re-drill against the new artifact

Repeat the drill that passed before, with the rebuilt image as the safe target:
tag `:0.9.3-known-safe` → build a deliberately broken derived image (corrupt `/app/config.yml`) →
deploy it → confirm `unhealthy` and no traffic → redeploy the safe tag → verify health, 401 without
token, and one 200 crawl → record from/to IDs and elapsed seconds → delete the broken image.

**Acceptance:** rollback completes; all three post-checks pass; target is v0.9.3-derived.

### T1-10 — Full-suite sweep

```bash
.venv/bin/python -m pytest tests/unit deploy/docker/tests -q \
  $(for f in 1_basic 2_memory 3_pool 4_concurrent 5_pool_stress 6_multi_endpoint 7_cleanup; \
    do echo --ignore=deploy/docker/tests/test_$f.py; done)
.venv/bin/python -m compileall -q crawl4ai deploy/docker deploy/gateway deploy/n8n
.venv/bin/python -m black --check deploy/gateway deploy/n8n tests/gateway \
  deploy/docker/tests/test_security_gateway_topology.py \
  deploy/docker/tests/test_security_playground_dom_xss.py \
  deploy/docker/tests/test_security_observability.py
```

Two **known pre-existing** conditions — confirm they are unchanged, do not "fix" them:
`test_monitor_demo.py::test_dashboard` fails (async plugin config) and the 7 ignored files need the
`docker` Python SDK. Verify pre-existence by stashing your changes and re-running.

**Optional, high value:** the 7 ignored files are integration tests that *can* run now that the
daemon is up. `VIRTUAL_ENV=.venv uv pip install -q docker` then run them. If they pass, that is new
coverage; if they fail, triage whether it is environmental before reporting anything.

### T1-11 — Close-out evidence pack

Rewrite `docs/implementation/deploy-evidence.md` and `handoff.md` from this session's actual output.
Every row must cite a command and its exit status. Produce the final AC-01..AC-15 table with exactly
one of `PASS` / `FAIL` / `BLOCKED` / `NOT SCORED` per row and no aggregate that hides a failure.

Commit in coherent units, one concern each, `type(scope): imperative summary`, ending with:
`Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

## 4. T2 — OWNER-DECISION GATES (prepare, then stop on that item)

Write each as a short memo in `docs/implementation/decisions/`. Present options, your
recommendation, and the consequence of each. Do not decide. Do not proceed past the gate.

### T2-GATE-1 — Residual unpatchable dependency risk (blocks AC-13)

Two advisories have **no patched release in existence**: `nltk PYSEC-2026-3740` and
`pyjwt CVE-2026-103001`. No amount of work closes them.

Your job: for **each**, prove reachability from the gateway's request path rather than asserting it.
For nltk, the prior finding was zero references to any of the six affected APIs
(`TransitionParser.train/parse`, `AveragedPerceptron.save/load`, `PerceptronTagger.save_to_json`,
`save_maxent_params`) or to `pathsec` — re-verify, do not inherit. For the pyjwt CVE, read the
advisory, identify its precondition, and check it against `deploy/docker/auth.py` and `auth_gate.py`.

Memo must offer exactly: **(a)** accept residual risk with a written re-evaluation trigger,
**(b)** block promotion until upstream patches, **(c)** remove/replace the dependency.
State the cost of each. AC-13 stays **FAIL** until the owner picks one.

### T2-GATE-2 — AC-15 production score (blocks AC-15)

No scoring rubric was ever supplied with the strategy or execution pack. **Do not invent one** — a
fabricated score in a release record is exactly the kind of thing that fails an audit.
Memo offers: **(a)** owner supplies the rubric and you compute it, or **(b)** AC-15 is struck as
unspecified with that fact recorded. Until then AC-15 is `NOT SCORED`, never `PASS`.

### T2-GATE-3 — Push, PR, and promotion authorization

The branch has never left the machine. Pushing and opening a PR are outward-facing and need explicit
approval. Prepare but **do not run**: the push command, a PR title/body (ending
`🤖 Generated with [Claude Code](https://claude.com/claude-code)`), and the expected CI outcome —
note that `dependency-scan` will be **red** while T2-GATE-1 is unresolved, and say so in the PR body
rather than letting a reviewer discover it.

### T2-GATE-4 — n8n connection and production promotion

n8n is deliberately **not** in this repository and was never connected. Everything proven so far is
gateway-side. Memo must state what remains unproven without it: a real n8n credential-store token,
`e2e.py` run from the n8n host, and the Notion/Linear routing (P1, unconfigured — invent no
identifiers). Plus any T1-8 leak finding.

---

## 5. SELF-VERIFICATION (run before declaring done)

```bash
# 1. No fabricated SHAs in workflows
grep -rn 'uses:' .github/workflows/*.yml | grep -vE '@[0-9a-f]{40}' && echo FAIL || echo OK
# 2. No secret committed anywhere on the branch
git diff origin/main..HEAD | grep -iE '^\+.*(bearer [A-Za-z0-9_-]{12}|sk-[A-Za-z0-9]{16}|PRIVATE KEY)'
# 3. The live token never entered the repo
grep -rq "$CRAWL4AI_API_TOKEN" . --exclude-dir=.git --exclude-dir=.venv && echo FAIL || echo OK
# 4. Rendered topology is still private
CRAWL4AI_API_TOKEN=x docker compose config | .venv/bin/python deploy/gateway/check_rendered_topology.py
# 5. Compose still fails closed
env -u CRAWL4AI_API_TOKEN docker compose config >/dev/null 2>&1 && echo FAIL || echo OK
# 6. No security test weakened
git diff origin/main..HEAD -- deploy/docker/tests tests/unit | grep -E '^-.*(assert|xfail|def test_)'
# 7. Working tree clean, every change committed
git status --short
```

Checks 1, 3, 4, 5 must print `OK` / succeed. Checks 2 and 6 must print nothing. Any deviation ⇒ not done.

**Evidence integrity rule:** for every PASS you report, name the command and its exit status. If you
cannot, the correct value is `BLOCKED`, not `PASS`.

---

## 6. DEFINITION OF DONE

| # | Condition | Verify with |
|---|---|---|
| 1 | T1-1..T1-11 each meet their acceptance checks | this file, per task |
| 2 | Security gate 399+ passed, 1 xfailed, exit 0, no test altered | §1 baseline command |
| 3 | `pip-audit` findings reduced to the two provably unfixable advisories | `audit-after.json` |
| 4 | Image, deployment, E2E, concurrent soak, rollback all re-verified post-upgrade | T1-5..T1-9 |
| 5 | Every doc claim matches a command run this session | T1-4, T1-11 |
| 6 | Four T2 memos written, each with options + recommendation + consequences | `docs/implementation/decisions/` |
| 7 | All seven self-verification checks clean | §5 |
| 8 | Working tree clean; nothing pushed | `git status`, `git branch -r --contains HEAD` |

**Then stop and report.** Final output: the AC-01..AC-15 table, the four decision memos, exact
commands with exit statuses, and a one-line verdict of `GO` / `CONDITIONAL GO` / `NO-GO` with
reasoning. Expected realistic verdict: **CONDITIONAL GO**, because AC-13 and AC-15 are owner
decisions and AC-11's strength depends on what the concurrent soak finds.

Claiming `GO` while a T2 gate is open, or while any number in the evidence pack is unverified, is
the single worst outcome available to you. A precise `CONDITIONAL GO` is a success.
