from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication
import yaml

from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigLoader
from rtos_sim.ui.app import MainWindow


APP = QApplication.instance() or QApplication([])


class _DummyClickEvent:
    def __init__(self, scene_pos) -> None:
        self._scene_pos = scene_pos
        self.accepted = False

    def scenePos(self):
        return self._scene_pos

    def accept(self) -> None:
        self.accepted = True


def _render_example(example_name: str) -> MainWindow:
    assert APP is not None
    loader = ConfigLoader()
    spec = loader.load(f"examples/{example_name}")
    engine = SimEngine()
    engine.build(spec)
    engine.run()

    events = [event.model_dump(mode="json") for event in engine.events]
    window = MainWindow(config_path=f"examples/{example_name}")
    window._on_finished(engine.metric_report(), events)
    return window


def test_ui_cpu_lane_and_preempt_visuals() -> None:
    window = _render_example("at05_preempt.yaml")
    try:
        assert set(window._core_to_y) == {"c0"}
        assert len(window._segment_items) == 3

        statuses = {item.meta.status for item in window._segment_items}
        assert "Preempted" in statuses
        assert "Completed" in statuses

        text = window._metrics.toPlainText()
        assert text.count("[Segment]") == 3
        assert "[Preempt] low@0:s0:seg0 at t=1.000" in text

        preempted = [item.meta for item in window._segment_items if item.meta.status == "Preempted"][0]
        detail = window._format_segment_details(preempted)
        assert "task_id: low" in detail
        assert "subtask_id: s0" in detail
        assert "remaining_after_preempt:" in detail
    finally:
        window.close()


def test_ui_legend_hierarchy_and_styles() -> None:
    window = _render_example("at01_single_dag_single_core.yaml")
    try:
        assert ("t0", "s0") in window._subtask_legend_map
        assert ("t0", "s1") in window._subtask_legend_map
        assert "seg0" in window._segment_legend_map
        assert "seg1" in window._segment_legend_map

        window._legend_toggle_subtask.setChecked(True)
        window._legend_toggle_segment.setChecked(True)
        legend_text = window._legend_detail.toPlainText()
        assert "Subtask Legend" in legend_text
        assert "Segment Legend" in legend_text
        assert "t0/s0" in legend_text
        assert "seg0" in legend_text
    finally:
        window.close()


def test_ui_hover_preview_and_click_lock() -> None:
    window = _render_example("at05_preempt.yaml")
    try:
        first = window._segment_items[0]
        window.show()
        APP.processEvents()
        scene_pos = first.sceneBoundingRect().center()

        window._on_plot_mouse_moved(scene_pos)
        assert window._hovered_segment_key is not None
        hovered_key = window._hovered_segment_key
        assert "segment_key:" in window._details.toPlainText()

        click_event = _DummyClickEvent(scene_pos)
        window._on_plot_mouse_clicked(click_event)
        assert click_event.accepted
        assert window._locked_segment_key == hovered_key

        window._on_plot_mouse_clicked(click_event)
        assert window._locked_segment_key is None
    finally:
        window.close()


def test_ui_structured_form_apply_to_text() -> None:
    window = MainWindow(config_path="examples/at05_preempt.yaml")
    try:
        assert window._form_task_id.text() == "low"

        window._form_task_id.setText("demo")
        window._form_task_name.setText("demo-task")
        window._form_task_type.setCurrentText("time_deterministic")
        window._form_task_period.setText("12")
        window._form_task_deadline.setText("12")
        window._form_segment_wcet.setValue(2.5)
        window._form_scheduler_name.setCurrentText("rm")
        window._form_tie_breaker.setCurrentText("lifo")
        window._form_allow_preempt.setChecked(False)
        window._form_event_id_mode.setCurrentText("random")
        window._form_sim_seed.setValue(99)
        window._form_resource_enabled.setChecked(True)
        window._form_resource_id.setText("r0")
        window._form_resource_name.setText("lock")
        window._form_resource_bound_core.setText("c0")
        window._form_resource_protocol.setCurrentText("pcp")
        window._form_segment_required_resources.setText("r0")

        window._on_sync_form_to_text()
        payload = yaml.safe_load(window._editor.toPlainText())

        assert payload["tasks"][0]["id"] == "demo"
        assert payload["tasks"][0]["task_type"] == "time_deterministic"
        assert payload["tasks"][0]["subtasks"][0]["segments"][0]["wcet"] == 2.5
        assert payload["tasks"][0]["subtasks"][0]["segments"][0]["required_resources"] == ["r0"]
        assert payload["scheduler"]["name"] == "rm"
        assert payload["scheduler"]["params"]["tie_breaker"] == "lifo"
        assert payload["scheduler"]["params"]["allow_preempt"] is False
        assert payload["scheduler"]["params"]["event_id_mode"] == "random"
        assert payload["sim"]["seed"] == 99
        assert payload["resources"][0]["protocol"] == "pcp"
    finally:
        window.close()


def test_ui_structured_form_sync_from_text() -> None:
    window = MainWindow()
    try:
        window._editor.setPlainText(
            """
version: "0.2"
platform:
  processor_types:
    - id: PX
      name: procx
      core_count: 2
      speed_factor: 1.2
  cores:
    - id: cx
      type_id: PX
      speed_factor: 1.1
resources:
  - id: r0
    name: lock
    bound_core_id: cx
    protocol: pip
tasks:
  - id: t0
    name: t0
    task_type: dynamic_rt
    deadline: 15
    arrival: 1
    subtasks:
      - id: s0
        predecessors: []
        successors: []
        segments:
          - id: seg0
            index: 1
            wcet: 3
            mapping_hint: cx
            required_resources: [r0]
scheduler:
  name: edf
  params:
    tie_breaker: segment_key
    allow_preempt: true
    event_id_mode: seeded_random
sim:
  duration: 30
  seed: 123
""".strip()
        )

        window._on_sync_text_to_form()

        assert window._form_processor_id.text() == "PX"
        assert window._form_processor_core_count.value() == 2
        assert window._form_core_id.text() == "cx"
        assert window._form_resource_enabled.isChecked() is True
        assert window._form_resource_protocol.currentText() == "pip"
        assert window._form_task_id.text() == "t0"
        assert window._form_segment_mapping_hint.text() == "cx"
        assert window._form_segment_required_resources.text() == "r0"
        assert window._form_tie_breaker.currentText() == "segment_key"
        assert window._form_event_id_mode.currentText() == "seeded_random"
        assert window._form_sim_seed.value() == 123
    finally:
        window.close()


def test_ui_table_crud_for_tasks_and_resources() -> None:
    window = MainWindow(config_path="examples/at05_preempt.yaml")
    try:
        assert window._task_table.rowCount() == 2
        assert window._resource_table.rowCount() == 0

        window._on_add_task()
        assert window._task_table.rowCount() == 3
        window._task_table.selectRow(2)
        APP.processEvents()
        window._task_table.item(2, 0).setText("extra")
        window._task_table.item(2, 1).setText("extra-task")

        window._on_add_resource()
        assert window._resource_table.rowCount() == 1
        window._resource_table.selectRow(0)
        APP.processEvents()
        window._resource_table.item(0, 0).setText("r_new")
        window._resource_table.item(0, 3).setText("pcp")

        window._on_sync_form_to_text()
        payload = yaml.safe_load(window._editor.toPlainText())

        task_ids = {task["id"] for task in payload["tasks"]}
        assert "extra" in task_ids
        assert payload["resources"][0]["id"] == "r_new"
        assert payload["resources"][0]["protocol"] == "pcp"
    finally:
        window.close()


def test_ui_dag_sidebar_edit_sync() -> None:
    window = MainWindow(config_path="examples/at01_single_dag_single_core.yaml")
    try:
        assert window._dag_subtasks_list.count() == 2

        window._dag_new_subtask_id.setText("s2")
        window._on_dag_add_subtask()
        assert window._dag_subtasks_list.count() == 3

        window._dag_edge_src.setText("s1")
        window._dag_edge_dst.setText("s2")
        window._on_dag_add_edge()
        edges_text = [window._dag_edges_list.item(i).text() for i in range(window._dag_edges_list.count())]
        assert "s1 -> s2" in edges_text

        for i in range(window._dag_edges_list.count()):
            if window._dag_edges_list.item(i).text() == "s1 -> s2":
                window._dag_edges_list.setCurrentRow(i)
                break
        window._on_dag_remove_edge()
        edges_text = [window._dag_edges_list.item(i).text() for i in range(window._dag_edges_list.count())]
        assert "s1 -> s2" not in edges_text

        window._on_sync_form_to_text()
        payload = yaml.safe_load(window._editor.toPlainText())
        task = payload["tasks"][0]
        ids = {sub["id"] for sub in task["subtasks"]}
        assert "s2" in ids
    finally:
        window.close()


def test_ui_unknown_fields_preserved_after_form_edit() -> None:
    window = MainWindow()
    try:
        window._editor.setPlainText(
            """
version: "0.2"
meta:
  owner: test-owner
platform:
  processor_types:
    - id: CPU
      name: cpu
      core_count: 1
      speed_factor: 1.0
      custom_flag: keep-me
  cores:
    - id: c0
      type_id: CPU
      speed_factor: 1.0
resources:
  - id: r0
    name: lock
    bound_core_id: c0
    protocol: mutex
    custom_resource_field: keep-resource
tasks:
  - id: t0
    name: base
    task_type: dynamic_rt
    deadline: 10
    arrival: 0
    custom_task_field: keep-task
    subtasks:
      - id: s0
        predecessors: []
        successors: []
        segments:
          - id: seg0
            index: 1
            wcet: 1
            required_resources: []
scheduler:
  name: edf
  params:
    tie_breaker: fifo
sim:
  duration: 10
  seed: 42
""".strip()
        )
        window._on_sync_text_to_form()

        window._form_task_name.setText("edited-name")
        window._on_sync_form_to_text()
        payload = yaml.safe_load(window._editor.toPlainText())

        assert payload["meta"]["owner"] == "test-owner"
        assert payload["platform"]["processor_types"][0]["custom_flag"] == "keep-me"
        assert payload["resources"][0]["custom_resource_field"] == "keep-resource"
        assert payload["tasks"][0]["custom_task_field"] == "keep-task"
        assert payload["tasks"][0]["name"] == "edited-name"
    finally:
        window.close()


def test_ui_dag_drag_edge_cycle_rejected() -> None:
    window = MainWindow(config_path="examples/at01_single_dag_single_core.yaml")
    try:
        src = window._dag_scene_pos_for_subtask("s1")
        dst = window._dag_scene_pos_for_subtask("s0")
        assert src is not None
        assert dst is not None

        window._start_dag_link_drag("s1", src)
        window._update_dag_link_drag(dst)
        window._finish_dag_link_drag(dst)

        edges_text = [window._dag_edges_list.item(i).text() for i in range(window._dag_edges_list.count())]
        assert "s1 -> s0" not in edges_text
        assert "creates a cycle" in window._form_hint.text()
    finally:
        window.close()


def test_ui_table_validation_highlight_and_block_apply() -> None:
    window = MainWindow(config_path="examples/at05_preempt.yaml")
    try:
        window._on_add_task()
        invalid_row = window._task_table.rowCount() - 1
        window._task_table.item(invalid_row, 3).setText("abc")
        APP.processEvents()

        assert window._has_table_validation_errors() is True
        assert "arrival must be number" in window._task_table.item(invalid_row, 3).toolTip()
        assert window._sync_form_to_text(show_message=False) is False
        assert "validation failed" in window._form_hint.text().lower()

        window._task_table.item(invalid_row, 3).setText("1.5")
        APP.processEvents()
        assert window._has_table_validation_errors() is False
        assert window._sync_form_to_text(show_message=False) is True
    finally:
        window.close()


def test_ui_dag_node_can_move_freely_in_view_layer() -> None:
    window = MainWindow(config_path="examples/at01_single_dag_single_core.yaml")
    try:
        before = window._dag_scene_pos_for_subtask("s1")
        assert before is not None
        node = window._dag_node_items["s1"]
        node.setPos(QPointF(before.x() + 110.0, before.y() + 40.0))
        window._on_dag_node_drag_finished("s1")
        APP.processEvents()

        after = window._dag_scene_pos_for_subtask("s1")
        assert after is not None
        assert abs(after.x() - before.x()) > 50

        window._on_sync_form_to_text()
        payload = yaml.safe_load(window._editor.toPlainText())
        assert "ui_layout" not in payload
    finally:
        window.close()


def test_ui_dag_auto_layout_button_rearranges_nodes() -> None:
    window = MainWindow(config_path="examples/at01_single_dag_single_core.yaml")
    try:
        window._dag_new_subtask_id.setText("s2")
        window._on_dag_add_subtask()
        window._dag_new_subtask_id.setText("s3")
        window._on_dag_add_subtask()
        window._try_add_dag_edge("s1", "s2", show_feedback=False)
        window._try_add_dag_edge("s1", "s3", show_feedback=False)

        # Disturb current layout first.
        p2 = window._dag_scene_pos_for_subtask("s2")
        p3 = window._dag_scene_pos_for_subtask("s3")
        assert p2 is not None and p3 is not None
        window._dag_node_items["s2"].setPos(QPointF(p2.x() + 220.0, p2.y() + 180.0))
        window._dag_node_items["s3"].setPos(QPointF(p3.x() - 180.0, p3.y() + 200.0))
        APP.processEvents()

        window._on_dag_auto_layout()
        APP.processEvents()

        s0 = window._dag_scene_pos_for_subtask("s0")
        s1 = window._dag_scene_pos_for_subtask("s1")
        s2 = window._dag_scene_pos_for_subtask("s2")
        s3 = window._dag_scene_pos_for_subtask("s3")
        assert s0 is not None and s1 is not None and s2 is not None and s3 is not None

        # Layered order: s0 -> s1 -> (s2,s3)
        assert s0.x() < s1.x()
        assert s1.x() < s2.x()
        assert s1.x() < s3.x()
    finally:
        window.close()


def test_ui_dag_layout_persist_to_ui_layout_optional() -> None:
    window = MainWindow(config_path="examples/at01_single_dag_single_core.yaml")
    try:
        window._dag_persist_layout.setChecked(True)
        before = window._dag_scene_pos_for_subtask("s1")
        assert before is not None
        window._dag_node_items["s1"].setPos(QPointF(before.x() + 66.0, before.y() + 33.0))
        window._on_dag_node_drag_finished("s1")
        APP.processEvents()

        assert window._sync_form_to_text(show_message=False) is True
        payload = yaml.safe_load(window._editor.toPlainText())
        assert "ui_layout" in payload
        assert "task_nodes" in payload["ui_layout"]
        assert "t0" in payload["ui_layout"]["task_nodes"]
        assert "s1" in payload["ui_layout"]["task_nodes"]["t0"]

        # ui_layout metadata should not break runtime validation in UI path.
        window._loader.load_data(payload)
    finally:
        window.close()
