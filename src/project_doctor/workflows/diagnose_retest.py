"""Diagnosis owns the measurements and verdict for a source repair retest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from project_doctor.features.diagnosis.ports import EvidenceReader
from project_doctor.features.diagnosis.retest import evaluate_retest
from project_doctor.models.common import EvidenceRef
from project_doctor.models.finding import Finding
from project_doctor.models.repair import RepairComparison, RepairRecord, RepairRun
from project_doctor.models.task import CallContext, TaskBundle


@dataclass(frozen=True)
class RetestEvidence:
    baseline: RepairRun
    patched: RepairRun
    refs: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class ValidatedRetest:
    comparison: RepairComparison
    evidence: RetestEvidence


class RetestRejected(ValueError):
    """A completed, verified measurement that failed the diagnosis verdict gate."""

    def __init__(self, reason: str, evidence: RetestEvidence) -> None:
        super().__init__(reason)
        self.evidence = evidence


class DiagnosticRetestAdapter(Protocol):
    async def run(
        self, bundle: TaskBundle, finding: Finding, repair: RepairRecord
    ) -> RetestEvidence: ...

    async def cleanup(self, repair: RepairRecord, context: CallContext) -> None: ...


class DiagnosisRetestService:
    def __init__(self, adapter: DiagnosticRetestAdapter, reader: EvidenceReader) -> None:
        self._adapter = adapter
        self._reader = reader

    async def cleanup(self, repair: RepairRecord, context: CallContext) -> None:
        await self._adapter.cleanup(repair, context)

    async def run(
        self, bundle: TaskBundle, finding: Finding, repair: RepairRecord
    ) -> ValidatedRetest:
        if repair.status != "retesting" or repair.source_commit != bundle.task.project.commit:
            raise ValueError("diagnostic retest needs the persisted source build")
        if repair.patch_ref is None or repair.build_ref is None:
            raise ValueError("diagnostic retest lacks patch/build evidence")
        if repair.patch_ref.sha256 != repair.patch_sha256:
            raise ValueError("diagnostic retest patch digest differs from the submitted patch")
        build_check = await self._reader.verify([repair.patch_ref, repair.build_ref])
        if not build_check.valid:
            raise ValueError("diagnostic retest patch/build evidence is unavailable")
        evidence = await self._adapter.run(bundle, finding, repair)
        if (
            evidence.baseline.image_digest != repair.baseline_image_digest
            or evidence.patched.image_digest != repair.patched_image_digest
        ):
            raise ValueError("diagnostic retest image identities differ from the built images")
        observed_ids = set(evidence.baseline.evidence_ids + evidence.patched.evidence_ids)
        if not observed_ids.issubset({ref.artifact_id for ref in evidence.refs}):
            raise ValueError("diagnostic observations lack published evidence")
        check = await self._reader.verify(list(evidence.refs))
        if not check.valid:
            raise ValueError("diagnostic retest artifacts are unavailable or corrupt")
        try:
            comparison = evaluate_retest(finding, evidence.baseline, evidence.patched)
        except ValueError as exc:
            raise RetestRejected(str(exc), evidence) from exc
        return ValidatedRetest(comparison, evidence)
