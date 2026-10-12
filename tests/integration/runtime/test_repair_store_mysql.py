"""Repair state and diagnosis backfill survive a real MySQL store restart."""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from pathlib import Path

import pytest

from project_doctor.features.repair.gates import apply_retest_fields
from project_doctor.integrations.mysql.factory import build_store
from project_doctor.models.repair import RepairComparison, RepairRecord
from project_doctor.workflows.repair import RepairWorkflow
from tests.diagnosis.test_n_plus_one import Reader
from tests.integration.runtime.test_store import make_settings
from tests.repair.test_gates import _handoff, _run
from tests.repair.test_store import _record, _ref


def test_repair_transaction_survives_mysql_store_restart(tmp_path: Path) -> None:
    if not os.environ.get("PROJECT_DOCTOR_PLATFORM_DSN"):
        pytest.skip("PROJECT_DOCTOR_PLATFORM_DSN not set; MySQL repair transaction unverified")
    settings = make_settings(tmp_path)
    store = build_store(settings)
    bundle, finding = _handoff()
    task_id = "repair-mysql-" + uuid.uuid4().hex
    bundle.task = bundle.task.model_copy(
        update={
            "id": task_id,
            "correlation": bundle.task.correlation.model_copy(update={"task_id": task_id}),
        }
    )
    finding.task_id = task_id
    asyncio.run(store.create(bundle.task))
    asyncio.run(store.save_findings(task_id, [finding]))
    preparing = _record(bundle, finding)
    assert asyncio.run(store.create_repair(preparing)) == preparing

    built = RepairRecord.model_validate(
        preparing.model_copy(
            update={
                "status": "built",
                "source_sha256": "c" * 64,
                "baseline_source_sha256": "d" * 64,
                "workspace_name": "repair-mysql-source",
                "baseline_image_digest": "sha256:" + "a" * 64,
                "patched_image_digest": "sha256:" + "b" * 64,
                "patch_ref": _ref("mysql-patch"),
                "build_ref": _ref("mysql-build"),
            }
        ).model_dump()
    )
    assert asyncio.run(store.update_repair(built, "preparing"))
    stale = built.model_copy(update={"status": "failed", "failure_reason": "stale"})
    assert not asyncio.run(store.update_repair(stale, "preparing"))
    retesting = built.model_copy(update={"status": "retesting"})
    assert asyncio.run(store.update_repair(retesting, "built"))
    comparison = RepairComparison(
        source_task_id=task_id,
        finding_id=finding.id,
        baseline_task_id="baseline-task",
        patched_task_id="patched-task",
        retest_experiment_ids=["baseline-exp", "patched-exp"],
        measured_gain_percent=85.0,
        baseline_median_ms=100.0,
        patched_median_ms=15.0,
        evidence_ids=["mysql-baseline", "mysql-patched"],
    )
    finished = RepairRecord.model_validate(
        retesting.model_copy(
            update={
                "status": "retested",
                "comparison": comparison,
                "baseline_run": _run(),
                "patched_run": _run(patched=True),
                "retest_refs": [_ref("mysql-baseline"), _ref("mysql-patched")],
            }
        ).model_dump()
    )
    updated = apply_retest_fields(finding, comparison)
    wrong = updated.model_copy(update={"status": "unclassified"})
    with pytest.raises(ValueError, match="diagnostic evidence"):
        asyncio.run(store.complete_repair(finished, wrong, "retesting"))
    assert asyncio.run(store.load_repair(task_id, preparing.id)) == retesting
    assert asyncio.run(store.complete_repair(finished, updated, "retesting"))

    restarted = build_store(settings)
    assert asyncio.run(restarted.load_repair(task_id, preparing.id)) == finished
    assert asyncio.run(restarted.load_bundle(task_id)).findings == [updated]
    assert asyncio.run(restarted.complete_repair(finished, updated, "retesting"))


def test_orphaned_patch_reconciles_after_store_restart_without_source(tmp_path: Path) -> None:
    if not os.environ.get("PROJECT_DOCTOR_PLATFORM_DSN"):
        pytest.skip("PROJECT_DOCTOR_PLATFORM_DSN not set; repair recovery unverified")
    settings = make_settings(tmp_path)
    store = build_store(settings)
    bundle, finding = _handoff()
    task_id = "repair-orphan-" + uuid.uuid4().hex
    bundle.task = bundle.task.model_copy(
        update={
            "id": task_id,
            "correlation": bundle.task.correlation.model_copy(
                update={"task_id": task_id, "operation_id": "fix-orphan"}
            ),
        }
    )
    finding.task_id = task_id
    diff = "test patch"
    context = bundle.task.correlation
    identity = hashlib.sha256(f"{task_id}\n{context.operation_id}".encode()).hexdigest()[:24]
    preparing = RepairRecord(
        id="repair-" + identity,
        task_id=task_id,
        finding_id=finding.id,
        operation_id=context.operation_id,
        attempt_id="worker-that-exited",
        status="preparing",
        source_commit=bundle.task.project.commit,
        patch_sha256=hashlib.sha256(diff.encode()).hexdigest(),
        parent_key_column="user_id",
    )

    async def run() -> None:
        await store.create(bundle.task)
        await store.save_findings(task_id, [finding])
        await store.create_repair(preparing)
        restarted = build_store(settings)
        workflow = RepairWorkflow(settings, restarted, Reader(False), object())
        with pytest.raises(ValueError, match="operation_conflict"):
            await workflow.submit_fix_patch(context, finding.id, "different patch")
        assert await restarted.load_repair(task_id, preparing.id) == preparing
        settled = await workflow.submit_fix_patch(context, finding.id, diff)
        assert settled.status == "needs_reconcile"
        assert "exited" in (settled.failure_reason or "")
        assert await build_store(settings).load_repair(task_id, preparing.id) == settled
        assert (await restarted.load_bundle(task_id)).findings == [finding]

    asyncio.run(run())
