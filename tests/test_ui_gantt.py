from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

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
