#!/usr/bin/env python3
"""
Dependency-vulnerability gate (AC-13): an exception may only waive an advisory
that has no published fix, names the right package, and has not lapsed.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "deploy", "gateway"))

import audit_gate as g  # noqa: E402

EXCEPTIONS_FILE = os.path.join(REPO_ROOT, "deploy", "gateway", "audit-exceptions.json")
TODAY = "2026-10-09"


def _report(*deps):
    return {"dependencies": list(deps), "fixes": []}


def _dep(name, version, *vulns):
    return {"name": name, "version": version, "vulns": list(vulns)}


def _vuln(vid, fixes=(), aliases=()):
    return {"id": vid, "fix_versions": list(fixes), "aliases": list(aliases)}


def _exc(vid="PYSEC-1", package="nltk", review_by="2026-11-09"):
    return {
        "id": vid,
        "package": package,
        "reason": "no fix",
        "evidence": "unreachable",
        "review_by": review_by,
    }


def _run(tmp_path, report, exceptions, today=TODAY):
    rp = tmp_path / "audit.json"
    ep = tmp_path / "exc.json"
    rp.write_text(json.dumps(report))
    ep.write_text(json.dumps({"exceptions": exceptions}))
    return g.main([str(rp), "--exceptions", str(ep), "--today", today])


def test_clean_report_passes(tmp_path):
    assert _run(tmp_path, _report(_dep("requests", "2.32.0")), []) == 0


def test_unwaived_finding_fails(tmp_path):
    report = _report(_dep("pyjwt", "2.13.0", _vuln("PYSEC-9", ["2.14.0"])))
    assert _run(tmp_path, report, []) == 1


def test_unfixable_finding_with_exception_passes(tmp_path):
    report = _report(_dep("nltk", "3.10.3", _vuln("PYSEC-1")))
    assert _run(tmp_path, report, [_exc()]) == 0


def test_exception_matches_by_alias(tmp_path):
    report = _report(_dep("nltk", "3.10.3", _vuln("GHSA-x", aliases=["PYSEC-1"])))
    assert _run(tmp_path, report, [_exc()]) == 0


def test_exception_stops_applying_once_a_fix_ships(tmp_path):
    """The core guarantee: a waiver can never outlive the missing fix."""
    report = _report(_dep("nltk", "3.10.3", _vuln("PYSEC-1", ["3.10.4"])))
    assert _run(tmp_path, report, [_exc()]) == 1


def test_lapsed_exception_fails(tmp_path):
    report = _report(_dep("nltk", "3.10.3", _vuln("PYSEC-1")))
    assert _run(tmp_path, report, [_exc(review_by="2026-10-01")]) == 1


def test_exception_for_wrong_package_fails(tmp_path):
    report = _report(_dep("pypdf", "6.17.0", _vuln("PYSEC-1")))
    assert _run(tmp_path, report, [_exc(package="nltk")]) == 1


@pytest.mark.parametrize("field", g.REQUIRED_EXCEPTION_FIELDS)
def test_incomplete_exception_fails(tmp_path, field):
    exc = _exc()
    exc[field] = ""
    report = _report(_dep("nltk", "3.10.3", _vuln("PYSEC-1")))
    assert _run(tmp_path, report, [exc]) == 1


def test_non_audit_input_is_unusable(tmp_path):
    assert _run(tmp_path, {"not": "pip-audit"}, []) == 2


def test_shipped_exceptions_are_well_formed_and_unfixable_only():
    with open(EXCEPTIONS_FILE) as fh:
        exceptions = json.load(fh)["exceptions"]
    assert g.validate_exceptions(exceptions) == []
    # Each waiver names reachability evidence, not just a reason.
    for exc in exceptions:
        assert "grep" in exc["evidence"] or "reach" in exc["evidence"], exc["id"]
