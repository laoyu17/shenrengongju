"""Table validation helpers for the UI editor."""

from __future__ import annotations


CellKey = tuple[int, int]


def _safe_optional_float(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def build_task_table_errors(rows: list[dict[str, str]], valid_task_types: set[str]) -> dict[CellKey, str]:
    """Return cell-level validation errors for the task table."""
    errors: dict[CellKey, str] = {}
    id_counts: dict[str, int] = {}
    for row in rows:
        task_id = (row.get("id") or "").strip()
        if task_id:
            id_counts[task_id] = id_counts.get(task_id, 0) + 1

    for row_idx, row in enumerate(rows):
        task_id = (row.get("id") or "").strip()
        task_name = (row.get("name") or "").strip()
        task_type = (row.get("task_type") or "").strip()
        arrival_text = (row.get("arrival") or "").strip()
        deadline_text = (row.get("deadline") or "").strip()

        if not task_id:
            errors[(row_idx, 0)] = "task.id can not be empty"
        elif id_counts.get(task_id, 0) > 1:
            errors[(row_idx, 0)] = "task.id must be unique"

        if not task_name:
            errors[(row_idx, 1)] = "task.name can not be empty"

        if task_type not in valid_task_types:
            errors[(row_idx, 2)] = "task_type must be dynamic_rt/time_deterministic/non_rt"

        arrival = _safe_optional_float(arrival_text)
        if arrival is None:
            errors[(row_idx, 3)] = "arrival must be number"
        elif arrival < 0:
            errors[(row_idx, 3)] = "arrival must be >= 0"

        if deadline_text:
            deadline = _safe_optional_float(deadline_text)
            if deadline is None:
                errors[(row_idx, 4)] = "deadline must be number"
            elif deadline <= 0:
                errors[(row_idx, 4)] = "deadline must be > 0"

    return errors


def build_resource_table_errors(rows: list[dict[str, str]], valid_protocols: set[str]) -> dict[CellKey, str]:
    """Return cell-level validation errors for the resource table."""
    errors: dict[CellKey, str] = {}
    id_counts: dict[str, int] = {}
    for row in rows:
        resource_id = (row.get("id") or "").strip()
        if resource_id:
            id_counts[resource_id] = id_counts.get(resource_id, 0) + 1

    for row_idx, row in enumerate(rows):
        resource_id = (row.get("id") or "").strip()
        resource_name = (row.get("name") or "").strip()
        bound_core_id = (row.get("bound_core_id") or "").strip()
        protocol = (row.get("protocol") or "").strip()

        if not resource_id:
            errors[(row_idx, 0)] = "resource.id can not be empty"
        elif id_counts.get(resource_id, 0) > 1:
            errors[(row_idx, 0)] = "resource.id must be unique"

        if not resource_name:
            errors[(row_idx, 1)] = "resource.name can not be empty"

        if not bound_core_id:
            errors[(row_idx, 2)] = "bound_core_id can not be empty"

        if protocol not in valid_protocols:
            errors[(row_idx, 3)] = "protocol must be mutex/pip/pcp"

    return errors
