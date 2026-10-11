"""
Operator-console logic for the private Crawl4AI gateway (Streamlit-free).

Every crawl goes through the same code the n8n workflow contract is specified
by -- deploy/n8n/contract.py for classification, retries and provenance, and
deploy/gateway/e2e.py for the HTTP calls and security probes -- so what the
console shows is what n8n would record. Nothing here reimplements the contract.

The bearer token is read server-side (env var or mounted secret file) and is
never returned to the browser.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

_HERE = os.path.dirname(os.path.abspath(__file__))
for _rel in (("..", "n8n"), ("..", "gateway")):
    _path = os.path.normpath(os.path.join(_HERE, *_rel))
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)

import contract as c  # noqa: E402
import e2e  # noqa: E402

DEFAULT_BASE_URL = c.BASE_URL
TOKEN_FILE_DEFAULT = "/run/secrets/api_token"

#: Hard ceilings for one console submission. The gateway enforces its own
#: limits; these keep a single operator click from becoming a load test.
MAX_URLS_PER_BATCH = 10
MAX_TIMEOUT_S = 300

CACHE_MODES = ("bypass", "enabled", "read_only", "write_only")
MARKDOWN_VARIANTS = ("auto", "raw_markdown", "fit_markdown")


class ConsoleError(Exception):
    """A user-facing configuration or input problem."""


# ── configuration ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GatewaySettings:
    base_url: str
    token: str = field(repr=False)
    history_path: str | None = None

    @property
    def token_source_label(self) -> str:
        return "set" if self.token else "missing"


def load_settings(environ: dict[str, str] | None = None) -> GatewaySettings:
    """Resolve gateway settings; the token comes from a file or the env."""
    env = os.environ if environ is None else environ
    base_url = (env.get("CRAWL4AI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    scheme = urlsplit(base_url).scheme
    if scheme not in ("http", "https"):
        raise ConsoleError(f"CRAWL4AI_BASE_URL must be http(s), got {base_url!r}")

    token = ""
    token_file = env.get("CRAWL4AI_API_TOKEN_FILE") or TOKEN_FILE_DEFAULT
    if os.path.isfile(token_file):
        with open(token_file, encoding="utf-8") as fh:
            token = fh.read().strip()
    if not token:
        token = (env.get("CRAWL4AI_API_TOKEN") or "").strip()
    if not token:
        raise ConsoleError(
            "No gateway token: set CRAWL4AI_API_TOKEN or mount a secret at "
            f"{token_file}."
        )
    history_path = env.get("CONSOLE_HISTORY_PATH") or None
    return GatewaySettings(base_url=base_url, token=token, history_path=history_path)


# ── input handling ───────────────────────────────────────────────────────────


def parse_urls(text: str) -> list[str]:
    """One URL per line (or comma separated); http(s) only, de-duplicated."""
    seen, urls = set(), []
    for raw in (text or "").replace(",", "\n").splitlines():
        url = raw.strip()
        if not url or url.startswith("#"):
            continue
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ConsoleError(f"Not an http(s) URL: {url!r}")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    if not urls:
        raise ConsoleError("Enter at least one URL.")
    if len(urls) > MAX_URLS_PER_BATCH:
        raise ConsoleError(
            f"{len(urls)} URLs given; the console runs at most "
            f"{MAX_URLS_PER_BATCH} per batch. Use n8n for bulk jobs."
        )
    return urls


@dataclass(frozen=True)
class CrawlOptions:
    cache_mode: str = "bypass"
    css_selector: str = ""
    excluded_tags: tuple[str, ...] = ()
    word_count_threshold: int | None = None
    wait_for: str = ""
    page_timeout_ms: int | None = None
    exclude_external_links: bool = False
    remove_overlay_elements: bool = False
    check_robots_txt: bool = False


def build_crawler_config(opts: CrawlOptions) -> dict[str, Any]:
    """Build a /crawl crawler_config using only untrusted-allowlisted fields.

    The server re-validates everything; staying inside the allowlist here
    means a console request is never refused for a field we chose to send.
    """
    if opts.cache_mode not in CACHE_MODES:
        raise ConsoleError(f"cache_mode must be one of {CACHE_MODES}")
    cfg: dict[str, Any] = {"stream": False, "cache_mode": opts.cache_mode}
    if opts.css_selector.strip():
        cfg["css_selector"] = opts.css_selector.strip()
    tags = [t.strip() for t in opts.excluded_tags if t and t.strip()]
    if tags:
        cfg["excluded_tags"] = tags
    if opts.word_count_threshold is not None:
        if opts.word_count_threshold < 0:
            raise ConsoleError("word_count_threshold must be >= 0")
        cfg["word_count_threshold"] = int(opts.word_count_threshold)
    if opts.wait_for.strip():
        cfg["wait_for"] = opts.wait_for.strip()
    if opts.page_timeout_ms is not None:
        if not 1_000 <= opts.page_timeout_ms <= 60_000:
            raise ConsoleError("page_timeout_ms must be between 1000 and 60000")
        cfg["page_timeout"] = int(opts.page_timeout_ms)
    for flag in (
        "exclude_external_links",
        "remove_overlay_elements",
        "check_robots_txt",
    ):
        if getattr(opts, flag):
            cfg[flag] = True
    return cfg


# ── gateway calls ────────────────────────────────────────────────────────────


@dataclass
class Health:
    ok: bool
    status_code: int | None
    version: str | None
    latency_ms: float
    safe_version: bool
    error: str | None = None


def check_health(settings: GatewaySettings, timeout: int = 10) -> Health:
    started = time.perf_counter()
    status, body, err = e2e._request(
        settings.base_url, "/health", None, None, timeout, method="GET"
    )
    latency = (time.perf_counter() - started) * 1000
    version = (body or {}).get("version") if status == 200 else None
    return Health(
        ok=status == 200 and bool(version),
        status_code=status,
        version=version,
        latency_ms=round(latency, 1),
        safe_version=bool(version)
        and e2e.version_tuple(version) >= e2e.MIN_SAFE_VERSION,
        error=err,
    )


@dataclass
class RunView:
    """One crawl as the console shows it: the n8n record plus the text."""

    record: dict[str, Any]
    markdown: str
    markdown_source: str
    markdown_reason: str
    http_status: int | None


def _first_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        results = raw.get("results") or []
        if results and isinstance(results[0], dict):
            return results[0]
    return {}


def extract_markdown(raw: Any, variant: str = "auto") -> tuple[str, str, str]:
    """Pick the markdown to show, applying the contract's code-safe fallback."""
    result = _first_result(raw)
    md = result.get("markdown")
    if isinstance(md, dict):
        raw_md = md.get("raw_markdown") or ""
        fit_md = md.get("fit_markdown") or ""
    else:
        raw_md, fit_md = (md or ""), ""
    if variant == "raw_markdown":
        return raw_md, "raw_markdown", "selected by operator"
    if variant == "fit_markdown":
        return fit_md, "fit_markdown", "selected by operator"
    sel = c.select_markdown(raw_md, fit_md)
    return sel.text, sel.source, sel.reason


def run_crawl(
    settings: GatewaySettings,
    url: str,
    crawler_config: dict[str, Any],
    crawler_version: str,
    timeout_s: int = 180,
    variant: str = "auto",
    sleeper=time.sleep,
) -> RunView:
    """One logical run with the contract's retries and provenance."""
    timeout_s = max(5, min(int(timeout_s), MAX_TIMEOUT_S))
    run, status = e2e.run_with_retries(
        settings.base_url,
        settings.token,
        url,
        timeout_s,
        crawler_config,
        crawler_version,
        sleeper=sleeper,
    )
    record = run.to_dict()
    text, source, reason = extract_markdown(record["raw_response"], variant)
    return RunView(record, text, source, reason, status)


# ── security self-test ───────────────────────────────────────────────────────


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def self_test(settings: GatewaySettings, probe_url: str = "https://example.com/"):
    """Live, read-only security checks against the running gateway.

    Mirrors the E2E acceptance items that can run without a workload: version
    floor (AC-01), auth (AC-03), the untrusted-config gate (AC-04 /
    GHSA-5w5p-vcv6-mm3f) and metadata-SSRF refusal (AC-04). None of these
    probes can send anything off the box, even against a vulnerable server.
    """
    checks: list[Check] = []
    health = check_health(settings)
    checks.append(
        Check(
            "Version floor (AC-01)",
            health.safe_version,
            f"/health reports {health.version or 'nothing'} "
            f"(minimum {'.'.join(map(str, e2e.MIN_SAFE_VERSION))})",
        )
    )
    cfg = {"stream": False, "cache_mode": "bypass"}
    no_tok, _, _ = e2e.crawl_once(settings.base_url, None, probe_url, 30, cfg)
    checks.append(
        Check(
            "No token refused (AC-03)",
            no_tok in (401, 403),
            f"HTTP {no_tok}",
        )
    )
    bad_tok, _, _ = e2e.crawl_once(
        settings.base_url, "not-the-token", probe_url, 30, cfg
    )
    checks.append(
        Check(
            "Wrong token refused (AC-03)",
            bad_tok in (401, 403),
            f"HTTP {bad_tok}",
        )
    )
    probe, _, _ = e2e.crawl_once(
        settings.base_url, settings.token, probe_url, 60, e2e.LAUNDERING_PROBE_CONFIG
    )
    checks.append(
        Check(
            "Config laundering refused (GHSA-5w5p)",
            probe == 400,
            f"HTTP {probe} (expected 400)",
        )
    )
    meta, body, _ = e2e.crawl_once(
        settings.base_url,
        settings.token,
        "http://169.254.169.254/latest/meta-data/",
        60,
        cfg,
    )
    cls = c.classify_response(meta, body)
    checks.append(
        Check(
            "Metadata SSRF refused (AC-04)",
            cls.status != c.SUCCEEDED,
            f"HTTP {meta}, classified {cls.status}/{cls.failure_class}",
        )
    )
    return checks


# ── run history (local, optional) ────────────────────────────────────────────

_HISTORY_LOCK = threading.Lock()
HISTORY_MAX_RECORDS = 500


def summarize(record: dict[str, Any]) -> dict[str, Any]:
    """The history row: provenance only, never the raw page body."""
    return {
        k: record.get(k)
        for k in (
            "run_id",
            "source_url",
            "started_at",
            "finished_at",
            "status",
            "failure_class",
            "attempts",
            "crawler_version",
            "config_fingerprint",
            "raw_checksum",
        )
    }


def append_history(path: str | None, record: dict[str, Any]) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    line = json.dumps(summarize(record), sort_keys=True)
    with _HISTORY_LOCK:
        rows = read_history(path)
        rows.append(json.loads(line))
        rows = rows[-HISTORY_MAX_RECORDS:]
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        os.replace(tmp, path)


def read_history(path: str | None) -> list[dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # one torn line must not hide the rest
    return rows
