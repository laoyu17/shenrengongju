"""Background simulation worker for PyQt UI."""

from __future__ import annotations

from queue import Empty, SimpleQueue
import time
from typing import Any

import yaml
from PyQt6.QtCore import QThread, pyqtSignal

from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigError, ConfigLoader


class SimulationWorker(QThread):
    """Run simulation in background and stream event batches."""

    events_batch = pyqtSignal(list)
    finished_report = pyqtSignal(dict, list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        config_text: str,
        until: float | None = None,
        *,
        step_delta: float | None = None,
        start_paused: bool = False,
    ) -> None:
        super().__init__()
        self._config_text = config_text
        self._until = until
        self._step_delta = step_delta
        self._start_paused = start_paused
        self._stop_requested = False
        self._engine: SimEngine | None = None
        self._commands: SimpleQueue[tuple[str, float | None]] = SimpleQueue()
        self._paused = start_paused

    def stop(self) -> None:
        self._stop_requested = True
        if self._engine:
            self._engine.stop()

    def pause(self) -> None:
        self._commands.put(("pause", None))

    def resume(self) -> None:
        self._commands.put(("resume", None))

    def request_step(self, delta: float | None = None) -> None:
        self._commands.put(("step", delta))

    def run(self) -> None:  # noqa: D401
        loader = ConfigLoader()
        try:
            data = yaml.safe_load(self._config_text)
            if not isinstance(data, dict):
                raise ConfigError("config root must be object")
            spec = loader.load_data(data)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return

        self._engine = SimEngine()
        all_events: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        last_flush = time.monotonic()

        def on_event(event) -> None:
            nonlocal last_flush
            serialized = event.model_dump(mode="json")
            all_events.append(serialized)
            pending.append(serialized)
            now = time.monotonic()
            if len(pending) >= 64 or now - last_flush >= 0.15:
                self.events_batch.emit(list(pending))
                pending.clear()
                last_flush = now
            if self._stop_requested and self._engine:
                self._engine.stop()

        self._engine.subscribe(on_event)

        try:
            self._engine.build(spec)
            horizon = self._until if self._until is not None else spec.sim.duration
            while not self._stop_requested and self._engine.now < horizon - 1e-12:
                while True:
                    try:
                        command, value = self._commands.get_nowait()
                    except Empty:
                        break
                    if command == "pause":
                        self._paused = True
                    elif command == "resume":
                        self._paused = False
                    elif command == "step":
                        delta = value if value is not None else self._step_delta
                        before = self._engine.now
                        if delta is None:
                            self._engine.step()
                        else:
                            self._engine.step(delta)
                        if self._engine.now <= before + 1e-12:
                            break
                if self._stop_requested:
                    break
                if self._paused:
                    time.sleep(0.01)
                    continue

                before = self._engine.now
                if self._step_delta is None:
                    self._engine.step()
                else:
                    self._engine.step(self._step_delta)
                if self._engine.now <= before + 1e-12:
                    break

            # Normalize end-of-run bookkeeping for partial or stepped execution.
            if not self._stop_requested:
                self._engine.run(until=min(self._engine.now, horizon))
            self.finished_report.emit(self._engine.metric_report(), all_events)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
