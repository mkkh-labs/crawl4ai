#!/usr/bin/env python3
"""
Observability signal availability (SPEC.md M8, offline half).

M8 splits in two. The resource soak needs a live container and lives in
scripts/gateway_soak.py. What can be asserted offline is that the signals an
operator needs actually exist and are correlation-ready: a health endpoint, a
Prometheus scrape target, and declared resource budgets for the soak to
compare against. Correlation ids on 5xx are already covered by
test_security_headers_xss.py::TestErrorSanitization, so they are not
re-asserted here.

A healthy /health is explicitly NOT proof that browser resources are healthy --
that is what the soak is for.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)


class TestHealthSignal:
    def test_health_is_reachable_without_a_credential(self, stock_client):
        """The container healthcheck runs before any token is presented."""
        r = stock_client.get("/health")
        assert r.status_code == 200

    def test_health_reports_version(self, stock_client, effective_config):
        body = stock_client.get("/health").json()
        assert "version" in body, body


class TestPrometheusSignal:
    def test_prometheus_is_enabled_in_shipped_config(self, effective_config):
        assert effective_config["observability"]["prometheus"]["enabled"] is True

    def test_metrics_endpoint_is_configured(self, effective_config):
        assert effective_config["observability"]["prometheus"]["endpoint"] == "/metrics"

    def test_metrics_endpoint_is_not_anonymous(self, stock_client):
        """Metrics expose request volume and target shape; they are gated."""
        r = stock_client.get("/metrics")
        assert r.status_code in (401, 403), r.status_code


class TestResourceGovernanceIsObservable:
    """The soak needs finite, declared budgets to compare a run against."""

    def test_pool_and_queue_budgets_are_declared(self, effective_config):
        assert effective_config["crawler"]["pool"]["max_pages"] > 0
        assert effective_config["crawler"]["pool"]["idle_ttl_sec"] > 0
        assert effective_config["limits"]["queue"]["maxsize"] > 0

    def test_memory_threshold_is_declared(self, effective_config):
        threshold = effective_config["crawler"]["memory_threshold_percent"]
        assert 0 < threshold <= 100


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
