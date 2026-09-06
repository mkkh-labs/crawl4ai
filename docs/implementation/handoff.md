# Handoff

## Current state

| Item | Value |
|---|---|
| Phase | DEPLOY complete; validated on this host, **not promoted** |
| Branch | `build/crawl4ai-self-hosted-gateway` (9 commits ahead of `origin/main`, **unpushed**) |
| Final commit | `8f9349a0ee0adb13604dcac216d99379323f4716` |
| Image | `crawl4ai-self-hosted:0.9.3` = `sha256:4e3ec44c1e53…` |
| Safe rollback tag | `crawl4ai-self-hosted:0.9.3-known-safe` (same image) |
| Verdict | **CONDITIONAL GO** — every P0 gate passes except AC-13 |
| Modules | M1–M9 complete; M10 (MCP) deferred, P2 |

A container is **still running** from this validation: `crawl4ai-crawl4ai-1` on
the `automation_internal` network, healthy, no host port published. Stop it with
`docker compose down` if it is not wanted.

The validation token lives only in this session's scratchpad
(`token.env`, mode 600) and was never written to the repository. Rotate or
discard it; generate a real one for production and store it in the n8n
credential store.

## What blocks a full GO

1. **AC-13** — `nltk 3.10.3` / `PYSEC-2026-3740` has **no patched release**
   (`fix_versions` empty), so it cannot be fixed by upgrading. Assessed as not
   reachable from the gateway (zero references to any of the six affected APIs or
   to `pathsec`). Next action: watch for a patched nltk and re-run
   `pip-audit --strict`; or decide explicitly to accept the residual risk.
2. **AC-15** — no scoring rubric was supplied with the packs, so the score was
   not computed. Inventing one would be fabricated evidence. Next action: supply
   the rubric, or drop AC-15.

## Next atomic action

Push the branch and open a PR to `main`:

```bash
git push -u origin build/crawl4ai-self-hosted-gateway
```

Required checks that will run: `Security` (security-offline, blocker-families,
posture-gate, gateway-contract) and `Supply chain` (dependency-scan, sbom,
secret-scan, codeql, format-gateway). `dependency-scan` is expected to fail on
the nltk finding above until it is patched or explicitly excepted.

## Then, before real production traffic

- Connect n8n to `automation_internal` and run `deploy/gateway/e2e.py` from the
  n8n host itself.
- Run a **concurrent** soak. The soak that passed was 20 sequential jobs over 2
  URLs with no concurrency, which proves no leak under that workload only.
- Decide on F-04 (`--no-sandbox`): needs an unprivileged userns or a verified
  seccomp profile, plus a build confirming Chromium still starts.
- Configure the Notion registry and Linear routing (P1). `deploy/n8n/contract.py`
  already emits the required fields; no identifiers were fabricated.

## Reading order for a fresh session

`CLAUDE.md` → `SPEC.md` → `docs/RUNBOOK.md` → `docs/implementation/deploy-evidence.md`
→ this file. Revalidate `git rev-parse HEAD` before editing.
