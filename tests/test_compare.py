from __future__ import annotations

from rtos_sim.analysis import build_compare_report, compare_report_to_rows


def test_build_compare_report_contains_scalar_and_core_rows() -> None:
    left = {
        "jobs_completed": 3,
        "deadline_miss_count": 1,
        "core_utilization": {"c0": 0.5, "c1": 0.25},
    }
    right = {
        "jobs_completed": 5,
        "deadline_miss_count": 0,
        "core_utilization": {"c0": 0.75, "c1": 0.5},
    }

    report = build_compare_report(left, right, left_label="base", right_label="candidate")
    assert report["left_label"] == "base"
    assert report["right_label"] == "candidate"
    assert any(item["metric"] == "jobs_completed" for item in report["scalar_metrics"])
    assert any(item["core_id"] == "c0" for item in report["core_utilization"])


def test_compare_report_to_rows_flattens_output() -> None:
    report = build_compare_report(
        {"jobs_completed": 1, "core_utilization": {"c0": 0.2}},
        {"jobs_completed": 2, "core_utilization": {"c0": 0.4}},
    )
    rows = compare_report_to_rows(report)
    assert any(row["category"] == "scalar" for row in rows)
    assert any(row["category"] == "core_utilization" for row in rows)
