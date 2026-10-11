# Handoff

## Current state (2026-10-11)

| Item | Value |
|---|---|
| Phase | v0.9.4 gateway deployed and validated on this host; PR open, not merged |
| Branch | `build/crawl4ai-self-hosted-gateway`, pushed; PR [mkkh-labs/crawl4ai#1](https://github.com/mkkh-labs/crawl4ai/pull/1) into the fork's `main` |
| CI | 9/9 required checks green; `main` protected (required checks, strict, no force-push or deletion) |
| Gateway image | `crawl4ai-self-hosted:0.9.4`; rollback `crawl4ai-self-hosted:0.9.4-known-safe` |
| Console | `crawl4ai-console:0.9.4` at http://127.0.0.1:8501 |
| Evidence | `closeout-evidence-0.9.4.md`; old→new commit SHAs in `sha-map.md` |
| Verdict | AC-01..AC-14 PASS (AC-13 with one documented nltk waiver); AC-15 not scored |

Superseded: the 0.9.3 state, its CONDITIONAL GO and its blocker list. v0.9.3
is now a forbidden rollback target.

## Secrets

`~/.config/crawl4ai-gateway/` (0700): `gateway.env` (`CRAWL4AI_API_TOKEN=…`)
and `api_token` (bare token, used by the console). Both rotated on
2026-10-09. The token is never in the repo. Rotation steps: `docs/RUNBOOK.md`
→ Operations → Secrets.

## Host state at handoff

- Docker Desktop had **paused every container** (gateway, console, n8n,
  uptime-kuma, dockge) after a host restart on 2026-10-11. This was not caused
  by this work. Unpause before any live check.
- The n8n change lives on local branch `chore/crawl4ai-gateway-network` in
  `~/Developer/mkkh-labs/n8n-docker` (commit `9866c7c`, 32/32 tests pass,
  gitleaks clean). That branch is checked out and its config is what n8n
  runs, but it is **not merged or pushed**. Starting n8n from `main` would
  drop the network and SSRF allowance.

## Open decisions (owner)

1. **Merge PR #1** (CI green, mergeable).
2. **n8n-docker**: merge `chore/crawl4ai-gateway-network` per that repo's
   workflow (owner review).
3. **n8n credential**: paste the rotated token into the n8n credential used
   by the HTTP Request node.
4. **AC-15**: supply a rubric or drop the criterion.
5. **F-04 `--no-sandbox`**: needs an unprivileged userns or a verified seccomp
   profile, plus a build proving Chromium starts.
6. **nltk waiver** lapses 2026-11-09. Re-check for a fixed release first.

## Next atomic action

Unpause Docker, then regenerate machine-readable evidence: E2E from n8n's
namespace and the 60 × 4 soak with a 720 s cooldown (RUNBOOK → Release
gates). The earlier JSON was lost with the session scratchpad.

## Reading order for a fresh session

`CLAUDE.md` → `SPEC.md` → `docs/RUNBOOK.md` (Operations section) →
`docs/implementation/closeout-evidence-0.9.4.md` → this file.
