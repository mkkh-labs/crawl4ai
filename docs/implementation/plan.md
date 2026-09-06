# STRATEGIZE plan

Phase 3 of `docs/RUNBOOK.md`. Frozen before implementation.

## Architecture (unchanged from the strategy)

```
n8n  --Bearer POST /crawl-->  crawl4ai:11235   (private automation_internal network)
```

- Upstream `/crawl` API unchanged; no fork of the public response model.
- No host-published crawler port in production.
- Bearer token mandatory; JWT off for the service-to-service MVP.
- Hooks and `execute_js` stay disabled.
- MCP is post-launch and never a production dependency.
- Provenance, retries and failure routing live in n8n, **not** in Crawl4AI. No
  server-side persistence is added.

## Module order and status

| Module | Files changed | Tests | Status |
|---|---|---|---|
| M1 upstream v0.9.3 sync | none (already satisfied) | version + compileall | PASS |
| M3 security regression gate | `+test_security_playground_dom_xss.py` | 5 families | PASS |
| M2 private Docker posture | `docker-compose.yml` | `test_security_gateway_topology.py` | PASS |
| M4 auth + runtime config | `deploy/docker/config.yml`, `tests/conftest.py` | topology + Host guard | PASS |
| M5 n8n HTTP contract | `deploy/n8n/{README.md,contract.py,fixtures/}` | `tests/gateway/test_n8n_contract.py` | PASS |
| M6 provenance + failure taxonomy | `deploy/n8n/contract.py` | same | PASS |
| M7 fidelity guard | `tests/gateway/fixtures/fidelity/` | `test_fidelity_corpus.py` | PASS |
| M8 observability + soak | `deploy/gateway/soak.py`, `+test_security_observability.py` | `test_soak_analysis.py` | offline PASS; runtime soak requires a live container |
| M9 CI + supply chain | `.github/workflows/*` | workflow render + pin scan | PASS |
| M10 MCP pilot | none | none | Deferred (P2, post-launch) |

## Rollback points

| After | Revert | Preserved |
|---|---|---|
| M3 | the DOM-XSS test commit | v0.9.3 and upstream coverage |
| M2/M4 | `feat(deploy): harden private Crawl4AI gateway` | v0.9.3 + all security tests |
| M5–M7 | `feat(integration): lock the n8n crawl and provenance contract` | secure runtime untouched (caller-side only) |
| M8/M9 | the CI commit | never by disabling a security check |

Rollback target is always a v0.9.3-derived artifact. **Never v0.9.2.**

## Constraint check

- No public or multi-tenant requirement introduced.
- No v0.9.2 rollback target.
- No unbounded limit (`wall_clock_s` 300; body/pages/depth finite).
- No new server-side persistence layer.
- No new service, daemon, database, or framework.
