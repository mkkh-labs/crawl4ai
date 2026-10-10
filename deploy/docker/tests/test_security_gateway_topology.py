#!/usr/bin/env python3
"""
Acceptance tests for the private gateway topology (SPEC.md M2) and the
production runtime configuration (SPEC.md M4).

M2 asserts the *rendered* deployment shape: the crawler publishes no host port,
reaches n8n only over the external `automation_internal` network, requires a
bearer token before compose will start, and keeps every v0.9.3 least-privilege
setting.

M4 asserts the *shipped* config.yml (the artifact that ships in the image, not a
merged runtime dict) plus the live Host guard, which is the control that makes
an explicit trusted_hosts allowlist meaningful.

These parse YAML rather than grepping text: an earlier posture bug was a raw
substring search matching a word inside a comment and guarding nothing.
"""

import os
import sys

import pytest
import yaml

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
COMPOSE = os.path.join(REPO_ROOT, "docker-compose.yml")
CONFIG = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.yml"))

INTERNAL_NETWORK = "automation_internal"
EXPECTED_TRUSTED_HOSTS = ["crawl4ai", "localhost", "127.0.0.1"]


@pytest.fixture(scope="module")
def compose():
    with open(COMPOSE) as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def compose_text():
    with open(COMPOSE) as fh:
        return fh.read()


@pytest.fixture(scope="module")
def shipped_config():
    """config.yml exactly as it ships, before DEFAULT_CONFIG merging."""
    with open(CONFIG) as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def service(compose):
    return compose["services"]["crawl4ai"]


@pytest.fixture(scope="module")
def base(compose):
    return compose["x-base-config"]


# ───────────────────────────── M2: private topology ─────────────────────────


class TestNoPublicExposure:
    def test_service_publishes_no_host_port(self, service, base):
        """AC-03: a host-published crawler port is a release blocker."""
        assert (
            "ports" not in service
        ), f"crawl4ai publishes host ports: {service.get('ports')}"
        assert (
            "ports" not in base
        ), f"shared base publishes host ports: {base.get('ports')}"

    def test_no_service_publishes_a_host_port(self, compose):
        for name, svc in compose.get("services", {}).items():
            assert "ports" not in svc, f"service {name!r} publishes host ports"


class TestPrivateNetwork:
    def test_service_joins_the_internal_network(self, service):
        assert INTERNAL_NETWORK in (service.get("networks") or [])

    def test_network_is_external(self, compose):
        net = (compose.get("networks") or {}).get(INTERNAL_NETWORK)
        assert net is not None, f"{INTERNAL_NETWORK} not declared"
        assert (
            net.get("external") is True
        ), "network must be external (shared with the n8n stack)"


class TestTokenIsMandatory:
    def test_token_uses_compose_required_variable_syntax(self, compose_text):
        """`:?` makes compose fail before starting an unauthenticated service."""
        assert "${CRAWL4AI_API_TOKEN:?" in compose_text
        assert (
            "${CRAWL4AI_API_TOKEN:-}" not in compose_text
        ), "optional-empty token default reintroduced; the gateway would start unauthenticated"


class TestImmutableImageReference:
    def test_default_tag_is_not_latest(self, service):
        """AC-07: production must not resolve to a mutable tag."""
        assert "latest" not in service["image"], service["image"]

    def test_image_is_required_with_no_upstream_fallback(self, compose_text):
        """The stock upstream image lacks this fork's baked-in config.yml
        (trusted_hosts allowlist, Redis limiter). An unset IMAGE must fail
        compose, not silently fall back to it."""
        assert "${IMAGE:?" in compose_text
        assert "${IMAGE:-" not in compose_text
        assert "unclecode/crawl4ai:" not in compose_text


class TestLeastPrivilegePreserved:
    """M2 must not trade away any v0.9.3 hardening to gain private networking."""

    def test_read_only_root(self, base):
        assert base["read_only"] is True

    def test_all_capabilities_dropped(self, base):
        assert base["cap_drop"] == ["ALL"]

    def test_no_new_privileges(self, base):
        assert "no-new-privileges:true" in base["security_opt"]

    def test_memory_limit_is_finite(self, base):
        assert base["deploy"]["resources"]["limits"]["memory"]

    def test_pid_limit_is_finite(self, base):
        pids = base["deploy"]["resources"]["limits"]["pids"]
        assert isinstance(pids, int) and pids > 0

    def test_runs_as_non_root(self, base):
        assert base["user"] == "appuser"

    def test_healthcheck_and_restart_retained(self, base):
        assert "healthcheck" in base
        assert base["restart"] == "unless-stopped"

    def test_writable_areas_are_tmpfs(self, base):
        assert base["tmpfs"], "read-only root needs tmpfs writable areas"

    def test_no_privileged_or_docker_socket(self, compose_text, base):
        assert base.get("privileged") is not True
        assert "/var/run/docker.sock" not in compose_text


# ─────────────────────── M4: shipped runtime configuration ──────────────────


class TestBindPosture:
    def test_host_accepts_private_network_traffic(self, shipped_config):
        """0.0.0.0 + no published port = reachable on automation_internal only.

        This is also what makes the startup guard strict: a non-loopback bind
        refuses to start without a credential.
        """
        assert shipped_config["app"]["host"] == "0.0.0.0"


class TestFiniteResourceLimits:
    """AC-05/AC-06: every governance limit must be finite (0 means unbounded)."""

    def test_wall_clock_deadline_is_300s(self, shipped_config):
        assert shipped_config["limits"]["wall_clock_s"] == 300

    @pytest.mark.parametrize(
        "key", ["max_body_bytes", "max_pages", "max_depth", "wall_clock_s"]
    )
    def test_limit_is_non_zero(self, shipped_config, key):
        value = shipped_config["limits"][key]
        assert (
            isinstance(value, int) and value > 0
        ), f"limits.{key}={value} means unbounded"


class TestRateLimiting:
    def test_enabled(self, shipped_config):
        assert shipped_config["rate_limiting"]["enabled"] is True

    def test_storage_is_redis_backed(self, shipped_config):
        """Shared across gunicorn workers; memory:// resets per worker."""
        uri = shipped_config["rate_limiting"]["storage_uri"]
        assert uri.startswith(("redis://", "rediss://")), uri


class TestSecurityBlock:
    def test_security_enabled(self, shipped_config):
        assert shipped_config["security"]["enabled"] is True

    def test_jwt_disabled_for_service_to_service_mvp(self, shipped_config):
        assert shipped_config["security"]["jwt_enabled"] is False

    def test_trusted_hosts_are_explicit(self, shipped_config):
        hosts = shipped_config["security"]["trusted_hosts"]
        assert hosts == EXPECTED_TRUSTED_HOSTS, hosts
        assert "*" not in hosts

    def test_cors_denies_by_default(self, shipped_config):
        assert shipped_config["security"]["cors_allow_origins"] == []


class TestDangerousFeaturesStayOff:
    def test_compose_does_not_enable_hooks_or_execute_js(self, compose_text):
        for flag in (
            "CRAWL4AI_HOOKS_ENABLED=true",
            "CRAWL4AI_EXECUTE_JS_ENABLED=true",
            "CRAWL4AI_ALLOW_INSECURE_TLS=true",
        ):
            assert flag not in compose_text, f"{flag} must stay off for the MVP"

    def test_tls_verification_flags_absent(self, shipped_config):
        args = shipped_config["crawler"]["browser"].get("extra_args", [])
        for flag in (
            "--ignore-certificate-errors",
            "--allow-insecure-localhost",
            "--disable-web-security",
        ):
            assert flag not in args, f"{flag} disables TLS/origin checks"


# ───────────────────────────── M4: live Host guard ──────────────────────────


class TestHostGuardBehavior:
    """An explicit allowlist is only worth anything if the guard enforces it."""

    def test_trusted_host_is_accepted(self, stock_client):
        # stock_client sends Host: crawl4ai, the production service DNS name.
        r = stock_client.get("/health")
        assert r.status_code == 200, r.status_code

    @pytest.mark.parametrize(
        "host", ["evil.example", "attacker.test", "crawl4ai.evil.example"]
    )
    def test_untrusted_host_is_rejected(self, server_module, host):
        from starlette.testclient import TestClient

        client = TestClient(
            server_module.app, base_url=f"http://{host}", raise_server_exceptions=False
        )
        r = client.get("/health")
        assert (
            r.status_code == 400
        ), f"Host {host!r} was not rejected (got {r.status_code})"
        assert "host" in r.text.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
