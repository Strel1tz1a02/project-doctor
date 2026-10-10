"""N+1 diagnosis: structure detection, three-way grading, and batch-intervention proof."""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from project_doctor.features.diagnosis.n_plus_one import check_n_plus_one
from project_doctor.features.diagnosis.sql_shape import extract_sql_literals, parameterize_sql
from project_doctor.features.experiments.interventions import parse_query_shape_recipe
from project_doctor.models.common import EvidenceCheck, EvidenceRef
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.task import TaskBundle
from project_doctor.workflows.diagnose import evaluate

_FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[2] / "tests/contracts/fixtures/verified_slow_query.json"
    ).read_text("utf-8")
)

PARENT_SQL = "SELECT * FROM orders WHERE email LIKE '%user1%' AND status = 'PAID' LIMIT 20 OFFSET 0"


class Reader:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid

    async def verify(self, refs: list[EvidenceRef]) -> EvidenceCheck:
        return EvidenceCheck(
            valid=self.valid, missing_ids=[] if self.valid else [refs[0].artifact_id]
        )


def _template_call() -> dict:
    return copy.deepcopy(
        _FIXTURE["bundle"]["experiments"][0]["observations"][0]["sql_calls"][0]
    )


def _sql_call(
    call_id: str, sql: str, duration_ms: float, rows_examined: int, rows_returned: int, line: int
) -> dict:
    call = _template_call()
    call["id"] = call_id
    call["normalized_sql"] = sql
    call["duration_ms"] = duration_ms
    call["rows_examined"] = rows_examined
    call["rows_returned"] = rows_returned
    call["code_location"]["line"] = line
    return call


def _baseline_calls(obs_id: str) -> list[dict]:
    calls = [_sql_call(f"{obs_id}-parent", PARENT_SQL, 100.0, 10000, 20, 12)]
    calls.extend(
        _sql_call(f"{obs_id}-child-{i}", f"SELECT * FROM users WHERE id = {i}", 0.5, 1, 1, 40)
        for i in range(1, 21)
    )
    return calls


def _batch_calls(obs_id: str) -> list[dict]:
    return [
        _sql_call(f"{obs_id}-parent", PARENT_SQL, 10.0, 10000, 20, 12),
        _sql_call(
            f"{obs_id}-batch",
            "SELECT * FROM users WHERE id IN (" + ",".join(str(i) for i in range(1, 21)) + ")",
            5.0,
            20,
            20,
            40,
        ),
    ]


def n_plus_one_bundle() -> TaskBundle:
    """A valid query_shape experiment: baseline 1 parent + 20 children, batch 1 parent + 1 IN."""
    case = copy.deepcopy(_FIXTURE)
    case["spec"]["variable"] = "query_shape"
    case["spec"]["levels"] = ["baseline", "candidate_batch"]
    case["bundle"]["hypotheses"][0]["kind"] = "n_plus_one"
    case["bundle"]["hypotheses"][0]["explanation"] = "n_plus_one_batch"
    experiment = case["bundle"]["experiments"][0]
    for prep in experiment["preparation_results"]:
        if prep["level"] == "candidate_index":
            prep["level"] = "candidate_batch"
    for warmup in experiment["warmup_results"]:
        if warmup["level"] == "candidate_index":
            warmup["level"] = "candidate_batch"
    for obs in experiment["observations"]:
        if obs["level"] == "candidate_index":
            obs["level"] = "candidate_batch"
        if obs["level"] == "baseline":
            obs["sql_calls"] = _baseline_calls(obs["id"])
            obs["latency_ms"] = 105.0
        else:
            obs["sql_calls"] = _batch_calls(obs["id"])
            obs["latency_ms"] = 15.0
    bundle = TaskBundle.model_validate(case["bundle"])
    bundle.experiments[0].spec = ExperimentSpec.model_validate(case["spec"])
    return bundle


def test_parameterize_sql_normalizes_literals_only() -> None:
    assert parameterize_sql("SELECT * FROM users WHERE id = 123") == (
        "SELECT * FROM users WHERE id = ?"
    )
    assert parameterize_sql("SELECT * FROM users WHERE name = 'alice'") == (
        "SELECT * FROM users WHERE name = ?"
    )
    assert parameterize_sql("SELECT * FROM users WHERE id IN (1, 2, 3)") == (
        "SELECT * FROM users WHERE id IN (?, ?, ?)"
    )
    assert parameterize_sql("SELECT col_1 FROM t1") == "SELECT col_1 FROM t1"


def test_extract_sql_literals_orders_strings_then_numbers() -> None:
    assert extract_sql_literals("SELECT * FROM users WHERE name = 'alice' AND id = 7") == [
        "alice",
        "7",
    ]


def test_query_shape_recipe_is_strict() -> None:
    recipe = parse_query_shape_recipe(
        json.dumps(
            {
                "strategy": "batch_in",
                "flag": "app.query.mode",
                "baseline_value": "n1",
                "candidate_value": "batch",
                "child_template": "SELECT * FROM users WHERE id = ?",
                "key_column": "id",
            }
        )
    )
    assert recipe.strategy == "batch_in"
    assert recipe.baseline_value != recipe.candidate_value
    with pytest.raises(ValueError, match="strategy"):
        parse_query_shape_recipe(
            json.dumps(
                {
                    "strategy": "merge",
                    "flag": "f",
                    "baseline_value": "a",
                    "candidate_value": "b",
                    "child_template": "SELECT 1",
                    "key_column": "id",
                }
            )
        )
    with pytest.raises(ValueError, match="differ"):
        parse_query_shape_recipe(
            json.dumps(
                {
                    "strategy": "batch_in",
                    "flag": "f",
                    "baseline_value": "a",
                    "candidate_value": "a",
                    "child_template": "SELECT 1",
                    "key_column": "id",
                }
            )
        )


def test_n_plus_one_verified_when_batch_collapses_loop() -> None:
    bundle = n_plus_one_bundle()
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "verified"
    assert findings[0].kind == "n_plus_one"
    assert findings[0].fix_spec is not None
    assert findings[0].fix_spec.strategy == "batch_in"
    assert findings[0].fix_spec.key_column == "id"
    assert findings[0].fix_spec.observed_child_count == 20
    assert findings[0].recommendation is not None


def test_n_plus_one_lead_when_batch_does_not_collapse() -> None:
    bundle = n_plus_one_bundle()
    # The candidate batch still issues the same 20 child queries: the loop did not
    # collapse, so the intervention cannot prove the mechanism.
    for obs in bundle.experiments[0].observations:
        if obs.level == "candidate_batch":
            obs.sql_calls = _baseline_calls(obs.id)
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "lead"
    assert any("查询次数" in reason for reason in findings[0].limitations)


def test_single_query_is_unclassified() -> None:
    bundle = n_plus_one_bundle()
    for obs in bundle.experiments[0].observations:
        if obs.level == "baseline":
            obs.sql_calls = [_sql_call(f"{obs.id}-parent", PARENT_SQL, 100.0, 10000, 20, 12)]
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "unclassified"
    assert findings[0].recommendation is None
    assert findings[0].fix_spec is None


def test_cross_request_homogeneous_is_not_n_plus_one() -> None:
    bundle = n_plus_one_bundle()
    # One child per request (same template across requests, never repeated within one).
    for obs in bundle.experiments[0].observations:
        if obs.level == "baseline":
            obs.sql_calls = [
                _sql_call(f"{obs.id}-parent", PARENT_SQL, 100.0, 10000, 20, 12),
                _sql_call(f"{obs.id}-child", "SELECT * FROM users WHERE id = 1", 0.5, 1, 1, 40),
            ]
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "unclassified"


def test_child_without_distinct_literals_is_lead() -> None:
    bundle = n_plus_one_bundle()
    for obs in bundle.experiments[0].observations:
        if obs.level == "baseline":
            calls = _baseline_calls(obs.id)
            for call in calls[1:]:
                call["normalized_sql"] = "SELECT * FROM users WHERE id = 7"
            obs.sql_calls = calls
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "lead"
    assert any("互异" in reason for reason in findings[0].limitations)


def test_child_without_parent_is_lead() -> None:
    bundle = n_plus_one_bundle()
    for obs in bundle.experiments[0].observations:
        if obs.level == "baseline":
            obs.sql_calls = _baseline_calls(obs.id)[1:]  # children only, no parent link
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "lead"
    assert any("父查询" in reason for reason in findings[0].limitations)


def test_missing_child_code_location_is_lead() -> None:
    bundle = n_plus_one_bundle()
    for obs in bundle.experiments[0].observations:
        if obs.level == "baseline":
            for call in obs.sql_calls[1:]:
                call.code_location = None
    result = bundle.experiments[0]
    findings = check_n_plus_one(
        result, bundle.scenarios[0], bundle.task.id, bundle.task.project.commit
    )
    assert findings[0].status == "lead"


def test_n_plus_one_hypothesis_becomes_supported_when_verified() -> None:
    from project_doctor.workflows.tools import ToolWorkflows
    from tests.diagnosis.fakes import MemoryStore, ScriptedReader, ScriptedRuntime

    bundle = n_plus_one_bundle()
    bundle.task.status = "running"
    store = MemoryStore(bundle)
    runtime = ScriptedRuntime(store)
    workflows = ToolWorkflows(
        runtime, store, ScriptedReader(), {"scenarios": [bundle.scenarios[0].model_dump()]}
    )
    result = asyncio.run(
        workflows.evaluate_evidence(bundle.task.correlation, ["hypothesis-1"], ["experiment-1"])
    )
    assert result[0].status == "verified"
    assert store.bundle.hypotheses[0].status == "supported"
