"""Executable reference for the n8n -> Crawl4AI integration contract.

SPEC.md M5 (HTTP contract) and M6 (provenance + failure taxonomy).

Scope
-----
This module is the *normative reference* for behavior that runs in n8n, not
server code. Crawl4AI is not modified and gains no persistence: the gateway
keeps returning the upstream `/crawl` response unchanged, and everything here
happens on the caller's side. Keeping it in-repo and executable means the retry
matrix and provenance envelope are covered by tests instead of living only in a
workflow export nobody can diff.

Nothing in this module performs I/O, so it is deterministic and offline.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

# ── constants ────────────────────────────────────────────────────────────────

#: Internal service DNS. There is deliberately no public hostname.
BASE_URL = "http://crawl4ai:11235"
CRAWL_ENDPOINT = "/crawl"

#: SPEC.md M6 failure taxonomy. Every failure maps to exactly one of these.
FAILURE_CLASSES = frozenset(
    {
        "validation",
        "auth",
        "rate_limit",
        "capacity",
        "deadline",
        "network",
        "server",
        "content_contract",
        "blocked_target",
        "unknown",
    }
)

#: CrawlRun.status values.
SUCCEEDED = "succeeded"
FAILED_RETRYABLE = "failed_retryable"
FAILED_TERMINAL = "failed_terminal"

#: Bounded retry budget. Bounded is the point: an unbounded budget turns a
#: broken target into a retry storm against it. [A]
MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 2.0
BACKOFF_CAP_S = 60.0

#: Header names that must never reach a provenance record or a log line.
SECRET_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
    }
)

#: Query parameters commonly carrying credentials in target URLs.
SECRET_QUERY_KEYS = frozenset(
    {
        "token",
        "access_token",
        "api_key",
        "apikey",
        "key",
        "signature",
        "sig",
        "password",
        "secret",
    }
)

#: Result-level errors that mean "the target refused us", not "we broke".
#: Retrying these immediately is what CLAUDE.md forbids as a retry storm.
_BLOCKED_MARKERS = re.compile(
    r"\b(403|401|blocked|forbidden|captcha|cloudflare|bot detection|access denied|"
    r"rate.?limited|too many requests)\b",
    re.I,
)


@dataclass(frozen=True)
class Classification:
    """How one attempt's outcome maps onto the taxonomy."""

    status: str
    failure_class: str | None
    retryable: bool

    def __post_init__(self) -> None:
        assert self.status in (SUCCEEDED, FAILED_RETRYABLE, FAILED_TERMINAL)
        assert self.failure_class is None or self.failure_class in FAILURE_CLASSES
        if self.status == SUCCEEDED:
            assert self.failure_class is None and not self.retryable
        if self.status == FAILED_TERMINAL:
            assert not self.retryable, "terminal failures are never retried"


# ── HTTP status classification (SPEC.md M5) ──────────────────────────────────

#: Explicit status -> (failure_class, retryable). Anything unlisted falls back
#: to the range rules in `classify_http`, which fail terminal for 4xx.
_STATUS_MAP: dict[int, tuple[str, bool]] = {
    400: ("validation", False),
    401: ("auth", False),
    403: ("auth", False),
    # 413 is the server refusing an oversized request body. It is a property of
    # the request we sent, so it is terminal and belongs with validation rather
    # than capacity -- resending the same body cannot succeed. [A]
    413: ("validation", False),
    422: ("validation", False),
    429: ("rate_limit", True),
    500: ("server", True),
    502: ("server", True),
    503: ("capacity", True),
    504: ("deadline", True),
}


def classify_http(status_code: int) -> Classification:
    """Classify an HTTP status from the gateway."""
    if 200 <= status_code < 300:
        return Classification(SUCCEEDED, None, False)

    mapped = _STATUS_MAP.get(status_code)
    if mapped is not None:
        failure_class, retryable = mapped
    elif 400 <= status_code < 500:
        # Unlisted 4xx: our request is wrong in some way we did not anticipate.
        # Never blind-retry a 4xx.
        failure_class, retryable = "validation", False
    elif status_code >= 500:
        failure_class, retryable = "server", True
    else:
        failure_class, retryable = "unknown", False

    return Classification(
        FAILED_RETRYABLE if retryable else FAILED_TERMINAL, failure_class, retryable
    )


def classify_exception(exc: BaseException) -> Classification:
    """Classify a transport-level failure (no HTTP status was received)."""
    return Classification(FAILED_RETRYABLE, "network", True)


def classify_body(body: Any) -> Classification:
    """Classify the body of a 2xx response.

    A 2xx only means the gateway accepted and ran the job. The crawl itself can
    still have failed, and the upstream contract reports that inside `results`.
    Treating 2xx as success without reading the body is exactly the silent
    failure this contract exists to prevent.
    """
    if not isinstance(body, Mapping):
        return Classification(FAILED_TERMINAL, "content_contract", False)
    if "success" not in body or "results" not in body:
        return Classification(FAILED_TERMINAL, "content_contract", False)

    results = body.get("results")
    if not isinstance(results, list) or not results:
        return Classification(FAILED_TERMINAL, "content_contract", False)

    if body.get("success") is not True:
        return _classify_result_failure(results)

    for item in results:
        if not isinstance(item, Mapping):
            return Classification(FAILED_TERMINAL, "content_contract", False)
        if item.get("success") is not True:
            return _classify_result_failure(results)

    return Classification(SUCCEEDED, None, False)


def _classify_result_failure(results: Iterable[Any]) -> Classification:
    """A crawl-level failure inside a 2xx envelope. Terminal by default."""
    messages = " ".join(
        str(r.get("error_message") or r.get("error") or "")
        for r in results
        if isinstance(r, Mapping)
    )
    if _BLOCKED_MARKERS.search(messages):
        return Classification(FAILED_TERMINAL, "blocked_target", False)
    return Classification(FAILED_TERMINAL, "unknown", False)


def classify_response(status_code: int, body: Any = None) -> Classification:
    """Full classification for one attempt: status first, then body."""
    by_status = classify_http(status_code)
    if by_status.status != SUCCEEDED:
        return by_status
    return classify_body(body)


# ── retry policy (SPEC.md M5) ────────────────────────────────────────────────


def should_retry(classification: Classification, attempt: int) -> bool:
    """Retry only classified-retryable failures, and only within budget.

    `attempt` is 1-based: attempt 1 is the first try.
    """
    if not classification.retryable:
        return False
    return attempt < MAX_ATTEMPTS


def retry_delay_seconds(attempt: int, retry_after: str | float | None = None) -> float:
    """Bounded exponential backoff, honoring Retry-After when the server sends it."""
    if retry_after is not None:
        try:
            parsed = float(retry_after)
            if parsed >= 0:
                return min(parsed, BACKOFF_CAP_S)
        except (TypeError, ValueError):
            pass  # HTTP-date form: fall through to backoff.
    return min(BACKOFF_BASE_S**attempt, BACKOFF_CAP_S)


# ── canonicalization + provenance (SPEC.md M6) ───────────────────────────────


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes: stable key order, no incidental whitespace.

    Two semantically identical configs must fingerprint identically regardless
    of key order, or the fingerprint cannot be used to compare runs.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def config_fingerprint(
    browser_config: Mapping[str, Any] | None,
    crawler_config: Mapping[str, Any] | None,
) -> str:
    """Fingerprint the request configuration that produced a run."""
    return sha256_hex(
        canonical_json(
            {
                "browser_config": browser_config or {},
                "crawler_config": crawler_config or {},
            }
        )
    )


def raw_checksum(raw_response: Any) -> str:
    """Checksum the raw response exactly as received."""
    if isinstance(raw_response, (bytes, bytearray)):
        return sha256_hex(bytes(raw_response))
    return sha256_hex(canonical_json(raw_response))


def redact_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    """Drop credential-bearing headers. Values are never partially echoed."""
    return {
        k: ("[REDACTED]" if k.lower() in SECRET_HEADERS else str(v))
        for k, v in headers.items()
    }


def redact_url(url: str) -> str:
    """Strip credential-bearing query values from a URL kept as evidence."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = [
        (k, "[REDACTED]" if k.lower() in SECRET_QUERY_KEYS else v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment)
    )


@dataclass
class CrawlRun:
    """The downstream provenance envelope (SPEC.md M6).

    Held by n8n/storage, never by Crawl4AI.
    """

    run_id: str
    source_url: str
    started_at: str
    finished_at: str
    crawler_version: str
    config_fingerprint: str
    raw_response: Any
    raw_checksum: str
    status: str
    failure_class: str | None
    artifact_ref: str | None = None
    attempts: int = 1
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source_url": redact_url(self.source_url),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "crawler_version": self.crawler_version,
            "config_fingerprint": self.config_fingerprint,
            "raw_response": self.raw_response,
            "raw_checksum": self.raw_checksum,
            "status": self.status,
            "failure_class": self.failure_class,
            "artifact_ref": self.artifact_ref,
            "attempts": self.attempts,
            "failures": self.failures,
        }


def build_crawl_run(
    *,
    run_id: str,
    source_url: str,
    started_at: str,
    finished_at: str,
    crawler_version: str,
    browser_config: Mapping[str, Any] | None,
    crawler_config: Mapping[str, Any] | None,
    raw_response: Any,
    classification: Classification,
    attempts: int = 1,
    failures: list[dict[str, Any]] | None = None,
    artifact_ref: str | None = None,
) -> CrawlRun:
    """Assemble a complete, checksummed provenance record for one run."""
    return CrawlRun(
        run_id=run_id,
        source_url=source_url,
        started_at=started_at,
        finished_at=finished_at,
        crawler_version=crawler_version,
        config_fingerprint=config_fingerprint(browser_config, crawler_config),
        raw_response=raw_response,
        raw_checksum=raw_checksum(raw_response),
        status=classification.status,
        failure_class=classification.failure_class,
        artifact_ref=artifact_ref,
        attempts=attempts,
        failures=failures or [],
    )


def failure_record(
    *,
    run_id: str,
    classification: Classification,
    attempt: int,
    http_status: int | None,
    message: str,
) -> dict[str, Any]:
    """One attempt's failure evidence.

    The raw exception text is digested rather than stored: upstream error
    strings can echo request URLs (and therefore their query strings) back.
    """
    return {
        "run_id": run_id,
        "class": classification.failure_class,
        "http_status": http_status,
        "retryable": classification.retryable,
        "attempt": attempt,
        "message_digest": sha256_hex(message.encode("utf-8")),
    }


# ── extraction fidelity fallback (SPEC.md M7) ────────────────────────────────

CODE_FENCE = "```"


def code_fence_count(markdown: str) -> int:
    return (markdown or "").count(CODE_FENCE)


def inline_code_count(markdown: str) -> int:
    """Count single-backtick spans, ignoring fence markers."""
    return len(re.findall(r"(?<!`)`[^`\n]+`(?!`)", markdown or ""))


@dataclass(frozen=True)
class MarkdownSelection:
    """Which markdown variant a run should index, and why."""

    text: str
    source: str  # "fit_markdown" | "raw_markdown"
    reason: str


def select_markdown(raw_markdown: str, fit_markdown: str | None) -> MarkdownSelection:
    """Choose the variant to index, falling back to raw when fit loses code.

    `fit_markdown` is preferred when present: it strips navigation and other
    boilerplate. But it is produced by a content filter, and a filter that drops
    a fenced block silently turns a code sample into prose. For a technical
    corpus that is data loss, so raw wins whenever fit lost code that raw had.

    Note the production Docker config sets no content filter, in which case
    `fit_markdown` is empty and this returns raw. That is the common path, not
    an error -- which is exactly why callers must not read `fit_markdown`
    unconditionally.
    """
    fit = fit_markdown or ""
    if not fit.strip():
        return MarkdownSelection(raw_markdown, "raw_markdown", "fit_markdown is empty")

    if code_fence_count(fit) < code_fence_count(raw_markdown):
        return MarkdownSelection(
            raw_markdown, "raw_markdown", "fit_markdown dropped fenced code blocks"
        )

    if inline_code_count(fit) < inline_code_count(raw_markdown):
        return MarkdownSelection(
            raw_markdown, "raw_markdown", "fit_markdown dropped inline code spans"
        )

    return MarkdownSelection(fit, "fit_markdown", "fit_markdown preserved code content")
