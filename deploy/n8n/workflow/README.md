# n8n workflow: crawl one URL through the private gateway

`crawl4ai-crawl.workflow.json` is an importable n8n workflow that implements
the contract in [`../README.md`](../README.md). It is generated, so don't edit
it by hand.

| File | Role |
|---|---|
| `contract.js` | JavaScript port of `../contract.py` (classification, retry policy, markdown selection, URL redaction). Inlined into the Code nodes. |
| `build_workflow.py` | Generates `crawl4ai-crawl.workflow.json`. |
| `crawl4ai-crawl.workflow.json` | The workflow to import. |
| `isolated_e2e.py` | Proves the workflow in a throwaway gateway and n8n (see below). |
| `parity_cli.js` | Test harness used by `tests/gateway/test_n8n_workflow.py`. |

## What it does

```
When called by another workflow ─┐
Manual test → Example input ─────┴→ Init run → Gateway version → POST /crawl → Classify → Retry?
                                                                     ▲                   │true
                                                                     └──── Backoff ◄─────┘
                                                                         false → Finalize → Checksum → CrawlRun
```

- **One URL per run.** Input is `{ "url": "https://…" }`. A URL that is not
  absolute http(s) stops the run with an error before any request is sent.
- **Status first, then body.** A `2xx` whose crawl result failed is terminal
  (`blocked_target` or `unknown`) and is never retried.
- **Bounded retries.** Only retryable classes (`network`, `server`,
  `capacity`, `deadline`, `rate_limit`) are retried: 3 attempts in total,
  backoff 2 s then 4 s, `Retry-After` honored up to 60 s.
- **Every run emits a `CrawlRun`.** Fields: `run_id`, redacted `source_url`,
  `started_at`, `finished_at`, `crawler_version` (from `/health`),
  `config_fingerprint`, `raw_response`, `raw_checksum`, `status`,
  `failure_class`, `attempts`, `failures`, and `markdown` (text, source, reason).
- **Checksum.** `raw_response` is the exact HTTP body text, and `raw_checksum`
  is `sha256:` over its UTF-8 bytes, the same as
  `contract.raw_checksum(raw_response.encode())`. A run with no response
  stores `null`, hashed as `contract.raw_checksum(None)`.
- **No secrets in records.** Failure entries carry class, HTTP status and
  attempt only, never error text, because upstream messages can echo URLs.

## Install

1. **Credential.** In n8n, create a **Header Auth** credential named
   `Crawl4AI Gateway`, with header name `Authorization` and value
   `Bearer <token>`. The token is in `~/.config/crawl4ai-gateway/api_token`.
   Paste it in n8n's credential dialog only; never put it in a node,
   expression or export.
2. **Import** `crawl4ai-crawl.workflow.json` (Workflows → Import from File).
   When asked, select the credential on the **POST /crawl** node.
3. **n8n settings** (already applied in `n8n-docker`): n8n is attached to
   `automation_internal`, and `N8N_SSRF_ALLOWED_HOSTNAMES=crawl4ai` is set.
   Without that allowance n8n's SSRF guard blocks the gateway's private
   address.
4. **Publish** the workflow (the toggle in its header). n8n 2.x refuses to
   run an unpublished sub-workflow from an *Execute Workflow* node ("Workflow
   is not active and cannot be executed").
5. **Smoke test.** Open the workflow and click *Test workflow* (it crawls
   `https://example.com/`). Expect a `CrawlRun` with `status: "succeeded"`.
6. **Use it** from other workflows with an *Execute Workflow* node, passing
   `{ "url": … }`. The `CrawlRun` comes back as the output.

## Regenerate and verify

```bash
python deploy/n8n/workflow/build_workflow.py --out deploy/n8n/workflow/crawl4ai-crawl.workflow.json
```

```bash
pytest tests/gateway/test_n8n_workflow.py -q
```

```bash
python deploy/n8n/workflow/isolated_e2e.py --gateway-image crawl4ai-self-hosted:0.9.4 --n8n-image lab/n8n:2.41.6-custom3 --out docs/implementation/evidence-0.9.4/n8n-workflow-e2e.json
```

`isolated_e2e.py` creates a private Docker network, a throwaway gateway (same
image, seccomp profile and sandbox switch as production) and a throwaway n8n
(same image and SSRF settings, its own SQLite). It uses a token generated for
that run, executes the real workflow for four scenarios (success with URL
redaction, wrong token, gateway down, invalid URL), and removes everything it
created. It never touches the live gateway or the live n8n.
