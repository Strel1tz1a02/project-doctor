from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from project_doctor.models.experiment import ExperimentResult, WarmupSpec
from project_doctor.models.lock import LockEvidence
from project_doctor.models.observation import MetricSource, SqlCall
from tests.contracts.test_contracts import load_case


def test_old_results_remain_readable_without_claiming_preparation() -> None:
    result = ExperimentResult(experiment_id="old", operation_id="op", phase="prepared")
    assert result.preparation_results == result.warmup_results == []
    assert WarmupSpec().requests_per_level == 5


def test_empty_poll_cannot_assert_zero() -> None:
    now = datetime.now(UTC)
    unknown = LockEvidence(status="unknown", coverage="partial", window_start=now, window_end=now)
    with pytest.raises(ValidationError, match="cannot assert zero"):
        SqlCall(
            id="sql",
            normalized_sql="SELECT 1",
            lock_wait_ms=0,
            metric_sources={"lock_wait_ms": MetricSource(source="poll", measurement="actual")},
            lock_evidence=unknown,
        )
    with pytest.raises(ValidationError, match="complete associated"):
        LockEvidence(
            status="covered_no_wait", coverage="complete", window_start=now, window_end=now
        )


def test_warmup_cannot_reuse_a_formal_request_id() -> None:
    result = load_case()["bundle"]["experiments"][0]
    result["warmup_results"][0]["request_id"] = result["observations"][0]["request_id"]
    with pytest.raises(ValidationError, match="duplicate request identity"):
        ExperimentResult.model_validate(result)
