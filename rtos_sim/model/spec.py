"""Configuration domain models and semantic validation."""

from __future__ import annotations

from collections import defaultdict, deque
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskType(str, Enum):
    """Task timing category."""

    TIME_DETERMINISTIC = "time_deterministic"
    DYNAMIC_RT = "dynamic_rt"
    NON_RT = "non_rt"


class ProcessorTypeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    core_count: int = Field(ge=1)
    speed_factor: float = Field(gt=0)


class CoreSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type_id: str
    speed_factor: float = Field(gt=0)


class ResourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    bound_core_id: str
    protocol: str = Field(default="mutex")


class SegmentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    index: int = Field(ge=1)
    wcet: float = Field(gt=0)
    acet: Optional[float] = Field(default=None, gt=0)
    required_resources: list[str] = Field(default_factory=list)
    mapping_hint: Optional[str] = None
    preemptible: bool = True


class SubtaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    predecessors: list[str] = Field(default_factory=list)
    successors: list[str] = Field(default_factory=list)
    segments: list[SegmentSpec] = Field(min_length=1)


class TaskGraphSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    task_type: TaskType
    period: Optional[float] = Field(default=None, gt=0)
    deadline: Optional[float] = Field(default=None, gt=0)
    arrival: float = Field(default=0, ge=0)
    min_inter_arrival: Optional[float] = Field(default=None, gt=0)
    abort_on_miss: bool = False
    subtasks: list[SubtaskSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_timing_fields(self) -> "TaskGraphSpec":
        if self.task_type == TaskType.TIME_DETERMINISTIC and self.period is None:
            raise ValueError("time_deterministic task must define period")
        if self.task_type != TaskType.NON_RT and self.deadline is None:
            raise ValueError("real-time task must define deadline")
        if self.period is not None and self.min_inter_arrival is None:
            self.min_inter_arrival = self.period
        if self.period is not None and self.deadline is not None and self.deadline <= 0:
            raise ValueError("deadline must be > 0")
        return self


class SchedulerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    params: dict = Field(default_factory=dict)


class SimSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration: float = Field(gt=0)
    seed: int = 42


class PlatformSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processor_types: list[ProcessorTypeSpec] = Field(min_length=1)
    cores: list[CoreSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_platform(self) -> "PlatformSpec":
        processor_ids = [p.id for p in self.processor_types]
        core_ids = [c.id for c in self.cores]
        if len(processor_ids) != len(set(processor_ids)):
            raise ValueError("duplicate processor_types.id")
        if len(core_ids) != len(set(core_ids)):
            raise ValueError("duplicate cores.id")
        processor_set = set(processor_ids)
        for core in self.cores:
            if core.type_id not in processor_set:
                raise ValueError(f"core {core.id} references unknown processor type {core.type_id}")
        return self


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    platform: PlatformSpec
    resources: list[ResourceSpec] = Field(default_factory=list)
    tasks: list[TaskGraphSpec] = Field(min_length=1)
    scheduler: SchedulerSpec
    sim: SimSpec

    @model_validator(mode="after")
    def validate_semantics(self) -> "ModelSpec":
        core_ids = {core.id for core in self.platform.cores}
        resource_ids = [res.id for res in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("duplicate resources.id")
        for resource in self.resources:
            if resource.bound_core_id not in core_ids:
                raise ValueError(
                    f"resource {resource.id} bound_core_id {resource.bound_core_id} does not exist"
                )
        resource_set = set(resource_ids)
        resource_bound_cores = {resource.id: resource.bound_core_id for resource in self.resources}

        task_ids = [task.id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("duplicate tasks.id")

        for task in self.tasks:
            self._validate_task_graph(task, resource_set, core_ids, resource_bound_cores)
        return self

    @staticmethod
    def _validate_task_graph(
        task: TaskGraphSpec,
        resource_set: set[str],
        core_ids: set[str],
        resource_bound_cores: dict[str, str],
    ) -> None:
        subtask_ids = [sub.id for sub in task.subtasks]
        if len(subtask_ids) != len(set(subtask_ids)):
            raise ValueError(f"task {task.id} contains duplicate subtask ids")

        adjacency: dict[str, set[str]] = defaultdict(set)
        subtask_set = set(subtask_ids)
        edges: set[tuple[str, str]] = set()

        for sub in task.subtasks:
            for pred in sub.predecessors:
                if pred not in subtask_set:
                    raise ValueError(
                        f"task '{task.id}' subtask '{sub.id}' references unknown predecessor '{pred}'"
                    )
                edges.add((pred, sub.id))
            for succ in sub.successors:
                if succ not in subtask_set:
                    raise ValueError(
                        f"task '{task.id}' subtask '{sub.id}' references unknown successor '{succ}'"
                    )
                edges.add((sub.id, succ))

            segment_ids = [seg.id for seg in sub.segments]
            if len(segment_ids) != len(set(segment_ids)):
                raise ValueError(f"task '{task.id}' subtask '{sub.id}' has duplicate segment ids")
            indexes = sorted(seg.index for seg in sub.segments)
            if indexes != list(range(1, len(indexes) + 1)):
                raise ValueError(
                    f"task '{task.id}' subtask '{sub.id}' segment index must start at 1 and be continuous"
                )
            for seg in sub.segments:
                for resource_id in seg.required_resources:
                    if resource_id not in resource_set:
                        raise ValueError(
                            f"task '{task.id}' segment '{seg.id}' references unknown resource '{resource_id}'"
                        )
                if seg.mapping_hint and seg.mapping_hint not in core_ids:
                    raise ValueError(
                        f"task '{task.id}' segment '{seg.id}' mapping_hint '{seg.mapping_hint}' does not exist"
                    )
                required_bound_cores = {
                    resource_bound_cores[resource_id]
                    for resource_id in seg.required_resources
                    if resource_id in resource_bound_cores
                }
                if len(required_bound_cores) > 1:
                    ordered = ", ".join(sorted(required_bound_cores))
                    raise ValueError(
                        f"task '{task.id}' segment '{seg.id}' requires resources bound to multiple cores: {ordered}"
                    )
                if required_bound_cores:
                    bound_core_id = next(iter(required_bound_cores))
                    if seg.mapping_hint is None:
                        seg.mapping_hint = bound_core_id
                    elif seg.mapping_hint != bound_core_id:
                        raise ValueError(
                            f"task '{task.id}' segment '{seg.id}' mapping_hint '{seg.mapping_hint}' "
                            f"conflicts with required resource core '{bound_core_id}'"
                        )

        indegree: dict[str, int] = {sub_id: 0 for sub_id in subtask_ids}
        for src, dst in sorted(edges):
            adjacency[src].add(dst)
            indegree[dst] += 1

        queue = deque([node for node, deg in indegree.items() if deg == 0])
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for nxt in adjacency[current]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)

        if visited != len(indegree):
            raise ValueError(f"task '{task.id}' DAG contains cycle")
