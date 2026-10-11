# Evidence — release image `crawl4ai-self-hosted:0.9.4` (`sha256:459878969baf…`)

Generated on 2026-10-11 on the deployment host. No file contains the gateway
token or the per-run test token (checked with grep and gitleaks).

| File | Produced by | Shows |
|---|---|---|
| `e2e-n8n-netns.json` | `deploy/gateway/e2e.py` run inside n8n's network namespace | 20/20 runs, version floor, auth, GHSA-5w5p probe, forced failures |
| `sandbox-verify.json` | `deploy/gateway/verify_sandbox.py` inside the gateway | Renderer sandbox active (own user ns, nested PID ns, Seccomp 2, no `--no-sandbox`) |
| `soak-60x4.json` | `deploy/gateway/soak.py --jobs 60 --concurrency 4 --cooldown-s 720` | Bounded processes and memory after concurrent traffic |
| `n8n-workflow-e2e.json` | `deploy/n8n/workflow/isolated_e2e.py` | The shipped workflow in a real, isolated n8n: S1–S5 |
| `rollback-drill.json` | timed `docker compose up` to `0.9.4-known-safe` and back | Rollback 7.1 s, roll-forward 6.8 s, n8n reaches the gateway |
| `console-selftest.json` | `console.self_test()` inside the console container | 5/5 live security checks |
| `pip-audit-*.json` | `pip list --format=freeze` from each image → `pip-audit` | Inputs to `deploy/gateway/audit_gate.py` |

Re-generate with the commands in `docs/RUNBOOK.md` → "Release gates to run
before promotion".
