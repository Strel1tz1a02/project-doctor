"""Compute experiment-level differences between groups; never a root-cause verdict."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from project_doctor.models.observation import ExperimentLevel, Observation


@dataclass(frozen=True)
class GroupSummary:
    level: ExperimentLevel
    repetitions: int
    latency_ms: tuple[float, ...]
    sql_duration_ms: tuple[float, ...]
    rows_examined: tuple[float, ...]

    @property
    def median_latency_ms(self) -> float:
        return median(self.latency_ms)

    @property
    def median_sql_duration_ms(self) -> float:
        return median(self.sql_duration_ms)

    @property
    def median_rows_examined(self) -> float:
        return median(self.rows_examined)


@dataclass(frozen=True)
class ExperimentComparison:
    baseline: GroupSummary
    candidate_index: GroupSummary

    @property
    def latency_delta_ms(self) -> float:
        return self.baseline.median_latency_ms - self.candidate_index.median_latency_ms

    @property
    def sql_duration_delta_ms(self) -> float:
        return self.baseline.median_sql_duration_ms - self.candidate_index.median_sql_duration_ms

    @property
    def rows_examined_delta(self) -> float:
        return self.baseline.median_rows_examined - self.candidate_index.median_rows_examined


def summarize(observations: list[Observation], level: ExperimentLevel) -> GroupSummary:
    """Collect one group's measurements; missing SQL metrics are omitted, not filled with zero."""
    items = [item for item in observations if item.level == level]
    latencies = tuple(item.latency_ms for item in items)
    durations = tuple(
        call.duration_ms
        for item in items
        for call in item.sql_calls
        if call.duration_ms is not None
    )
    rows = tuple(
        float(call.rows_examined)
        for item in items
        for call in item.sql_calls
        if call.rows_examined is not None
    )
    return GroupSummary(
        level=level,
        repetitions=len(items),
        latency_ms=latencies,
        sql_duration_ms=durations,
        rows_examined=rows,
    )


def compare(observations: list[Observation]) -> ExperimentComparison:
    """Return a structural comparison of the two groups; deltas are baseline minus candidate."""
    return ExperimentComparison(
        baseline=summarize(observations, "baseline"),
        candidate_index=summarize(observations, "candidate_index"),
    )
