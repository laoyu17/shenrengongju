"""Background simulation worker for PyQt UI."""

from __future__ import annotations

import time
from typing import Any

import yaml
from PyQt6.QtCore import QThread, pyqtSignal

from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigError, ConfigLoader


class SimulationWorker(QThread):
    """Run simulation in background and stream event batches."""

    events_batch = pyqtSignal(list)
    finished_report = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, config_text: str, until: float | None = None) -> None:
        super().__init__()
        self._config_text = config_text
        self._until = until
        self._stop_requested = False
        self._engine: SimEngine | None = None

    def stop(self) -> None:
        self._stop_requested = True
        if self._engine:
            self._engine.stop()

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
        pending: list[dict[str, Any]] = []
        last_flush = time.monotonic()

        def on_event(event) -> None:
            nonlocal last_flush
            pending.append(event.model_dump(mode="json"))
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
            self._engine.run(until=self._until)
            if pending:
                self.events_batch.emit(list(pending))
            self.finished_report.emit(self._engine.metric_report())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
