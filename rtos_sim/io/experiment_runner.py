"""Batch experiment runner for parameter matrix simulations."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from itertools import product
import json
from pathlib import Path
from typing import Any

import yaml

from rtos_sim.core import SimEngine

from .loader import ConfigError, ConfigLoader


@dataclass(slots=True)
class BatchRunSummary:
    summary_csv: Path
    summary_json: Path
    total_runs: int
    succeeded_runs: int
    failed_runs: int


class ExperimentRunner:
    """Expand matrix factors, run simulations and persist summaries."""

    SUPPORTED_VERSION = "0.1"

    def __init__(self, loader: ConfigLoader | None = None) -> None:
        self._loader = loader or ConfigLoader()

    def run_batch(
        self,
        batch_config_path: str,
        *,
        output_dir: str | None = None,
        summary_csv: str | None = None,
        summary_json: str | None = None,
    ) -> BatchRunSummary:
        batch_path = Path(batch_config_path)
        batch_payload = self._read_payload(batch_path)
        version = str(batch_payload.get("version", self.SUPPORTED_VERSION))
        if version != self.SUPPORTED_VERSION:
            raise ConfigError(f"unsupported batch version '{version}'")

        base_config = batch_payload.get("base_config")
        if not isinstance(base_config, str) or not base_config:
            raise ConfigError("batch config requires non-empty 'base_config'")
        base_config_path = (batch_path.parent / base_config).resolve()
        base_payload = self._read_payload(base_config_path)

        factors = batch_payload.get("factors")
        if not isinstance(factors, dict) or not factors:
            raise ConfigError("batch config requires non-empty 'factors' object")

        normalized_factors: dict[str, list[Any]] = {}
        for path, values in factors.items():
            if not isinstance(path, str) or not path:
                raise ConfigError("factor path must be non-empty string")
            if not isinstance(values, list) or not values:
                raise ConfigError(f"factor '{path}' must provide non-empty list")
            normalized_factors[path] = list(values)

        run_output_raw = output_dir or batch_payload.get("output_dir")
        if isinstance(run_output_raw, str) and run_output_raw:
            run_output_dir = self._resolve_path(batch_path.parent, run_output_raw)
        else:
            run_output_dir = (batch_path.parent / "artifacts" / "batch").resolve()
        run_output_dir.mkdir(parents=True, exist_ok=True)

        factor_paths = sorted(normalized_factors)
        factor_values = [normalized_factors[path] for path in factor_paths]
        combinations = list(product(*factor_values))
        until_override = batch_payload.get("until")
        if until_override is not None and not isinstance(until_override, (int, float)):
            raise ConfigError("batch 'until' must be number when provided")

        rows: list[dict[str, Any]] = []
        for idx, combo in enumerate(combinations):
            run_id = f"run_{idx:03d}"
            run_dir = run_output_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)

            row: dict[str, Any] = {"run_id": run_id}
            combo_payload = json.loads(json.dumps(base_payload))
            for path, value in zip(factor_paths, combo, strict=True):
                self._apply_factor(combo_payload, path, value)
                row[path] = value

            try:
                spec = self._loader.load_data(combo_payload)
                engine = SimEngine()
                engine.build(spec)
                engine.run(until=float(until_override) if until_override is not None else None)
                events = [event.model_dump(mode="json") for event in engine.events]
                metrics = engine.metric_report()

                events_path = run_dir / "events.jsonl"
                metrics_path = run_dir / "metrics.json"
                self._write_jsonl(events_path, events)
                self._write_json(metrics_path, metrics)

                row["status"] = "ok"
                row["events_path"] = str(events_path)
                row["metrics_path"] = str(metrics_path)
                row.update(metrics)
            except Exception as exc:  # noqa: BLE001 - batch should continue with error summary
                row["status"] = "error"
                row["error"] = str(exc)

            rows.append(row)

        summary_csv_path = (
            self._resolve_path(batch_path.parent, summary_csv)
            if isinstance(summary_csv, str) and summary_csv
            else run_output_dir / "summary.csv"
        )
        summary_json_path = (
            self._resolve_path(batch_path.parent, summary_json)
            if isinstance(summary_json, str) and summary_json
            else run_output_dir / "summary.json"
        )
        self._write_summary_csv(summary_csv_path, rows)
        self._write_json(
            summary_json_path,
            {
                "version": self.SUPPORTED_VERSION,
                "base_config": str(base_config_path),
                "factors": normalized_factors,
                "total_runs": len(rows),
                "succeeded_runs": sum(1 for row in rows if row.get("status") == "ok"),
                "failed_runs": sum(1 for row in rows if row.get("status") != "ok"),
                "runs": rows,
            },
        )

        return BatchRunSummary(
            summary_csv=summary_csv_path,
            summary_json=summary_json_path,
            total_runs=len(rows),
            succeeded_runs=sum(1 for row in rows if row.get("status") == "ok"),
            failed_runs=sum(1 for row in rows if row.get("status") != "ok"),
        )

    def _apply_factor(self, payload: dict[str, Any], path: str, value: Any) -> None:
        parts = path.split(".")
        self._apply_parts(payload, parts, value)

    def _apply_parts(self, node: Any, parts: list[str], value: Any) -> None:
        if not parts:
            return
        head = parts[0]
        tail = parts[1:]
        is_last = len(parts) == 1

        if head in {"*", "[*]"}:
            if not isinstance(node, list):
                raise ConfigError(f"factor path wildcard expects list node, got {type(node).__name__}")
            for item in node:
                if is_last:
                    raise ConfigError("wildcard cannot be terminal in factor path")
                self._apply_parts(item, tail, value)
            return

        if isinstance(node, list):
            raise ConfigError("factor path cannot address list without wildcard")

        if not isinstance(node, dict):
            raise ConfigError(f"cannot apply factor path to node type {type(node).__name__}")

        if is_last:
            node[head] = value
            return

        if head not in node:
            node[head] = {}
        self._apply_parts(node[head], tail, value)

    def _read_payload(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        text = path.read_text(encoding="utf-8")
        try:
            if path.suffix.lower() in {".yaml", ".yml"}:
                payload = yaml.safe_load(text)
            else:
                payload = json.loads(text)
        except Exception as exc:  # noqa: BLE001 - normalize to ConfigError
            raise ConfigError(f"invalid config syntax: {exc}") from exc
        if not isinstance(payload, dict):
            raise ConfigError(f"config root must be object: {path}")
        return payload

    def _resolve_path(self, base_dir: Path, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return (base_dir / path).resolve()

    def _write_summary_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
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

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
