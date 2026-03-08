"""Controller for DAG overview canvas and cross-task workbench switching."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPen
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
)

from rtos_sim.ui.panel_state import DagOverviewCanvasEntry, DagOverviewTaskEntry

if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class DagOverviewTaskCardItem(QGraphicsRectItem):
    """Clickable overview card that opens a task in detail mode."""

    def __init__(
        self,
        *,
        owner: MainWindow,
        task_index: int,
        rect: QRectF,
        active: bool,
    ) -> None:
        super().__init__(rect)
        self._owner = owner
        self.task_index = task_index
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_active(active)

    def set_active(self, active: bool) -> None:
        border = QColor("#2d7ff9" if active else "#5f7388")
        background = QColor("#16212d" if active else "#1f2c3a")
        pen = QPen(border)
        pen.setWidth(3 if active else 2)
        self.setPen(pen)
        self.setBrush(QBrush(background))

    def mousePressEvent(self, event: Any) -> None:  # noqa: ANN401
        self._owner._open_dag_overview_task_detail(self.task_index)
        event.accept()


class DagOverviewController:
    """Render overview cards and coordinate overview/detail canvas switching."""

    OVERVIEW_TAB_INDEX = 0
    DETAIL_TAB_INDEX = 1

    def __init__(self, owner: MainWindow) -> None:
        self._owner = owner

    def on_canvas_tab_changed(self, index: int) -> None:
        self._owner._dag_canvas_mode = "overview" if index == self.OVERVIEW_TAB_INDEX else "detail"

    def show_overview_canvas(self) -> None:
        self._owner._dag_canvas_tabs.setCurrentIndex(self.OVERVIEW_TAB_INDEX)

    def show_detail_canvas(self) -> None:
        self._owner._dag_canvas_tabs.setCurrentIndex(self.DETAIL_TAB_INDEX)

    def open_task_detail(self, task_ref: int | str) -> bool:
        doc = self._owner._ensure_config_doc()
        task_index = self._resolve_task_index(doc, task_ref)
        if task_index is None:
            return False
        opened = self._owner._dag_controller.select_task(task_index, sync_table_selection=True)
        if opened:
            self.show_detail_canvas()
        return opened

    def refresh_overview_canvas(self, entry: DagOverviewCanvasEntry | None) -> None:
        scene = self._owner._dag_overview_scene
        scene.clear()
        if entry is None or not entry.tasks:
            scene.addText("No task in DAG workbench")
            self._owner._dag_overview_view.setSceneRect(scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
            return

        columns = 1 if len(entry.tasks) <= 1 else 2
        card_width = 280.0
        card_height = 190.0
        gap = 24.0

        for index, task_entry in enumerate(entry.tasks):
            row = index // columns
            col = index % columns
            rect = QRectF(
                col * (card_width + gap),
                row * (card_height + gap),
                card_width,
                card_height,
            )
            card = DagOverviewTaskCardItem(
                owner=self._owner,
                task_index=task_entry.task_index,
                rect=rect,
                active=task_entry.task_index == entry.task_index,
            )
            scene.addItem(card)
            self._populate_card(card, task_entry, active=task_entry.task_index == entry.task_index)

        self._owner._dag_overview_view.setSceneRect(scene.itemsBoundingRect().adjusted(-24, -24, 24, 24))

    def _populate_card(self, card: DagOverviewTaskCardItem, entry: DagOverviewTaskEntry, *, active: bool) -> None:
        title = QGraphicsSimpleTextItem(entry.task_id, card)
        title.setPos(card.rect().left() + 14.0, card.rect().top() + 10.0)
        title.setBrush(QBrush(QColor("#f5f7fa")))
        title.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

        subtitle_bits = [
            entry.task_name or "unnamed task",
            entry.task_type or "task",
            f"{entry.subtask_count} subtasks",
            f"{entry.edge_count} edges",
        ]
        subtitle = QGraphicsSimpleTextItem(" · ".join(subtitle_bits), card)
        subtitle.setPos(card.rect().left() + 14.0, card.rect().top() + 34.0)
        subtitle.setBrush(QBrush(QColor("#b8c7d6")))
        subtitle.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

        helper = QGraphicsSimpleTextItem(
            "Click to open task detail" if not active else "Active task in detail canvas",
            card,
        )
        helper.setPos(card.rect().left() + 14.0, card.rect().top() + 56.0)
        helper.setBrush(QBrush(QColor("#86d0ff" if active else "#8ea6b8")))
        helper.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

        preview_rect = QRectF(
            card.rect().left() + 14.0,
            card.rect().top() + 82.0,
            card.rect().width() - 28.0,
            card.rect().height() - 96.0,
        )
        self._populate_preview(card, entry, preview_rect)

    def _populate_preview(
        self,
        card: DagOverviewTaskCardItem,
        entry: DagOverviewTaskEntry,
        preview_rect: QRectF,
    ) -> None:
        positions = self._scaled_preview_positions(entry, preview_rect)
        if not positions:
            text = QGraphicsSimpleTextItem("No subtasks", card)
            text.setPos(preview_rect.left() + 4.0, preview_rect.center().y() - 8.0)
            text.setBrush(QBrush(QColor("#8ea6b8")))
            text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            return

        edge_pen = QPen(QColor("#7f96a8"))
        edge_pen.setWidth(2)
        for src_id, dst_id in entry.edges:
            src = positions.get(src_id)
            dst = positions.get(dst_id)
            if src is None or dst is None:
                continue
            line = QGraphicsLineItem(src[0], src[1], dst[0], dst[1], card)
            line.setPen(edge_pen)
            line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

        selected_ids = set(entry.selected_subtask_ids)
        radius = 10.0
        for sub_id in entry.subtask_ids:
            pos = positions.get(sub_id)
            if pos is None:
                continue
            node = QGraphicsEllipseItem(-radius, -radius, radius * 2.0, radius * 2.0, card)
            node.setPos(pos[0], pos[1])
            node.setPen(QPen(QColor("#f5f7fa")))
            fill = "#2d7ff9" if sub_id in selected_ids else "#47617a"
            node.setBrush(QBrush(QColor(fill)))
            node.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

            label = QGraphicsSimpleTextItem(sub_id, card)
            label_rect = label.boundingRect()
            label.setPos(pos[0] - label_rect.width() / 2.0, pos[1] + radius + 2.0)
            label.setBrush(QBrush(QColor("#dbe7f0")))
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def _scaled_preview_positions(
        self,
        entry: DagOverviewTaskEntry,
        preview_rect: QRectF,
    ) -> dict[str, tuple[float, float]]:
        if not entry.subtask_ids:
            return {}

        raw_positions = {sub_id: coords for sub_id, coords in entry.node_positions}
        if not raw_positions:
            raw_positions = {
                sub_id: (float(index * 120), 0.0)
                for index, sub_id in enumerate(entry.subtask_ids)
            }

        xs = [coords[0] for coords in raw_positions.values()]
        ys = [coords[1] for coords in raw_positions.values()]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)
        range_x = max(max_x - min_x, 1.0)
        range_y = max(max_y - min_y, 1.0)
        inner_rect = preview_rect.adjusted(14.0, 10.0, -14.0, -22.0)

        scaled: dict[str, tuple[float, float]] = {}
        for sub_id in entry.subtask_ids:
            raw_x, raw_y = raw_positions.get(sub_id, (min_x, min_y))
            if len(entry.subtask_ids) == 1:
                scaled[sub_id] = (inner_rect.center().x(), inner_rect.center().y())
                continue
            x_ratio = (raw_x - min_x) / range_x
            y_ratio = (raw_y - min_y) / range_y if max_y != min_y else 0.5
            scaled[sub_id] = (
                inner_rect.left() + x_ratio * inner_rect.width(),
                inner_rect.top() + y_ratio * inner_rect.height(),
            )
        return scaled

    @staticmethod
    def _resolve_task_index(doc: Any, task_ref: int | str) -> int | None:
        tasks = doc.list_tasks()
        if isinstance(task_ref, int):
            return task_ref if 0 <= task_ref < len(tasks) else None

        target = str(task_ref).strip()
        if not target:
            return None
        for index, task_view in enumerate(tasks):
            task_payload = task_view.task if hasattr(task_view, "task") else task_view
            task_id = str(task_payload.get("id") or "").strip() or f"task_{index}"
            if task_id == target:
                return index
        return None
