#!/usr/bin/env python3
"""
Operator console logic (deploy/ui/console.py), tested offline against a stub
gateway that speaks the real /health and /crawl shapes.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "deploy", "ui"))

import console as con  # noqa: E402

from crawl4ai.async_configs import (  # noqa: E402
    UNTRUSTED_FIELD_ALLOWLIST,
    CrawlerRunConfig,
    Provenance,
)

TOKEN = "stub-token-123"


# ── stub gateway ─────────────────────────────────────────────────────────────


class _Gateway(BaseHTTPRequestHandler):
    version = "0.9.4"
    calls: list = []

    def log_message(self, *args):  # keep test output clean
        pass

    def _send(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "version": self.version})
        else:
            self._send(404, {"detail": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).calls.append(body)
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"detail": "unauthorized"})
        cfg = body.get("crawler_config") or {}
        if "extraction_strategy" in cfg:
            return self._send(400, {"detail": "type may not be constructed"})
        url = body["urls"][0]
        if "169.254.169.254" in url:
            return self._send(400, {"detail": "destination not allowed"})
        if "flaky" in url:
            return self._send(503, {"detail": "busy"})
        md = {"raw_markdown": "# Title\n\n```py\nx = 1\n```\n", "fit_markdown": ""}
        self._send(
            200,
            {
                "success": True,
                "results": [
                    {"url": url, "success": True, "status_code": 200, "markdown": md}
                ],
            },
        )


@pytest.fixture()
def gateway():
    _Gateway.calls = []
    _Gateway.version = "0.9.4"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture()
def settings(gateway, tmp_path):
    return con.GatewaySettings(
        base_url=gateway, token=TOKEN, history_path=str(tmp_path / "h.jsonl")
    )


# ── settings ─────────────────────────────────────────────────────────────────


def test_token_file_wins_over_env(tmp_path):
    f = tmp_path / "tok"
    f.write_text("from-file\n")
    s = con.load_settings(
        {"CRAWL4AI_API_TOKEN_FILE": str(f), "CRAWL4AI_API_TOKEN": "from-env"}
    )
    assert s.token == "from-file"


def test_env_token_used_when_no_file(tmp_path):
    s = con.load_settings(
        {
            "CRAWL4AI_API_TOKEN_FILE": str(tmp_path / "missing"),
            "CRAWL4AI_API_TOKEN": "from-env",
        }
    )
    assert s.token == "from-env"
    assert s.base_url == con.DEFAULT_BASE_URL


def test_missing_token_fails_closed(tmp_path):
    with pytest.raises(con.ConsoleError):
        con.load_settings({"CRAWL4AI_API_TOKEN_FILE": str(tmp_path / "missing")})


def test_non_http_base_url_rejected():
    with pytest.raises(con.ConsoleError):
        con.load_settings(
            {"CRAWL4AI_API_TOKEN": "t", "CRAWL4AI_BASE_URL": "file:///etc/passwd"}
        )


def test_token_never_in_repr():
    s = con.GatewaySettings(base_url="http://x", token="secret-value")
    assert "secret-value" not in repr(s)


# ── input handling ───────────────────────────────────────────────────────────


def test_parse_urls_dedupes_and_skips_comments():
    text = "https://a.example/\n# note\nhttps://a.example/, https://b.example/x\n"
    assert con.parse_urls(text) == ["https://a.example/", "https://b.example/x"]


@pytest.mark.parametrize(
    "bad", ["", "ftp://x/", "javascript:alert(1)", "file:///etc/passwd", "no-scheme"]
)
def test_parse_urls_rejects_non_http(bad):
    with pytest.raises(con.ConsoleError):
        con.parse_urls(bad)


def test_parse_urls_caps_batch():
    many = "\n".join(
        f"https://e.example/{i}" for i in range(con.MAX_URLS_PER_BATCH + 1)
    )
    with pytest.raises(con.ConsoleError):
        con.parse_urls(many)


def test_every_console_field_is_untrusted_allowlisted():
    opts = con.CrawlOptions(
        cache_mode="enabled",
        css_selector="main",
        excluded_tags=("nav", " footer ", ""),
        word_count_threshold=5,
        wait_for="css:main",
        page_timeout_ms=30_000,
        exclude_external_links=True,
        remove_overlay_elements=True,
        check_robots_txt=True,
    )
    cfg = con.build_crawler_config(opts)
    assert set(cfg) <= UNTRUSTED_FIELD_ALLOWLIST["CrawlerRunConfig"]
    assert cfg["excluded_tags"] == ["nav", "footer"]
    # The server's own untrusted gate accepts it unchanged.
    loaded = CrawlerRunConfig.load(cfg, provenance=Provenance.UNTRUSTED)
    assert loaded.css_selector == "main"
    assert loaded.page_timeout == 30_000


@pytest.mark.parametrize(
    "opts",
    [
        con.CrawlOptions(cache_mode="nonsense"),
        con.CrawlOptions(page_timeout_ms=999_999),
        con.CrawlOptions(word_count_threshold=-1),
    ],
)
def test_invalid_options_rejected(opts):
    with pytest.raises(con.ConsoleError):
        con.build_crawler_config(opts)


# ── gateway calls ────────────────────────────────────────────────────────────


def test_health_reports_safe_version(settings):
    h = con.check_health(settings)
    assert h.ok and h.version == "0.9.4" and h.safe_version


def test_health_flags_unsafe_version(settings):
    _Gateway.version = "0.9.3"
    h = con.check_health(settings)
    assert h.ok and not h.safe_version


def test_health_unreachable():
    s = con.GatewaySettings(base_url="http://127.0.0.1:9", token=TOKEN)
    h = con.check_health(s, timeout=2)
    assert not h.ok and h.status_code is None


def test_run_crawl_produces_contract_record(settings):
    view = con.run_crawl(settings, "https://example.com/", {"stream": False}, "0.9.4")
    rec = view.record
    assert rec["status"] == con.c.SUCCEEDED
    assert rec["crawler_version"] == "0.9.4"
    assert rec["raw_checksum"] == con.c.raw_checksum(rec["raw_response"])
    # fit is empty, so the contract falls back to raw and keeps the code block.
    assert view.markdown_source == "raw_markdown"
    assert "```py" in view.markdown


def test_retryable_failure_is_retried_then_terminal(settings):
    view = con.run_crawl(
        settings,
        "https://flaky.example/",
        {"stream": False},
        "0.9.4",
        sleeper=lambda _s: None,
    )
    assert view.record["status"] == con.c.FAILED_TERMINAL
    assert view.record["attempts"] == con.c.MAX_ATTEMPTS


def test_self_test_passes_against_hardened_gateway(settings):
    checks = con.self_test(settings)
    assert [ch.passed for ch in checks] == [True] * len(checks), checks


def test_self_test_fails_on_old_version(settings):
    _Gateway.version = "0.9.3"
    checks = {ch.name: ch for ch in con.self_test(settings)}
    assert not checks["Version floor (AC-01)"].passed


# ── history ──────────────────────────────────────────────────────────────────


def test_history_stores_provenance_not_page_content(settings):
    view = con.run_crawl(settings, "https://example.com/", {"stream": False}, "0.9.4")
    con.append_history(settings.history_path, view.record)
    rows = con.read_history(settings.history_path)
    assert len(rows) == 1 and rows[0]["run_id"] == view.record["run_id"]
    raw = open(settings.history_path).read()
    assert "x = 1" not in raw and "raw_response" not in raw
    assert TOKEN not in raw


def test_history_is_bounded_and_tolerates_torn_lines(tmp_path, monkeypatch):
    path = str(tmp_path / "h.jsonl")
    monkeypatch.setattr(con, "HISTORY_MAX_RECORDS", 3)
    for i in range(5):
        con.append_history(path, {"run_id": f"r{i}", "status": "succeeded"})
    with open(path, "a") as fh:
        fh.write('{"torn": \n')
    rows = con.read_history(path)
    assert [r["run_id"] for r in rows] == ["r2", "r3", "r4"]
