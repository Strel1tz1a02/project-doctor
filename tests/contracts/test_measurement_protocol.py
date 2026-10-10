from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from project_doctor.models.common import EvidenceRef
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
    # A measured LOCK_TIME may still be zero next to unknown coverage; the diagnosis
    # gate (not the model) treats the missing coverage as insufficient.
    call = SqlCall(
        id="sql",
        normalized_sql="SELECT 1",
        lock_wait_ms=0,
        metric_sources={
            "lock_wait_ms": MetricSource(source="performance_schema", measurement="actual")
        },
        lock_evidence=unknown,
    )
    assert call.lock_wait_ms == 0
    # covered_no_wait without proven table/InnoDB row-lock coverage is rejected.
    with pytest.raises(ValidationError, match="table and InnoDB"):
        LockEvidence(
            status="covered_no_wait", coverage="complete", window_start=now, window_end=now
        )


def test_covered_no_wait_accepts_bounded_metadata_residual() -> None:
    now = datetime.now(UTC)
    ref = EvidenceRef(
        artifact_id="evt-1",
        relative_path="tasks/task-1/experiments/op-1/locks/req-1/coverage.json",
        media_type="application/json",
        format_version="lock-sampling.v1",
        sha256="a" * 64,
        size_bytes=1,
    )
    # table/InnoDB proven by LOCK_TIME==0; metadata (MDL) bounded by the residual.
    evidence = LockEvidence(
        status="covered_no_wait",
        coverage="complete",
        covered_kinds=["table", "innodb_data"],
        missing_kinds=[],
        residual_ms=0.05,
        thread_id=1,
        statement_event_id=1,
        window_start=now,
        window_end=now,
        evidence_refs=[ref],
    )
    assert evidence.residual_ms == 0.05


def test_sql_call_parameterization_fields_are_optional() -> None:
    call = SqlCall(id="sql", normalized_sql="SELECT * FROM users WHERE id = 123")
    assert call.template_sql is None
    assert call.literal_parameters == []
    templated = SqlCall(
        id="sql",
        normalized_sql="SELECT * FROM users WHERE id = 123",
        template_sql="SELECT * FROM users WHERE id = ?",
        literal_parameters=["123"],
    )
    assert templated.template_sql == "SELECT * FROM users WHERE id = ?"
    assert templated.literal_parameters == ["123"]


def test_warmup_cannot_reuse_a_formal_request_id() -> None:
    result = load_case()["bundle"]["experiments"][0]
    result["warmup_results"][0]["request_id"] = result["observations"][0]["request_id"]
    with pytest.raises(ValidationError, match="duplicate request identity"):
        ExperimentResult.model_validate(result)
