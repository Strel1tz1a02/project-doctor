"""A successful repair and its Recommendation backfill are one transaction."""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert

from project_doctor.features.repair.gates import apply_retest_fields
from project_doctor.integrations.mysql.migrations.schema import (
    create_schema,
    findings,
    tasks,
)
from project_doctor.integrations.mysql.task_store import MySQLTaskStore
from project_doctor.models.common import EvidenceRef
from project_doctor.models.repair import RepairComparison, RepairRecord
from project_doctor.workflows.diagnose import evaluate
from tests.diagnosis.test_n_plus_one import Reader, n_plus_one_bundle
from tests.repair.test_gates import _run


def _record(bundle, finding) -> RepairRecord:
    return RepairRecord(
        id="repair-1",
        task_id=bundle.task.id,
        finding_id=finding.id,
        operation_id="repair-op-1",
        attempt_id="attempt-1",
        status="preparing",
        source_commit=bundle.task.project.commit,
        patch_sha256="a" * 64,
    )


def _ref(name: str) -> EvidenceRef:
    return EvidenceRef(
        artifact_id=name,
        relative_path=f"repairs/{name}.json",
        media_type="application/json",
        format_version="repair.v1",
        sha256="b" * 64,
        size_bytes=10,
    )


def test_repair_state_and_recommendation_are_persisted_atomically(tmp_path: Path) -> None:
    bundle = n_plus_one_bundle()
    finding = asyncio.run(evaluate(bundle, Reader()))[0]
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'repair.db').as_posix()}")
    create_schema(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(tasks).values(
                id=bundle.task.id,
                status=bundle.task.status,
                record_json=bundle.task.model_dump(mode="json", exclude={"status"}),
            )
        )
        conn.execute(
            insert(findings).values(
                task_id=bundle.task.id,
                finding_id=finding.id,
                record_json=finding.model_dump(mode="json"),
            )
        )
    store = MySQLTaskStore(engine)
    preparing = _record(bundle, finding)
    assert asyncio.run(store.create_repair(preparing)) == preparing
    assert asyncio.run(store.create_repair(preparing)) == preparing
    built = preparing.model_copy(
        update={
            "status": "built",
            "source_sha256": "c" * 64,
            "baseline_source_sha256": "f" * 64,
            "workspace_name": "repair-aaaaaaaaaaaaaaaaaaaa",
            "baseline_image_digest": "sha256:" + "a" * 64,
            "patched_image_digest": "sha256:" + "b" * 64,
            "patch_ref": _ref("patch"),
            "build_ref": _ref("build"),
        }
    )
    assert asyncio.run(store.update_repair(built, "preparing"))
    retesting = built.model_copy(update={"status": "retesting"})
    assert asyncio.run(store.update_repair(retesting, "built"))
    comparison = RepairComparison(
        source_task_id=bundle.task.id,
        finding_id=finding.id,
        baseline_task_id="baseline-task",
        patched_task_id="patched-task",
        retest_experiment_ids=["baseline-exp", "patched-exp"],
        measured_gain_percent=85.0,
        baseline_median_ms=100.0,
        patched_median_ms=15.0,
        evidence_ids=["baseline-evidence", "patched-evidence"],
    )
    finished = retesting.model_copy(
        update={
            "status": "retested",
            "comparison": comparison,
            "baseline_run": _run(),
            "patched_run": _run(patched=True),
            "retest_refs": [_ref("baseline-evidence"), _ref("patched-evidence")],
        }
    )
    updated = apply_retest_fields(finding, comparison)
    wrong = updated.model_copy(update={"status": "unclassified"})
    with pytest.raises(ValueError, match="diagnostic evidence"):
        asyncio.run(store.complete_repair(finished, wrong, "retesting"))
    assert asyncio.run(store.load_repair(bundle.task.id, preparing.id)) == retesting
    assert asyncio.run(store.complete_repair(finished, updated, "retesting"))
    assert asyncio.run(store.complete_repair(finished, updated, "retesting"))
    saved = asyncio.run(store.load_bundle(bundle.task.id))
    assert saved.findings == [updated]
    assert saved.repairs == [finished]
