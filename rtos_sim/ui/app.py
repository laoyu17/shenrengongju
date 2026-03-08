"""PyQt6 UI app for simulation control and visualization."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import pyqtgraph as pg
import yaml
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QCloseEvent, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QDoubleSpinBox,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigError, ConfigLoader

from .controllers import (
    CompareController,
    DagController,
    DagOverviewController,
    FormController,
    GanttStyleController,
    PlanningController,
    ResearchReportController,
    RunController,
    TelemetryController,
    TimelineController,
)
from .config_doc import ConfigDocument
from .gantt_helpers import (
    SegmentBlockItem,
    SegmentVisualMeta,
    format_segment_details,
    safe_float,
    safe_optional_float,
)
from .panel_builders import build_compare_group, build_dag_workbench_group, build_planning_tab
from .panel_state import (
    ComparePanelState,
    DagBatchOperationEntry,
    DagMultiSelectState,
    DagOverviewCanvasEntry,
    DagWorkbenchState,
    TelemetryPanelState,
)
from .table_validation import build_resource_table_errors, build_task_table_errors
from .worker import SimulationWorker

_LOGGER = logging.getLogger(__name__)


def _log_ui_error(action: str, exc: Exception, **context: Any) -> None:
    """Emit structured UI error logs for diagnostics."""

    payload: dict[str, Any] = {
        "event": "ui_error",
        "action": action,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }
    payload.update({key: value for key, value in context.items() if value is not None})
    _LOGGER.error(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), exc_info=exc)


class DagNodeItem(QGraphicsEllipseItem):
    """Interactive DAG node supporting move and drag-to-connect."""

    def __init__(
        self,
        *,
        owner: "MainWindow",
        subtask_id: str,
        center: QPointF,
        radius: float,
        selected: bool,
    ) -> None:
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self._owner = owner
        self.subtask_id = subtask_id
        self._link_dragging = False
        self.setPos(center)
        self.setBrush(QBrush(QColor("#2d7ff9" if selected else "#47617a")))
        self.setPen(QPen(QColor("#f5f7fa")))
        self.setZValue(2)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: Any) -> None:  # noqa: ANN401
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
        start_link = event.button() == Qt.MouseButton.RightButton or (
            event.button() == Qt.MouseButton.LeftButton
            and bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        )
        toggle_selection = not start_link and (
            bool(modifiers & Qt.KeyboardModifier.ControlModifier)
            or bool(modifiers & Qt.KeyboardModifier.MetaModifier)
        )
        self._owner._on_dag_node_clicked(
            self.subtask_id,
            toggle=toggle_selection,
            preserve_existing=not toggle_selection,
        )
        if start_link:
            self._owner._start_dag_link_drag(self.subtask_id, event.scenePos())
            self._link_dragging = True
            self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        if toggle_selection:
            self._link_dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        self._link_dragging = False
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: ANN401
        if self._link_dragging:
            self._owner._update_dag_link_drag(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: ANN401
        if self._link_dragging:
            self._owner._finish_dag_link_drag(event.scenePos())
            self._link_dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._owner._on_dag_node_drag_finished(self.subtask_id)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and isinstance(value, QPointF):
            self._owner._on_dag_node_moved(self.subtask_id, value)
        return super().itemChange(change, value)


class MainWindow(QMainWindow):
    """Main window with config editor, run controls and Gantt view."""

    _SUBTASK_BRUSH_STYLES = [
        Qt.BrushStyle.SolidPattern,
        Qt.BrushStyle.Dense4Pattern,
        Qt.BrushStyle.Dense6Pattern,
        Qt.BrushStyle.BDiagPattern,
        Qt.BrushStyle.DiagCrossPattern,
        Qt.BrushStyle.CrossPattern,
    ]
    _SEGMENT_PEN_STYLES = [
        Qt.PenStyle.SolidLine,
        Qt.PenStyle.DotLine,
        Qt.PenStyle.DashDotLine,
        Qt.PenStyle.DashDotDotLine,
    ]
    _TASK_TYPE_OPTIONS = {"dynamic_rt", "time_deterministic", "non_rt"}
    _RESOURCE_PROTOCOL_OPTIONS = {"mutex", "pip", "pcp"}
    _RIGHT_SPLITTER_LOWER_RATIO_COLLAPSED = 0.36
    _RIGHT_SPLITTER_LOWER_RATIO_EXPANDED = 0.42
    _RIGHT_SPLITTER_LOWER_MIN_COLLAPSED = 180
    _RIGHT_SPLITTER_LOWER_MIN_EXPANDED = 260

    def __init__(self, config_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("RTOS Sim UI (PyQt6)")
        self.resize(1500, 920)

        self._loader = ConfigLoader()
        self._worker: SimulationWorker | None = None

        self._core_to_y: dict[str, int] = {}
        self._active_segments: dict[str, dict[str, Any]] = {}
        self._segment_resources: dict[str, set[str]] = {}
        self._job_deadlines: dict[str, float | None] = {}

        self._legend_tasks: set[str] = set()
        self._legend_samples: list[pg.PlotDataItem] = []
        self._subtask_legend_map: dict[tuple[str, str], str] = {}
        self._segment_legend_map: dict[str, str] = {}

        self._subtask_style_cache: dict[tuple[str, str], Qt.BrushStyle] = {}
        self._segment_style_cache: dict[str, Qt.PenStyle] = {}

        self._segment_items: list[SegmentBlockItem] = []
        self._segment_labels: list[pg.TextItem] = []
        self._seen_event_ids: set[str] = set()

        self._max_time = 0.0
        self._lane_height = 0.62
        self._segment_label_min_duration = 0.85

        self._compare_panel_state = ComparePanelState()
        self._dag_workbench_state = DagWorkbenchState()
        self._telemetry_panel_state = TelemetryPanelState()
        self._latest_metrics_report: dict[str, Any] = {}
        self._latest_run_payload: dict[str, Any] | None = None
        self._latest_run_spec: Any | None = None
        self._latest_run_events: list[dict[str, Any]] | None = None
        self._latest_audit_report: dict[str, Any] | None = None
        self._latest_model_relations_report: dict[str, Any] | None = None
        self._latest_quality_snapshot: dict[str, Any] | None = None
        self._latest_research_report: dict[str, Any] | None = None
        self._latest_plan_result: Any | None = None
        self._latest_plan_payload: dict[str, Any] | None = None
        self._latest_plan_spec_fingerprint: str | None = None
        self._latest_plan_semantic_fingerprint: str | None = None
        self._latest_planning_wcrt_report: Any | None = None
        self._latest_planning_os_payload: dict[str, Any] | None = None

        self._editor = QPlainTextEdit()
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._form_dirty = False
        self._suspend_form_events = False
        self._suspend_text_events = False
        self._config_doc: ConfigDocument | None = None
        self._selected_task_index = 0
        self._selected_resource_index = 0
        self._selected_subtask_id = "s0"
        self._table_validation_errors: dict[tuple[str, int, int], str] = {}
        self._editor_tabs = QTabWidget()
        self._form_hint = QLabel("Structured form ready.")
        self._sync_text_to_form_button = QPushButton("Sync Text -> Form")
        self._sync_form_to_text_button = QPushButton("Apply Form -> Text")

        self._form_processor_id = QLineEdit("CPU")
        self._form_processor_name = QLineEdit("cpu")
        self._form_processor_core_count = QSpinBox()
        self._form_processor_core_count.setRange(1, 4096)
        self._form_processor_core_count.setValue(1)
        self._form_processor_speed = QDoubleSpinBox()
        self._form_processor_speed.setRange(0.001, 1_000_000.0)
        self._form_processor_speed.setDecimals(3)
        self._form_processor_speed.setValue(1.0)
        self._form_core_id = QLineEdit("c0")
        self._form_core_speed = QDoubleSpinBox()
        self._form_core_speed.setRange(0.001, 1_000_000.0)
        self._form_core_speed.setDecimals(3)
        self._form_core_speed.setValue(1.0)

        self._form_resource_enabled = QCheckBox("Enable one basic resource")
        self._form_resource_enabled.setChecked(False)
        self._form_resource_id = QLineEdit("r0")
        self._form_resource_name = QLineEdit("lock")
        self._form_resource_bound_core = QLineEdit("c0")
        self._form_resource_protocol = QComboBox()
        self._form_resource_protocol.addItems(["mutex", "pip", "pcp"])
        self._resource_table = QTableWidget(0, 4)
        self._resource_table.setHorizontalHeaderLabels(["id", "name", "bound_core_id", "protocol"])
        self._resource_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._resource_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._resource_table.verticalHeader().setVisible(False)
        self._resource_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._resource_add_button = QPushButton("Add Resource")
        self._resource_remove_button = QPushButton("Remove Resource")

        self._form_task_id = QLineEdit("t0")
        self._form_task_name = QLineEdit("task")
        self._form_task_type = QComboBox()
        self._form_task_type.addItems(["dynamic_rt", "time_deterministic", "non_rt"])
        self._form_task_arrival = QDoubleSpinBox()
        self._form_task_arrival.setRange(0.0, 1_000_000.0)
        self._form_task_arrival.setDecimals(3)
        self._form_task_arrival.setValue(0.0)
        self._form_task_period = QLineEdit("10")
        self._form_task_deadline = QLineEdit("10")
        self._form_task_abort_on_miss = QCheckBox("abort_on_miss")
        self._form_task_abort_on_miss.setChecked(False)
        self._form_subtask_id = QLineEdit("s0")
        self._form_segment_id = QLineEdit("seg0")
        self._form_segment_wcet = QDoubleSpinBox()
        self._form_segment_wcet.setRange(0.001, 1_000_000.0)
        self._form_segment_wcet.setDecimals(3)
        self._form_segment_wcet.setValue(1.0)
        self._form_segment_mapping_hint = QLineEdit("c0")
        self._form_segment_required_resources = QLineEdit("")
        self._form_segment_preemptible = QCheckBox("preemptible")
        self._form_segment_preemptible.setChecked(True)
        self._task_table = QTableWidget(0, 5)
        self._task_table.setHorizontalHeaderLabels(["id", "name", "task_type", "arrival", "deadline"])
        self._task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._task_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._task_table.verticalHeader().setVisible(False)
        self._task_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._task_add_button = QPushButton("Add Task")
        self._task_remove_button = QPushButton("Remove Task")

        self._dag_scene = QGraphicsScene(self)
        self._dag_view = QGraphicsView(self._dag_scene)
        self._dag_view.setMinimumHeight(210)
        self._dag_overview_scene = QGraphicsScene(self)
        self._dag_overview_view = QGraphicsView(self._dag_overview_scene)
        self._dag_overview_view.setMinimumHeight(210)
        self._dag_canvas_tabs = QTabWidget()
        self._dag_overview_tab: QWidget | None = None
        self._dag_detail_tab: QWidget | None = None
        self._dag_subtasks_list = QListWidget()
        self._dag_edges_list = QListWidget()
        self._dag_new_subtask_id = QLineEdit()
        self._dag_new_subtask_id.setPlaceholderText("new subtask id (optional)")
        self._dag_add_subtask_button = QPushButton("Add Subtask")
        self._dag_remove_subtask_button = QPushButton("Remove Selected Subtask")
        self._dag_edge_src = QLineEdit()
        self._dag_edge_src.setPlaceholderText("src id")
        self._dag_edge_dst = QLineEdit()
        self._dag_edge_dst.setPlaceholderText("dst id")
        self._dag_add_edge_button = QPushButton("Add Edge")
        self._dag_remove_edge_button = QPushButton("Remove Selected Edge")
        self._dag_auto_layout_button = QPushButton("Auto Layout")
        self._dag_persist_layout = QCheckBox("Persist Layout (ui_layout)")
        self._dag_persist_layout.setChecked(False)

        self._form_scheduler_name = QComboBox()
        self._form_scheduler_name.addItems(["edf", "rm", "fixed_priority"])
        self._form_tie_breaker = QComboBox()
        self._form_tie_breaker.addItems(["fifo", "lifo", "segment_key"])
        self._form_allow_preempt = QCheckBox("allow_preempt")
        self._form_allow_preempt.setChecked(True)
        self._form_event_id_mode = QComboBox()
        self._form_event_id_mode.addItems(["deterministic", "random", "seeded_random"])
        self._form_resource_acquire_policy = QComboBox()
        self._form_resource_acquire_policy.addItems(["legacy_sequential", "atomic_rollback"])
        self._form_sim_duration = QDoubleSpinBox()
        self._form_sim_duration.setRange(0.001, 1_000_000.0)
        self._form_sim_duration.setDecimals(3)
        self._form_sim_duration.setValue(10.0)
        self._form_sim_seed = QSpinBox()
        self._form_sim_seed.setRange(-2_147_483_648, 2_147_483_647)
        self._form_sim_seed.setValue(42)

        self._planning_enabled = QCheckBox("planning.enabled")
        self._planning_enabled.setChecked(False)
        self._planning_planner = QComboBox()
        self._planning_planner.addItems(
            ["np_edf", "np_dm", "np_rm", "precautious_dm", "precautious_rm", "lp"]
        )
        self._planning_lp_objective = QComboBox()
        self._planning_lp_objective.addItems(["response_time", "spread_execution"])
        self._planning_task_scope = QComboBox()
        self._planning_task_scope.addItems(["sync_only", "sync_and_dynamic_rt", "all"])
        self._planning_include_non_rt = QCheckBox("include_non_rt")
        self._planning_horizon = QDoubleSpinBox()
        self._planning_horizon.setRange(0.0, 1_000_000.0)
        self._planning_horizon.setDecimals(3)
        self._planning_horizon.setSpecialValueText("auto")
        self._planning_horizon.setValue(0.0)
        self._planning_time_limit = QDoubleSpinBox()
        self._planning_time_limit.setRange(0.1, 1_000_000.0)
        self._planning_time_limit.setDecimals(3)
        self._planning_time_limit.setValue(30.0)
        self._planning_wcrt_max_iterations = QSpinBox()
        self._planning_wcrt_max_iterations.setRange(1, 10_000)
        self._planning_wcrt_max_iterations.setValue(64)
        self._planning_wcrt_epsilon = QDoubleSpinBox()
        self._planning_wcrt_epsilon.setDecimals(12)
        self._planning_wcrt_epsilon.setRange(1e-12, 1.0)
        self._planning_wcrt_epsilon.setValue(1e-9)
        self._planning_plan_button = QPushButton("Plan Static")
        self._planning_wcrt_button = QPushButton("Analyze WCRT")
        self._planning_export_button = QPushButton("Export OS Config")

        self._planning_random_seed = QSpinBox()
        self._planning_random_seed.setRange(-2_147_483_648, 2_147_483_647)
        self._planning_random_seed.setValue(20260304)
        self._planning_random_load_tier = QComboBox()
        self._planning_random_load_tier.addItems(["low", "medium", "high"])
        self._planning_random_rule = QComboBox()
        self._planning_random_rule.addItems(["single_chain", "fork_join"])
        self._planning_random_task_count = QSpinBox()
        self._planning_random_task_count.setRange(1, 64)
        self._planning_random_task_count.setValue(3)
        self._planning_random_generate_button = QPushButton("Generate Random Tasks")

        self._planning_windows_table = QTableWidget(0, 8)
        self._planning_windows_table.setHorizontalHeaderLabels(
            ["segment_key", "task_id", "subtask_id", "segment_id", "core_id", "start", "end", "deadline"]
        )
        self._planning_windows_table.verticalHeader().setVisible(False)
        self._planning_windows_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._planning_wcrt_table = QTableWidget(0, 4)
        self._planning_wcrt_table.setHorizontalHeaderLabels(["task_id", "wcrt", "deadline", "schedulable"])
        self._planning_wcrt_table.verticalHeader().setVisible(False)
        self._planning_wcrt_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._planning_os_table = QTableWidget(0, 7)
        self._planning_os_table.setHorizontalHeaderLabels(
            ["task_id", "priority", "core_binding", "primary_core", "window_count", "deadline", "total_wcet"]
        )
        self._planning_os_table.verticalHeader().setVisible(False)
        self._planning_os_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._planning_output = QPlainTextEdit()
        self._planning_output.setReadOnly(True)
        self._planning_output.setMaximumHeight(180)

        self._validate_button = QPushButton("Validate")
        self._run_button = QPushButton("Run")
        self._stop_button = QPushButton("Stop")
        self._pause_button = QPushButton("Pause")
        self._resume_button = QPushButton("Resume")
        self._step_button = QPushButton("Step")
        self._reset_button = QPushButton("Reset")
        self._research_export_button = QPushButton("Export Research Report")
        self._step_delta_spin = QDoubleSpinBox()
        self._step_delta_spin.setRange(0.0, 1_000_000.0)
        self._step_delta_spin.setDecimals(3)
        self._step_delta_spin.setSingleStep(0.1)
        self._step_delta_spin.setSpecialValueText("auto")
        self._step_delta_spin.setValue(0.0)
        self._load_button = QPushButton("Load")
        self._save_button = QPushButton("Save")
        self._status_label = QLabel("Ready")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._plot = pg.PlotWidget(title="Gantt (CPU Lanes)")
        self._plot.showGrid(x=True, y=True)
        self._plot.setLabel("bottom", "Time")
        self._plot.setLabel("left", "Core")
        self._plot.addLegend(offset=(10, 10))
        self._plot.setMinimumHeight(320)

        self._legend_toggle_subtask = QPushButton("Subtask Legend")
        self._legend_toggle_subtask.setCheckable(True)
        self._legend_toggle_segment = QPushButton("Segment Legend")
        self._legend_toggle_segment.setCheckable(True)

        self._legend_detail = QPlainTextEdit()
        self._legend_detail.setReadOnly(True)
        self._legend_detail.setMaximumHeight(120)
        self._legend_detail.hide()

        self._hover_hint = QLabel("Hover a segment for details. Click segment to lock/unlock.")

        self._metrics = QTextEdit()
        self._metrics.setReadOnly(True)

        self._state_legend = QLabel("State Legend: Released / Ready / Executing / Blocked")
        self._state_view = QPlainTextEdit()
        self._state_view.setReadOnly(True)
        self._state_view.setMaximumHeight(150)

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(200)

        self._compare_left_label = QLineEdit("")
        self._compare_right_label = QLineEdit("")
        self._compare_scenario_label = QLineEdit("")
        self._compare_scenario_label.setPlaceholderText("optional label for next added scenario")
        self._compare_scenarios_list = QListWidget()
        self._compare_scenarios_list.setMinimumHeight(104)
        self._compare_add_metrics_button = QPushButton("Add Metrics File")
        self._compare_add_latest_button = QPushButton("Add Latest Run")
        self._compare_remove_selected_button = QPushButton("Remove Selected")
        self._compare_move_up_button = QPushButton("Move Up")
        self._compare_move_down_button = QPushButton("Move Down")
        self._compare_load_left_button = QPushButton("Load Left Metrics")
        self._compare_load_right_button = QPushButton("Load Right Metrics")
        self._compare_use_latest_left_button = QPushButton("Use Latest -> Left")
        self._compare_use_latest_right_button = QPushButton("Use Latest -> Right")
        self._compare_build_button = QPushButton("Build Compare")
        self._compare_export_json_button = QPushButton("Export Compare JSON")
        self._compare_export_csv_button = QPushButton("Export Compare CSV")
        self._compare_export_markdown_button = QPushButton("Export Compare Markdown")
        self._compare_output = QPlainTextEdit()
        self._compare_output.setReadOnly(True)
        self._compare_output.setMinimumHeight(120)
        self._compare_output.setMaximumHeight(220)
        self._compare_toggle_button = QPushButton("Show FR-13 Compare")
        self._compare_toggle_button.setCheckable(True)
        self._compare_group: QGroupBox | None = None
        self._telemetry_scroll: QScrollArea | None = None
        self._right_splitter: QSplitter | None = None
        self._compare_controller = CompareController(self, _log_ui_error)
        self._form_controller = FormController(self, _log_ui_error)
        self._dag_controller = DagController(self)
        self._dag_overview_controller = DagOverviewController(self)
        self._gantt_style_controller = GanttStyleController(self)
        self._planning_controller = PlanningController(self, _log_ui_error)
        self._research_report_controller = ResearchReportController(self, _log_ui_error)
        self._run_controller = RunController(self, _log_ui_error)
        self._telemetry_controller = TelemetryController(self)
        self._timeline_controller = TimelineController(self)

        self._build_layout()
        self._connect_signals()

        if config_path:
            self._load_file(config_path)
        else:
            self._sync_form_to_text(show_message=False)

    @property
    def _compare_left_metrics(self) -> dict[str, Any] | None:
        return self._compare_controller.get_scenario_metrics(0)

    @_compare_left_metrics.setter
    def _compare_left_metrics(self, value: dict[str, Any] | None) -> None:
        self._compare_controller.set_scenario_metrics(0, value, default_label="baseline")

    @property
    def _compare_right_metrics(self) -> dict[str, Any] | None:
        return self._compare_controller.get_scenario_metrics(1)

    @_compare_right_metrics.setter
    def _compare_right_metrics(self, value: dict[str, Any] | None) -> None:
        self._compare_controller.set_scenario_metrics(1, value, default_label="focus")

    @property
    def _latest_compare_report(self) -> dict[str, Any] | None:
        return self._compare_panel_state.latest_report

    @_latest_compare_report.setter
    def _latest_compare_report(self, value: dict[str, Any] | None) -> None:
        self._compare_panel_state.latest_report = value

    @property
    def _state_transitions(self) -> list[str]:
        return self._telemetry_panel_state.state_transitions

    @_state_transitions.setter
    def _state_transitions(self, value: list[str]) -> None:
        self._telemetry_panel_state.state_transitions = list(value)

    @property
    def _hovered_segment_key(self) -> str | None:
        return self._telemetry_panel_state.hovered_segment_key

    @_hovered_segment_key.setter
    def _hovered_segment_key(self, value: str | None) -> None:
        self._telemetry_panel_state.hovered_segment_key = value

    @property
    def _locked_segment_key(self) -> str | None:
        return self._telemetry_panel_state.locked_segment_key

    @_locked_segment_key.setter
    def _locked_segment_key(self, value: str | None) -> None:
        self._telemetry_panel_state.locked_segment_key = value

    @property
    def _dag_node_centers(self) -> dict[str, QPointF]:
        return self._dag_workbench_state.node_centers

    @_dag_node_centers.setter
    def _dag_node_centers(self, value: dict[str, QPointF]) -> None:
        self._dag_workbench_state.node_centers = dict(value)

    @property
    def _dag_node_items(self) -> dict[str, DagNodeItem]:
        return self._dag_workbench_state.node_items

    @_dag_node_items.setter
    def _dag_node_items(self, value: dict[str, DagNodeItem]) -> None:
        self._dag_workbench_state.node_items = dict(value)

    @property
    def _dag_edge_items(self) -> dict[tuple[str, str], QGraphicsLineItem]:
        return self._dag_workbench_state.edge_items

    @_dag_edge_items.setter
    def _dag_edge_items(self, value: dict[tuple[str, str], QGraphicsLineItem]) -> None:
        self._dag_workbench_state.edge_items = dict(value)

    @property
    def _dag_manual_positions_by_task(self) -> dict[str, dict[str, QPointF]]:
        return self._dag_workbench_state.manual_positions_by_task

    @_dag_manual_positions_by_task.setter
    def _dag_manual_positions_by_task(self, value: dict[str, dict[str, QPointF]]) -> None:
        self._dag_workbench_state.manual_positions_by_task = {
            key: dict(positions) for key, positions in value.items()
        }

    @property
    def _dag_drag_source_id(self) -> str | None:
        return self._dag_workbench_state.drag_source_id

    @_dag_drag_source_id.setter
    def _dag_drag_source_id(self, value: str | None) -> None:
        self._dag_workbench_state.drag_source_id = value

    @property
    def _dag_drag_line(self) -> QGraphicsLineItem | None:
        return self._dag_workbench_state.drag_line

    @_dag_drag_line.setter
    def _dag_drag_line(self, value: QGraphicsLineItem | None) -> None:
        self._dag_workbench_state.drag_line = value

    @property
    def _dag_multi_select_state(self) -> DagMultiSelectState:
        return self._dag_workbench_state.multi_selection

    @property
    def _dag_last_batch_operation(self) -> DagBatchOperationEntry | None:
        return self._dag_workbench_state.last_batch_operation

    @_dag_last_batch_operation.setter
    def _dag_last_batch_operation(self, value: DagBatchOperationEntry | None) -> None:
        self._dag_workbench_state.last_batch_operation = value

    @property
    def _dag_overview_canvas_entry(self) -> DagOverviewCanvasEntry | None:
        return self._dag_workbench_state.overview_canvas_entry

    @_dag_overview_canvas_entry.setter
    def _dag_overview_canvas_entry(self, value: DagOverviewCanvasEntry | None) -> None:
        self._dag_workbench_state.overview_canvas_entry = value

    @property
    def _dag_canvas_mode(self) -> str:
        return self._dag_workbench_state.canvas_mode

    @_dag_canvas_mode.setter
    def _dag_canvas_mode(self, value: str) -> None:
        self._dag_workbench_state.canvas_mode = value

    def _build_layout(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._load_button)
        toolbar.addWidget(self._save_button)
        toolbar.addWidget(self._validate_button)
        toolbar.addWidget(self._run_button)
        toolbar.addWidget(self._stop_button)
        toolbar.addWidget(self._pause_button)
        toolbar.addWidget(self._resume_button)
        toolbar.addWidget(self._step_button)
        toolbar.addWidget(QLabel("Step Δ"))
        toolbar.addWidget(self._step_delta_spin)
        toolbar.addWidget(self._reset_button)
        toolbar.addWidget(self._research_export_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self._status_label)
        root_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        editor_container = QWidget()
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.addWidget(QLabel("Config Editor"))

        form_tab = QWidget()
        form_tab_layout = QVBoxLayout(form_tab)
        sync_toolbar = QHBoxLayout()
        sync_toolbar.addWidget(self._sync_text_to_form_button)
        sync_toolbar.addWidget(self._sync_form_to_text_button)
        sync_toolbar.addStretch(1)
        sync_toolbar.addWidget(self._form_hint)
        form_tab_layout.addLayout(sync_toolbar)

        form_content = QWidget()
        form_content_layout = QVBoxLayout(form_content)

        platform_group = QGroupBox("Platform")
        platform_form = QFormLayout(platform_group)
        platform_form.addRow("processor_type.id", self._form_processor_id)
        platform_form.addRow("processor_type.name", self._form_processor_name)
        platform_form.addRow("processor_type.core_count", self._form_processor_core_count)
        platform_form.addRow("processor_type.speed_factor", self._form_processor_speed)
        platform_form.addRow("core.id", self._form_core_id)
        platform_form.addRow("core.speed_factor", self._form_core_speed)
        form_content_layout.addWidget(platform_group)

        resource_group = QGroupBox("Resources (Table + Selected Detail)")
        resource_layout = QVBoxLayout(resource_group)
        resource_layout.addWidget(self._resource_table)
        resource_button_row = QHBoxLayout()
        resource_button_row.addWidget(self._resource_add_button)
        resource_button_row.addWidget(self._resource_remove_button)
        resource_button_row.addStretch(1)
        resource_layout.addLayout(resource_button_row)
        resource_form = QFormLayout()
        resource_form.addRow(self._form_resource_enabled)
        resource_form.addRow("selected resource.id", self._form_resource_id)
        resource_form.addRow("selected resource.name", self._form_resource_name)
        resource_form.addRow("selected resource.bound_core_id", self._form_resource_bound_core)
        resource_form.addRow("selected resource.protocol", self._form_resource_protocol)
        resource_layout.addLayout(resource_form)
        form_content_layout.addWidget(resource_group)

        task_group = QGroupBox("Tasks (Table + DAG Workbench + Selected Detail)")
        task_layout = QVBoxLayout(task_group)
        task_layout.addWidget(self._task_table)
        task_button_row = QHBoxLayout()
        task_button_row.addWidget(self._task_add_button)
        task_button_row.addWidget(self._task_remove_button)
        task_button_row.addStretch(1)
        task_layout.addLayout(task_button_row)
        task_layout.addWidget(build_dag_workbench_group(self))

        task_form = QFormLayout()
        task_form.addRow("selected task.id", self._form_task_id)
        task_form.addRow("selected task.name", self._form_task_name)
        task_form.addRow("selected task.task_type", self._form_task_type)
        task_form.addRow("selected task.arrival", self._form_task_arrival)
        task_form.addRow("selected task.period (optional)", self._form_task_period)
        task_form.addRow("selected task.deadline (optional)", self._form_task_deadline)
        task_form.addRow(self._form_task_abort_on_miss)
        task_form.addRow("selected subtask.id", self._form_subtask_id)
        task_form.addRow("selected segment.id", self._form_segment_id)
        task_form.addRow("selected segment.wcet", self._form_segment_wcet)
        task_form.addRow("selected segment.mapping_hint (optional)", self._form_segment_mapping_hint)
        task_form.addRow(
            "segment.required_resources (comma separated)",
            self._form_segment_required_resources,
        )
        task_form.addRow(self._form_segment_preemptible)
        task_layout.addLayout(task_form)
        form_content_layout.addWidget(task_group)

        runtime_group = QGroupBox("Scheduler / Simulation")
        runtime_form = QFormLayout(runtime_group)
        runtime_form.addRow("scheduler.name", self._form_scheduler_name)
        runtime_form.addRow("scheduler.params.tie_breaker", self._form_tie_breaker)
        runtime_form.addRow(self._form_allow_preempt)
        runtime_form.addRow("scheduler.params.event_id_mode", self._form_event_id_mode)
        runtime_form.addRow(
            "scheduler.params.resource_acquire_policy",
            self._form_resource_acquire_policy,
        )
        runtime_form.addRow("sim.duration", self._form_sim_duration)
        runtime_form.addRow("sim.seed", self._form_sim_seed)
        form_content_layout.addWidget(runtime_group)
        form_content_layout.addStretch(1)

        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(form_content)
        form_tab_layout.addWidget(form_scroll)

        text_tab = QWidget()
        text_tab_layout = QVBoxLayout(text_tab)
        text_tab_layout.addWidget(QLabel("YAML / JSON Text"))
        text_tab_layout.addWidget(self._editor)

        planning_tab = build_planning_tab(self)

        self._editor_tabs.addTab(form_tab, "Structured Form")
        self._editor_tabs.addTab(text_tab, "YAML/JSON")
        self._editor_tabs.addTab(planning_tab, "Planning")
        editor_layout.addWidget(self._editor_tabs)
        splitter.addWidget(editor_container)

        viz_container = QWidget()
        viz_layout = QVBoxLayout(viz_container)

        gantt_panel = QWidget()
        gantt_panel_layout = QVBoxLayout(gantt_panel)
        gantt_panel_layout.addWidget(self._plot, stretch=1)

        legend_toolbar = QHBoxLayout()
        legend_toolbar.addWidget(QLabel("Legend"))
        legend_toolbar.addWidget(self._legend_toggle_subtask)
        legend_toolbar.addWidget(self._legend_toggle_segment)
        legend_toolbar.addStretch(1)
        gantt_panel_layout.addLayout(legend_toolbar)
        gantt_panel_layout.addWidget(self._legend_detail)
        gantt_panel_layout.addWidget(self._hover_hint)

        telemetry_panel = QWidget()
        telemetry_layout = QVBoxLayout(telemetry_panel)
        telemetry_layout.addWidget(QLabel("Metrics / Logs"))
        telemetry_layout.addWidget(self._metrics, stretch=2)
        telemetry_layout.addWidget(self._state_legend)
        telemetry_layout.addWidget(self._state_view, stretch=1)
        telemetry_layout.addWidget(QLabel("Segment Details (Hover/Click lock)"))
        telemetry_layout.addWidget(self._details, stretch=2)
        telemetry_layout.addWidget(self._compare_toggle_button)

        self._compare_group = build_compare_group(self)
        self._compare_group.setVisible(False)
        telemetry_layout.addWidget(self._compare_group)

        self._telemetry_scroll = QScrollArea()
        self._telemetry_scroll.setWidgetResizable(True)
        self._telemetry_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._telemetry_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._telemetry_scroll.setWidget(telemetry_panel)

        self._right_splitter = QSplitter(Qt.Orientation.Vertical)
        self._right_splitter.addWidget(gantt_panel)
        self._right_splitter.addWidget(self._telemetry_scroll)
        self._right_splitter.setCollapsible(0, False)
        self._right_splitter.setCollapsible(1, False)
        self._right_splitter.setStretchFactor(0, 3)
        self._right_splitter.setStretchFactor(1, 2)
        self._right_splitter.setSizes([520, 300])
        viz_layout.addWidget(self._right_splitter)

        splitter.addWidget(viz_container)
        splitter.setSizes([560, 940])

        root_layout.addWidget(splitter)
        self.setCentralWidget(root)
        self._set_worker_controls(running=False, paused=False)

    def _connect_signals(self) -> None:
        self._load_button.clicked.connect(self._pick_load_file)
        self._save_button.clicked.connect(self._pick_save_file)
        self._validate_button.clicked.connect(self._on_validate)
        self._run_button.clicked.connect(self._on_run)
        self._stop_button.clicked.connect(self._on_stop)
        self._pause_button.clicked.connect(self._on_pause)
        self._resume_button.clicked.connect(self._on_resume)
        self._step_button.clicked.connect(self._on_step)
        self._reset_button.clicked.connect(self._on_reset)
        self._research_export_button.clicked.connect(self._on_research_export)
        self._sync_text_to_form_button.clicked.connect(self._on_sync_text_to_form)
        self._sync_form_to_text_button.clicked.connect(self._on_sync_form_to_text)
        self._legend_toggle_subtask.toggled.connect(self._refresh_legend_details)
        self._legend_toggle_segment.toggled.connect(self._refresh_legend_details)
        self._task_add_button.clicked.connect(self._on_add_task)
        self._task_remove_button.clicked.connect(self._on_remove_task)
        self._resource_add_button.clicked.connect(self._on_add_resource)
        self._resource_remove_button.clicked.connect(self._on_remove_resource)
        self._task_table.itemSelectionChanged.connect(self._on_task_selection_changed)
        self._resource_table.itemSelectionChanged.connect(self._on_resource_selection_changed)
        self._task_table.cellChanged.connect(self._on_task_table_cell_changed)
        self._resource_table.cellChanged.connect(self._on_resource_table_cell_changed)
        self._dag_subtasks_list.itemSelectionChanged.connect(self._on_dag_subtask_selected)
        self._dag_add_subtask_button.clicked.connect(self._on_dag_add_subtask)
        self._dag_remove_subtask_button.clicked.connect(self._on_dag_remove_subtask)
        self._dag_add_edge_button.clicked.connect(self._on_dag_add_edge)
        self._dag_remove_edge_button.clicked.connect(self._on_dag_remove_edge)
        self._dag_auto_layout_button.clicked.connect(self._on_dag_auto_layout)
        self._dag_persist_layout.toggled.connect(self._on_dag_persist_layout_toggled)
        self._dag_canvas_tabs.currentChanged.connect(self._on_dag_canvas_tab_changed)
        self._compare_toggle_button.toggled.connect(self._on_compare_toggle)
        self._compare_add_metrics_button.clicked.connect(self._on_compare_add_metrics)
        self._compare_add_latest_button.clicked.connect(self._on_compare_add_latest)
        self._compare_remove_selected_button.clicked.connect(self._on_compare_remove_selected)
        self._compare_move_up_button.clicked.connect(self._on_compare_move_up)
        self._compare_move_down_button.clicked.connect(self._on_compare_move_down)
        self._compare_load_left_button.clicked.connect(self._on_compare_load_left)
        self._compare_load_right_button.clicked.connect(self._on_compare_load_right)
        self._compare_use_latest_left_button.clicked.connect(self._on_compare_use_latest_left)
        self._compare_use_latest_right_button.clicked.connect(self._on_compare_use_latest_right)
        self._compare_build_button.clicked.connect(self._on_compare_build)
        self._compare_export_json_button.clicked.connect(self._on_compare_export_json)
        self._compare_export_csv_button.clicked.connect(self._on_compare_export_csv)
        self._compare_export_markdown_button.clicked.connect(self._on_compare_export_markdown)
        self._planning_plan_button.clicked.connect(self._on_plan_static)
        self._planning_wcrt_button.clicked.connect(self._on_plan_analyze_wcrt)
        self._planning_export_button.clicked.connect(self._on_plan_export_os_config)
        self._planning_random_generate_button.clicked.connect(self._on_plan_generate_random_tasks)

        self._editor.textChanged.connect(self._on_text_edited)
        self._register_form_change_signals()

        scene = self._plot.scene()
        scene.sigMouseMoved.connect(self._on_plot_mouse_moved)
        scene.sigMouseClicked.connect(self._on_plot_mouse_clicked)

    def _register_form_change_signals(self) -> None:
        line_edits = [
            self._form_processor_id,
            self._form_processor_name,
            self._form_core_id,
            self._form_resource_id,
            self._form_resource_name,
            self._form_resource_bound_core,
            self._form_task_id,
            self._form_task_name,
            self._form_task_period,
            self._form_task_deadline,
            self._form_subtask_id,
            self._form_segment_id,
            self._form_segment_mapping_hint,
            self._form_segment_required_resources,
        ]
        for widget in line_edits:
            widget.textChanged.connect(self._mark_form_dirty)

        combo_boxes = [
            self._form_resource_protocol,
            self._form_task_type,
            self._form_scheduler_name,
            self._form_tie_breaker,
            self._form_event_id_mode,
            self._form_resource_acquire_policy,
            self._planning_planner,
            self._planning_lp_objective,
            self._planning_task_scope,
            self._planning_random_load_tier,
            self._planning_random_rule,
        ]
        for widget in combo_boxes:
            widget.currentIndexChanged.connect(self._mark_form_dirty)

        check_boxes = [
            self._form_resource_enabled,
            self._form_task_abort_on_miss,
            self._form_segment_preemptible,
            self._form_allow_preempt,
            self._planning_enabled,
            self._planning_include_non_rt,
        ]
        for widget in check_boxes:
            widget.toggled.connect(self._mark_form_dirty)

        spins = [
            self._form_processor_core_count,
            self._form_processor_speed,
            self._form_core_speed,
            self._form_task_arrival,
            self._form_segment_wcet,
            self._form_sim_duration,
            self._form_sim_seed,
            self._planning_horizon,
            self._planning_time_limit,
            self._planning_wcrt_max_iterations,
            self._planning_wcrt_epsilon,
            self._planning_random_seed,
            self._planning_random_task_count,
        ]
        for widget in spins:
            widget.valueChanged.connect(self._mark_form_dirty)

    def _on_text_edited(self) -> None:
        if self._suspend_text_events:
            return
        self._config_doc = None
        self._dag_manual_positions_by_task.clear()
        self._invalidate_planning_cache()
        if self._editor_tabs.currentIndex() == 1:
            self._form_hint.setText("Text changed. Use 'Sync Text -> Form' to refresh form.")

    def _invalidate_planning_cache(self) -> None:
        self._latest_plan_result = None
        self._latest_plan_payload = None
        self._latest_plan_spec_fingerprint = None
        self._latest_plan_semantic_fingerprint = None
        self._latest_planning_wcrt_report = None
        self._latest_planning_os_payload = None

    def _mark_form_dirty(self, *args: Any) -> None:  # noqa: ARG002
        if self._suspend_form_events:
            return
        self._form_dirty = True
        self._form_hint.setText("Form changed. Use 'Apply Form -> Text' before run/save.")

    def _on_sync_text_to_form(self) -> None:
        self._form_controller.on_sync_text_to_form()

    def _on_sync_form_to_text(self) -> None:
        self._form_controller.on_sync_form_to_text()

    def _sync_form_to_text_if_dirty(self) -> bool:
        return self._form_controller.sync_form_to_text_if_dirty()

    def _sync_text_to_form(self, *, show_message: bool) -> bool:
        return self._form_controller.sync_text_to_form(show_message=show_message)

    def _sync_form_to_text(self, *, show_message: bool) -> bool:
        return self._form_controller.sync_form_to_text(show_message=show_message)

    def _read_editor_payload(self) -> dict[str, Any]:
        text = self._editor.toPlainText()
        payload = yaml.safe_load(text)
        if not isinstance(payload, dict):
            raise ConfigError("config root must be object")
        return payload

    def _populate_form_from_payload(self, payload: dict[str, Any]) -> None:
        self._dag_manual_positions_by_task.clear()
        self._config_doc = ConfigDocument.from_payload(payload)
        self._populate_form_from_doc()

    def _populate_form_from_doc(self) -> None:
        doc = self._ensure_config_doc()

        tasks = doc.list_tasks()
        resources = doc.list_resources()
        task_count = len(tasks)
        resource_count = len(resources)

        if task_count <= 0:
            self._selected_task_index = -1
        else:
            self._selected_task_index = min(max(self._selected_task_index, 0), task_count - 1)

        if resource_count <= 0:
            self._selected_resource_index = -1
        else:
            self._selected_resource_index = min(max(self._selected_resource_index, 0), resource_count - 1)

        processor = doc.get_primary_processor()
        core = doc.get_primary_core()
        scheduler = doc.get_scheduler()
        scheduler_params = scheduler.get("params")
        params = scheduler_params if isinstance(scheduler_params, dict) else {}
        planning = doc.get_planning()
        sim = doc.get_sim()

        self._suspend_form_events = True
        try:
            self._form_processor_id.setText(str(processor.get("id", "CPU")))
            self._form_processor_name.setText(str(processor.get("name", "cpu")))
            self._form_processor_core_count.setValue(max(1, int(safe_float(processor.get("core_count"), 1))))
            self._form_processor_speed.setValue(safe_float(processor.get("speed_factor"), 1.0))

            self._form_core_id.setText(str(core.get("id", "c0")))
            self._form_core_speed.setValue(safe_float(core.get("speed_factor"), 1.0))

            self._refresh_resource_table(doc)
            self._refresh_task_table(doc)
            self._refresh_selected_resource_fields(doc)
            self._refresh_selected_task_fields(doc)

            self._set_combo_value(self._form_scheduler_name, str(scheduler.get("name", "edf")))
            self._set_combo_value(self._form_tie_breaker, str(params.get("tie_breaker", "fifo")))
            self._form_allow_preempt.setChecked(self._to_bool(params.get("allow_preempt"), True))
            self._set_combo_value(self._form_event_id_mode, str(params.get("event_id_mode", "deterministic")))
            self._set_combo_value(
                self._form_resource_acquire_policy,
                str(params.get("resource_acquire_policy", "legacy_sequential")),
            )
            self._form_sim_duration.setValue(safe_float(sim.get("duration"), 10.0))
            self._form_sim_seed.setValue(int(safe_float(sim.get("seed"), 42)))

            self._planning_enabled.setChecked(self._to_bool(planning.get("enabled"), False))
            self._set_combo_value(self._planning_planner, str(planning.get("planner", "np_edf")))
            self._set_combo_value(
                self._planning_lp_objective,
                str(planning.get("lp_objective", "response_time")),
            )
            self._set_combo_value(
                self._planning_task_scope,
                str(planning.get("task_scope", "sync_only")),
            )
            self._planning_include_non_rt.setChecked(self._to_bool(planning.get("include_non_rt"), False))
            self._planning_horizon.setValue(safe_float(planning.get("horizon"), 0.0))
        finally:
            self._suspend_form_events = False

        self._refresh_dag_widgets(doc)

    def _ensure_config_doc(self) -> ConfigDocument:
        if self._config_doc is not None:
            return self._config_doc
        try:
            payload = self._read_editor_payload()
        except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
            _log_ui_error("ensure_config_doc_fallback", exc)
            payload = {}
        self._config_doc = ConfigDocument.from_payload(payload)
        return self._config_doc

    def _refresh_task_table(self, doc: ConfigDocument) -> None:
        tasks = doc.list_tasks()
        table = self._task_table
        table.blockSignals(True)
        try:
            table.setRowCount(len(tasks))
            for view in tasks:
                task = view.task
                row = view.index
                self._set_table_item(table, row, 0, str(task.get("id", "")))
                self._set_table_item(table, row, 1, str(task.get("name", "")))
                self._set_table_item(table, row, 2, str(task.get("task_type", "")))
                self._set_table_item(
                    table,
                    row,
                    3,
                    self._stringify_optional_number(task.get("arrival")),
                )
                self._set_table_item(
                    table,
                    row,
                    4,
                    self._stringify_optional_number(task.get("deadline")),
                )
            if 0 <= self._selected_task_index < len(tasks):
                table.selectRow(self._selected_task_index)
            else:
                table.clearSelection()
        finally:
            table.blockSignals(False)
        self._task_remove_button.setEnabled(len(tasks) > 0)
        self._validate_task_table()

    def _refresh_resource_table(self, doc: ConfigDocument) -> None:
        resources = doc.list_resources()
        table = self._resource_table
        table.blockSignals(True)
        try:
            table.setRowCount(len(resources))
            for view in resources:
                resource = view.resource
                row = view.index
                self._set_table_item(table, row, 0, str(resource.get("id", "")))
                self._set_table_item(table, row, 1, str(resource.get("name", "")))
                self._set_table_item(table, row, 2, str(resource.get("bound_core_id", "")))
                self._set_table_item(table, row, 3, str(resource.get("protocol", "")))
            if 0 <= self._selected_resource_index < len(resources):
                table.selectRow(self._selected_resource_index)
            else:
                table.clearSelection()
        finally:
            table.blockSignals(False)
        self._resource_remove_button.setEnabled(len(resources) > 0)
        self._validate_resource_table()

    def _refresh_selected_resource_fields(self, doc: ConfigDocument) -> None:
        resources = doc.list_resources()
        selected: dict[str, Any] = {}
        if resources:
            if self._selected_resource_index < 0:
                self._selected_resource_index = 0
            self._selected_resource_index = min(self._selected_resource_index, len(resources) - 1)
            selected = doc.get_resource(self._selected_resource_index)

        self._form_resource_enabled.setChecked(bool(resources))
        self._form_resource_id.setText(str(selected.get("id", "r0")))
        self._form_resource_name.setText(str(selected.get("name", "lock")))
        self._form_resource_bound_core.setText(str(selected.get("bound_core_id", self._form_core_id.text())))
        self._set_combo_value(self._form_resource_protocol, str(selected.get("protocol", "mutex")))

    def _refresh_selected_task_fields(self, doc: ConfigDocument) -> None:
        tasks = doc.list_tasks()
        if tasks:
            if self._selected_task_index < 0:
                self._selected_task_index = 0
            self._selected_task_index = min(self._selected_task_index, len(tasks) - 1)
            task = doc.get_task(self._selected_task_index)
        else:
            task = {}

        self._form_task_id.setText(str(task.get("id", "t0")))
        self._form_task_name.setText(str(task.get("name", "task")))
        self._set_combo_value(self._form_task_type, str(task.get("task_type", "dynamic_rt")))
        self._form_task_arrival.setValue(safe_float(task.get("arrival"), 0.0))
        self._form_task_period.setText(self._stringify_optional_number(task.get("period")))
        self._form_task_deadline.setText(self._stringify_optional_number(task.get("deadline")))
        self._form_task_abort_on_miss.setChecked(bool(task.get("abort_on_miss", False)))

        subtask = {}
        segment = {}
        if tasks and self._selected_task_index >= 0:
            subtasks = doc.list_subtasks(self._selected_task_index)
            if subtasks:
                by_id = {
                    str(item.get("id") or ""): (idx, item)
                    for idx, item in enumerate(subtasks)
                    if isinstance(item, dict)
                }
                lookup = by_id.get(self._selected_subtask_id)
                if lookup is None:
                    idx = 0
                    subtask = subtasks[idx]
                    self._selected_subtask_id = str(subtask.get("id") or "s0")
                else:
                    idx, subtask = lookup
                segment = doc.get_segment(self._selected_task_index, idx, 0)
            else:
                self._selected_subtask_id = "s0"
        else:
            self._selected_subtask_id = "s0"

        self._form_subtask_id.setText(str(subtask.get("id", "s0")))
        self._form_segment_id.setText(str(segment.get("id", "seg0")))
        self._form_segment_wcet.setValue(safe_float(segment.get("wcet"), 1.0))
        mapping_hint = segment.get("mapping_hint")
        self._form_segment_mapping_hint.setText("" if mapping_hint is None else str(mapping_hint))
        required_resources = segment.get("required_resources")
        if isinstance(required_resources, list):
            self._form_segment_required_resources.setText(",".join(str(item) for item in required_resources))
        else:
            self._form_segment_required_resources.setText("")
        self._form_segment_preemptible.setChecked(bool(segment.get("preemptible", True)))

    def _refresh_dag_widgets(self, doc: ConfigDocument) -> None:
        self._dag_controller.refresh_dag_widgets(doc)

    def _current_task_layout_key(self, doc: ConfigDocument) -> str:
        tasks = doc.list_tasks()
        if not tasks or self._selected_task_index < 0:
            return ""
        self._selected_task_index = min(self._selected_task_index, len(tasks) - 1)
        task = doc.get_task(self._selected_task_index)
        task_id = str(task.get("id") or "").strip()
        if task_id:
            return task_id
        return f"task_{self._selected_task_index}"

    def _resolve_dag_positions(
        self,
        doc: ConfigDocument,
        layout_key: str,
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
    ) -> dict[str, QPointF]:
        return self._dag_controller.resolve_dag_positions(doc, layout_key, subtask_ids, edges)

    @staticmethod
    def _compute_auto_layout_positions(
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
    ) -> dict[str, QPointF]:
        return DagController.compute_auto_layout_positions(subtask_ids, edges)

    def _render_dag_scene(
        self,
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
        *,
        positions: dict[str, QPointF],
    ) -> None:
        self._dag_controller.render_dag_scene(subtask_ids, edges, positions=positions)

    def _start_dag_link_drag(self, src_id: str, scene_pos: QPointF) -> None:
        self._dag_controller.start_dag_link_drag(src_id, scene_pos)

    def _update_dag_link_drag(self, scene_pos: QPointF) -> None:
        self._dag_controller.update_dag_link_drag(scene_pos)

    def _finish_dag_link_drag(self, scene_pos: QPointF) -> None:
        self._dag_controller.finish_dag_link_drag(scene_pos)

    def _clear_dag_drag_preview(self) -> None:
        self._dag_controller.clear_dag_drag_preview()

    def _dag_node_id_from_scene_pos(self, scene_pos: QPointF) -> str | None:
        return self._dag_controller.dag_node_id_from_scene_pos(scene_pos)

    def _dag_scene_pos_for_subtask(self, subtask_id: str) -> QPointF | None:
        return self._dag_controller.dag_scene_pos_for_subtask(subtask_id)

    def _on_dag_node_clicked(
        self,
        subtask_id: str,
        *,
        toggle: bool = False,
        preserve_existing: bool = False,
    ) -> None:
        self._dag_controller.on_dag_node_clicked(
            subtask_id,
            toggle=toggle,
            preserve_existing=preserve_existing,
        )

    def _refresh_dag_node_selection_visuals(self) -> None:
        self._dag_controller.refresh_dag_node_selection_visuals()

    def _on_dag_node_moved(self, subtask_id: str, center: QPointF) -> None:
        self._dag_controller.on_dag_node_moved(subtask_id, center)

    def _on_dag_node_drag_finished(self, subtask_id: str) -> None:
        self._dag_controller.on_dag_node_drag_finished(subtask_id)

    def _update_dag_edges_for_node(self, subtask_id: str) -> None:
        self._dag_controller.update_dag_edges_for_node(subtask_id)

    def _persist_current_dag_layout_to_doc(self) -> None:
        self._dag_controller.persist_current_dag_layout_to_doc()

    def _refresh_dag_overview_canvas(self, entry: DagOverviewCanvasEntry | None) -> None:
        self._dag_overview_controller.refresh_overview_canvas(entry)

    def _on_dag_canvas_tab_changed(self, index: int) -> None:
        self._dag_overview_controller.on_canvas_tab_changed(index)

    def _open_dag_overview_canvas(self) -> None:
        self._dag_overview_controller.show_overview_canvas()

    def _open_dag_overview_task_detail(self, task_ref: int | str) -> bool:
        return self._dag_overview_controller.open_task_detail(task_ref)

    def _on_dag_auto_layout(self) -> None:
        self._dag_controller.on_dag_auto_layout()

    def _on_dag_persist_layout_toggled(self, checked: bool) -> None:
        self._dag_controller.on_dag_persist_layout_toggled(checked)

    def _try_add_dag_edge(self, src_id: str, dst_id: str, *, show_feedback: bool) -> bool:
        return self._dag_controller.try_add_dag_edge(src_id, dst_id, show_feedback=show_feedback)

    @staticmethod
    def _would_create_cycle(doc: ConfigDocument, task_index: int, src_id: str, dst_id: str) -> bool:
        return DagController.would_create_cycle(doc, task_index, src_id, dst_id)

    def _apply_form_to_payload(self, base_payload: dict[str, Any]) -> dict[str, Any]:
        doc = ConfigDocument.from_payload(base_payload)
        self._apply_form_to_document(doc)
        self._config_doc = doc
        return doc.to_payload()

    def _apply_form_to_document(self, doc: ConfigDocument) -> None:
        processor_id = self._form_processor_id.text().strip() or "CPU"
        core_id = self._form_core_id.text().strip() or "c0"

        doc.patch_primary_processor(
            {
                "id": processor_id,
                "name": self._form_processor_name.text().strip() or "cpu",
                "core_count": int(self._form_processor_core_count.value()),
                "speed_factor": float(self._form_processor_speed.value()),
            }
        )
        doc.patch_primary_core(
            {
                "id": core_id,
                "type_id": processor_id,
                "speed_factor": float(self._form_core_speed.value()),
            }
        )

        resources = doc.list_resources()
        if self._form_resource_enabled.isChecked():
            if not resources:
                self._selected_resource_index = doc.add_resource()
            elif self._selected_resource_index < 0:
                self._selected_resource_index = 0
            if doc.list_resources():
                self._selected_resource_index = min(
                    self._selected_resource_index,
                    len(doc.list_resources()) - 1,
                )
                doc.patch_resource(
                    self._selected_resource_index,
                    {
                        "id": self._form_resource_id.text().strip() or "r0",
                        "name": self._form_resource_name.text().strip() or "lock",
                        "bound_core_id": self._form_resource_bound_core.text().strip() or core_id,
                        "protocol": self._form_resource_protocol.currentText().strip() or "mutex",
                    },
                )
        else:
            for idx in range(len(resources) - 1, -1, -1):
                doc.remove_resource(idx)
            self._selected_resource_index = -1

        tasks = doc.list_tasks()
        if not tasks:
            self._selected_task_index = doc.add_task()
            tasks = doc.list_tasks()
        if self._selected_task_index < 0:
            self._selected_task_index = 0
        self._selected_task_index = min(self._selected_task_index, len(tasks) - 1)

        task_type = self._form_task_type.currentText().strip() or "dynamic_rt"
        period_value = self._parse_optional_float(self._form_task_period.text(), "task.period")
        deadline_value = self._parse_optional_float(self._form_task_deadline.text(), "task.deadline")
        if task_type == "time_deterministic":
            if period_value is None:
                period_value = 10.0
            if deadline_value is None:
                deadline_value = period_value
        elif task_type != "non_rt" and deadline_value is None:
            deadline_value = 10.0

        doc.patch_task(
            self._selected_task_index,
            {
                "id": self._form_task_id.text().strip() or "t0",
                "name": self._form_task_name.text().strip() or "task",
                "task_type": task_type,
                "arrival": float(self._form_task_arrival.value()),
                "period": period_value,
                "deadline": deadline_value,
                "abort_on_miss": bool(self._form_task_abort_on_miss.isChecked()),
            },
        )

        subtasks = doc.list_subtasks(self._selected_task_index)
        selected_subtask_index = 0
        if subtasks:
            selected_subtask_index = 0
            for idx, subtask in enumerate(subtasks):
                if str(subtask.get("id") or "") == self._selected_subtask_id:
                    selected_subtask_index = idx
                    break
        else:
            selected_subtask_index = doc.add_subtask(self._selected_task_index)

        doc.patch_subtask(
            self._selected_task_index,
            selected_subtask_index,
            {"id": self._form_subtask_id.text().strip() or "s0"},
        )
        selected_subtask = doc.get_subtask(self._selected_task_index, selected_subtask_index)
        self._selected_subtask_id = str(selected_subtask.get("id") or "s0")

        required_resources = [
            token.strip()
            for token in self._form_segment_required_resources.text().split(",")
            if token.strip()
        ]
        mapping_hint = self._form_segment_mapping_hint.text().strip()
        doc.patch_segment(
            self._selected_task_index,
            selected_subtask_index,
            {
                "id": self._form_segment_id.text().strip() or "seg0",
                "index": 1,
                "wcet": float(self._form_segment_wcet.value()),
                "mapping_hint": mapping_hint or None,
                "required_resources": required_resources,
                "preemptible": bool(self._form_segment_preemptible.isChecked()),
            },
        )

        doc.patch_scheduler(
            self._form_scheduler_name.currentText().strip() or "edf",
            {
                "tie_breaker": self._form_tie_breaker.currentText().strip() or "fifo",
                "allow_preempt": bool(self._form_allow_preempt.isChecked()),
                "event_id_mode": self._form_event_id_mode.currentText().strip() or "deterministic",
                "resource_acquire_policy": self._form_resource_acquire_policy.currentText().strip()
                or "legacy_sequential",
            },
        )
        doc.patch_sim(float(self._form_sim_duration.value()), int(self._form_sim_seed.value()))
        planning_horizon = float(self._planning_horizon.value())
        doc.patch_planning(
            {
                "enabled": bool(self._planning_enabled.isChecked()),
                "planner": self._planning_planner.currentText().strip() or "np_edf",
                "lp_objective": self._planning_lp_objective.currentText().strip() or "response_time",
                "task_scope": self._planning_task_scope.currentText().strip() or "sync_only",
                "include_non_rt": bool(self._planning_include_non_rt.isChecked()),
                "horizon": None if planning_horizon <= 1e-12 else planning_horizon,
            }
        )

    @staticmethod
    def _set_table_item(table: QTableWidget, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        table.setItem(row, col, item)

    @staticmethod
    def _table_cell_text(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text().strip() if item is not None else ""

    def _clear_table_error_bucket(self, table_key: str) -> None:
        for key in list(self._table_validation_errors):
            if key[0] == table_key:
                self._table_validation_errors.pop(key, None)

    def _set_table_cell_error(
        self,
        *,
        table_key: str,
        table: QTableWidget,
        row: int,
        col: int,
        error: str | None,
    ) -> None:
        item = table.item(row, col)
        if item is None:
            item = QTableWidgetItem("")
            table.setItem(row, col, item)

        key = (table_key, row, col)
        if error:
            self._table_validation_errors[key] = error
            item.setData(Qt.ItemDataRole.BackgroundRole, QColor("#6f2f2f"))
            item.setData(Qt.ItemDataRole.ForegroundRole, QColor("#ffecec"))
            item.setToolTip(error)
        else:
            self._table_validation_errors.pop(key, None)
            item.setData(Qt.ItemDataRole.BackgroundRole, None)
            item.setData(Qt.ItemDataRole.ForegroundRole, None)
            item.setToolTip("")

    def _validate_task_table(self) -> None:
        table = self._task_table
        row_count = table.rowCount()
        rows = [
            {
                "id": self._table_cell_text(table, row, 0),
                "name": self._table_cell_text(table, row, 1),
                "task_type": self._table_cell_text(table, row, 2),
                "arrival": self._table_cell_text(table, row, 3),
                "deadline": self._table_cell_text(table, row, 4),
            }
            for row in range(row_count)
        ]
        errors = build_task_table_errors(rows=rows, valid_task_types=self._TASK_TYPE_OPTIONS)

        self._clear_table_error_bucket("task")
        table.blockSignals(True)
        try:
            for row in range(row_count):
                self._set_table_cell_error(
                    table_key="task",
                    table=table,
                    row=row,
                    col=0,
                    error=errors.get((row, 0)),
                )

                self._set_table_cell_error(
                    table_key="task",
                    table=table,
                    row=row,
                    col=1,
                    error=errors.get((row, 1)),
                )

                self._set_table_cell_error(
                    table_key="task",
                    table=table,
                    row=row,
                    col=2,
                    error=errors.get((row, 2)),
                )

                self._set_table_cell_error(
                    table_key="task",
                    table=table,
                    row=row,
                    col=3,
                    error=errors.get((row, 3)),
                )

                self._set_table_cell_error(
                    table_key="task",
                    table=table,
                    row=row,
                    col=4,
                    error=errors.get((row, 4)),
                )
        finally:
            table.blockSignals(False)

    def _validate_resource_table(self) -> None:
        table = self._resource_table
        row_count = table.rowCount()
        rows = [
            {
                "id": self._table_cell_text(table, row, 0),
                "name": self._table_cell_text(table, row, 1),
                "bound_core_id": self._table_cell_text(table, row, 2),
                "protocol": self._table_cell_text(table, row, 3),
            }
            for row in range(row_count)
        ]
        errors = build_resource_table_errors(rows=rows, valid_protocols=self._RESOURCE_PROTOCOL_OPTIONS)

        self._clear_table_error_bucket("resource")
        table.blockSignals(True)
        try:
            for row in range(row_count):
                self._set_table_cell_error(
                    table_key="resource",
                    table=table,
                    row=row,
                    col=0,
                    error=errors.get((row, 0)),
                )

                self._set_table_cell_error(
                    table_key="resource",
                    table=table,
                    row=row,
                    col=1,
                    error=errors.get((row, 1)),
                )
                self._set_table_cell_error(
                    table_key="resource",
                    table=table,
                    row=row,
                    col=2,
                    error=errors.get((row, 2)),
                )
                self._set_table_cell_error(
                    table_key="resource",
                    table=table,
                    row=row,
                    col=3,
                    error=errors.get((row, 3)),
                )
        finally:
            table.blockSignals(False)

    def _has_table_validation_errors(self) -> bool:
        return bool(self._table_validation_errors)

    def _first_table_validation_error(self) -> str:
        if not self._table_validation_errors:
            return ""
        key = sorted(self._table_validation_errors.keys())[0]
        table_name = "task_table" if key[0] == "task" else "resource_table"
        row = key[1] + 1
        col = key[2] + 1
        return f"{table_name} row={row} col={col}: {self._table_validation_errors[key]}"

    def _patch_task_row_from_table(self, doc: ConfigDocument, row: int) -> None:
        task_type = self._table_cell_text(self._task_table, row, 2) or "dynamic_rt"
        deadline_text = self._table_cell_text(self._task_table, row, 4)
        deadline = safe_optional_float(deadline_text) if deadline_text else None
        doc.patch_task(
            row,
            {
                "id": self._table_cell_text(self._task_table, row, 0) or f"t{row}",
                "name": self._table_cell_text(self._task_table, row, 1) or "task",
                "task_type": task_type,
                "arrival": float(safe_optional_float(self._table_cell_text(self._task_table, row, 3)) or 0.0),
                "deadline": deadline,
            },
        )

    def _patch_resource_row_from_table(self, doc: ConfigDocument, row: int) -> None:
        doc.patch_resource(
            row,
            {
                "id": self._table_cell_text(self._resource_table, row, 0) or f"r{row}",
                "name": self._table_cell_text(self._resource_table, row, 1) or "lock",
                "bound_core_id": self._table_cell_text(self._resource_table, row, 2) or "c0",
                "protocol": self._table_cell_text(self._resource_table, row, 3) or "mutex",
            },
        )

    def _on_add_task(self) -> None:
        doc = self._ensure_config_doc()
        self._selected_task_index = doc.add_task()
        subtasks = doc.list_subtasks(self._selected_task_index)
        if subtasks:
            self._selected_subtask_id = str(subtasks[0].get("id") or "s0")
        self._populate_form_from_doc()
        self._mark_form_dirty()

    def _on_remove_task(self) -> None:
        doc = self._ensure_config_doc()
        if self._selected_task_index < 0:
            return
        doc.remove_task(self._selected_task_index)
        remaining = len(doc.list_tasks())
        if remaining <= 0:
            self._selected_task_index = -1
            self._selected_subtask_id = "s0"
        else:
            self._selected_task_index = min(self._selected_task_index, remaining - 1)
            subtasks = doc.list_subtasks(self._selected_task_index)
            self._selected_subtask_id = str(subtasks[0].get("id") or "s0") if subtasks else "s0"
        self._populate_form_from_doc()
        self._mark_form_dirty()

    def _on_add_resource(self) -> None:
        doc = self._ensure_config_doc()
        self._selected_resource_index = doc.add_resource()
        self._form_resource_enabled.setChecked(True)
        self._populate_form_from_doc()
        self._mark_form_dirty()

    def _on_remove_resource(self) -> None:
        doc = self._ensure_config_doc()
        if self._selected_resource_index < 0:
            return
        doc.remove_resource(self._selected_resource_index)
        remaining = len(doc.list_resources())
        if remaining <= 0:
            self._selected_resource_index = -1
            self._form_resource_enabled.setChecked(False)
        else:
            self._selected_resource_index = min(self._selected_resource_index, remaining - 1)
        self._populate_form_from_doc()
        self._mark_form_dirty()

    def _on_task_selection_changed(self) -> None:
        if self._suspend_form_events:
            return
        row = self._task_table.currentRow()
        if row < 0:
            self._selected_task_index = -1
            self._selected_subtask_id = "s0"
            self._dag_controller.refresh_dag_widgets(self._ensure_config_doc())
            return
        self._dag_controller.select_task(row, sync_table_selection=False)

    def _on_resource_selection_changed(self) -> None:
        if self._suspend_form_events:
            return
        row = self._resource_table.currentRow()
        self._selected_resource_index = row if row >= 0 else -1
        doc = self._ensure_config_doc()
        self._suspend_form_events = True
        try:
            self._refresh_selected_resource_fields(doc)
        finally:
            self._suspend_form_events = False

    def _on_task_table_cell_changed(self, row: int, col: int) -> None:
        if self._suspend_form_events:
            return
        doc = self._ensure_config_doc()
        if row < 0 or row >= len(doc.list_tasks()):
            return
        if col < 0 or col > 4:
            return

        self._validate_task_table()
        if self._has_table_validation_errors():
            self._mark_form_dirty()
            self._form_hint.setText("Task table has validation errors. Fix highlighted cells before apply.")
            return

        self._patch_task_row_from_table(doc, row)
        self._selected_task_index = row
        self._populate_form_from_doc()
        self._mark_form_dirty()

    def _on_resource_table_cell_changed(self, row: int, col: int) -> None:
        if self._suspend_form_events:
            return
        doc = self._ensure_config_doc()
        if row < 0 or row >= len(doc.list_resources()):
            return
        if col < 0 or col > 3:
            return

        self._validate_resource_table()
        if self._has_table_validation_errors():
            self._mark_form_dirty()
            self._form_hint.setText("Resource table has validation errors. Fix highlighted cells before apply.")
            return

        self._patch_resource_row_from_table(doc, row)
        self._selected_resource_index = row
        self._populate_form_from_doc()
        self._mark_form_dirty()

    def _on_dag_subtask_selected(self) -> None:
        self._dag_controller.on_dag_subtask_selected()

    def _on_dag_add_subtask(self) -> None:
        self._dag_controller.on_dag_add_subtask()

    def _on_dag_remove_subtask(self) -> None:
        self._dag_controller.on_dag_remove_subtask()

    def _on_dag_add_edge(self) -> None:
        self._dag_controller.on_dag_add_edge()

    def _on_dag_remove_edge(self) -> None:
        self._dag_controller.on_dag_remove_edge()

    def _get_dag_multi_select_state(self) -> DagMultiSelectState:
        return self._dag_controller.get_multi_select_state()

    def _open_dag_batch_operation(
        self,
        action_id: str,
        *,
        selected_subtask_ids: list[str] | tuple[str, ...] | None = None,
    ) -> DagBatchOperationEntry | None:
        return self._dag_controller.open_batch_operation(
            action_id,
            selected_subtask_ids=selected_subtask_ids,
        )

    def _get_dag_overview_canvas_entry(self) -> DagOverviewCanvasEntry | None:
        return self._dag_controller.get_overview_canvas_entry()

    @staticmethod
    def _parse_optional_float(raw: str, field_name: str) -> float | None:
        text = raw.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError as exc:  # pragma: no cover - UI guard
            raise ConfigError(f"{field_name} must be number") from exc

    @staticmethod
    def _stringify_optional_number(value: Any) -> str:
        if value is None:
            return ""
        try:
            return str(float(value)).rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _to_bool(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default

    @staticmethod
    def _set_combo_value(widget: QComboBox, value: str) -> None:
        idx = widget.findText(value)
        if idx >= 0:
            widget.setCurrentIndex(idx)

    def _pick_load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open config",
            str(Path.cwd()),
            "Config Files (*.yaml *.yml *.json)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str) -> None:
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            self._status_label.setText("Load failed")
            return
        self._suspend_text_events = True
        try:
            self._editor.setPlainText(content)
        finally:
            self._suspend_text_events = False
        self._config_doc = None
        self._invalidate_planning_cache()
        if self._sync_text_to_form(show_message=False):
            self._status_label.setText(f"Loaded: {path}")
            return
        self._status_label.setText(f"Loaded text only: {path}")

    def _pick_save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save config",
            str(Path.cwd() / "config.yaml"),
            "Config Files (*.yaml *.yml *.json)",
        )
        if not path:
            return
        if not self._sync_form_to_text_if_dirty():
            return
        payload = self._read_editor_payload()
        if Path(path).suffix.lower() == ".json":
            content = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            content = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        try:
            Path(path).write_text(content, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            self._status_label.setText("Save failed")
            return
        self._status_label.setText(f"Saved: {path}")

    def _pick_metrics_file(self) -> str | None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open metrics json",
            str(Path.cwd()),
            "JSON Files (*.json)",
        )
        return path or None

    def _on_compare_toggle(self, checked: bool) -> None:
        self._compare_controller.on_compare_toggle(checked)

    def _on_compare_add_metrics(self) -> None:
        self._compare_controller.on_compare_add_metrics()

    def _on_compare_add_latest(self) -> None:
        self._compare_controller.on_compare_add_latest()

    def _on_compare_remove_selected(self) -> None:
        self._compare_controller.on_compare_remove_selected()

    def _on_compare_move_up(self) -> None:
        self._compare_controller.on_compare_move_selected_up()

    def _on_compare_move_down(self) -> None:
        self._compare_controller.on_compare_move_selected_down()

    def _rebalance_right_splitter(self, *, compare_open: bool) -> None:
        self._compare_controller.rebalance_right_splitter(compare_open=compare_open)

    def _ensure_compare_visible(self) -> None:
        self._compare_controller.ensure_compare_visible()

    def _on_compare_load_left(self) -> None:
        self._compare_controller.on_compare_load_left()

    def _on_compare_load_right(self) -> None:
        self._compare_controller.on_compare_load_right()

    def _on_compare_use_latest_left(self) -> None:
        self._compare_controller.on_compare_use_latest_left()

    def _on_compare_use_latest_right(self) -> None:
        self._compare_controller.on_compare_use_latest_right()

    def _on_compare_build(self) -> None:
        self._compare_controller.on_compare_build()

    def _on_compare_export_json(self) -> None:
        self._compare_controller.on_compare_export_json()

    def _on_compare_export_csv(self) -> None:
        self._compare_controller.on_compare_export_csv()

    def _on_compare_export_markdown(self) -> None:
        self._compare_controller.on_compare_export_markdown()

    def _on_plan_static(self) -> None:
        self._planning_controller.on_plan_static()

    def _on_plan_analyze_wcrt(self) -> None:
        self._planning_controller.on_plan_analyze_wcrt()

    def _on_plan_export_os_config(self) -> None:
        self._planning_controller.on_plan_export_os_config()

    def _on_plan_generate_random_tasks(self) -> None:
        self._planning_controller.on_generate_random_tasks()

    def _append_state_transition(self, *, event_time: float, state: str, label: str) -> None:
        self._telemetry_controller.append_state_transition(event_time=event_time, state=state, label=label)

    def _set_worker_controls(self, *, running: bool, paused: bool) -> None:
        self._run_controller.set_worker_controls(running=running, paused=paused)

    def _step_delta_value(self) -> float | None:
        return self._run_controller.step_delta_value()

    def _on_validate(self) -> None:
        if not self._sync_form_to_text_if_dirty():
            return
        try:
            payload = self._read_editor_payload()
            spec = self._loader.load_data(payload)
            SimEngine().build(spec)
        except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
            _log_ui_error("validate", exc)
            QMessageBox.critical(self, "Validation failed", str(exc))
            self._status_label.setText("Validation failed")
            return
        self._status_label.setText("Validation passed")
        QMessageBox.information(self, "Validation", "Config validation passed.")

    def _on_run(self) -> None:
        self._run_controller.on_run()

    def _on_stop(self) -> None:
        self._run_controller.on_stop()

    def _on_pause(self) -> None:
        self._run_controller.on_pause()

    def _on_resume(self) -> None:
        self._run_controller.on_resume()

    def _on_step(self) -> None:
        self._run_controller.on_step()

    def _on_reset(self) -> None:
        self._run_controller.on_reset()

    def _on_research_export(self) -> None:
        self._research_report_controller.on_research_export()

    def _on_event_batch(self, events: list[dict[str, Any]]) -> None:
        self._timeline_controller.on_event_batch(events)

    def _consume_event(self, event: dict[str, Any]) -> None:
        self._timeline_controller.consume_event(event)

    def _close_segment(self, segment_key: str, end_event: dict[str, Any], interrupted: bool) -> None:
        self._timeline_controller.close_segment(segment_key, end_event, interrupted)

    def _draw_gantt_segment(self, meta: SegmentVisualMeta) -> None:
        self._timeline_controller.draw_gantt_segment(meta)

    def _draw_preempt_marker(self, event_time: float, core_id: str) -> None:
        self._timeline_controller.draw_preempt_marker(event_time, core_id)

    def _core_lane(self, core_id: str) -> int:
        if core_id not in self._core_to_y:
            self._core_to_y[core_id] = len(self._core_to_y) + 1
            ticks = [(y, core) for core, y in sorted(self._core_to_y.items(), key=lambda item: item[1])]
            self._plot.getAxis("left").setTicks([ticks])
        return self._core_to_y[core_id]

    def _task_color(self, task_id: str) -> QColor:
        return self._gantt_style_controller.task_color(task_id)

    def _subtask_brush_style(self, task_id: str, subtask_id: str) -> Qt.BrushStyle:
        return self._gantt_style_controller.subtask_brush_style(task_id, subtask_id)

    def _segment_pen_style(self, segment_id: str, interrupted: bool) -> Qt.PenStyle:
        return self._gantt_style_controller.segment_pen_style(segment_id, interrupted)

    def _ensure_task_legend(self, task_id: str, color: QColor) -> None:
        self._gantt_style_controller.ensure_task_legend(task_id, color)

    def _on_plot_mouse_moved(self, scene_pos: QPointF) -> None:
        self._telemetry_controller.on_plot_mouse_moved(scene_pos)

    def _on_plot_mouse_clicked(self, event: Any) -> None:
        self._telemetry_controller.on_plot_mouse_clicked(event)

    def _segment_item_from_scene(self, scene_pos: QPointF) -> SegmentBlockItem | None:
        return self._telemetry_controller.segment_item_from_scene(scene_pos)

    def _refresh_legend_details(self) -> None:
        self._telemetry_controller.refresh_legend_details()

    def _format_segment_details(self, meta: SegmentVisualMeta) -> str:
        return format_segment_details(meta)

    def _on_finished(self, report: dict[str, Any], all_events: list[dict[str, Any]]) -> None:
        self._run_controller.on_finished(report, all_events)

    def _on_failed(self, error_message: str) -> None:
        self._run_controller.on_failed(error_message)

    def _reset_viz(self) -> None:
        self._plot.clear()
        plot_item = self._plot.getPlotItem()
        if plot_item.legend is not None:
            plot_item.legend.scene().removeItem(plot_item.legend)
            plot_item.legend = None
        self._plot.addLegend(offset=(10, 10))

        self._core_to_y.clear()
        self._active_segments.clear()
        self._segment_resources.clear()
        self._job_deadlines.clear()

        self._legend_tasks.clear()
        self._legend_samples.clear()
        self._subtask_legend_map.clear()
        self._segment_legend_map.clear()
        self._subtask_style_cache.clear()
        self._segment_style_cache.clear()

        self._segment_items.clear()
        self._segment_labels.clear()
        self._seen_event_ids.clear()

        self._max_time = 0.0
        self._telemetry_controller.reset_panel_state()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._run_controller.teardown_worker(wait_ms=2000):
            self._status_label.setText("Stopping...")
            event.ignore()
            return
        super().closeEvent(event)


def run_ui(config_path: str | None = None) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(config_path=config_path)
    window.show()
    app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rtos-sim-ui")
    parser.add_argument("-c", "--config", default=None, help="initial config path")
    args = parser.parse_args(argv)
    run_ui(args.config)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
