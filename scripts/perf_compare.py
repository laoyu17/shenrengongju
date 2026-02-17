"""Compare two perf baseline reports and print deltas per case."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _case_key(case: dict) -> str:
    case_name = case.get("case_name")
    if isinstance(case_name, str) and case_name:
        return case_name
    return f"tasks_{case.get('task_count', 'unknown')}"


def _render_lines(base: dict, current: dict) -> list[str]:
    base_cases = {_case_key(case): case for case in base.get("cases", [])}
    current_cases = {_case_key(case): case for case in current.get("cases", [])}
    keys = sorted(set(base_cases) | set(current_cases))

    lines = ["# Perf Compare", "", "| case | base(ms) | current(ms) | delta(ms) | delta(%) |", "|---|---:|---:|---:|---:|"]
    for key in keys:
        base_ms = float(base_cases.get(key, {}).get("wall_time_ms", 0.0))
        current_ms = float(current_cases.get(key, {}).get("wall_time_ms", 0.0))
        delta = current_ms - base_ms
        ratio = (delta / base_ms * 100.0) if base_ms > 1e-12 else 0.0
        lines.append(f"| {key} | {base_ms:.2f} | {current_ms:.2f} | {delta:+.2f} | {ratio:+.2f}% |")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two perf baseline json reports")
    parser.add_argument("--base", required=True, help="baseline report json path")
    parser.add_argument("--current", required=True, help="current report json path")
    parser.add_argument("--output", default="", help="optional markdown output path")
    args = parser.parse_args(argv)

    base_report = _load_report(Path(args.base))
    current_report = _load_report(Path(args.current))
    lines = _render_lines(base_report, current_report)
    text = "\n".join(lines)
    print(text)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
        print(f"[INFO] wrote compare report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
