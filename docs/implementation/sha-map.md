# SHA map: author-email rewrite (2026-10-10)

The branch had never been pushed. GitHub declined the first push because 25
commits used a private author address and the account blocks command-line
pushes that expose it. Only those 25 commits were re-authored to
`193409480+MikkohChen@users.noreply.github.com`. The tree is byte-identical,
and all 44 upstream commits brought in by the v0.9.4 merge keep their
original, signed SHAs (v0.9.4 = `133e1d9`).

Evidence documents written before the rewrite (`handoff.md`,
`deploy-evidence.md`, `CLOSEOUT-RUNBOOK.md`, `SESSION-KICKOFF.md`) cite the
old SHAs. Translate them with this table.

| Old | New | Subject |
|---|---|---|
| `deb8ab5` | `0fa9fd1` | docs(gateway): add operating contract, spec, and runbook |
| `5f1f7d8` | `baf9993` | test(security): guard the Playground DOM XSS sink |
| `3387fee` | `ffe4fac` | feat(deploy): harden private Crawl4AI gateway |
| `4067822` | `e7d89da` | feat(integration): lock the n8n crawl and provenance contract |
| `9b88fef` | `eb117e3` | feat(observability): add soak harness and offline signal checks |
| `8cc090d` | `ae32102` | ci(security): enforce release evidence and supply-chain gates |
| `6979b7d` | `90e2645` | docs(implementation): record SCAN, ASSESS and STRATEGIZE evidence |
| `ee3b7c2` | `5ed9d02` | feat(gateway): add n8n-equivalent E2E validation runner |
| `8f9349a` | `261b00a` | fix(security): patch PyJWT and correct E2E provenance and soak transport |
| `ca18033` | `6c2ae08` | docs(implementation): record DEPLOY evidence and handoff |
| `ed44f43` | `320e41c` | docs(closeout): add close-out runbook and correct the AC-13 record |
| `8316e89` | `18965ba` | docs(closeout): refresh the dependency snapshot and de-hardcode its acceptance |
| `8e2794d` | `fb13958` | docs(closeout): add the execution-session kickoff and protocol |
| `8b800f9` | `422df8f` | chore(upstream): merge v0.9.4 security release |
| `435517d` | `1d17d19` | test(gateway): guard the LXML FIT filter and require a safe version floor |
| `d19457a` | `0dba454` | feat(gateway): probe the live version floor and GHSA-5w5p in E2E |
| `899a961` | `638693e` | fix(deps): patch PyJWT, pypdf, urllib3, multidict and anyio |
| `90f0d22` | `07537cd` | ci(security): gate pip-audit on fix-aware, expiring exceptions |
| `54d6feb` | `4977145` | fix(deploy): require IMAGE and refuse the stock upstream image |
| `87483f4` | `27a47c5` | fix(docker): keep .venv, .git and secrets out of the build context |
| `88acfdd` | `877ced4` | feat(ui): add a Streamlit operator console for the gateway |
| `a5828d1` | `5e14b66` | feat(gateway): run the soak with bounded concurrency |
| `88cb1f0` | `099de45` | fix(docker): route /crawl to the permanent browser and apply browser policy |
| `fc7cc17` | `c921756` | fix(ui): source the console token from a file and tighten metrics |
| `a881888` | `5c6bd3d` | docs(gateway): update commands, rollback target and operations for v0.9.4 |
