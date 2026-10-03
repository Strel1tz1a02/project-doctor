"""Runtime composition: the RuntimeService and its synchronous factory.

The service owns reservation, budget settlement, environment exclusivity, actual
measurement, restoration and persistence; B never reserves or settles operations.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import Engine, create_engine

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.environments.ports import EnvironmentGateway
from project_doctor.features.environments.prepare import compose_project_name
from project_doctor.features.experiments.interventions import IndexRecipe, parse_index_recipe
from project_doctor.features.experiments.ports import Runtime
from project_doctor.features.experiments.validate import validate_experiment
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.integrations.artifacts.verify import resolve_contained
from project_doctor.integrations.docker.gateway import DockerEnvironmentGateway
from project_doctor.integrations.http.requests import (
    HttpResponse,
    RestrictedHttpClient,
    check_assertions,
)
from project_doctor.integrations.mysql.environment_state import (
    load_environment_state,
    mark_operation_running,
)
from project_doctor.integrations.mysql.factory import resolve_secret_ref
from project_doctor.integrations.observation.sql_probe import (
    PERF_SCHEMA_COLUMNS,
    PerfSchemaSqlProbe,
    SqlCollection,
    parse_mysql_batch,
)
from project_doctor.models.common import EvidenceRef, Usage
from project_doctor.models.environment import EnvironmentHandle, ProjectInput, RestoreResult
from project_doctor.models.errors import Failure
from project_doctor.models.experiment import ExperimentResult, ExperimentSpec, ReconcileResult
from project_doctor.models.finding import ReportData, ReportResult
from project_doctor.models.observation import ExperimentLevel, Observation
from project_doctor.models.scenario import RequestStep, Scenario
from project_doctor.models.task import CallContext, OperationResult
from project_doctor.workflows.execute_experiment import (
    assemble_result,
    experiment_input_digest,
    needed_requests,
    normalized_result_digest,
)
from project_doctor.workflows.reconcile import reconcile
from project_doctor.workflows.task_ports import TaskStore

SqlProbe = Callable[
    [RequestStep, HttpResponse, CallContext, str, ExperimentLevel], Awaitable[SqlCollection]
]
Work = Callable[[], Awaitable[tuple[OperationResult, Usage]]]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class RuntimeService:
    """The real Runtime: Docker environments, restricted HTTP, measurements and recovery."""

    def __init__(
        self,
        settings: Settings,
        store: TaskStore,
        engine: Engine,
        gateway: EnvironmentGateway,
        *,
        service_port: int = 18080,
        probe: SqlProbe | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._engine = engine
        self._gateway = gateway
        self._http = RestrictedHttpClient(
            base_url=f"http://127.0.0.1:{service_port}",
            allowed_network=settings.allowed_target_network,
            timeout=15.0,
        )
        self._probe = probe

    # -- Runtime protocol ----------------------------------------------------

    async def prepare(self, project: ProjectInput, context: CallContext) -> EnvironmentHandle:
        start = time.monotonic()
        digest = _sha256(project.model_dump_json())

        async def work() -> tuple[OperationResult, Usage]:
            prepared = await self._gateway.prepare(project, context)
            relative = f"tasks/{context.task_id}/environment/{prepared.environment_id}/baseline.sql"
            await publish_artifact(
                self._settings.artifact_root,
                relative,
                prepared.baseline_dump,
                "application/sql",
                "mysqldump.v1",
            )
            handle = EnvironmentHandle(
                id=prepared.environment_id,
                isolated_base_url=prepared.isolated_base_url,
                fingerprint=prepared.fingerprint,
                baseline_snapshot_id=prepared.baseline_snapshot_id,
                health="available",
            )
            result = OperationResult(
                operation_id=context.operation_id,
                state="completed",
                input_digest=digest,
                payload=handle,
            )
            usage = Usage(
                wall_seconds=time.monotonic() - start,
                artifact_bytes=len(prepared.baseline_dump),
            )
            return result, usage

        operation = await self._settle(
            task_id=context.task_id,
            operation_id=context.operation_id,
            input_digest=digest,
            request_allowance=0,
            work=work,
        )
        payload = operation.payload
        if not isinstance(payload, EnvironmentHandle):
            raise RuntimeError("prepare operation did not persist an environment handle")
        return payload

    async def run(
        self,
        environment_id: str,
        scenario: Scenario,
        spec: ExperimentSpec,
        context: CallContext,
    ) -> ExperimentResult:
        task = await self._store.get(context.task_id)
        failures = validate_experiment(spec, scenario, task)
        if failures:
            return self._reject(spec, context, failures[0])

        state = await asyncio.to_thread(load_environment_state, self._engine, context.task_id)
        if state is None or state.environment_id != environment_id or state.health != "available":
            return self._reject(
                spec,
                context,
                Failure(
                    code="environment_blocked",
                    message="environment is not prepared",
                    retry_policy="reconcile_first",
                ),
            )
        if (
            state.fingerprint != spec.baseline_fingerprint
            or state.baseline_snapshot_id != spec.snapshot_id
        ):
            return self._reject(
                spec,
                context,
                Failure(
                    code="scenario_invalid",
                    message="spec baseline does not match the prepared environment",
                    retry_policy="never",
                ),
            )

        needed = needed_requests(spec)
        if task.usage.requests + needed > task.limits.max_requests:
            return self._reject(
                spec,
                context,
                Failure(
                    code="budget_exhausted",
                    message="request budget is exhausted",
                    retry_policy="never",
                ),
            )

        try:
            recipe = parse_index_recipe(
                await asyncio.to_thread(self._resolve_recipe, spec.intervention_recipe_ref)
            )
        except ValueError as exc:
            return self._reject(
                spec,
                context,
                Failure(code="scenario_invalid", message=str(exc), retry_policy="never"),
            )

        async def work() -> tuple[OperationResult, Usage]:
            return await self._run_work(
                environment_id, scenario, spec, context, recipe, commit=task.project.commit
            )

        operation = await self._settle(
            task_id=context.task_id,
            operation_id=context.operation_id,
            input_digest=experiment_input_digest(spec),
            request_allowance=needed,
            work=work,
        )
        payload = operation.payload
        if not isinstance(payload, ExperimentResult):
            raise RuntimeError("run operation did not persist an experiment result")
        return payload

    async def reconcile(self, task_id: str) -> ReconcileResult:
        return await reconcile(
            task_id=task_id, store=self._store, engine=self._engine, gateway=self._gateway
        )

    async def close(self, environment_id: str, context: CallContext) -> RestoreResult:
        task_id = context.task_id

        async def work() -> tuple[OperationResult, Usage]:
            start = time.monotonic()
            state = await asyncio.to_thread(load_environment_state, self._engine, task_id)
            baseline_path = await asyncio.to_thread(
                resolve_contained,
                self._settings.artifact_root,
                f"tasks/{task_id}/environment/{environment_id}/baseline.sql",
            )
            baseline_dump = await asyncio.to_thread(baseline_path.read_bytes)
            snapshot_id = _digest_bytes(baseline_dump)
            try:
                restored = await self._gateway.restore(
                    environment_id, snapshot_id, context, baseline_dump
                )
            finally:
                await self._gateway.teardown(environment_id, context)
            evidence_refs = []
            if restored.verified and restored.restored_dump is not None:
                evidence_refs.append(
                    await publish_artifact(
                        self._settings.artifact_root,
                        f"tasks/{task_id}/environment/{environment_id}/restore.sql",
                        restored.restored_dump,
                        "application/sql",
                        "mysqldump.v1",
                    )
                )
            restore_result = RestoreResult(
                verified=restored.verified,
                fingerprint=state.fingerprint if restored.verified and state else None,
                snapshot_id=snapshot_id if restored.verified else None,
                evidence_refs=evidence_refs,
                reason=restored.reason,
            )
            result = OperationResult(
                operation_id=context.operation_id,
                state="completed" if restored.verified else "needs_reconcile",
                input_digest=_sha256(f"{environment_id}:close"),
                payload=restore_result,
            )
            return result, Usage(
                wall_seconds=time.monotonic() - start,
                artifact_bytes=sum(ref.size_bytes for ref in evidence_refs),
            )

        operation = await self._settle(
            task_id=task_id,
            operation_id=context.operation_id,
            input_digest=_sha256(f"{environment_id}:close"),
            request_allowance=0,
            work=work,
        )
        payload = operation.payload
        if not isinstance(payload, RestoreResult):
            raise RuntimeError("close operation did not persist a restore result")
        return payload

    async def publish_report(self, data: ReportData, context: CallContext) -> ReportResult:
        task_id = context.task_id

        async def work() -> tuple[OperationResult, Usage]:
            start = time.monotonic()
            json_bytes = data.json_content.encode("utf-8")
            html_bytes = data.html_content.encode("utf-8")
            json_ref = await publish_artifact(
                self._settings.artifact_root,
                f"tasks/{task_id}/report.json",
                json_bytes,
                "application/json",
                "report.v1",
            )
            html_ref = await publish_artifact(
                self._settings.artifact_root,
                f"tasks/{task_id}/report.html",
                html_bytes,
                "text/html",
                "report.v1",
            )
            report = ReportResult(
                task_id=task_id,
                task_status=data.task.status,
                json_ref=json_ref,
                html_ref=html_ref,
            )
            result = OperationResult(
                operation_id=context.operation_id,
                state="completed",
                input_digest=_sha256(data.json_content),
                payload=report,
            )
            return result, Usage(
                wall_seconds=time.monotonic() - start,
                artifact_bytes=len(json_bytes) + len(html_bytes),
            )

        operation = await self._settle(
            task_id=task_id,
            operation_id=context.operation_id,
            input_digest=_sha256(data.json_content),
            request_allowance=0,
            work=work,
        )
        payload = operation.payload
        if not isinstance(payload, ReportResult):
            raise RuntimeError("report operation did not persist a report result")
        return payload

    # -- helpers -------------------------------------------------------------

    async def _settle(
        self,
        *,
        task_id: str,
        operation_id: str,
        input_digest: str,
        request_allowance: int,
        work: Work,
    ) -> OperationResult:
        reservation = await self._store.reserve(
            task_id, operation_id, input_digest, request_allowance
        )
        if reservation.replay_result is not None:
            return reservation.replay_result
        if not reservation.accepted:
            raise ValueError(reservation.reason or "operation conflict")
        await asyncio.to_thread(mark_operation_running, self._engine, task_id, operation_id)
        result, consumed = await work()
        await self._store.finish_operation(task_id, operation_id, result, consumed)
        return result

    @staticmethod
    def _reject(spec: ExperimentSpec, context: CallContext, failure: Failure) -> ExperimentResult:
        return assemble_result(
            spec=spec,
            operation_id=context.operation_id,
            observations=[],
            restore=None,
            failure=failure,
            evidence_refs=[],
        )

    async def _run_work(
        self,
        environment_id: str,
        scenario: Scenario,
        spec: ExperimentSpec,
        context: CallContext,
        recipe: IndexRecipe,
        commit: str,
    ) -> tuple[OperationResult, Usage]:
        start = time.monotonic()
        observations: list[Observation] = []
        requests_made = 0
        measurement_failure: Failure | None = None
        step = scenario.steps[0]
        try:
            for level in ("baseline", "candidate_index"):
                if level == "candidate_index":
                    await self._gateway.execute_sql(environment_id, context, recipe.create_sql)
                for repetition in range(1, spec.repetitions + 1):
                    observations.append(
                        await self._measure(
                            step=step,
                            spec=spec,
                            level=level,
                            repetition=repetition,
                            context=context,
                            commit=commit,
                            environment_id=environment_id,
                        )
                    )
                    requests_made += 1
        except Exception as exc:
            # A timeout or failed request must not skip restoration; partial
            # observations collected before the failure are preserved.
            measurement_failure = Failure(
                code="tool_failure",
                message=str(exc).strip() or "measurement failed",
                retry_policy="reconcile_first",
            )

        restore, restore_failure, evidence_refs = await self._restore_after_run(
            environment_id, spec, context
        )
        failure = measurement_failure or restore_failure
        result = assemble_result(
            spec=spec,
            operation_id=context.operation_id,
            observations=observations,
            restore=restore,
            failure=failure,
            evidence_refs=evidence_refs,
        )
        operation = OperationResult(
            operation_id=context.operation_id,
            state="completed" if result.phase == "finished" else "needs_reconcile",
            input_digest=experiment_input_digest(spec),
            payload=result,
            failure=result.failure if result.phase != "finished" else None,
        )
        usage = Usage(
            wall_seconds=time.monotonic() - start,
            requests=requests_made,
            experiments=1,
            artifact_bytes=sum(
                ref.size_bytes
                for ref in {
                    ref.artifact_id: ref
                    for ref in (
                        evidence_refs + [ref for obs in observations for ref in obs.evidence_refs]
                    )
                }.values()
            ),
        )
        return operation, usage

    async def _measure(
        self,
        *,
        step: RequestStep,
        spec: ExperimentSpec,
        level: ExperimentLevel,
        repetition: int,
        context: CallContext,
        commit: str,
        environment_id: str,
    ) -> Observation:
        fingerprint_before = await self._gateway.fingerprint(environment_id, context, commit)
        if level == "baseline" and fingerprint_before != spec.baseline_fingerprint:
            raise ValueError("live baseline fingerprint does not match experiment")
        response = await self._http.request(step)
        fingerprint_after = await self._gateway.fingerprint(environment_id, context, commit)
        if fingerprint_before != fingerprint_after:
            raise ValueError("environment changed during observation")
        valid, _ = check_assertions(step.assertions, response)
        digest = normalized_result_digest(response.body) if valid else None
        collection = (
            await self._probe(step, response, context, commit, level)
            if self._probe
            else SqlCollection(calls=[], evidence_refs=[])
        )
        return Observation(
            id=f"{spec.id}-{level}-{repetition}",
            experiment_id=spec.id,
            level=level,
            repetition=repetition,
            request_id=response.request_id or f"{context.operation_id}-{level}-{repetition}",
            business_valid=valid,
            latency_ms=response.latency_ms,
            result_digest=digest,
            sql_calls=collection.calls,
            fingerprint=fingerprint_before,
            snapshot_id=spec.snapshot_id,
            observation_config_id=spec.observation_config_id,
            evidence_refs=collection.evidence_refs,
        )

    async def _restore_after_run(
        self, environment_id: str, spec: ExperimentSpec, context: CallContext
    ) -> tuple[RestoreResult | None, Failure | None, list[EvidenceRef]]:
        baseline_path = await asyncio.to_thread(
            resolve_contained,
            self._settings.artifact_root,
            f"tasks/{context.task_id}/environment/{environment_id}/baseline.sql",
        )
        baseline_dump = await asyncio.to_thread(baseline_path.read_bytes)
        restored = await self._gateway.restore(
            environment_id, spec.snapshot_id, context, baseline_dump
        )
        evidence_refs: list[EvidenceRef] = []
        if restored.verified and restored.restored_dump is not None:
            evidence_refs.append(
                await publish_artifact(
                    self._settings.artifact_root,
                    f"tasks/{context.task_id}/experiments/{spec.id}/restore.sql",
                    restored.restored_dump,
                    "application/sql",
                    "mysqldump.v1",
                )
            )
        if restored.verified:
            return (
                RestoreResult(
                    verified=True,
                    fingerprint=spec.baseline_fingerprint,
                    snapshot_id=spec.snapshot_id,
                    evidence_refs=evidence_refs,
                ),
                None,
                evidence_refs,
            )
        return (
            RestoreResult(verified=False, reason=restored.reason or "restoration failed"),
            Failure(
                code="environment_contaminated",
                message=restored.reason or "restoration failed",
                retry_policy="reconcile_first",
            ),
            evidence_refs,
        )

    def _resolve_recipe(self, recipe_ref: str) -> str:
        text = recipe_ref.strip()
        if not text.startswith("recipe:"):
            raise ValueError("intervention must reference a controlled recipe")
        name = text.removeprefix("recipe:")
        candidate = resolve_contained(self._settings.target_repo_root / "recipes", f"{name}.sql")
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
        raise ValueError(f"unknown intervention recipe reference {recipe_ref}")


def build_runtime(settings: Settings, store: TaskStore) -> Runtime:
    """Assemble the real Runtime from settings, sharing A-internal MySQL state access."""
    engine = create_engine(resolve_secret_ref(settings.platform_dsn_ref), pool_pre_ping=True)
    gateway = DockerEnvironmentGateway(
        settings,
        db_service="db",
        db_name="app",
        db_user="app",
        db_password="app",
        db_image="mysql:8.4",
        service_image="project-doctor-target:latest",
        service_port=18080,
    )

    async def fetch_rows(context: CallContext, sql: str) -> list[dict[str, Any]]:
        environment_id = compose_project_name(context.task_id)
        raw = await gateway.query_sql(environment_id, context, sql)
        return parse_mysql_batch(raw, PERF_SCHEMA_COLUMNS)

    async def explain(context: CallContext, sql: str) -> str:
        environment_id = compose_project_name(context.task_id)
        return await gateway.query_sql(environment_id, context, f"EXPLAIN FORMAT=JSON {sql}")

    async def publish(
        relative_path: str, content: bytes, media_type: str, format_version: str
    ) -> EvidenceRef:
        return await publish_artifact(
            settings.artifact_root, relative_path, content, media_type, format_version
        )

    probe = PerfSchemaSqlProbe(fetch_rows=fetch_rows, explain=explain, publish=publish)
    return RuntimeService(settings, store, engine, gateway, service_port=18080, probe=probe)
