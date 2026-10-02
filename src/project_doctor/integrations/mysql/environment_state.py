"""A-internal MySQL state access (not part of the frozen TaskStore protocol)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, select, update

from project_doctor.integrations.mysql.migrations.schema import environment_health, operations


@dataclass(frozen=True)
class EnvironmentState:
    health: str
    environment_id: str | None
    fingerprint: str | None
    baseline_snapshot_id: str | None


@dataclass(frozen=True)
class OperationRow:
    operation_id: str
    state: str


def load_environment_state(engine: Engine, task_id: str) -> EnvironmentState | None:
    """Read the persisted environment health row for a task, or ``None`` if unprepared."""
    with engine.connect() as conn:
        row = conn.execute(
            select(environment_health).where(environment_health.c.task_id == task_id)
        ).one_or_none()
    if row is None:
        return None
    return EnvironmentState(
        health=row.health,
        environment_id=row.environment_id,
        fingerprint=row.fingerprint,
        baseline_snapshot_id=row.baseline_snapshot_id,
    )


def mark_operation_running(engine: Engine, task_id: str, operation_id: str) -> None:
    """Transition a reserved operation to ``running`` once side effects begin."""
    with engine.begin() as conn:
        conn.execute(
            update(operations)
            .where(
                operations.c.task_id == task_id,
                operations.c.operation_id == operation_id,
                operations.c.state == "reserved",
            )
            .values(state="running")
        )


def list_operations(engine: Engine, task_id: str) -> list[OperationRow]:
    """Every operation recorded for a task, in insertion-stable order."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(operations.c.operation_id, operations.c.state).where(
                operations.c.task_id == task_id
            )
        ).all()
    return [OperationRow(operation_id=row.operation_id, state=row.state) for row in rows]
