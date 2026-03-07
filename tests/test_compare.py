from __future__ import annotations

from rtos_sim.analysis import (
    build_compare_report,
    build_multi_compare_report,
    compare_report_to_rows,
    render_compare_report_markdown,
)


def test_build_compare_report_contains_scalar_core_and_n_way_summary() -> None:
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
    assert report["comparison_mode"] == "two_way"
    assert report["left_label"] == "base"
    assert report["right_label"] == "candidate"
    assert report["scenario_labels"] == ["base", "candidate"]
    assert [item["label"] for item in report["scenarios"]] == ["base", "candidate"]
    assert any(item["metric"] == "jobs_completed" for item in report["scalar_metrics"])
    assert any(item["core_id"] == "c0" for item in report["core_utilization"])

    jobs_summary = next(item for item in report["scalar_summary"] if item["metric"] == "jobs_completed")
    assert jobs_summary["baseline_label"] == "base"
    assert jobs_summary["focus_label"] == "candidate"
    assert jobs_summary["focus_delta"] == 2.0
    assert jobs_summary["best_label"] == "candidate"


def test_build_multi_compare_report_supports_n_way_aggregation() -> None:
    report = build_multi_compare_report(
        [
            ("baseline", {"jobs_completed": 3, "core_utilization": {"c0": 0.4}}),
            ("candidate_a", {"jobs_completed": 5, "core_utilization": {"c0": 0.6}}),
            ("candidate_b", {"jobs_completed": 7, "core_utilization": {"c0": 0.8}}),
        ]
    )

    assert report["comparison_mode"] == "n_way"
    assert report["scenario_labels"] == ["baseline", "candidate_a", "candidate_b"]

    jobs_summary = next(item for item in report["scalar_summary"] if item["metric"] == "jobs_completed")
    assert jobs_summary["min"] == 3.0
    assert jobs_summary["max"] == 7.0
    assert jobs_summary["span"] == 4.0
    assert jobs_summary["values"]["candidate_b"] == 7.0

    core_summary = next(item for item in report["core_utilization_summary"] if item["core_id"] == "c0")
    assert core_summary["baseline_value"] == 0.4
    assert core_summary["focus_value"] == 0.6
    assert core_summary["max"] == 0.8


def test_compare_report_to_rows_flattens_output() -> None:
    report = build_compare_report(
        {"jobs_completed": 1, "core_utilization": {"c0": 0.2}},
        {"jobs_completed": 2, "core_utilization": {"c0": 0.4}},
    )
    rows = compare_report_to_rows(report)
    categories = {row["category"] for row in rows}
    assert {"scalar", "core_utilization", "scalar_summary", "core_utilization_summary"} <= categories


def test_render_compare_report_markdown_contains_pairwise_and_n_way_sections() -> None:
    report = build_multi_compare_report(
        [
            ("baseline", {"jobs_completed": 2, "core_utilization": {"c0": 0.3}}),
            ("candidate", {"jobs_completed": 4, "core_utilization": {"c0": 0.5}}),
            ("stress", {"jobs_completed": 1, "core_utilization": {"c0": 0.7}}),
        ]
    )

    markdown = render_compare_report_markdown(report)
    assert "# Compare 报告" in markdown
    assert "## 双方案标量差分" in markdown
    assert "## N-way 标量聚合" in markdown
    assert "baseline=2" in markdown
    assert "stress=1" in markdown
