"""Generate markdown/csv research review report from audit artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from rtos_sim.analysis.research_report import (
    build_research_report_payload,
    render_research_report_markdown,
    research_report_to_rows,
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json root must be object: {path}")
    return payload


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate research review report")
    parser.add_argument("--audit", required=True, help="audit report json path")
    parser.add_argument("--relations", default="", help="optional model_relations json path")
    parser.add_argument("--quality", default="", help="optional quality snapshot json path")
    parser.add_argument(
        "--out-markdown",
        default="artifacts/research/research-report.md",
        help="markdown report output path",
    )
    parser.add_argument(
        "--out-csv",
        default="artifacts/research/research-summary.csv",
        help="csv summary output path",
    )
    parser.add_argument(
        "--out-json",
        default="artifacts/research/research-report.json",
        help="json summary output path",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return non-zero when report status is not pass",
    )
    args = parser.parse_args(argv)

    audit = _load_json(Path(args.audit))
    relations = _load_json(Path(args.relations)) if args.relations else None
    quality = _load_json(Path(args.quality)) if args.quality else None

    report = build_research_report_payload(
        audit_report=audit,
        model_relations_report=relations,
        quality_snapshot=quality,
    )

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    out_md = Path(args.out_markdown)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_research_report_markdown(report), encoding="utf-8")

    _write_rows_csv(Path(args.out_csv), research_report_to_rows(report))

    print(
        "[INFO] research report generated "
        f"status={report['status']} markdown={out_md} json={out_json}"
    )

    if args.strict and report["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
