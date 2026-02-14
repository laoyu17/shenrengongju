"""PyQt6 UI app for simulation control and visualization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyqtgraph as pg
import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rtos_sim.io import ConfigError, ConfigLoader

from .worker import SimulationWorker


class MainWindow(QMainWindow):
    """Main window with config editor, run controls and Gantt view."""

    def __init__(self, config_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("RTOS Sim UI (PyQt6)")
        self.resize(1400, 900)

        self._loader = ConfigLoader()
        self._worker: SimulationWorker | None = None
        self._core_to_y: dict[str, int] = {}
        self._active_segments: dict[str, tuple[float, str, str]] = {}
        self._max_time = 0.0

        self._editor = QPlainTextEdit()
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._validate_button = QPushButton("Validate")
        self._run_button = QPushButton("Run")
        self._stop_button = QPushButton("Stop")
        self._load_button = QPushButton("Load")
        self._save_button = QPushButton("Save")
        self._status_label = QLabel("Ready")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._plot = pg.PlotWidget(title="Gantt")
        self._plot.showGrid(x=True, y=True)
        self._plot.setLabel("bottom", "Time")
        self._plot.setLabel("left", "Core")

        self._metrics = QTextEdit()
        self._metrics.setReadOnly(True)

        self._build_layout()
        self._connect_signals()

        if config_path:
            self._load_file(config_path)

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
        editor_layout.addWidget(QLabel("Config Editor (YAML/JSON)"))
        editor_layout.addWidget(self._editor)
        splitter.addWidget(editor_container)

        viz_container = QWidget()
        viz_layout = QVBoxLayout(viz_container)
        viz_layout.addWidget(self._plot, stretch=3)
        viz_layout.addWidget(QLabel("Metrics / Logs"))
        viz_layout.addWidget(self._metrics, stretch=2)
        splitter.addWidget(viz_container)
        splitter.setSizes([600, 800])

        root_layout.addWidget(splitter)
        self.setCentralWidget(root)

        self._stop_button.setEnabled(False)

    def _connect_signals(self) -> None:
        self._load_button.clicked.connect(self._pick_load_file)
        self._save_button.clicked.connect(self._pick_save_file)
        self._validate_button.clicked.connect(self._on_validate)
        self._run_button.clicked.connect(self._on_run)
        self._stop_button.clicked.connect(self._on_stop)

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
        content = Path(path).read_text(encoding="utf-8")
        self._editor.setPlainText(content)
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
        Path(path).write_text(self._editor.toPlainText(), encoding="utf-8")
        self._status_label.setText(f"Saved: {path}")

    def _on_validate(self) -> None:
        try:
            payload = yaml.safe_load(self._editor.toPlainText())
            if not isinstance(payload, dict):
                raise ConfigError("config root must be object")
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
        self._reset_viz()
        self._metrics.clear()

        self._worker = SimulationWorker(self._editor.toPlainText())
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
            self._consume_event(event)

    def _consume_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        segment_key = event.get("payload", {}).get("segment_key")
        event_time = float(event.get("time", 0.0))
        core_id = event.get("core_id")
        self._max_time = max(self._max_time, event_time)

        if event_type == "SegmentStart" and segment_key and core_id:
            self._active_segments[segment_key] = (
                event_time,
                str(core_id),
                str(event.get("job_id", "")),
            )
        elif event_type == "SegmentEnd" and segment_key:
            start_data = self._active_segments.pop(segment_key, None)
            if start_data:
                start_time, start_core, job_id = start_data
                self._draw_gantt_segment(start_time, event_time, start_core, job_id, segment_key)
        elif event_type == "DeadlineMiss":
            job_id = event.get("job_id", "")
            self._metrics.append(f"[DeadlineMiss] {job_id} at t={event_time:.3f}")

    def _draw_gantt_segment(
        self,
        start: float,
        end: float,
        core_id: str,
        job_id: str,
        segment_key: str,
    ) -> None:
        if core_id not in self._core_to_y:
            self._core_to_y[core_id] = len(self._core_to_y) + 1
            ticks = [(y, core) for core, y in sorted(self._core_to_y.items(), key=lambda item: item[1])]
            self._plot.getAxis("left").setTicks([ticks])
        y = self._core_to_y[core_id]
        color = pg.intColor(abs(hash(job_id)) % 255, 255)
        self._plot.plot([start, end], [y, y], pen=pg.mkPen(color=color, width=8))
        self._metrics.append(f"[Segment] {segment_key} core={core_id} [{start:.3f}, {end:.3f}]")
        self._plot.setXRange(0, max(1.0, self._max_time * 1.05), padding=0)

    def _on_finished(self, report: dict[str, Any]) -> None:
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
        self._core_to_y.clear()
        self._active_segments.clear()
        self._max_time = 0.0


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
