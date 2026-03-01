"""Controller for simulation run lifecycle and worker state transitions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol

import yaml
from PyQt6.QtWidgets import QMessageBox

from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigError
from rtos_sim.ui.worker import SimulationWorker


class UiErrorLogger(Protocol):
    def __call__(self, action: str, exc: Exception, **context: Any) -> None: ...


if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class RunController:
    """Keep run control behavior stable while delegating logic from MainWindow."""

    def __init__(self, owner: MainWindow, error_logger: UiErrorLogger) -> None:
        self._owner = owner
        self._error_logger = error_logger

    def set_worker_controls(self, *, running: bool, paused: bool) -> None:
        self._owner._run_button.setEnabled(not running)
        self._owner._stop_button.setEnabled(running)
        self._owner._pause_button.setEnabled(running and not paused)
        self._owner._resume_button.setEnabled(running and paused)
        self._owner._step_button.setEnabled(running)

    def step_delta_value(self) -> float | None:
        value = float(self._owner._step_delta_spin.value())
        if value <= 1e-12:
            return None
        return value

    def on_run(self) -> None:
        if self._owner._worker and self._owner._worker.isRunning():
            return
        if not self._owner._sync_form_to_text_if_dirty():
            return
        try:
            payload = self._owner._read_editor_payload()
            spec = self._owner._loader.load_data(payload)
            SimEngine().build(spec)
        except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
            self._error_logger("run_precheck", exc)
            QMessageBox.critical(self._owner, "Run failed", f"Invalid config: {exc}")
            self._owner._status_label.setText("Run blocked by invalid config")
            return

        self._owner._reset_viz()
        self._owner._metrics.clear()

        config_text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        self._owner._worker = SimulationWorker(config_text, step_delta=self.step_delta_value())
        self._owner._worker.events_batch.connect(self._owner._on_event_batch)
        self._owner._worker.finished_report.connect(self._owner._on_finished)
        self._owner._worker.failed.connect(self._owner._on_failed)
        self._owner._worker.start()

        self.set_worker_controls(running=True, paused=False)
        self._owner._status_label.setText("Running")

    def on_stop(self) -> None:
        if self._owner._worker:
            self._owner._worker.stop()
        self._owner._status_label.setText("Stopping...")

    def on_pause(self) -> None:
        if not self._owner._worker or not self._owner._worker.isRunning():
            return
        self._owner._worker.pause()
        self.set_worker_controls(running=True, paused=True)
        self._owner._status_label.setText("Paused")

    def on_resume(self) -> None:
        if not self._owner._worker or not self._owner._worker.isRunning():
            return
        self._owner._worker.resume()
        self.set_worker_controls(running=True, paused=False)
        self._owner._status_label.setText("Running")

    def on_step(self) -> None:
        if not self._owner._worker or not self._owner._worker.isRunning():
            return
        self._owner._worker.pause()
        self._owner._worker.request_step(self.step_delta_value())
        self.set_worker_controls(running=True, paused=True)
        self._owner._status_label.setText("Paused (step)")

    def on_reset(self) -> None:
        if self._owner._worker and self._owner._worker.isRunning():
            self._owner._worker.stop()
            self._owner._worker.wait(1000)
        self._owner._worker = None
        self._owner._reset_viz()
        self._owner._metrics.clear()
        self.set_worker_controls(running=False, paused=False)
        self._owner._status_label.setText("Reset")

    def on_finished(self, report: dict[str, Any], tail_events: list[dict[str, Any]]) -> None:
        if tail_events:
            self._owner._on_event_batch(tail_events)
        self._owner._latest_metrics_report = dict(report)
        self._owner._metrics.append("\n=== Metrics ===")
        self._owner._metrics.append(json.dumps(report, ensure_ascii=False, indent=2))
        self._owner._status_label.setText("Completed")
        self.set_worker_controls(running=False, paused=False)
        self._owner._worker = None

    def on_failed(self, error_message: str) -> None:
        self._owner._metrics.append(f"[Error] {error_message}")
        QMessageBox.critical(self._owner, "Simulation failed", error_message)
        self._owner._status_label.setText("Failed")
        self.set_worker_controls(running=False, paused=False)
        self._owner._worker = None
