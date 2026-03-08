from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QRectF

from rtos_sim.ui.controllers.dag_overview_controller import DagOverviewController
from rtos_sim.ui.panel_state import DagOverviewTaskEntry


class _Tabs:
    def __init__(self) -> None:
        self.current_index = -1

    def setCurrentIndex(self, value: int) -> None:  # noqa: N802
        self.current_index = value


@dataclass
class _Rect:
    adjusted_called: bool = False

    def adjusted(self, *_args: int) -> "_Rect":
        self.adjusted_called = True
        return self


class _Scene:
    def __init__(self) -> None:
        self.cleared = 0
        self.texts: list[str] = []

    def clear(self) -> None:
        self.cleared += 1

    def addText(self, value: str) -> None:  # noqa: N802
        self.texts.append(value)

    def itemsBoundingRect(self) -> _Rect:  # noqa: N802
        return _Rect()

    def addItem(self, _item: object) -> None:  # noqa: N802
        return None


class _View:
    def __init__(self) -> None:
        self.scene_rect = None

    def setSceneRect(self, rect: object) -> None:  # noqa: N802
        self.scene_rect = rect


class _DagController:
    def __init__(self, select_ok: bool = True) -> None:
        self.calls: list[tuple[int, bool]] = []
        self._select_ok = select_ok

    def select_task(self, task_index: int, *, sync_table_selection: bool) -> bool:
        self.calls.append((task_index, sync_table_selection))
        return self._select_ok


class _Doc:
    def __init__(self) -> None:
        self._tasks = [{"id": "t0"}, {"id": "t1"}]

    def list_tasks(self) -> list[dict]:
        return list(self._tasks)


class _Owner:
    def __init__(self, *, select_ok: bool = True) -> None:
        self._dag_canvas_tabs = _Tabs()
        self._dag_canvas_mode = "detail"
        self._dag_controller = _DagController(select_ok=select_ok)
        self._dag_overview_scene = _Scene()
        self._dag_overview_view = _View()
        self._doc = _Doc()

    def _ensure_config_doc(self) -> _Doc:
        return self._doc


def test_open_task_detail_switches_to_detail_canvas_on_success() -> None:
    owner = _Owner(select_ok=True)
    controller = DagOverviewController(owner)

    result = controller.open_task_detail("t1")

    assert result is True
    assert owner._dag_controller.calls == [(1, True)]
    assert owner._dag_canvas_tabs.current_index == DagOverviewController.DETAIL_TAB_INDEX


def test_open_task_detail_returns_false_for_unknown_task_ref() -> None:
    owner = _Owner(select_ok=True)
    controller = DagOverviewController(owner)

    result = controller.open_task_detail("missing")

    assert result is False
    assert owner._dag_controller.calls == []


def test_refresh_overview_canvas_empty_entry_shows_placeholder() -> None:
    owner = _Owner(select_ok=True)
    controller = DagOverviewController(owner)

    controller.refresh_overview_canvas(None)

    assert owner._dag_overview_scene.cleared == 1
    assert owner._dag_overview_scene.texts == ["No task in DAG workbench"]
    assert owner._dag_overview_view.scene_rect is not None


def test_scaled_preview_positions_handles_single_node_and_fallback_layout() -> None:
    owner = _Owner(select_ok=True)
    controller = DagOverviewController(owner)
    preview_rect = QRectF(0.0, 0.0, 100.0, 60.0)

    single = DagOverviewTaskEntry(
        task_index=0,
        task_id="t0",
        subtask_ids=("s0",),
        node_positions=(("s0", (7.0, 9.0)),),
    )
    fallback = DagOverviewTaskEntry(
        task_index=0,
        task_id="t0",
        subtask_ids=("s0", "s1"),
        node_positions=(),
    )

    single_positions = controller._scaled_preview_positions(single, preview_rect)
    fallback_positions = controller._scaled_preview_positions(fallback, preview_rect)

    assert single_positions["s0"] == (preview_rect.adjusted(14.0, 10.0, -14.0, -22.0).center().x(), preview_rect.adjusted(14.0, 10.0, -14.0, -22.0).center().y())
    assert fallback_positions["s0"][0] < fallback_positions["s1"][0]


def test_resolve_task_index_handles_int_string_and_blank() -> None:
    doc = _Doc()

    assert DagOverviewController._resolve_task_index(doc, 1) == 1
    assert DagOverviewController._resolve_task_index(doc, 9) is None
    assert DagOverviewController._resolve_task_index(doc, "t0") == 0
    assert DagOverviewController._resolve_task_index(doc, " ") is None
