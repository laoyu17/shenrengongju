"""Configuration domain models and semantic validation."""

from __future__ import annotations

from collections import defaultdict, deque
from enum import Enum
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskType(str, Enum):
    """Task timing category."""

    TIME_DETERMINISTIC = "time_deterministic"
    DYNAMIC_RT = "dynamic_rt"
    NON_RT = "non_rt"


class ArrivalModel(str, Enum):
    """Dynamic task arrival model."""

    FIXED_INTERVAL = "fixed_interval"
    UNIFORM_INTERVAL = "uniform_interval"


class ArrivalProcessType(str, Enum):
    """Unified arrival-process type for dynamic/non-RT tasks."""

    FIXED = "fixed"
    UNIFORM = "uniform"
    POISSON = "poisson"
    ONE_SHOT = "one_shot"
    CUSTOM = "custom"


class ArrivalProcessSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ArrivalProcessType
    params: dict[str, Any] = Field(default_factory=dict)
    max_releases: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_params(self) -> "ArrivalProcessSpec":
        allowed: dict[ArrivalProcessType, set[str]] = {
            ArrivalProcessType.FIXED: {"interval"},
            ArrivalProcessType.UNIFORM: {"min_interval", "max_interval"},
            ArrivalProcessType.POISSON: {"rate"},
            ArrivalProcessType.ONE_SHOT: set(),
            ArrivalProcessType.CUSTOM: set(),
        }
        if self.type == ArrivalProcessType.CUSTOM:
            generator = self.params.get("generator")
            if not isinstance(generator, str) or not generator.strip():
                raise ValueError("arrival_process type=custom requires params.generator")
            for key, value in self.params.items():
                if isinstance(value, (dict, list)):
                    raise ValueError(f"arrival_process.params.{key} must be scalar")
        else:
            unknown = sorted(set(self.params) - allowed[self.type])
            if unknown:
                joined = ", ".join(unknown)
                raise ValueError(f"arrival_process.params contains unsupported keys: {joined}")
            for key, value in self.params.items():
                if not isinstance(value, (int, float)):
                    raise ValueError(f"arrival_process.params.{key} must be number")
                if float(value) <= 0:
                    raise ValueError(f"arrival_process.params.{key} must be > 0")
        if self.type == ArrivalProcessType.ONE_SHOT and self.max_releases not in (None, 1):
            raise ValueError("arrival_process type=one_shot only supports max_releases=1")
        return self


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
    release_offsets: Optional[list[float]] = None


class SubtaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    predecessors: list[str] = Field(default_factory=list)
    successors: list[str] = Field(default_factory=list)
    subtask_mapping_hint: Optional[str] = None
    segments: list[SegmentSpec] = Field(min_length=1)


class TaskGraphSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    task_type: TaskType
    period: Optional[float] = Field(default=None, gt=0)
    deadline: Optional[float] = Field(default=None, gt=0)
    arrival: float = Field(default=0, ge=0)
    phase_offset: Optional[float] = Field(default=None, ge=0)
    min_inter_arrival: Optional[float] = Field(default=None, gt=0)
    max_inter_arrival: Optional[float] = Field(default=None, gt=0)
    arrival_model: Optional[ArrivalModel] = None
    arrival_process: Optional[ArrivalProcessSpec] = None
    task_mapping_hint: Optional[str] = None
    abort_on_miss: bool = False
    subtasks: list[SubtaskSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_timing_fields(self) -> "TaskGraphSpec":
        if self.task_type == TaskType.TIME_DETERMINISTIC and self.period is None:
            raise ValueError("time_deterministic task must define period")
        if self.task_type == TaskType.TIME_DETERMINISTIC and self.phase_offset is None:
            self.phase_offset = 0.0
        if self.task_type != TaskType.TIME_DETERMINISTIC and self.phase_offset not in (None, 0.0):
            raise ValueError("phase_offset is only valid for time_deterministic task")
        if self.task_type != TaskType.NON_RT and self.deadline is None:
            raise ValueError("real-time task must define deadline")
        if self.period is not None and self.min_inter_arrival is None and self.task_type == TaskType.DYNAMIC_RT:
            self.min_inter_arrival = self.period
        if self.task_type != TaskType.DYNAMIC_RT and self.max_inter_arrival is not None:
            raise ValueError("max_inter_arrival is only valid for dynamic_rt task")
        if self.max_inter_arrival is not None and self.min_inter_arrival is None:
            raise ValueError("max_inter_arrival requires min_inter_arrival or period")
        if (
            self.max_inter_arrival is not None
            and self.min_inter_arrival is not None
            and self.max_inter_arrival < self.min_inter_arrival - 1e-12
        ):
            raise ValueError("max_inter_arrival must be >= min_inter_arrival")
        if self.task_type != TaskType.DYNAMIC_RT and self.arrival_model is not None:
            raise ValueError("arrival_model is only valid for dynamic_rt task")
        if self.arrival_process is not None:
            self._normalize_arrival_process()
        elif self.task_type == TaskType.DYNAMIC_RT:
            if self.arrival_model is None:
                self.arrival_model = (
                    ArrivalModel.UNIFORM_INTERVAL
                    if self.max_inter_arrival is not None
                    else ArrivalModel.FIXED_INTERVAL
                )
            if self.arrival_model == ArrivalModel.UNIFORM_INTERVAL and self.max_inter_arrival is None:
                raise ValueError("arrival_model=uniform_interval requires max_inter_arrival")
            if self.arrival_model == ArrivalModel.FIXED_INTERVAL and self.max_inter_arrival is not None:
                raise ValueError("arrival_model=fixed_interval does not allow max_inter_arrival")
        if self.period is not None and self.deadline is not None and self.deadline <= 0:
            raise ValueError("deadline must be > 0")
        return self

    @staticmethod
    def _resolve_positive_param(params: dict[str, Any], key: str) -> float | None:
        value = params.get(key)
        if value is None:
            return None
        resolved = float(value)
        if resolved <= 0:
            raise ValueError(f"arrival_process.params.{key} must be > 0")
        return resolved

    def _normalize_arrival_process(self) -> None:
        process = self.arrival_process
        assert process is not None
        if self.task_type == TaskType.TIME_DETERMINISTIC:
            raise ValueError("arrival_process is not valid for time_deterministic task")

        process_type = process.type
        if process_type == ArrivalProcessType.ONE_SHOT and process.max_releases is None:
            process.max_releases = 1

        if process_type == ArrivalProcessType.FIXED:
            interval = self._resolve_positive_param(process.params, "interval")
            if interval is None and self.task_type == TaskType.DYNAMIC_RT:
                interval = self.min_inter_arrival if self.min_inter_arrival is not None else self.period
            if interval is None:
                raise ValueError("arrival_process type=fixed requires params.interval")
            if self.task_type == TaskType.DYNAMIC_RT:
                self.min_inter_arrival = interval
                self.max_inter_arrival = None
                self.arrival_model = ArrivalModel.FIXED_INTERVAL
            return

        if process_type == ArrivalProcessType.UNIFORM:
            min_interval = self._resolve_positive_param(process.params, "min_interval")
            max_interval = self._resolve_positive_param(process.params, "max_interval")
            if self.task_type == TaskType.DYNAMIC_RT:
                if min_interval is None:
                    min_interval = self.min_inter_arrival if self.min_inter_arrival is not None else self.period
                if max_interval is None:
                    max_interval = self.max_inter_arrival
            if min_interval is None or max_interval is None:
                raise ValueError(
                    "arrival_process type=uniform requires params.min_interval and params.max_interval"
                )
            if max_interval < min_interval - 1e-12:
                raise ValueError("arrival_process.params.max_interval must be >= min_interval")
            if self.task_type == TaskType.DYNAMIC_RT:
                self.min_inter_arrival = min_interval
                self.max_inter_arrival = max_interval
                self.arrival_model = ArrivalModel.UNIFORM_INTERVAL
            return

        if process_type == ArrivalProcessType.POISSON:
            rate = self._resolve_positive_param(process.params, "rate")
            if rate is None:
                raise ValueError("arrival_process type=poisson requires params.rate")
            return

        if process_type == ArrivalProcessType.CUSTOM:
            if self.task_type == TaskType.DYNAMIC_RT:
                self.arrival_model = None
            return

        if process_type == ArrivalProcessType.ONE_SHOT and self.task_type == TaskType.DYNAMIC_RT:
            self.arrival_model = None
            self.min_inter_arrival = None
            self.max_inter_arrival = None


class SchedulerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    VALID_EVENT_ID_MODES: ClassVar[set[str]] = {"deterministic", "random", "seeded_random"}

    name: str
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_params(self) -> "SchedulerSpec":
        policy = self.params.get("resource_acquire_policy")
        if policy is not None and str(policy).strip() not in {"legacy_sequential", "atomic_rollback"}:
            raise ValueError("scheduler.params.resource_acquire_policy must be legacy_sequential|atomic_rollback")

        if "event_id_validation" in self.params:
            raise ValueError(
                "scheduler.params.event_id_validation has been removed; "
                "event_id_mode now always fails on invalid values"
            )

        event_mode = self.params.get("event_id_mode")
        if event_mode is not None and not isinstance(event_mode, str):
            raise ValueError("scheduler.params.event_id_mode must be string")
        if event_mode is not None:
            event_mode_value = event_mode.strip().lower()
            if event_mode_value and event_mode_value not in self.VALID_EVENT_ID_MODES:
                raise ValueError(
                    "scheduler.params.event_id_mode must be "
                    "deterministic|random|seeded_random"
                )

        etm_name = self.params.get("etm")
        if etm_name is not None and not isinstance(etm_name, str):
            raise ValueError("scheduler.params.etm must be string")

        etm_params = self.params.get("etm_params")
        if etm_params is not None and not isinstance(etm_params, dict):
            raise ValueError("scheduler.params.etm_params must be object")
        return self


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
        cores_by_type: dict[str, int] = defaultdict(int)
        for core in self.cores:
            if core.type_id not in processor_set:
                raise ValueError(f"core {core.id} references unknown processor type {core.type_id}")
            cores_by_type[core.type_id] += 1

        for processor in self.processor_types:
            actual = cores_by_type.get(processor.id, 0)
            if actual != processor.core_count:
                raise ValueError(
                    "processor type "
                    f"'{processor.id}' declares core_count={processor.core_count} "
                    f"but has {actual} cores in platform.cores"
                )
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
        task_mapping_hint = task.task_mapping_hint
        if task_mapping_hint and task_mapping_hint not in core_ids:
            raise ValueError(
                f"task '{task.id}' task_mapping_hint '{task_mapping_hint}' does not exist"
            )

        adjacency: dict[str, set[str]] = defaultdict(set)
        subtask_set = set(subtask_ids)
        edges: set[tuple[str, str]] = set()

        for sub in task.subtasks:
            subtask_mapping_hint = sub.subtask_mapping_hint
            if subtask_mapping_hint and subtask_mapping_hint not in core_ids:
                raise ValueError(
                    f"task '{task.id}' subtask '{sub.id}' subtask_mapping_hint "
                    f"'{subtask_mapping_hint}' does not exist"
                )
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
                effective_mapping_hint = seg.mapping_hint or subtask_mapping_hint or task_mapping_hint
                for resource_id in seg.required_resources:
                    if resource_id not in resource_set:
                        raise ValueError(
                            f"task '{task.id}' segment '{seg.id}' references unknown resource '{resource_id}'"
                        )
                if effective_mapping_hint and effective_mapping_hint not in core_ids:
                    raise ValueError(
                        f"task '{task.id}' segment '{seg.id}' mapping_hint '{effective_mapping_hint}' does not exist"
                    )
                if seg.release_offsets is not None:
                    if task.task_type != TaskType.TIME_DETERMINISTIC:
                        raise ValueError(
                            f"task '{task.id}' segment '{seg.id}' release_offsets requires time_deterministic task"
                        )
                    if not seg.release_offsets:
                        raise ValueError(
                            f"task '{task.id}' segment '{seg.id}' release_offsets must not be empty"
                        )
                    for offset in seg.release_offsets:
                        if offset < 0:
                            raise ValueError(
                                f"task '{task.id}' segment '{seg.id}' release_offsets must be >= 0"
                            )
                        if task.period is not None and offset >= task.period - 1e-12:
                            raise ValueError(
                                f"task '{task.id}' segment '{seg.id}' release_offset {offset} must be < period"
                            )
                elif task.task_type == TaskType.TIME_DETERMINISTIC:
                    seg.release_offsets = [0.0]
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
                    if effective_mapping_hint is None:
                        effective_mapping_hint = bound_core_id
                    elif effective_mapping_hint != bound_core_id:
                        raise ValueError(
                            f"task '{task.id}' segment '{seg.id}' mapping_hint '{effective_mapping_hint}' "
                            f"conflicts with required resource core '{bound_core_id}'"
                        )
                if task.task_type == TaskType.TIME_DETERMINISTIC and effective_mapping_hint is None:
                    if len(core_ids) == 1:
                        effective_mapping_hint = sorted(core_ids)[0]
                    else:
                        raise ValueError(
                            f"task '{task.id}' segment '{seg.id}' requires mapping_hint for "
                            "time_deterministic task on multi-core platform"
                        )
                seg.mapping_hint = effective_mapping_hint

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
