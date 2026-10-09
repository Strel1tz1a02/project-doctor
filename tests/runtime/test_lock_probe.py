import asyncio
import json

import pytest

from project_doctor.integrations.observation.lock_probe import LockProbe, current_locks_sql
from project_doctor.models.common import EvidenceRef
from project_doctor.models.task import CallContext


def test_polling_distinguishes_positive_evidence_from_missing_coverage() -> None:
    async def exercise():
        content = {}

        async def publish(path, raw, media, version):
            content[path] = json.loads(raw)
            return EvidenceRef(
                artifact_id=path,
                relative_path=path,
                media_type=media,
                format_version=version,
                sha256="a" * 64,
                size_bytes=len(raw),
            )

        for event in (
            None,
            {"kind": "innodb_data", "thread_id": 3, "event_id": 4, "sql_text": "SELECT 1"},
        ):

            async def query(context, sql, event=event):
                if "JSON_ARRAYAGG" in sql:
                    return '{"version":"8.4"}'
                return json.dumps(event) if event else ""

            probe = LockProbe(query=query, publish=publish)
            capture = await probe.begin(
                CallContext(
                    task_id="task",
                    operation_id="op",
                    missing_correlation=["agh_session_id", "tool_call_id"],
                ),
                "a" * 32,
            )
            await capture.finish()
            result = capture.evidence_for("SELECT 1", 3, 4, None)
            assert result.status == ("observed" if event else "unknown")
            assert result.coverage == "partial" and result.missing_kinds
            # Another event on the same reused connection does not inherit the wait.
            assert capture.evidence_for("SELECT 1", 3, 5, None).status == "unknown"
        assert len(content) == 3

    asyncio.run(exercise())


def test_collector_failure_is_unknown_and_evidenced() -> None:
    async def exercise():
        async def query(*args):
            raise RuntimeError("consumer unavailable")

        async def publish(path, raw, media, version):
            return EvidenceRef(
                artifact_id=path,
                relative_path=path,
                media_type=media,
                format_version=version,
                sha256="a" * 64,
                size_bytes=len(raw),
            )

        capture = await LockProbe(query=query, publish=publish).begin(
            CallContext(
                task_id="t",
                operation_id="o",
                missing_correlation=["agh_session_id", "tool_call_id"],
            ),
            "a" * 32,
        )
        await capture.finish()
        result = capture.evidence_for("SELECT 1", None, None, 0)
        assert result.status == "unknown" and len(result.evidence_refs) == 3
        assert any("consumer unavailable" in reason for reason in result.reasons)

    asyncio.run(exercise())


def test_covered_no_wait_declares_residual_in_milliseconds() -> None:
    async def exercise():
        counter_calls = 0

        async def query(context, sql):
            nonlocal counter_calls
            if "global_status" in sql:
                counter_calls += 1
                return json.dumps(
                    {
                        "Innodb_row_lock_waits": counter_calls,
                        "Innodb_row_lock_time": counter_calls,
                        "Innodb_row_lock_current_waits": 0,
                        "Uptime": 100,
                        "metadata_enabled": 1,
                        "metadata_count": 10,
                        "metadata_time": 1000,
                    }
                )
            if "JSON_ARRAYAGG" in sql:
                return '{"version":"8.4"}'
            return ""  # no lock events observed across the window

        async def publish(path, raw, media, version):
            return EvidenceRef(
                artifact_id=path,
                relative_path=path,
                media_type=media,
                format_version=version,
                sha256="a" * 64,
                size_bytes=len(raw),
            )

        probe = LockProbe(query=query, publish=publish, interval=0.05)
        capture = await probe.begin(
            CallContext(
                task_id="t",
                operation_id="o",
                missing_correlation=["agh_session_id", "tool_call_id"],
            ),
            "a" * 32,
        )
        await capture.finish()
        result = capture.evidence_for("SELECT 1", 3, 4, 0.0)
        assert result.status == "covered_no_wait"
        assert result.coverage == "complete"
        assert result.residual_ms == 50.0  # 0.05 s poll gap × 1000, not 0.05 ms

    asyncio.run(exercise())


def test_collector_failure_with_valid_statement_cannot_certify_zero() -> None:
    async def run():
        async def query(*args):
            raise RuntimeError("collector unavailable")

        async def publish(path, raw, media, version):
            return EvidenceRef(
                artifact_id=path,
                relative_path=path,
                media_type=media,
                format_version=version,
                sha256="a" * 64,
                size_bytes=len(raw),
            )

        capture = await LockProbe(query=query, publish=publish).begin(
            CallContext(
                task_id="t",
                operation_id="o",
                missing_correlation=["agh_session_id", "tool_call_id"],
            ),
            "a" * 32,
        )
        await capture.finish()
        result = capture.evidence_for("SELECT 1", 3, 4, 0)
        assert result.status == "unknown" and result.coverage == "partial"

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode", ["zero", "short_wait", "metadata_delay", "table_delay", "disabled", "reset", "failure"]
)
def test_global_counters_and_failure_modes(mode: str) -> None:
    async def run():
        counter_calls = 0

        async def query(context, sql):
            nonlocal counter_calls
            if "global_status" in sql:
                counter_calls += 1
                values = {
                    "Innodb_row_lock_waits": 7,
                    "Innodb_row_lock_time": 19,
                    "Innodb_row_lock_current_waits": 0,
                    "Uptime": 100,
                    "metadata_enabled": 1,
                    "metadata_count": 10,
                    "metadata_time": 1000,
                }
                if mode == "disabled":
                    values["metadata_enabled"] = 0
                if counter_calls == 2:
                    if mode == "short_wait":
                        values["Innodb_row_lock_waits"] += 1
                    if mode == "metadata_delay":
                        values["metadata_time"] += 100_000_000
                    if mode == "reset":
                        values["Uptime"] = 0
                        values["metadata_count"] = 0
                return json.dumps(values)
            if "JSON_ARRAYAGG" in sql:
                return '{"version":"8.4"}'
            if mode == "failure":
                raise RuntimeError("sampling failed")
            return ""

        async def publish(path, raw, media, version):
            return EvidenceRef(
                artifact_id=path,
                relative_path=path,
                media_type=media,
                format_version=version,
                sha256="a" * 64,
                size_bytes=len(raw),
            )

        capture = await LockProbe(query=query, publish=publish).begin(
            CallContext(
                task_id="t",
                operation_id="o",
                missing_correlation=["agh_session_id", "tool_call_id"],
            ),
            "a" * 32,
        )
        await capture.finish()
        result = capture.evidence_for("SELECT 1", 3, 4, 0.003 if mode == "table_delay" else 0)
        if mode in {"disabled", "reset", "failure"}:
            assert result.status == "unknown" and result.coverage == "partial"
        elif mode == "zero":
            assert result.status == "covered_no_wait" and result.residual_ms is None
            assert set(result.covered_kinds) == {"table", "metadata", "innodb_data"}
        elif mode == "table_delay":
            assert result.status == "observed" and result.coverage == "complete"
            assert result.residual_ms == 0.003
        else:
            assert result.status == "covered_no_wait" and result.residual_ms is not None
            assert result.residual_ms == (0.1 if mode == "metadata_delay" else 50.0)

    asyncio.run(run())


def test_request_id_cannot_inject_lock_query() -> None:
    import pytest

    with pytest.raises(ValueError):
        current_locks_sql("' OR 1=1")
