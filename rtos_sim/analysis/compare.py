"""Metric comparison helpers for two simulation runs."""

from __future__ import annotations

from typing import Any


DEFAULT_SCALAR_KEYS: tuple[str, ...] = (
    "jobs_released",
    "jobs_completed",
    "jobs_aborted",
    "deadline_miss_count",
    "deadline_miss_ratio",
    "avg_response_time",
    "avg_lateness",
    "preempt_count",
    "scheduler_preempt_count",
    "forced_preempt_count",
    "migrate_count",
    "event_count",
    "max_time",
)


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _build_scalar_rows(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in keys:
        left_value = _to_float(left.get(key))
        right_value = _to_float(right.get(key))
        delta = right_value - left_value
        delta_ratio = (delta / left_value * 100.0) if abs(left_value) > 1e-12 else 0.0
        rows.append(
            {
                "metric": key,
                "left": left_value,
                "right": right_value,
                "delta": delta,
                "delta_ratio_pct": delta_ratio,
            }
        )
    return rows


def _build_core_rows(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    left_core = left.get("core_utilization")
    right_core = right.get("core_utilization")
    left_map = left_core if isinstance(left_core, dict) else {}
    right_map = right_core if isinstance(right_core, dict) else {}
    core_ids = sorted(set(left_map) | set(right_map))
    rows: list[dict[str, Any]] = []
    for core_id in core_ids:
        left_value = _to_float(left_map.get(core_id))
        right_value = _to_float(right_map.get(core_id))
        delta = right_value - left_value
        delta_ratio = (delta / left_value * 100.0) if abs(left_value) > 1e-12 else 0.0
        rows.append(
            {
                "core_id": str(core_id),
                "left": left_value,
                "right": right_value,
                "delta": delta,
                "delta_ratio_pct": delta_ratio,
            }
        )
    return rows


def build_compare_report(
    left_metrics: dict[str, Any],
    right_metrics: dict[str, Any],
    *,
    left_label: str = "left",
    right_label: str = "right",
    scalar_keys: tuple[str, ...] = DEFAULT_SCALAR_KEYS,
) -> dict[str, Any]:
    """Build a deterministic metric diff report for two runs."""

    scalar_rows = _build_scalar_rows(left_metrics, right_metrics, keys=scalar_keys)
    core_rows = _build_core_rows(left_metrics, right_metrics)
    return {
        "left_label": left_label,
        "right_label": right_label,
        "scalar_metrics": scalar_rows,
        "core_utilization": core_rows,
    }


def compare_report_to_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten compare report to CSV-friendly rows."""

    rows: list[dict[str, Any]] = []
    for item in report.get("scalar_metrics", []):
        if not isinstance(item, dict):
            continue
        rows.append({"category": "scalar", **item})
    for item in report.get("core_utilization", []):
        if not isinstance(item, dict):
            continue
        rows.append({"category": "core_utilization", "metric": item.get("core_id", ""), **item})
    return rows
