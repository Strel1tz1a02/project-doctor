"""Diagnosis owns the measurements and verdict for a source repair retest."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from project_doctor.features.diagnosis.ports import EvidenceReader
from project_doctor.features.diagnosis.retest import (
    evaluate_deep_pagination_retest,
    evaluate_retest,
    evaluate_slow_query_retest,
)
from project_doctor.models.common import EvidenceRef
from project_doctor.models.deep_pagination import DeepPaginationSpec
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
    def __init__(
        self,
        adapter: DiagnosticRetestAdapter,
        reader: EvidenceReader,
        verifiers: Mapping[str, Callable[[Finding, RepairRun, RepairRun], RepairComparison]]
        | None = None,
    ) -> None:
        self._adapter = adapter
        self._reader = reader
        self._verifiers = (
            dict(verifiers)
            if verifiers is not None
            else {
                "n_plus_one": evaluate_retest,
                "slow_query": evaluate_slow_query_retest,
                "deep_pagination": evaluate_deep_pagination_retest,
            }
        )

    async def cleanup(self, repair: RepairRecord, context: CallContext) -> None:
        await self._adapter.cleanup(repair, context)

    async def run(
        self, bundle: TaskBundle, finding: Finding, repair: RepairRecord
    ) -> ValidatedRetest:
        verifier = self._verifiers.get(finding.kind)
        if verifier is None:
            raise ValueError(
                f"diagnostic source-version verifier is unavailable for {finding.kind}"
            )
        if finding.kind == "deep_pagination" and (
            not isinstance(finding.fix_spec, DeepPaginationSpec)
            or finding.fix_spec.strategy != "keyset"
        ):
            raise ValueError("deep-pagination source verifier only supports keyset")
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
            comparison = verifier(finding, evidence.baseline, evidence.patched)
        except ValueError as exc:
            raise RetestRejected(str(exc), evidence) from exc
        return ValidatedRetest(comparison, evidence)
