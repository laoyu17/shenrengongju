"""Simulation event definitions."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    JOB_RELEASED = "JobReleased"
    SEGMENT_READY = "SegmentReady"
    SEGMENT_START = "SegmentStart"
    SEGMENT_END = "SegmentEnd"
    RESOURCE_ACQUIRE = "ResourceAcquire"
    RESOURCE_RELEASE = "ResourceRelease"
    SEGMENT_BLOCKED = "SegmentBlocked"
    SEGMENT_UNBLOCKED = "SegmentUnblocked"
    PREEMPT = "Preempt"
    MIGRATE = "Migrate"
    DEADLINE_MISS = "DeadlineMiss"
    JOB_COMPLETE = "JobComplete"
    ERROR = "Error"


class SimEvent(BaseModel):
    """Normalized event envelope for tracing and metrics."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    seq: int = Field(ge=0)
    correlation_id: str
    time: float = Field(ge=0)
    type: EventType
    job_id: Optional[str] = None
    segment_id: Optional[str] = None
    core_id: Optional[str] = None
    resource_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False)
