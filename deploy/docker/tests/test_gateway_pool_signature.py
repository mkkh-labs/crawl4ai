"""
Request-built browser configs must share the permanent browser's pool
signature, and must carry the operator's config.yml browser policy.

Before this fix, an ordinary /crawl body (`browser_config: {}`) never matched
DEFAULT_CONFIG_SIG: every request launched a second Chromium while the
permanent one sat idle, and config.yml's extra_args / text_mode never applied.
Observed live on 2026-10-09: 60/60 soak jobs routed to a cold->hot browser,
none to the permanent one.
"""

from __future__ import annotations

import pytest

import crawler_pool as cp
from browser_defaults import (
    apply_server_browser_defaults,
    requested_fields,
    server_extra_args,
)
from crawl4ai import BrowserConfig
from crawl4ai.async_configs import Provenance, UntrustedConfigError
from egress_broker import enforce_egress
from utils import load_config

CONFIG = load_config()


def _permanent() -> BrowserConfig:
    """The real permanent-browser config, not a re-implementation of it."""
    import server

    return server.get_default_browser_config()


def _request(raw) -> BrowserConfig:
    """Mirror of api.handle_crawl_request's browser-config path."""
    bc = BrowserConfig.load(raw, provenance=Provenance.UNTRUSTED)
    apply_server_browser_defaults(bc, raw, CONFIG)
    enforce_egress(bc)
    return bc


def _sig(bc):
    return cp._sig(cp._apply_pool_defaults(bc))


@pytest.mark.parametrize("raw", [{}, {"type": "BrowserConfig", "params": {}}])
def test_default_request_shares_the_permanent_signature(raw):
    assert _sig(_request(raw)) == _sig(_permanent())


def test_without_the_fix_signatures_diverge():
    """Guards the test itself: the bug is real, not an artifact of _sig."""
    bare = BrowserConfig.load({}, provenance=Provenance.UNTRUSTED)
    enforce_egress(bare)
    assert _sig(bare) != _sig(_permanent())


def test_operator_browser_policy_reaches_requests():
    bc = _request({})
    assert bc.extra_args == server_extra_args(CONFIG)
    for key, value in CONFIG["crawler"]["browser"].get("kwargs", {}).items():
        assert getattr(bc, key) == value, key


@pytest.mark.parametrize(
    "raw",
    [
        {"text_mode": False},
        {"type": "BrowserConfig", "params": {"text_mode": False}},
    ],
)
def test_explicit_request_fields_still_win(raw):
    assert _request(raw).text_mode is False


def test_request_still_cannot_set_extra_args():
    with pytest.raises(UntrustedConfigError):
        _request({"extra_args": ["--remote-debugging-port=9222"]})


def test_sandbox_opt_in_drops_no_sandbox(monkeypatch):
    monkeypatch.setenv("CRAWL4AI_CHROMIUM_SANDBOX", "true")
    assert "--no-sandbox" not in server_extra_args(CONFIG)
    monkeypatch.setenv("CRAWL4AI_CHROMIUM_SANDBOX", "false")
    assert "--no-sandbox" in server_extra_args(CONFIG)


def test_requested_fields_handles_both_shapes_and_junk():
    assert requested_fields({"a": 1, "type": "BrowserConfig"}) == {"a"}
    assert requested_fields({"type": "BrowserConfig", "params": {"b": 2}}) == {"b"}
    assert requested_fields(None) == set()
    assert requested_fields(["x"]) == set()
