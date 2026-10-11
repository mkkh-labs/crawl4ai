#!/usr/bin/env python3
"""
The n8n workflow's JavaScript contract must agree with deploy/n8n/contract.py.

contract.py is the specification; deploy/n8n/workflow/contract.js is inlined
into the workflow's Code nodes. Both run over the same inputs, and any
divergence fails, so a change to one without the other cannot ship.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
N8N_DIR = os.path.join(REPO_ROOT, "deploy", "n8n")
WF_DIR = os.path.join(N8N_DIR, "workflow")
sys.path.insert(0, N8N_DIR)
sys.path.insert(0, WF_DIR)

import contract as c  # noqa: E402

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for parity")


def run_js(cases: list[dict]) -> list:
    proc = subprocess.run(
        [NODE, os.path.join(WF_DIR, "parity_cli.js")],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def _py_cls(status, body):
    k = c.classify_response(status, body)
    return {
        "status": k.status,
        "failure_class": k.failure_class,
        "retryable": k.retryable,
    }


GOOD = {"success": True, "results": [{"url": "u", "success": True}]}
BODIES = [
    GOOD,
    None,
    [],
    "text",
    {},
    {"success": True},
    {"results": []},
    {"success": True, "results": []},
    {"success": True, "results": "x"},
    {"success": True, "results": ["not-a-mapping"]},
    {"success": False, "results": [{"error_message": "captcha required"}]},
    {"success": False, "results": [{"error": "Too Many Requests"}]},
    {"success": False, "results": [{"error_message": "net::ERR_NAME_NOT_RESOLVED"}]},
    {"success": True, "results": [{"success": False, "error_message": "403"}]},
    {"success": True, "results": [{"success": False}]},
]


def test_http_status_classification_matches_for_every_code():
    codes = list(range(100, 600))
    cases = [{"fn": "classifyResponse", "status": s, "body": GOOD} for s in codes]
    js = run_js(cases)
    for s, got in zip(codes, js):
        assert got == _py_cls(s, GOOD), s


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_body_classification_matches(status):
    cases = [{"fn": "classifyResponse", "status": status, "body": b} for b in BODIES]
    for body, got in zip(BODIES, run_js(cases)):
        assert got == _py_cls(status, body), body


def test_shipped_fixtures_match():
    fixtures = sorted(glob.glob(os.path.join(N8N_DIR, "fixtures", "*.json")))
    assert fixtures
    loaded = [json.load(open(f)) for f in fixtures]
    cases = [
        {"fn": "classifyResponse", "status": f["http_status"], "body": f.get("body")}
        for f in loaded
    ]
    for path, f, got in zip(fixtures, loaded, run_js(cases)):
        assert got == _py_cls(f["http_status"], f.get("body")), path


def test_retry_policy_matches():
    classes = [
        {"status": c.FAILED_RETRYABLE, "failure_class": "server", "retryable": True},
        {"status": c.FAILED_TERMINAL, "failure_class": "auth", "retryable": False},
    ]
    retry_after = [None, "", "0", "5", "12.5", "999", "-1", "abc", "Wed, 21 Oct"]
    cases, expected = [], []
    for attempt in range(0, 6):
        for k in classes:
            cases.append({"fn": "shouldRetry", "classification": k, "attempt": attempt})
            expected.append(
                c.should_retry(
                    c.Classification(k["status"], k["failure_class"], k["retryable"]),
                    attempt,
                )
            )
        for ra in retry_after:
            cases.append(
                {"fn": "retryDelaySeconds", "attempt": attempt, "retry_after": ra}
            )
            expected.append(c.retry_delay_seconds(attempt, ra))
    assert run_js(cases) == pytest.approx(expected)


def test_markdown_selection_matches_on_the_fidelity_corpus():
    samples = [
        ("raw", ""),
        ("raw", None),
        ("```a```\n```b```", "```a```"),
        ("use `x` and `y`", "use `x`"),
        ("```a```", "```a```"),
        ("plain", "shorter"),
    ]
    corpus = sorted(
        glob.glob(
            os.path.join(
                REPO_ROOT, "tests", "gateway", "fixtures", "fidelity", "*.html"
            )
        )
    )
    from crawl4ai.content_filter_strategy_lxml import PruningContentFilterLXML
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    for path in corpus:
        html = open(path, encoding="utf-8").read()
        r = DefaultMarkdownGenerator().generate_markdown(
            input_html=html,
            base_url="https://example.com/",
            content_filter=PruningContentFilterLXML(),
        )
        samples.append((r.raw_markdown, r.fit_markdown))
    cases = [{"fn": "selectMarkdown", "raw": raw, "fit": fit} for raw, fit in samples]
    for (raw, fit), got in zip(samples, run_js(cases)):
        sel = c.select_markdown(raw, fit)
        assert got == {"text": sel.text, "source": sel.source, "reason": sel.reason}


URLS = [
    "https://example.com/",
    "https://example.com/path",
    "https://example.com/p?q=1",
    "https://example.com/p?token=abc&q=two words",
    "https://example.com/p?API_KEY=x&Sig=y&page=2#frag",
    "https://example.com/p?a=1&&b=&c",
    "https://example.com/p?redirect=https%3A%2F%2Fx.test%2F%3Fa%3Db",
    "https://example.com/p?q=caf%C3%A9&password=p%40ss",
    "https://example.com/p?q=a+b&x=%E2%9C%93",
    "https://example.com/p?bad=%ZZ",
    "https://example.com/p?",
    "https://example.com/p?#only-frag",
    "https://example.com/p?k=v*~!'()",
]


def test_url_redaction_matches():
    for url, got in zip(URLS, run_js([{"fn": "redactUrl", "url": u} for u in URLS])):
        assert got == c.redact_url(url), url


# ── generated workflow artifact ──────────────────────────────────────────────


def _build_module():
    import importlib

    return importlib.import_module("build_workflow")


def test_committed_workflow_matches_its_generator():
    bw = _build_module()
    committed = json.load(
        open(os.path.join(WF_DIR, "crawl4ai-crawl.workflow.json"), encoding="utf-8")
    )
    assert committed == bw.build("REPLACE_WITH_YOUR_CREDENTIAL_ID")


def test_workflow_contains_no_secret_and_targets_only_the_gateway():
    raw = open(
        os.path.join(WF_DIR, "crawl4ai-crawl.workflow.json"), encoding="utf-8"
    ).read()
    assert "Bearer " not in raw
    wf = json.loads(raw)
    http = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    assert {n["parameters"]["url"] for n in http} == {
        f"{c.BASE_URL}/health",
        f"{c.BASE_URL}{c.CRAWL_ENDPOINT}",
    }
    crawl = next(n for n in http if n["parameters"]["url"].endswith(c.CRAWL_ENDPOINT))
    assert crawl["parameters"]["authentication"] == "genericCredentialType"
    assert crawl["parameters"]["genericAuthType"] == "httpHeaderAuth"
    assert set(crawl["credentials"]) == {"httpHeaderAuth"}


def test_workflow_embeds_the_tested_contract_verbatim():
    bw = _build_module()
    js = open(os.path.join(WF_DIR, "contract.js"), encoding="utf-8").read()
    wf = bw.build("x")
    for name in ("Classify", "Finalize"):
        node = next(n for n in wf["nodes"] if n["name"] == name)
        assert node["parameters"]["jsCode"].startswith(js), name


def test_retry_loop_is_bounded_by_the_contract():
    bw = _build_module()
    wf = bw.build("x")
    conn = wf["connections"]
    # The only path back into POST /crawl is Retry?(true) -> Backoff.
    assert conn["Retry?"]["main"][0] == [
        {"node": "Backoff", "type": "main", "index": 0}
    ]
    assert conn["Backoff"]["main"][0][0]["node"] == "POST /crawl"
    classify = next(n for n in wf["nodes"] if n["name"] == "Classify")
    assert "shouldRetry(k, attempt)" in classify["parameters"]["jsCode"]
    assert "const MAX_ATTEMPTS = 3;" in classify["parameters"]["jsCode"]
