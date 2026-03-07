"""Metric comparison helpers for one or more simulation runs."""

from __future__ import annotations

import json
from typing import Any, Sequence


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


def _format_number(value: Any) -> str:
    number = _to_float(value)
    rounded = round(number)
    if abs(number - rounded) < 1e-12:
        return str(int(rounded))
    return f"{number:.6g}"


def _unique_labels(labels: Sequence[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique: list[str] = []
    for index, raw_label in enumerate(labels, start=1):
        base_label = raw_label.strip() or f"scenario_{index}"
        count = seen.get(base_label, 0)
        seen[base_label] = count + 1
        unique.append(base_label if count == 0 else f"{base_label}_{count + 1}")
    return unique


def _normalize_scenarios(
    scenarios: Sequence[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    if len(scenarios) < 2:
        raise ValueError("compare report requires at least two scenarios")

    labels = _unique_labels([str(label) for label, _metrics in scenarios])
    normalized: list[tuple[str, dict[str, Any]]] = []
    for label, (_raw_label, metrics) in zip(labels, scenarios, strict=False):
        normalized.append((label, metrics if isinstance(metrics, dict) else {}))
    return normalized


def _core_map(metrics: dict[str, Any]) -> dict[str, float]:
    core_utilization = metrics.get("core_utilization")
    if not isinstance(core_utilization, dict):
        return {}
    return {str(core_id): _to_float(value) for core_id, value in core_utilization.items()}


def _scenario_entry(
    label: str,
    metrics: dict[str, Any],
    *,
    scalar_keys: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "label": label,
        "scalar_metrics": {key: _to_float(metrics.get(key)) for key in scalar_keys},
        "core_utilization": _core_map(metrics),
    }


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
    left_map = _core_map(left)
    right_map = _core_map(right)
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


def _select_extreme(values: list[tuple[str, float]], *, choose_max: bool) -> tuple[str, float]:
    selected_label, selected_value = values[0]
    for label, value in values[1:]:
        if (choose_max and value > selected_value) or (not choose_max and value < selected_value):
            selected_label, selected_value = label, value
    return selected_label, selected_value


def _build_summary_row(metric_key: str, values: list[tuple[str, float]]) -> dict[str, Any]:
    baseline_label, baseline_value = values[0]
    focus_label, focus_value = values[1]
    min_label, min_value = _select_extreme(values, choose_max=False)
    max_label, max_value = _select_extreme(values, choose_max=True)
    focus_delta = focus_value - baseline_value
    focus_delta_ratio = (focus_delta / baseline_value * 100.0) if abs(baseline_value) > 1e-12 else 0.0
    return {
        "metric": metric_key,
        "values": {label: value for label, value in values},
        "scenario_count": len(values),
        "baseline_label": baseline_label,
        "baseline_value": baseline_value,
        "focus_label": focus_label,
        "focus_value": focus_value,
        "focus_delta": focus_delta,
        "focus_delta_ratio_pct": focus_delta_ratio,
        "min_label": min_label,
        "min": min_value,
        "max_label": max_label,
        "max": max_value,
        "span": max_value - min_value,
        "best_label": max_label,
        "best_value": max_value,
    }


def _build_scalar_summary_rows(
    scenario_entries: list[dict[str, Any]],
    *,
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in keys:
        values = [
            (str(entry.get("label", "")), _to_float(entry.get("scalar_metrics", {}).get(key)))
            for entry in scenario_entries
        ]
        rows.append(_build_summary_row(key, values))
    return rows


def _build_core_summary_rows(scenario_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    core_ids: set[str] = set()
    for entry in scenario_entries:
        core_ids.update(str(core_id) for core_id in entry.get("core_utilization", {}))

    rows: list[dict[str, Any]] = []
    for core_id in sorted(core_ids):
        values = [
            (str(entry.get("label", "")), _to_float(entry.get("core_utilization", {}).get(core_id)))
            for entry in scenario_entries
        ]
        row = _build_summary_row(core_id, values)
        row["core_id"] = core_id
        rows.append(row)
    return rows


def build_multi_compare_report(
    scenarios: Sequence[tuple[str, dict[str, Any]]],
    *,
    scalar_keys: tuple[str, ...] = DEFAULT_SCALAR_KEYS,
) -> dict[str, Any]:
    """Build a deterministic compare report that is ready for N-way aggregation."""

    normalized_scenarios = _normalize_scenarios(scenarios)
    scenario_entries = [
        _scenario_entry(label, metrics, scalar_keys=scalar_keys) for label, metrics in normalized_scenarios
    ]
    baseline_label, baseline_metrics = normalized_scenarios[0]
    focus_label, focus_metrics = normalized_scenarios[1]
    return {
        "comparison_mode": "two_way" if len(normalized_scenarios) == 2 else "n_way",
        "scenario_labels": [label for label, _metrics in normalized_scenarios],
        "scenarios": scenario_entries,
        "baseline_label": baseline_label,
        "focus_label": focus_label,
        "left_label": baseline_label,
        "right_label": focus_label,
        "scalar_metrics": _build_scalar_rows(baseline_metrics, focus_metrics, keys=scalar_keys),
        "core_utilization": _build_core_rows(baseline_metrics, focus_metrics),
        "scalar_summary": _build_scalar_summary_rows(scenario_entries, keys=scalar_keys),
        "core_utilization_summary": _build_core_summary_rows(scenario_entries),
    }


def build_compare_report(
    left_metrics: dict[str, Any],
    right_metrics: dict[str, Any],
    *,
    left_label: str = "left",
    right_label: str = "right",
    scalar_keys: tuple[str, ...] = DEFAULT_SCALAR_KEYS,
) -> dict[str, Any]:
    """Build a deterministic metric diff report for two runs."""

    return build_multi_compare_report(
        [(left_label, left_metrics), (right_label, right_metrics)],
        scalar_keys=scalar_keys,
    )


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
    for item in report.get("scalar_summary", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "category": "scalar_summary",
                "metric": item.get("metric", ""),
                "baseline_label": item.get("baseline_label", ""),
                "baseline_value": item.get("baseline_value", 0.0),
                "focus_label": item.get("focus_label", ""),
                "focus_value": item.get("focus_value", 0.0),
                "focus_delta": item.get("focus_delta", 0.0),
                "focus_delta_ratio_pct": item.get("focus_delta_ratio_pct", 0.0),
                "min": item.get("min", 0.0),
                "max": item.get("max", 0.0),
                "span": item.get("span", 0.0),
                "values_json": json.dumps(item.get("values", {}), ensure_ascii=False, sort_keys=True),
            }
        )
    for item in report.get("core_utilization_summary", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "category": "core_utilization_summary",
                "metric": item.get("core_id", item.get("metric", "")),
                "baseline_label": item.get("baseline_label", ""),
                "baseline_value": item.get("baseline_value", 0.0),
                "focus_label": item.get("focus_label", ""),
                "focus_value": item.get("focus_value", 0.0),
                "focus_delta": item.get("focus_delta", 0.0),
                "focus_delta_ratio_pct": item.get("focus_delta_ratio_pct", 0.0),
                "min": item.get("min", 0.0),
                "max": item.get("max", 0.0),
                "span": item.get("span", 0.0),
                "values_json": json.dumps(item.get("values", {}), ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def _render_pairwise_table(
    rows: list[dict[str, Any]],
    *,
    left_column: str,
    right_column: str,
    key_name: str,
) -> list[str]:
    if not rows:
        return ["- 无"]

    lines = [
        f"| {key_name} | {left_column} | {right_column} | delta | delta_ratio_pct |",
        "|---|---|---|---|---|",
    ]
    for item in rows:
        lines.append(
            "| "
            f"{item.get(key_name.lower(), item.get('metric', ''))} | "
            f"{_format_number(item.get('left'))} | "
            f"{_format_number(item.get('right'))} | "
            f"{_format_number(item.get('delta'))} | "
            f"{_format_number(item.get('delta_ratio_pct'))} |"
        )
    return lines


def _render_summary_table(
    rows: list[dict[str, Any]],
    *,
    key_name: str,
) -> list[str]:
    if not rows:
        return ["- 无"]

    lines = [
        f"| {key_name} | min | max | span | values |",
        "|---|---|---|---|---|",
    ]
    for item in rows:
        values = item.get("values", {})
        value_text = "; ".join(
            f"{label}={_format_number(value)}" for label, value in values.items()
        )
        lines.append(
            "| "
            f"{item.get(key_name.lower(), item.get('metric', ''))} | "
            f"{_format_number(item.get('min'))} | "
            f"{_format_number(item.get('max'))} | "
            f"{_format_number(item.get('span'))} | "
            f"{value_text or '-'} |"
        )
    return lines


def render_compare_report_markdown(report: dict[str, Any]) -> str:
    """Render a compare report as Markdown for UI/CLI exports."""

    scenario_labels = [str(label) for label in report.get("scenario_labels", []) if isinstance(label, str)]
    scenarios = [item for item in report.get("scenarios", []) if isinstance(item, dict)]
    scalar_rows = [item for item in report.get("scalar_metrics", []) if isinstance(item, dict)]
    core_rows = [item for item in report.get("core_utilization", []) if isinstance(item, dict)]
    scalar_summary = [item for item in report.get("scalar_summary", []) if isinstance(item, dict)]
    core_summary = [item for item in report.get("core_utilization_summary", []) if isinstance(item, dict)]

    lines: list[str] = []
    lines.append("# Compare 报告")
    lines.append("")
    lines.append(f"- 对比模式：**{report.get('comparison_mode', 'unknown')}**")
    lines.append(f"- 场景列表：{', '.join(scenario_labels) if scenario_labels else '-'}")
    lines.append(f"- 基线场景：{report.get('baseline_label', '-')}")
    lines.append(f"- 对焦场景：{report.get('focus_label', '-')}")

    lines.append("")
    lines.append("## 场景概览")
    if not scenarios:
        lines.append("- 无")
    else:
        lines.append("| 场景 | 标量指标数 | 核利用率核心数 |")
        lines.append("|---|---|---|")
        for item in scenarios:
            scalar_count = len(item.get("scalar_metrics", {})) if isinstance(item.get("scalar_metrics"), dict) else 0
            core_count = len(item.get("core_utilization", {})) if isinstance(item.get("core_utilization"), dict) else 0
            lines.append(f"| {item.get('label', '-')} | {scalar_count} | {core_count} |")

    lines.append("")
    lines.append("## 双方案标量差分")
    lines.extend(
        _render_pairwise_table(
            scalar_rows,
            left_column=str(report.get("left_label", "left")),
            right_column=str(report.get("right_label", "right")),
            key_name="metric",
        )
    )

    lines.append("")
    lines.append("## 双方案核利用率差分")
    lines.extend(
        _render_pairwise_table(
            core_rows,
            left_column=str(report.get("left_label", "left")),
            right_column=str(report.get("right_label", "right")),
            key_name="core_id",
        )
    )

    lines.append("")
    lines.append("## N-way 标量聚合")
    lines.extend(_render_summary_table(scalar_summary, key_name="metric"))

    lines.append("")
    lines.append("## N-way 核利用率聚合")
    lines.extend(_render_summary_table(core_summary, key_name="core_id"))
    return "\n".join(lines) + "\n"
