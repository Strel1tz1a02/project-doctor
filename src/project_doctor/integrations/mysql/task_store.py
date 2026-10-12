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

from sqlalchemy import Connection, Engine, insert, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError

from project_doctor.integrations.mysql.evidence_index import index_evidence
from project_doctor.integrations.mysql.migrations.schema import (
    environment_health,
    experiments,
    findings,
    hypotheses,
    operations,
    repairs,
    scenarios,
    tasks,
)
from project_doctor.integrations.mysql.operation_store import load_operation, reserve_operation
from project_doctor.models.common import EvidenceRef, TaskStatus, Usage
from project_doctor.models.environment import EnvironmentHandle, RestoreResult
from project_doctor.models.experiment import ExperimentResult
from project_doctor.models.finding import Finding, ReportResult
from project_doctor.models.hypothesis import Hypothesis
from project_doctor.models.repair import RepairRecord
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

    async def create_repair(self, item: RepairRecord) -> RepairRecord:
        return await asyncio.to_thread(self._create_repair_sync, item)

    async def load_repair(self, task_id: str, repair_id: str) -> RepairRecord | None:
        return await asyncio.to_thread(self._load_repair_sync, task_id, repair_id)

    async def update_repair(self, item: RepairRecord, expected_status: str) -> bool:
        return await asyncio.to_thread(self._update_repair_sync, item, expected_status)

    async def complete_repair(
        self, item: RepairRecord, finding: Finding, expected_status: str
    ) -> bool:
        return await asyncio.to_thread(self._complete_repair_sync, item, finding, expected_status)

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

    async def load_report(self, task_id: str) -> ReportResult | None:
        return await asyncio.to_thread(self._load_report_sync, task_id)

    def _load_report_sync(self, task_id: str) -> ReportResult | None:
        with self._engine.connect() as conn:
            task = self._load_task(conn, task_id)
            rows: Any = conn.execute(
                select(operations.c.result_json).where(
                    operations.c.task_id == task_id,
                    operations.c.state == "completed",
                    operations.c.result_json.is_not(None),
                )
            ).scalars()
            for row in rows:
                payload = OperationResult.model_validate(row).payload
                if isinstance(payload, ReportResult) and payload.task_status == task.status:
                    return payload
        return None

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

    @staticmethod
    def _repair_row(conn: Connection, task_id: str, repair_id: str) -> RepairRecord | None:
        row = conn.execute(
            select(repairs.c.record_json).where(
                repairs.c.task_id == task_id, repairs.c.repair_id == repair_id
            )
        ).scalar_one_or_none()
        return RepairRecord.model_validate(row) if row is not None else None

    def _create_repair_sync(self, item: RepairRecord) -> RepairRecord:
        if item.status != "preparing":
            raise ValueError("new repair must start in preparing")
        with self._engine.begin() as conn:
            self._load_task(conn, item.task_id)
            persisted = conn.execute(
                select(findings.c.finding_id).where(
                    findings.c.task_id == item.task_id,
                    findings.c.finding_id == item.finding_id,
                )
            ).scalar_one_or_none()
            if persisted is None:
                raise ValueError("repair finding is not persisted")
            try:
                conn.execute(
                    insert(repairs).values(
                        task_id=item.task_id,
                        repair_id=item.id,
                        status=item.status,
                        record_json=item.model_dump(mode="json"),
                    )
                )
            except IntegrityError:
                prior = self._repair_row(conn, item.task_id, item.id)
                if prior is None or (
                    prior.finding_id != item.finding_id
                    or prior.patch_sha256 != item.patch_sha256
                    or prior.source_commit != item.source_commit
                    or prior.parent_key_column != item.parent_key_column
                ):
                    raise ValueError(
                        "operation_conflict: repair identity has different input"
                    ) from None
                return prior
        return item

    def _load_repair_sync(self, task_id: str, repair_id: str) -> RepairRecord | None:
        with self._engine.connect() as conn:
            return self._repair_row(conn, task_id, repair_id)

    def _update_repair_sync(self, item: RepairRecord, expected_status: str) -> bool:
        with self._engine.begin() as conn:
            current = self._repair_row(conn, item.task_id, item.id)
            if current is None:
                raise KeyError(item.id)
            self._check_repair_identity(current, item)
            if current == item:
                return True
            if current.status != expected_status:
                return False
            allowed = {
                "preparing": {"built", "failed", "needs_reconcile"},
                "built": {"retesting", "failed", "needs_reconcile"},
                "retesting": {"failed", "needs_reconcile"},
            }
            if item.status not in allowed.get(current.status, set()):
                raise ValueError("invalid repair state transition")
            result = conn.execute(
                update(repairs)
                .where(
                    repairs.c.task_id == item.task_id,
                    repairs.c.repair_id == item.id,
                    repairs.c.status == expected_status,
                )
                .values(status=item.status, record_json=item.model_dump(mode="json"))
            )
            return result.rowcount == 1

    def _complete_repair_sync(
        self, item: RepairRecord, finding: Finding, expected_status: str
    ) -> bool:
        if item.status != "retested" or item.comparison is None or expected_status != "retesting":
            raise ValueError("only a verified retest can complete a repair")
        if finding.task_id != item.task_id or finding.id != item.finding_id:
            raise ValueError("repair completion finding identity differs")
        with self._engine.begin() as conn:
            current = self._repair_row(conn, item.task_id, item.id)
            if current is None:
                raise KeyError(item.id)
            self._check_repair_identity(current, item)
            if current == item:
                stored = conn.execute(
                    select(findings.c.record_json).where(
                        findings.c.task_id == item.task_id,
                        findings.c.finding_id == item.finding_id,
                    )
                ).scalar_one_or_none()
                return stored == finding.model_dump(mode="json")
            if current.status != expected_status:
                return False
            original_json = conn.execute(
                select(findings.c.record_json)
                .where(
                    findings.c.task_id == item.task_id,
                    findings.c.finding_id == item.finding_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if original_json is None:
                raise ValueError("repair finding disappeared")
            original = Finding.model_validate(original_json)
            if original.recommendation is None or finding.recommendation is None:
                raise ValueError("repair finding has no recommendation")
            if (
                finding.recommendation.validation_status != "retested"
                or finding.recommendation.measured_gain_percent
                != item.comparison.measured_gain_percent
                or finding.recommendation.retest_experiment_ids
                != item.comparison.retest_experiment_ids
            ):
                raise ValueError("repair completion differs from verified comparison")
            before = original.model_dump(mode="json")
            after = finding.model_dump(mode="json")
            for key in ("validation_status", "measured_gain_percent", "retest_experiment_ids"):
                before["recommendation"].pop(key)
                after["recommendation"].pop(key)
            if before != after:
                raise ValueError("repair completion changed diagnostic evidence")
            if original.recommendation.validation_status != "expected_mechanism":
                raise ValueError("repair finding was already retested")
            result = conn.execute(
                update(repairs)
                .where(
                    repairs.c.task_id == item.task_id,
                    repairs.c.repair_id == item.id,
                    repairs.c.status == expected_status,
                )
                .values(status=item.status, record_json=item.model_dump(mode="json"))
            )
            if result.rowcount != 1:
                return False
            conn.execute(
                update(findings)
                .where(findings.c.task_id == item.task_id, findings.c.finding_id == item.finding_id)
                .values(record_json=finding.model_dump(mode="json"))
            )
            return True

    @staticmethod
    def _check_repair_identity(current: RepairRecord, item: RepairRecord) -> None:
        if (
            current.task_id != item.task_id
            or current.finding_id != item.finding_id
            or current.operation_id != item.operation_id
            or current.attempt_id != item.attempt_id
            or current.source_commit != item.source_commit
            or current.patch_sha256 != item.patch_sha256
            or current.parent_key_column != item.parent_key_column
        ):
            raise ValueError("operation_conflict: repair identity changed")

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
            # Match reservation lock order, and serialize settlement across IDs.
            # Otherwise concurrent finishers can both read reserved and bill twice.
            conn.execute(select(tasks.c.id).where(tasks.c.id == task_id).with_for_update()).one()
            state: str = conn.execute(
                select(operations.c.state)
                .where(operations.c.task_id == task_id, operations.c.operation_id == operation_id)
                .with_for_update()
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
            repair_records: Sequence[Any] = (
                conn.execute(select(repairs.c.record_json).where(repairs.c.task_id == task_id))
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
                repairs=[RepairRecord.model_validate(row) for row in repair_records],
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
