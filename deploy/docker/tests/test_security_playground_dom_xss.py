#!/usr/bin/env python3
"""
Regression test for the DOM-based XSS in the Playground result viewer
(the fifth v0.9.3 security blocker family).

Root cause: forceHighlightElement reset highlight.js state with

    const text = element.textContent;
    element.innerHTML = text;

That round trip re-parses the element's text as live HTML. The text is crawl
output, so script in a crawled page could run in the operator's Playground
session and read the API token held there.

The fix removed the round trip: crawl output reaches the DOM only through
textContent, and highlight.js re-renders from textContent emitting escaped
markup. These tests assert the sink stays closed -- they scan the shipped
Playground asset, not a copy of it.
"""

import os
import re
import sys
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

PLAYGROUND = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "static", "playground", "index.html")
)

# Assignment forms that hand a string to the HTML parser.
LIVE_HTML_SINKS = (
    re.compile(r"\.innerHTML\s*="),
    re.compile(r"\.outerHTML\s*="),
    re.compile(r"\.insertAdjacentHTML\s*\("),
    re.compile(r"document\s*\.\s*write(?:ln)?\s*\("),
)


def _strip_comment_lines(source: str) -> str:
    """Drop whole-line JS/HTML comments.

    The fix deliberately leaves the dangerous pattern quoted in a warning
    comment above the call site. Only comment-only lines are removed, so a
    real sink can never be hidden behind a trailing comment.
    """
    kept = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("//", "/*", "*", "<!--")):
            continue
        kept.append(line)
    return "\n".join(kept)


class TestPlaygroundDomXss(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PLAYGROUND, encoding="utf-8") as fh:
            cls.source = fh.read()
        cls.code = _strip_comment_lines(cls.source)

    def test_playground_asset_exists(self):
        """The scanned asset must be the one the server actually serves."""
        self.assertTrue(os.path.isfile(PLAYGROUND), f"missing {PLAYGROUND}")
        self.assertIn("forceHighlightElement", self.source)

    def test_no_live_html_sink_anywhere(self):
        """No code path may hand a string to the HTML parser."""
        for pattern in LIVE_HTML_SINKS:
            hits = [
                line.strip() for line in self.code.splitlines() if pattern.search(line)
            ]
            self.assertEqual(
                [], hits, f"live-HTML sink {pattern.pattern!r} reintroduced: {hits}"
            )

    def test_textcontent_is_not_round_tripped_through_innerhtml(self):
        """The exact regressed pattern must never come back."""
        self.assertIsNone(
            re.search(r"\.innerHTML\s*=\s*[\w.]*textContent", self.code),
            "element.innerHTML = <...>.textContent round trip reintroduced",
        )

    def test_force_highlight_resets_via_attribute_not_markup(self):
        """Highlight state is reset by attribute removal, not by reparsing."""
        match = re.search(
            r"function\s+forceHighlightElement\s*\([^)]*\)\s*\{(.*?)\n        \}",
            self.code,
            re.S,
        )
        self.assertIsNotNone(match, "forceHighlightElement not found")
        body = match.group(1)
        self.assertNotIn("innerHTML", body)
        self.assertIn("removeAttribute('data-highlighted')", body)

    def test_response_content_is_written_via_textcontent(self):
        """Crawl output reaches the viewer only through textContent."""
        writes = re.findall(r"#response-content code'\)\s*\.\s*(\w+)\s*=", self.code)
        self.assertTrue(writes, "no #response-content writes found")
        for prop in writes:
            self.assertIn(
                prop,
                ("textContent", "className"),
                f"#response-content written via unsafe property {prop!r}",
            )


if __name__ == "__main__":
    unittest.main()
