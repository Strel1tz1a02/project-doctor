"""Persisted N+1 handoff through a real patch, build, diagnosis retest and backfill."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.environments.prepare import environment_fingerprint
from project_doctor.features.scenarios.discover import discover
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.integrations.artifacts.verify import FileEvidenceReader
from project_doctor.integrations.diagnosis.retest import DockerDiagnosisRetester
from project_doctor.integrations.docker.gateway import DockerEnvironmentGateway
from project_doctor.integrations.http.requests import RestrictedHttpClient
from project_doctor.integrations.mysql.factory import build_store
from project_doctor.integrations.observation.sql_probe import (
    PERF_SCHEMA_COLUMNS,
    normalize_sql,
    parse_mysql_batch,
    recent_tagged_statements_sql,
)
from project_doctor.integrations.repair.build import build_image
from project_doctor.integrations.repair.source import copy_baseline_source
from project_doctor.models.common import Usage
from project_doctor.models.task import OperationResult
from project_doctor.workflows.diagnose_retest import DiagnosisRetestService
from project_doctor.workflows.repair import RepairWorkflow
from tests.integration.runtime.test_target_probe import load_manifest
from tests.repair.test_demo_patch import MAPPER, ROOT, SERVICE, _batch_diff, _target
from tests.repair.test_gates import _handoff


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI unavailable")
def test_persisted_repair_chain_uses_diagnosis_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not os.environ.get("PROJECT_DOCTOR_PLATFORM_DSN"):
        pytest.skip("PROJECT_DOCTOR_PLATFORM_DSN not set; real repair chain unverified")
    if subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode:
        pytest.skip("Docker daemon unavailable")
    docker_dir = shutil.which("docker")
    assert docker_dir is not None
    monkeypatch.setenv("PATH", str(Path(docker_dir).parent) + os.pathsep + os.environ["PATH"])
    settings = Settings(
        platform_dsn_ref="env:PROJECT_DOCTOR_PLATFORM_DSN",
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        target_repo_root=ROOT,
        allowed_target_network="127.0.0.0/8",
        tool_timeouts={
            "prepare_environment": 600,
            "run_experiment": 600,
            "submit_fix_patch": 600,
            "verify_fix": 600,
        },
        model_config_ref="file:model.json",
    )
    target = _target()
    source_before = {path: (ROOT / path).read_bytes() for path in (MAPPER, SERVICE)}
    baseline_source = copy_baseline_source(target, settings.workspace_root / "fixture-origin")
    baseline_image = build_image(baseline_source, tag_prefix="project-doctor-baseline")
    bundle, finding = _handoff()
    task_id = "repair-chain-" + uuid.uuid4().hex
    bundle.task = bundle.task.model_copy(
        update={
            "id": task_id,
            "correlation": bundle.task.correlation.model_copy(update={"task_id": task_id}),
        }
    )
    bundle.task.project.commit = target.source_commit
    bundle.task.project.repo_path = str(ROOT)
    bundle.task.status = "running"
    finding.task_id = task_id
    for location in finding.code_locations:
        location.commit = target.source_commit
        location.path = MAPPER
        location.line = 40
    assert finding.fix_spec is not None
    finding.fix_spec.child_code_location.commit = target.source_commit
    finding.fix_spec.child_code_location.path = MAPPER
    finding.fix_spec.child_code_location.line = 40
    experiment = bundle.experiments[0]
    assert experiment.spec is not None
    experiment.spec.task_id = task_id
    for observation in experiment.observations:
        for call in observation.sql_calls:
            if call.code_location is not None:
                call.code_location.commit = target.source_commit
    scenario = next(
        item
        for item in discover(bundle.task.project, load_manifest())
        if item.id == "n-plus-one-orders-search"
    )
    scenario.id = finding.scenario_id
    bundle.scenarios = [scenario]
    context = bundle.task.correlation
    gateway = DockerEnvironmentGateway(
        settings,
        db_service="db",
        db_name="app",
        db_user="app",
        db_password="app",
        db_image="mysql:8.4",
        service_image=baseline_image.digest,
        service_port=18080,
        source_root=baseline_source.root,
    )

    async def run() -> None:
        prepared = await gateway.prepare(bundle.task.project, context)
        try:
            bundle.task.environment_id = prepared.environment_id
            experiment.spec.snapshot_id = prepared.baseline_snapshot_id
            experiment.spec.baseline_fingerprint = environment_fingerprint(
                commit=target.source_commit, snapshot_id=prepared.baseline_snapshot_id
            )
            scenario.dataset.snapshot_id = prepared.baseline_snapshot_id
            snapshot_ref = await publish_artifact(
                settings.artifact_root,
                f"tasks/{task_id}/environment/{prepared.environment_id}/baseline.sql",
                prepared.baseline_dump,
                "application/sql",
                "mysqldump.v1",
            )
            assert (
                hashlib.sha256(prepared.baseline_dump).hexdigest() == prepared.baseline_snapshot_id
            )
            finding.evidence_refs = [snapshot_ref]
            experiment.evidence_refs = [snapshot_ref]
            for location in [*finding.code_locations, finding.fix_spec.child_code_location]:
                location.association_evidence_ids = [snapshot_ref.artifact_id]
            client = RestrictedHttpClient(
                prepared.isolated_base_url, settings.allowed_target_network, 15.0
            )
            response = await client.request(scenario.steps[0])
            raw = await gateway.query_sql(
                prepared.environment_id,
                context,
                recent_tagged_statements_sql(64, response.request_id),
            )
            parent_queries = [
                normalize_sql(str(row["SQL_TEXT"]))
                for row in parse_mysql_batch(raw, PERF_SCHEMA_COLUMNS)
                if "FROM orders o" in str(row["SQL_TEXT"]) and "SELECT o.*" in str(row["SQL_TEXT"])
            ]
            assert len(parent_queries) == 1
            for observation in experiment.observations:
                for call in observation.sql_calls:
                    if call.id in finding.fix_spec.parent_sql_call_ids:
                        call.normalized_sql = parent_queries[0]
        finally:
            await gateway.teardown(prepared.environment_id, context)

        store = build_store(settings)
        await store.create(bundle.task)
        await store.save_scenario(task_id, scenario)
        await store.save_hypotheses(task_id, bundle.hypotheses)
        operation_id = experiment.operation_id
        digest = "a" * 64
        assert (await store.reserve(task_id, operation_id, digest, 0)).accepted
        await store.finish_operation(
            task_id,
            operation_id,
            OperationResult(
                operation_id=operation_id,
                state="completed",
                input_digest=digest,
                payload=experiment,
            ),
            Usage(),
        )
        await store.save_findings(task_id, [finding])
        assert (await store.load_bundle(task_id)).findings == [finding]
        reader = FileEvidenceReader(settings.artifact_root)
        diagnosis = DiagnosisRetestService(DockerDiagnosisRetester(settings, store, reader), reader)
        repair_workflow = RepairWorkflow(settings, store, reader, diagnosis)
        fix_context = context.model_copy(update={"operation_id": "fix-" + uuid.uuid4().hex})
        view = await repair_workflow.inspect_fix_target(fix_context, finding.id)
        assert view.mapper_path == MAPPER and view.caller_path == SERVICE
        built = await repair_workflow.submit_fix_patch(fix_context, finding.id, _batch_diff())
        assert built.status == "built"
        assert (
            await repair_workflow.submit_fix_patch(fix_context, finding.id, _batch_diff()) == built
        )
        assert built.patch_ref is not None and built.build_ref is not None
        verify_context = context.model_copy(update={"operation_id": "verify-" + uuid.uuid4().hex})
        try:
            result = await repair_workflow.verify_fix(verify_context, built.id)
        except ValueError as exc:
            # A real SQL-count collapse still needs a distinguishable latency gain.
            assert "gain" in str(exc)
            result = await repair_workflow.get_fix_status(verify_context, built.id)
            assert result.status == "failed"
            assert result.failure_reason is not None and "gain" in result.failure_reason
            assert result.baseline_run is not None and result.patched_run is not None
            assert result.baseline_run.samples[0].child_count >= 20
            assert all(sample.child_count == 0 for sample in result.patched_run.samples)
            assert result.retest_refs and (await reader.verify(result.retest_refs)).valid
            assert (await store.load_bundle(task_id)).findings == [finding]
        else:
            assert result.status == "retested"
            assert result.baseline_run is not None and result.patched_run is not None
            assert result.baseline_run.samples[0].child_count >= 20
            assert all(sample.child_count == 0 for sample in result.patched_run.samples)
            updated = (await store.load_bundle(task_id)).findings[0]
            assert updated.recommendation is not None
            assert updated.recommendation.validation_status == "retested"
            before, after = finding.model_dump(), updated.model_dump()
            for key in ("validation_status", "measured_gain_percent", "retest_experiment_ids"):
                before["recommendation"].pop(key)
                after["recommendation"].pop(key)
            assert before == after
        restarted = build_store(settings)
        assert await restarted.load_repair(task_id, built.id) == result
        assert {path: (ROOT / path).read_bytes() for path in (MAPPER, SERVICE)} == source_before

    asyncio.run(run())
