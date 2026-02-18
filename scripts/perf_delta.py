"""Build a compact nightly performance delta summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_report(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"report root must be object: {path}")
    return payload


def _select_case(report: dict[str, Any], task_count: int) -> dict[str, Any] | None:
    cases = report.get("cases")
    if not isinstance(cases, list):
        return None

    for case in cases:
        if not isinstance(case, dict):
            continue
        try:
            case_task_count = int(case.get("task_count"))
        except (TypeError, ValueError):
            continue
        if case_task_count == task_count:
            return case
    return None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _delta_block(*, base: float | None, current: float) -> dict[str, Any]:
    if base is None:
        return {
            "base": None,
            "current": current,
            "delta": None,
            "delta_pct": None,
        }
    delta = current - base
    delta_pct = (delta / base * 100.0) if abs(base) > 1e-12 else None
    return {
        "base": base,
        "current": current,
        "delta": delta,
        "delta_pct": delta_pct,
    }


def build_delta_summary(
    *,
    current_report: dict[str, Any],
    base_report: dict[str, Any] | None,
    task_count: int,
    highlight_pct: float,
    current_run_id: str,
    base_run_id: str,
) -> dict[str, Any]:
    current_case = _select_case(current_report, task_count)
    if current_case is None:
        raise ValueError("current report has no comparable case")

    case_name = str(current_case.get("case_name") or f"tasks_{task_count}")
    current_task_count = int(current_case.get("task_count", task_count))
    current_wall = _to_float(current_case.get("wall_time_ms"))
    current_event_count = _to_float(current_case.get("event_count"))

    if base_report is None:
        return {
            "status": "no_base",
            "reason": "missing previous nightly artifact",
            "case_name": case_name,
            "task_count": current_task_count,
            "current_run_id": current_run_id,
            "base_run_id": base_run_id or None,
            "highlight_pct_threshold": highlight_pct,
            "highlight": False,
            "wall_time_ms": _delta_block(base=None, current=current_wall),
            "event_count": _delta_block(base=None, current=current_event_count),
        }

    base_case = _select_case(base_report, current_task_count)
    if base_case is None:
        return {
            "status": "no_base",
            "reason": "previous nightly artifact has no matching task_count case",
            "case_name": case_name,
            "task_count": current_task_count,
            "current_run_id": current_run_id,
            "base_run_id": base_run_id or None,
            "highlight_pct_threshold": highlight_pct,
            "highlight": False,
            "wall_time_ms": _delta_block(base=None, current=current_wall),
            "event_count": _delta_block(base=None, current=current_event_count),
        }

    base_wall = _to_float(base_case.get("wall_time_ms"))
    base_event_count = _to_float(base_case.get("event_count"))
    wall_delta = _delta_block(base=base_wall, current=current_wall)
    event_delta = _delta_block(base=base_event_count, current=current_event_count)

    wall_delta_value = float(wall_delta["delta"])
    if wall_delta_value > 1e-9:
        status = "regressed"
    elif wall_delta_value < -1e-9:
        status = "improved"
    else:
        status = "neutral"

    delta_pct = wall_delta["delta_pct"]
    highlight = isinstance(delta_pct, (int, float)) and abs(delta_pct) >= highlight_pct

    return {
        "status": status,
        "reason": "ok",
        "case_name": case_name,
        "task_count": current_task_count,
        "current_run_id": current_run_id,
        "base_run_id": base_run_id or None,
        "highlight_pct_threshold": highlight_pct,
        "highlight": bool(highlight),
        "wall_time_ms": wall_delta,
        "event_count": event_delta,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build nightly perf delta summary")
    parser.add_argument("--current", required=True, help="current perf report json path")
    parser.add_argument("--base", default="", help="optional previous perf report json path")
    parser.add_argument("--task-count", type=int, default=1000, help="task case to compare")
    parser.add_argument(
        "--highlight-pct",
        type=float,
        default=5.0,
        help="highlight threshold for absolute wall_time delta pct",
    )
    parser.add_argument("--current-run-id", default="", help="current CI run id")
    parser.add_argument("--base-run-id", default="", help="previous CI run id")
    parser.add_argument(
        "--out",
        default="artifacts/perf/perf-delta-summary.json",
        help="output summary json path",
    )
    args = parser.parse_args(argv)

    current_path = Path(args.current)
    current_report = _load_report(current_path)
    if current_report is None:
        raise FileNotFoundError(f"current report not found: {current_path}")

    base_path = Path(args.base) if args.base else None
    base_report = _load_report(base_path) if base_path is not None else None

    summary = build_delta_summary(
        current_report=current_report,
        base_report=base_report,
        task_count=args.task_count,
        highlight_pct=args.highlight_pct,
        current_run_id=str(args.current_run_id),
        base_run_id=str(args.base_run_id),
    )

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        "[INFO] nightly delta status="
        f"{summary['status']} case={summary['case_name']} out={output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
