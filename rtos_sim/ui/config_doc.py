"""Config document helpers for UI editing with unknown-field preservation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


def _ensure_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _unique_id(existing_ids: set[str], prefix: str) -> str:
    index = 0
    while True:
        candidate = f"{prefix}{index}"
        if candidate not in existing_ids:
            return candidate
        index += 1


@dataclass(slots=True)
class TaskView:
    index: int
    task: dict[str, Any]


@dataclass(slots=True)
class ResourceView:
    index: int
    resource: dict[str, Any]


class ConfigDocument:
    """Mutable config wrapper used by UI forms/tables/graph editors."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = deepcopy(payload)
        self._payload.setdefault("version", "0.2")
        self._payload.setdefault("platform", {})
        self._payload.setdefault("tasks", [])
        self._payload.setdefault("resources", [])
        self._payload.setdefault("scheduler", {"name": "edf", "params": {}})
        self._payload.setdefault("sim", {"duration": 10.0, "seed": 42})

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ConfigDocument":
        return cls(payload)

    def to_payload(self) -> dict[str, Any]:
        return deepcopy(self._payload)

    def has_ui_layout(self) -> bool:
        return isinstance(self._payload.get("ui_layout"), dict)

    def get_task_node_layout(self, task_id: str) -> dict[str, tuple[float, float]]:
        ui_layout = _ensure_dict(self._payload.get("ui_layout"))
        task_nodes = _ensure_dict(ui_layout.get("task_nodes"))
        task_layout = _ensure_dict(task_nodes.get(task_id))
        result: dict[str, tuple[float, float]] = {}
        for sub_id, value in task_layout.items():
            if isinstance(value, (list, tuple)) and len(value) == 2:
                try:
                    result[str(sub_id)] = (float(value[0]), float(value[1]))
                except (TypeError, ValueError):
                    continue
        return result

    def set_task_node_layout(self, task_id: str, positions: dict[str, tuple[float, float]]) -> None:
        if not task_id:
            return

        ui_layout = _ensure_dict(self._payload.get("ui_layout"))
        task_nodes = _ensure_dict(ui_layout.get("task_nodes"))
        normalized = {
            str(sub_id): [float(x), float(y)]
            for sub_id, (x, y) in positions.items()
        }
        task_nodes[str(task_id)] = normalized
        ui_layout["task_nodes"] = task_nodes
        self._payload["ui_layout"] = ui_layout

    def get_platform(self) -> dict[str, Any]:
        platform = _ensure_dict(self._payload.get("platform"))
        if "platform" not in self._payload or not isinstance(self._payload["platform"], dict):
            self._payload["platform"] = platform
        platform.setdefault("processor_types", [])
        platform.setdefault("cores", [])
        return platform

    def get_primary_processor(self) -> dict[str, Any]:
        platform = self.get_platform()
        processor_types = _ensure_list(platform.get("processor_types"))
        if "processor_types" not in platform or not isinstance(platform["processor_types"], list):
            platform["processor_types"] = processor_types
        if not processor_types or not isinstance(processor_types[0], dict):
            processor_types.insert(0, {})
        return processor_types[0]

    def patch_primary_processor(self, values: dict[str, Any]) -> None:
        processor = self.get_primary_processor()
        processor.update(values)

    def get_primary_core(self) -> dict[str, Any]:
        platform = self.get_platform()
        cores = _ensure_list(platform.get("cores"))
        if "cores" not in platform or not isinstance(platform["cores"], list):
            platform["cores"] = cores
        if not cores or not isinstance(cores[0], dict):
            cores.insert(0, {})
        return cores[0]

    def patch_primary_core(self, values: dict[str, Any]) -> None:
        core = self.get_primary_core()
        core.update(values)

    def list_tasks(self) -> list[TaskView]:
        tasks = _ensure_list(self._payload.get("tasks"))
        return [
            TaskView(index=idx, task=task)
            for idx, task in enumerate(tasks)
            if isinstance(task, dict)
        ]

    def get_task(self, index: int) -> dict[str, Any]:
        tasks = _ensure_list(self._payload.get("tasks"))
        task = tasks[index]
        if not isinstance(task, dict):
            raise IndexError(f"task at index {index} is not object")
        return task

    def add_task(self, task: dict[str, Any] | None = None) -> int:
        tasks = _ensure_list(self._payload.get("tasks"))
        if "tasks" not in self._payload or not isinstance(self._payload["tasks"], list):
            self._payload["tasks"] = tasks

        existing_ids = {
            str(item.get("id"))
            for item in tasks
            if isinstance(item, dict) and item.get("id") is not None
        }
        default_task = {
            "id": _unique_id(existing_ids, "t"),
            "name": "task",
            "task_type": "dynamic_rt",
            "arrival": 0.0,
            "deadline": 10.0,
            "abort_on_miss": False,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [
                        {
                            "id": "seg0",
                            "index": 1,
                            "wcet": 1.0,
                            "required_resources": [],
                            "mapping_hint": None,
                            "preemptible": True,
                        }
                    ],
                }
            ],
        }
        merged = deepcopy(default_task)
        if isinstance(task, dict):
            merged.update(task)
        tasks.append(merged)
        return len(tasks) - 1

    def remove_task(self, index: int) -> None:
        tasks = _ensure_list(self._payload.get("tasks"))
        if index < 0 or index >= len(tasks):
            return
        tasks.pop(index)
        self._payload["tasks"] = tasks

    def patch_task(self, index: int, values: dict[str, Any]) -> None:
        task = self.get_task(index)
        for key, value in values.items():
            if value is None and key in {"period", "deadline"}:
                task.pop(key, None)
                continue
            task[key] = value

    def list_resources(self) -> list[ResourceView]:
        resources = _ensure_list(self._payload.get("resources"))
        return [
            ResourceView(index=idx, resource=resource)
            for idx, resource in enumerate(resources)
            if isinstance(resource, dict)
        ]

    def get_resource(self, index: int) -> dict[str, Any]:
        resources = _ensure_list(self._payload.get("resources"))
        resource = resources[index]
        if not isinstance(resource, dict):
            raise IndexError(f"resource at index {index} is not object")
        return resource

    def add_resource(self, resource: dict[str, Any] | None = None) -> int:
        resources = _ensure_list(self._payload.get("resources"))
        if "resources" not in self._payload or not isinstance(self._payload["resources"], list):
            self._payload["resources"] = resources

        existing_ids = {
            str(item.get("id"))
            for item in resources
            if isinstance(item, dict) and item.get("id") is not None
        }
        default_resource = {
            "id": _unique_id(existing_ids, "r"),
            "name": "lock",
            "bound_core_id": "c0",
            "protocol": "mutex",
        }
        merged = deepcopy(default_resource)
        if isinstance(resource, dict):
            merged.update(resource)
        resources.append(merged)
        return len(resources) - 1

    def remove_resource(self, index: int) -> None:
        resources = _ensure_list(self._payload.get("resources"))
        if index < 0 or index >= len(resources):
            return
        resources.pop(index)
        self._payload["resources"] = resources

    def patch_resource(self, index: int, values: dict[str, Any]) -> None:
        resource = self.get_resource(index)
        resource.update(values)

    def get_scheduler(self) -> dict[str, Any]:
        scheduler = _ensure_dict(self._payload.get("scheduler"))
        scheduler.setdefault("name", "edf")
        params = _ensure_dict(scheduler.get("params"))
        scheduler["params"] = params
        self._payload["scheduler"] = scheduler
        return scheduler

    def patch_scheduler(self, name: str, params: dict[str, Any]) -> None:
        scheduler = self.get_scheduler()
        scheduler["name"] = name
        existing_params = _ensure_dict(scheduler.get("params"))
        existing_params.update(params)
        scheduler["params"] = existing_params

    def get_sim(self) -> dict[str, Any]:
        sim = _ensure_dict(self._payload.get("sim"))
        sim.setdefault("duration", 10.0)
        sim.setdefault("seed", 42)
        self._payload["sim"] = sim
        return sim

    def patch_sim(self, duration: float, seed: int) -> None:
        sim = self.get_sim()
        sim["duration"] = duration
        sim["seed"] = seed

    def list_subtasks(self, task_index: int) -> list[dict[str, Any]]:
        task = self.get_task(task_index)
        subtasks = _ensure_list(task.get("subtasks"))
        if "subtasks" not in task or not isinstance(task["subtasks"], list):
            task["subtasks"] = subtasks
        return [subtask for subtask in subtasks if isinstance(subtask, dict)]

    def get_subtask(self, task_index: int, subtask_index: int) -> dict[str, Any]:
        task = self.get_task(task_index)
        subtasks = _ensure_list(task.get("subtasks"))
        subtask = subtasks[subtask_index]
        if not isinstance(subtask, dict):
            raise IndexError(f"subtask at index {subtask_index} is not object")
        return subtask

    def patch_subtask(
        self,
        task_index: int,
        subtask_index: int,
        values: dict[str, Any],
    ) -> None:
        task = self.get_task(task_index)
        subtasks = _ensure_list(task.get("subtasks"))
        subtask = self.get_subtask(task_index, subtask_index)

        old_id = str(subtask.get("id") or "")
        new_id: str | None = None

        for key, value in values.items():
            if key == "id":
                requested = str(value).strip()
                if requested:
                    existing_ids = {
                        str(item.get("id"))
                        for idx, item in enumerate(subtasks)
                        if idx != subtask_index and isinstance(item, dict) and item.get("id")
                    }
                    if requested not in existing_ids:
                        new_id = requested
                continue
            subtask[key] = value

        if new_id is None or new_id == old_id:
            return

        subtask["id"] = new_id
        for item in subtasks:
            if not isinstance(item, dict):
                continue
            item["predecessors"] = [
                new_id if str(pred) == old_id else str(pred)
                for pred in _ensure_list(item.get("predecessors"))
            ]
            item["successors"] = [
                new_id if str(succ) == old_id else str(succ)
                for succ in _ensure_list(item.get("successors"))
            ]

    def get_segment(self, task_index: int, subtask_index: int, segment_index: int = 0) -> dict[str, Any]:
        subtask = self.get_subtask(task_index, subtask_index)
        segments = _ensure_list(subtask.get("segments"))
        if "segments" not in subtask or not isinstance(subtask["segments"], list):
            subtask["segments"] = segments
        if not segments:
            segments.append(
                {
                    "id": "seg0",
                    "index": 1,
                    "wcet": 1.0,
                    "required_resources": [],
                    "mapping_hint": None,
                    "preemptible": True,
                }
            )
        if segment_index == 0 and not isinstance(segments[0], dict):
            segments[0] = {
                "id": "seg0",
                "index": 1,
                "wcet": 1.0,
                "required_resources": [],
                "mapping_hint": None,
                "preemptible": True,
            }
        segment = segments[segment_index]
        if not isinstance(segment, dict):
            raise IndexError(f"segment at index {segment_index} is not object")
        return segment

    def patch_segment(
        self,
        task_index: int,
        subtask_index: int,
        values: dict[str, Any],
        segment_index: int = 0,
    ) -> None:
        segment = self.get_segment(task_index, subtask_index, segment_index=segment_index)
        segment.update(values)

    def add_subtask(self, task_index: int, subtask_id: str | None = None) -> int:
        task = self.get_task(task_index)
        subtasks = _ensure_list(task.get("subtasks"))
        existing_ids = {
            str(item.get("id"))
            for item in subtasks
            if isinstance(item, dict) and item.get("id") is not None
        }
        sub_id = (subtask_id or "").strip() or _unique_id(existing_ids, "s")
        if sub_id in existing_ids:
            sub_id = _unique_id(existing_ids, "s")
        subtasks.append(
            {
                "id": sub_id,
                "predecessors": [],
                "successors": [],
                "segments": [
                    {
                        "id": "seg0",
                        "index": 1,
                        "wcet": 1.0,
                        "required_resources": [],
                        "mapping_hint": None,
                        "preemptible": True,
                    }
                ],
            }
        )
        task["subtasks"] = subtasks
        return len(subtasks) - 1

    def remove_subtask(self, task_index: int, subtask_index: int) -> None:
        task = self.get_task(task_index)
        subtasks = _ensure_list(task.get("subtasks"))
        if subtask_index < 0 or subtask_index >= len(subtasks):
            return
        removed = subtasks.pop(subtask_index)
        removed_id = str(removed.get("id")) if isinstance(removed, dict) else ""
        for subtask in subtasks:
            if not isinstance(subtask, dict):
                continue
            predecessors = [x for x in _ensure_list(subtask.get("predecessors")) if str(x) != removed_id]
            successors = [x for x in _ensure_list(subtask.get("successors")) if str(x) != removed_id]
            subtask["predecessors"] = predecessors
            subtask["successors"] = successors
        task["subtasks"] = subtasks

    def add_edge(self, task_index: int, src_id: str, dst_id: str) -> None:
        src = src_id.strip()
        dst = dst_id.strip()
        if not src or not dst or src == dst:
            return
        by_id = self._subtask_map(task_index)
        src_subtask = by_id.get(src)
        dst_subtask = by_id.get(dst)
        if src_subtask is None or dst_subtask is None:
            return

        src_succ = [str(item) for item in _ensure_list(src_subtask.get("successors"))]
        dst_pred = [str(item) for item in _ensure_list(dst_subtask.get("predecessors"))]
        if dst not in src_succ:
            src_succ.append(dst)
        if src not in dst_pred:
            dst_pred.append(src)
        src_subtask["successors"] = src_succ
        dst_subtask["predecessors"] = dst_pred

    def remove_edge(self, task_index: int, src_id: str, dst_id: str) -> None:
        by_id = self._subtask_map(task_index)
        src_subtask = by_id.get(src_id)
        dst_subtask = by_id.get(dst_id)
        if src_subtask is None or dst_subtask is None:
            return

        src_subtask["successors"] = [
            str(item)
            for item in _ensure_list(src_subtask.get("successors"))
            if str(item) != dst_id
        ]
        dst_subtask["predecessors"] = [
            str(item)
            for item in _ensure_list(dst_subtask.get("predecessors"))
            if str(item) != src_id
        ]

    def list_edges(self, task_index: int) -> list[tuple[str, str]]:
        edges: list[tuple[str, str]] = []
        by_id = self._subtask_map(task_index)
        for src_id, subtask in by_id.items():
            successors = _ensure_list(subtask.get("successors"))
            for dst in successors:
                dst_id = str(dst)
                if dst_id in by_id:
                    edges.append((src_id, dst_id))
        return sorted(set(edges))

    def _subtask_map(self, task_index: int) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for subtask in self.list_subtasks(task_index):
            sub_id = str(subtask.get("id") or "")
            if sub_id:
                result[sub_id] = subtask
        return result
