"""Collect SQL statements for a request and map them to code locations and plan evidence.

The target application tags every statement with a ``/* pd:<path>:<line> */`` marker
via a MyBatis interceptor. The probe reads those tagged statements from MySQL
``performance_schema.events_statements_history_long``, publishes the raw rows and one
``EXPLAIN FORMAT=JSON`` plan per statement as artifacts, and returns ``SqlCall`` items
whose metric sources, code locations and plan references all cite the published artifact
ids (their content hashes), so B's evidence gate can resolve them.

The row fetcher, explain fetcher and publisher are injected so this module never talks
to Docker/MySQL directly; the real implementations run ``mysql --batch`` inside the
isolated db container and write artifacts under the artifact root.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from project_doctor.integrations.http.requests import HttpResponse
from project_doctor.integrations.observation.plans import PlanEstimate, attach_plan, parse_plan
from project_doctor.models.common import CodeLocation, EvidenceRef, safe_relative_path
from project_doctor.models.observation import ExperimentLevel, MetricName, MetricSource, SqlCall
from project_doctor.models.scenario import RequestStep
from project_doctor.models.task import CallContext

_CODE_MARKER = re.compile(r"\A\s*/\*\s*pd:(?P<path>[^:\s]+):(?P<line>\d+)\s*\*/")

PERF_SCHEMA_COLUMNS: tuple[str, ...] = (
    "SQL_TEXT",
    "TIMER_WAIT",
    "ROWS_EXAMINED",
    "ROWS_SENT",
    "LOCK_TIME",
)

SqlRowFetcher = Callable[[CallContext, str], Awaitable[list[dict[str, Any]]]]
ExplainFetcher = Callable[[CallContext, str], Awaitable[str]]
EvidencePublisher = Callable[[str, bytes, str, str], Awaitable[EvidenceRef]]


@dataclass(frozen=True)
class SqlCollection:
    """One probe pass: the mapped calls plus every artifact they cite."""

    calls: list[SqlCall]
    evidence_refs: list[EvidenceRef]


def recent_tagged_statements_sql(limit: int) -> str:
    """Return the query for the most recent marker-tagged statements.

    Newlines and tabs in ``SQL_TEXT`` are flattened so ``mysql --batch`` output
    stays one row per line.
    """
    return (
        "SELECT "
        "REPLACE(REPLACE(SQL_TEXT, '\\n', ' '), '\\t', ' ') AS SQL_TEXT, "
        "TIMER_WAIT, ROWS_EXAMINED, ROWS_SENT, LOCK_TIME "
        "FROM performance_schema.events_statements_history_long "
        "WHERE SQL_TEXT LIKE '/* pd:%' "
        "ORDER BY TIMER_START DESC "
        f"LIMIT {limit}"
    )


def normalize_sql(sql_text: str) -> str:
    """Strip the marker comment and collapse whitespace to a single line."""
    text = _CODE_MARKER.sub("", sql_text)
    return " ".join(text.split()).rstrip(";").strip()


def timer_wait_to_ms(timer_wait: Any) -> float | None:
    """Convert ``performance_schema`` TIMER_WAIT (picoseconds) to milliseconds."""
    if timer_wait is None or timer_wait == "":
        return None
    try:
        return round(float(timer_wait) / 1_000_000_000, 3)
    except (TypeError, ValueError):
        return None


def lock_wait_to_ms(lock_time: Any) -> float | None:
    """Convert ``performance_schema`` LOCK_TIME (picoseconds) to milliseconds.

    ``LOCK_TIME`` counts table/metadata-lock wait only (InnoDB row-lock waits are
    reported elsewhere), so a value in the microsecond range is timer granularity,
    not lock contention. Rounding to one decimal place reports 0.0 when there is no
    meaningful wait while a real contention of several milliseconds stays non-zero.
    """
    if lock_time is None or lock_time == "":
        return None
    try:
        return round(float(lock_time) / 1_000_000_000, 1)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_code_location(sql_text: str, commit: str, evidence_id: str) -> CodeLocation | None:
    """Parse the ``/* pd:<path>:<line> */`` marker into a code location.

    Returns None when the statement is untagged. Raises ValueError when the marker
    is malformed (absolute path, ``..`` escape, or non-positive line) so collection
    fails loudly instead of fabricating a location.
    """
    match = _CODE_MARKER.match(sql_text)
    if match is None:
        return None
    path = match.group("path")
    line = int(match.group("line"))
    if line <= 0:
        raise ValueError("code-location marker has a non-positive line")
    safe_relative_path(path)
    return CodeLocation(
        commit=commit,
        path=path,
        line=line,
        association_evidence_ids=[evidence_id],
    )


def perf_schema_row_to_sql_call(
    row: Mapping[str, Any],
    *,
    commit: str,
    evidence_id: str,
    call_id: str,
) -> SqlCall:
    """Convert one ``performance_schema`` row into a SqlCall with actual metric sources."""
    sql_text = str(row.get("SQL_TEXT", ""))
    normalized = normalize_sql(sql_text)
    if not normalized:
        raise ValueError("statement row has no SQL text")
    code_location = extract_code_location(sql_text, commit, evidence_id)

    duration_ms = timer_wait_to_ms(row.get("TIMER_WAIT"))
    rows_examined = _as_int(row.get("ROWS_EXAMINED"))
    rows_returned = _as_int(row.get("ROWS_SENT"))
    lock_wait_ms = lock_wait_to_ms(row.get("LOCK_TIME"))

    metric_sources: dict[MetricName, MetricSource] = {}
    actual = MetricSource(
        source="performance_schema", measurement="actual", evidence_ids=[evidence_id]
    )
    if duration_ms is not None:
        metric_sources["duration_ms"] = actual
    if rows_examined is not None:
        metric_sources["rows_examined"] = actual
    if rows_returned is not None:
        metric_sources["rows_returned"] = actual
    if lock_wait_ms is not None:
        metric_sources["lock_wait_ms"] = actual

    return SqlCall(
        id=call_id,
        normalized_sql=normalized,
        duration_ms=duration_ms,
        rows_examined=rows_examined,
        rows_returned=rows_returned,
        lock_wait_ms=lock_wait_ms,
        metric_sources=metric_sources,
        code_location=code_location,
    )


def parse_mysql_batch(output: str, columns: Sequence[str]) -> list[dict[str, Any]]:
    """Parse ``mysql --batch --skip-column-names`` output into column-keyed rows."""
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        values = line.split("\t")
        if len(values) != len(columns):
            raise ValueError("mysql batch row does not match the expected columns")
        rows.append(dict(zip(columns, values, strict=True)))
    return rows


def substitute_placeholders(sql: str, *, value: str = "0") -> str:
    """Replace JDBC ``?`` placeholders with a literal so ``EXPLAIN`` can parse the text.

    ``performance_schema.SQL_TEXT`` holds the prepared-statement form with ``?`` for
    bound values; MySQL rejects ``?`` as SQL. Replacing with ``0`` yields a parseable
    statement whose access shape is still decided by the indexes present. A real
    interceptor that binds actual values would be more faithful but is app-side.
    """
    return sql.replace("?", value)


class PerfSchemaSqlProbe:
    """Collect tagged statements, publish raw + plan evidence, and map to SqlCalls.

    The probe is a ``SqlProbe``: it is bound to a row fetcher, an explain fetcher and
    a publisher, and receives the request/response plus the operation context, target
    commit and level at call time.
    """

    def __init__(
        self,
        *,
        fetch_rows: SqlRowFetcher,
        explain: ExplainFetcher,
        publish: EvidencePublisher,
        history_limit: int = 64,
    ) -> None:
        self._fetch_rows = fetch_rows
        self._explain = explain
        self._publish = publish
        self._history_limit = history_limit

    async def __call__(
        self,
        step: RequestStep,
        response: HttpResponse,
        context: CallContext,
        commit: str,
        level: ExperimentLevel,
    ) -> SqlCollection:
        # Collection is a recent-statement window (serial load -> one request at a
        # time), so the request parameters and response are not needed for mapping.
        del step, response
        rows = await self._fetch_rows(context, recent_tagged_statements_sql(self._history_limit))
        if not rows:
            return SqlCollection(calls=[], evidence_refs=[])

        base = f"tasks/{context.task_id}/experiments/{context.operation_id}/{level}"
        evidence: dict[str, EvidenceRef] = {}
        raw_ref = await self._publish_evidence(
            base,
            "perf-schema",
            json.dumps(rows, ensure_ascii=False).encode("utf-8"),
            "application/json",
            "perf-schema.v1",
            evidence,
        )

        calls: list[SqlCall] = []
        for index, row in enumerate(rows):
            try:
                call = perf_schema_row_to_sql_call(
                    row,
                    commit=commit,
                    evidence_id=raw_ref.artifact_id,
                    call_id=f"sql-{context.operation_id}-{index}",
                )
            except ValueError:
                continue
            plan = await self._collect_plan(
                context, call.normalized_sql, level, index, base, evidence
            )
            if plan is not None:
                call = attach_plan(call, plan)
            calls.append(call)
        return SqlCollection(calls=calls, evidence_refs=list(evidence.values()))

    async def _collect_plan(
        self,
        context: CallContext,
        sql: str,
        level: str,
        index: int,
        base: str,
        evidence: dict[str, EvidenceRef],
    ) -> PlanEstimate | None:
        try:
            raw = await self._explain(context, substitute_placeholders(sql))
            plan_doc = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return None
        plan_ref = await self._publish_evidence(
            base,
            f"explain-{index}",
            raw.encode("utf-8"),
            "application/json",
            "explain.v1",
            evidence,
        )
        return parse_plan(plan_doc, plan_ref.artifact_id)

    async def _publish_evidence(
        self,
        base: str,
        stem: str,
        content: bytes,
        media_type: str,
        format_version: str,
        evidence: dict[str, EvidenceRef],
    ) -> EvidenceRef:
        digest = hashlib.sha256(content).hexdigest()
        relative_path = f"{base}/{stem}-{digest}.json"
        ref = await self._publish(relative_path, content, media_type, format_version)
        evidence[ref.artifact_id] = ref
        return ref
