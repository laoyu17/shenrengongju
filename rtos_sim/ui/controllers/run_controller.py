"""Controller for simulation run lifecycle and worker state transitions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol

import yaml
from PyQt6.QtWidgets import QMessageBox

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
        self._streamed_event_count = 0
        self._accept_event_batches = False

    def _clear_latest_research_state(self) -> None:
        self._owner._latest_run_payload = None
        self._owner._latest_run_spec = None
        self._owner._latest_run_events = None
        self._owner._latest_audit_report = None
        self._owner._latest_model_relations_report = None
        self._owner._latest_research_report = None
        self._streamed_event_count = 0
        self._accept_event_batches = False

    def _remaining_events(self, all_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._streamed_event_count <= 0:
            return list(all_events)
        if self._streamed_event_count >= len(all_events):
            return []
        return list(all_events[self._streamed_event_count :])

    def _disconnect_signal(self, signal: Any, handler: Any) -> None:
        try:
            signal.disconnect(handler)
        except (AttributeError, RuntimeError, TypeError):
            return

    def _attach_worker_callbacks(self, worker: SimulationWorker) -> None:
        events_batch = getattr(worker, "events_batch", None)
        finished_report = getattr(worker, "finished_report", None)
        failed = getattr(worker, "failed", None)
        if events_batch is not None:
            events_batch.connect(self.on_event_batch)
        if finished_report is not None:
            finished_report.connect(self.on_finished)
        if failed is not None:
            failed.connect(self.on_failed)
        if hasattr(worker, "finished"):
            worker.finished.connect(self.on_worker_thread_finished)

    def _detach_worker_callbacks(self, worker: SimulationWorker) -> None:
        events_batch = getattr(worker, "events_batch", None)
        finished_report = getattr(worker, "finished_report", None)
        failed = getattr(worker, "failed", None)
        if events_batch is not None:
            self._disconnect_signal(events_batch, self.on_event_batch)
        if finished_report is not None:
            self._disconnect_signal(finished_report, self.on_finished)
        if failed is not None:
            self._disconnect_signal(failed, self.on_failed)

    def teardown_worker(self, *, wait_ms: int) -> bool:
        worker = self._owner._worker
        if worker is None:
            self._accept_event_batches = False
            self._streamed_event_count = 0
            return True

        self._accept_event_batches = False
        self._detach_worker_callbacks(worker)
        if worker.isRunning():
            worker.stop()
            wait_result = worker.wait(wait_ms)
            if wait_result is False:
                return False
        self._owner._worker = None
        self._streamed_event_count = 0
        return True

    def on_worker_thread_finished(self) -> None:
        worker = self._owner._worker
        if worker is not None and not worker.isRunning():
            self._owner._worker = None
            self._streamed_event_count = 0
            self._accept_event_batches = False

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
        except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
            self._error_logger("run_precheck", exc)
            QMessageBox.critical(self._owner, "Run failed", f"Invalid config: {exc}")
            self._owner._status_label.setText("Run blocked by invalid config")
            return

        self._owner._latest_run_payload = dict(payload)
        self._owner._latest_run_spec = spec
        self._owner._latest_run_events = None
        self._owner._latest_audit_report = None
        self._owner._latest_model_relations_report = None
        self._owner._latest_research_report = None
        self._streamed_event_count = 0
        self._accept_event_batches = True
        self._owner._reset_viz()
        self._owner._metrics.clear()

        config_text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        self._owner._worker = SimulationWorker(config_text, step_delta=self.step_delta_value())
        self._attach_worker_callbacks(self._owner._worker)
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

    def on_event_batch(self, rows: list[dict[str, Any]]) -> None:
        worker = self._owner._worker
        if not self._accept_event_batches and not (worker is not None and worker.isRunning()):
            return
        if rows:
            self._streamed_event_count += len(rows)
        self._owner._on_event_batch(rows)

    def on_reset(self) -> None:
        if not self.teardown_worker(wait_ms=1000):
            self.set_worker_controls(running=False, paused=False)
            self._owner._status_label.setText("Stopping...")
            return
        self._clear_latest_research_state()
        self._owner._reset_viz()
        self._owner._metrics.clear()
        self.set_worker_controls(running=False, paused=False)
        self._owner._status_label.setText("Reset")

    def on_finished(self, report: dict[str, Any], all_events: list[dict[str, Any]]) -> None:
        worker = self._owner._worker
        self._accept_event_batches = False
        if worker is not None:
            self._detach_worker_callbacks(worker)
        remaining_events = self._remaining_events(all_events)
        if remaining_events:
            self._owner._on_event_batch(remaining_events)
        self._owner._latest_metrics_report = dict(report)
        self._owner._latest_run_events = list(all_events)
        self._streamed_event_count = 0
        self._owner._metrics.append("\n=== Metrics ===")
        self._owner._metrics.append(json.dumps(report, ensure_ascii=False, indent=2))
        self._owner._status_label.setText("Completed")
        self.set_worker_controls(running=False, paused=False)
        self._owner._worker = None

    def on_failed(self, error_message: str) -> None:
        worker = self._owner._worker
        self._accept_event_batches = False
        if worker is not None:
            self._detach_worker_callbacks(worker)
        self._clear_latest_research_state()
        self._owner._metrics.append(f"[Error] {error_message}")
        QMessageBox.critical(self._owner, "Simulation failed", error_message)
        self._owner._status_label.setText("Failed")
        self.set_worker_controls(running=False, paused=False)
        self._owner._worker = None
