#!/usr/bin/env python3
"""
Dependency-vulnerability release gate (AC-13).

Reads a `pip-audit --format json` report and fails unless every finding is
either fixed or covered by a narrow, documented exception. An exception is
only admissible while the advisory has NO published fix: the moment a fix
version appears, the exception stops applying and the gate fails, so a
waiver can never outlive the reason it was granted. Exceptions also carry a
review date, after which they lapse even if no fix exists.

This replaces a bare `pip-audit --strict`, which can never pass while any
unfixable advisory exists, and so trains people to ignore a red gate.

Usage:
    pip-audit --format json --output audit.json || true
    python deploy/gateway/audit_gate.py audit.json \
        --exceptions deploy/gateway/audit-exceptions.json

Exit status: 0 pass, 1 gate failure, 2 unusable input.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

REQUIRED_EXCEPTION_FIELDS = ("id", "package", "reason", "evidence", "review_by")


def load_findings(report: dict) -> list[dict]:
    """Flatten pip-audit's JSON into one record per (package, advisory)."""
    findings = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            findings.append(
                {
                    "package": dep["name"].lower(),
                    "version": dep.get("version", ""),
                    "id": vuln["id"],
                    "aliases": list(vuln.get("aliases", [])),
                    "fix_versions": list(vuln.get("fix_versions", [])),
                }
            )
    return findings


def validate_exceptions(exceptions: list[dict]) -> list[str]:
    errors = []
    for i, exc in enumerate(exceptions):
        missing = [f for f in REQUIRED_EXCEPTION_FIELDS if not exc.get(f)]
        if missing:
            errors.append(f"exception #{i} is missing {missing}")
            continue
        try:
            dt.date.fromisoformat(exc["review_by"])
        except ValueError:
            errors.append(f"exception {exc['id']}: review_by is not an ISO date")
    return errors


def evaluate(
    findings: list[dict], exceptions: list[dict], today: dt.date
) -> tuple[list[str], list[str]]:
    """Return (failures, waived) for the gate."""
    by_id = {}
    for exc in exceptions:
        by_id[exc["id"]] = exc
    failures, waived = [], []
    for f in findings:
        names = [f["id"], *f["aliases"]]
        exc = next((by_id[n] for n in names if n in by_id), None)
        label = f"{f['package']} {f['version']} {f['id']}"
        if exc is None:
            fix = ", ".join(f["fix_versions"]) or "no fix published"
            failures.append(f"{label}: unwaived ({fix})")
        elif exc["package"].lower() != f["package"]:
            failures.append(f"{label}: exception is for package {exc['package']}")
        elif f["fix_versions"]:
            failures.append(
                f"{label}: a fix now exists ({', '.join(f['fix_versions'])}); "
                "upgrade and delete the exception"
            )
        elif dt.date.fromisoformat(exc["review_by"]) < today:
            failures.append(f"{label}: exception lapsed on {exc['review_by']}")
        else:
            waived.append(f"{label}: waived until {exc['review_by']}")
    return failures, waived


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", help="pip-audit --format json output")
    ap.add_argument("--exceptions", required=True)
    ap.add_argument("--today", help="override the date (tests)")
    args = ap.parse_args(argv)

    try:
        with open(args.report) as fh:
            report = json.load(fh)
        with open(args.exceptions) as fh:
            exceptions = json.load(fh).get("exceptions", [])
    except (OSError, ValueError) as exc:
        print(f"[audit-gate] cannot read input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(report, dict) or "dependencies" not in report:
        print("[audit-gate] report is not pip-audit JSON", file=sys.stderr)
        return 2

    errors = validate_exceptions(exceptions)
    if errors:
        for e in errors:
            print(f"[audit-gate] FAIL: {e}")
        return 1

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    findings = load_findings(report)
    failures, waived = evaluate(findings, exceptions, today)
    print(f"[audit-gate] {len(findings)} finding(s), {len(waived)} waived")
    for w in waived:
        print(f"[audit-gate] waived: {w}")
    for f in failures:
        print(f"[audit-gate] FAIL: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
