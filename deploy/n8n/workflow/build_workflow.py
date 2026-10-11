#!/usr/bin/env python3
"""
Generate the importable n8n workflow for the private Crawl4AI gateway.

    python deploy/n8n/workflow/build_workflow.py \
        --out deploy/n8n/workflow/crawl4ai-crawl.workflow.json

The workflow implements deploy/n8n/README.md exactly: one URL per run,
status-then-body classification, bounded retries (3 attempts, exponential
backoff capped at 60 s, Retry-After honored), and a CrawlRun provenance record
for every run, success or failure. Its Code nodes inline workflow/contract.js,
which tests/gateway/test_n8n_workflow.py holds to parity with contract.py.

The credential is referenced by name only ("Crawl4AI Gateway", type Header
Auth: name `Authorization`, value `Bearer <token>`). The exported JSON never
contains a token.

Checksum rule: `raw_response` is the exact HTTP body text and `raw_checksum`
is the sha256 of its UTF-8 bytes, i.e. contract.raw_checksum(body.encode()).
No response at all (transport failure) is recorded as raw_response = null and
hashed as the 4 bytes "null", the same as contract.raw_checksum(None).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import contract as c  # noqa: E402

GATEWAY = c.BASE_URL
CRAWLER_CONFIG = {"stream": False, "cache_mode": "bypass"}
BROWSER_CONFIG: dict = {}
CREDENTIAL_NAME = "Crawl4AI Gateway"
# HTTP request timeout: gateway wall clock (300 s) plus margin.
REQUEST_TIMEOUT_MS = 330_000


def _contract_js() -> str:
    with open(os.path.join(HERE, "contract.js"), encoding="utf-8") as fh:
        return fh.read()


INIT_JS = """
const url = String($json.url ?? "").trim();
let valid = false;
try {
  const u = new URL(url);
  valid = (u.protocol === "http:" || u.protocol === "https:") && Boolean(u.hostname);
} catch (e) {
  valid = false;
}
if (!valid) {
  throw new Error("crawl4ai: `url` must be an absolute http(s) URL");
}
return {
  json: {
    url,
    run_id: "run-" + $execution.id + "-" + Date.now().toString(36),
    started_at: new Date().toISOString().replace(/\\.\\d{3}Z$/, "Z"),
    request: { urls: [url], browser_config: %(browser)s, crawler_config: %(crawler)s },
  },
};
"""

CLASSIFY_JS = """
const init = $("Init run").first().json;
const attempt = $runIndex + 1;
const previous = $runIndex > 0 ? $("Classify").all(0, $runIndex - 1)[0].json.failures : [];

let k;
let httpStatus = null;
let rawText = null;
let body;
let retryAfter = null;
if ($json.statusCode === undefined || $json.statusCode === null) {
  k = classifyTransportError();
} else {
  httpStatus = Number($json.statusCode);
  const payload = $json.body !== undefined ? $json.body : $json.data;
  rawText = typeof payload === "string" ? payload : JSON.stringify(payload ?? null);
  try {
    body = JSON.parse(rawText);
  } catch (e) {
    body = undefined;
  }
  const headers = $json.headers || {};
  retryAfter = headers["retry-after"] ?? headers["Retry-After"] ?? null;
  k = body === undefined
    ? cls(FAILED_TERMINAL, "content_contract", false)
    : classifyResponse(httpStatus, body);
}

// Failure evidence never stores error text: upstream messages can echo the
// request URL, query string included.
const failures = k.status === SUCCEEDED ? previous : previous.concat([{
  run_id: init.run_id,
  class: k.failure_class,
  http_status: httpStatus,
  retryable: k.retryable,
  attempt,
  message_digest: null,
}]);

const retry = shouldRetry(k, attempt);
return {
  json: {
    attempt,
    http_status: httpStatus,
    classification: k,
    retry,
    backoff_s: retry ? retryDelaySeconds(attempt, retryAfter) : 0,
    raw_response: rawText,
    body: body === undefined ? null : body,
    failures,
  },
};
"""

FINALIZE_JS = """
const init = $("Init run").first().json;
const health = $("Gateway version").first().json;
const k = $json.classification;
// A retryable failure that exhausted its budget is terminal for the operator.
const final = k.status === FAILED_RETRYABLE ? cls(FAILED_TERMINAL, k.failure_class, false) : k;

let markdown = null;
if (final.status === SUCCEEDED) {
  const r = ($json.body.results || [])[0] || {};
  const md = r.markdown;
  const raw = md && typeof md === "object" ? md.raw_markdown || "" : md || "";
  const fit = md && typeof md === "object" ? md.fit_markdown || "" : "";
  markdown = selectMarkdown(raw, fit);
}

return {
  json: {
    run_id: init.run_id,
    source_url: redactUrl(init.url),
    started_at: init.started_at,
    finished_at: new Date().toISOString().replace(/\\.\\d{3}Z$/, "Z"),
    crawler_version: (health && typeof health.version === "string") ? health.version : "unknown",
    config_fingerprint: "%(fingerprint)s",
    raw_response: $json.raw_response,
    status: final.status,
    failure_class: final.failure_class,
    artifact_ref: null,
    attempts: $json.attempt,
    failures: $json.failures,
    markdown,
    checksum_input: $json.raw_response === null ? "null" : $json.raw_response,
  },
};
"""

RECORD_JS = """
const out = Object.assign({}, $json);
out.raw_checksum = "sha256:" + out.raw_sha256;
delete out.raw_sha256;
delete out.checksum_input;
return { json: out };
"""


def _code(name: str, js: str, pos: list[int]) -> dict:
    return {
        "parameters": {"mode": "runOnceForEachItem", "jsCode": js},
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": pos,
    }


def build(credential_id: str, example_url: str = "https://example.com/") -> dict:
    contract_js = _contract_js()
    fingerprint = c.config_fingerprint(BROWSER_CONFIG, CRAWLER_CONFIG)
    init_js = INIT_JS % {
        "browser": json.dumps(BROWSER_CONFIG),
        "crawler": json.dumps(CRAWLER_CONFIG),
    }
    nodes = [
        {
            "parameters": {
                "inputSource": "workflowInputs",
                "workflowInputs": {"values": [{"name": "url"}]},
            },
            "id": "called-by-workflow",
            "name": "When called by another workflow",
            "type": "n8n-nodes-base.executeWorkflowTrigger",
            "typeVersion": 1.1,
            "position": [0, 0],
        },
        {
            "parameters": {},
            "id": "manual-test",
            "name": "Manual test",
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [0, 200],
        },
        {
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": "u",
                            "name": "url",
                            "value": example_url,
                            "type": "string",
                        }
                    ]
                },
                "options": {},
            },
            "id": "example-input",
            "name": "Example input",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [220, 200],
        },
        _code("Init run", init_js, [440, 100]),
        {
            "parameters": {
                "url": f"{GATEWAY}/health",
                "options": {
                    "response": {
                        "response": {"neverError": True, "responseFormat": "json"}
                    },
                    "timeout": 10000,
                },
            },
            "id": "gateway-version",
            "name": "Gateway version",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [660, 100],
            "onError": "continueRegularOutput",
        },
        {
            "parameters": {
                "method": "POST",
                "url": f"{GATEWAY}{c.CRAWL_ENDPOINT}",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($('Init run').first().json.request) }}",
                "options": {
                    "response": {
                        "response": {
                            "fullResponse": True,
                            "neverError": True,
                            "responseFormat": "text",
                        }
                    },
                    "timeout": REQUEST_TIMEOUT_MS,
                },
            },
            "id": "post-crawl",
            "name": "POST /crawl",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [880, 100],
            "credentials": {
                "httpHeaderAuth": {"id": credential_id, "name": CREDENTIAL_NAME}
            },
            "onError": "continueRegularOutput",
        },
        _code("Classify", contract_js + CLASSIFY_JS, [1100, 100]),
        {
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "strict",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": "retry",
                            "leftValue": "={{ $json.retry }}",
                            "rightValue": True,
                            "operator": {
                                "type": "boolean",
                                "operation": "true",
                                "singleValue": True,
                            },
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
            "id": "retry",
            "name": "Retry?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.2,
            "position": [1320, 100],
        },
        {
            "parameters": {"amount": "={{ $json.backoff_s }}", "unit": "seconds"},
            "id": "backoff",
            "name": "Backoff",
            "type": "n8n-nodes-base.wait",
            "typeVersion": 1.1,
            "position": [1540, -60],
            "webhookId": "00000000-0000-4000-8000-00000000c4a1",
        },
        _code(
            "Finalize",
            contract_js + FINALIZE_JS % {"fingerprint": fingerprint},
            [1540, 200],
        ),
        {
            "parameters": {
                "action": "hash",
                "type": "SHA256",
                "value": "={{ $json.checksum_input }}",
                "dataPropertyName": "raw_sha256",
                "encoding": "hex",
            },
            "id": "checksum",
            "name": "Checksum",
            "type": "n8n-nodes-base.crypto",
            "typeVersion": 1,
            "position": [1760, 200],
        },
        _code("CrawlRun", RECORD_JS, [1980, 200]),
    ]

    def edge(target: str) -> dict:
        return {"node": target, "type": "main", "index": 0}

    connections = {
        "When called by another workflow": {"main": [[edge("Init run")]]},
        "Manual test": {"main": [[edge("Example input")]]},
        "Example input": {"main": [[edge("Init run")]]},
        "Init run": {"main": [[edge("Gateway version")]]},
        "Gateway version": {"main": [[edge("POST /crawl")]]},
        "POST /crawl": {"main": [[edge("Classify")]]},
        "Classify": {"main": [[edge("Retry?")]]},
        "Retry?": {"main": [[edge("Backoff")], [edge("Finalize")]]},
        "Backoff": {"main": [[edge("POST /crawl")]]},
        "Finalize": {"main": [[edge("Checksum")]]},
        "Checksum": {"main": [[edge("CrawlRun")]]},
    }
    return {
        "name": "Crawl4AI: crawl one URL (private gateway)",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "saveManualExecutions": True},
        "pinData": {},
        "meta": {"templateCredsSetupCompleted": False},
        "tags": [],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--credential-id",
        default="REPLACE_WITH_YOUR_CREDENTIAL_ID",
        help="id of the n8n Header Auth credential; n8n asks you to pick one on import otherwise",
    )
    ap.add_argument("--workflow-id", default=None)
    ap.add_argument("--example-url", default="https://example.com/")
    args = ap.parse_args(argv)
    wf = build(args.credential_id, args.example_url)
    if args.workflow_id:
        wf["id"] = args.workflow_id
        wf["active"] = False
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(wf, fh, indent=2)
        fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
