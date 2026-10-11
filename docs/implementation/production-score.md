# Production score rubric (AC-15)

SPEC.md requires a production score ≥ 90/100 but never defined one. The owner
delegated the definition on 2026-10-11. This rubric was written **before**
scoring and is fixed for this release. Change it only in a separate commit,
before re-scoring.

## Rules

1. **Gate first.** Any release blocker in `CLAUDE.md` (failed AC-01..AC-14,
   P0/P1 finding, public crawler exposure, missing bearer token, silent n8n
   failure, unbounded post-traffic growth) sets the score to **0**, whatever
   the checks below say.
2. **Ten dimensions × 10 points.** Each dimension has binary checks of equal
   weight. Dimension score = 10 × passed / total, rounded to one decimal.
3. **A check passes only with evidence**: a command, a test or a CI job
   whose result is recorded in `scorecard` below. "Not run" is a fail.
4. **No partial credit** and no check may be dropped after scoring starts.

## Dimensions and checks

| # | Dimension | Checks (binary) |
|---|---|---|
| D1 | Supply-chain currency | (a) running version ≥ latest upstream security release · (b) image audit: 0 unwaived findings, incl. pip/setuptools · (c) every waiver has no published fix, reachability evidence and a review date · (d) CI actions pinned by SHA · (e) SBOM generated in CI |
| D2 | Exposure and authN | (a) no host-published crawler port · (b) no-token and wrong-token → 401 live · (c) Host allowlist, bad Host → 400 live · (d) compose fails closed without token and without IMAGE · (e) console bound to 127.0.0.1 only, token as file secret |
| D3 | Untrusted input and egress | (a) GHSA-5w5p laundering probe → 400 live · (b) metadata SSRF refused live · (c) seeder/robots egress regression tests pass · (d) hooks and execute_js disabled |
| D4 | Runtime isolation | (a) non-root user · (b) read-only rootfs · (c) cap_drop ALL + no-new-privileges · (d) Chromium renderer sandbox active live (own user/PID/net ns, Seccomp 2, no `--no-sandbox`) · (e) seccomp profile generated, minimal, denies mount ns and netfilter netlink |
| D5 | Resource bounds | (a) memory.max and pids.max set live · (b) wall_clock_s > 0 · (c) concurrent soak passes (60 × 4, cooldown ≥ 2 × idle TTL + janitor) · (d) every soak job succeeds |
| D6 | Integration | (a) E2E 20/20 from n8n's network namespace · (b) n8n SSRF guard allows `crawl4ai` and blocks gateway-by-IP and metadata · (c) forced failures classified terminal, none silent · (d) the n8n configuration change is merged in the n8n-docker repo · (e) a real n8n workflow execution, using the n8n credential, crawled through the gateway |
| D7 | Fidelity and provenance | (a) fidelity corpus passes on the production filter · (b) LXML ≡ legacy filter parity · (c) provenance complete on all E2E runs · (d) raw checksums re-verify |
| D8 | Operability | (a) rollback drill ≤ 60 s to healthy · (b) runbook covers deploy, rotate, rollback, console, gates · (c) console self-test 5/5 live · (d) rollback target is a validated v0.9.4 image |
| D9 | Verification and CI | (a) all required checks green on the release head · (b) branch protection on `main` requires them · (c) full-history secret scan clean · (d) offline suite passes locally |
| D10 | Evidence and governance | (a) machine-readable E2E and soak evidence committed for the deployed image · (b) evidence states its provenance · (c) handoff lists every open owner decision · (d) no secret in repo or evidence |

## Scorecard

Filled in `docs/implementation/closeout-evidence-0.9.4.md` → "Production
score", from the validation run of the deployed image.
