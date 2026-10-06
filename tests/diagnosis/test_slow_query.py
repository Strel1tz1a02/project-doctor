import asyncio
import json
from pathlib import Path

import pytest

from project_doctor.features.diagnosis.slow_query import check_slow_query
from project_doctor.models.common import EvidenceCheck, EvidenceRef
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.task import TaskBundle
from project_doctor.workflows.diagnose import evaluate


def add_spec(bundle: TaskBundle) -> TaskBundle:
    path = Path(__file__).resolve().parents[1] / "contracts/fixtures/verified_slow_query.json"
    spec = ExperimentSpec.model_validate(json.loads(path.read_text("utf-8"))["spec"])
    bundle.experiments[0].spec = spec
    return bundle


class Reader:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid

    async def verify(self, refs: list[EvidenceRef]) -> EvidenceCheck:
        return EvidenceCheck(
            valid=self.valid, missing_ids=[] if self.valid else [refs[0].artifact_id]
        )


def test_index_work_reduction_supported_under_comparable_conditions(bundle: TaskBundle) -> None:
    add_spec(bundle)
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "verified"
    assert findings[0].impact.latency_delta_ms == 90
    assert findings[0].recommendation is not None
    assert findings[0].recommendation.measured_gain_percent is None


@pytest.mark.parametrize(
    "condition",
    [
        "missing_spec",
        "missing_location",
        "missing_plan",
        "invalid_business",
        "different_result",
        "different_snapshot",
        "unknown_cache",
        "lock_wait",
        "missing_rows",
        "unstable",
        "not_finished",
        "restore_failed",
        "different_commit",
        "no_effect",
        "duplicate_repetition",
    ],
)
def test_incomplete_or_confounded_evidence_is_never_verified(
    bundle: TaskBundle, condition: str
) -> None:
    add_spec(bundle)
    result = bundle.experiments[0]
    first = result.observations[0]
    call = first.sql_calls[0]
    if condition == "missing_spec":
        result.spec = None
    elif condition == "missing_location":
        call.code_location = None
    elif condition == "missing_plan":
        call.plan_evidence_ids = []
    elif condition == "invalid_business":
        first.business_valid = False
    elif condition == "different_result":
        first.result_digest = "c" * 64
    elif condition == "different_snapshot":
        first.snapshot_id = "another-snapshot"
    elif condition == "unknown_cache":
        bundle.scenarios[0].cache.state = "unknown"
    elif condition == "lock_wait":
        call.lock_evidence = None
        call.lock_wait_ms = 100
    elif condition == "missing_rows":
        call.metric_sources.pop("rows_examined")
        call.rows_examined = None
    elif condition == "unstable":
        first.latency_ms = 10000
        call.duration_ms = 10000
    elif condition == "not_finished":
        result.phase = "needs_reconcile"
    elif condition == "restore_failed":
        result.phase = "needs_reconcile"
        result.restore_result = None
    elif condition == "different_commit":
        assert call.code_location is not None
        call.code_location.commit = "old-commit"
    elif condition == "no_effect":
        for item in result.observations:
            item.sql_calls[0].duration_ms = 100
    elif condition == "duplicate_repetition":
        result.observations[1].repetition = 1
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert all(item.status == "lead" for item in findings)


def test_unreadable_artifact_cannot_be_verified(bundle: TaskBundle) -> None:
    add_spec(bundle)
    findings = asyncio.run(evaluate(bundle, Reader(False)))
    assert findings[0].status == "lead"
    assert any("缺失" in reason for reason in findings[0].limitations)


def test_request_latency_without_sql_effect_does_not_prove_root_cause(bundle: TaskBundle) -> None:
    add_spec(bundle)
    for observation in bundle.experiments[0].observations:
        observation.sql_calls[0].duration_ms = 100
    result = check_slow_query(
        bundle.experiments[0], bundle.scenarios[0], bundle.task.id, bundle.task.project.commit
    )
    assert result[0].status == "lead"


def test_slow_query_hypothesis_unclassified_when_not_reproduced(bundle: TaskBundle) -> None:
    add_spec(bundle)
    # Intervention does not reduce scanned rows, and the baseline SQL is already
    # below the minimum distinguishable delta: the hypothesis did not reproduce.
    for item in bundle.experiments[0].observations:
        item.sql_calls[0].rows_examined = 10
        item.sql_calls[0].duration_ms = 0.5
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "unclassified"
    assert findings[0].recommendation is None


def test_repeated_request_id_is_not_independent_measurement(bundle: TaskBundle) -> None:
    add_spec(bundle)
    bundle.experiments[0].observations[1].request_id = (
        bundle.experiments[0].observations[0].request_id
    )
    assert asyncio.run(evaluate(bundle, Reader()))[0].status == "lead"
