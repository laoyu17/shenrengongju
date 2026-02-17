"""PyQt6 UI app for simulation control and visualization."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import zlib

import pyqtgraph as pg
import yaml
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QCursor, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
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
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from rtos_sim.io import ConfigError, ConfigLoader

from .config_doc import ConfigDocument
from .worker import SimulationWorker


@dataclass(slots=True)
class SegmentVisualMeta:
    task_id: str
    job_id: str
    subtask_id: str
    segment_id: str
    segment_key: str
    core_id: str
    start: float
    end: float
    duration: float
    status: str
    resources: list[str]
    event_id_start: str
    event_id_end: str
    seq_start: int | None
    seq_end: int | None
    correlation_id: str
    deadline: float | None
    lateness_at_end: float | None
    remaining_after_preempt: float | None
    execution_time_est: float | None
    context_overhead: float | None
    migration_overhead: float | None
    estimated_finish: float | None


class SegmentBlockItem(QGraphicsRectItem):
    """Rect block in gantt with hover metadata."""

    def __init__(
        self,
        *,
        meta: SegmentVisualMeta,
        y: float,
        lane_height: float,
        color: QColor,
        brush_style: Qt.BrushStyle,
        pen_style: Qt.PenStyle,
    ) -> None:
        super().__init__(meta.start, y - lane_height / 2.0, max(meta.duration, 1e-6), lane_height)
        self.meta = meta

        brush = QBrush(color)
        brush.setStyle(brush_style)
        self.setBrush(brush)
        self.setPen(pg.mkPen(color="#f0f0f0", width=1.2, style=pen_style))
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.setToolTip(self._build_brief_tooltip())

    def _build_brief_tooltip(self) -> str:
        return (
            f"{self.meta.task_id}/{self.meta.subtask_id}/{self.meta.segment_id}"
            f"\ncore={self.meta.core_id} [{self.meta.start:.3f}, {self.meta.end:.3f}]"
        )


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
        self._owner._on_dag_node_clicked(self.subtask_id)
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
        start_link = event.button() == Qt.MouseButton.RightButton or (
            event.button() == Qt.MouseButton.LeftButton
            and bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        )
        if start_link:
            self._owner._start_dag_link_drag(self.subtask_id, event.scenePos())
            self._link_dragging = True
            self.setCursor(Qt.CursorShape.CrossCursor)
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

        self._hovered_segment_key: str | None = None
        self._locked_segment_key: str | None = None

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
        self._dag_node_centers: dict[str, QPointF] = {}
        self._dag_node_items: dict[str, DagNodeItem] = {}
        self._dag_edge_items: dict[tuple[str, str], QGraphicsLineItem] = {}
        self._dag_manual_positions_by_task: dict[str, dict[str, QPointF]] = {}
        self._dag_drag_source_id: str | None = None
        self._dag_drag_line: QGraphicsLineItem | None = None
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
        self._form_sim_duration = QDoubleSpinBox()
        self._form_sim_duration.setRange(0.001, 1_000_000.0)
        self._form_sim_duration.setDecimals(3)
        self._form_sim_duration.setValue(10.0)
        self._form_sim_seed = QSpinBox()
        self._form_sim_seed.setRange(-2_147_483_648, 2_147_483_647)
        self._form_sim_seed.setValue(42)

        self._validate_button = QPushButton("Validate")
        self._run_button = QPushButton("Run")
        self._stop_button = QPushButton("Stop")
        self._load_button = QPushButton("Load")
        self._save_button = QPushButton("Save")
        self._status_label = QLabel("Ready")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._plot = pg.PlotWidget(title="Gantt (CPU Lanes)")
        self._plot.showGrid(x=True, y=True)
        self._plot.setLabel("bottom", "Time")
        self._plot.setLabel("left", "Core")
        self._plot.addLegend(offset=(10, 10))

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

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(200)

        self._build_layout()
        self._connect_signals()

        if config_path:
            self._load_file(config_path)
        else:
            self._sync_form_to_text(show_message=False)

    def _build_layout(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._load_button)
        toolbar.addWidget(self._save_button)
        toolbar.addWidget(self._validate_button)
        toolbar.addWidget(self._run_button)
        toolbar.addWidget(self._stop_button)
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

        platform_group = QGroupBox("Platform (Basic)")
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

        task_group = QGroupBox("Tasks (Table + DAG Prototype + Selected Detail)")
        task_layout = QVBoxLayout(task_group)
        task_layout.addWidget(self._task_table)
        task_button_row = QHBoxLayout()
        task_button_row.addWidget(self._task_add_button)
        task_button_row.addWidget(self._task_remove_button)
        task_button_row.addStretch(1)
        task_layout.addLayout(task_button_row)

        dag_group = QGroupBox("DAG Prototype (selected task)")
        dag_layout = QHBoxLayout(dag_group)
        dag_layout.addWidget(self._dag_view, stretch=2)
        dag_side = QVBoxLayout()
        dag_actions_row = QHBoxLayout()
        dag_actions_row.addWidget(self._dag_auto_layout_button)
        dag_actions_row.addWidget(self._dag_persist_layout)
        dag_actions_row.addStretch(1)
        dag_side.addLayout(dag_actions_row)
        dag_side.addWidget(QLabel("Subtasks"))
        dag_side.addWidget(self._dag_subtasks_list)
        dag_subtask_add_row = QHBoxLayout()
        dag_subtask_add_row.addWidget(self._dag_new_subtask_id)
        dag_subtask_add_row.addWidget(self._dag_add_subtask_button)
        dag_side.addLayout(dag_subtask_add_row)
        dag_side.addWidget(self._dag_remove_subtask_button)
        dag_side.addWidget(QLabel("Edges"))
        dag_side.addWidget(self._dag_edges_list)
        dag_edge_row = QHBoxLayout()
        dag_edge_row.addWidget(self._dag_edge_src)
        dag_edge_row.addWidget(self._dag_edge_dst)
        dag_side.addLayout(dag_edge_row)
        dag_edge_button_row = QHBoxLayout()
        dag_edge_button_row.addWidget(self._dag_add_edge_button)
        dag_edge_button_row.addWidget(self._dag_remove_edge_button)
        dag_side.addLayout(dag_edge_button_row)
        dag_layout.addLayout(dag_side, stretch=1)
        task_layout.addWidget(dag_group)

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

        self._editor_tabs.addTab(form_tab, "Structured Form")
        self._editor_tabs.addTab(text_tab, "YAML/JSON")
        editor_layout.addWidget(self._editor_tabs)
        splitter.addWidget(editor_container)

        viz_container = QWidget()
        viz_layout = QVBoxLayout(viz_container)
        viz_layout.addWidget(self._plot, stretch=3)

        legend_toolbar = QHBoxLayout()
        legend_toolbar.addWidget(QLabel("Legend"))
        legend_toolbar.addWidget(self._legend_toggle_subtask)
        legend_toolbar.addWidget(self._legend_toggle_segment)
        legend_toolbar.addStretch(1)
        viz_layout.addLayout(legend_toolbar)
        viz_layout.addWidget(self._legend_detail)
        viz_layout.addWidget(self._hover_hint)

        viz_layout.addWidget(QLabel("Metrics / Logs"))
        viz_layout.addWidget(self._metrics, stretch=2)
        viz_layout.addWidget(QLabel("Segment Details (Hover/Click lock)"))
        viz_layout.addWidget(self._details, stretch=2)

        splitter.addWidget(viz_container)
        splitter.setSizes([560, 940])

        root_layout.addWidget(splitter)
        self.setCentralWidget(root)
        self._stop_button.setEnabled(False)

    def _connect_signals(self) -> None:
        self._load_button.clicked.connect(self._pick_load_file)
        self._save_button.clicked.connect(self._pick_save_file)
        self._validate_button.clicked.connect(self._on_validate)
        self._run_button.clicked.connect(self._on_run)
        self._stop_button.clicked.connect(self._on_stop)
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
        ]
        for widget in combo_boxes:
            widget.currentIndexChanged.connect(self._mark_form_dirty)

        check_boxes = [
            self._form_resource_enabled,
            self._form_task_abort_on_miss,
            self._form_segment_preemptible,
            self._form_allow_preempt,
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
        ]
        for widget in spins:
            widget.valueChanged.connect(self._mark_form_dirty)

    def _on_text_edited(self) -> None:
        if self._suspend_text_events:
            return
        self._config_doc = None
        self._dag_manual_positions_by_task.clear()
        if self._editor_tabs.currentIndex() == 1:
            self._form_hint.setText("Text changed. Use 'Sync Text -> Form' to refresh form.")

    def _mark_form_dirty(self, *args: Any) -> None:  # noqa: ARG002
        if self._suspend_form_events:
            return
        self._form_dirty = True
        self._form_hint.setText("Form changed. Use 'Apply Form -> Text' before run/save.")

    def _on_sync_text_to_form(self) -> None:
        if self._sync_text_to_form(show_message=True):
            self._status_label.setText("Form synced from text")

    def _on_sync_form_to_text(self) -> None:
        if self._sync_form_to_text(show_message=True):
            self._status_label.setText("Text updated from form")

    def _sync_form_to_text_if_dirty(self) -> bool:
        if not self._form_dirty:
            return True
        return self._sync_form_to_text(show_message=False)

    def _sync_text_to_form(self, *, show_message: bool) -> bool:
        try:
            payload = self._read_editor_payload()
        except Exception as exc:  # noqa: BLE001
            if show_message:
                QMessageBox.critical(self, "Sync failed", str(exc))
            self._form_hint.setText("Sync Text -> Form failed.")
            return False

        self._populate_form_from_payload(payload)
        self._form_dirty = False
        self._form_hint.setText("Form synced from text.")
        return True

    def _sync_form_to_text(self, *, show_message: bool) -> bool:
        self._validate_task_table()
        self._validate_resource_table()
        if self._has_table_validation_errors():
            message = self._first_table_validation_error()
            if show_message:
                QMessageBox.warning(
                    self,
                    "Sync blocked",
                    "Table validation failed. Fix highlighted cells first.\n"
                    + message,
                )
            self._form_hint.setText("Apply blocked: table validation failed.")
            return False

        if self._config_doc is not None:
            base_payload = self._config_doc.to_payload()
        else:
            try:
                base_payload = self._read_editor_payload()
            except Exception:
                base_payload = {}

        try:
            payload = self._apply_form_to_payload(base_payload)
            text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        except Exception as exc:  # noqa: BLE001
            if show_message:
                QMessageBox.critical(self, "Sync failed", str(exc))
            self._form_hint.setText("Apply Form -> Text failed.")
            return False

        self._suspend_text_events = True
        try:
            self._editor.setPlainText(text)
        finally:
            self._suspend_text_events = False
        self._config_doc = ConfigDocument.from_payload(payload)
        self._populate_form_from_doc()
        self._form_dirty = False
        self._form_hint.setText("Form applied to text.")
        return True

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
        sim = doc.get_sim()

        self._suspend_form_events = True
        try:
            self._form_processor_id.setText(str(processor.get("id", "CPU")))
            self._form_processor_name.setText(str(processor.get("name", "cpu")))
            self._form_processor_core_count.setValue(max(1, int(self._safe_float(processor.get("core_count"), 1))))
            self._form_processor_speed.setValue(self._safe_float(processor.get("speed_factor"), 1.0))

            self._form_core_id.setText(str(core.get("id", "c0")))
            self._form_core_speed.setValue(self._safe_float(core.get("speed_factor"), 1.0))

            self._refresh_resource_table(doc)
            self._refresh_task_table(doc)
            self._refresh_selected_resource_fields(doc)
            self._refresh_selected_task_fields(doc)

            self._set_combo_value(self._form_scheduler_name, str(scheduler.get("name", "edf")))
            self._set_combo_value(self._form_tie_breaker, str(params.get("tie_breaker", "fifo")))
            self._form_allow_preempt.setChecked(self._to_bool(params.get("allow_preempt"), True))
            self._set_combo_value(self._form_event_id_mode, str(params.get("event_id_mode", "deterministic")))
            self._form_sim_duration.setValue(self._safe_float(sim.get("duration"), 10.0))
            self._form_sim_seed.setValue(int(self._safe_float(sim.get("seed"), 42)))
        finally:
            self._suspend_form_events = False

        self._refresh_dag_widgets(doc)

    def _ensure_config_doc(self) -> ConfigDocument:
        if self._config_doc is not None:
            return self._config_doc
        try:
            payload = self._read_editor_payload()
        except Exception:
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
        self._form_task_arrival.setValue(self._safe_float(task.get("arrival"), 0.0))
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
        self._form_segment_wcet.setValue(self._safe_float(segment.get("wcet"), 1.0))
        mapping_hint = segment.get("mapping_hint")
        self._form_segment_mapping_hint.setText("" if mapping_hint is None else str(mapping_hint))
        required_resources = segment.get("required_resources")
        if isinstance(required_resources, list):
            self._form_segment_required_resources.setText(",".join(str(item) for item in required_resources))
        else:
            self._form_segment_required_resources.setText("")
        self._form_segment_preemptible.setChecked(bool(segment.get("preemptible", True)))

    def _refresh_dag_widgets(self, doc: ConfigDocument) -> None:
        if self._selected_task_index < 0 or not doc.list_tasks():
            self._clear_dag_drag_preview()
            self._dag_scene.clear()
            self._dag_subtasks_list.clear()
            self._dag_edges_list.clear()
            self._dag_node_centers.clear()
            self._dag_node_items.clear()
            self._dag_edge_items.clear()
            self._dag_auto_layout_button.setEnabled(False)
            return

        subtasks = doc.list_subtasks(self._selected_task_index)
        subtask_ids = [str(subtask.get("id") or "") for subtask in subtasks if str(subtask.get("id") or "")]
        edges = doc.list_edges(self._selected_task_index)

        if self._selected_subtask_id not in subtask_ids and subtask_ids:
            self._selected_subtask_id = subtask_ids[0]

        self._dag_subtasks_list.blockSignals(True)
        self._dag_edges_list.blockSignals(True)
        try:
            self._dag_subtasks_list.clear()
            for sub_id in subtask_ids:
                self._dag_subtasks_list.addItem(sub_id)

            self._dag_edges_list.clear()
            for src_id, dst_id in edges:
                item = QListWidgetItem(f"{src_id} -> {dst_id}")
                item.setData(Qt.ItemDataRole.UserRole, (src_id, dst_id))
                self._dag_edges_list.addItem(item)

            for idx, sub_id in enumerate(subtask_ids):
                if sub_id == self._selected_subtask_id:
                    self._dag_subtasks_list.setCurrentRow(idx)
                    break
        finally:
            self._dag_subtasks_list.blockSignals(False)
            self._dag_edges_list.blockSignals(False)

        self._dag_remove_subtask_button.setEnabled(bool(subtask_ids))
        self._dag_remove_edge_button.setEnabled(bool(edges))
        self._dag_auto_layout_button.setEnabled(bool(subtask_ids))
        layout_key = self._current_task_layout_key(doc)
        positions = self._resolve_dag_positions(doc, layout_key, subtask_ids, edges)
        self._render_dag_scene(subtask_ids, edges, positions=positions)

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
        auto_positions = self._compute_auto_layout_positions(subtask_ids, edges)
        if not layout_key:
            return auto_positions

        task_positions = self._dag_manual_positions_by_task.get(layout_key)
        if task_positions is None:
            saved_positions = doc.get_task_node_layout(layout_key)
            if saved_positions:
                task_positions = {
                    sub_id: QPointF(float(xy[0]), float(xy[1]))
                    for sub_id, xy in saved_positions.items()
                }
                self._dag_manual_positions_by_task[layout_key] = task_positions

        result: dict[str, QPointF] = {}
        for sub_id in subtask_ids:
            manual = task_positions.get(sub_id) if task_positions else None
            if manual is not None:
                result[sub_id] = QPointF(manual.x(), manual.y())
            else:
                result[sub_id] = auto_positions.get(sub_id, QPointF(80.0, 80.0))

        if task_positions is not None:
            self._dag_manual_positions_by_task[layout_key] = {
                sub_id: QPointF(pos.x(), pos.y()) for sub_id, pos in result.items()
            }
        return result

    @staticmethod
    def _compute_auto_layout_positions(
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
    ) -> dict[str, QPointF]:
        if not subtask_ids:
            return {}

        children: dict[str, set[str]] = {sub_id: set() for sub_id in subtask_ids}
        indegree: dict[str, int] = {sub_id: 0 for sub_id in subtask_ids}
        for src_id, dst_id in edges:
            if src_id not in children or dst_id not in children:
                continue
            if dst_id in children[src_id]:
                continue
            children[src_id].add(dst_id)
            indegree[dst_id] += 1

        queue = sorted([sub_id for sub_id, degree in indegree.items() if degree == 0])
        level: dict[str, int] = {sub_id: 0 for sub_id in subtask_ids}
        visited: set[str] = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for nxt in sorted(children.get(current, set())):
                level[nxt] = max(level[nxt], level[current] + 1)
                indegree[nxt] -= 1
                if indegree[nxt] <= 0:
                    queue.append(nxt)

        # Defensive fallback for non-DAG/isolated edge cases.
        if len(visited) < len(subtask_ids):
            for idx, sub_id in enumerate(sorted(subtask_ids)):
                level[sub_id] = max(level.get(sub_id, 0), idx // 4)

        level_groups: dict[int, list[str]] = {}
        for sub_id in subtask_ids:
            level_groups.setdefault(level.get(sub_id, 0), []).append(sub_id)
        for values in level_groups.values():
            values.sort()

        x_gap = 170.0
        y_gap = 115.0
        positions: dict[str, QPointF] = {}
        for col, layer in enumerate(sorted(level_groups)):
            for row, sub_id in enumerate(level_groups[layer]):
                positions[sub_id] = QPointF(80.0 + col * x_gap, 80.0 + row * y_gap)
        return positions

    def _render_dag_scene(
        self,
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
        *,
        positions: dict[str, QPointF],
    ) -> None:
        self._clear_dag_drag_preview()
        self._dag_scene.clear()
        self._dag_node_centers = {}
        self._dag_node_items = {}
        self._dag_edge_items = {}
        if not subtask_ids:
            self._dag_scene.addText("No subtask in selected task")
            return

        node_radius = 22.0
        self._dag_node_centers = {
            sub_id: QPointF(
                positions.get(sub_id, QPointF(80.0, 80.0)).x(),
                positions.get(sub_id, QPointF(80.0, 80.0)).y(),
            )
            for sub_id in subtask_ids
        }

        edge_pen = QPen(QColor("#8ea6b8"))
        edge_pen.setWidth(2)
        for src_id, dst_id in edges:
            src = self._dag_node_centers.get(src_id)
            dst = self._dag_node_centers.get(dst_id)
            if src is None or dst is None:
                continue
            line = QGraphicsLineItem(src.x(), src.y(), dst.x(), dst.y())
            line.setPen(edge_pen)
            line.setZValue(1)
            self._dag_scene.addItem(line)
            self._dag_edge_items[(src_id, dst_id)] = line

        for sub_id in subtask_ids:
            center = self._dag_node_centers[sub_id]
            node_item = DagNodeItem(
                owner=self,
                subtask_id=sub_id,
                center=center,
                radius=node_radius,
                selected=sub_id == self._selected_subtask_id,
            )
            self._dag_scene.addItem(node_item)
            self._dag_node_items[sub_id] = node_item

            label_item = self._dag_scene.addText(sub_id)
            label_item.setParentItem(node_item)
            rect = label_item.boundingRect()
            label_item.setPos(-rect.width() / 2.0, -rect.height() / 2.0)
            label_item.setDefaultTextColor(QColor("#f5f7fa"))
            label_item.setZValue(3)

        self._dag_view.setSceneRect(self._dag_scene.itemsBoundingRect().adjusted(-30, -30, 30, 30))

    def _start_dag_link_drag(self, src_id: str, scene_pos: QPointF) -> None:
        self._clear_dag_drag_preview()
        self._dag_drag_source_id = src_id
        line = QGraphicsLineItem(scene_pos.x(), scene_pos.y(), scene_pos.x(), scene_pos.y())
        pen = QPen(QColor("#f8d26a"))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidth(2)
        line.setPen(pen)
        line.setZValue(4)
        self._dag_scene.addItem(line)
        self._dag_drag_line = line

    def _update_dag_link_drag(self, scene_pos: QPointF) -> None:
        line = self._dag_drag_line
        if line is None:
            return
        segment = line.line()
        line.setLine(segment.x1(), segment.y1(), scene_pos.x(), scene_pos.y())

    def _finish_dag_link_drag(self, scene_pos: QPointF) -> None:
        src_id = self._dag_drag_source_id
        dst_id = self._dag_node_id_from_scene_pos(scene_pos)
        self._clear_dag_drag_preview()
        if src_id is None or dst_id is None:
            return
        self._try_add_dag_edge(src_id, dst_id, show_feedback=True)

    def _clear_dag_drag_preview(self) -> None:
        if self._dag_drag_line is not None:
            try:
                self._dag_scene.removeItem(self._dag_drag_line)
            except RuntimeError:
                pass
        self._dag_drag_line = None
        self._dag_drag_source_id = None

    def _dag_node_id_from_scene_pos(self, scene_pos: QPointF) -> str | None:
        for item in self._dag_scene.items(scene_pos):
            if isinstance(item, DagNodeItem):
                return item.subtask_id
        nearest_id: str | None = None
        nearest_distance = float("inf")
        for sub_id, center in self._dag_node_centers.items():
            dx = center.x() - scene_pos.x()
            dy = center.y() - scene_pos.y()
            distance = dx * dx + dy * dy
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_id = sub_id
        if nearest_id is not None and nearest_distance <= 28.0 * 28.0:
            return nearest_id
        return None

    def _dag_scene_pos_for_subtask(self, subtask_id: str) -> QPointF | None:
        center = self._dag_node_centers.get(subtask_id)
        if center is None:
            return None
        return QPointF(center.x(), center.y())

    def _on_dag_node_clicked(self, subtask_id: str) -> None:
        if not subtask_id:
            return
        self._selected_subtask_id = subtask_id

        self._dag_subtasks_list.blockSignals(True)
        try:
            for idx in range(self._dag_subtasks_list.count()):
                item = self._dag_subtasks_list.item(idx)
                if item is not None and item.text().strip() == subtask_id:
                    self._dag_subtasks_list.setCurrentRow(idx)
                    break
        finally:
            self._dag_subtasks_list.blockSignals(False)

        doc = self._ensure_config_doc()
        self._suspend_form_events = True
        try:
            self._refresh_selected_task_fields(doc)
        finally:
            self._suspend_form_events = False
        self._refresh_dag_node_selection_visuals()

    def _refresh_dag_node_selection_visuals(self) -> None:
        for sub_id, node_item in self._dag_node_items.items():
            node_item.setBrush(QBrush(QColor("#2d7ff9" if sub_id == self._selected_subtask_id else "#47617a")))

    def _on_dag_node_moved(self, subtask_id: str, center: QPointF) -> None:
        if not subtask_id:
            return
        self._dag_node_centers[subtask_id] = QPointF(center.x(), center.y())
        self._update_dag_edges_for_node(subtask_id)
        self._dag_view.setSceneRect(self._dag_scene.itemsBoundingRect().adjusted(-30, -30, 30, 30))

        doc = self._ensure_config_doc()
        layout_key = self._current_task_layout_key(doc)
        if layout_key:
            task_positions = self._dag_manual_positions_by_task.setdefault(layout_key, {})
            task_positions[subtask_id] = QPointF(center.x(), center.y())

    def _on_dag_node_drag_finished(self, subtask_id: str) -> None:
        if not subtask_id:
            return
        self._update_dag_edges_for_node(subtask_id)
        if self._dag_persist_layout.isChecked():
            self._persist_current_dag_layout_to_doc()

    def _update_dag_edges_for_node(self, subtask_id: str) -> None:
        center = self._dag_node_centers.get(subtask_id)
        if center is None:
            return
        for (src_id, dst_id), line in self._dag_edge_items.items():
            current = line.line()
            if src_id == subtask_id:
                line.setLine(center.x(), center.y(), current.x2(), current.y2())
            elif dst_id == subtask_id:
                line.setLine(current.x1(), current.y1(), center.x(), center.y())

    def _persist_current_dag_layout_to_doc(self) -> None:
        doc = self._ensure_config_doc()
        layout_key = self._current_task_layout_key(doc)
        if not layout_key:
            return
        positions = {
            sub_id: (center.x(), center.y())
            for sub_id, center in self._dag_node_centers.items()
        }
        doc.set_task_node_layout(layout_key, positions)
        self._mark_form_dirty()
        self._form_hint.setText("DAG layout changed. Apply Form -> Text to persist ui_layout.")

    def _on_dag_auto_layout(self) -> None:
        doc = self._ensure_config_doc()
        if self._selected_task_index < 0 or not doc.list_tasks():
            return
        subtasks = doc.list_subtasks(self._selected_task_index)
        subtask_ids = [str(subtask.get("id") or "") for subtask in subtasks if str(subtask.get("id") or "")]
        edges = doc.list_edges(self._selected_task_index)
        layout_key = self._current_task_layout_key(doc)
        auto_positions = self._compute_auto_layout_positions(subtask_ids, edges)
        if layout_key:
            self._dag_manual_positions_by_task[layout_key] = {
                sub_id: QPointF(pos.x(), pos.y()) for sub_id, pos in auto_positions.items()
            }
        self._render_dag_scene(subtask_ids, edges, positions=auto_positions)
        self._refresh_dag_node_selection_visuals()
        self._form_hint.setText("DAG auto-layout applied.")
        if self._dag_persist_layout.isChecked():
            self._persist_current_dag_layout_to_doc()

    def _on_dag_persist_layout_toggled(self, checked: bool) -> None:
        if checked:
            self._persist_current_dag_layout_to_doc()
        else:
            self._form_hint.setText("DAG layout persistence disabled.")

    def _try_add_dag_edge(self, src_id: str, dst_id: str, *, show_feedback: bool) -> bool:
        doc = self._ensure_config_doc()
        if self._selected_task_index < 0:
            self._form_hint.setText("DAG edge rejected: no selected task.")
            return False

        src = src_id.strip()
        dst = dst_id.strip()
        if not src or not dst:
            self._form_hint.setText("DAG edge rejected: src/dst can not be empty.")
            return False
        if src == dst:
            self._form_hint.setText("DAG edge rejected: self-loop is not allowed.")
            return False

        subtask_ids = {
            str(subtask.get("id") or "")
            for subtask in doc.list_subtasks(self._selected_task_index)
            if str(subtask.get("id") or "")
        }
        if src not in subtask_ids or dst not in subtask_ids:
            self._form_hint.setText("DAG edge rejected: src/dst node does not exist.")
            return False

        if (src, dst) in set(doc.list_edges(self._selected_task_index)):
            self._form_hint.setText(f"DAG edge ignored: {src}->{dst} already exists.")
            return False

        if self._would_create_cycle(doc, self._selected_task_index, src, dst):
            self._form_hint.setText(f"DAG edge rejected: {src}->{dst} creates a cycle.")
            return False

        doc.add_edge(self._selected_task_index, src, dst)
        self._populate_form_from_doc()
        self._refresh_dag_node_selection_visuals()
        self._mark_form_dirty()
        if show_feedback:
            self._form_hint.setText(f"DAG edge added: {src}->{dst}")
        return True

    @staticmethod
    def _would_create_cycle(doc: ConfigDocument, task_index: int, src_id: str, dst_id: str) -> bool:
        adjacency: dict[str, set[str]] = {}
        for src, dst in doc.list_edges(task_index):
            adjacency.setdefault(src, set()).add(dst)
        adjacency.setdefault(src_id, set()).add(dst_id)

        stack = [dst_id]
        visited: set[str] = set()
        while stack:
            node = stack.pop()
            if node == src_id:
                return True
            if node in visited:
                continue
            visited.add(node)
            for nxt in adjacency.get(node, set()):
                if nxt not in visited:
                    stack.append(nxt)
        return False

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
            },
        )
        doc.patch_sim(float(self._form_sim_duration.value()), int(self._form_sim_seed.value()))

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
        id_counts: dict[str, int] = {}
        for row in range(row_count):
            task_id = self._table_cell_text(table, row, 0)
            if task_id:
                id_counts[task_id] = id_counts.get(task_id, 0) + 1

        self._clear_table_error_bucket("task")
        table.blockSignals(True)
        try:
            for row in range(row_count):
                task_id = self._table_cell_text(table, row, 0)
                task_name = self._table_cell_text(table, row, 1)
                task_type = self._table_cell_text(table, row, 2)
                arrival_text = self._table_cell_text(table, row, 3)
                deadline_text = self._table_cell_text(table, row, 4)

                id_error: str | None = None
                if not task_id:
                    id_error = "task.id can not be empty"
                elif id_counts.get(task_id, 0) > 1:
                    id_error = "task.id must be unique"
                self._set_table_cell_error(
                    table_key="task",
                    table=table,
                    row=row,
                    col=0,
                    error=id_error,
                )

                self._set_table_cell_error(
                    table_key="task",
                    table=table,
                    row=row,
                    col=1,
                    error=None if task_name else "task.name can not be empty",
                )

                self._set_table_cell_error(
                    table_key="task",
                    table=table,
                    row=row,
                    col=2,
                    error=None if task_type in self._TASK_TYPE_OPTIONS else "task_type must be dynamic_rt/time_deterministic/non_rt",
                )

                arrival_error: str | None = None
                arrival = self._safe_optional_float(arrival_text)
                if arrival is None:
                    arrival_error = "arrival must be number"
                elif arrival < 0:
                    arrival_error = "arrival must be >= 0"
                self._set_table_cell_error(
                    table_key="task",
                    table=table,
                    row=row,
                    col=3,
                    error=arrival_error,
                )

                deadline_error: str | None = None
                if deadline_text:
                    deadline = self._safe_optional_float(deadline_text)
                    if deadline is None:
                        deadline_error = "deadline must be number"
                    elif deadline <= 0:
                        deadline_error = "deadline must be > 0"
                self._set_table_cell_error(
                    table_key="task",
                    table=table,
                    row=row,
                    col=4,
                    error=deadline_error,
                )
        finally:
            table.blockSignals(False)

    def _validate_resource_table(self) -> None:
        table = self._resource_table
        row_count = table.rowCount()
        id_counts: dict[str, int] = {}
        for row in range(row_count):
            resource_id = self._table_cell_text(table, row, 0)
            if resource_id:
                id_counts[resource_id] = id_counts.get(resource_id, 0) + 1

        self._clear_table_error_bucket("resource")
        table.blockSignals(True)
        try:
            for row in range(row_count):
                resource_id = self._table_cell_text(table, row, 0)
                resource_name = self._table_cell_text(table, row, 1)
                bound_core_id = self._table_cell_text(table, row, 2)
                protocol = self._table_cell_text(table, row, 3)

                id_error: str | None = None
                if not resource_id:
                    id_error = "resource.id can not be empty"
                elif id_counts.get(resource_id, 0) > 1:
                    id_error = "resource.id must be unique"
                self._set_table_cell_error(
                    table_key="resource",
                    table=table,
                    row=row,
                    col=0,
                    error=id_error,
                )

                self._set_table_cell_error(
                    table_key="resource",
                    table=table,
                    row=row,
                    col=1,
                    error=None if resource_name else "resource.name can not be empty",
                )
                self._set_table_cell_error(
                    table_key="resource",
                    table=table,
                    row=row,
                    col=2,
                    error=None if bound_core_id else "bound_core_id can not be empty",
                )
                self._set_table_cell_error(
                    table_key="resource",
                    table=table,
                    row=row,
                    col=3,
                    error=None if protocol in self._RESOURCE_PROTOCOL_OPTIONS else "protocol must be mutex/pip/pcp",
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
        deadline = self._safe_optional_float(deadline_text) if deadline_text else None
        doc.patch_task(
            row,
            {
                "id": self._table_cell_text(self._task_table, row, 0) or f"t{row}",
                "name": self._table_cell_text(self._task_table, row, 1) or "task",
                "task_type": task_type,
                "arrival": float(self._safe_optional_float(self._table_cell_text(self._task_table, row, 3)) or 0.0),
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
        self._selected_task_index = row if row >= 0 else -1
        doc = self._ensure_config_doc()
        self._suspend_form_events = True
        try:
            self._refresh_selected_task_fields(doc)
        finally:
            self._suspend_form_events = False
        self._refresh_dag_widgets(doc)

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
        if self._suspend_form_events:
            return
        item = self._dag_subtasks_list.currentItem()
        if item is None:
            return
        selected = item.text().strip()
        if selected:
            self._on_dag_node_clicked(selected)

    def _on_dag_add_subtask(self) -> None:
        doc = self._ensure_config_doc()
        if self._selected_task_index < 0:
            self._selected_task_index = doc.add_task()
        new_index = doc.add_subtask(self._selected_task_index, self._dag_new_subtask_id.text().strip() or None)
        new_subtask = doc.get_subtask(self._selected_task_index, new_index)
        self._selected_subtask_id = str(new_subtask.get("id") or "s0")
        self._dag_new_subtask_id.clear()
        self._populate_form_from_doc()
        self._refresh_dag_node_selection_visuals()
        if self._dag_persist_layout.isChecked():
            self._persist_current_dag_layout_to_doc()
        self._mark_form_dirty()

    def _on_dag_remove_subtask(self) -> None:
        doc = self._ensure_config_doc()
        if self._selected_task_index < 0:
            return
        subtasks = doc.list_subtasks(self._selected_task_index)
        if not subtasks:
            return

        target_index = 0
        item = self._dag_subtasks_list.currentItem()
        selected_id = item.text().strip() if item is not None else self._selected_subtask_id
        for idx, subtask in enumerate(subtasks):
            if str(subtask.get("id") or "") == selected_id:
                target_index = idx
                break
        doc.remove_subtask(self._selected_task_index, target_index)

        remaining = doc.list_subtasks(self._selected_task_index)
        self._selected_subtask_id = str(remaining[0].get("id") or "s0") if remaining else "s0"
        self._populate_form_from_doc()
        self._refresh_dag_node_selection_visuals()
        if self._dag_persist_layout.isChecked():
            self._persist_current_dag_layout_to_doc()
        self._mark_form_dirty()

    def _on_dag_add_edge(self) -> None:
        src_id = self._dag_edge_src.text().strip()
        dst_id = self._dag_edge_dst.text().strip()
        if not src_id:
            src_id = self._selected_subtask_id
        self._try_add_dag_edge(src_id, dst_id, show_feedback=True)
        self._dag_edge_src.clear()
        self._dag_edge_dst.clear()

    def _on_dag_remove_edge(self) -> None:
        doc = self._ensure_config_doc()
        if self._selected_task_index < 0:
            return
        item = self._dag_edges_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple) or len(data) != 2:
            return
        src_id, dst_id = data
        doc.remove_edge(self._selected_task_index, str(src_id), str(dst_id))
        self._populate_form_from_doc()
        self._refresh_dag_node_selection_visuals()
        if self._dag_persist_layout.isChecked():
            self._persist_current_dag_layout_to_doc()
        self._mark_form_dirty()

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
        self._sync_text_to_form(show_message=False)
        self._status_label.setText(f"Loaded: {path}")

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

    def _on_validate(self) -> None:
        if not self._sync_form_to_text_if_dirty():
            return
        try:
            payload = self._read_editor_payload()
            self._loader.load_data(payload)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Validation failed", str(exc))
            self._status_label.setText("Validation failed")
            return
        self._status_label.setText("Validation passed")
        QMessageBox.information(self, "Validation", "Config validation passed.")

    def _on_run(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        if not self._sync_form_to_text_if_dirty():
            return
        try:
            payload = self._read_editor_payload()
            self._loader.load_data(payload)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Run failed", f"Invalid config: {exc}")
            self._status_label.setText("Run blocked by invalid config")
            return

        self._reset_viz()
        self._metrics.clear()

        config_text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        self._worker = SimulationWorker(config_text)
        self._worker.events_batch.connect(self._on_event_batch)
        self._worker.finished_report.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self._run_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._status_label.setText("Running")

    def _on_stop(self) -> None:
        if self._worker:
            self._worker.stop()
        self._status_label.setText("Stopping...")

    def _on_event_batch(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            event_id = event.get("event_id")
            if event_id and event_id in self._seen_event_ids:
                continue
            if event_id:
                self._seen_event_ids.add(event_id)
            self._consume_event(event)

    def _consume_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        segment_key = payload.get("segment_key")
        event_time = self._safe_float(event.get("time"), 0.0)
        self._max_time = max(self._max_time, event_time)

        if event_type == "JobReleased":
            job_id = str(event.get("job_id") or "")
            self._job_deadlines[job_id] = self._safe_optional_float(payload.get("absolute_deadline"))
            return

        if event_type == "ResourceAcquire" and isinstance(segment_key, str):
            resource_id = event.get("resource_id")
            if resource_id:
                self._segment_resources.setdefault(segment_key, set()).add(str(resource_id))
            return

        if event_type == "SegmentStart" and isinstance(segment_key, str):
            core_id = str(event.get("core_id") or "unknown")
            job_id = str(event.get("job_id") or "")
            subtask_id, parsed_segment_id = self._parse_segment_key(segment_key)
            self._active_segments[segment_key] = {
                "start": event_time,
                "core_id": core_id,
                "job_id": job_id,
                "task_id": self._task_from_job(job_id),
                "subtask_id": subtask_id,
                "segment_id": str(event.get("segment_id") or parsed_segment_id),
                "start_payload": payload,
                "start_event_id": str(event.get("event_id") or ""),
                "start_seq": self._safe_optional_int(event.get("seq")),
                "correlation_id": str(event.get("correlation_id") or ""),
                "absolute_deadline": self._job_deadlines.get(job_id),
            }
            return

        if event_type == "SegmentEnd" and isinstance(segment_key, str):
            self._close_segment(segment_key=segment_key, end_event=event, interrupted=False)
            return

        if event_type == "Preempt" and isinstance(segment_key, str):
            self._close_segment(segment_key=segment_key, end_event=event, interrupted=True)
            return

        if event_type == "DeadlineMiss":
            job_id = event.get("job_id", "")
            self._metrics.append(f"[DeadlineMiss] {job_id} at t={event_time:.3f}")

    def _close_segment(self, segment_key: str, end_event: dict[str, Any], interrupted: bool) -> None:
        start_data = self._active_segments.pop(segment_key, None)
        if not start_data:
            return

        start_time = self._safe_float(start_data.get("start"), 0.0)
        end_time = self._safe_float(end_event.get("time"), start_time)
        if end_time < start_time:
            return
        duration = max(0.0, end_time - start_time)

        start_payload = start_data.get("start_payload", {})
        if not isinstance(start_payload, dict):
            start_payload = {}

        deadline = self._safe_optional_float(start_data.get("absolute_deadline"))
        lateness = end_time - deadline if deadline is not None else None
        estimated_finish = self._safe_optional_float(start_payload.get("estimated_finish"))
        remaining_after_preempt = None
        if interrupted and estimated_finish is not None:
            remaining_after_preempt = max(0.0, estimated_finish - end_time)

        status = "Preempted" if interrupted else "Completed"
        meta = SegmentVisualMeta(
            task_id=str(start_data.get("task_id") or "unknown"),
            job_id=str(start_data.get("job_id") or ""),
            subtask_id=str(start_data.get("subtask_id") or "unknown"),
            segment_id=str(start_data.get("segment_id") or "unknown"),
            segment_key=segment_key,
            core_id=str(start_data.get("core_id") or "unknown"),
            start=start_time,
            end=end_time,
            duration=duration,
            status=status,
            resources=sorted(self._segment_resources.get(segment_key, set())),
            event_id_start=str(start_data.get("start_event_id") or ""),
            event_id_end=str(end_event.get("event_id") or ""),
            seq_start=self._safe_optional_int(start_data.get("start_seq")),
            seq_end=self._safe_optional_int(end_event.get("seq")),
            correlation_id=str(end_event.get("correlation_id") or start_data.get("correlation_id") or ""),
            deadline=deadline,
            lateness_at_end=lateness,
            remaining_after_preempt=remaining_after_preempt,
            execution_time_est=self._safe_optional_float(start_payload.get("execution_time")),
            context_overhead=self._safe_optional_float(start_payload.get("context_overhead")),
            migration_overhead=self._safe_optional_float(start_payload.get("migration_overhead")),
            estimated_finish=estimated_finish,
        )

        self._draw_gantt_segment(meta)

        self._metrics.append(
            f"[Segment] {meta.segment_key} task={meta.task_id} core={meta.core_id} "
            f"[{meta.start:.3f}, {meta.end:.3f}]"
            + (" (preempted)" if interrupted else "")
        )

        if interrupted:
            self._draw_preempt_marker(meta.end, meta.core_id)
            self._metrics.append(f"[Preempt] {meta.segment_key} at t={meta.end:.3f}")

        self._segment_resources.pop(segment_key, None)

    def _draw_gantt_segment(self, meta: SegmentVisualMeta) -> None:
        y = self._core_lane(meta.core_id)
        color = self._task_color(meta.task_id)
        brush_style = self._subtask_brush_style(meta.task_id, meta.subtask_id)
        pen_style = self._segment_pen_style(meta.segment_id, interrupted=(meta.status == "Preempted"))

        self._ensure_task_legend(meta.task_id, color)
        self._subtask_legend_map[(meta.task_id, meta.subtask_id)] = self._brush_style_name(brush_style)
        self._segment_legend_map[meta.segment_id] = self._pen_style_name(pen_style)
        self._refresh_legend_details()

        block = SegmentBlockItem(
            meta=meta,
            y=y,
            lane_height=self._lane_height,
            color=color,
            brush_style=brush_style,
            pen_style=pen_style,
        )
        self._plot.addItem(block)
        self._segment_items.append(block)

        if meta.duration >= self._segment_label_min_duration:
            label = pg.TextItem(text=meta.segment_id, anchor=(0.5, 0.5), color="#f4f4f4")
            label.setZValue(3)
            label.setPos(meta.start + meta.duration / 2.0, y)
            self._plot.addItem(label)
            self._segment_labels.append(label)

        self._plot.setXRange(0, max(1.0, self._max_time * 1.05), padding=0)

    def _draw_preempt_marker(self, event_time: float, core_id: str) -> None:
        if core_id not in self._core_to_y:
            return
        y = self._core_to_y[core_id]
        marker = pg.ScatterPlotItem(
            x=[event_time],
            y=[y],
            symbol="x",
            size=12,
            pen=pg.mkPen(color="#ffd54f", width=2),
            brush=pg.mkBrush("#ffd54f"),
        )
        marker.setZValue(4)
        self._plot.addItem(marker)

    def _core_lane(self, core_id: str) -> int:
        if core_id not in self._core_to_y:
            self._core_to_y[core_id] = len(self._core_to_y) + 1
            ticks = [(y, core) for core, y in sorted(self._core_to_y.items(), key=lambda item: item[1])]
            self._plot.getAxis("left").setTicks([ticks])
        return self._core_to_y[core_id]

    def _task_color(self, task_id: str) -> QColor:
        return pg.intColor(
            zlib.crc32(task_id.encode("utf-8")) % 24,
            hues=24,
            values=1,
            minValue=170,
            maxValue=255,
        )

    def _subtask_brush_style(self, task_id: str, subtask_id: str) -> Qt.BrushStyle:
        key = (task_id, subtask_id)
        cached = self._subtask_style_cache.get(key)
        if cached is not None:
            return cached
        idx = zlib.crc32(f"{task_id}:{subtask_id}".encode("utf-8")) % len(self._SUBTASK_BRUSH_STYLES)
        style = self._SUBTASK_BRUSH_STYLES[idx]
        self._subtask_style_cache[key] = style
        return style

    def _segment_pen_style(self, segment_id: str, interrupted: bool) -> Qt.PenStyle:
        if interrupted:
            return Qt.PenStyle.DashLine
        cached = self._segment_style_cache.get(segment_id)
        if cached is not None:
            return cached
        idx = zlib.crc32(segment_id.encode("utf-8")) % len(self._SEGMENT_PEN_STYLES)
        style = self._SEGMENT_PEN_STYLES[idx]
        self._segment_style_cache[segment_id] = style
        return style

    def _ensure_task_legend(self, task_id: str, color: QColor) -> None:
        plot_item = self._plot.getPlotItem()
        if task_id in self._legend_tasks or plot_item.legend is None:
            return
        sample = pg.PlotDataItem([0, 1], [0, 0], pen=pg.mkPen(color=color, width=6))
        plot_item.legend.addItem(sample, task_id)
        self._legend_samples.append(sample)
        self._legend_tasks.add(task_id)

    def _on_plot_mouse_moved(self, scene_pos: QPointF) -> None:
        item = self._segment_item_from_scene(scene_pos)
        if item is None:
            self._hovered_segment_key = None
            QToolTip.hideText()
            if self._locked_segment_key is None:
                self._hover_hint.setText("Hover a segment for details. Click segment to lock/unlock.")
                self._details.clear()
            return

        self._hovered_segment_key = item.meta.segment_key
        self._hover_hint.setText(
            f"Hover: {item.meta.task_id}/{item.meta.subtask_id}/{item.meta.segment_id} "
            f"core={item.meta.core_id} [{item.meta.start:.3f}, {item.meta.end:.3f}]"
        )
        QToolTip.showText(QCursor.pos(), item.toolTip())

        if self._locked_segment_key is None:
            self._details.setPlainText(self._format_segment_details(item.meta))

    def _on_plot_mouse_clicked(self, event: Any) -> None:
        scene_pos = event.scenePos() if hasattr(event, "scenePos") else QPointF()
        item = self._segment_item_from_scene(scene_pos)
        if item is None:
            self._locked_segment_key = None
            if self._hovered_segment_key is None:
                self._details.clear()
            if hasattr(event, "accept"):
                event.accept()
            return

        key = item.meta.segment_key
        if self._locked_segment_key == key:
            self._locked_segment_key = None
        else:
            self._locked_segment_key = key
            self._details.setPlainText(self._format_segment_details(item.meta))

        if hasattr(event, "accept"):
            event.accept()

    def _segment_item_from_scene(self, scene_pos: QPointF) -> SegmentBlockItem | None:
        for raw_item in self._plot.scene().items(scene_pos):
            if isinstance(raw_item, SegmentBlockItem):
                return raw_item
            parent = raw_item.parentItem() if hasattr(raw_item, "parentItem") else None
            if isinstance(parent, SegmentBlockItem):
                return parent
        return None

    def _refresh_legend_details(self) -> None:
        show_subtask = self._legend_toggle_subtask.isChecked()
        show_segment = self._legend_toggle_segment.isChecked()
        if not show_subtask and not show_segment:
            self._legend_detail.clear()
            self._legend_detail.hide()
            return

        lines: list[str] = []
        if show_subtask:
            lines.append("Subtask Legend (task/subtask -> brush pattern)")
            for (task_id, subtask_id), style_name in sorted(self._subtask_legend_map.items()):
                lines.append(f"- {task_id}/{subtask_id}: {style_name}")

        if show_segment:
            if lines:
                lines.append("")
            lines.append("Segment Legend (segment id -> border style)")
            for segment_id, style_name in sorted(self._segment_legend_map.items()):
                lines.append(f"- {segment_id}: {style_name}")

        self._legend_detail.setPlainText("\n".join(lines))
        self._legend_detail.show()

    def _format_segment_details(self, meta: SegmentVisualMeta) -> str:
        resources_text = ", ".join(meta.resources) if meta.resources else "-"
        deadline_text = self._fmt_optional_float(meta.deadline)
        lateness_text = self._fmt_optional_float(meta.lateness_at_end)
        remaining_text = self._fmt_optional_float(meta.remaining_after_preempt)
        return (
            f"task_id: {meta.task_id}\n"
            f"job_id: {meta.job_id}\n"
            f"subtask_id: {meta.subtask_id}\n"
            f"segment_id: {meta.segment_id}\n"
            f"segment_key: {meta.segment_key}\n"
            f"core_id: {meta.core_id}\n"
            f"start_time: {meta.start:.3f}\n"
            f"end_time: {meta.end:.3f}\n"
            f"duration: {meta.duration:.3f}\n"
            f"status: {meta.status}\n"
            f"resources: {resources_text}\n"
            f"event_id_start: {meta.event_id_start or '-'}\n"
            f"event_id_end: {meta.event_id_end or '-'}\n"
            f"seq_start: {self._fmt_optional_int(meta.seq_start)}\n"
            f"seq_end: {self._fmt_optional_int(meta.seq_end)}\n"
            f"correlation_id: {meta.correlation_id or '-'}\n"
            f"deadline: {deadline_text}\n"
            f"lateness_at_end: {lateness_text}\n"
            f"remaining_after_preempt: {remaining_text}\n"
            f"execution_time_est: {self._fmt_optional_float(meta.execution_time_est)}\n"
            f"context_overhead: {self._fmt_optional_float(meta.context_overhead)}\n"
            f"migration_overhead: {self._fmt_optional_float(meta.migration_overhead)}\n"
            f"estimated_finish: {self._fmt_optional_float(meta.estimated_finish)}"
        )

    @staticmethod
    def _fmt_optional_int(value: int | None) -> str:
        return "-" if value is None else str(value)

    @staticmethod
    def _fmt_optional_float(value: float | None) -> str:
        return "-" if value is None else f"{value:.3f}"

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_optional_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_optional_int(value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _task_from_job(job_id: str) -> str:
        if not job_id:
            return "unknown"
        return job_id.split("@", 1)[0]

    @staticmethod
    def _parse_segment_key(segment_key: str) -> tuple[str, str]:
        parts = segment_key.split(":", 2)
        if len(parts) != 3:
            return ("unknown", "unknown")
        return (parts[1], parts[2])

    @staticmethod
    def _brush_style_name(style: Qt.BrushStyle) -> str:
        names = {
            Qt.BrushStyle.SolidPattern: "Solid",
            Qt.BrushStyle.Dense4Pattern: "Dense4",
            Qt.BrushStyle.Dense6Pattern: "Dense6",
            Qt.BrushStyle.BDiagPattern: "BackwardDiag",
            Qt.BrushStyle.DiagCrossPattern: "DiagCross",
            Qt.BrushStyle.CrossPattern: "Cross",
        }
        return names.get(style, style.name)

    @staticmethod
    def _pen_style_name(style: Qt.PenStyle) -> str:
        names = {
            Qt.PenStyle.SolidLine: "Solid",
            Qt.PenStyle.DashLine: "Dash",
            Qt.PenStyle.DotLine: "Dot",
            Qt.PenStyle.DashDotLine: "DashDot",
            Qt.PenStyle.DashDotDotLine: "DashDotDot",
        }
        return names.get(style, style.name)

    def _on_finished(self, report: dict[str, Any], tail_events: list[dict[str, Any]]) -> None:
        if tail_events:
            self._on_event_batch(tail_events)
        self._metrics.append("\n=== Metrics ===")
        self._metrics.append(json.dumps(report, ensure_ascii=False, indent=2))
        self._status_label.setText("Completed")
        self._run_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._worker = None

    def _on_failed(self, error_message: str) -> None:
        self._metrics.append(f"[Error] {error_message}")
        QMessageBox.critical(self, "Simulation failed", error_message)
        self._status_label.setText("Failed")
        self._run_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._worker = None

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
        self._hovered_segment_key = None
        self._locked_segment_key = None

        self._hover_hint.setText("Hover a segment for details. Click segment to lock/unlock.")
        self._details.clear()
        self._refresh_legend_details()
        QToolTip.hideText()


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
