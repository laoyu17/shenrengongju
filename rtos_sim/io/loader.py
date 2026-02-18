"""Configuration loading, compatibility conversion and validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from pydantic import ValidationError

from rtos_sim.model import ModelSpec

from .schema import CONFIG_SCHEMA


@dataclass(slots=True)
class ValidationIssue:
    path: str
    message: str


class ConfigError(Exception):
    """Configuration loading/validation error."""


class ConfigLoader:
    """Load and validate model spec from JSON/YAML files."""

    SUPPORTED_VERSION = "0.2"

    def load(self, path: str) -> ModelSpec:
        raw = self._read(path)
        return self.load_data(raw)

    def load_data(self, payload: dict[str, Any]) -> ModelSpec:
        normalized = self._normalize_version(payload)
        self._validate_schema(normalized)
        try:
            return ModelSpec.model_validate(normalized)
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc

    def save(self, spec: ModelSpec, path: str) -> None:
        output_path = Path(path)
        payload = spec.model_dump(mode="json", exclude_none=True)
        if output_path.suffix.lower() in {".yaml", ".yml"}:
            output_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        else:
            output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def validate(self, spec_or_path: ModelSpec | str) -> list[ValidationIssue]:
        if isinstance(spec_or_path, ModelSpec):
            return []
        issues: list[ValidationIssue] = []
        try:
            self.load(spec_or_path)
        except ConfigError as exc:
            issues.append(ValidationIssue(path=spec_or_path, message=str(exc)))
        return issues

    @staticmethod
    def _read(path: str) -> dict[str, Any]:
        input_path = Path(path)
        if not input_path.exists():
            raise ConfigError(f"config file not found: {path}")

        text = input_path.read_text(encoding="utf-8")
        try:
            if input_path.suffix.lower() in {".yaml", ".yml"}:
                data = yaml.safe_load(text)
            else:
                data = json.loads(text)
        except (yaml.YAMLError, json.JSONDecodeError) as exc:
            raise ConfigError(f"invalid config syntax: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigError("config root must be object")
        return data

    def _normalize_version(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_payload = dict(payload)
        # UI-only layout metadata must not participate in schema/model validation.
        normalized_payload.pop("ui_layout", None)
        version = str(normalized_payload.get("version", "0.1"))

        if version == self.SUPPORTED_VERSION:
            return normalized_payload
        if version == "0.1":
            migrated = dict(normalized_payload)
            migrated["version"] = self.SUPPORTED_VERSION
            resources = migrated.setdefault("resources", [])
            if not isinstance(resources, list):
                raise ConfigError("invalid config structure: resources must be list")

            scheduler = migrated.setdefault("scheduler", {})
            if not isinstance(scheduler, dict):
                raise ConfigError("invalid config structure: scheduler must be object")
            params = scheduler.setdefault("params", {})
            if not isinstance(params, dict):
                raise ConfigError("invalid config structure: scheduler.params must be object")

            tasks = migrated.get("tasks", [])
            if not isinstance(tasks, list):
                raise ConfigError("invalid config structure: tasks must be list")
            for task_idx, task in enumerate(tasks):
                if not isinstance(task, dict):
                    raise ConfigError(
                        f"invalid config structure: tasks[{task_idx}] must be object"
                    )
                task.setdefault("arrival", 0)
                task.setdefault("abort_on_miss", False)

                subtasks = task.get("subtasks", [])
                if not isinstance(subtasks, list):
                    raise ConfigError(
                        f"invalid config structure: tasks[{task_idx}].subtasks must be list"
                    )
                for subtask_idx, subtask in enumerate(subtasks):
                    if not isinstance(subtask, dict):
                        raise ConfigError(
                            f"invalid config structure: tasks[{task_idx}].subtasks[{subtask_idx}] "
                            "must be object"
                        )
                    subtask.setdefault("predecessors", [])
                    subtask.setdefault("successors", [])

                    segments = subtask.get("segments", [])
                    if not isinstance(segments, list):
                        raise ConfigError(
                            "invalid config structure: "
                            f"tasks[{task_idx}].subtasks[{subtask_idx}].segments must be list"
                        )
                    for segment_idx, segment in enumerate(segments):
                        if not isinstance(segment, dict):
                            raise ConfigError(
                                "invalid config structure: "
                                f"tasks[{task_idx}].subtasks[{subtask_idx}].segments[{segment_idx}] "
                                "must be object"
                            )
                        segment.setdefault("required_resources", [])
                        segment.setdefault("preemptible", True)
            return migrated

        raise ConfigError(f"unsupported config version '{version}'")

    @staticmethod
    def _validate_schema(payload: dict[str, Any]) -> None:
        validator = jsonschema.Draft202012Validator(CONFIG_SCHEMA)
        errors = sorted(validator.iter_errors(payload), key=lambda err: err.path)
        if not errors:
            return
        formatted = []
        for error in errors[:8]:
            path = ".".join(str(x) for x in error.path)
            formatted.append(f"{path or '<root>'}: {error.message}")
        raise ConfigError("schema validation failed: " + " | ".join(formatted))
