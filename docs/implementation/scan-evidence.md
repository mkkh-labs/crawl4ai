# SCAN evidence

Phase 1 of `docs/RUNBOOK.md`. Read-only: no source changes were made in this phase.

## Repository identity

| Item | Value |
|---|---|
| Working directory | `/Users/mikkohchen/Developer/mkkh-labs/crawl4ai` |
| `origin` | `https://github.com/mkkh-labs/crawl4ai.git` |
| `upstream` | `https://github.com/unclecode/crawl4ai.git` |
| Branch at start | `main` |
| HEAD at start | `862f6bccb9c063f49b9d42701baa0eea17a4993f` |
| `git describe --tags` | `v0.9.3-4-g862f6bc` |
| Working tree | clean (`git status --short` empty) |
| Tags present | `v0.9.0`, `v0.9.1`, `v0.9.2`, `v0.9.3` |
| `crawl4ai/__version__.py` | `0.9.3` |
| Dockerfile `C4AI_VER` | `0.9.3` |

## Deviations from the governing packs

Both packs state the repository is `MikkohChen/crawl4ai` at the audited v0.9.2
baseline `7e801521428ee12509994d39151006f64055ebe3`. Repository reality differs,
and per the precedence rule repository reality wins. Recorded rather than
silently accepted:

| # | Pack claim | Reality | Consequence |
|---|---|---|---|
| D-01 | repo is `MikkohChen/crawl4ai` | `origin` is `mkkh-labs/crawl4ai` | Naming only. Same fork, same upstream. No action. |
| D-02 | HEAD is v0.9.2 `7e80152`; M1 must fast-forward | HEAD is `862f6bc`, already 4 commits past the `v0.9.3` tag | M1 was already satisfied. No merge was performed; none was needed. |

`7e801521428ee12509994d39151006f64055ebe3` **is** the `v0.9.2` tag and **is** an
ancestor of HEAD, so the audited baseline is intact and reachable.

### The 4 commits past v0.9.3 are documentation only

```
862f6bc Merge pull request #2221 from unclecode/develop
5ee246f docs: credit Zhixi (Jace) Sun by GitHub handle in security credits and release notes
b0e8a2b Merge pull request #2220 from unclecode/develop
7245f98 docs: add the non-security bug fixes to the v0.9.3 release notes
```

`git diff --stat v0.9.3..HEAD`:

```
 CHANGELOG.md                | 38 ++++++++++++++++++++++++++++++++++++--
 README.md                   |  4 +++-
 SECURITY-CREDITS.md         |  2 +-
 docs/blog/release-v0.9.3.md | 43 ++++++++++++++++++++++++++++++++++++++++---
 4 files changed, 80 insertions(+), 7 deletions(-)
```

No code, config, workflow, or dependency file changed. HEAD therefore satisfies
"v0.9.3-derived or newer-safe" and AC-01.

## Environment

| Tool | State |
|---|---|
| System Python | 3.9.6 — below the project's 3.10–3.13 floor |
| Python used | 3.11.16 in `.venv` (created with `uv`) |
| Docker | 29.7.2, Compose v5.5.0 |
| Docker daemon | initially **down**; started during DEPLOY |
| CI workflows at start | `docker-release.yml`, `main.yml`, `release.yml`, `security.yml`, plus `release.yml.backup` and `test-release.yml.disabled` |

## Branches created

| Branch | Commit | Purpose |
|---|---|---|
| `audit/v0.9.2-20260903` | `7e80152` | Preserves the audited v0.9.2 state (M1) |
| `build/crawl4ai-self-hosted-gateway` | from `862f6bc` | Implementation branch |

No destructive git operation was run. `main` was not reset, rewritten, or force-pushed.
