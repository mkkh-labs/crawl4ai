"""Streamlit AppTest smoke tests for the console UI (needs streamlit)."""

from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "app.py")
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "gateway"))

from test_console import TOKEN, _Gateway, gateway  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _fresh_caches():
    import streamlit as st

    st.cache_data.clear()
    yield


@pytest.fixture()
def env(monkeypatch, tmp_path, gateway):  # noqa: F811
    monkeypatch.setenv("CRAWL4AI_BASE_URL", gateway)
    monkeypatch.setenv("CRAWL4AI_API_TOKEN_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("CRAWL4AI_API_TOKEN", TOKEN)
    monkeypatch.setenv("CONSOLE_HISTORY_PATH", str(tmp_path / "h.jsonl"))
    return gateway


def test_status_page_shows_healthy_safe_gateway(env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("0.9.4 healthy" in s.value for s in at.success)
    labels = {m.label: m.value for m in at.metric}
    assert labels["Version"] == "0.9.4"
    assert labels["Token"] == "set"


def test_status_page_warns_on_unsafe_version(env):
    _Gateway.version = "0.9.3"
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("below the minimum safe version" in w.value for w in at.warning)


def test_missing_token_stops_with_error(monkeypatch, tmp_path):
    monkeypatch.delenv("CRAWL4AI_API_TOKEN", raising=False)
    monkeypatch.setenv("CRAWL4AI_API_TOKEN_FILE", str(tmp_path / "none"))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("No gateway token" in e.value for e in at.error)
    assert not at.metric


def test_token_is_never_rendered(env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    rendered = " ".join(
        str(getattr(el, "value", "")) for el in at.main.children.values()
    )
    assert TOKEN not in rendered
