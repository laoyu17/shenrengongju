"""Runtime types shared across the simulation engine and plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DecisionAction(str, Enum):
    DISPATCH = "dispatch"
    PREEMPT = "preempt"
    MIGRATE = "migrate"
    IDLE = "idle"


@dataclass(slots=True)
class ReadySegment:
    """Scheduler-facing runtime segment description."""

    job_id: str
    task_id: str
    subtask_id: str
    segment_id: str
    remaining_time: float
    absolute_deadline: Optional[float]
    task_period: Optional[float]
    mapping_hint: Optional[str]
    required_resources: list[str]
    preemptible: bool
    release_time: float
    priority_value: float = field(default=0.0)

    @property
    def key(self) -> str:
        return f"{self.job_id}:{self.subtask_id}:{self.segment_id}"


@dataclass(slots=True)
class CoreState:
    core_id: str
    core_speed: float
    running_segment_key: Optional[str]
    running_since: Optional[float]
    running_segment: Optional["ReadySegment"] = None


@dataclass(slots=True)
class ScheduleSnapshot:
    now: float
    ready_segments: list[ReadySegment]
    core_states: list[CoreState]


@dataclass(slots=True)
class Decision:
    action: DecisionAction
    job_id: Optional[str]
    segment_id: Optional[str]
    from_core: Optional[str]
    to_core: Optional[str]
    reason: str = ""


@dataclass(slots=True)
class RuntimeSegmentState:
    """Engine-internal mutable runtime state for one segment."""

    task_id: str
    job_id: str
    subtask_id: str
    segment_id: str
    wcet: float
    remaining_time: float
    required_resources: list[str]
    mapping_hint: Optional[str]
    preemptible: bool
    absolute_deadline: Optional[float]
    task_period: Optional[float]
    release_time: float
    predecessor_subtasks: list[str]
    successor_subtasks: list[str]
    segment_index: int
    base_priority: float = 0.0
    effective_priority: float = 0.0

    started_at: Optional[float] = None
    running_on: Optional[str] = None
    finished: bool = False
    blocked: bool = False
    waiting_resource: Optional[str] = None
    deterministic_ready_time: Optional[float] = None
    deterministic_window_id: Optional[int] = None
    deterministic_offset_index: Optional[int] = None

    @property
    def key(self) -> str:
        return f"{self.job_id}:{self.subtask_id}:{self.segment_id}"


@dataclass(slots=True)
class JobState:
    task_id: str
    job_id: str
    release_time: float
    absolute_deadline: Optional[float]
    subtask_completion: dict[str, bool]
    completed: bool = False
    missed_deadline: bool = False
