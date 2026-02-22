"""Model relation extraction helpers for design/docx traceability."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rtos_sim.model import ModelSpec


UNBOUND_CORE_ID = "unbound"
RELATION_SECTIONS: tuple[str, ...] = (
    "task_to_cores",
    "subtask_to_cores",
    "segment_to_core",
    "task_to_resources",
    "subtask_to_resources",
    "segment_to_resources",
    "resource_to_tasks",
    "resource_to_subtasks",
    "resource_to_segments",
    "core_to_tasks",
    "core_to_subtasks",
    "core_to_segments",
)
RELATION_CHECK_VERSION = "0.1"


def _segment_key(task_id: str, subtask_id: str, segment_id: str) -> str:
    return f"{task_id}:{subtask_id}:{segment_id}"


def _sorted_tuple_rows(
    rows: set[tuple[str, ...]],
    fields: tuple[str, ...],
) -> list[dict[str, str]]:
    return [
        {field: value for field, value in zip(fields, row, strict=True)}
        for row in sorted(rows)
    ]


def build_model_relations_checks(report: dict[str, Any]) -> dict[str, Any]:
    """Evaluate deterministic semantic checks from relation report."""

    summary = report.get("summary", {})
    segment_to_core = report.get("segment_to_core", [])
    segment_to_resources = report.get("segment_to_resources", [])
    core_to_segments = report.get("core_to_segments", [])

    checks: dict[str, dict[str, Any]] = {}

    unbound_count = int(summary.get("unbound_segment_count", 0) or 0)
    checks["segment_core_binding_coverage"] = {
        "passed": unbound_count == 0,
        "severity": "warn",
        "message": "all segments should bind to concrete cores for deterministic replay",
        "unbound_segment_count": unbound_count,
    }

    core_by_segment_key = {
        str(item.get("segment_key")): str(item.get("core_id"))
        for item in segment_to_core
        if isinstance(item, dict) and item.get("segment_key") is not None
    }
    resources_on_unbound_segments: list[dict[str, str]] = []
    for item in segment_to_resources:
        if not isinstance(item, dict):
            continue
        segment_key = item.get("segment_key")
        if not isinstance(segment_key, str):
            continue
        if core_by_segment_key.get(segment_key) == UNBOUND_CORE_ID:
            resources_on_unbound_segments.append(
                {
                    "segment_key": segment_key,
                    "resource_id": str(item.get("resource_id")),
                }
            )
    checks["resource_segment_bound_core_alignment"] = {
        "passed": not resources_on_unbound_segments,
        "severity": "error",
        "message": "segments requiring resources should not remain unbound",
        "samples": resources_on_unbound_segments[:20],
    }

    core_reverse = {
        (
            str(item.get("core_id")),
            str(item.get("task_id")),
            str(item.get("subtask_id")),
            str(item.get("segment_id")),
            str(item.get("segment_key")),
        )
        for item in core_to_segments
        if isinstance(item, dict)
    }
    missing_reverse: list[dict[str, str]] = []
    for item in segment_to_core:
        if not isinstance(item, dict):
            continue
        relation_key = (
            str(item.get("core_id")),
            str(item.get("task_id")),
            str(item.get("subtask_id")),
            str(item.get("segment_id")),
            str(item.get("segment_key")),
        )
        if relation_key not in core_reverse:
            missing_reverse.append(
                {
                    "core_id": relation_key[0],
                    "task_id": relation_key[1],
                    "subtask_id": relation_key[2],
                    "segment_id": relation_key[3],
                    "segment_key": relation_key[4],
                }
            )
    checks["core_reverse_relation_consistency"] = {
        "passed": not missing_reverse,
        "severity": "error",
        "message": "segment_to_core rows must have reverse core_to_segments rows",
        "samples": missing_reverse[:20],
    }

    has_error_failure = any(
        (not result.get("passed", False)) and result.get("severity") == "error"
        for result in checks.values()
    )
    has_warn_failure = any(
        (not result.get("passed", False)) and result.get("severity") == "warn"
        for result in checks.values()
    )
    status = "pass"
    if has_error_failure:
        status = "fail"
    elif has_warn_failure:
        status = "warn"

    return {
        "check_version": RELATION_CHECK_VERSION,
        "status": status,
        "checks": checks,
    }


def build_model_relations_report(spec: ModelSpec) -> dict[str, Any]:
    """Build deterministic task/core/resource relation tables from a validated model."""

    task_to_cores: set[tuple[str, str]] = set()
    subtask_to_cores: set[tuple[str, str, str]] = set()
    segment_to_core: set[tuple[str, str, str, str, str]] = set()

    task_to_resources: set[tuple[str, str]] = set()
    subtask_to_resources: set[tuple[str, str, str]] = set()
    segment_to_resources: set[tuple[str, str, str, str, str]] = set()

    resource_to_tasks: set[tuple[str, str]] = set()
    resource_to_subtasks: set[tuple[str, str, str]] = set()
    resource_to_segments: set[tuple[str, str, str, str, str]] = set()

    core_to_tasks: set[tuple[str, str]] = set()
    core_to_subtasks: set[tuple[str, str, str]] = set()
    core_to_segments: set[tuple[str, str, str, str, str]] = set()

    for task in spec.tasks:
        for subtask in task.subtasks:
            for segment in sorted(subtask.segments, key=lambda item: (item.index, item.id)):
                segment_key = _segment_key(task.id, subtask.id, segment.id)
                core_id = segment.mapping_hint or UNBOUND_CORE_ID

                task_to_cores.add((task.id, core_id))
                subtask_to_cores.add((task.id, subtask.id, core_id))
                segment_to_core.add((task.id, subtask.id, segment.id, segment_key, core_id))

                core_to_tasks.add((core_id, task.id))
                core_to_subtasks.add((core_id, task.id, subtask.id))
                core_to_segments.add((core_id, task.id, subtask.id, segment.id, segment_key))

                for resource_id in sorted(set(segment.required_resources)):
                    task_to_resources.add((task.id, resource_id))
                    subtask_to_resources.add((task.id, subtask.id, resource_id))
                    segment_to_resources.add((task.id, subtask.id, segment.id, segment_key, resource_id))

                    resource_to_tasks.add((resource_id, task.id))
                    resource_to_subtasks.add((resource_id, task.id, subtask.id))
                    resource_to_segments.add((resource_id, task.id, subtask.id, segment.id, segment_key))

    sections = {
        "task_to_cores": _sorted_tuple_rows(task_to_cores, ("task_id", "core_id")),
        "subtask_to_cores": _sorted_tuple_rows(subtask_to_cores, ("task_id", "subtask_id", "core_id")),
        "segment_to_core": _sorted_tuple_rows(
            segment_to_core,
            ("task_id", "subtask_id", "segment_id", "segment_key", "core_id"),
        ),
        "task_to_resources": _sorted_tuple_rows(task_to_resources, ("task_id", "resource_id")),
        "subtask_to_resources": _sorted_tuple_rows(
            subtask_to_resources,
            ("task_id", "subtask_id", "resource_id"),
        ),
        "segment_to_resources": _sorted_tuple_rows(
            segment_to_resources,
            ("task_id", "subtask_id", "segment_id", "segment_key", "resource_id"),
        ),
        "resource_to_tasks": _sorted_tuple_rows(resource_to_tasks, ("resource_id", "task_id")),
        "resource_to_subtasks": _sorted_tuple_rows(
            resource_to_subtasks,
            ("resource_id", "task_id", "subtask_id"),
        ),
        "resource_to_segments": _sorted_tuple_rows(
            resource_to_segments,
            ("resource_id", "task_id", "subtask_id", "segment_id", "segment_key"),
        ),
        "core_to_tasks": _sorted_tuple_rows(core_to_tasks, ("core_id", "task_id")),
        "core_to_subtasks": _sorted_tuple_rows(core_to_subtasks, ("core_id", "task_id", "subtask_id")),
        "core_to_segments": _sorted_tuple_rows(
            core_to_segments,
            ("core_id", "task_id", "subtask_id", "segment_id", "segment_key"),
        ),
    }

    subtask_count = sum(len(task.subtasks) for task in spec.tasks)
    segment_count = sum(len(subtask.segments) for task in spec.tasks for subtask in task.subtasks)
    summary = {
        "task_count": len(spec.tasks),
        "subtask_count": subtask_count,
        "segment_count": segment_count,
        "core_count": len(spec.platform.cores),
        "resource_count": len(spec.resources),
        "unbound_segment_count": sum(
            1 for item in sections["segment_to_core"] if item["core_id"] == UNBOUND_CORE_ID
        ),
        "relation_row_count": sum(len(sections[name]) for name in RELATION_SECTIONS),
    }

    report = {
        "relation_version": "0.1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "summary": summary,
        **sections,
    }
    report.update(build_model_relations_checks(report))
    return report


def model_relations_report_to_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten relation report into CSV-friendly rows."""

    rows: list[dict[str, Any]] = []
    for section in RELATION_SECTIONS:
        for item in report.get(section, []):
            if not isinstance(item, dict):
                continue
            rows.append({"category": section, **item})
    return rows
