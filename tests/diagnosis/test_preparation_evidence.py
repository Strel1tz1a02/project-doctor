import asyncio

import pytest

from project_doctor.models.task import TaskBundle
from project_doctor.workflows.diagnose import evaluate
from tests.diagnosis.test_slow_query import Reader, add_spec


@pytest.mark.parametrize(
    "fault",
    [
        "legacy",
        "missing_preparation",
        "changed_group",
        "recipe",
        "warmup_failed",
        "digest",
        "duplicate_request",
        "missing_warmup_raw",
        "naked_zero",
    ],
)
def test_incomplete_preparation_or_lock_proof_remains_lead(bundle: TaskBundle, fault: str) -> None:
    add_spec(bundle)
    result = bundle.experiments[0]
    if fault == "legacy":
        result.spec.warmup = None
    elif fault == "missing_preparation":
        result.preparation_results = []
    elif fault == "changed_group":
        result.preparation_results[0].final_fingerprint = "changed"
    elif fault == "recipe":
        result.preparation_results[0].recipe_digest = "c" * 64
    elif fault == "warmup_failed":
        result.warmup_results[0].business_valid = False
    elif fault == "digest":
        result.warmup_results[0].result_digest = "c" * 64
    elif fault == "duplicate_request":
        result.warmup_results[0].request_id = result.observations[0].request_id
    elif fault == "missing_warmup_raw":
        result.warmup_results[0].evidence_refs = []
    elif fault == "naked_zero":
        result.observations[0].sql_calls[0].lock_evidence = None
    assert asyncio.run(evaluate(bundle, Reader()))[0].status == "lead"
