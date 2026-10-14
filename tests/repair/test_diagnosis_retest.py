"""The diagnosis service, not the patch workflow, decides repair effect."""

import asyncio
from pathlib import Path

import pytest

from project_doctor.integrations.diagnosis.retest import (
    DockerDiagnosisRetester,
    _key_values,
    _safe_parent_query,
)
from project_doctor.models.common import EvidenceRef
from project_doctor.models.repair import RepairRecord
from project_doctor.workflows.diagnose_retest import (
    DiagnosisRetestService,
    RetestEvidence,
    RetestRejected,
)
from tests.diagnosis.test_n_plus_one import Reader
from tests.repair.test_gates import _handoff, _run


class Adapter:
    def __init__(self, evidence: RetestEvidence) -> None:
        self.evidence = evidence

    async def run(self, bundle, finding, repair) -> RetestEvidence:
        return self.evidence

    async def cleanup(self, repair, context) -> None:
        pass


def test_cleanup_targets_both_retest_environments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.repair.test_workflow import _settings

    bundle, finding = _handoff()
    repair = _repair(bundle, finding)
    calls: list[tuple[str, str]] = []

    class Gateway:
        def __init__(self, *args, **kwargs):
            pass

        async def teardown(self, environment_id, context):
            calls.append((environment_id, context.task_id))

    monkeypatch.setattr(
        "project_doctor.integrations.diagnosis.retest.DockerEnvironmentGateway", Gateway
    )
    retester = DockerDiagnosisRetester(_settings(tmp_path), object(), Reader())
    asyncio.run(retester.cleanup(repair, bundle.task.correlation))
    assert calls == [
        ("repair-1-baseline", "repair-1-baseline"),
        ("repair-1-patched", "repair-1-patched"),
    ]


def _ref(digest: str = "a" * 64) -> EvidenceRef:
    return EvidenceRef(
        artifact_id="artifact-1",
        relative_path="repairs/diagnostic-retest.json",
        media_type="application/json",
        format_version="repair.run.v1",
        sha256=digest,
        size_bytes=1,
    )


def _repair(bundle, finding) -> RepairRecord:
    return RepairRecord(
        id="repair-1",
        task_id=bundle.task.id,
        finding_id=finding.id,
        operation_id="repair-op",
        attempt_id="attempt-1",
        status="retesting",
        source_commit=bundle.task.project.commit,
        patch_sha256="b" * 64,
        source_sha256="c" * 64,
        baseline_source_sha256="d" * 64,
        parent_key_column="user_id",
        workspace_name="fix-repair-1/patched",
        baseline_image_digest=_run().image_digest,
        patched_image_digest=_run(patched=True).image_digest,
        patch_ref=_ref("b" * 64),
        build_ref=_ref(),
    )


def test_diagnosis_retest_returns_evidence_based_verdict() -> None:
    bundle, finding = _handoff()
    evidence = RetestEvidence(_run(), _run(patched=True), (_ref(),))
    verdict = asyncio.run(
        DiagnosisRetestService(Adapter(evidence), Reader()).run(
            bundle, finding, _repair(bundle, finding)
        )
    )
    assert verdict.comparison.measured_gain_percent > 80
    assert verdict.evidence is evidence


def test_unregistered_problem_kind_cannot_claim_retested() -> None:
    bundle, finding = _handoff()
    other = finding.model_copy(update={"kind": "deep_pagination", "fix_spec": None})
    evidence = RetestEvidence(_run(), _run(patched=True), (_ref(),))
    service = DiagnosisRetestService(Adapter(evidence), Reader(), verifiers={})
    with pytest.raises(ValueError, match="verifier is unavailable for deep_pagination"):
        asyncio.run(service.run(bundle, other, _repair(bundle, finding)))


def test_diagnosis_retest_rejects_wrong_image_and_business_output() -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding)
    repair.patched_image_digest = "sha256:" + "f" * 64
    evidence = RetestEvidence(_run(), _run(patched=True), (_ref(),))
    service = DiagnosisRetestService(Adapter(evidence), Reader())
    with pytest.raises(ValueError, match="image identities"):
        asyncio.run(service.run(bundle, finding, repair))
    repair.patched_image_digest = _run(patched=True).image_digest
    evidence.patched.samples[0].result_digest = "e" * 64
    with pytest.raises(ValueError, match="business results"):
        asyncio.run(service.run(bundle, finding, repair))


def test_diagnosis_retest_preserves_verified_samples_when_gain_is_noise() -> None:
    bundle, finding = _handoff()
    baseline, patched = _run(), _run(patched=True)
    for sample in patched.samples:
        sample.latency_ms = 105.0
    evidence = RetestEvidence(baseline, patched, (_ref(),))
    service = DiagnosisRetestService(Adapter(evidence), Reader())
    with pytest.raises(RetestRejected, match="gain") as caught:
        asyncio.run(service.run(bundle, finding, _repair(bundle, finding)))
    assert caught.value.evidence is evidence


def test_parent_replay_requires_read_only_select_and_exact_child_keys() -> None:
    assert _safe_parent_query("SELECT * FROM orders LIMIT 20", "user_id") == (
        "SELECT DISTINCT `user_id` FROM (SELECT * FROM orders LIMIT 20) AS pd_parent"
    )
    with pytest.raises(ValueError, match="safely replayed"):
        _safe_parent_query("DELETE FROM orders", "user_id")
    assert _key_values("SELECT * FROM users WHERE id IN (1, 2, 3)", "id", batch=True) == [
        "1",
        "2",
        "3",
    ]
