"""Reusable UI panel builders for MainWindow layout assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:  # pragma: no cover - type-only import to avoid circular dependency
    from .app import MainWindow


def build_planning_tab(owner: MainWindow) -> QWidget:
    planning_tab = QWidget()
    planning_layout = QVBoxLayout(planning_tab)

    planning_group = QGroupBox("Offline Planning")
    planning_form = QFormLayout(planning_group)
    planning_form.addRow(owner._planning_enabled)
    planning_form.addRow("planner", owner._planning_planner)
    planning_form.addRow("lp_objective", owner._planning_lp_objective)
    planning_form.addRow("task_scope", owner._planning_task_scope)
    planning_form.addRow(owner._planning_include_non_rt)
    planning_form.addRow("horizon", owner._planning_horizon)
    planning_form.addRow("time_limit_seconds", owner._planning_time_limit)
    planning_form.addRow("wcrt_max_iterations", owner._planning_wcrt_max_iterations)
    planning_form.addRow("wcrt_epsilon", owner._planning_wcrt_epsilon)
    planning_layout.addWidget(planning_group)

    planning_actions = QHBoxLayout()
    planning_actions.addWidget(owner._planning_plan_button)
    planning_actions.addWidget(owner._planning_wcrt_button)
    planning_actions.addWidget(owner._planning_export_button)
    planning_actions.addStretch(1)
    planning_layout.addLayout(planning_actions)

    random_group = QGroupBox("Random Task Generator")
    random_form = QFormLayout(random_group)
    random_form.addRow("seed", owner._planning_random_seed)
    random_form.addRow("load_tier", owner._planning_random_load_tier)
    random_form.addRow("rule", owner._planning_random_rule)
    random_form.addRow("task_count", owner._planning_random_task_count)
    random_form.addRow(owner._planning_random_generate_button)
    planning_layout.addWidget(random_group)

    planning_result_tabs = QTabWidget()
    planning_result_tabs.addTab(owner._planning_windows_table, "Schedule")
    planning_result_tabs.addTab(owner._planning_wcrt_table, "WCRT")
    planning_result_tabs.addTab(owner._planning_os_table, "OS Config")
    planning_layout.addWidget(planning_result_tabs, stretch=1)
    planning_layout.addWidget(QLabel("Planning Logs"))
    planning_layout.addWidget(owner._planning_output)
    return planning_tab


def build_compare_group(owner: MainWindow) -> QGroupBox:
    compare_group = QGroupBox("FR-13 Compare")
    compare_layout = QVBoxLayout(compare_group)
    compare_layout.addWidget(QLabel("Ordered scenarios (#1 baseline, #2 focus)"))
    compare_layout.addWidget(owner._compare_scenarios_list)

    compare_label_form = QFormLayout()
    compare_label_form.addRow("new scenario label", owner._compare_scenario_label)
    compare_layout.addLayout(compare_label_form)

    compare_actions_grid = QGridLayout()
    compare_actions_grid.addWidget(owner._compare_add_metrics_button, 0, 0)
    compare_actions_grid.addWidget(owner._compare_add_latest_button, 0, 1)
    compare_actions_grid.addWidget(owner._compare_remove_selected_button, 1, 0)
    compare_actions_grid.addWidget(owner._compare_move_up_button, 1, 1)
    compare_actions_grid.addWidget(owner._compare_move_down_button, 2, 0, 1, 2)
    compare_actions_grid.setColumnStretch(0, 1)
    compare_actions_grid.setColumnStretch(1, 1)
    compare_layout.addLayout(compare_actions_grid)

    compare_export_grid = QGridLayout()
    compare_export_grid.addWidget(owner._compare_build_button, 0, 0)
    compare_export_grid.addWidget(owner._compare_export_json_button, 0, 1)
    compare_export_grid.addWidget(owner._compare_export_csv_button, 1, 0)
    compare_export_grid.addWidget(owner._compare_export_markdown_button, 1, 1)
    compare_export_grid.setColumnStretch(0, 1)
    compare_export_grid.setColumnStretch(1, 1)
    compare_layout.addLayout(compare_export_grid)
    compare_layout.addWidget(owner._compare_output)
    return compare_group


def build_dag_workbench_group(owner: MainWindow) -> QGroupBox:
    dag_group = QGroupBox("DAG Workbench")
    dag_layout = QVBoxLayout(dag_group)

    overview_tab = QWidget()
    overview_layout = QVBoxLayout(overview_tab)
    overview_layout.addWidget(QLabel("Cross-task overview. Click a task card to open its detail canvas."))
    overview_layout.addWidget(owner._dag_overview_view, stretch=1)

    detail_tab = QWidget()
    detail_layout = QHBoxLayout(detail_tab)
    detail_layout.addWidget(owner._dag_view, stretch=2)

    dag_side = QVBoxLayout()
    dag_actions_row = QHBoxLayout()
    dag_actions_row.addWidget(owner._dag_auto_layout_button)
    dag_actions_row.addWidget(owner._dag_persist_layout)
    dag_actions_row.addStretch(1)
    dag_side.addLayout(dag_actions_row)
    dag_side.addWidget(QLabel("Subtasks"))
    dag_side.addWidget(owner._dag_subtasks_list)
    dag_subtask_add_row = QHBoxLayout()
    dag_subtask_add_row.addWidget(owner._dag_new_subtask_id)
    dag_subtask_add_row.addWidget(owner._dag_add_subtask_button)
    dag_side.addLayout(dag_subtask_add_row)
    dag_side.addWidget(owner._dag_remove_subtask_button)
    dag_side.addWidget(QLabel("Edges"))
    dag_side.addWidget(owner._dag_edges_list)
    dag_edge_row = QHBoxLayout()
    dag_edge_row.addWidget(owner._dag_edge_src)
    dag_edge_row.addWidget(owner._dag_edge_dst)
    dag_side.addLayout(dag_edge_row)
    dag_edge_button_row = QHBoxLayout()
    dag_edge_button_row.addWidget(owner._dag_add_edge_button)
    dag_edge_button_row.addWidget(owner._dag_remove_edge_button)
    dag_side.addLayout(dag_edge_button_row)
    detail_layout.addLayout(dag_side, stretch=1)

    owner._dag_canvas_tabs.clear()
    owner._dag_canvas_tabs.addTab(overview_tab, "Overview")
    owner._dag_canvas_tabs.addTab(detail_tab, "Task Detail")
    owner._dag_overview_tab = overview_tab
    owner._dag_detail_tab = detail_tab
    owner._dag_canvas_tabs.setCurrentIndex(1)
    dag_layout.addWidget(owner._dag_canvas_tabs)
    return dag_group
