"""Collect SQL statements for a request and map them to code locations and plan evidence.

The target application tags every statement with a
``/* pd:<path>:<line> request=<32 hex digits> */`` marker
via a MyBatis interceptor. The probe reads those tagged statements from MySQL
``performance_schema.events_statements_history_long``, publishes the raw rows and one
``EXPLAIN FORMAT=JSON`` plan per statement as artifacts, and returns ``SqlCall`` items
whose metric sources, code locations and plan references all cite the published artifact
    ids, so B's evidence gate can resolve them.

The row fetcher, explain fetcher and publisher are injected so this module never talks
to Docker/MySQL directly; the real implementations run ``mysql --batch`` inside the
isolated db container and write artifacts under the artifact root.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from project_doctor.integrations.http.requests import HttpResponse
from project_doctor.integrations.observation.plans import PlanEstimate, attach_plan, parse_plan
from project_doctor.models.common import CodeLocation, EvidenceRef, safe_relative_path
from project_doctor.models.lock import LockEvidence
from project_doctor.models.observation import ExperimentLevel, MetricName, MetricSource, SqlCall
from project_doctor.models.scenario import RequestStep
from project_doctor.models.task import CallContext

_CODE_MARKER = re.compile(
    r"\A\s*/\*\s*pd:(?P<path>[^:\s]+):(?P<line>\d+)"
    r"(?:\s+request=(?P<request>[a-f0-9]{32}))?\s*\*/"
)

PERF_SCHEMA_COLUMNS: tuple[str, ...] = (
    "SQL_TEXT",
    "TIMER_WAIT",
    "ROWS_EXAMINED",
    "ROWS_SENT",
    "LOCK_TIME",
    "THREAD_ID",
    "EVENT_ID",
)

SqlRowFetcher = Callable[[CallContext, str], Awaitable[list[dict[str, Any]]]]
ExplainFetcher = Callable[[CallContext, str], Awaitable[str]]
LockWaitCounter = Callable[[CallContext, str], Awaitable[int]]
EvidencePublisher = Callable[[str, bytes, str, str], Awaitable[EvidenceRef]]


@dataclass(frozen=True)
class SqlCollection:
    """One probe pass: the mapped calls plus every artifact they cite."""

    calls: list[SqlCall]
    evidence_refs: list[EvidenceRef]
    statement_rows: dict[str, dict[str, Any]] = field(default_factory=dict)


def recent_tagged_statements_sql(limit: int, request_id: str | None = None) -> str:
    """Return the query for the most recent marker-tagged statements.

    Newlines and tabs in ``SQL_TEXT`` are flattened so ``mysql --batch`` output
    stays one row per line.
    """
    if limit <= 0:
        raise ValueError("history limit must be positive")
    if request_id is not None and not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise ValueError("invalid request correlation id")
    scope = f"AND SQL_TEXT LIKE '% request={request_id} */%' " if request_id else "AND 1=0 "
    return (
        "SELECT "
        "REPLACE(REPLACE(SQL_TEXT, '\\n', ' '), '\\t', ' ') AS SQL_TEXT, "
        "TIMER_WAIT, ROWS_EXAMINED, ROWS_SENT, LOCK_TIME, THREAD_ID, EVENT_ID "
        "FROM performance_schema.events_statements_history_long "
        "WHERE SQL_TEXT LIKE '/* pd:%' " + scope + "ORDER BY TIMER_START DESC "
        f"LIMIT {limit}"
    )


def row_lock_waits_sql() -> str:
    """Return the query that counts active InnoDB row lock waits.

    This is a live snapshot only. It cannot recover a wait that resolved before
    collection, identify the request's interval, or establish total lock coverage.
    """
    return "SELECT COUNT(*) FROM performance_schema.data_lock_waits"


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
    """Convert the per-statement ``LOCK_TIME`` (picoseconds) to milliseconds.

    Since MySQL 8.0.28 ``LOCK_TIME`` accumulates SQL table-lock and InnoDB
    row-lock (data-lock) wait time for the statement; it excludes metadata-lock
    (MDL) waits. A nonzero value must stay nonzero (no rounding) so a tiny wait
    cannot be smuggled past the diagnosis gate's zero-wait threshold. MDL is the
    only kind not covered here; ``lock_probe`` bounds it separately.
    """
    if lock_time is None or lock_time == "":
        return None
    try:
        return float(lock_time) / 1_000_000_000
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
    lock_wait_complete: bool = False,
    lock_wait_evidence_id: str | None = None,
) -> SqlCall:
    """Convert one ``performance_schema`` row into a SqlCall with actual metric sources.

    ``LOCK_TIME`` is the per-statement table+row lock wait and becomes the
    ``lock_wait_ms`` metric; MDL is bounded separately by ``lock_probe``. The
    legacy lock flags remain accepted for caller compatibility but never
    establish interval coverage.
    """
    del lock_wait_complete, lock_wait_evidence_id
    sql_text = str(row.get("SQL_TEXT", ""))
    normalized = normalize_sql(sql_text)
    if not normalized:
        raise ValueError("statement row has no SQL text")
    code_location = extract_code_location(sql_text, commit, evidence_id)

    duration_ms = timer_wait_to_ms(row.get("TIMER_WAIT"))
    rows_examined = _as_int(row.get("ROWS_EXAMINED"))
    rows_returned = _as_int(row.get("ROWS_SENT"))
    # LOCK_TIME is the authoritative per-statement table+row lock wait (8.0.28+);
    # MDL is the only uncovered kind and is bounded separately by lock_probe.
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


def attach_lock_evidence(call: SqlCall, evidence: LockEvidence) -> SqlCall:
    """Attach lock coverage; ``lock_wait_ms`` stays the measured ``LOCK_TIME``.

    The caller already set ``lock_wait_ms`` from ``perf_schema_row_to_sql_call``
    (table + InnoDB row locks). This only adds the MDL bound carried by
    ``evidence.residual_ms`` without overwriting that actual metric.
    """
    payload = call.model_dump(mode="json")
    payload["lock_evidence"] = evidence.model_dump(mode="json")
    return SqlCall.model_validate(payload)


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
    """Legacy helper; the production probe never uses substituted parameter plans."""
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
        fetch_lock_waits: LockWaitCounter | None = None,
        history_limit: int = 64,
    ) -> None:
        self._fetch_rows = fetch_rows
        self._explain = explain
        self._publish = publish
        self._fetch_lock_waits = fetch_lock_waits
        self._history_limit = history_limit

    async def __call__(
        self,
        step: RequestStep,
        response: HttpResponse,
        context: CallContext,
        commit: str,
        level: ExperimentLevel,
    ) -> SqlCollection:
        # Only SQL tagged with this client's unique request ID is admissible.
        del step
        if response is None or response.request_id is None:
            return SqlCollection(calls=[], evidence_refs=[])
        request_id = response.request_id
        rows = await self._fetch_rows(
            context, recent_tagged_statements_sql(self._history_limit, request_id)
        )
        rows = [
            row
            for row in rows
            if (
                (marker := _CODE_MARKER.match(str(row.get("SQL_TEXT", "")))) is not None
                and marker.group("request") == request_id
            )
        ]
        if not rows:
            return SqlCollection(calls=[], evidence_refs=[])

        base = f"tasks/{context.task_id}/experiments/{context.operation_id}/{level}/{request_id}"
        evidence: dict[str, EvidenceRef] = {}
        raw_ref = await self._publish_evidence(
            base,
            "perf-schema",
            json.dumps(rows, ensure_ascii=False).encode("utf-8"),
            "application/json",
            "perf-schema.v1",
            evidence,
        )

        lock_wait_complete = False
        lock_wait_evidence_id: str | None = None
        if self._fetch_lock_waits is not None:
            count = await self._fetch_lock_waits(context, row_lock_waits_sql())
            # This snapshot is diagnostic context, never interval coverage.
            lock_wait_complete = False
            lock_ref = await self._publish_evidence(
                base,
                "row-lock-waits",
                json.dumps({"data_lock_waits_count": count}, ensure_ascii=False).encode("utf-8"),
                "application/json",
                "row-lock-waits.v1",
                evidence,
            )
            lock_wait_evidence_id = lock_ref.artifact_id

        calls: list[SqlCall] = []
        statement_rows: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(rows):
            try:
                call = perf_schema_row_to_sql_call(
                    row,
                    commit=commit,
                    evidence_id=raw_ref.artifact_id,
                    call_id=f"sql-{request_id}-{index}",
                    lock_wait_complete=lock_wait_complete,
                    lock_wait_evidence_id=lock_wait_evidence_id,
                )
            except ValueError:
                continue
            plan = await self._collect_plan(
                context, call.normalized_sql, level, index, base, evidence
            )
            if plan is not None:
                call = attach_plan(call, plan)
            calls.append(call)
            statement_rows[call.id] = dict(row)
        return SqlCollection(
            calls=calls, evidence_refs=list(evidence.values()), statement_rows=statement_rows
        )

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
            if "?" in sql:
                return None
            raw = await self._explain(context, sql)
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
