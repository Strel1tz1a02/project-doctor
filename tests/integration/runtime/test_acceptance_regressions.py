"""Cross-module regressions found during first-delivery acceptance."""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert

from project_doctor.features.diagnosis.gates import evidence_refs
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.integrations.http.requests import HttpResponse
from project_doctor.integrations.mysql.environment_state import load_environment_state
from project_doctor.integrations.mysql.migrations.schema import (
    create_schema,
    environment_health,
    operations,
)
from project_doctor.integrations.mysql.operation_store import load_operation
from project_doctor.integrations.observation.sql_probe import PerfSchemaSqlProbe
from project_doctor.models.task import CallContext, TaskBundle
from project_doctor.workflows.reconcile import reconcile


def test_running_record_from_real_loader_is_quarantined(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'state.db'}")
    create_schema(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(environment_health).values(
                task_id="t",
                health="available",
                environment_id="e",
                fingerprint="f",
                baseline_snapshot_id="s",
            )
        )
        for name, state in (("active", "running"), ("pending", "reserved")):
            conn.execute(
                insert(operations).values(
                    task_id="t",
                    operation_id=name,
                    input_digest="a" * 64,
                    state=state,
                )
            )

    class Store:
        async def load_operation(self, task_id: str, operation_id: str):
            with engine.connect() as conn:
                return load_operation(conn, task_id=task_id, operation_id=operation_id)

    class Gateway:
        async def health(self, task_id: str):
            return "available"

    result = asyncio.run(reconcile(task_id="t", store=Store(), engine=engine, gateway=Gateway()))
    assert result.unresolved_operations == ["active"]
    assert result.environment_health == "quarantined"
    assert result.operation_results[0].operation_id == "pending"
    assert result.operation_results[0].state == "failed"
    assert load_environment_state(engine, "t").health == "quarantined"


def test_identical_plans_at_different_paths_pass_b_gate(tmp_path: Path) -> None:
    async def run():
        refs = [
            await publish_artifact(tmp_path, path, b"{}", "application/json", "explain.v1")
            for path in ("baseline/plan.json", "candidate/plan.json")
        ]
        case = json.loads(
            (
                Path(__file__).resolve().parents[2] / "contracts/fixtures/verified_slow_query.json"
            ).read_text("utf-8")
        )
        result = (
            TaskBundle.model_validate(case["bundle"])
            .experiments[0]
            .model_copy(update={"evidence_refs": refs})
        )
        assert refs[0].sha256 == refs[1].sha256
        assert refs[0].artifact_id != refs[1].artifact_id
        assert len(evidence_refs(result)) >= 2

    asyncio.run(run())


@pytest.mark.parametrize("sql,expected_plans", [("SELECT 1", 1), ("SELECT ?", 0)])
def test_probe_excludes_old_and_unrelated_requests(
    tmp_path: Path, sql: str, expected_plans: int
) -> None:
    request_id = "a" * 32
    explained = []
    context = CallContext(
        task_id="t", operation_id="o", missing_correlation=["agh_session_id", "tool_call_id"]
    )

    async def fetch(context, query):
        assert f"request={request_id}" in query
        return [
            {
                "SQL_TEXT": marker + sql,
                "TIMER_WAIT": 1000000000,
                "ROWS_EXAMINED": 1,
                "ROWS_SENT": 1,
                "LOCK_TIME": 0,
            }
            for marker in (
                f"/* pd:App.java:1 request={request_id} */ ",
                f"/* pd:App.java:1 request={'b' * 32} */ ",
                "/* pd:App.java:1 */ ",
            )
        ]

    async def explain(context, query):
        explained.append(query)
        return '{"query_block":{"table":{"access_type":"ALL","rows":1}}}'

    async def publish(path, content, media, version):
        return await publish_artifact(tmp_path, path, content, media, version)

    probe = PerfSchemaSqlProbe(fetch_rows=fetch, explain=explain, publish=publish)
    response = HttpResponse(200, {}, 1, {}, request_id)
    result = asyncio.run(probe(None, response, context, "c", "baseline"))
    assert len(result.calls) == 1
    assert len(explained) == expected_plans
    assert result.calls[0].lock_wait_ms is None
    assert "lock_wait_ms" not in result.calls[0].metric_sources
    assert result.calls[0].code_location is not None


def test_probe_without_request_id_does_not_fetch_history(tmp_path: Path) -> None:
    async def forbidden(*args):
        raise AssertionError("uncorrelated history must never be read")

    probe = PerfSchemaSqlProbe(fetch_rows=forbidden, explain=forbidden, publish=forbidden)
    context = CallContext(
        task_id="t", operation_id="o", missing_correlation=["agh_session_id", "tool_call_id"]
    )
    result = asyncio.run(probe(None, HttpResponse(200, {}, 1, {}), context, "c", "baseline"))
    assert result.calls == []
