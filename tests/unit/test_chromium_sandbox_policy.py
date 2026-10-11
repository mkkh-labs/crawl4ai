"""
Chromium renderer-sandbox switch (F-04).

`--no-sandbox` was hard-coded in every launch path, and Playwright appends it
again unless `chromium_sandbox=True`, so CRAWL4AI_CHROMIUM_SANDBOX could never
take effect. The switch is operator-only (process env), never request-driven.
"""

from __future__ import annotations

import pytest

from crawl4ai import BrowserConfig
from crawl4ai.async_configs import Provenance, UntrustedConfigError
from crawl4ai.browser_manager import (
    BrowserManager,
    ManagedBrowser,
    _apply_sandbox_policy,
    chromium_sandbox_enabled,
)


@pytest.fixture
def sandbox_on(monkeypatch):
    monkeypatch.setenv("CRAWL4AI_CHROMIUM_SANDBOX", "true")


@pytest.fixture
def sandbox_off(monkeypatch):
    monkeypatch.delenv("CRAWL4AI_CHROMIUM_SANDBOX", raising=False)


def test_default_is_upstream_behavior(sandbox_off):
    assert not chromium_sandbox_enabled()
    args = BrowserManager(BrowserConfig())._build_browser_args()
    assert "--no-sandbox" in args["args"]
    assert "chromium_sandbox" not in args
    assert "--no-sandbox" in ManagedBrowser.build_browser_flags(BrowserConfig())


def test_switch_removes_every_no_sandbox(sandbox_on):
    cfg = BrowserConfig(extra_args=["--no-sandbox", "--disable-dev-shm-usage"])
    args = BrowserManager(cfg)._build_browser_args()
    assert "--no-sandbox" not in args["args"]
    assert "--disable-dev-shm-usage" in args["args"]
    assert args["chromium_sandbox"] is True


def test_switch_covers_managed_browser_flags(sandbox_on):
    assert "--no-sandbox" not in ManagedBrowser.build_browser_flags(BrowserConfig())


@pytest.mark.parametrize("browser_type", ["firefox", "webkit"])
def test_non_chromium_gets_no_chromium_kwarg(sandbox_on, browser_type):
    args = BrowserManager(
        BrowserConfig(browser_type=browser_type)
    )._build_browser_args()
    assert "chromium_sandbox" not in args


@pytest.mark.parametrize("value", ["false", "0", "", "yes", "TRUEISH"])
def test_only_exact_true_enables(monkeypatch, value):
    monkeypatch.setenv("CRAWL4AI_CHROMIUM_SANDBOX", value)
    assert not chromium_sandbox_enabled()
    assert _apply_sandbox_policy(["--no-sandbox"]) == ["--no-sandbox"]


def test_request_cannot_reintroduce_no_sandbox(sandbox_on):
    """An untrusted body cannot pass extra_args at all (400), so it cannot
    smuggle --no-sandbox back in."""
    with pytest.raises(UntrustedConfigError):
        BrowserConfig.load(
            {"extra_args": ["--no-sandbox"]}, provenance=Provenance.UNTRUSTED
        )
