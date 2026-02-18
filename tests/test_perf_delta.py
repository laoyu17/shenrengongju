from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "perf_delta.py"
SPEC = spec_from_file_location("perf_delta", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
perf_delta = module_from_spec(SPEC)
SPEC.loader.exec_module(perf_delta)


def _report(*, task_count: int, wall_ms: float, event_count: int) -> dict:
    return {
        "cases": [
            {
                "case_name": f"tasks_{task_count}",
                "task_count": task_count,
                "wall_time_ms": wall_ms,
                "event_count": event_count,
            }
        ]
    }


def test_build_delta_summary_regressed_and_highlighted() -> None:
    summary = perf_delta.build_delta_summary(
        current_report=_report(task_count=1000, wall_ms=120.0, event_count=2100),
        base_report=_report(task_count=1000, wall_ms=100.0, event_count=2000),
        task_count=1000,
        highlight_pct=5.0,
        current_run_id="200",
        base_run_id="100",
    )

    assert summary["status"] == "regressed"
    assert summary["base_run_id"] == "100"
    assert summary["current_run_id"] == "200"
    assert summary["highlight"] is True
    assert summary["wall_time_ms"]["delta"] == pytest.approx(20.0)
    assert summary["wall_time_ms"]["delta_pct"] == pytest.approx(20.0)


def test_build_delta_summary_no_base_when_previous_missing() -> None:
    summary = perf_delta.build_delta_summary(
        current_report=_report(task_count=1000, wall_ms=95.0, event_count=1800),
        base_report=None,
        task_count=1000,
        highlight_pct=5.0,
        current_run_id="200",
        base_run_id="",
    )

    assert summary["status"] == "no_base"
    assert summary["highlight"] is False
    assert summary["wall_time_ms"]["base"] is None
    assert summary["wall_time_ms"]["delta_pct"] is None


def test_build_delta_summary_requires_exact_task_count_match() -> None:
    current_report = {
        "cases": [
            {"case_name": "tasks_300", "task_count": 300, "wall_time_ms": 30.0, "event_count": 800},
            {"case_name": "tasks_1000", "task_count": 1000, "wall_time_ms": 100.0, "event_count": 2000},
        ]
    }
    base_report = {
        "cases": [
            {"case_name": "tasks_300", "task_count": 300, "wall_time_ms": 28.0, "event_count": 780},
        ]
    }

    summary = perf_delta.build_delta_summary(
        current_report=current_report,
        base_report=base_report,
        task_count=1000,
        highlight_pct=5.0,
        current_run_id="200",
        base_run_id="100",
    )

    assert summary["status"] == "no_base"
    assert summary["reason"] == "previous nightly artifact has no matching task_count case"
    assert summary["task_count"] == 1000
    assert summary["wall_time_ms"]["base"] is None


def test_build_delta_summary_raises_when_current_report_has_no_match() -> None:
    with pytest.raises(ValueError, match="no comparable case"):
        perf_delta.build_delta_summary(
            current_report={"cases": [{"case_name": "tasks_300", "task_count": 300, "wall_time_ms": 30.0}]},
            base_report=None,
            task_count=1000,
            highlight_pct=5.0,
            current_run_id="200",
            base_run_id="100",
        )
