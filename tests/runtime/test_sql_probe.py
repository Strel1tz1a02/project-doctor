"""Unit tests for the SqlProbe: marker parsing, metric conversion, evidence publication."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import pytest

from project_doctor.integrations.observation.sql_probe import (
    PERF_SCHEMA_COLUMNS,
    PerfSchemaSqlProbe,
    extract_code_location,
    lock_wait_to_ms,
    normalize_sql,
    parse_mysql_batch,
    perf_schema_row_to_sql_call,
    recent_tagged_statements_sql,
    substitute_placeholders,
    timer_wait_to_ms,
)
from project_doctor.models.common import EvidenceRef
from project_doctor.models.task import CallContext

COMMIT = "9f497db5d4ea09d37f3d07bcda3471c71c815031"
EVIDENCE_ID = "sql-evidence:op-1"


def _context() -> CallContext:
    return CallContext(
        task_id="task-1",
        operation_id="op-1",
        missing_correlation=["agh_session_id", "tool_call_id"],
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _publisher() -> tuple[Any, list[EvidenceRef]]:
    refs: list[EvidenceRef] = []

    async def publish(
        relative_path: str, content: bytes, media_type: str, format_version: str
    ) -> EvidenceRef:
        digest = _sha256(content)
        ref = EvidenceRef(
            artifact_id=digest,
            relative_path=relative_path,
            media_type=media_type,
            format_version=format_version,
            sha256=digest,
            size_bytes=len(content),
        )
        refs.append(ref)
        return ref

    return publish, refs


# --- marker / SQL text ------------------------------------------------------


def test_recent_tagged_statements_sql_selects_and_flattens() -> None:
    sql = recent_tagged_statements_sql(64)
    assert "performance_schema.events_statements_history_long" in sql
    assert "REPLACE(REPLACE(SQL_TEXT" in sql
    assert "SQL_TEXT LIKE '/* pd:%'" in sql
    assert "LIMIT 64" in sql


def test_normalize_sql_strips_marker_and_collapses_whitespace() -> None:
    tagged = "/* pd:src/main/App.java:42 */   SELECT o.*\nFROM orders o\tWHERE id = ?"
    assert normalize_sql(tagged) == "SELECT o.* FROM orders o WHERE id = ?"


def test_normalize_sql_trims_trailing_semicolon() -> None:
    assert normalize_sql("/* pd:a/b.sql:1 */ SELECT 1;") == "SELECT 1"


def test_substitute_placeholders_replaces_jdbc_marks() -> None:
    assert (
        substitute_placeholders("SELECT * FROM t WHERE a = ? LIMIT ?")
        == "SELECT * FROM t WHERE a = 0 LIMIT 0"
    )


# --- metric conversion ------------------------------------------------------


def test_timer_wait_to_ms_converts_picoseconds() -> None:
    assert timer_wait_to_ms(412_000_000_000) == 412.0
    assert timer_wait_to_ms("0") == 0.0


def test_timer_wait_to_ms_rejects_garbage() -> None:
    assert timer_wait_to_ms(None) is None
    assert timer_wait_to_ms("") is None
    assert timer_wait_to_ms("NULL") is None
    assert timer_wait_to_ms("not-a-number") is None


def test_lock_wait_to_ms_zeroes_timer_noise() -> None:
    assert lock_wait_to_ms(2_000_000) == 0.0  # 2 µs of MDL timing, not contention
    assert lock_wait_to_ms(5_000_000_000) == 5.0  # 5 ms stays clearly non-zero
    assert lock_wait_to_ms("0") == 0.0
    assert lock_wait_to_ms("NULL") is None


# --- code location ----------------------------------------------------------


def test_extract_code_location_parses_marker() -> None:
    location = extract_code_location("/* pd:src/main/App.java:42 */ SELECT 1", COMMIT, EVIDENCE_ID)
    assert location is not None
    assert location.commit == COMMIT
    assert location.path == "src/main/App.java"
    assert location.line == 42
    assert location.association_evidence_ids == [EVIDENCE_ID]


def test_extract_code_location_returns_none_when_untagged() -> None:
    assert extract_code_location("SELECT 1", COMMIT, EVIDENCE_ID) is None


def test_extract_code_location_rejects_unsafe_paths() -> None:
    with pytest.raises(ValueError):
        extract_code_location("/* pd:/abs/App.java:5 */ SELECT 1", COMMIT, EVIDENCE_ID)
    with pytest.raises(ValueError):
        extract_code_location("/* pd:../App.java:5 */ SELECT 1", COMMIT, EVIDENCE_ID)


def test_extract_code_location_rejects_nonpositive_line() -> None:
    with pytest.raises(ValueError):
        extract_code_location("/* pd:src/App.java:0 */ SELECT 1", COMMIT, EVIDENCE_ID)


# --- row → SqlCall ----------------------------------------------------------


def test_perf_schema_row_to_sql_call_builds_actual_sources() -> None:
    call = perf_schema_row_to_sql_call(
        {
            "SQL_TEXT": "/* pd:src/main/OrderMapper.java:14 */ SELECT o.* FROM orders o",
            "TIMER_WAIT": "412000000000",
            "ROWS_EXAMINED": "200000",
            "ROWS_SENT": "20",
            "LOCK_TIME": "0",
        },
        commit=COMMIT,
        evidence_id=EVIDENCE_ID,
        call_id="sql-op-1-0",
    )
    assert call.id == "sql-op-1-0"
    assert call.normalized_sql == "SELECT o.* FROM orders o"
    assert call.duration_ms == 412.0
    assert call.rows_examined == 200000
    assert call.rows_returned == 20
    assert call.lock_wait_ms == 0.0
    assert set(call.metric_sources) == {
        "duration_ms",
        "rows_examined",
        "rows_returned",
        "lock_wait_ms",
    }
    assert all(
        source.source == "performance_schema"
        and source.measurement == "actual"
        and source.evidence_ids == [EVIDENCE_ID]
        for source in call.metric_sources.values()
    )
    assert call.code_location is not None
    assert call.code_location.line == 14


def test_perf_schema_row_to_sql_call_omits_missing_metrics() -> None:
    call = perf_schema_row_to_sql_call(
        {
            "SQL_TEXT": "/* pd:src/App.java:1 */ SELECT 1",
            "TIMER_WAIT": "1000000000",
            "ROWS_EXAMINED": "3",
            "ROWS_SENT": "NULL",
            "LOCK_TIME": "NULL",
        },
        commit=COMMIT,
        evidence_id=EVIDENCE_ID,
        call_id="sql-op-1-1",
    )
    assert call.rows_returned is None
    assert call.lock_wait_ms is None
    assert set(call.metric_sources) == {"duration_ms", "rows_examined"}


def test_perf_schema_row_to_sql_call_rejects_empty_sql() -> None:
    with pytest.raises(ValueError):
        perf_schema_row_to_sql_call(
            {"SQL_TEXT": ""}, commit=COMMIT, evidence_id=EVIDENCE_ID, call_id="sql-op-1-2"
        )


# --- batch parsing ----------------------------------------------------------


def test_parse_mysql_batch_roundtrip() -> None:
    output = "SELECT 1\t1000000000\t10\t2\t0\nSELECT 2\t2000000000\t5\t1\t0\n"
    rows = parse_mysql_batch(output, PERF_SCHEMA_COLUMNS)
    assert rows == [
        {
            "SQL_TEXT": "SELECT 1",
            "TIMER_WAIT": "1000000000",
            "ROWS_EXAMINED": "10",
            "ROWS_SENT": "2",
            "LOCK_TIME": "0",
        },
        {
            "SQL_TEXT": "SELECT 2",
            "TIMER_WAIT": "2000000000",
            "ROWS_EXAMINED": "5",
            "ROWS_SENT": "1",
            "LOCK_TIME": "0",
        },
    ]


def test_parse_mysql_batch_skips_blank_lines() -> None:
    assert parse_mysql_batch("\n\n", PERF_SCHEMA_COLUMNS) == []


def test_parse_mysql_batch_rejects_mismatched_columns() -> None:
    with pytest.raises(ValueError):
        parse_mysql_batch("SELECT 1\t1000000000\n", PERF_SCHEMA_COLUMNS)


# --- probe collection -------------------------------------------------------

_GOOD_ROW = {
    "SQL_TEXT": "/* pd:src/main/OrderMapper.java:14 */ SELECT o.* FROM orders o WHERE status = ?",
    "TIMER_WAIT": "412000000000",
    "ROWS_EXAMINED": "200000",
    "ROWS_SENT": "20",
    "LOCK_TIME": "0",
}


def test_perf_schema_probe_publishes_and_attaches_evidence() -> None:
    rows = [
        _GOOD_ROW,
        {
            "SQL_TEXT": "",
            "TIMER_WAIT": "0",
            "ROWS_EXAMINED": "0",
            "ROWS_SENT": "0",
            "LOCK_TIME": "0",
        },
    ]

    async def fake_fetcher(context: CallContext, sql: str) -> list[dict[str, Any]]:
        assert "events_statements_history_long" in sql
        return rows

    async def fake_explain(context: CallContext, sql: str) -> str:
        assert "?" not in sql
        return json.dumps(
            {
                "query_block": {
                    "table": {"access_type": "ALL", "rows_examined_per_scan": 200000, "key": None}
                }
            }
        )

    publish, refs = _publisher()
    probe = PerfSchemaSqlProbe(fetch_rows=fake_fetcher, explain=fake_explain, publish=publish)
    collection = asyncio.run(probe(None, None, _context(), COMMIT, "baseline"))  # type: ignore[arg-type]

    assert len(collection.calls) == 1
    call = collection.calls[0]
    assert call.id == "sql-op-1-0"
    assert call.code_location is not None
    assert call.code_location.commit == COMMIT

    raw_ref, plan_ref = refs
    assert call.code_location.association_evidence_ids == [raw_ref.artifact_id]
    assert all(
        source.evidence_ids == [raw_ref.artifact_id] for source in call.metric_sources.values()
    )
    assert call.plan_evidence_ids == [plan_ref.artifact_id]
    assert {ref.artifact_id for ref in collection.evidence_refs} == {
        raw_ref.artifact_id,
        plan_ref.artifact_id,
    }


def test_perf_schema_probe_returns_empty_when_no_rows() -> None:
    async def fake_fetcher(context: CallContext, sql: str) -> list[dict[str, Any]]:
        return []

    async def fake_explain(context: CallContext, sql: str) -> str:
        raise AssertionError("explain must not run without rows")

    publish, _ = _publisher()
    probe = PerfSchemaSqlProbe(fetch_rows=fake_fetcher, explain=fake_explain, publish=publish)
    collection = asyncio.run(probe(None, None, _context(), COMMIT, "baseline"))  # type: ignore[arg-type]
    assert collection.calls == []
    assert collection.evidence_refs == []


def test_perf_schema_probe_degrades_when_explain_is_not_json() -> None:
    async def fake_fetcher(context: CallContext, sql: str) -> list[dict[str, Any]]:
        return [_GOOD_ROW]

    async def fake_explain(context: CallContext, sql: str) -> str:
        return "not json"

    publish, _ = _publisher()
    probe = PerfSchemaSqlProbe(fetch_rows=fake_fetcher, explain=fake_explain, publish=publish)
    collection = asyncio.run(probe(None, None, _context(), COMMIT, "baseline"))  # type: ignore[arg-type]
    assert len(collection.calls) == 1
    assert collection.calls[0].plan_evidence_ids == []
    assert len(collection.evidence_refs) == 1  # raw only, no plan
