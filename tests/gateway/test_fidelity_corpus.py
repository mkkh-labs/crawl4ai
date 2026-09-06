#!/usr/bin/env python3
"""
Golden-corpus fidelity gate (SPEC.md M7).

Guards the failure mode where an extraction or filter change silently destroys
technical content: a dropped fenced block turns a code sample into prose, and
nothing downstream notices because the crawl still "succeeded".

Deterministic and offline. The corpus is local HTML and the assertions run the
real markdown pipeline (DefaultMarkdownGenerator + PruningContentFilter)
directly, so no browser, network, or public website is involved -- a release
gate that depends on a live site is not a gate.

Expectations here were measured against this pipeline, not assumed.
"""

from __future__ import annotations

import hashlib
import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "deploy", "n8n"))

import contract as c  # noqa: E402

from crawl4ai.__version__ import __version__ as CRAWLER_VERSION  # noqa: E402
from crawl4ai.content_filter_strategy import PruningContentFilter  # noqa: E402
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "fidelity")
BASE_URL = "https://example.com/docs/page"

#: Fixtures whose loss is a release blocker rather than a quality regression.
CRITICAL = {"code_heavy"}


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, f"{name}.html"), encoding="utf-8") as fh:
        return fh.read()


def _extract(name: str, *, content_filter=None):
    html = _load(name)
    result = DefaultMarkdownGenerator().generate_markdown(
        input_html=html, base_url=BASE_URL, content_filter=content_filter
    )
    return html, result


@pytest.fixture(scope="module")
def corpus():
    """Every fixture extracted twice: production default, and pruned."""
    out = {}
    for name in (
        "code_heavy",
        "dynamic_ready",
        "canonical_duplicate",
        "noisy_navigation",
        "pdf_escaped_text",
    ):
        html, unfiltered = _extract(name)
        _, pruned = _extract(name, content_filter=PruningContentFilter())
        out[name] = {
            "html": html,
            "source_checksum": "sha256:" + hashlib.sha256(html.encode()).hexdigest(),
            "raw_markdown": unfiltered.raw_markdown,
            "fit_unfiltered": getattr(unfiltered, "fit_markdown", "") or "",
            "fit_pruned": getattr(pruned, "fit_markdown", "") or "",
        }
    return out


# ───────────────────────── evidence attached to output ──────────────────────


def test_corpus_records_source_checksum_and_crawler_version(corpus):
    """M7: fidelity evidence is only meaningful with the inputs identified."""
    assert CRAWLER_VERSION == "0.9.3", CRAWLER_VERSION
    for name, data in corpus.items():
        assert data["source_checksum"].startswith("sha256:"), name
        # Distinct fixtures must not collide, or a swap would go unnoticed.
    checksums = {d["source_checksum"] for d in corpus.values()}
    assert len(checksums) == len(corpus)


# ───────────────────────────── critical: code content ───────────────────────


class TestCodeBlockPreservation:
    """The blocker case: technical content must survive extraction intact."""

    def test_both_fenced_blocks_survive(self, corpus):
        md = corpus["code_heavy"]["raw_markdown"]
        assert md.count("```") == 4, "expected two opened+closed fenced blocks"

    def test_code_body_is_preserved_verbatim(self, corpus):
        md = corpus["code_heavy"]["raw_markdown"]
        for line in (
            "# create the network first",
            "docker network create automation_internal",
            "docker compose up -d crawl4ai",
            "def check(config):",
            'raise ValueError("unbounded deadline")',
            '"depth": config["limits"]["max_depth"],',
        ):
            assert line in md, f"lost code line: {line!r}"

    def test_indentation_is_not_collapsed(self, corpus):
        """Whitespace is semantic in Python; collapsing it corrupts the sample."""
        md = corpus["code_heavy"]["raw_markdown"]
        assert '\n    if config["limits"]["wall_clock_s"] == 0:' in md
        assert '\n        raise ValueError("unbounded deadline")' in md
        assert '\n        "ok": True,' in md

    def test_blank_line_inside_code_block_survives(self, corpus):
        md = corpus["code_heavy"]["raw_markdown"]
        assert "docker network create automation_internal\n\ndocker compose" in md

    def test_inline_code_survives(self, corpus):
        assert "`--no-sandbox`" in corpus["code_heavy"]["raw_markdown"]

    def test_pruning_filter_does_not_strip_code(self, corpus):
        """Measured: PruningContentFilter keeps both blocks on this fixture."""
        fit = corpus["code_heavy"]["fit_pruned"]
        assert fit, "pruned output unexpectedly empty"
        assert fit.count("```") == 4
        assert '"depth": config["limits"]["max_depth"],' in fit


# ──────────────────────────── structure preservation ────────────────────────


class TestStructurePreservation:
    def test_table_rows_and_headers_survive(self, corpus):
        md = corpus["dynamic_ready"]["raw_markdown"]
        assert "| Signal | Healthy |" in md
        assert "| browser processes | returns to band |" in md
        assert "| queue age | bounded |" in md

    def test_dynamic_content_is_extracted(self, corpus):
        assert (
            "resolved this content before extraction"
            in corpus["dynamic_ready"]["raw_markdown"]
        )

    def test_canonical_target_is_preserved_for_dedup(self, corpus):
        """Duplicate URLs must stay resolvable to their canonical target."""
        assert 'rel="canonical"' in corpus["canonical_duplicate"]["html"]
        assert (
            "https://example.com/docs/install"
            in corpus["canonical_duplicate"]["raw_markdown"]
        )

    def test_relative_links_are_absolutised(self, corpus):
        assert "https://example.com/docs" in corpus["code_heavy"]["raw_markdown"]

    def test_pdf_text_is_preserved_faithfully(self, corpus):
        """The extracted PDF text keeps its characters.

        This asserts fidelity only. Escaping when this text is *rendered* is a
        separate control, covered by tests/unit/test_pdf_html_escaping.py and
        test_security_playground_dom_xss.py. Extracted content stays untrusted.
        """
        md = corpus["pdf_escaped_text"]["raw_markdown"]
        assert "alert('xss')" in md
        assert "Escaped ampersand" in md


# ──────────────────────────── noise removal, safely ─────────────────────────


class TestNoiseRemoval:
    def test_pruning_removes_navigation_boilerplate(self, corpus):
        fit = corpus["noisy_navigation"]["fit_pruned"]
        assert fit, "pruned output unexpectedly empty"
        for noise in ("Pricing", "Careers", "Newsletter", "Cookie preferences"):
            assert noise not in fit, f"boilerplate survived pruning: {noise}"

    def test_substantive_content_survives_pruning(self, corpus):
        fit = corpus["noisy_navigation"]["fit_pruned"]
        assert "wall-clock deadline is now finite" in fit
        assert "three hundred seconds" in fit


# ─────────────────────── raw-markdown fallback behavior ─────────────────────


class TestRawMarkdownFallback:
    def test_production_default_yields_empty_fit_so_raw_is_selected(self, corpus):
        """Measured: with no content filter configured, fit_markdown is empty.

        This is the production Docker default, so a consumer reading
        fit_markdown unconditionally would index nothing at all.
        """
        data = corpus["code_heavy"]
        assert data["fit_unfiltered"] == ""
        chosen = c.select_markdown(data["raw_markdown"], data["fit_unfiltered"])
        assert chosen.source == "raw_markdown"
        assert chosen.reason == "fit_markdown is empty"
        assert chosen.text.count("```") == 4

    def test_fit_is_used_when_it_keeps_the_code(self, corpus):
        data = corpus["code_heavy"]
        chosen = c.select_markdown(data["raw_markdown"], data["fit_pruned"])
        assert chosen.source == "fit_markdown"

    def test_fallback_triggers_when_a_filter_eats_a_code_block(self, corpus):
        """A filter that drops fenced code must not silently win."""
        raw = corpus["code_heavy"]["raw_markdown"]
        corrupted = raw.replace("```", "", 2)  # lose one block's fences
        chosen = c.select_markdown(raw, corrupted)
        assert chosen.source == "raw_markdown"
        assert chosen.reason == "fit_markdown dropped fenced code blocks"
        assert chosen.text == raw

    def test_fallback_triggers_on_lost_inline_code(self, corpus):
        raw = corpus["code_heavy"]["raw_markdown"]
        corrupted = raw.replace("`--no-sandbox`", "--no-sandbox")
        chosen = c.select_markdown(raw, corrupted)
        assert chosen.source == "raw_markdown"
        assert chosen.reason == "fit_markdown dropped inline code spans"

    @pytest.mark.parametrize("name", sorted(CRITICAL))
    def test_critical_fixture_never_selects_empty_content(self, corpus, name):
        data = corpus[name]
        for fit in (data["fit_unfiltered"], data["fit_pruned"]):
            assert c.select_markdown(data["raw_markdown"], fit).text.strip()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
