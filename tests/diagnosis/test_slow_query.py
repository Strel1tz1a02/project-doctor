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


def test_lock_residual_larger_than_effect_prevents_verified(bundle: TaskBundle) -> None:
    add_spec(bundle)
    for item in bundle.experiments[0].observations:
        call = item.sql_calls[0]
        payload = call.model_dump(mode="json")
        payload["lock_evidence"]["residual_ms"] = 10000
        item.sql_calls[0] = type(call).model_validate(payload)
    result = asyncio.run(evaluate(bundle, Reader()))
    assert result[0].status == "lead"
    assert any("残差上界" in reason for reason in result[0].limitations)


@pytest.mark.parametrize("wait,expected", [(0.003, "verified"), (10000, "lead")])
def test_measured_table_wait_is_compared_with_gain_not_rounded_to_zero(
    bundle: TaskBundle, wait: float, expected: str
) -> None:
    add_spec(bundle)
    for item in bundle.experiments[0].observations:
        call = item.sql_calls[0]
        payload = call.model_dump(mode="json")
        payload["lock_wait_ms"] = wait
        payload["lock_evidence"]["status"] = "observed"
        item.sql_calls[0] = type(call).model_validate(payload)
    result = asyncio.run(evaluate(bundle, Reader()))
    assert result[0].status == expected


def test_repeated_request_id_is_not_independent_measurement(bundle: TaskBundle) -> None:
    add_spec(bundle)
    bundle.experiments[0].observations[1].request_id = (
        bundle.experiments[0].observations[0].request_id
    )
    assert asyncio.run(evaluate(bundle, Reader()))[0].status == "lead"


@pytest.mark.parametrize(
    "condition", ["covered", "missing", "not_covering", "subquery", "unstable"]
)
def test_count_negative_requires_covering_plan_and_unchanged_actual_work(
    bundle: TaskBundle, condition: str
) -> None:
    add_spec(bundle)
    plans = {}
    for index, item in enumerate(bundle.experiments[0].observations):
        call = item.sql_calls[0]
        call.normalized_sql = "SELECT COUNT(*) FROM orders WHERE status = 'PAID'"
        if condition == "subquery":
            call.normalized_sql += " AND user_id IN (SELECT id FROM users)"
        call.rows_examined = 40000
        call.rows_returned = 1
        call.duration_ms = 4 if condition != "unstable" or index != 0 else 100
        for key in call.plan_evidence_ids:
            plans[key] = {
                "query_block": {
                    "table": {
                        "table_name": "orders",
                        "access_type": "ref",
                        "key": "existing",
                        "used_key_parts": ["status"],
                        "used_columns": ["status"],
                        "using_index": condition != "not_covering",
                        "rows_examined_per_scan": 1,
                    }
                }
            }
    findings = check_slow_query(
        bundle.experiments[0],
        bundle.scenarios[0],
        bundle.task.id,
        bundle.task.project.commit,
        verified_plans={} if condition == "missing" else plans,
    )
    assert findings[0].status == ("unclassified" if condition == "covered" else "lead")
    assert any("COUNT" in note for note in findings[0].limitations)
