# Handoff

## Current state (2026-10-11, final)

| Item | Value |
|---|---|
| Phase | v0.9.4 gateway with renderer sandbox, deployed and validated on this host |
| Branch / PR | `build/crawl4ai-self-hosted-gateway` → [mkkh-labs/crawl4ai#1](https://github.com/mkkh-labs/crawl4ai/pull/1) (fork `main`) |
| CI | 9 required checks on `main` (branch protection: strict, no force-push or deletion) |
| Release image | `crawl4ai-self-hosted:0.9.4` = `sha256:459878969baf…` |
| Rollback image | `crawl4ai-self-hosted:0.9.4-known-safe` = `sha256:4e291bacd07d…` |
| Console | `crawl4ai-console:0.9.4` at http://127.0.0.1:8501 |
| Verdict | AC-01..AC-14 PASS (AC-13 with one nltk waiver); AC-15 score **98.0/100** |
| Evidence | `closeout-evidence-0.9.4.md`, `evidence-0.9.4/` (JSON), `production-score.md`, `sha-map.md` |

## What changed in the final pass

- **F-04 closed.** Chromium runs its renderer sandbox under
  `deploy/docker/seccomp/chromium.json`. The core library honors
  `CRAWL4AI_CHROMIUM_SANDBOX` in every launch path.
- **n8n workflow shipped.** `deploy/n8n/workflow/`, proven in a real isolated
  n8n (S1–S5).
- **n8n-docker change merged** into that repo's local `main` (fast-forward,
  32/32 tests). Not pushed: the remote belongs to another organization
  (Frictionless-Labs).
- **Soak harness hardened.** Docker-transport outages are scored as
  unobserved, never as gateway health.
- **CI.** The advisory and sandbox unit suites now run in `security-offline`.

## Secrets

`~/.config/crawl4ai-gateway/` (0700): `gateway.env` and `api_token`, rotated
on 2026-10-09. Never in the repo or evidence (gitleaks plus a token grep).

## Open owner actions

1. **n8n credential.** Create the Header Auth credential `Crawl4AI Gateway`
   (`Authorization: Bearer <api_token>`), import and **publish** the workflow,
   then run its smoke test (`deploy/n8n/workflow/README.md`). This is the only
   failing scorecard check (D6e), and completing it raises the score to 100.
2. **n8n-docker remote.** Push or PR `main` to Frictionless-Labs/fl-n8n if
   that is the right home. Other agent worktrees (`codex/*`) are active there.
3. **Docker Desktop on this host** was stopped and quit by an external client
   several times on 2026-10-11 (see closeout evidence). Identify that client;
   the gateway and n8n restart cleanly, but evidence runs need a stable
   engine.
4. **nltk waiver** lapses 2026-11-09. Re-run the dependency gate before then.

## Reading order for a fresh session

`CLAUDE.md` → `SPEC.md` → `docs/RUNBOOK.md` (Operations) →
`docs/implementation/closeout-evidence-0.9.4.md` → this file.
