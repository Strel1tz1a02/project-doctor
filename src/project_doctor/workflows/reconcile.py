"""Interruption reconciliation: classify and resolve operations left mid-flight."""

from __future__ import annotations

from sqlalchemy import Engine, update

from project_doctor.features.environments.ports import EnvironmentGateway
from project_doctor.integrations.mysql.environment_state import (
    list_operations,
    load_environment_state,
)
from project_doctor.integrations.mysql.migrations.schema import environment_health
from project_doctor.models.common import EnvironmentHealth
from project_doctor.models.environment import RestoreResult
from project_doctor.models.experiment import ExperimentResult, ReconciledOperation, ReconcileResult
from project_doctor.workflows.task_ports import TaskStore


def classify_operation(*, state: str, has_result: bool) -> str:
    """Return ``completed``, ``safe_same_input`` or ``needs_reconcile``.

    A stored result means the operation ran to a determinate end. A reserved operation
    with no result never began, so it is safe to re-execute. Anything else is unknown.
    """
    if has_result and state in ("completed", "failed"):
        return "completed"
    if state == "reserved":
        return "safe_same_input"
    return "needs_reconcile"


async def reconcile(
    *, task_id: str, store: TaskStore, engine: Engine, gateway: EnvironmentGateway
) -> ReconcileResult:
    """Compare persisted state against the live environment and file a verdict.

    Side effects are never replayed here: completed operations are returned, never
    re-run; unknown operations are reported as unresolved and the environment is
    quarantined rather than trusted.
    """
    persisted = load_environment_state(engine, task_id)
    actual_health = await gateway.health(task_id)

    operation_results: list[ReconciledOperation] = []
    unresolved: list[str] = []
    for row in list_operations(engine, task_id):
        stored = await store.load_operation(task_id, row.operation_id)
        verdict = classify_operation(
            state=row.state,
            has_result=stored is not None
            and (stored.payload is not None or stored.failure is not None),
        )
        if verdict == "completed" and stored is not None:
            result = (
                stored.payload
                if isinstance(stored.payload, (ExperimentResult, RestoreResult))
                else None
            )
            operation_results.append(
                ReconciledOperation(
                    operation_id=row.operation_id,
                    state="completed" if stored.state == "completed" else "failed",
                    result=result,
                    reason=None,
                )
            )
        elif verdict == "safe_same_input":
            operation_results.append(
                ReconciledOperation(
                    operation_id=row.operation_id,
                    state="failed",
                    result=None,
                    reason="reserved but never started; safe to re-execute",
                )
            )
        else:
            unresolved.append(row.operation_id)

    if unresolved:
        health: EnvironmentHealth = "quarantined"
        with engine.begin() as conn:
            conn.execute(
                update(environment_health)
                .where(environment_health.c.task_id == task_id)
                .values(health=health)
            )
    elif persisted is not None and persisted.health == "quarantined":
        health = "quarantined"
    elif persisted is not None and actual_health == "available":
        health = "available"
    else:
        health = actual_health

    return ReconcileResult(
        task_id=task_id,
        environment_health=health,
        operation_results=operation_results,
        unresolved_operations=unresolved,
        evidence_refs=[],
    )
