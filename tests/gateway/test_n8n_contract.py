#!/usr/bin/env python3
"""
Contract tests for the n8n -> Crawl4AI integration (SPEC.md M5 and M6).

These pin the caller-side behavior that keeps automation failures loud:
every response class maps to exactly one taxonomy entry, retries are bounded
and only ever attempted for classified-retryable failures, and the provenance
envelope is complete and carries no credential material.

Offline and deterministic: fixtures are sanitized JSON captured in-repo, and
the reference implementation performs no I/O.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
N8N_DIR = os.path.join(REPO_ROOT, "deploy", "n8n")
FIXTURES = os.path.join(N8N_DIR, "fixtures")
sys.path.insert(0, N8N_DIR)

import contract as c  # noqa: E402


def load(name: str) -> dict:
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


# ───────────────────────────── M5: status taxonomy ──────────────────────────


class TestResponseClassification:
    def test_success_fixture_is_succeeded(self):
        fx = load("success_2xx.json")
        got = c.classify_response(fx["http_status"], fx["body"])
        assert got.status == c.SUCCEEDED
        assert got.failure_class is None
        assert got.retryable is False

    @pytest.mark.parametrize(
        "fixture,expected_class",
        [
            ("terminal_4xx_validation.json", "validation"),
            ("terminal_4xx_auth.json", "auth"),
        ],
    )
    def test_terminal_4xx_is_never_retried(self, fixture, expected_class):
        fx = load(fixture)
        got = c.classify_response(fx["http_status"], fx["body"])
        assert got.status == c.FAILED_TERMINAL
        assert got.failure_class == expected_class
        assert got.retryable is False
        assert c.should_retry(got, attempt=1) is False

    @pytest.mark.parametrize(
        "fixture,expected_class",
        [
            ("retryable_5xx.json", "capacity"),
            ("retryable_504_deadline.json", "deadline"),
        ],
    )
    def test_retryable_server_failures(self, fixture, expected_class):
        fx = load(fixture)
        got = c.classify_response(fx["http_status"], fx["body"])
        assert got.status == c.FAILED_RETRYABLE
        assert got.failure_class == expected_class
        assert got.retryable is True

    def test_malformed_success_body_is_a_terminal_contract_failure(self):
        """A 2xx with the wrong shape must not be indexed as a good crawl."""
        fx = load("malformed_success.json")
        got = c.classify_response(fx["http_status"], fx["body"])
        assert got.status == c.FAILED_TERMINAL
        assert got.failure_class == "content_contract"

    def test_2xx_with_failed_result_is_not_silent_success(self):
        """The silent-failure case: HTTP fine, crawl refused by the target."""
        fx = load("blocked_target_2xx.json")
        got = c.classify_response(fx["http_status"], fx["body"])
        assert got.status == c.FAILED_TERMINAL
        assert got.failure_class == "blocked_target"
        assert (
            c.should_retry(got, attempt=1) is False
        ), "no retry storm at a blocking target"

    def test_network_exception_is_retryable_network_class(self):
        got = c.classify_exception(TimeoutError("read timeout"))
        assert got.status == c.FAILED_RETRYABLE
        assert got.failure_class == "network"

    @pytest.mark.parametrize("code", [400, 401, 403, 413, 422, 429, 500, 502, 503, 504])
    def test_every_documented_status_maps_into_the_taxonomy(self, code):
        got = c.classify_http(code)
        assert got.failure_class in c.FAILURE_CLASSES

    @pytest.mark.parametrize("code", [402, 418, 451, 599])
    def test_unlisted_4xx_is_terminal_and_unlisted_5xx_retryable(self, code):
        got = c.classify_http(code)
        if code < 500:
            assert got.retryable is False, "never blind-retry a 4xx"
        else:
            assert got.retryable is True


# ───────────────────────────── M5: retry policy ─────────────────────────────


class TestRetryPolicy:
    def test_retry_budget_is_bounded(self):
        retryable = c.classify_http(503)
        attempts = [a for a in range(1, 10) if c.should_retry(retryable, a)]
        assert attempts == [1, 2], attempts
        assert len(attempts) + 1 == c.MAX_ATTEMPTS

    def test_terminal_never_retries_at_any_attempt(self):
        terminal = c.classify_http(401)
        assert not any(c.should_retry(terminal, a) for a in range(1, 10))

    def test_retry_after_is_honored(self):
        fx = load("retryable_504_deadline.json")
        assert c.retry_delay_seconds(1, fx["retry_after"]) == 12.0

    def test_backoff_grows_and_is_capped(self):
        delays = [c.retry_delay_seconds(a) for a in range(1, 12)]
        assert delays == sorted(delays), "backoff must be non-decreasing"
        assert max(delays) <= c.BACKOFF_CAP_S

    def test_http_date_retry_after_falls_back_to_backoff(self):
        got = c.retry_delay_seconds(1, "Wed, 21 Oct 2026 07:28:00 GMT")
        assert got == c.retry_delay_seconds(1)


# ──────────────────────── M6: canonicalization + hashing ────────────────────


class TestCanonicalization:
    def test_fingerprint_is_key_order_independent(self):
        a = c.config_fingerprint(
            {"headless": True, "text_mode": True}, {"stream": False}
        )
        b = c.config_fingerprint(
            {"text_mode": True, "headless": True}, {"stream": False}
        )
        assert a == b

    def test_fingerprint_changes_with_config(self):
        a = c.config_fingerprint(None, {"cache_mode": "bypass"})
        b = c.config_fingerprint(None, {"cache_mode": "enabled"})
        assert a != b

    def test_checksum_is_deterministic_and_labelled(self):
        body = load("success_2xx.json")["body"]
        first = c.raw_checksum(body)
        assert first == c.raw_checksum(json.loads(json.dumps(body)))
        assert first.startswith("sha256:")

    def test_checksum_detects_any_change(self):
        body = load("success_2xx.json")["body"]
        mutated = json.loads(json.dumps(body))
        mutated["results"][0]["markdown"]["raw_markdown"] += " "
        assert c.raw_checksum(body) != c.raw_checksum(mutated)


# ────────────────────────── M6: provenance envelope ─────────────────────────

REQUIRED_FIELDS = (
    "run_id",
    "source_url",
    "started_at",
    "finished_at",
    "crawler_version",
    "config_fingerprint",
    "raw_response",
    "raw_checksum",
    "status",
    "failure_class",
)


def _run(fixture="success_2xx.json", **over):
    fx = load(fixture)
    cls = c.classify_response(fx["http_status"], fx["body"])
    kwargs = dict(
        run_id="run-0001",
        source_url="https://example.com/docs/install",
        started_at="2026-09-06T08:00:00Z",
        finished_at="2026-09-06T08:00:04Z",
        crawler_version="0.9.3",
        browser_config={},
        crawler_config={"stream": False, "cache_mode": "bypass"},
        raw_response=fx["body"],
        classification=cls,
    )
    kwargs.update(over)
    return c.build_crawl_run(**kwargs)


class TestProvenanceEnvelope:
    @pytest.mark.parametrize("field_name", REQUIRED_FIELDS)
    def test_required_field_present(self, field_name):
        record = _run().to_dict()
        assert field_name in record
        if field_name != "failure_class":
            assert record[field_name] not in (None, "", {}), field_name

    def test_raw_response_is_preserved_verbatim(self):
        """Evidence must survive downstream normalization."""
        fx = load("success_2xx.json")
        assert _run().raw_response == fx["body"]

    def test_status_and_failure_class_agree_with_classification(self):
        assert _run().status == c.SUCCEEDED
        failed = _run("terminal_4xx_auth.json")
        assert failed.status == c.FAILED_TERMINAL
        assert failed.failure_class == "auth"

    def test_run_is_reconstructible_from_its_checksum(self):
        record = _run().to_dict()
        assert c.raw_checksum(record["raw_response"]) == record["raw_checksum"]

    def test_rerun_is_a_new_run_not_an_overwrite(self):
        first, second = _run(run_id="run-0001"), _run(run_id="run-0002")
        assert first.run_id != second.run_id
        # Same source and config => same fingerprint, so runs stay comparable.
        assert first.config_fingerprint == second.config_fingerprint


class TestNoSecretsInProvenance:
    def test_authorization_header_is_redacted(self):
        red = c.redact_headers(
            {"Authorization": "Bearer super-secret-value", "Accept": "application/json"}
        )
        assert red["Authorization"] == "[REDACTED]"
        assert "super-secret-value" not in json.dumps(red)
        assert red["Accept"] == "application/json"

    @pytest.mark.parametrize("header", sorted(c.SECRET_HEADERS))
    def test_every_secret_header_is_redacted(self, header):
        assert c.redact_headers({header: "leak-me"})[header] == "[REDACTED]"

    def test_secret_query_values_are_stripped_from_evidence(self):
        record = _run(
            source_url="https://example.com/x?api_key=leak-me&page=2"
        ).to_dict()
        blob = json.dumps(record)
        assert "leak-me" not in blob
        assert "page=2" in record["source_url"]

    def test_failure_record_digests_the_message(self):
        rec = c.failure_record(
            run_id="run-0001",
            classification=c.classify_http(500),
            attempt=2,
            http_status=500,
            message="upstream error for https://example.com/x?token=leak-me",
        )
        assert "leak-me" not in json.dumps(rec)
        assert rec["message_digest"].startswith("sha256:")


class TestRetryExhaustionEvidence:
    """A run that burns its budget must leave enough to open a Linear issue."""

    def test_exhausted_retries_produce_terminal_evidence(self):
        cls = c.classify_http(503)
        failures, attempt = [], 1
        while True:
            failures.append(
                c.failure_record(
                    run_id="run-0009",
                    classification=cls,
                    attempt=attempt,
                    http_status=503,
                    message="Server busy",
                )
            )
            if not c.should_retry(cls, attempt):
                break
            attempt += 1

        assert attempt == c.MAX_ATTEMPTS
        assert len(failures) == c.MAX_ATTEMPTS

        run = _run("retryable_5xx.json", attempts=attempt, failures=failures)
        record = run.to_dict()
        # Budget is spent, so the run is terminal for the operator even though
        # the last attempt's class was retryable.
        assert record["attempts"] == c.MAX_ATTEMPTS
        assert record["failures"][-1]["class"] == "capacity"
        assert record["run_id"] and record["source_url"] and record["raw_checksum"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
