"""MySQL-backed TaskStore implementing the platform TaskStore protocol.

The status column is the single source of truth for atomic transitions; every other
field lives in a versioned JSON summary column. Operation settlement is idempotent
so a replayed finish never double-charges budget.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, Engine, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError

from project_doctor.integrations.mysql.evidence_index import index_evidence
from project_doctor.integrations.mysql.migrations.schema import (
    environment_health,
    experiments,
    findings,
    hypotheses,
    operations,
    scenarios,
    tasks,
)
from project_doctor.integrations.mysql.operation_store import load_operation, reserve_operation
from project_doctor.models.common import EvidenceRef, TaskStatus, Usage
from project_doctor.models.environment import EnvironmentHandle, RestoreResult
from project_doctor.models.experiment import ExperimentResult
from project_doctor.models.finding import Finding, ReportResult
from project_doctor.models.hypothesis import Hypothesis
from project_doctor.models.scenario import Scenario
from project_doctor.models.task import OperationResult, Reservation, TaskBundle, TaskRecord


class MySQLTaskStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- public async protocol methods --------------------------------------

    async def create(self, task: TaskRecord) -> None:
        await asyncio.to_thread(self._create_sync, task)

    async def get(self, task_id: str) -> TaskRecord:
        return await asyncio.to_thread(self._get_sync, task_id)

    async def save_scenario(self, task_id: str, scenario: Scenario) -> None:
        await asyncio.to_thread(self._save_scenario_sync, task_id, scenario)

    async def save_hypotheses(self, task_id: str, items: list[Hypothesis]) -> None:
        await asyncio.to_thread(self._save_hypotheses_sync, task_id, items)

    async def save_findings(self, task_id: str, items: list[Finding]) -> None:
        await asyncio.to_thread(self._save_findings_sync, task_id, items)

    async def transition(self, task_id: str, expected: TaskStatus, target: TaskStatus) -> bool:
        return await asyncio.to_thread(self._transition_sync, task_id, expected, target)

    async def reserve(
        self, task_id: str, operation_id: str, input_digest: str, request_allowance: int
    ) -> Reservation:
        return await asyncio.to_thread(
            self._reserve_sync, task_id, operation_id, input_digest, request_allowance
        )

    async def finish_operation(
        self, task_id: str, operation_id: str, result: OperationResult, consumed: Usage
    ) -> None:
        await asyncio.to_thread(self._finish_sync, task_id, operation_id, result, consumed)

    async def load_operation(self, task_id: str, operation_id: str) -> OperationResult | None:
        return await asyncio.to_thread(self._load_operation_sync, task_id, operation_id)

    async def load_bundle(self, task_id: str) -> TaskBundle:
        return await asyncio.to_thread(self._load_bundle_sync, task_id)

    # -- sync implementations -----------------------------------------------

    def _create_sync(self, task: TaskRecord) -> None:
        with self._engine.begin() as conn:
            try:
                conn.execute(
                    mysql_insert(tasks).values(
                        id=task.id, status=task.status, record_json=self._record_json(task)
                    )
                )
            except IntegrityError:
                if self._load_task(conn, task.id) != task:
                    raise ValueError(
                        "operation_conflict: same task id with different content"
                    ) from None

    def _get_sync(self, task_id: str) -> TaskRecord:
        with self._engine.connect() as conn:
            return self._load_task(conn, task_id)

    def _save_scenario_sync(self, task_id: str, scenario: Scenario) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                mysql_insert(scenarios)
                .values(
                    task_id=task_id,
                    scenario_id=scenario.id,
                    version=scenario.version,
                    record_json=scenario.model_dump(mode="json"),
                )
                .on_duplicate_key_update(record_json=scenario.model_dump(mode="json"))
            )
            self._add_id(conn, task_id, "scenario_ids", scenario.id)

    def _save_hypotheses_sync(self, task_id: str, items: list[Hypothesis]) -> None:
        with self._engine.begin() as conn:
            for item in items:
                conn.execute(
                    mysql_insert(hypotheses)
                    .values(
                        task_id=task_id,
                        hypothesis_id=item.id,
                        record_json=item.model_dump(mode="json"),
                    )
                    .on_duplicate_key_update(record_json=item.model_dump(mode="json"))
                )
                self._add_id(conn, task_id, "hypothesis_ids", item.id)

    def _save_findings_sync(self, task_id: str, items: list[Finding]) -> None:
        with self._engine.begin() as conn:
            for item in items:
                conn.execute(
                    mysql_insert(findings)
                    .values(
                        task_id=task_id,
                        finding_id=item.id,
                        record_json=item.model_dump(mode="json"),
                    )
                    .on_duplicate_key_update(record_json=item.model_dump(mode="json"))
                )
                self._add_id(conn, task_id, "finding_ids", item.id)

    def _transition_sync(self, task_id: str, expected: TaskStatus, target: TaskStatus) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                update(tasks)
                .where(tasks.c.id == task_id, tasks.c.status == expected)
                .values(status=target)
            )
            return result.rowcount == 1

    def _reserve_sync(
        self, task_id: str, operation_id: str, input_digest: str, request_allowance: int
    ) -> Reservation:
        with self._engine.begin() as conn:
            record = self._load_task(conn, task_id)
            return reserve_operation(
                conn,
                task_id=task_id,
                operation_id=operation_id,
                input_digest=input_digest,
                request_allowance=request_allowance,
                exclusive_preparation=input_digest
                == hashlib.sha256(record.project.model_dump_json().encode("utf-8")).hexdigest(),
            )

    def _load_operation_sync(self, task_id: str, operation_id: str) -> OperationResult | None:
        with self._engine.connect() as conn:
            return load_operation(conn, task_id=task_id, operation_id=operation_id)

    def _finish_sync(
        self, task_id: str, operation_id: str, result: OperationResult, consumed: Usage
    ) -> None:
        with self._engine.begin() as conn:
            state: str = conn.execute(
                select(operations.c.state).where(
                    operations.c.task_id == task_id, operations.c.operation_id == operation_id
                )
            ).scalar_one()
            if state in ("completed", "failed", "needs_reconcile"):
                return
            conn.execute(
                update(operations)
                .where(
                    operations.c.task_id == task_id,
                    operations.c.operation_id == operation_id,
                )
                .values(
                    state=result.state,
                    result_json=result.model_dump(mode="json"),
                    consumed_json=consumed.model_dump(mode="json"),
                )
            )
            self._dispatch(conn, task_id, result)
            self._settle_budget(conn, task_id, consumed)

    def _load_bundle_sync(self, task_id: str) -> TaskBundle:
        with self._engine.connect() as conn:
            task = self._load_task(conn, task_id)
            scenario_records: Sequence[Any] = (
                conn.execute(select(scenarios.c.record_json).where(scenarios.c.task_id == task_id))
                .scalars()
                .all()
            )
            hypothesis_records: Sequence[Any] = (
                conn.execute(
                    select(hypotheses.c.record_json).where(hypotheses.c.task_id == task_id)
                )
                .scalars()
                .all()
            )
            finding_records: Sequence[Any] = (
                conn.execute(select(findings.c.record_json).where(findings.c.task_id == task_id))
                .scalars()
                .all()
            )
            experiment_records: Sequence[Any] = (
                conn.execute(
                    select(experiments.c.record_json).where(experiments.c.task_id == task_id)
                )
                .scalars()
                .all()
            )
            experiment_models = [ExperimentResult.model_validate(row) for row in experiment_records]
            return TaskBundle(
                task=task,
                scenarios=[Scenario.model_validate(row) for row in scenario_records],
                hypotheses=[Hypothesis.model_validate(row) for row in hypothesis_records],
                findings=[Finding.model_validate(row) for row in finding_records],
                experiments=experiment_models,
                evidence_refs=self._gather_refs(experiment_models),
            )

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _record_json(task: TaskRecord) -> dict[str, object]:
        return task.model_dump(mode="json", exclude={"status"})

    def _load_task(self, conn: Connection, task_id: str) -> TaskRecord:
        row = conn.execute(
            select(tasks.c.status, tasks.c.record_json).where(tasks.c.id == task_id)
        ).one_or_none()
        if row is None:
            raise KeyError(task_id)
        data = dict(row.record_json)
        data["status"] = row.status
        return TaskRecord.model_validate(data)

    def _add_id(self, conn: Connection, task_id: str, field: str, value: str) -> None:
        record = self._load_task(conn, task_id)
        ids = list(getattr(record, field))
        if value in ids:
            return
        ids.append(value)
        updated = record.model_copy(update={field: ids})
        conn.execute(
            update(tasks)
            .where(tasks.c.id == task_id)
            .values(record_json=self._record_json(updated))
        )

    def _dispatch(self, conn: Connection, task_id: str, result: OperationResult) -> None:
        if result.failure:
            record = self._load_task(conn, task_id)
            note = f"操作 {result.operation_id}: {result.failure.code}: {result.failure.message}"
            updated = record.model_copy(
                update={"coverage": list(dict.fromkeys([*record.coverage, note]))}
            )
            conn.execute(
                update(tasks)
                .where(tasks.c.id == task_id)
                .values(record_json=self._record_json(updated))
            )
        payload = result.payload
        if isinstance(payload, EnvironmentHandle):
            conn.execute(
                mysql_insert(environment_health)
                .values(
                    task_id=task_id,
                    health=payload.health,
                    environment_id=payload.id,
                    fingerprint=payload.fingerprint,
                    baseline_snapshot_id=payload.baseline_snapshot_id,
                )
                .on_duplicate_key_update(
                    health=payload.health,
                    environment_id=payload.id,
                    fingerprint=payload.fingerprint,
                    baseline_snapshot_id=payload.baseline_snapshot_id,
                )
            )
            record = self._load_task(conn, task_id).model_copy(
                update={"environment_id": payload.id}
            )
            conn.execute(
                update(tasks)
                .where(tasks.c.id == task_id)
                .values(status="running", record_json=self._record_json(record))
            )
        elif isinstance(payload, ExperimentResult):
            conn.execute(
                mysql_insert(experiments)
                .values(
                    task_id=task_id,
                    experiment_id=payload.experiment_id,
                    record_json=payload.model_dump(mode="json"),
                )
                .on_duplicate_key_update(record_json=payload.model_dump(mode="json"))
            )
            self._add_id(conn, task_id, "experiment_ids", payload.experiment_id)
        elif isinstance(payload, RestoreResult):
            conn.execute(
                update(environment_health)
                .where(environment_health.c.task_id == task_id)
                .values(health="available" if payload.verified else "quarantined")
            )
        elif isinstance(payload, ReportResult):
            index_evidence(conn, payload.json_ref)
            index_evidence(conn, payload.html_ref)

    def _settle_budget(self, conn: Connection, task_id: str, consumed: Usage) -> None:
        record = self._load_task(conn, task_id)
        usage = Usage(
            wall_seconds=record.usage.wall_seconds + consumed.wall_seconds,
            requests=record.usage.requests + consumed.requests,
            experiments=record.usage.experiments + consumed.experiments,
            artifact_bytes=record.usage.artifact_bytes + consumed.artifact_bytes,
        )
        updated = record.model_copy(update={"usage": usage})
        conn.execute(
            update(tasks)
            .where(tasks.c.id == task_id)
            .values(record_json=self._record_json(updated))
        )

    @staticmethod
    def _gather_refs(experiment_models: list[ExperimentResult]) -> list[EvidenceRef]:
        by_id: dict[str, EvidenceRef] = {}
        for experiment in experiment_models:
            for item in experiment.preparation_results + experiment.warmup_results:
                for ref in item.evidence_refs:
                    by_id[ref.artifact_id] = ref
            for ref in experiment.evidence_refs:
                by_id[ref.artifact_id] = ref
            for observation in experiment.observations:
                for call in observation.sql_calls:
                    if call.lock_evidence:
                        for ref in call.lock_evidence.evidence_refs:
                            by_id[ref.artifact_id] = ref
                for ref in observation.evidence_refs:
                    by_id[ref.artifact_id] = ref
            if experiment.restore_result is not None:
                for ref in experiment.restore_result.evidence_refs:
                    by_id[ref.artifact_id] = ref
        return list(by_id.values())
