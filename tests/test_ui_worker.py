from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from rtos_sim.ui.worker import SimulationWorker


APP = QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _base_config_text(duration: float = 20.0) -> str:
    return f"""
version: "0.2"
platform:
  processor_types:
    - id: CPU
      name: cpu
      core_count: 1
      speed_factor: 1.0
  cores:
    - id: c0
      type_id: CPU
      speed_factor: 1.0
resources: []
tasks:
  - id: t0
    name: task
    task_type: dynamic_rt
    period: 1
    min_inter_arrival: 1
    deadline: 1
    arrival: 0
    subtasks:
      - id: s0
        predecessors: []
        successors: []
        segments:
          - id: seg0
            index: 1
            wcet: 0.1
scheduler:
  name: edf
  params: {{}}
sim:
  duration: {duration}
  seed: 1
""".strip()


def test_worker_streams_batches_and_emits_finished_report() -> None:
    worker = SimulationWorker(_base_config_text(duration=30.0))
    batches: list[list[dict]] = []
    finished: list[tuple[dict, list]] = []
    failed: list[str] = []
    worker.events_batch.connect(lambda rows: batches.append(rows))
    worker.finished_report.connect(lambda metrics, events: finished.append((metrics, events)))
    worker.failed.connect(lambda message: failed.append(message))

    worker.start()
    assert _wait_until(lambda: bool(finished) or bool(failed), timeout=8.0)
    worker.wait(2000)

    assert failed == []
    assert finished
    metrics, events = finished[0]
    assert metrics["jobs_completed"] >= 1
    assert len(events) >= 64
    assert batches


def test_worker_start_paused_then_step_and_resume_advances() -> None:
    worker = SimulationWorker(_base_config_text(duration=6.0), start_paused=True, step_delta=0.5)
    finished: list[tuple[dict, list]] = []
    failed: list[str] = []
    worker.finished_report.connect(lambda metrics, events: finished.append((metrics, events)))
    worker.failed.connect(lambda message: failed.append(message))

    worker.start()
    assert _wait_until(lambda: worker._engine is not None, timeout=3.0)
    assert worker._engine is not None
    paused_now = worker._engine.now
    time.sleep(0.05)
    APP.processEvents()
    assert worker._engine.now == paused_now

    worker.request_step(0.5)
    assert _wait_until(lambda: worker._engine is not None and worker._engine.now > paused_now + 1e-12, timeout=3.0)

    worker.resume()
    assert _wait_until(lambda: bool(finished) or bool(failed), timeout=6.0)
    worker.wait(2000)
    assert failed == []
    assert finished


def test_worker_invalid_config_emits_failed_signal() -> None:
    worker = SimulationWorker("[]")
    finished: list[tuple[dict, list]] = []
    failed: list[str] = []
    worker.finished_report.connect(lambda metrics, events: finished.append((metrics, events)))
    worker.failed.connect(lambda message: failed.append(message))

    worker.start()
    assert _wait_until(lambda: bool(failed), timeout=3.0)
    worker.wait(2000)

    assert failed
    assert finished == []


def test_worker_execute_direct_mode_covers_command_flow() -> None:
    worker = SimulationWorker(_base_config_text(duration=4.0), start_paused=True, step_delta=0.5)
    finished: list[tuple[dict, list]] = []
    failed: list[str] = []
    worker.finished_report.connect(lambda metrics, events: finished.append((metrics, events)))
    worker.failed.connect(lambda message: failed.append(message))

    worker.request_step(0.5)
    worker.resume()
    worker._execute()

    assert failed == []
    assert finished
    metrics, events = finished[0]
    assert metrics["jobs_completed"] >= 1
    assert events


def test_worker_execute_stopped_before_loop_returns_partial_report() -> None:
    worker = SimulationWorker(_base_config_text(duration=4.0))
    finished: list[tuple[dict, list]] = []
    failed: list[str] = []
    worker.finished_report.connect(lambda metrics, events: finished.append((metrics, events)))
    worker.failed.connect(lambda message: failed.append(message))

    worker.stop()
    worker._execute()

    assert failed == []
    assert finished
    metrics, events = finished[0]
    assert metrics["max_time"] == 0.0
    assert events == []


def test_worker_stop_calls_engine_stop_when_engine_exists() -> None:
    class _DummyEngine:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    worker = SimulationWorker(_base_config_text(duration=1.0))
    worker._engine = _DummyEngine()  # type: ignore[assignment]
    worker.stop()
    assert worker._engine.stopped is True  # type: ignore[union-attr]


def test_worker_pause_enqueues_pause_command() -> None:
    worker = SimulationWorker(_base_config_text(duration=1.0))
    worker.pause()
    command, value = worker._commands.get_nowait()
    assert command == "pause"
    assert value is None


def test_worker_run_direct_invalid_config_emits_failed() -> None:
    worker = SimulationWorker("[]")
    failed: list[str] = []
    worker.failed.connect(lambda message: failed.append(message))
    worker.run()
    assert failed
