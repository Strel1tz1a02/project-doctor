import asyncio
import json

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


def test_request_id_cannot_inject_lock_query() -> None:
    import pytest

    with pytest.raises(ValueError):
        current_locks_sql("' OR 1=1")
