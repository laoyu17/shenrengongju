"""Shared CLI helpers for plan validation and file I/O."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from rtos_sim import api as sim_api
from rtos_sim.io import ConfigError
from rtos_sim.model import ModelSpec


def _write_json(path: str, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_rows_csv(path: str, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigError(f"metrics file must be object: {path}")
    return payload


def _read_planning_result(path: str) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload.get("schedule_table"), dict):
        raise ConfigError(f"planning result missing schedule_table: {path}")
    return payload


def _validate_plan_fingerprint_match(
    *,
    command: str,
    spec: ModelSpec,
    plan_payload: dict[str, Any],
    strict: bool,
) -> bool:
    expectations = sim_api.plan_fingerprint_expectations(spec, plan_payload)
    expected_spec = str(expectations["expected_spec_fingerprint"])
    actual_spec = expectations["actual_spec_fingerprint"]
    if not isinstance(actual_spec, str) or not actual_spec.strip():
        level = "[ERROR]" if strict else "[WARN]"
        print(f"{level} {command}: plan-json missing spec_fingerprint, 期望指纹#{expected_spec}")
        return not strict
    if actual_spec != expected_spec:
        level = "[ERROR]" if strict else "[WARN]"
        print(
            f"{level} {command}: plan/config mismatch, "
            f"期望指纹#{expected_spec}, 实际指纹#{actual_spec}"
        )
        return not strict

    expected_semantic = str(expectations["expected_semantic_fingerprint"])
    actual_semantic = expectations["actual_semantic_fingerprint"]
    if not isinstance(actual_semantic, str) or not actual_semantic.strip():
        level = "[ERROR]" if strict else "[WARN]"
        print(
            f"{level} {command}: plan-json missing semantic_fingerprint, "
            f"期望语义指纹#{expected_semantic}"
        )
        return not strict
    if actual_semantic != expected_semantic:
        level = "[ERROR]" if strict else "[WARN]"
        print(
            f"{level} {command}: plan semantic mismatch, "
            f"期望语义指纹#{expected_semantic}, 实际语义指纹#{actual_semantic}"
        )
        return not strict
    return True


write_json = _write_json
write_rows_csv = _write_rows_csv
read_json = _read_json
read_planning_result = _read_planning_result
validate_plan_fingerprint_match = _validate_plan_fingerprint_match
