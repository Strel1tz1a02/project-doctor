"""Independent baseline-only measurements of old and repaired Java/MyBatis images."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.diagnosis.ports import EvidenceReader
from project_doctor.features.diagnosis.sql_shape import extract_sql_literals, parameterize_sql
from project_doctor.features.environments.prepare import (
    compose_project_name,
    environment_fingerprint,
)
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.integrations.artifacts.verify import resolve_contained
from project_doctor.integrations.docker.gateway import DockerEnvironmentGateway
from project_doctor.integrations.http.requests import RestrictedHttpClient, check_assertions
from project_doctor.integrations.mysql.factory import resolve_secret_ref
from project_doctor.integrations.observation.lock_probe import LockProbe
from project_doctor.integrations.observation.sql_probe import (
    PERF_SCHEMA_COLUMNS,
    PerfSchemaSqlProbe,
    parse_mysql_batch,
)
from project_doctor.integrations.repair.build import inspect_image_digest
from project_doctor.integrations.repair.source import source_tree_sha256
from project_doctor.integrations.runtime_factory import RuntimeService
from project_doctor.models.common import EvidenceRef
from project_doctor.models.finding import Finding
from project_doctor.models.n_plus_one import BatchQuerySpec
from project_doctor.models.repair import RepairRecord, RepairRun, RepairSample
from project_doctor.models.task import CallContext, TaskBundle
from project_doctor.workflows.diagnose_retest import RetestEvidence
from project_doctor.workflows.task_ports import TaskStore

_SELECT = re.compile(r"\ASELECT\s", re.IGNORECASE)
_IDENTIFIER = re.compile(r"\A[A-Za-z_][A-Za-z_0-9]*\Z")


def _diagnostic_spec(bundle: TaskBundle, finding: Finding) -> tuple[Any, str]:
    fix_spec = finding.fix_spec
    if not isinstance(fix_spec, BatchQuerySpec):
        raise ValueError("retest requires an N+1 BatchQuerySpec")
    experiments = [
        item for item in bundle.experiments if item.experiment_id in finding.experiment_ids
    ]
    if len(experiments) != 1 or experiments[0].spec is None:
        raise ValueError("retest requires one persisted source experiment")
    spec = experiments[0].spec
    parent_templates = {
        parameterize_sql(call.normalized_sql)
        for observation in experiments[0].observations
        for call in observation.sql_calls
        if call.id in fix_spec.parent_sql_call_ids
    }
    if len(parent_templates) != 1:
        raise ValueError("diagnostic parent query shape is ambiguous")
    return spec, parent_templates.pop()


def _safe_parent_query(sql: str, column: str) -> str:
    if not _IDENTIFIER.fullmatch(column):
        raise ValueError("parent key column is not a simple SQL identifier")
    statement = sql.strip()
    if not _SELECT.match(statement) or ";" in statement or "--" in statement or "/*" in statement:
        raise ValueError("parent SQL cannot be safely replayed")
    return f"SELECT DISTINCT `{column}` FROM ({statement}) AS pd_parent"


def _key_values(sql: str, column: str, *, batch: bool) -> list[str]:
    key = re.escape(column)
    if batch:
        match = re.search(rf"\b`?{key}`?\s+IN\s*\(([^()]*)\)", sql, re.IGNORECASE)
    else:
        match = re.search(rf"\b`?{key}`?\s*=\s*('[^']*'|-?\d+)", sql, re.IGNORECASE)
    if match is None:
        raise ValueError("child SQL has no recognizable key parameters")
    return extract_sql_literals(match.group(1))


class DockerDiagnosisRetester:
    """Conservative adapter for a single GET, serial-load Java/MyBatis scenario."""

    def __init__(self, settings: Settings, store: TaskStore, reader: EvidenceReader) -> None:
        self._settings = settings
        self._store = store
        self._reader = reader

    async def cleanup(self, repair: RepairRecord, context: CallContext) -> None:
        """Close both deterministic retest projects after an exited worker."""
        if context.task_id != repair.task_id:
            raise ValueError("repair cleanup task identity differs from the persisted task")
        gateway = DockerEnvironmentGateway(
            self._settings,
            db_service="db",
            db_name="app",
            db_user="app",
            db_password="app",
            db_image="mysql:8.4",
            service_image=repair.baseline_image_digest or "unused",
            service_port=18080,
        )
        failures: list[Exception] = []
        for side in ("baseline", "patched"):
            side_task_id = f"{repair.id}-{side}"
            side_context = context.model_copy(
                update={"task_id": side_task_id, "operation_id": f"{repair.id}-{side}-cleanup"}
            )
            try:
                await gateway.teardown(compose_project_name(side_task_id), side_context)
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise ValueError(f"{len(failures)} retest environment cleanup(s) failed") from failures[
                0
            ]

    async def run(
        self, bundle: TaskBundle, finding: Finding, repair: RepairRecord
    ) -> RetestEvidence:
        if not (
            repair.workspace_name
            and repair.source_sha256
            and repair.baseline_source_sha256
            and repair.parent_key_column
        ):
            raise ValueError("repair build does not identify a validated source and parent key")
        scenario = next((item for item in bundle.scenarios if item.id == finding.scenario_id), None)
        if scenario is None or len(scenario.steps) != 1 or scenario.steps[0].method != "GET":
            raise ValueError("Java/MyBatis retest requires one read-only GET step")
        if scenario.load.mode != "serial":
            raise ValueError("Java/MyBatis retest currently supports serial load only")
        spec, parent_template = _diagnostic_spec(bundle, finding)
        if (
            spec.snapshot_id != scenario.dataset.snapshot_id
            and scenario.dataset.snapshot_id != "snapshot-resolved-at-first-prepare"
        ):
            raise ValueError("scenario and diagnostic snapshot identities differ")
        if bundle.task.environment_id is None:
            raise ValueError("diagnostic task has no persisted environment")
        original_dump_path = resolve_contained(
            self._settings.artifact_root,
            f"tasks/{bundle.task.id}/environment/{bundle.task.environment_id}/baseline.sql",
        )
        original_dump = await asyncio.to_thread(original_dump_path.read_bytes)
        if hashlib.sha256(original_dump).hexdigest() != spec.snapshot_id:
            raise ValueError("persisted diagnostic snapshot content does not match its digest")
        source = (self._settings.workspace_root / repair.workspace_name).resolve(strict=True)
        if not source.is_relative_to(self._settings.workspace_root.resolve()):
            raise ValueError("repaired source escaped the isolated workspace")
        if source_tree_sha256(source) != repair.source_sha256:
            raise ValueError("repaired source changed after image build")
        baseline_source = (source.parent / "baseline-source").resolve(strict=True)
        if not baseline_source.is_relative_to(self._settings.workspace_root.resolve()):
            raise ValueError("baseline source escaped the isolated workspace")
        if source_tree_sha256(baseline_source) != repair.baseline_source_sha256:
            raise ValueError("baseline source changed after image build")
        patched_tag = "project-doctor-repair:" + repair.source_sha256[:20]
        if (
            await asyncio.to_thread(inspect_image_digest, patched_tag)
            != repair.patched_image_digest
        ):
            raise ValueError("repaired image tag no longer resolves to its built digest")
        baseline_tag = "project-doctor-baseline:" + repair.baseline_source_sha256[:20]
        if (
            await asyncio.to_thread(inspect_image_digest, baseline_tag)
            != repair.baseline_image_digest
        ):
            raise ValueError("baseline image tag changed after repair submission")
        baseline, first_refs, baseline_dump = await self._one_run(
            bundle,
            finding,
            repair,
            spec,
            scenario,
            parent_template,
            side="baseline",
            source_root=baseline_source,
            image_digest=repair.baseline_image_digest,
            expected_dump=original_dump,
        )
        patched, second_refs, _ = await self._one_run(
            bundle,
            finding,
            repair,
            spec,
            scenario,
            parent_template,
            side="patched",
            source_root=source,
            image_digest=repair.patched_image_digest,
            expected_dump=baseline_dump,
        )
        return RetestEvidence(baseline, patched, tuple(first_refs + second_refs))

    async def _one_run(
        self,
        bundle: TaskBundle,
        finding: Finding,
        repair: RepairRecord,
        original_spec: Any,
        scenario: Any,
        parent_template: str,
        *,
        side: str,
        source_root: Path,
        image_digest: str,
        expected_dump: bytes | None,
    ) -> tuple[RepairRun, list[EvidenceRef], bytes]:
        fix_spec = finding.fix_spec
        if not isinstance(fix_spec, BatchQuerySpec):
            raise ValueError("retest requires an N+1 BatchQuerySpec")
        assert repair.parent_key_column is not None
        task_id = f"{repair.id}-{side}"
        context = bundle.task.correlation.model_copy(
            update={"task_id": task_id, "operation_id": f"{repair.id}-{side}-measure"}
        )
        gateway = DockerEnvironmentGateway(
            self._settings,
            db_service="db",
            db_name="app",
            db_user="app",
            db_password="app",
            db_image="mysql:8.4",
            service_image=image_digest,
            service_port=18080,
            source_root=source_root,
        )
        refs: list[EvidenceRef] = []
        environment_id = ""

        async def publish(path: str, content: bytes, media_type: str, version: str) -> EvidenceRef:
            ref = await publish_artifact(
                self._settings.artifact_root, path, content, media_type, version
            )
            refs.append(ref)
            return ref

        async def fetch_rows(call_context: CallContext, sql: str) -> list[dict[str, Any]]:
            raw = await gateway.query_sql(environment_id, call_context, sql)
            return parse_mysql_batch(raw, PERF_SCHEMA_COLUMNS)

        async def explain(call_context: CallContext, sql: str) -> str:
            return await gateway.query_sql(
                environment_id, call_context, f"EXPLAIN FORMAT=JSON {sql}"
            )

        async def lock_query(call_context: CallContext, sql: str) -> str:
            return await gateway.query_sql(environment_id, call_context, sql)

        probe = PerfSchemaSqlProbe(fetch_rows=fetch_rows, explain=explain, publish=publish)
        locks = LockProbe(query=lock_query, publish=publish)
        engine = create_engine(resolve_secret_ref(self._settings.platform_dsn_ref))
        runtime = RuntimeService(
            self._settings,
            self._store,
            engine,
            gateway,
            service_port=18080,
            probe=probe,
            lock_probe=locks,
        )
        prepared = None
        teardown_error: BaseException | None = None
        try:
            prepared = await gateway.prepare(bundle.task.project, context)
            environment_id = prepared.environment_id
            baseline_dump = expected_dump or prepared.baseline_dump
            from project_doctor.integrations.docker.snapshots import SnapshotManager

            snapshot_id = SnapshotManager.digest(baseline_dump)
            if side == "baseline" and snapshot_id != original_spec.snapshot_id:
                raise ValueError("new baseline does not reproduce the diagnostic data snapshot")
            restored = await gateway.restore(
                prepared.environment_id, snapshot_id, context, baseline_dump
            )
            if not restored.verified:
                raise ValueError("cannot prepare an identical baseline snapshot")
            refs.append(
                await publish_artifact(
                    self._settings.artifact_root,
                    f"tasks/{task_id}/repairs/{repair.id}/baseline.sql",
                    baseline_dump,
                    "application/sql",
                    "mysqldump.v1",
                )
            )
            fingerprint = environment_fingerprint(
                commit=bundle.task.project.commit, snapshot_id=snapshot_id
            )
            run_spec = original_spec.model_copy(
                update={
                    "id": f"{repair.id}-{side}-experiment",
                    "task_id": task_id,
                    "baseline_fingerprint": fingerprint,
                    "snapshot_id": snapshot_id,
                }
            )
            step = scenario.steps[0]
            client = RestrictedHttpClient(
                prepared.isolated_base_url, self._settings.allowed_target_network, 15.0
            )
            warmup_count = original_spec.warmup.requests_per_level if original_spec.warmup else 5
            for ordinal in range(warmup_count):
                response = await client.request(step, request_id=uuid.uuid4().hex)
                valid, reasons = check_assertions(step.assertions, response)
                if not valid:
                    raise ValueError(f"{side} warmup {ordinal + 1} failed: {reasons}")
            if (
                await gateway.fingerprint(environment_id, context, bundle.task.project.commit)
                != fingerprint
            ):
                raise ValueError("diagnostic retest snapshot changed during warmup")
            samples: list[RepairSample] = []
            for repetition in range(1, original_spec.repetitions + 1):
                observation = await runtime.measure_request(
                    step=step,
                    spec=run_spec,
                    level="baseline",
                    repetition=repetition,
                    context=context,
                    commit=bundle.task.project.commit,
                    environment_id=prepared.environment_id,
                    prepared_fingerprint=fingerprint,
                    request_id=uuid.uuid4().hex,
                    retained_refs=refs,
                )
                refs.extend(observation.evidence_refs)
                if not observation.business_valid or observation.result_digest is None:
                    raise ValueError("repair retest changed business assertions")
                parents = [
                    call
                    for call in observation.sql_calls
                    if parameterize_sql(call.normalized_sql) == parent_template
                ]
                if len(parents) != 1 or parents[0].rows_examined is None:
                    raise ValueError("retest did not capture one measurable parent query")
                parent_query = _safe_parent_query(
                    parents[0].normalized_sql, repair.parent_key_column
                )
                parent_raw = await gateway.query_sql(prepared.environment_id, context, parent_query)
                parent_keys = [value.strip() for value in parent_raw.splitlines() if value.strip()]
                if not parent_keys or "\\N" in parent_keys:
                    raise ValueError("parent query returned no usable association keys")
                refs.append(
                    await publish_artifact(
                        self._settings.artifact_root,
                        f"tasks/{task_id}/repairs/{repair.id}/parent-{repetition}.json",
                        json.dumps(
                            {"query": parent_query, "keys": parent_keys}, sort_keys=True
                        ).encode(),
                        "application/json",
                        "repair.parent-keys.v1",
                    )
                )
                child_calls = [
                    call
                    for call in observation.sql_calls
                    if parameterize_sql(call.normalized_sql) == fix_spec.child_template
                ]
                batch_calls = [
                    call
                    for call in observation.sql_calls
                    if re.search(
                        rf"\b{re.escape(fix_spec.key_column)}\s+IN\s*\(",
                        call.normalized_sql,
                        re.IGNORECASE,
                    )
                    and re.search(
                        r"\bFROM\s+" + re.escape(_child_table(fix_spec.child_template)),
                        call.normalized_sql,
                        re.IGNORECASE,
                    )
                ]
                if side == "patched" and len(batch_calls) != 1:
                    raise ValueError("repaired request did not execute one child batch query")
                samples.append(
                    RepairSample(
                        request_id=observation.request_id,
                        business_valid=True,
                        result_digest=observation.result_digest,
                        latency_ms=observation.latency_ms,
                        sql_count=len(observation.sql_calls),
                        child_count=len(child_calls),
                        parent_rows_examined=parents[0].rows_examined,
                        parent_keys=parent_keys,
                        child_parameters=[
                            value
                            for call in child_calls
                            for value in _key_values(
                                call.normalized_sql, fix_spec.key_column, batch=False
                            )
                        ],
                        batch_parameters=[
                            value
                            for call in batch_calls
                            for value in _key_values(
                                call.normalized_sql, fix_spec.key_column, batch=True
                            )
                        ],
                        lock_covered=bool(observation.sql_calls)
                        and all(
                            call.lock_evidence is not None
                            and call.lock_evidence.coverage == "complete"
                            for call in observation.sql_calls
                        ),
                    )
                )
            if (
                await gateway.fingerprint(environment_id, context, bundle.task.project.commit)
                != fingerprint
            ):
                raise ValueError("diagnostic retest snapshot changed during measurement")
            final_restore = await gateway.restore(
                prepared.environment_id, snapshot_id, context, baseline_dump
            )
            if not final_restore.verified or final_restore.restored_dump is None:
                raise ValueError("repair retest did not restore the database")
            refs.append(
                await publish_artifact(
                    self._settings.artifact_root,
                    f"tasks/{task_id}/repairs/{repair.id}/restore.sql",
                    final_restore.restored_dump,
                    "application/sql",
                    "mysqldump.v1",
                )
            )
            check = await self._reader.verify(refs)
            if not check.valid:
                raise ValueError("diagnostic measurement artifacts could not be verified")
            run = RepairRun(
                task_id=task_id,
                experiment_id=run_spec.id,
                source_commit=bundle.task.project.commit,
                image_digest=image_digest,
                snapshot_id=snapshot_id,
                scenario_id=scenario.id,
                scenario_version=scenario.version,
                observation_config_id=run_spec.observation_config_id,
                cache_state=scenario.cache.state,
                samples=samples,
                restored=True,
                artifacts_verified=True,
                evidence_ids=list(dict.fromkeys(ref.artifact_id for ref in refs)),
            )
            summary = await publish_artifact(
                self._settings.artifact_root,
                f"tasks/{task_id}/repairs/{repair.id}/run.json",
                run.model_dump_json().encode("utf-8"),
                "application/json",
                "repair.run.v1",
            )
            refs.append(summary)
            check = await self._reader.verify(refs)
            if not check.valid:
                raise ValueError("repair run artifacts could not be verified")
            return run, refs, baseline_dump
        finally:
            try:
                if prepared is not None:
                    cleanup = asyncio.create_task(
                        gateway.teardown(prepared.environment_id, context)
                    )
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        # Drain the already-started teardown before reporting an
                        # unknown retest outcome to the durable workflow.
                        try:
                            await cleanup
                        except BaseException:
                            pass
                        raise
                    except BaseException as exc:
                        teardown_error = exc
            finally:
                engine.dispose()
            if teardown_error is not None:
                raise ValueError("repair retest Docker teardown failed") from teardown_error


def _child_table(sql: str) -> str:
    match = re.search(r"\bFROM\s+([A-Za-z_][A-Za-z_0-9]*)", sql, re.IGNORECASE)
    if match is None:
        raise ValueError("diagnosed child query has no simple table")
    return match.group(1)
