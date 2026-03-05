"""State containers for UI panels."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ComparePanelState:
    left_metrics: dict[str, Any] | None = None
    right_metrics: dict[str, Any] | None = None
    latest_report: dict[str, Any] | None = None


@dataclass(slots=True)
class TelemetryPanelState:
    state_transitions: list[str] = field(default_factory=list)
    hovered_segment_key: str | None = None
    locked_segment_key: str | None = None
