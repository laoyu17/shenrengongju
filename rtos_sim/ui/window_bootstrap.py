"""Bootstrap helpers for ``MainWindow`` widget/state assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGraphicsScene,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QDoubleSpinBox,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QListWidget,
    QGraphicsView,
)

from rtos_sim.io import ConfigLoader

from .controllers import (
    CompareController,
    DagController,
    DagOverviewController,
    DocumentSyncController,
    FormController,
    GanttStyleController,
    PlanningController,
    ResearchReportController,
    RunController,
    TableEditorController,
    TelemetryController,
    TimelineController,
)
from .panel_builders import build_compare_group, build_dag_workbench_group, build_planning_tab
from .panel_state import ComparePanelState, DagWorkbenchState, TelemetryPanelState

if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class UiErrorLogger(Protocol):
    def __call__(self, action: str, exc: Exception, **context: Any) -> None: ...


def bootstrap_main_window(owner: MainWindow, error_logger: UiErrorLogger) -> None:
    owner._loader = ConfigLoader()
    owner._worker = None

    owner._core_to_y = {}
    owner._active_segments = {}
    owner._segment_resources = {}
    owner._job_deadlines = {}

    owner._legend_tasks = set()
    owner._legend_samples = []
    owner._subtask_legend_map = {}
    owner._segment_legend_map = {}

    owner._subtask_style_cache = {}
    owner._segment_style_cache = {}

    owner._segment_items = []
    owner._segment_labels = []
    owner._seen_event_ids = set()

    owner._max_time = 0.0
    owner._lane_height = 0.62
    owner._segment_label_min_duration = 0.85

    owner._compare_panel_state = ComparePanelState()
    owner._dag_workbench_state = DagWorkbenchState()
    owner._telemetry_panel_state = TelemetryPanelState()
    owner._latest_metrics_report = {}
    owner._latest_run_payload = None
    owner._latest_run_spec = None
    owner._latest_run_events = None
    owner._latest_audit_report = None
    owner._latest_model_relations_report = None
    owner._latest_quality_snapshot = None
    owner._latest_research_report = None
    owner._latest_plan_result = None
    owner._latest_plan_payload = None
    owner._latest_plan_spec_fingerprint = None
    owner._latest_plan_semantic_fingerprint = None
    owner._latest_planning_wcrt_report = None
    owner._latest_planning_os_payload = None

    owner._editor = QPlainTextEdit()
    owner._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    owner._form_dirty = False
    owner._suspend_form_events = False
    owner._suspend_text_events = False
    owner._config_doc = None
    owner._selected_task_index = 0
    owner._selected_resource_index = 0
    owner._selected_subtask_id = "s0"
    owner._table_validation_errors = {}
    owner._editor_tabs = QTabWidget()
    owner._form_hint = QLabel("Structured form ready.")
    owner._sync_text_to_form_button = QPushButton("Sync Text -> Form")
    owner._sync_form_to_text_button = QPushButton("Apply Form -> Text")

    owner._form_processor_id = QLineEdit("CPU")
    owner._form_processor_name = QLineEdit("cpu")
    owner._form_processor_core_count = QSpinBox()
    owner._form_processor_core_count.setRange(1, 4096)
    owner._form_processor_core_count.setValue(1)
    owner._form_processor_speed = QDoubleSpinBox()
    owner._form_processor_speed.setRange(0.001, 1_000_000.0)
    owner._form_processor_speed.setDecimals(3)
    owner._form_processor_speed.setValue(1.0)
    owner._form_core_id = QLineEdit("c0")
    owner._form_core_speed = QDoubleSpinBox()
    owner._form_core_speed.setRange(0.001, 1_000_000.0)
    owner._form_core_speed.setDecimals(3)
    owner._form_core_speed.setValue(1.0)

    owner._form_resource_enabled = QCheckBox("Enable one basic resource")
    owner._form_resource_enabled.setChecked(False)
    owner._form_resource_id = QLineEdit("r0")
    owner._form_resource_name = QLineEdit("lock")
    owner._form_resource_bound_core = QLineEdit("c0")
    owner._form_resource_protocol = QComboBox()
    owner._form_resource_protocol.addItems(["mutex", "pip", "pcp"])
    owner._resource_table = QTableWidget(0, 4)
    owner._resource_table.setHorizontalHeaderLabels(["id", "name", "bound_core_id", "protocol"])
    owner._resource_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    owner._resource_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    owner._resource_table.verticalHeader().setVisible(False)
    owner._resource_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    owner._resource_add_button = QPushButton("Add Resource")
    owner._resource_remove_button = QPushButton("Remove Resource")

    owner._form_task_id = QLineEdit("t0")
    owner._form_task_name = QLineEdit("task")
    owner._form_task_type = QComboBox()
    owner._form_task_type.addItems(["dynamic_rt", "time_deterministic", "non_rt"])
    owner._form_task_arrival = QDoubleSpinBox()
    owner._form_task_arrival.setRange(0.0, 1_000_000.0)
    owner._form_task_arrival.setDecimals(3)
    owner._form_task_arrival.setValue(0.0)
    owner._form_task_period = QLineEdit("10")
    owner._form_task_deadline = QLineEdit("10")
    owner._form_task_abort_on_miss = QCheckBox("abort_on_miss")
    owner._form_task_abort_on_miss.setChecked(False)
    owner._form_subtask_id = QLineEdit("s0")
    owner._form_segment_id = QLineEdit("seg0")
    owner._form_segment_wcet = QDoubleSpinBox()
    owner._form_segment_wcet.setRange(0.001, 1_000_000.0)
    owner._form_segment_wcet.setDecimals(3)
    owner._form_segment_wcet.setValue(1.0)
    owner._form_segment_mapping_hint = QLineEdit("c0")
    owner._form_segment_required_resources = QLineEdit("")
    owner._form_segment_preemptible = QCheckBox("preemptible")
    owner._form_segment_preemptible.setChecked(True)
    owner._task_table = QTableWidget(0, 5)
    owner._task_table.setHorizontalHeaderLabels(["id", "name", "task_type", "arrival", "deadline"])
    owner._task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    owner._task_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    owner._task_table.verticalHeader().setVisible(False)
    owner._task_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    owner._task_add_button = QPushButton("Add Task")
    owner._task_remove_button = QPushButton("Remove Task")

    owner._dag_scene = QGraphicsScene(owner)
    owner._dag_view = QGraphicsView(owner._dag_scene)
    owner._dag_view.setMinimumHeight(210)
    owner._dag_overview_scene = QGraphicsScene(owner)
    owner._dag_overview_view = QGraphicsView(owner._dag_overview_scene)
    owner._dag_overview_view.setMinimumHeight(210)
    owner._dag_canvas_tabs = QTabWidget()
    owner._dag_overview_tab = None
    owner._dag_detail_tab = None
    owner._dag_subtasks_list = QListWidget()
    owner._dag_edges_list = QListWidget()
    owner._dag_new_subtask_id = QLineEdit()
    owner._dag_new_subtask_id.setPlaceholderText("new subtask id (optional)")
    owner._dag_add_subtask_button = QPushButton("Add Subtask")
    owner._dag_remove_subtask_button = QPushButton("Remove Selected Subtask")
    owner._dag_edge_src = QLineEdit()
    owner._dag_edge_src.setPlaceholderText("src id")
    owner._dag_edge_dst = QLineEdit()
    owner._dag_edge_dst.setPlaceholderText("dst id")
    owner._dag_add_edge_button = QPushButton("Add Edge")
    owner._dag_remove_edge_button = QPushButton("Remove Selected Edge")
    owner._dag_auto_layout_button = QPushButton("Auto Layout")
    owner._dag_persist_layout = QCheckBox("Persist Layout (ui_layout)")
    owner._dag_persist_layout.setChecked(False)

    owner._form_scheduler_name = QComboBox()
    owner._form_scheduler_name.addItems(["edf", "rm", "fixed_priority"])
    owner._form_tie_breaker = QComboBox()
    owner._form_tie_breaker.addItems(["fifo", "lifo", "segment_key"])
    owner._form_allow_preempt = QCheckBox("allow_preempt")
    owner._form_allow_preempt.setChecked(True)
    owner._form_event_id_mode = QComboBox()
    owner._form_event_id_mode.addItems(["deterministic", "random", "seeded_random"])
    owner._form_resource_acquire_policy = QComboBox()
    owner._form_resource_acquire_policy.addItems(["legacy_sequential", "atomic_rollback"])
    owner._form_sim_duration = QDoubleSpinBox()
    owner._form_sim_duration.setRange(0.001, 1_000_000.0)
    owner._form_sim_duration.setDecimals(3)
    owner._form_sim_duration.setValue(10.0)
    owner._form_sim_seed = QSpinBox()
    owner._form_sim_seed.setRange(-2_147_483_648, 2_147_483_647)
    owner._form_sim_seed.setValue(42)

    owner._planning_enabled = QCheckBox("planning.enabled")
    owner._planning_enabled.setChecked(False)
    owner._planning_planner = QComboBox()
    owner._planning_planner.addItems(["np_edf", "np_dm", "np_rm", "precautious_dm", "precautious_rm", "lp"])
    owner._planning_lp_objective = QComboBox()
    owner._planning_lp_objective.addItems(["response_time", "spread_execution"])
    owner._planning_task_scope = QComboBox()
    owner._planning_task_scope.addItems(["sync_only", "sync_and_dynamic_rt", "all"])
    owner._planning_include_non_rt = QCheckBox("include_non_rt")
    owner._planning_horizon = QDoubleSpinBox()
    owner._planning_horizon.setRange(0.0, 1_000_000.0)
    owner._planning_horizon.setDecimals(3)
    owner._planning_horizon.setSpecialValueText("auto")
    owner._planning_horizon.setValue(0.0)
    owner._planning_time_limit = QDoubleSpinBox()
    owner._planning_time_limit.setRange(0.1, 1_000_000.0)
    owner._planning_time_limit.setDecimals(3)
    owner._planning_time_limit.setValue(30.0)
    owner._planning_wcrt_max_iterations = QSpinBox()
    owner._planning_wcrt_max_iterations.setRange(1, 10_000)
    owner._planning_wcrt_max_iterations.setValue(64)
    owner._planning_wcrt_epsilon = QDoubleSpinBox()
    owner._planning_wcrt_epsilon.setDecimals(12)
    owner._planning_wcrt_epsilon.setRange(1e-12, 1.0)
    owner._planning_wcrt_epsilon.setValue(1e-9)
    owner._planning_plan_button = QPushButton("Plan Static")
    owner._planning_wcrt_button = QPushButton("Analyze WCRT")
    owner._planning_export_button = QPushButton("Export OS Config")

    owner._planning_random_seed = QSpinBox()
    owner._planning_random_seed.setRange(-2_147_483_648, 2_147_483_647)
    owner._planning_random_seed.setValue(20260304)
    owner._planning_random_load_tier = QComboBox()
    owner._planning_random_load_tier.addItems(["low", "medium", "high"])
    owner._planning_random_rule = QComboBox()
    owner._planning_random_rule.addItems(["single_chain", "fork_join"])
    owner._planning_random_task_count = QSpinBox()
    owner._planning_random_task_count.setRange(1, 64)
    owner._planning_random_task_count.setValue(3)
    owner._planning_random_generate_button = QPushButton("Generate Random Tasks")

    owner._planning_windows_table = QTableWidget(0, 8)
    owner._planning_windows_table.setHorizontalHeaderLabels(
        ["segment_key", "task_id", "subtask_id", "segment_id", "core_id", "start", "end", "deadline"]
    )
    owner._planning_windows_table.verticalHeader().setVisible(False)
    owner._planning_windows_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    owner._planning_wcrt_table = QTableWidget(0, 4)
    owner._planning_wcrt_table.setHorizontalHeaderLabels(["task_id", "wcrt", "deadline", "schedulable"])
    owner._planning_wcrt_table.verticalHeader().setVisible(False)
    owner._planning_wcrt_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    owner._planning_os_table = QTableWidget(0, 7)
    owner._planning_os_table.setHorizontalHeaderLabels(
        ["task_id", "priority", "core_binding", "primary_core", "window_count", "deadline", "total_wcet"]
    )
    owner._planning_os_table.verticalHeader().setVisible(False)
    owner._planning_os_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    owner._planning_output = QPlainTextEdit()
    owner._planning_output.setReadOnly(True)
    owner._planning_output.setMaximumHeight(180)

    owner._validate_button = QPushButton("Validate")
    owner._run_button = QPushButton("Run")
    owner._stop_button = QPushButton("Stop")
    owner._pause_button = QPushButton("Pause")
    owner._resume_button = QPushButton("Resume")
    owner._step_button = QPushButton("Step")
    owner._reset_button = QPushButton("Reset")
    owner._research_export_button = QPushButton("Export Research Report")
    owner._step_delta_spin = QDoubleSpinBox()
    owner._step_delta_spin.setRange(0.0, 1_000_000.0)
    owner._step_delta_spin.setDecimals(3)
    owner._step_delta_spin.setSingleStep(0.1)
    owner._step_delta_spin.setSpecialValueText("auto")
    owner._step_delta_spin.setValue(0.0)
    owner._load_button = QPushButton("Load")
    owner._save_button = QPushButton("Save")
    owner._status_label = QLabel("Ready")
    owner._status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    owner._plot = pg.PlotWidget(title="Gantt (CPU Lanes)")
    owner._plot.showGrid(x=True, y=True)
    owner._plot.setLabel("bottom", "Time")
    owner._plot.setLabel("left", "Core")
    owner._plot.addLegend(offset=(10, 10))
    owner._plot.setMinimumHeight(320)

    owner._legend_toggle_subtask = QPushButton("Subtask Legend")
    owner._legend_toggle_subtask.setCheckable(True)
    owner._legend_toggle_segment = QPushButton("Segment Legend")
    owner._legend_toggle_segment.setCheckable(True)

    owner._legend_detail = QPlainTextEdit()
    owner._legend_detail.setReadOnly(True)
    owner._legend_detail.setMaximumHeight(120)
    owner._legend_detail.hide()

    owner._hover_hint = QLabel("Hover a segment for details. Click segment to lock/unlock.")

    owner._metrics = QTextEdit()
    owner._metrics.setReadOnly(True)

    owner._state_legend = QLabel("State Legend: Released / Ready / Executing / Blocked")
    owner._state_view = QPlainTextEdit()
    owner._state_view.setReadOnly(True)
    owner._state_view.setMaximumHeight(150)

    owner._details = QPlainTextEdit()
    owner._details.setReadOnly(True)
    owner._details.setMaximumHeight(200)

    owner._compare_left_label = QLineEdit("")
    owner._compare_right_label = QLineEdit("")
    owner._compare_scenario_label = QLineEdit("")
    owner._compare_scenario_label.setPlaceholderText("optional label for next added scenario")
    owner._compare_scenarios_list = QListWidget()
    owner._compare_scenarios_list.setMinimumHeight(104)
    owner._compare_add_metrics_button = QPushButton("Add Metrics File")
    owner._compare_add_latest_button = QPushButton("Add Latest Run")
    owner._compare_remove_selected_button = QPushButton("Remove Selected")
    owner._compare_move_up_button = QPushButton("Move Up")
    owner._compare_move_down_button = QPushButton("Move Down")
    owner._compare_load_left_button = QPushButton("Load Left Metrics")
    owner._compare_load_right_button = QPushButton("Load Right Metrics")
    owner._compare_use_latest_left_button = QPushButton("Use Latest -> Left")
    owner._compare_use_latest_right_button = QPushButton("Use Latest -> Right")
    owner._compare_build_button = QPushButton("Build Compare")
    owner._compare_export_json_button = QPushButton("Export Compare JSON")
    owner._compare_export_csv_button = QPushButton("Export Compare CSV")
    owner._compare_export_markdown_button = QPushButton("Export Compare Markdown")
    owner._compare_output = QPlainTextEdit()
    owner._compare_output.setReadOnly(True)
    owner._compare_output.setMinimumHeight(120)
    owner._compare_output.setMaximumHeight(220)
    owner._compare_toggle_button = QPushButton("Show FR-13 Compare")
    owner._compare_toggle_button.setCheckable(True)
    owner._compare_group = None
    owner._telemetry_scroll = None
    owner._right_splitter = None

    owner._compare_controller = CompareController(owner, error_logger)
    owner._form_controller = FormController(owner, error_logger)
    owner._document_sync_controller = DocumentSyncController(owner, error_logger)
    owner._table_editor_controller = TableEditorController(owner)
    owner._dag_controller = DagController(owner)
    owner._dag_overview_controller = DagOverviewController(owner)
    owner._gantt_style_controller = GanttStyleController(owner)
    owner._planning_controller = PlanningController(owner, error_logger)
    owner._research_report_controller = ResearchReportController(owner, error_logger)
    owner._run_controller = RunController(owner, error_logger)
    owner._telemetry_controller = TelemetryController(owner)
    owner._timeline_controller = TimelineController(owner)

    build_main_window_layout(owner)
    connect_main_window_signals(owner)


def build_main_window_layout(owner: MainWindow) -> None:
    root = QWidget(owner)
    root_layout = QVBoxLayout(root)

    toolbar = QHBoxLayout()
    toolbar.addWidget(owner._load_button)
    toolbar.addWidget(owner._save_button)
    toolbar.addWidget(owner._validate_button)
    toolbar.addWidget(owner._run_button)
    toolbar.addWidget(owner._stop_button)
    toolbar.addWidget(owner._pause_button)
    toolbar.addWidget(owner._resume_button)
    toolbar.addWidget(owner._step_button)
    toolbar.addWidget(QLabel("Step Δ"))
    toolbar.addWidget(owner._step_delta_spin)
    toolbar.addWidget(owner._reset_button)
    toolbar.addWidget(owner._research_export_button)
    toolbar.addStretch(1)
    toolbar.addWidget(owner._status_label)
    root_layout.addLayout(toolbar)

    splitter = QSplitter(Qt.Orientation.Horizontal)

    editor_container = QWidget()
    editor_layout = QVBoxLayout(editor_container)
    editor_layout.addWidget(QLabel("Config Editor"))

    form_tab = QWidget()
    form_tab_layout = QVBoxLayout(form_tab)
    sync_toolbar = QHBoxLayout()
    sync_toolbar.addWidget(owner._sync_text_to_form_button)
    sync_toolbar.addWidget(owner._sync_form_to_text_button)
    sync_toolbar.addStretch(1)
    sync_toolbar.addWidget(owner._form_hint)
    form_tab_layout.addLayout(sync_toolbar)

    form_content = QWidget()
    form_content_layout = QVBoxLayout(form_content)

    platform_group = QGroupBox("Platform")
    platform_form = QFormLayout(platform_group)
    platform_form.addRow("processor_type.id", owner._form_processor_id)
    platform_form.addRow("processor_type.name", owner._form_processor_name)
    platform_form.addRow("processor_type.core_count", owner._form_processor_core_count)
    platform_form.addRow("processor_type.speed_factor", owner._form_processor_speed)
    platform_form.addRow("core.id", owner._form_core_id)
    platform_form.addRow("core.speed_factor", owner._form_core_speed)
    form_content_layout.addWidget(platform_group)

    resource_group = QGroupBox("Resources (Table + Selected Detail)")
    resource_layout = QVBoxLayout(resource_group)
    resource_layout.addWidget(owner._resource_table)
    resource_button_row = QHBoxLayout()
    resource_button_row.addWidget(owner._resource_add_button)
    resource_button_row.addWidget(owner._resource_remove_button)
    resource_button_row.addStretch(1)
    resource_layout.addLayout(resource_button_row)
    resource_form = QFormLayout()
    resource_form.addRow(owner._form_resource_enabled)
    resource_form.addRow("selected resource.id", owner._form_resource_id)
    resource_form.addRow("selected resource.name", owner._form_resource_name)
    resource_form.addRow("selected resource.bound_core_id", owner._form_resource_bound_core)
    resource_form.addRow("selected resource.protocol", owner._form_resource_protocol)
    resource_layout.addLayout(resource_form)
    form_content_layout.addWidget(resource_group)

    task_group = QGroupBox("Tasks (Table + DAG Workbench + Selected Detail)")
    task_layout = QVBoxLayout(task_group)
    task_layout.addWidget(owner._task_table)
    task_button_row = QHBoxLayout()
    task_button_row.addWidget(owner._task_add_button)
    task_button_row.addWidget(owner._task_remove_button)
    task_button_row.addStretch(1)
    task_layout.addLayout(task_button_row)
    task_layout.addWidget(build_dag_workbench_group(owner))

    task_form = QFormLayout()
    task_form.addRow("selected task.id", owner._form_task_id)
    task_form.addRow("selected task.name", owner._form_task_name)
    task_form.addRow("selected task.task_type", owner._form_task_type)
    task_form.addRow("selected task.arrival", owner._form_task_arrival)
    task_form.addRow("selected task.period (optional)", owner._form_task_period)
    task_form.addRow("selected task.deadline (optional)", owner._form_task_deadline)
    task_form.addRow(owner._form_task_abort_on_miss)
    task_form.addRow("selected subtask.id", owner._form_subtask_id)
    task_form.addRow("selected segment.id", owner._form_segment_id)
    task_form.addRow("selected segment.wcet", owner._form_segment_wcet)
    task_form.addRow("selected segment.mapping_hint (optional)", owner._form_segment_mapping_hint)
    task_form.addRow(
        "segment.required_resources (comma separated)",
        owner._form_segment_required_resources,
    )
    task_form.addRow(owner._form_segment_preemptible)
    task_layout.addLayout(task_form)
    form_content_layout.addWidget(task_group)

    runtime_group = QGroupBox("Scheduler / Simulation")
    runtime_form = QFormLayout(runtime_group)
    runtime_form.addRow("scheduler.name", owner._form_scheduler_name)
    runtime_form.addRow("scheduler.params.tie_breaker", owner._form_tie_breaker)
    runtime_form.addRow(owner._form_allow_preempt)
    runtime_form.addRow("scheduler.params.event_id_mode", owner._form_event_id_mode)
    runtime_form.addRow(
        "scheduler.params.resource_acquire_policy",
        owner._form_resource_acquire_policy,
    )
    runtime_form.addRow("sim.duration", owner._form_sim_duration)
    runtime_form.addRow("sim.seed", owner._form_sim_seed)
    form_content_layout.addWidget(runtime_group)
    form_content_layout.addStretch(1)

    form_scroll = QScrollArea()
    form_scroll.setWidgetResizable(True)
    form_scroll.setWidget(form_content)
    form_tab_layout.addWidget(form_scroll)

    text_tab = QWidget()
    text_tab_layout = QVBoxLayout(text_tab)
    text_tab_layout.addWidget(QLabel("YAML / JSON Text"))
    text_tab_layout.addWidget(owner._editor)

    planning_tab = build_planning_tab(owner)

    owner._editor_tabs.addTab(form_tab, "Structured Form")
    owner._editor_tabs.addTab(text_tab, "YAML/JSON")
    owner._editor_tabs.addTab(planning_tab, "Planning")
    editor_layout.addWidget(owner._editor_tabs)
    splitter.addWidget(editor_container)

    viz_container = QWidget()
    viz_layout = QVBoxLayout(viz_container)

    gantt_panel = QWidget()
    gantt_panel_layout = QVBoxLayout(gantt_panel)
    gantt_panel_layout.addWidget(owner._plot, stretch=1)

    legend_toolbar = QHBoxLayout()
    legend_toolbar.addWidget(QLabel("Legend"))
    legend_toolbar.addWidget(owner._legend_toggle_subtask)
    legend_toolbar.addWidget(owner._legend_toggle_segment)
    legend_toolbar.addStretch(1)
    gantt_panel_layout.addLayout(legend_toolbar)
    gantt_panel_layout.addWidget(owner._legend_detail)
    gantt_panel_layout.addWidget(owner._hover_hint)

    telemetry_panel = QWidget()
    telemetry_layout = QVBoxLayout(telemetry_panel)
    telemetry_layout.addWidget(QLabel("Metrics / Logs"))
    telemetry_layout.addWidget(owner._metrics, stretch=2)
    telemetry_layout.addWidget(owner._state_legend)
    telemetry_layout.addWidget(owner._state_view, stretch=1)
    telemetry_layout.addWidget(QLabel("Segment Details (Hover/Click lock)"))
    telemetry_layout.addWidget(owner._details, stretch=2)
    telemetry_layout.addWidget(owner._compare_toggle_button)

    owner._compare_group = build_compare_group(owner)
    owner._compare_group.setVisible(False)
    telemetry_layout.addWidget(owner._compare_group)

    owner._telemetry_scroll = QScrollArea()
    owner._telemetry_scroll.setWidgetResizable(True)
    owner._telemetry_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    owner._telemetry_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    owner._telemetry_scroll.setWidget(telemetry_panel)

    owner._right_splitter = QSplitter(Qt.Orientation.Vertical)
    owner._right_splitter.addWidget(gantt_panel)
    owner._right_splitter.addWidget(owner._telemetry_scroll)
    owner._right_splitter.setCollapsible(0, False)
    owner._right_splitter.setCollapsible(1, False)
    owner._right_splitter.setStretchFactor(0, 3)
    owner._right_splitter.setStretchFactor(1, 2)
    owner._right_splitter.setSizes([520, 300])
    viz_layout.addWidget(owner._right_splitter)

    splitter.addWidget(viz_container)
    splitter.setSizes([560, 940])

    root_layout.addWidget(splitter)
    owner.setCentralWidget(root)
    owner._set_worker_controls(running=False, paused=False)


def register_form_change_signals(owner: MainWindow) -> None:
    line_edits = [
        owner._form_processor_id,
        owner._form_processor_name,
        owner._form_core_id,
        owner._form_resource_id,
        owner._form_resource_name,
        owner._form_resource_bound_core,
        owner._form_task_id,
        owner._form_task_name,
        owner._form_task_period,
        owner._form_task_deadline,
        owner._form_subtask_id,
        owner._form_segment_id,
        owner._form_segment_mapping_hint,
        owner._form_segment_required_resources,
    ]
    for widget in line_edits:
        widget.textChanged.connect(owner._mark_form_dirty)

    combo_boxes = [
        owner._form_resource_protocol,
        owner._form_task_type,
        owner._form_scheduler_name,
        owner._form_tie_breaker,
        owner._form_event_id_mode,
        owner._form_resource_acquire_policy,
        owner._planning_planner,
        owner._planning_lp_objective,
        owner._planning_task_scope,
        owner._planning_random_load_tier,
        owner._planning_random_rule,
    ]
    for widget in combo_boxes:
        widget.currentIndexChanged.connect(owner._mark_form_dirty)

    check_boxes = [
        owner._form_resource_enabled,
        owner._form_task_abort_on_miss,
        owner._form_segment_preemptible,
        owner._form_allow_preempt,
        owner._planning_enabled,
        owner._planning_include_non_rt,
    ]
    for widget in check_boxes:
        widget.toggled.connect(owner._mark_form_dirty)

    spins = [
        owner._form_processor_core_count,
        owner._form_processor_speed,
        owner._form_core_speed,
        owner._form_task_arrival,
        owner._form_segment_wcet,
        owner._form_sim_duration,
        owner._form_sim_seed,
        owner._planning_horizon,
        owner._planning_time_limit,
        owner._planning_wcrt_max_iterations,
        owner._planning_wcrt_epsilon,
        owner._planning_random_seed,
        owner._planning_random_task_count,
    ]
    for widget in spins:
        widget.valueChanged.connect(owner._mark_form_dirty)


def connect_main_window_signals(owner: MainWindow) -> None:
    owner._load_button.clicked.connect(owner._pick_load_file)
    owner._save_button.clicked.connect(owner._pick_save_file)
    owner._validate_button.clicked.connect(owner._on_validate)
    owner._run_button.clicked.connect(owner._on_run)
    owner._stop_button.clicked.connect(owner._on_stop)
    owner._pause_button.clicked.connect(owner._on_pause)
    owner._resume_button.clicked.connect(owner._on_resume)
    owner._step_button.clicked.connect(owner._on_step)
    owner._reset_button.clicked.connect(owner._on_reset)
    owner._research_export_button.clicked.connect(owner._on_research_export)
    owner._sync_text_to_form_button.clicked.connect(owner._on_sync_text_to_form)
    owner._sync_form_to_text_button.clicked.connect(owner._on_sync_form_to_text)
    owner._legend_toggle_subtask.toggled.connect(owner._refresh_legend_details)
    owner._legend_toggle_segment.toggled.connect(owner._refresh_legend_details)
    owner._task_add_button.clicked.connect(owner._on_add_task)
    owner._task_remove_button.clicked.connect(owner._on_remove_task)
    owner._resource_add_button.clicked.connect(owner._on_add_resource)
    owner._resource_remove_button.clicked.connect(owner._on_remove_resource)
    owner._task_table.itemSelectionChanged.connect(owner._on_task_selection_changed)
    owner._resource_table.itemSelectionChanged.connect(owner._on_resource_selection_changed)
    owner._task_table.cellChanged.connect(owner._on_task_table_cell_changed)
    owner._resource_table.cellChanged.connect(owner._on_resource_table_cell_changed)
    owner._dag_subtasks_list.itemSelectionChanged.connect(owner._on_dag_subtask_selected)
    owner._dag_add_subtask_button.clicked.connect(owner._on_dag_add_subtask)
    owner._dag_remove_subtask_button.clicked.connect(owner._on_dag_remove_subtask)
    owner._dag_add_edge_button.clicked.connect(owner._on_dag_add_edge)
    owner._dag_remove_edge_button.clicked.connect(owner._on_dag_remove_edge)
    owner._dag_auto_layout_button.clicked.connect(owner._on_dag_auto_layout)
    owner._dag_persist_layout.toggled.connect(owner._on_dag_persist_layout_toggled)
    owner._dag_canvas_tabs.currentChanged.connect(owner._on_dag_canvas_tab_changed)
    owner._compare_toggle_button.toggled.connect(owner._on_compare_toggle)
    owner._compare_add_metrics_button.clicked.connect(owner._on_compare_add_metrics)
    owner._compare_add_latest_button.clicked.connect(owner._on_compare_add_latest)
    owner._compare_remove_selected_button.clicked.connect(owner._on_compare_remove_selected)
    owner._compare_move_up_button.clicked.connect(owner._on_compare_move_up)
    owner._compare_move_down_button.clicked.connect(owner._on_compare_move_down)
    owner._compare_load_left_button.clicked.connect(owner._on_compare_load_left)
    owner._compare_load_right_button.clicked.connect(owner._on_compare_load_right)
    owner._compare_use_latest_left_button.clicked.connect(owner._on_compare_use_latest_left)
    owner._compare_use_latest_right_button.clicked.connect(owner._on_compare_use_latest_right)
    owner._compare_build_button.clicked.connect(owner._on_compare_build)
    owner._compare_export_json_button.clicked.connect(owner._on_compare_export_json)
    owner._compare_export_csv_button.clicked.connect(owner._on_compare_export_csv)
    owner._compare_export_markdown_button.clicked.connect(owner._on_compare_export_markdown)
    owner._planning_plan_button.clicked.connect(owner._on_plan_static)
    owner._planning_wcrt_button.clicked.connect(owner._on_plan_analyze_wcrt)
    owner._planning_export_button.clicked.connect(owner._on_plan_export_os_config)
    owner._planning_random_generate_button.clicked.connect(owner._on_plan_generate_random_tasks)

    owner._editor.textChanged.connect(owner._on_text_edited)
    register_form_change_signals(owner)

    scene = owner._plot.scene()
    scene.sigMouseMoved.connect(owner._on_plot_mouse_moved)
    scene.sigMouseClicked.connect(owner._on_plot_mouse_clicked)
