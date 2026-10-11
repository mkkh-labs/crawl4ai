# ASSESS evidence

Phase 2 of `docs/RUNBOOK.md`. Maps the five v0.9.3 security blocker families to
the code that fixes them and the tests that guard them.

## The v0.9.2 → v0.9.3 delta

`git diff --stat v0.9.2..v0.9.3` touches these security-sensitive paths:

```
crawl4ai/processors/pdf/__init__.py
crawl4ai/processors/pdf/processor.py
crawl4ai/processors/pdf/utils.py
deploy/docker/api.py
deploy/docker/config.yml
deploy/docker/server.py
deploy/docker/static/playground/index.html
```

Four of the five defects are in the PDF path and share one root cause:
`PDFContentScrapingStrategy` can be selected from an untrusted Docker API
request body and downloads with `requests` rather than through the browser, so
the destination pinning and resource caps applied on the Chromium side never
reached it. The fifth is a DOM-based XSS in the Playground.

## Family → test mapping

| # | Family | Guarding tests | Status |
|---|---|---|---|
| 1 | PDF arbitrary image-write | `deploy/docker/tests/test_security_pdf_image_write.py` (6 tests); `test_security_2026_04.py::TestOutputPathRemoved` (3) | upstream coverage, passing |
| 2 | PDF SSRF (redirect + peer) | `test_security_ssrf_crawl.py` (28); `test_security_ssrf_egress.py`; `tests/unit/test_pdf_download_limits.py` redirect/peer cases | upstream coverage, passing |
| 3 | PDF DoS (byte/page/wall-clock) | `tests/unit/test_pdf_download_limits.py` (byte cap, page cap, untrusted body cannot raise its own caps); `test_security_resource_caps.py` | upstream coverage, passing |
| 4 | PDF-generated HTML XSS | `tests/unit/test_pdf_html_escaping.py` (7) | upstream coverage, passing |
| 5 | Playground DOM XSS | **was uncovered** — added `deploy/docker/tests/test_security_playground_dom_xss.py` (5) | gap closed in this build |

### Family 5 was the gap

The v0.9.3 fix removed this round trip from `forceHighlightElement`:

```js
const text = element.textContent;
element.innerHTML = text;
```

`element.innerHTML = element.textContent` re-parses the text as live HTML. That
text is crawl output, so script in a crawled page could run in the operator's
Playground session and read the API token held there.

The fix shipped in the asset but **no test guarded it** — the other four
families each had upstream coverage; this one relied on the fix simply not being
reverted. `test_security_playground_dom_xss.py` scans the shipped asset for
live-HTML sinks and asserts crawl output reaches the viewer only via
`textContent`.

Verified as a real guard rather than a tautology: run against the v0.9.2 asset
it fails 2 of 5 on the original `element.innerHTML = text` sink; against the
fixed asset it passes 5 of 5.

## Additional findings

| ID | Finding | Severity | Disposition |
|---|---|---|---|
| F-01 | Two of five families (3 and 4) live under `tests/unit/` and were never matched by `security.yml`'s `deploy/docker/tests/test_security_*.py` glob, so **CI was not running them** | High for release evidence | Fixed: new `blocker-families` job runs all five as named steps |
| F-02 | `Ilshidur/action-discord@master` — mutable third-party action executing on every issue/comment/PR/star | High (supply chain) | Workflow disabled (M9) |
| F-03 | No enabled workflow pinned actions to SHAs; `docker-release.yml` declared no `permissions:` at all | Medium | Fixed: all pinned to verified 40-char SHAs, minimum permissions added |
| F-04 | Pre-existing xfail `test_no_no_sandbox_flag`: Chromium still runs with `--no-sandbox` | Medium, build-gated | **Open.** Not one of the five families. Removing it needs an unprivileged userns or a verified seccomp profile plus a build confirming Chromium still starts. `CRAWL4AI_CHROMIUM_SANDBOX=true` exists as the opt-in. Not enabled blind, since an unverified flip can stop Chromium starting. |
| F-05 | `black --check crawl4ai deploy/docker tests` (CLAUDE.md's canonical lint) fails on the **pristine upstream tree**: 304 of 350 files | Low | Cannot pass without a mass reformat of unrelated upstream source, which the change policy forbids. CI lint scoped to gateway-owned files. |
| F-06 | `deploy/docker/tests/test_monitor_demo.py::test_dashboard` fails (`async def` with no plugin config) | Low | Pre-existing; fails identically on the unmodified tree. Not caused by this build, not fixed here (out of scope). |
| F-07 | `CLAUDE.md` and `scripts/` are excluded by upstream `.gitignore` | Low | `CLAUDE.md` force-added; the soak harness placed at `deploy/gateway/soak.py` instead of `scripts/`. Upstream `.gitignore` left unmodified to keep fork delta minimal. |

## Threat-model confirmation

No change. The gateway remains private, authenticated, hooks and `execute_js`
disabled, MCP post-launch. Nothing in the v0.9.2→v0.9.3 delta or in the four
documentation commits past the tag alters it.
