"""Docker-gated proof that diagnosis retests an isolated Java/MyBatis rewrite."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.diagnosis.retest import evaluate_retest
from project_doctor.features.scenarios.discover import discover
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.integrations.artifacts.verify import FileEvidenceReader
from project_doctor.integrations.diagnosis.retest import DockerDiagnosisRetester
from project_doctor.integrations.docker.gateway import DockerEnvironmentGateway
from project_doctor.integrations.http.requests import RestrictedHttpClient
from project_doctor.integrations.observation.sql_probe import (
    PERF_SCHEMA_COLUMNS,
    normalize_sql,
    parse_mysql_batch,
    recent_tagged_statements_sql,
)
from project_doctor.integrations.repair.build import build_image
from project_doctor.integrations.repair.source import apply_patch, copy_baseline_source
from project_doctor.models.repair import RepairRecord
from tests.integration.runtime.test_target_probe import load_manifest
from tests.repair.test_demo_patch import ROOT, _batch_diff, _target
from tests.repair.test_diagnosis_retest import _ref
from tests.repair.test_gates import _handoff


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI unavailable")
def test_real_java_mybatis_retest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode:
        pytest.skip("Docker daemon unavailable")
    # The observation primitive only needs a SQLAlchemy Engine constructor;
    # the retest itself uses the target's isolated MySQL, not the platform DB.
    monkeypatch.setenv("REPAIR_TEST_DSN", "sqlite://")
    settings = Settings(
        platform_dsn_ref="env:REPAIR_TEST_DSN",
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        target_repo_root=ROOT,
        allowed_target_network="127.0.0.0/8",
        tool_timeouts={"prepare_environment": 600.0, "run_experiment": 600.0},
        model_config_ref="file:model.json",
    )
    target = _target()
    source = apply_patch(target, _batch_diff(), settings.workspace_root / "fix-live")
    baseline_source = copy_baseline_source(target, settings.workspace_root / "fix-live")
    baseline_image = build_image(baseline_source, tag_prefix="project-doctor-baseline")
    patched_image = build_image(source)
    bundle, finding = _handoff()
    bundle.task.project.commit = target.source_commit
    bundle.task.project.repo_path = str(ROOT)
    for location in finding.code_locations:
        location.commit = target.source_commit
    assert finding.fix_spec is not None
    finding.fix_spec.child_code_location.commit = target.source_commit
    scenario = discover(bundle.task.project, load_manifest())[0]
    scenario.id = finding.scenario_id
    bundle.scenarios = [scenario]
    bundle.task.scenario_ids = [scenario.id]
    context = bundle.task.correlation
    original_gateway = DockerEnvironmentGateway(
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
        prepared = await original_gateway.prepare(bundle.task.project, context)
        try:
            bundle.task.environment_id = prepared.environment_id
            spec = bundle.experiments[0].spec
            assert spec is not None
            spec.snapshot_id = prepared.baseline_snapshot_id
            scenario.dataset.snapshot_id = prepared.baseline_snapshot_id
            await publish_artifact(
                settings.artifact_root,
                f"tasks/{bundle.task.id}/environment/{prepared.environment_id}/baseline.sql",
                prepared.baseline_dump,
                "application/sql",
                "mysqldump.v1",
            )
            client = RestrictedHttpClient(
                prepared.isolated_base_url, settings.allowed_target_network, 15.0
            )
            response = await client.request(scenario.steps[0])
            raw = await original_gateway.query_sql(
                prepared.environment_id,
                context,
                recent_tagged_statements_sql(64, response.request_id),
            )
            rows = parse_mysql_batch(raw, PERF_SCHEMA_COLUMNS)
            parents = [
                normalize_sql(str(row["SQL_TEXT"]))
                for row in rows
                if "FROM orders o" in str(row["SQL_TEXT"]) and "SELECT o.*" in str(row["SQL_TEXT"])
            ]
            assert len(parents) == 1
            for observation in bundle.experiments[0].observations:
                for call in observation.sql_calls:
                    if call.id in finding.fix_spec.parent_sql_call_ids:
                        call.normalized_sql = parents[0]
        finally:
            await original_gateway.teardown(prepared.environment_id, context)
        repair = RepairRecord.model_validate(
            {
                "id": "repair-live",
                "task_id": bundle.task.id,
                "finding_id": finding.id,
                "operation_id": "repair-live-op",
                "attempt_id": "repair-live-attempt",
                "status": "retesting",
                "source_commit": target.source_commit,
                "patch_sha256": source.patch_sha256,
                "parent_key_column": target.parent_key_column,
                "source_sha256": source.source_sha256,
                "baseline_source_sha256": baseline_source.source_sha256,
                "workspace_name": source.root.relative_to(settings.workspace_root).as_posix(),
                "baseline_image_digest": baseline_image.digest,
                "patched_image_digest": patched_image.digest,
                "patch_ref": _ref(),
                "build_ref": _ref(),
            }
        )
        evidence = await DockerDiagnosisRetester(
            settings, object(), FileEvidenceReader(settings.artifact_root)
        ).run(bundle, finding, repair)
        assert evidence.baseline.samples[0].child_count >= 20
        assert all(sample.child_count == 0 for sample in evidence.patched.samples)
        assert all(sample.batch_parameters for sample in evidence.patched.samples)
        assert (
            evidence.baseline.samples[0].result_digest == evidence.patched.samples[0].result_digest
        )
        try:
            comparison = evaluate_retest(finding, evidence.baseline, evidence.patched)
        except ValueError as exc:
            # Query collapse alone is not proof of a latency gain.
            assert "gain" in str(exc)
        else:
            assert comparison.measured_gain_percent > 0

    asyncio.run(run())
