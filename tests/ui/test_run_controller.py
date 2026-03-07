from __future__ import annotations

from dataclasses import dataclass

import pytest

from rtos_sim.ui.controllers.run_controller import RunController


@dataclass
class _Label:
    text: str = ""

    def setText(self, value: str) -> None:  # noqa: N802
        self.text = value


@dataclass
class _Button:
    enabled: bool = False

    def setEnabled(self, value: bool) -> None:  # noqa: N802
        self.enabled = value


@dataclass
class _Spin:
    raw_value: float

    def value(self) -> float:
        return self.raw_value


class _Signal:
    def __init__(self) -> None:
        self.handlers = []

    def connect(self, handler) -> None:
        self.handlers.append(handler)


class _DummyWorker:
    def __init__(self, config_text: str, step_delta: float | None = None) -> None:
        self.config_text = config_text
        self.step_delta = step_delta
        self.events_batch = _Signal()
        self.finished_report = _Signal()
        self.failed = _Signal()
        self.started = False
        self.running = False
        self.paused = False
        self.stop_called = False
        self.pause_called = False
        self.resume_called = False
        self.requested_step: float | None = None

    def start(self) -> None:
        self.started = True
        self.running = True

    def isRunning(self) -> bool:  # noqa: N802
        return self.running

    def stop(self) -> None:
        self.stop_called = True
        self.running = False

    def pause(self) -> None:
        self.pause_called = True
        self.paused = True

    def resume(self) -> None:
        self.resume_called = True
        self.paused = False

    def request_step(self, delta: float | None) -> None:
        self.requested_step = delta

    def wait(self, _ms: int) -> None:
        self.running = False


class _DummyScheduler:
    name = "np_edf"


@dataclass
class _DummySpec:
    scheduler: _DummyScheduler


class _DummyEngine:
    def build(self, _spec: object) -> None:
        return None


class _Loader:
    def __init__(self) -> None:
        self.raise_exc: Exception | None = None

    def load_data(self, payload: dict) -> _DummySpec:
        if self.raise_exc is not None:
            raise self.raise_exc
        return _DummySpec(scheduler=_DummyScheduler())


class _Owner:
    def __init__(self) -> None:
        self._run_button = _Button(True)
        self._stop_button = _Button(False)
        self._pause_button = _Button(False)
        self._resume_button = _Button(False)
        self._step_button = _Button(False)
        self._step_delta_spin = _Spin(0.5)

        self._status_label = _Label()
        self._loader = _Loader()
        self._worker: _DummyWorker | None = None
        self._metrics: list[str] = []
        self._latest_metrics_report: dict = {}
        self._latest_run_payload: dict | None = None
        self._latest_run_spec: object | None = None
        self._latest_run_events: list[dict] | None = None
        self._latest_audit_report: dict | None = {"stale": True}
        self._latest_model_relations_report: dict | None = {"stale": True}
        self._latest_research_report: dict | None = {"stale": True}
        self._latest_quality_snapshot: dict | None = {"status": "pass"}
        self._reset_calls = 0
        self._event_batches: list[list[dict]] = []

    def _sync_form_to_text_if_dirty(self) -> bool:
        return True

    def _read_editor_payload(self) -> dict:
        return {"version": "0.2", "tasks": []}

    def _reset_viz(self) -> None:
        self._reset_calls += 1

    def _on_event_batch(self, rows: list[dict]) -> None:
        self._event_batches.append(rows)

    def _on_finished(self, _metrics: dict, _events: list[dict]) -> None:
        return None

    def _on_failed(self, _message: str) -> None:
        return None


def test_on_run_starts_worker_and_updates_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    controller = RunController(owner, lambda *_args, **_kwargs: None)

    monkeypatch.setattr("rtos_sim.ui.controllers.run_controller.SimulationWorker", _DummyWorker)
    monkeypatch.setattr("rtos_sim.ui.controllers.run_controller.SimEngine", _DummyEngine)

    controller.on_run()

    assert isinstance(owner._worker, _DummyWorker)
    assert owner._worker.started is True
    assert owner._worker.step_delta == 0.5
    assert owner._status_label.text == "Running"
    assert owner._run_button.enabled is False
    assert owner._stop_button.enabled is True
    assert owner._pause_button.enabled is True
    assert owner._resume_button.enabled is False
    assert owner._step_button.enabled is True
    assert owner._reset_calls == 1
    assert owner._latest_run_payload == {"version": "0.2", "tasks": []}
    assert owner._latest_run_spec is not None
    assert owner._latest_run_events is None
    assert owner._latest_audit_report is None
    assert owner._latest_model_relations_report is None
    assert owner._latest_research_report is None
    assert owner._latest_quality_snapshot == {"status": "pass"}


def test_on_run_invalid_config_sets_blocked_status(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    owner._loader.raise_exc = ValueError("invalid")
    controller = RunController(owner, lambda *_args, **_kwargs: None)

    monkeypatch.setattr(
        "rtos_sim.ui.controllers.run_controller.QMessageBox.critical",
        lambda *_args: None,
    )

    controller.on_run()

    assert owner._worker is None
    assert owner._status_label.text == "Run blocked by invalid config"


def test_on_step_pauses_worker_and_requests_delta() -> None:
    owner = _Owner()
    controller = RunController(owner, lambda *_args, **_kwargs: None)
    owner._worker = _DummyWorker("config")
    owner._worker.running = True

    controller.on_step()

    assert owner._worker.pause_called is True
    assert owner._worker.requested_step == 0.5
    assert owner._status_label.text == "Paused (step)"
    assert owner._resume_button.enabled is True


def test_on_finished_appends_metrics_caches_events_and_clears_worker() -> None:
    owner = _Owner()
    controller = RunController(owner, lambda *_args, **_kwargs: None)
    owner._worker = _DummyWorker("config")

    controller.on_event_batch([{"event_id": "e1"}])
    controller.on_finished(
        {"jobs_completed": 2},
        all_events=[{"event_id": "e1"}, {"event_id": "e2"}],
    )

    assert owner._latest_metrics_report["jobs_completed"] == 2
    assert owner._latest_run_events == [{"event_id": "e1"}, {"event_id": "e2"}]
    assert any(line.startswith("\n=== Metrics ===") for line in owner._metrics)
    assert owner._status_label.text == "Completed"
    assert owner._worker is None
    assert owner._event_batches == [[{"event_id": "e1"}], [{"event_id": "e2"}]]


def test_on_reset_and_failed_clear_research_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    controller = RunController(owner, lambda *_args, **_kwargs: None)
    owner._worker = _DummyWorker("config")
    owner._worker.running = True
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.run_controller.QMessageBox.critical",
        lambda *_args: None,
    )

    controller.on_reset()

    assert owner._latest_run_payload is None
    assert owner._latest_run_spec is None
    assert owner._latest_run_events is None
    assert owner._latest_audit_report is None
    assert owner._latest_model_relations_report is None
    assert owner._latest_research_report is None
    assert owner._latest_quality_snapshot == {"status": "pass"}
    assert owner._status_label.text == "Reset"

    owner._latest_run_payload = {"version": "0.2"}
    owner._latest_run_spec = _DummySpec(scheduler=_DummyScheduler())
    owner._latest_run_events = [{"event_id": "e2"}]
    owner._latest_audit_report = {"status": "pass"}
    owner._latest_model_relations_report = {"status": "pass"}
    owner._latest_research_report = {"status": "pass"}

    controller.on_failed("boom")

    assert owner._latest_run_payload is None
    assert owner._latest_run_spec is None
    assert owner._latest_run_events is None
    assert owner._latest_audit_report is None
    assert owner._latest_model_relations_report is None
    assert owner._latest_research_report is None
    assert owner._status_label.text == "Failed"
