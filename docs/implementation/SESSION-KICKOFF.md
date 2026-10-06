# SESSION KICKOFF — Crawl4AI Gateway close-out

**You are the execution session.** Your job is to finish `docs/implementation/CLOSEOUT-RUNBOOK.md`.
This file is context and protocol; the runbook is the work. Read both before your first edit.

---

## 1. Where things stand (verified 2026-10-06)

| Fact | Value |
|---|---|
| Repo | `mkkh-labs/crawl4ai` (fork of `unclecode/crawl4ai`) |
| Branch | `build/crawl4ai-self-hosted-gateway` |
| Head | `8316e89` — 12 commits ahead of `origin/main`, **never pushed** |
| Audited baseline | `audit/v0.9.2-20260903` at `7e80152` (= the `v0.9.2` tag) |
| Upstream position | `v0.9.3` + 4 upstream **docs-only** commits |
| Runtime version | `0.9.3` (confirmed via `/health`) |
| Container | `crawl4ai-crawl4ai-1` running + healthy on `automation_internal`, zero published ports |
| Verdict | **CONDITIONAL GO** — 13/15 AC pass, AC-13 FAIL, AC-15 NOT SCORED |
| Modules | M1–M9 complete; M10 (MCP) deferred, P2, post-launch |

**What this project is:** a private, authenticated Crawl4AI HTTP gateway that n8n calls at
`http://crawl4ai:11235` over a Docker network. Not a public SaaS. Not a crawler rewrite. n8n is
**not** in this repository and has never been connected.

**What was actually built** (10 commits of substance): the Playground DOM-XSS regression test that
upstream shipped without; private compose topology with a mandatory token; explicit `trusted_hosts`;
Redis-backed limiter; the n8n contract + provenance envelope + failure taxonomy in `deploy/n8n/`; an
offline fidelity corpus; a soak harness; SHA-pinned CI with the mutable Discord workflow disabled.

---

## 2. The two findings that define the remaining work

**(a) CI was not running two of the five security blocker families.** PDF DoS and PDF HTML escaping
live under `tests/unit/`, outside the `deploy/docker/tests/test_security_*.py` glob the workflow
used. Fixed by the `blocker-families` job. Mentioned because it is the pattern to watch for: a gate
that reports green on evidence it never collected.

**(b) The dependency audit drifts weekly and was once read from a stale cache.**
1 finding (2026-09-06, cached — wrong) → 19 (2026-10-01) → 28 (2026-10-06).
**Never trust a dependency number written in this repo. Re-derive it.** `pypdf` entered the set on
10-06 with 7 findings and sits under `crawl4ai/processors/pdf/`, where four of the five blocker
families live.

---

## 3. Reading order (do not skip)

1. `CLAUDE.md` — operating contract, NEVER-run rules, canonical commands
2. `SPEC.md` — modules M1–M10, API + provenance contracts
3. `docs/implementation/CLOSEOUT-RUNBOOK.md` — **your task list**
4. `docs/implementation/deploy-evidence.md` — AC-01..15 results (note its AC-13 correction notice)
5. `docs/implementation/handoff.md` — prior session's state
6. `docs/RUNBOOK.md`, `docs/implementation/{scan,assess}-evidence.md`, `plan.md` — background

---

## 4. Protocol

**P1 — Establish ground truth before acting.** Run the §1 bootstrap and baseline in the runbook.
Expect `399 passed, 1 xfailed` and `88 passed`. If either differs, stop and diagnose: the baseline
has drifted and every later comparison is void.

**P2 — One concern per commit.** `type(scope): imperative summary`, body explaining *why*, ending
`Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Commit working increments; do not
accumulate a mega-diff.

**P3 — Measure, never assert.** Every PASS you report names a command and its exit status. If you
did not run it, the value is `BLOCKED`, not `PASS`. No invented SHAs, scores, versions, or counts.

**P4 — Never weaken a control to get green.** No deleting, `xfail`-ing, or loosening a security
test; no raising a limit; no widening `trusted_hosts`; no publishing a host port. If a security test
fails after a dependency bump, that is a blocking finding — pin back and escalate.

**P5 — Respect the T1/T2 split.** T1 is yours to finish without asking. T2 are four gates no code
can close (two advisories with no patched release, an AC with no rubric, pushing the branch,
connecting n8n). Bring each to a decision memo in `docs/implementation/decisions/` and stop on that
item only — keep working everything else.

**P6 — Do not push or publish.** The branch stays local until T2-GATE-3 is approved. No `git push`,
no PR, no force-push, no history rewrite of anything already pushed.

**P7 — Report drift honestly.** If you find that something I recorded is wrong, say so plainly and
correct it additively so the change is visible, not silent. That happened twice already and both
times mattered more than the original number.

**P8 — Checkpoint.** Before ending your session, update `docs/implementation/handoff.md` with:
current phase, exact head SHA, files changed, tests run with results, open failures, next atomic
action. Commit it.

---

## 5. Definition of done

Every T1 task in the runbook meets its acceptance check; four T2 memos written with options +
recommendation + consequences; all seven self-verification checks in runbook §5 clean; working tree
clean; nothing pushed; final AC-01..15 table with one of PASS/FAIL/BLOCKED/NOT SCORED per row and no
aggregate hiding a failure.

**Expected landing: CONDITIONAL GO.** AC-13 and AC-15 are owner decisions and AC-11's strength
depends on what the concurrent soak finds. Reporting a precise CONDITIONAL GO is success.
Claiming GO while a T2 gate is open is the worst outcome available to you.

---

## 6. Environment notes that will cost you time otherwise

- System Python is 3.9 — below the project floor. Use `.venv` (3.11, created with `uv`). `uv venv`
  ships **without pip**: use `VIRTUAL_ENV=.venv uv pip install`, not `python -m pip`.
- Never pipe a command through `tail` when you need its exit status — the pipeline returns `tail`'s.
- `CLAUDE.md` and `scripts/` are in upstream `.gitignore`. `CLAUDE.md` is force-added; the soak
  harness lives at `deploy/gateway/soak.py` for that reason. Do not edit upstream `.gitignore`.
- The gateway has **no host port**, so host-side HTTP cannot reach it. Drive it from a container on
  `automation_internal` (E2E) or via `docker exec` (soak). Do not publish a port to make testing
  easier — that destroys the property under test.
- `black --check crawl4ai deploy/docker tests` fails on 304/350 **pristine upstream** files. This is
  expected. Lint only gateway-owned files. Never mass-reformat.
- Known pre-existing, do not "fix": `test_monitor_demo.py::test_dashboard` (async plugin config) and
  the upstream xfail `test_no_no_sandbox_flag`.
- Generate a throwaway `CRAWL4AI_API_TOKEN` for validation. Never commit it, echo it, or put it in
  a workflow file.
