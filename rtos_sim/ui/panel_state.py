"""State containers for UI panels."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CompareScenarioState:
    label: str
    metrics: dict[str, Any]
    source: str = ""


@dataclass(slots=True)
class ComparePanelState:
    scenarios: list[CompareScenarioState] = field(default_factory=list)
    latest_report: dict[str, Any] | None = None


@dataclass(slots=True)
class TelemetryPanelState:
    state_transitions: list[str] = field(default_factory=list)
    hovered_segment_key: str | None = None
    locked_segment_key: str | None = None


@dataclass(slots=True)
class DagMultiSelectState:
    selected_subtask_ids: list[str] = field(default_factory=list)
    anchor_subtask_id: str | None = None
    focus_subtask_id: str | None = None


@dataclass(slots=True)
class DagBatchOperationEntry:
    action_id: str
    task_index: int
    selected_subtask_ids: tuple[str, ...] = ()
    focus_subtask_id: str | None = None


@dataclass(slots=True)
class DagOverviewTaskEntry:
    task_index: int
    task_id: str
    task_name: str = ""
    task_type: str = ""
    subtask_count: int = 0
    edge_count: int = 0
    selected_subtask_ids: tuple[str, ...] = ()
    subtask_ids: tuple[str, ...] = ()
    edges: tuple[tuple[str, str], ...] = ()
    node_positions: tuple[tuple[str, tuple[float, float]], ...] = ()


@dataclass(slots=True)
class DagOverviewCanvasEntry:
    task_index: int
    task_id: str
    selected_subtask_ids: tuple[str, ...] = ()
    subtask_ids: tuple[str, ...] = ()
    edges: tuple[tuple[str, str], ...] = ()
    tasks: tuple[DagOverviewTaskEntry, ...] = ()


@dataclass(slots=True)
class DagWorkbenchState:
    node_centers: dict[str, Any] = field(default_factory=dict)
    node_items: dict[str, Any] = field(default_factory=dict)
    edge_items: dict[tuple[str, str], Any] = field(default_factory=dict)
    manual_positions_by_task: dict[str, dict[str, Any]] = field(default_factory=dict)
    drag_source_id: str | None = None
    drag_line: Any | None = None
    multi_selection: DagMultiSelectState = field(default_factory=DagMultiSelectState)
    last_batch_operation: DagBatchOperationEntry | None = None
    overview_canvas_entry: DagOverviewCanvasEntry | None = None
    canvas_mode: str = "detail"
