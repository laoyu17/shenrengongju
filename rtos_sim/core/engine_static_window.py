"""Static-window constrained scheduling helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import TYPE_CHECKING

from rtos_sim.model import Decision, DecisionAction, ModelSpec

if TYPE_CHECKING:
    from .engine import SimEngine


EPSILON = 1e-12


@dataclass(slots=True)
class StaticWindow:
    core_id: str
    start_time: float
    end_time: float
    segment_key: str | None = None
    task_id: str | None = None
    subtask_id: str | None = None
    segment_id: str | None = None


def _to_bool(raw: object, *, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _parse_planning_segment_key(segment_key: str) -> tuple[str, str, str]:
    parts = [item.strip() for item in segment_key.split(":")]
    if len(parts) != 3 or any(not item for item in parts):
        raise ValueError("segment_key must follow 'task_id:subtask_id:segment_id'")
    return parts[0], parts[1], parts[2]


def _planning_segment_key(*, task_id: str, subtask_id: str, segment_id: str) -> str:
    return f"{task_id}:{subtask_id}:{segment_id}"


def _segment_matches_window(window: StaticWindow, segment: object) -> bool:
    task_id = getattr(segment, "task_id", None)
    subtask_id = getattr(segment, "subtask_id", None)
    segment_id = getattr(segment, "segment_id", None)
    if not isinstance(task_id, str) or not isinstance(subtask_id, str) or not isinstance(segment_id, str):
        return False

    if window.segment_key is not None:
        return _planning_segment_key(
            task_id=task_id,
            subtask_id=subtask_id,
            segment_id=segment_id,
        ) == window.segment_key

    if window.task_id is None:
        return False
    if window.subtask_id is not None and window.segment_id is not None:
        return (
            task_id == window.task_id
            and subtask_id == window.subtask_id
            and segment_id == window.segment_id
        )
    return task_id == window.task_id


def configure_static_window_mode(engine: SimEngine, spec: ModelSpec) -> None:
    params = spec.scheduler.params if isinstance(spec.scheduler.params, dict) else {}
    enabled = _to_bool(params.get("static_window_mode"), default=False)
    engine._static_window_mode_enabled = enabled
    engine._static_windows_by_core = {}
    if not enabled:
        return

    raw_windows = params.get("static_windows", [])
    if raw_windows is None:
        raw_windows = []
    if not isinstance(raw_windows, list):
        raise ValueError("scheduler.params.static_windows must be an array")

    known_cores = set(engine._cores)
    known_tasks = {task.id for task in spec.tasks}
    known_segments = {
        (task.id, subtask.id, segment.id)
        for task in spec.tasks
        for subtask in task.subtasks
        for segment in subtask.segments
    }
    by_core: dict[str, list[StaticWindow]] = {}
    for index, item in enumerate(raw_windows):
        if not isinstance(item, dict):
            raise ValueError(f"scheduler.params.static_windows[{index}] must be object")
        core_id_raw = item.get("core_id")
        if not isinstance(core_id_raw, str) or not core_id_raw.strip():
            raise ValueError(f"scheduler.params.static_windows[{index}].core_id must be non-empty string")
        core_id = core_id_raw.strip()
        if core_id not in known_cores:
            raise ValueError(f"static window references unknown core_id '{core_id}'")

        segment_key: str | None = None
        task_id: str | None = None
        subtask_id: str | None = None
        segment_id: str | None = None

        segment_key_raw = item.get("segment_key")
        if segment_key_raw is not None:
            if not isinstance(segment_key_raw, str) or not segment_key_raw.strip():
                raise ValueError(
                    f"scheduler.params.static_windows[{index}].segment_key must be non-empty string"
                )
            segment_key = segment_key_raw.strip()
            task_id, subtask_id, segment_id = _parse_planning_segment_key(segment_key)

        task_id_raw = item.get("task_id")
        if task_id_raw is not None:
            if not isinstance(task_id_raw, str) or not task_id_raw.strip():
                raise ValueError(f"scheduler.params.static_windows[{index}].task_id must be non-empty string")
            task_id = task_id_raw.strip()
        subtask_id_raw = item.get("subtask_id")
        if subtask_id_raw is not None:
            if not isinstance(subtask_id_raw, str) or not subtask_id_raw.strip():
                raise ValueError(
                    f"scheduler.params.static_windows[{index}].subtask_id must be non-empty string"
                )
            subtask_id = subtask_id_raw.strip()
        segment_id_raw = item.get("segment_id")
        if segment_id_raw is not None:
            if not isinstance(segment_id_raw, str) or not segment_id_raw.strip():
                raise ValueError(
                    f"scheduler.params.static_windows[{index}].segment_id must be non-empty string"
                )
            segment_id = segment_id_raw.strip()

        if segment_key is None and task_id is None:
            raise ValueError(
                f"scheduler.params.static_windows[{index}] requires segment_key or task_id"
            )
        if task_id is not None and task_id not in known_tasks:
            raise ValueError(f"static window references unknown task_id '{task_id}'")
        if subtask_id is not None and segment_id is not None:
            if task_id is None:
                raise ValueError(
                    f"scheduler.params.static_windows[{index}] requires task_id with subtask_id/segment_id"
                )
            if (task_id, subtask_id, segment_id) not in known_segments:
                raise ValueError(
                    "static window references unknown segment "
                    f"'{task_id}:{subtask_id}:{segment_id}'"
                )
            if segment_key is None:
                segment_key = _planning_segment_key(
                    task_id=task_id,
                    subtask_id=subtask_id,
                    segment_id=segment_id,
                )
        if segment_key is not None and (task_id, subtask_id, segment_id) not in known_segments:
            raise ValueError(f"static window references unknown segment_key '{segment_key}'")

        start_raw = item.get("start", item.get("start_time"))
        end_raw = item.get("end", item.get("end_time"))
        if start_raw is None or end_raw is None:
            raise ValueError(
                f"scheduler.params.static_windows[{index}] requires start/start_time and end/end_time"
            )
        try:
            start_time = float(start_raw)
            end_time = float(end_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"scheduler.params.static_windows[{index}] start/end must be numbers"
            ) from exc
        if end_time <= start_time + EPSILON:
            raise ValueError(
                f"scheduler.params.static_windows[{index}] requires end > start"
            )
        by_core.setdefault(core_id, []).append(
            StaticWindow(
                core_id=core_id,
                start_time=start_time,
                end_time=end_time,
                segment_key=segment_key,
                task_id=task_id,
                subtask_id=subtask_id,
                segment_id=segment_id,
            )
        )

    for core_id, windows in by_core.items():
        windows.sort(
            key=lambda item: (
                item.start_time,
                item.end_time,
                item.segment_key or "",
                item.task_id or "",
            )
        )
        previous_end = -inf
        for window in windows:
            if window.start_time < previous_end - EPSILON:
                raise ValueError(
                    f"static windows overlap on core '{core_id}' near t={window.start_time}"
                )
            previous_end = max(previous_end, window.end_time)

    engine._static_windows_by_core = by_core


def active_static_window(engine: SimEngine, core_id: str, now: float) -> StaticWindow | None:
    if not engine._static_window_mode_enabled:
        return None
    windows = engine._static_windows_by_core.get(core_id, [])
    for window in windows:
        if window.start_time <= now + EPSILON and now < window.end_time - EPSILON:
            return window
    return None


def enforce_static_window_before_schedule(engine: SimEngine, now: float) -> bool:
    if not engine._static_window_mode_enabled:
        return False
    changed = False
    for core_id, core in engine._cores.items():
        window = active_static_window(engine, core_id, now)
        if window is None or core.running_segment_key is None:
            continue
        segment = engine._segments.get(core.running_segment_key)
        if segment is None or segment.finished or segment.job_id in engine._aborted_jobs:
            continue
        if _segment_matches_window(window, segment):
            continue
        if engine._apply_preempt(
            core_id,
            now,
            force=True,
            reason="static_window_boundary",
            clear_running_on=False,
        ):
            changed = True
    return changed


def _segment_from_decision(engine: SimEngine, decision: Decision) -> object | None:
    if decision.segment_id is not None and decision.segment_id in engine._segments:
        return engine._segments[decision.segment_id]
    if decision.job_id is None:
        return None
    ready_segments = [
        engine._segments[segment_key]
        for segment_key in sorted(engine._ready)
        if segment_key in engine._segments
        and engine._segments[segment_key].job_id == decision.job_id
        and not engine._segments[segment_key].finished
    ]
    if len(ready_segments) == 1:
        return ready_segments[0]
    return None


def _build_window_dispatch(engine: SimEngine, *, core_id: str, window: StaticWindow) -> Decision | None:
    candidates = []
    for segment_key in sorted(engine._ready):
        segment = engine._segments.get(segment_key)
        if segment is None or segment.finished:
            continue
        if segment.job_id in engine._aborted_jobs:
            continue
        if not _segment_matches_window(window, segment):
            continue
        if segment.mapping_hint is not None and segment.mapping_hint != core_id:
            continue
        candidates.append(segment)
    if not candidates:
        return None
    chosen = min(
        candidates,
        key=lambda item: (
            float(item.absolute_deadline) if item.absolute_deadline is not None else inf,
            item.release_time,
            item.key,
        ),
    )
    return Decision(
        action=DecisionAction.DISPATCH,
        job_id=chosen.job_id,
        segment_id=chosen.key,
        from_core=None,
        to_core=core_id,
        reason="static_window_enforced",
    )


def apply_static_window_constraints(
    engine: SimEngine,
    now: float,
    decisions: list[Decision],
) -> list[Decision]:
    if not engine._static_window_mode_enabled:
        return decisions

    filtered: list[Decision] = []
    for decision in decisions:
        if decision.action == DecisionAction.PREEMPT and decision.from_core:
            window = active_static_window(engine, decision.from_core, now)
            if window is not None:
                running_key = engine._cores[decision.from_core].running_segment_key
                running_segment = engine._segments.get(running_key) if running_key else None
                if running_segment is not None and _segment_matches_window(window, running_segment):
                    continue

        if decision.action == DecisionAction.MIGRATE:
            if decision.from_core:
                from_window = active_static_window(engine, decision.from_core, now)
                if from_window is not None:
                    running_key = engine._cores[decision.from_core].running_segment_key
                    running_segment = engine._segments.get(running_key) if running_key else None
                    if running_segment is not None and _segment_matches_window(from_window, running_segment):
                        continue
            if decision.to_core:
                to_window = active_static_window(engine, decision.to_core, now)
                if to_window is not None:
                    segment = _segment_from_decision(engine, decision)
                    if segment is None or not _segment_matches_window(to_window, segment):
                        continue

        if decision.action == DecisionAction.DISPATCH and decision.to_core and decision.job_id:
            window = active_static_window(engine, decision.to_core, now)
            if window is not None:
                segment = _segment_from_decision(engine, decision)
                if segment is None or not _segment_matches_window(window, segment):
                    continue

        filtered.append(decision)

    for core_id, core in engine._cores.items():
        window = active_static_window(engine, core_id, now)
        if window is None:
            continue
        if core.running_segment_key is not None:
            continue
        has_dispatch = any(
            decision.action == DecisionAction.DISPATCH and decision.to_core == core_id
            for decision in filtered
        )
        if has_dispatch:
            continue
        fallback = _build_window_dispatch(engine, core_id=core_id, window=window)
        if fallback is not None:
            filtered.append(fallback)
    return filtered
