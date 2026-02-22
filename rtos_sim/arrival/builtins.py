"""Built-in custom arrival generators."""

from __future__ import annotations

import math
from random import Random
from typing import Any

from rtos_sim.model import TaskGraphSpec

from .base import IArrivalGenerator


class ConstantIntervalArrivalGenerator(IArrivalGenerator):
    """Always return a fixed interval from params.interval."""

    def next_interval(
        self,
        *,
        task: TaskGraphSpec,  # noqa: ARG002
        now: float,  # noqa: ARG002
        current_release: float,  # noqa: ARG002
        release_index: int,  # noqa: ARG002
        params: dict[str, Any],
        rng: Random,  # noqa: ARG002
    ) -> float:
        interval_raw = params.get("interval")
        if not isinstance(interval_raw, (int, float)):
            raise ValueError("custom arrival generator constant_interval requires numeric params.interval")
        interval = float(interval_raw)
        if interval <= 0:
            raise ValueError("custom arrival generator constant_interval requires params.interval > 0")
        return interval


class UniformIntervalArrivalGenerator(IArrivalGenerator):
    """Return rng.uniform(min_interval, max_interval)."""

    def next_interval(
        self,
        *,
        task: TaskGraphSpec,  # noqa: ARG002
        now: float,  # noqa: ARG002
        current_release: float,  # noqa: ARG002
        release_index: int,  # noqa: ARG002
        params: dict[str, Any],
        rng: Random,
    ) -> float:
        min_raw = params.get("min_interval")
        max_raw = params.get("max_interval")
        if not isinstance(min_raw, (int, float)) or not isinstance(max_raw, (int, float)):
            raise ValueError(
                "custom arrival generator uniform_interval requires numeric "
                "params.min_interval and params.max_interval"
            )
        lower = float(min_raw)
        upper = float(max_raw)
        if lower <= 0 or upper <= 0:
            raise ValueError("custom arrival generator uniform_interval requires intervals > 0")
        if upper < lower - 1e-12:
            raise ValueError("custom arrival generator uniform_interval requires max_interval >= min_interval")
        return rng.uniform(lower, upper)


class PoissonRateArrivalGenerator(IArrivalGenerator):
    """Return rng.expovariate(rate)."""

    def next_interval(
        self,
        *,
        task: TaskGraphSpec,  # noqa: ARG002
        now: float,  # noqa: ARG002
        current_release: float,  # noqa: ARG002
        release_index: int,  # noqa: ARG002
        params: dict[str, Any],
        rng: Random,
    ) -> float:
        rate_raw = params.get("rate")
        if not isinstance(rate_raw, (int, float)):
            raise ValueError("custom arrival generator poisson_rate requires numeric params.rate")
        rate = float(rate_raw)
        if rate <= 0:
            raise ValueError("custom arrival generator poisson_rate requires params.rate > 0")
        interval = float(rng.expovariate(rate))
        if interval <= 0:
            raise ValueError("custom arrival generator poisson_rate produced non-positive interval")
        return interval


class SequenceArrivalGenerator(IArrivalGenerator):
    """Return intervals from a numeric sequence string (comma-separated)."""

    @staticmethod
    def _parse_sequence(raw: Any) -> list[float]:
        if isinstance(raw, (int, float)):
            values = [float(raw)]
        elif isinstance(raw, str):
            tokens = [token.strip() for token in raw.split(",")]
            if not tokens or any(not token for token in tokens):
                raise ValueError("custom arrival generator sequence requires non-empty params.sequence")
            values = [float(token) for token in tokens]
        else:
            raise ValueError("custom arrival generator sequence requires params.sequence as string/number")

        if any((not math.isfinite(value)) or value <= 0 for value in values):
            raise ValueError("custom arrival generator sequence requires all intervals > 0")
        return values

    def next_interval(
        self,
        *,
        task: TaskGraphSpec,  # noqa: ARG002
        now: float,  # noqa: ARG002
        current_release: float,  # noqa: ARG002
        release_index: int,
        params: dict[str, Any],
        rng: Random,  # noqa: ARG002
    ) -> float:
        values = self._parse_sequence(params.get("sequence"))
        # Engine passes the target release index (first interval uses release_index=1).
        interval_index = max(0, release_index - 1)
        repeat_raw = params.get("repeat", True)
        repeat = bool(repeat_raw)
        if repeat:
            return values[interval_index % len(values)]
        idx = min(interval_index, len(values) - 1)
        return values[idx]
