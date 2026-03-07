"""Built-in custom arrival generators."""

from __future__ import annotations

import math
from random import Random
from typing import Any

from rtos_sim.model import TaskGraphSpec

from .base import IArrivalGenerator


def _parse_positive_number(raw: Any, *, error_message: str) -> float:
    if not isinstance(raw, (int, float)):
        raise ValueError(error_message)
    value = float(raw)
    if (not math.isfinite(value)) or value <= 0:
        raise ValueError(error_message)
    return value


def _parse_repeat_flag(raw: Any, *, generator_name: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in {"true", "1", "yes", "on"}:
            return True
        if token in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"custom arrival generator {generator_name} requires params.repeat as boolean")


def _parse_interval_sequence(raw: Any, *, param_name: str, generator_name: str) -> list[float]:
    if isinstance(raw, (int, float)):
        values = [float(raw)]
    elif isinstance(raw, str):
        tokens = [token.strip() for token in raw.split(",")]
        if not tokens or any(not token for token in tokens):
            raise ValueError(
                f"custom arrival generator {generator_name} requires non-empty params.{param_name}"
            )
        values = [float(token) for token in tokens]
    else:
        raise ValueError(
            f"custom arrival generator {generator_name} requires params.{param_name} as string/number"
        )
    if any((not math.isfinite(value)) or value <= 0 for value in values):
        raise ValueError(
            f"custom arrival generator {generator_name} requires all params.{param_name} intervals > 0"
        )
    return values


def _resolve_periodic_jitter_bounds(params: dict[str, Any]) -> tuple[float, float]:
    period = _parse_positive_number(
        params.get("period"),
        error_message="custom arrival generator periodic_jitter requires numeric params.period > 0",
    )
    jitter_raw = params.get("jitter", 0.0)
    if not isinstance(jitter_raw, (int, float)):
        raise ValueError("custom arrival generator periodic_jitter requires numeric params.jitter >= 0")
    jitter = float(jitter_raw)
    if (not math.isfinite(jitter)) or jitter < 0:
        raise ValueError("custom arrival generator periodic_jitter requires numeric params.jitter >= 0")
    lower = period - jitter
    upper = period + jitter
    if lower <= 0:
        raise ValueError("custom arrival generator periodic_jitter requires period - jitter > 0")
    return lower, upper


def _resolve_burst_sequence_pattern(params: dict[str, Any]) -> list[float]:
    burst_values = _parse_interval_sequence(
        params.get("burst_intervals"),
        param_name="burst_intervals",
        generator_name="burst_sequence",
    )
    recovery_interval = _parse_positive_number(
        params.get("recovery_interval"),
        error_message="custom arrival generator burst_sequence requires numeric params.recovery_interval > 0",
    )
    return [*burst_values, recovery_interval]


def resolve_generator_min_interval(
    generator_name: str,
    params: dict[str, Any],
) -> tuple[float | None, str | None]:
    key = str(generator_name or "").strip().lower()
    if key == "constant_interval":
        return (
            _parse_positive_number(
                params.get("interval"),
                error_message="custom arrival generator constant_interval requires numeric params.interval > 0",
            ),
            "arrival_process.params.interval",
        )
    if key == "uniform_interval":
        return (
            _parse_positive_number(
                params.get("min_interval"),
                error_message="custom arrival generator uniform_interval requires numeric params.min_interval > 0",
            ),
            "arrival_process.params.min_interval",
        )
    if key == "sequence":
        values = _parse_interval_sequence(
            params.get("sequence"),
            param_name="sequence",
            generator_name="sequence",
        )
        return min(values), "arrival_process.params.sequence(min)"
    if key == "periodic_jitter":
        lower, _ = _resolve_periodic_jitter_bounds(params)
        return lower, "arrival_process.params.period-jitter(lower_bound)"
    if key == "burst_sequence":
        pattern = _resolve_burst_sequence_pattern(params)
        return min(pattern), "arrival_process.params.burst_intervals/recovery_interval(min)"
    return None, None


def generator_uses_rng(generator_name: str) -> bool:
    return str(generator_name or "").strip().lower() in {
        "uniform_interval",
        "poisson_rate",
        "periodic_jitter",
    }


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
        interval, _ = resolve_generator_min_interval("constant_interval", params)
        assert interval is not None
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
        lower, _ = resolve_generator_min_interval("uniform_interval", params)
        max_raw = params.get("max_interval")
        upper = _parse_positive_number(
            max_raw,
            error_message=(
                "custom arrival generator uniform_interval requires numeric params.max_interval > 0"
            ),
        )
        assert lower is not None
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
        rate = _parse_positive_number(
            params.get("rate"),
            error_message="custom arrival generator poisson_rate requires numeric params.rate > 0",
        )
        interval = float(rng.expovariate(rate))
        if interval <= 0:
            raise ValueError("custom arrival generator poisson_rate produced non-positive interval")
        return interval


class SequenceArrivalGenerator(IArrivalGenerator):
    """Return intervals from a numeric sequence string (comma-separated)."""

    @staticmethod
    def _parse_repeat(raw: Any) -> bool:
        return _parse_repeat_flag(raw, generator_name="sequence")

    @staticmethod
    def _parse_sequence(raw: Any) -> list[float]:
        return _parse_interval_sequence(raw, param_name="sequence", generator_name="sequence")

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
        interval_index = max(0, release_index - 1)
        repeat = self._parse_repeat(params.get("repeat", True))
        if repeat:
            return values[interval_index % len(values)]
        idx = min(interval_index, len(values) - 1)
        return values[idx]


class PeriodicJitterArrivalGenerator(IArrivalGenerator):
    """Return a jittered interval around params.period."""

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
        lower, upper = _resolve_periodic_jitter_bounds(params)
        return rng.uniform(lower, upper)


class BurstSequenceArrivalGenerator(IArrivalGenerator):
    """Repeat short burst intervals followed by a recovery interval."""

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
        pattern = _resolve_burst_sequence_pattern(params)
        interval_index = max(0, release_index - 1)
        repeat = _parse_repeat_flag(params.get("repeat", True), generator_name="burst_sequence")
        if repeat:
            return pattern[interval_index % len(pattern)]
        idx = min(interval_index, len(pattern) - 1)
        return pattern[idx]
