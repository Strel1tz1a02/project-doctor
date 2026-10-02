"""Assemble actual SQL metrics from raw execution statistics without fabricating values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from project_doctor.models.observation import MetricName, MetricSource, SqlCall


@dataclass(frozen=True)
class RawExecutionStats:
    """Actual measurements for one SQL call; missing values stay ``None``."""

    source_id: str
    evidence_id: str
    duration_ms: float | None = None
    rows_examined: int | None = None
    rows_returned: int | None = None
    lock_wait_ms: float | None = None


def apply_actual_metrics(call: SqlCall, stats: RawExecutionStats) -> SqlCall:
    """Populate actual metrics and their sources on a copy of ``call``.

    A metric gets an ``actual`` source only when a value is present; missing values
    remain ``None`` with no source, so they can never be mistaken for zero. Estimated
    values belong in plans and are not accepted here.
    """
    metric_values: dict[MetricName, float | int | None] = {
        "duration_ms": stats.duration_ms,
        "rows_examined": stats.rows_examined,
        "rows_returned": stats.rows_returned,
        "lock_wait_ms": stats.lock_wait_ms,
    }
    sources: dict[MetricName, MetricSource] = {}
    updates: dict[str, Any] = {}
    for name, value in metric_values.items():
        if value is not None:
            sources[name] = MetricSource(
                source=stats.source_id,
                measurement="actual",
                evidence_ids=[stats.evidence_id],
            )
            updates[name] = value
    if sources:
        updates["metric_sources"] = sources
    return call.model_copy(update=updates)
