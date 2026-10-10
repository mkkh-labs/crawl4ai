#!/usr/bin/env python3
"""
Tests for the soak harness's decision logic (SPEC.md M8).

The soak itself needs a live container, but its verdict is a pure function over
sampled series, so the thing that decides pass/fail is testable offline. A gate
whose own logic is unverified is not a gate.
"""

from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "deploy", "gateway"))

import soak  # noqa: E402


def series(counts, *, phase, rss=None, healthy=True):
    rss = rss if rss is not None else [100] * len(counts)
    return [
        soak.Sample(
            t=float(i), phase=phase, browser_processes=c, rss_bytes=r, health_ok=healthy
        )
        for i, (c, r) in enumerate(zip(counts, rss))
    ]


class TestRecovery:
    def test_returning_to_baseline_passes(self):
        v = soak.analyse(
            series([2, 2, 2, 2], phase="baseline"),
            series([9, 11, 10, 12], phase="traffic"),
            series([8, 4, 3, 2, 2, 2], phase="cooldown"),
        )
        assert v.passed, v.notes

    def test_processes_that_never_come_down_fail(self):
        """The leak this gate exists to catch."""
        v = soak.analyse(
            series([2, 2, 2, 2], phase="baseline"),
            series([10, 14, 18, 22], phase="traffic"),
            series([24, 25, 26, 27, 28, 29], phase="cooldown"),
        )
        assert not v.passed
        assert any("stable band" in n for n in v.notes)

    def test_band_is_derived_from_this_runs_baseline(self):
        """No universal number: a bigger pool gets a proportionally bigger band."""
        small = soak.analyse(
            series([2] * 4, phase="baseline"),
            series([6] * 4, phase="traffic"),
            series([5] * 6, phase="cooldown"),
        )
        large = soak.analyse(
            series([20] * 4, phase="baseline"),
            series([60] * 4, phase="traffic"),
            series([5] * 6, phase="cooldown"),
        )
        assert small.checks["allowed_post_traffic_band"] == 4
        assert large.checks["allowed_post_traffic_band"] == 40
        assert large.passed


class TestMemory:
    def test_monotonic_rss_growth_after_traffic_fails(self):
        v = soak.analyse(
            series([2] * 4, phase="baseline"),
            series([8] * 4, phase="traffic"),
            series([2] * 6, phase="cooldown", rss=[10, 20, 30, 40, 50, 60]),
        )
        assert not v.passed
        assert any("monotonic" in n for n in v.notes)

    def test_rss_that_settles_passes(self):
        v = soak.analyse(
            series([2] * 4, phase="baseline"),
            series([8] * 4, phase="traffic"),
            series([2] * 6, phase="cooldown", rss=[60, 50, 45, 44, 44, 43]),
        )
        assert v.passed, v.notes


class TestHealth:
    def test_any_unhealthy_sample_fails(self):
        v = soak.analyse(
            series([2] * 4, phase="baseline"),
            series([8] * 4, phase="traffic", healthy=False),
            series([2] * 6, phase="cooldown"),
        )
        assert not v.passed
        assert any("/health" in n for n in v.notes)


class TestInsufficientData:
    @pytest.mark.parametrize("missing", ["baseline", "during", "after"])
    def test_empty_phase_cannot_pass(self, missing):
        phases = {
            "baseline": series([2] * 4, phase="baseline"),
            "during": series([8] * 4, phase="traffic"),
            "after": series([2] * 6, phase="cooldown"),
        }
        phases[missing] = []
        v = soak.analyse(phases["baseline"], phases["during"], phases["after"])
        assert not v.passed, "an unmeasured soak must never report success"


class TestByteParsing:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("512B", 512),
            ("1KiB", 1024),
            ("2MiB", 2 * 1024**2),
            ("1.5GiB", int(1.5 * 1024**3)),
            ("100MB", 100 * 1000**2),
        ],
    )
    def test_docker_stats_units(self, text, expected):
        assert soak._parse_bytes(text) == expected


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ── concurrent workload driver ───────────────────────────────────────────────


def test_workload_respects_concurrency_bound_and_order():
    import threading
    import time as _time

    lock = threading.Lock()
    state = {"in_flight": 0, "peak": 0}

    def job(url):
        with lock:
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
        _time.sleep(0.02)
        with lock:
            state["in_flight"] -= 1
        return url

    urls = ["a", "b", "c"]
    results, samples = soak.run_workload(job, urls, 12, 3, lambda: "s", 0.005)
    assert results == [urls[i % 3] for i in range(12)]
    assert state["peak"] == 3
    assert samples and samples[-1] == "s"


def test_workload_concurrency_floor_is_one():
    results, _ = soak.run_workload(lambda u: u, ["x"], 2, 0, lambda: None, 0.01)
    assert results == ["x", "x"]


def test_concurrent_jobs_never_share_a_body_path():
    paths = {soak.body_path_for_job() for _ in range(500)}
    assert len(paths) == 500
    assert all(p.startswith("/tmp/soak_body_") for p in paths)
