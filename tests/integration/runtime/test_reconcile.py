"""A4 interruption reconciliation: classify operations and quarantine unknowns."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import create_engine, insert

from project_doctor.integrations.mysql.migrations.schema import (
    create_schema,
    environment_health,
    operations,
)
from project_doctor.models.task import OperationResult, TaskBundle
from project_doctor.workflows.reconcile import classify_operation, reconcile

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


def test_classify_operation() -> None:
    assert classify_operation(state="completed", has_result=True) == "completed"
    assert classify_operation(state="reserved", has_result=False) == "safe_same_input"
    assert classify_operation(state="running", has_result=False) == "needs_reconcile"
    # A stored result means a determinate end regardless of the stored state.
    assert classify_operation(state="running", has_result=True) == "completed"


class FakeStore:
    def __init__(self, done: OperationResult | None) -> None:
        self.done = done

    async def load_operation(self, task_id: str, operation_id: str) -> OperationResult | None:
        if operation_id == "op-done":
            return self.done
        return None


class FakeGateway:
    async def health(self, task_id: str) -> str:
        return "available"


def seed_operations(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(environment_health).values(
                task_id="task-1",
                health="available",
                environment_id="environment-1",
                fingerprint="fingerprint-baseline",
                baseline_snapshot_id="snapshot-1",
            )
        )
        for operation_id, state in (
            ("op-done", "completed"),
            ("op-reserved", "reserved"),
            ("op-running", "running"),
        ):
            conn.execute(
                insert(operations).values(
                    task_id="task-1",
                    operation_id=operation_id,
                    input_digest="a" * 64,
                    state=state,
                )
            )


def test_reconcile_reports_completed_reserved_and_unresolved(tmp_path: Path) -> None:
    case = json.loads((FIXTURES / "verified_slow_query.json").read_text(encoding="utf-8"))
    bundle = TaskBundle.model_validate(case["bundle"])
    done = OperationResult(
        operation_id="op-done",
        state="completed",
        input_digest="a" * 64,
        payload=bundle.experiments[0],
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'state.db'}")
    create_schema(engine)
    seed_operations(engine)

    result = asyncio.run(
        reconcile(task_id="task-1", store=FakeStore(done), engine=engine, gateway=FakeGateway())
    )

    assert result.environment_health == "quarantined"
    assert result.unresolved_operations == ["op-running"]
    by_id = {op.operation_id: op for op in result.operation_results}
    assert by_id["op-done"].state == "completed"
    assert by_id["op-done"].result is not None
    assert by_id["op-reserved"].state == "failed"
    assert by_id["op-reserved"].result is None


def test_reconcile_available_when_everything_resolved(tmp_path: Path) -> None:
    case = json.loads((FIXTURES / "verified_slow_query.json").read_text(encoding="utf-8"))
    bundle = TaskBundle.model_validate(case["bundle"])
    done = OperationResult(
        operation_id="op-done",
        state="completed",
        input_digest="a" * 64,
        payload=bundle.experiments[0],
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'state.db'}")
    create_schema(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(environment_health).values(
                task_id="task-1",
                health="available",
                environment_id="environment-1",
                fingerprint="fingerprint-baseline",
                baseline_snapshot_id="snapshot-1",
            )
        )
        conn.execute(
            insert(operations).values(
                task_id="task-1",
                operation_id="op-done",
                input_digest="a" * 64,
                state="completed",
            )
        )

    result = asyncio.run(
        reconcile(task_id="task-1", store=FakeStore(done), engine=engine, gateway=FakeGateway())
    )

    assert result.environment_health == "available"
    assert result.unresolved_operations == []
    assert [op.state for op in result.operation_results] == ["completed"]
