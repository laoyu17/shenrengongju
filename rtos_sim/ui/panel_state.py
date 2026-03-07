"""State containers for UI panels."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CompareScenarioState:
    label: str
    metrics: dict[str, Any]
    source: str = ""


@dataclass(slots=True)
class ComparePanelState:
    scenarios: list[CompareScenarioState] = field(default_factory=list)
    latest_report: dict[str, Any] | None = None


@dataclass(slots=True)
class TelemetryPanelState:
    state_transitions: list[str] = field(default_factory=list)
    hovered_segment_key: str | None = None
    locked_segment_key: str | None = None
