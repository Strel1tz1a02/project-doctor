"""Durable Java/MyBatis patch workflow. Only a retest adapter may produce measurements."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Callable

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.diagnosis.ports import EvidenceReader
from project_doctor.features.repair.gates import (
    apply_retest_fields,
    validate_handoff,
)
from project_doctor.features.repair.source import present_target
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.integrations.repair.build import build_image
from project_doctor.integrations.repair.lease import RepairBusy, repair_lease
from project_doctor.integrations.repair.source import (
    apply_patch,
    copy_baseline_source,
    inspect_target,
)
from project_doctor.models.finding import Finding
from project_doctor.models.n_plus_one import BatchQuerySpec
from project_doctor.models.repair import RepairRecord, RepairTargetView
from project_doctor.models.task import CallContext, TaskBundle
from project_doctor.workflows.diagnose_retest import DiagnosisRetestService, RetestRejected
from project_doctor.workflows.task_ports import TaskStore


class RepairWorkflow:
    def __init__(
        self,
        settings: Settings,
        store: TaskStore,
        reader: EvidenceReader,
        diagnosis: DiagnosisRetestService,
    ) -> None:
        self._settings = settings
        self._store = store
        self._reader = reader
        self._diagnosis = diagnosis

    async def _target(
        self, task_id: str, finding_id: str
    ) -> tuple[TaskBundle, Finding, BatchQuerySpec]:
        bundle = await self._store.load_bundle(task_id)
        finding = next((item for item in bundle.findings if item.id == finding_id), None)
        if finding is None:
            raise ValueError("finding is not persisted in this task")
        spec = validate_handoff(finding, bundle)
        if not (await self._reader.verify(finding.evidence_refs)).valid:
            raise ValueError("diagnostic handoff evidence is unavailable or corrupt")
        return bundle, finding, spec

    async def inspect_fix_target(self, context: CallContext, finding_id: str) -> RepairTargetView:
        bundle, finding, spec = await self._target(context.task_id, finding_id)
        target = await asyncio.to_thread(
            inspect_target,
            self._settings.target_repo_root,
            spec,
            bundle.task.project.commit,
        )
        return present_target(finding_id, target)

    async def submit_fix_patch(
        self, context: CallContext, finding_id: str, diff: str
    ) -> RepairRecord:
        identity = hashlib.sha256(
            f"{context.task_id}\n{context.operation_id}".encode()
        ).hexdigest()[:24]
        with repair_lease(self._settings.workspace_root, "repair-" + identity):
            return await self._submit_fix_patch_locked(context, finding_id, diff, identity)

    async def _submit_fix_patch_locked(
        self, context: CallContext, finding_id: str, diff: str, identity: str
    ) -> RepairRecord:
        if not diff.strip() or len(diff.encode("utf-8")) > 128_000:
            raise ValueError("patch is empty or exceeds 128 KB")
        patch_hash = hashlib.sha256(diff.encode("utf-8")).hexdigest()
        existing = await self._store.load_repair(context.task_id, "repair-" + identity)
        if existing is not None:
            if (
                existing.finding_id != finding_id
                or existing.operation_id != context.operation_id
                or existing.patch_sha256 != patch_hash
            ):
                raise ValueError("operation_conflict: repair identity has different input")
            return await self._prior_repair(existing)
        bundle, finding, spec = await self._target(context.task_id, finding_id)
        target = await asyncio.to_thread(
            inspect_target,
            self._settings.target_repo_root,
            spec,
            bundle.task.project.commit,
        )
        repair = RepairRecord(
            id="repair-" + identity,
            task_id=context.task_id,
            finding_id=finding_id,
            operation_id=context.operation_id,
            attempt_id=uuid.uuid4().hex,
            status="preparing",
            source_commit=bundle.task.project.commit,
            patch_sha256=patch_hash,
            parent_key_column=target.parent_key_column,
        )
        prior = await self._store.create_repair(repair)
        if prior.attempt_id != repair.attempt_id:
            return await self._prior_repair(prior)
        try:
            workspace = self._settings.workspace_root / ("fix-" + identity)
            source = await asyncio.to_thread(
                apply_patch,
                target,
                diff,
                workspace,
            )
            baseline_source = await asyncio.to_thread(copy_baseline_source, target, workspace)
            patch_ref = await publish_artifact(
                self._settings.artifact_root,
                f"tasks/{context.task_id}/repairs/{repair.id}/patch.diff",
                diff.encode("utf-8"),
                "text/x-diff",
                "repair.patch.v1",
            )
            baseline_image, built = await asyncio.gather(
                asyncio.to_thread(
                    build_image,
                    baseline_source,
                    timeout_seconds=480.0,
                    tag_prefix="project-doctor-baseline",
                ),
                asyncio.to_thread(build_image, source, timeout_seconds=480.0),
            )
            if baseline_image.digest == built.digest:
                raise ValueError("patched image reused the baseline image")
            build_ref = await publish_artifact(
                self._settings.artifact_root,
                f"tasks/{context.task_id}/repairs/{repair.id}/build.json",
                json.dumps(
                    {
                        "source_commit": source.source_commit,
                        "source_sha256": source.source_sha256,
                        "baseline_source_sha256": baseline_source.source_sha256,
                        "patch_sha256": source.patch_sha256,
                        "changed_paths": source.changed_paths,
                        "before_hashes": source.before_hashes,
                        "after_hashes": source.after_hashes,
                        "baseline_image_digest": baseline_image.digest,
                        "patched_image_digest": built.digest,
                        "build_log": built.build_log[-16000:],
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode("utf-8"),
                "application/json",
                "repair.build.v1",
            )
            workspace_name = source.root.relative_to(self._settings.workspace_root).as_posix()
            completed = repair.model_copy(
                update={
                    "status": "built",
                    "source_sha256": source.source_sha256,
                    "baseline_source_sha256": baseline_source.source_sha256,
                    "workspace_name": workspace_name,
                    "baseline_image_digest": baseline_image.digest,
                    "patched_image_digest": built.digest,
                    "patch_ref": patch_ref,
                    "build_ref": build_ref,
                }
            )
            completed = RepairRecord.model_validate(completed.model_dump())
            if not await self._store.update_repair(completed, "preparing"):
                raise ValueError("repair state changed during build; reconcile")
            return completed
        except Exception as exc:
            failed = repair.model_copy(
                update={"status": "failed", "failure_reason": str(exc)[:1000] or "build failed"}
            )
            await self._store.update_repair(failed, "preparing")
            raise
        except BaseException:
            unknown = repair.model_copy(
                update={
                    "status": "needs_reconcile",
                    "failure_reason": "build outcome unknown after interruption",
                }
            )
            await self._store.update_repair(unknown, "preparing")
            raise

    async def _prior_repair(self, prior: RepairRecord) -> RepairRecord:
        if prior.status == "preparing":
            unknown = RepairRecord.model_validate(
                prior.model_copy(
                    update={
                        "status": "needs_reconcile",
                        "failure_reason": "build worker exited before recording its outcome",
                    }
                ).model_dump()
            )
            if await self._store.update_repair(unknown, "preparing"):
                return unknown
            raise ValueError("repair changed during reconciliation")
        if prior.status == "retested" and not (await self._reader.verify(prior.retest_refs)).valid:
            raise ValueError("persisted retest evidence is unavailable")
        return prior

    async def verify_fix(
        self,
        context: CallContext,
        repair_id: str,
        on_started: Callable[[RepairRecord], None] | None = None,
    ) -> RepairRecord:
        with repair_lease(self._settings.workspace_root, repair_id):
            return await self._verify_fix_locked(context, repair_id, on_started)

    async def _verify_fix_locked(
        self,
        context: CallContext,
        repair_id: str,
        on_started: Callable[[RepairRecord], None] | None,
    ) -> RepairRecord:
        repair = await self._store.load_repair(context.task_id, repair_id)
        if repair is None:
            raise ValueError("repair is not persisted in this task")
        if repair.status == "retested":
            check = await self._reader.verify(repair.retest_refs)
            if not check.valid:
                raise ValueError("persisted retest evidence is unavailable")
            return repair
        if repair.status == "retesting":
            return await self._reconcile_exited_retest(context, repair)
        if repair.status != "built":
            raise ValueError("repair is not ready for retest; reconcile its state")
        bundle, finding, _ = await self._target(context.task_id, repair.finding_id)
        retesting = repair.model_copy(update={"status": "retesting"})
        if not await self._store.update_repair(retesting, "built"):
            raise ValueError("another retest owns this repair")
        if on_started is not None:
            on_started(retesting)
        try:
            verdict = await self._diagnosis.run(bundle, finding, retesting)
            comparison = verdict.comparison
            evidence = verdict.evidence
            report_ref = await publish_artifact(
                self._settings.artifact_root,
                f"tasks/{context.task_id}/repairs/{repair.id}/comparison.json",
                json.dumps(
                    comparison.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
                ).encode("utf-8"),
                "application/json",
                "repair.comparison.v1",
            )
            completed = RepairRecord.model_validate(
                retesting.model_copy(
                    update={
                        "status": "retested",
                        "comparison": comparison,
                        "baseline_run": evidence.baseline,
                        "patched_run": evidence.patched,
                        "retest_refs": [*evidence.refs, report_ref],
                    }
                ).model_dump()
            )
            updated_finding = apply_retest_fields(finding, comparison)
            if not await self._store.complete_repair(completed, updated_finding, "retesting"):
                raise ValueError("repair changed during retest; reconcile")
            return completed
        except RetestRejected as exc:
            failed = RepairRecord.model_validate(
                retesting.model_copy(
                    update={
                        "status": "failed",
                        "failure_reason": (str(exc)[:950] or "diagnostic retest rejected")
                        + "; cleanup pending",
                        "baseline_run": exc.evidence.baseline,
                        "patched_run": exc.evidence.patched,
                        "retest_refs": list(exc.evidence.refs),
                    }
                ).model_dump()
            )
            if await self._store.update_repair(failed, "retesting"):
                await self._retry_cleanup(context, failed)
            raise
        except Exception as exc:
            failed = retesting.model_copy(
                update={
                    "status": "failed",
                    "failure_reason": (str(exc)[:950] or "retest failed") + "; cleanup pending",
                }
            )
            if await self._store.update_repair(failed, "retesting"):
                await self._retry_cleanup(context, failed)
            raise
        except BaseException:
            unknown = retesting.model_copy(
                update={
                    "status": "needs_reconcile",
                    "failure_reason": "retest outcome unknown after interruption; cleanup pending",
                }
            )
            if await self._store.update_repair(unknown, "retesting"):
                await self._retry_cleanup(context, unknown)
            raise

    async def get_fix_status(self, context: CallContext, repair_id: str) -> RepairRecord:
        try:
            with repair_lease(self._settings.workspace_root, repair_id):
                repair = await self._store.load_repair(context.task_id, repair_id)
                if repair is None:
                    raise ValueError("repair is not persisted in this task")
                if repair.status == "preparing":
                    return await self._prior_repair(repair)
                if repair.status == "retesting":
                    return await self._reconcile_exited_retest(context, repair)
                if repair.status in {"failed", "needs_reconcile"} and any(
                    marker in (repair.failure_reason or "")
                    for marker in ("; cleanup pending", "; cleanup failed:")
                ):
                    return await self._retry_cleanup(context, repair)
                return repair
        except RepairBusy:
            repair = await self._store.load_repair(context.task_id, repair_id)
            if repair is None:
                raise ValueError("repair is not persisted in this task") from None
            return repair

    async def _reconcile_exited_retest(
        self, context: CallContext, repair: RepairRecord
    ) -> RepairRecord:
        unknown = RepairRecord.model_validate(
            repair.model_copy(
                update={
                    "status": "needs_reconcile",
                    "failure_reason": (
                        "diagnostic retest worker exited before recording its outcome"
                        "; cleanup pending"
                    ),
                }
            ).model_dump()
        )
        if not await self._store.update_repair(unknown, "retesting"):
            raise ValueError("repair changed during reconciliation")
        return await self._retry_cleanup(context, unknown)

    async def _retry_cleanup(self, context: CallContext, repair: RepairRecord) -> RepairRecord:
        cleanup = asyncio.create_task(self._diagnosis.cleanup(repair, context))
        try:
            await asyncio.shield(cleanup)
        except BaseException as exc:
            if not cleanup.done():
                try:
                    await cleanup
                except BaseException:
                    pass
            if isinstance(exc, asyncio.CancelledError):
                raise
            reason = repair.failure_reason or "diagnostic retest outcome unknown"
            prefix = reason.split("; cleanup pending", 1)[0].split("; cleanup failed:", 1)[0]
            failed = repair.model_copy(
                update={"failure_reason": f"{prefix}; cleanup failed: {exc}"[:1000]}
            )
            if not await self._store.update_repair(failed, repair.status):
                raise ValueError("repair changed during cleanup reconciliation") from exc
            return failed
        reason = repair.failure_reason or "diagnostic retest outcome unknown"
        cleaned = repair.model_copy(
            update={
                "failure_reason": reason.split("; cleanup pending", 1)[0].split(
                    "; cleanup failed:", 1
                )[0]
            }
        )
        if not await self._store.update_repair(cleaned, repair.status):
            raise ValueError("repair changed during cleanup reconciliation")
        return cleaned
