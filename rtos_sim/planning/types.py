"""Planning data structures used by offline static schedulers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

from rtos_sim.model import ModelSpec


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


def eligible_core_ids_for_segment(segment: "PlanningSegment", core_ids: list[str]) -> list[str]:
    metadata = segment.metadata if isinstance(segment.metadata, dict) else {}
    metadata_eligible = metadata.get("eligible_core_ids")
    if isinstance(metadata_eligible, list):
        eligible = [str(core_id) for core_id in metadata_eligible if str(core_id) in set(core_ids)]
        if eligible:
            return eligible
    if segment.mapping_hint is not None:
        return [segment.mapping_hint] if segment.mapping_hint in set(core_ids) else []
    return [str(core_id) for core_id in core_ids]


def execution_cost_for_core(segment: "PlanningSegment", core_id: str | None = None) -> float:
    metadata = segment.metadata if isinstance(segment.metadata, dict) else {}
    execution_costs = metadata.get("execution_cost_by_core")
    if isinstance(execution_costs, dict):
        if core_id is not None:
            value = execution_costs.get(core_id)
            if isinstance(value, (int, float)):
                return float(value)
        numeric_values = [float(value) for value in execution_costs.values() if isinstance(value, (int, float))]
        if numeric_values:
            return min(numeric_values)
    default_value = metadata.get("default_execution_cost")
    if isinstance(default_value, (int, float)):
        return float(default_value)
    return float(segment.wcet)


def min_execution_cost(segment: "PlanningSegment", core_ids: list[str]) -> float:
    eligible_cores = eligible_core_ids_for_segment(segment, core_ids)
    if not eligible_cores:
        return float(segment.wcet)
    return min(execution_cost_for_core(segment, core_id) for core_id in eligible_cores)


def max_execution_cost(segment: "PlanningSegment", core_ids: list[str]) -> float:
    eligible_cores = eligible_core_ids_for_segment(segment, core_ids)
    if not eligible_cores:
        return float(segment.wcet)
    return max(execution_cost_for_core(segment, core_id) for core_id in eligible_cores)


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
    release_index: int | None = None
    mapping_hint: str | None = None
    predecessors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def base_segment_key(self) -> str:
        return f"{self.task_id}:{self.subtask_id}:{self.segment_id}"

    @property
    def key(self) -> str:
        if self.release_index is None:
            return self.base_segment_key
        return f"{self.task_id}@{self.release_index}:{self.subtask_id}:{self.segment_id}"


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
    release_index: int | None = None
    constraint_evidence: EvidencePayload = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_key": self.segment_key,
            "task_id": self.task_id,
            "subtask_id": self.subtask_id,
            "segment_id": self.segment_id,
            "release_index": self.release_index,
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
        from .normalized import build_normalized_execution_model

        normalized = build_normalized_execution_model(
            spec,
            task_scope=task_scope,
            include_non_rt=include_non_rt,
            horizon=horizon,
        )
        return normalized.to_planning_problem()

    def segment_map(self) -> dict[str, PlanningSegment]:
        return {segment.key: segment for segment in self.segments}


@dataclass(slots=True)
class PlanningResult:
    planner: str
    schedule_table: ScheduleTable
    feasible: bool
    assignments: dict[str, str] = field(default_factory=dict)
    unscheduled_segments: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

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
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "feasible": self.feasible,
            "items": [item.to_dict() for item in self.items],
            "evidence": [item.to_dict() for item in self.evidence],
            "metadata": dict(self.metadata),
        }
