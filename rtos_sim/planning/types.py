"""Planning data structures used by offline static schedulers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from rtos_sim.model import ModelSpec, TaskType


ScalarValue: TypeAlias = str | int | float | bool | None
EvidencePayload: TypeAlias = dict[str, ScalarValue]
PlanningTaskScope: TypeAlias = Literal["sync_only", "sync_and_dynamic_rt", "all"]
DEFAULT_TASK_SCOPE: PlanningTaskScope = "sync_only"


def normalize_task_scope(
    task_scope: str | None,
    *,
    include_non_rt: bool = False,
) -> PlanningTaskScope:
    """Resolve planning task scope with backward-compatible include_non_rt override."""

    if include_non_rt:
        return "all"
    if task_scope is None:
        return DEFAULT_TASK_SCOPE
    normalized = task_scope.strip().lower()
    if normalized in {"sync_only", "sync-and-dynamic-rt", "sync_and_dynamic_rt", "rt_only"}:
        if normalized in {"sync-and-dynamic-rt", "sync_and_dynamic_rt", "rt_only"}:
            return "sync_and_dynamic_rt"
        return "sync_only"
    if normalized in {"all", "all_tasks", "all-task"}:
        return "all"
    raise ValueError(
        "planning.task_scope must be sync_only|sync_and_dynamic_rt|all"
    )


@dataclass(slots=True)
class PlanningSegment:
    """Schedulable segment unit consumed by static planning heuristics."""

    task_id: str
    subtask_id: str
    segment_id: str
    wcet: float
    release_time: float
    period: float | None
    relative_deadline: float | None
    absolute_deadline: float | None
    mapping_hint: str | None = None
    predecessors: list[str] = field(default_factory=list)
    metadata: EvidencePayload = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.task_id}:{self.subtask_id}:{self.segment_id}"


@dataclass(slots=True)
class PlanningEvidence:
    rule: str
    message: str
    payload: EvidencePayload = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "message": self.message,
            "payload": dict(self.payload),
        }


@dataclass(slots=True)
class ConstraintViolation:
    constraint: str
    message: str
    segment_key: str | None = None
    payload: EvidencePayload = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "constraint": self.constraint,
            "message": self.message,
            "segment_key": self.segment_key,
            "payload": dict(self.payload),
        }


@dataclass(slots=True)
class ScheduleWindow:
    """One non-preemptive window on one core in an offline schedule table."""

    segment_key: str
    task_id: str
    subtask_id: str
    segment_id: str
    core_id: str
    start_time: float
    end_time: float
    release_time: float
    absolute_deadline: float | None
    constraint_evidence: EvidencePayload = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_key": self.segment_key,
            "task_id": self.task_id,
            "subtask_id": self.subtask_id,
            "segment_id": self.segment_id,
            "core_id": self.core_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "release_time": self.release_time,
            "absolute_deadline": self.absolute_deadline,
            "constraint_evidence": dict(self.constraint_evidence),
        }


@dataclass(slots=True)
class ScheduleTable:
    """Unified static scheduling table output for offline planning."""

    planner: str
    core_ids: list[str]
    windows: list[ScheduleWindow]
    feasible: bool
    violations: list[ConstraintViolation] = field(default_factory=list)
    evidence: list[PlanningEvidence] = field(default_factory=list)

    def by_core(self) -> dict[str, list[ScheduleWindow]]:
        grouped: dict[str, list[ScheduleWindow]] = {core_id: [] for core_id in self.core_ids}
        for window in self.windows:
            grouped.setdefault(window.core_id, []).append(window)
        for core_id in grouped:
            grouped[core_id].sort(key=lambda item: (item.start_time, item.end_time, item.segment_key))
        return grouped

    def to_dict(self) -> dict[str, object]:
        return {
            "planner": self.planner,
            "core_ids": list(self.core_ids),
            "feasible": self.feasible,
            "windows": [window.to_dict() for window in self.windows],
            "violations": [item.to_dict() for item in self.violations],
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(slots=True)
class PlanningProblem:
    """Input model for offline planners."""

    core_ids: list[str]
    segments: list[PlanningSegment]
    horizon: float | None = None
    metadata: EvidencePayload = field(default_factory=dict)

    @classmethod
    def from_model_spec(
        cls,
        spec: ModelSpec,
        *,
        task_scope: str | None = None,
        include_non_rt: bool = False,
        horizon: float | None = None,
    ) -> "PlanningProblem":
        resolved_scope = normalize_task_scope(task_scope, include_non_rt=include_non_rt)
        core_ids = [core.id for core in spec.platform.cores]
        segments: list[PlanningSegment] = []
        by_key: dict[str, PlanningSegment] = {}
        skipped_dynamic_rt = 0
        skipped_non_rt = 0

        for task in spec.tasks:
            if resolved_scope == "sync_only" and task.task_type != TaskType.TIME_DETERMINISTIC:
                if task.task_type == TaskType.DYNAMIC_RT:
                    skipped_dynamic_rt += 1
                elif task.task_type == TaskType.NON_RT:
                    skipped_non_rt += 1
                continue
            if resolved_scope == "sync_and_dynamic_rt" and task.task_type == TaskType.NON_RT:
                skipped_non_rt += 1
                continue
            release_time = float(task.arrival + (task.phase_offset or 0.0))
            relative_deadline = float(task.deadline) if task.deadline is not None else None
            absolute_deadline = (
                release_time + relative_deadline if relative_deadline is not None else None
            )
            task_mapping = task.task_mapping_hint
            subtask_segment_keys: dict[str, list[str]] = {}

            for subtask in task.subtasks:
                segment_keys: list[str] = []
                previous_segment_key: str | None = None
                subtask_mapping = subtask.subtask_mapping_hint or task_mapping
                ordered_segments = sorted(subtask.segments, key=lambda item: item.index)

                for segment in ordered_segments:
                    mapping_hint = segment.mapping_hint or subtask_mapping
                    planning_segment = PlanningSegment(
                        task_id=task.id,
                        subtask_id=subtask.id,
                        segment_id=segment.id,
                        wcet=float(segment.wcet),
                        release_time=release_time,
                        period=float(task.period) if task.period is not None else None,
                        relative_deadline=relative_deadline,
                        absolute_deadline=absolute_deadline,
                        mapping_hint=mapping_hint,
                        predecessors=[previous_segment_key] if previous_segment_key else [],
                        metadata={
                            "task_type": task.task_type.value,
                            "segment_index": segment.index,
                        },
                    )
                    previous_segment_key = planning_segment.key
                    segment_keys.append(planning_segment.key)
                    segments.append(planning_segment)
                    by_key[planning_segment.key] = planning_segment
                subtask_segment_keys[subtask.id] = segment_keys

            for subtask in task.subtasks:
                current_keys = subtask_segment_keys.get(subtask.id, [])
                if not current_keys:
                    continue
                first_segment = by_key[current_keys[0]]
                for predecessor_subtask in subtask.predecessors:
                    predecessor_keys = subtask_segment_keys.get(predecessor_subtask, [])
                    if not predecessor_keys:
                        continue
                    predecessor_key = predecessor_keys[-1]
                    if predecessor_key not in first_segment.predecessors:
                        first_segment.predecessors.append(predecessor_key)

        return cls(
            core_ids=core_ids,
            segments=segments,
            horizon=horizon,
            metadata={
                "source": "model_spec",
                "task_scope": resolved_scope,
                "total_tasks": len(spec.tasks),
                "included_segments": len(segments),
                "skipped_dynamic_rt_tasks": skipped_dynamic_rt,
                "skipped_non_rt_tasks": skipped_non_rt,
            },
        )

    def segment_map(self) -> dict[str, PlanningSegment]:
        return {segment.key: segment for segment in self.segments}


@dataclass(slots=True)
class PlanningResult:
    planner: str
    schedule_table: ScheduleTable
    feasible: bool
    assignments: dict[str, str] = field(default_factory=dict)
    unscheduled_segments: list[str] = field(default_factory=list)
    metadata: EvidencePayload = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "planner": self.planner,
            "feasible": self.feasible,
            "assignments": dict(self.assignments),
            "unscheduled_segments": list(self.unscheduled_segments),
            "metadata": dict(self.metadata),
            "schedule_table": self.schedule_table.to_dict(),
        }


@dataclass(slots=True)
class WCRTItem:
    task_id: str
    wcrt: float
    deadline: float | None
    schedulable: bool
    iterations: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "wcrt": self.wcrt,
            "deadline": self.deadline,
            "schedulable": self.schedulable,
            "iterations": list(self.iterations),
        }


@dataclass(slots=True)
class WCRTReport:
    items: list[WCRTItem]
    feasible: bool
    evidence: list[PlanningEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "feasible": self.feasible,
            "items": [item.to_dict() for item in self.items],
            "evidence": [item.to_dict() for item in self.evidence],
        }
