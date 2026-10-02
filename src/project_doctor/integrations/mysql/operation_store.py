"""Operation records: reserve, load and settle with idempotency on the unique key."""

from __future__ import annotations

from sqlalchemy import Connection, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError

from project_doctor.integrations.mysql.migrations.schema import operations
from project_doctor.models.task import OperationResult, Reservation


def reserve_operation(
    conn: Connection,
    *,
    task_id: str,
    operation_id: str,
    input_digest: str,
    request_allowance: int,
) -> Reservation:
    """Reserve once per (task, operation). Idempotent via the unique key, never read-then-write."""
    try:
        conn.execute(
            mysql_insert(operations).values(
                task_id=task_id,
                operation_id=operation_id,
                input_digest=input_digest,
                state="reserved",
                request_allowance=request_allowance,
            )
        )
    except IntegrityError:
        row = conn.execute(
            select(operations.c.input_digest, operations.c.state, operations.c.result_json).where(
                operations.c.task_id == task_id, operations.c.operation_id == operation_id
            )
        ).one()
        if row.input_digest != input_digest:
            return Reservation(
                accepted=False, reason="operation_conflict: same key with different input"
            )
        if row.state in ("completed", "failed", "needs_reconcile") and row.result_json is not None:
            return Reservation(
                accepted=False, replay_result=OperationResult.model_validate(row.result_json)
            )
        return Reservation(accepted=False, reason="operation already reserved")
    return Reservation(accepted=True)


def load_operation(conn: Connection, *, task_id: str, operation_id: str) -> OperationResult | None:
    """Return the persisted operation, or None when no record exists."""
    row = conn.execute(
        select(operations.c.input_digest, operations.c.state, operations.c.result_json).where(
            operations.c.task_id == task_id, operations.c.operation_id == operation_id
        )
    ).one_or_none()
    if row is None:
        return None
    if row.result_json is not None:
        return OperationResult.model_validate(row.result_json)
    return OperationResult.model_validate(
        {"operation_id": operation_id, "state": row.state, "input_digest": row.input_digest}
    )
