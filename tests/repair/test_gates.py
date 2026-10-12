"""Repair decisions require persisted handoff and independently checked retest data."""

import asyncio

import pytest
from pydantic import ValidationError

from project_doctor.features.diagnosis.retest import evaluate_retest
from project_doctor.features.repair.gates import (
    apply_retest_fields,
    validate_handoff,
)
from project_doctor.models.deep_pagination import DeepPaginationSpec
from project_doctor.models.finding import Recommendation
from project_doctor.models.repair import RepairRun, RepairSample
from project_doctor.workflows.diagnose import evaluate
from tests.diagnosis.test_n_plus_one import Reader, n_plus_one_bundle

_BASE = n_plus_one_bundle()


def _handoff():
    bundle = n_plus_one_bundle()
    finding = asyncio.run(evaluate(bundle, Reader()))[0]
    bundle.findings = [finding]
    return bundle, finding


def _run(*, patched: bool = False) -> RepairRun:
    return RepairRun(
        task_id="patched-task" if patched else "baseline-task",
        experiment_id="patched-exp" if patched else "baseline-exp",
        source_commit=_BASE.task.project.commit,
        image_digest="sha256:" + ("b" if patched else "a") * 64,
        snapshot_id=_BASE.experiments[0].spec.snapshot_id,
        scenario_id=_BASE.scenarios[0].id,
        scenario_version=_BASE.scenarios[0].version,
        observation_config_id=_BASE.experiments[0].spec.observation_config_id,
        cache_state=_BASE.scenarios[0].cache.state,
        samples=[
            RepairSample(
                request_id=f"{'patched' if patched else 'baseline'}-{n}",
                business_valid=True,
                result_digest="c" * 64,
                latency_ms=(15.0 + n / 10) if patched else (105.0 + n / 10),
                sql_count=2 if patched else 21,
                child_count=0 if patched else 20,
                parent_rows_examined=10000,
                parent_keys=[str(i) for i in range(1, 21)],
                child_parameters=[] if patched else [str(i) for i in range(1, 21)],
                batch_parameters=[str(i) for i in range(1, 21)] if patched else [],
                lock_covered=True,
            )
            for n in range(3)
        ],
        restored=True,
        artifacts_verified=True,
        evidence_ids=["artifact-1"],
    )


def test_valid_handoff_and_retest_changes_only_recommendation_fields() -> None:
    bundle, finding = _handoff()
    assert validate_handoff(finding, bundle).strategy == "batch_in"
    comparison = evaluate_retest(finding, _run(), _run(patched=True))
    updated = apply_retest_fields(finding, comparison)
    assert updated.recommendation is not None
    assert updated.recommendation.validation_status == "retested"
    assert updated.recommendation.measured_gain_percent > 80
    assert updated.recommendation.retest_experiment_ids == ["baseline-exp", "patched-exp"]
    before = finding.model_dump()
    after = updated.model_dump()
    for key in ("validation_status", "measured_gain_percent", "retest_experiment_ids"):
        before["recommendation"].pop(key)
        after["recommendation"].pop(key)
    assert after == before


def test_deep_pagination_handoff_cannot_enter_n_plus_one_repair() -> None:
    bundle, finding = _handoff()
    spec = DeepPaginationSpec(
        strategy="keyset",
        query_template="SELECT * FROM orders ORDER BY id LIMIT ? OFFSET ?",
        sort_column="id",
        code_location=finding.code_locations[0],
        observed_offset=100,
    )
    other = finding.model_copy(update={"kind": "deep_pagination", "fix_spec": spec})
    with pytest.raises(ValueError, match="N\\+1"):
        validate_handoff(other, bundle)
    with pytest.raises(ValueError, match="batch_in fix_spec"):
        evaluate_retest(other, _run(), _run(patched=True))


def test_handoff_rejects_unpersisted_or_unstructured_finding() -> None:
    bundle, finding = _handoff()
    with pytest.raises(ValueError, match="persisted"):
        validate_handoff(finding.model_copy(update={"id": "other"}), bundle)
    with pytest.raises(ValueError, match="fix_spec"):
        validate_handoff(finding.model_copy(update={"fix_spec": None}), bundle)
    assert finding.fix_spec is not None
    finding.fix_spec.child_code_location.association_evidence_ids = ["missing-artifact"]
    with pytest.raises(ValueError, match="mapper location"):
        validate_handoff(finding, bundle)


@pytest.mark.parametrize(
    "change",
    [
        lambda run: setattr(run, "snapshot_id", "other"),
        lambda run: setattr(run.samples[0], "result_digest", "d" * 64),
        lambda run: setattr(run.samples[0], "child_count", 20),
        lambda run: setattr(run.samples[0], "parent_rows_examined", 20000),
        lambda run: setattr(run.samples[0], "batch_parameters", ["unknown"]),
        lambda run: setattr(run, "restored", False),
        lambda run: setattr(run, "artifacts_verified", False),
    ],
)
def test_retest_rejects_incomparable_or_unverified_runs(change) -> None:
    _, finding = _handoff()
    patched = _run(patched=True)
    change(patched)
    with pytest.raises(ValueError):
        evaluate_retest(finding, _run(), patched)


def test_retest_rejects_no_measurable_gain() -> None:
    _, finding = _handoff()
    patched = _run(patched=True)
    for sample in patched.samples:
        sample.latency_ms = 105.0
    with pytest.raises(ValueError, match="gain"):
        evaluate_retest(finding, _run(), patched)


def test_unretested_recommendation_cannot_have_retest_ids() -> None:
    _, finding = _handoff()
    assert finding.recommendation is not None
    with pytest.raises(ValidationError, match="unretested"):
        Recommendation.model_validate(
            {**finding.recommendation.model_dump(), "retest_experiment_ids": ["claimed-exp"]}
        )
