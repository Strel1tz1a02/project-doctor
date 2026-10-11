"""Deep-pagination diagnosis: OFFSET detection, three-way grading, and keyset proof."""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from project_doctor.features.diagnosis.deep_pagination import (
    check_deep_pagination,
    extract_limit_offset,
)
from project_doctor.features.experiments.interventions import parse_pagination_recipe
from project_doctor.models.common import EvidenceCheck, EvidenceRef
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.task import TaskBundle
from project_doctor.workflows.diagnose import evaluate

_FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[2] / "tests/contracts/fixtures/verified_slow_query.json"
    ).read_text("utf-8")
)

OFFSET_SQL = "SELECT * FROM orders WHERE status = 'PAID' ORDER BY id LIMIT 20 OFFSET 100000"
KEYSET_SQL = "SELECT * FROM orders WHERE status = 'PAID' AND id > 100000 ORDER BY id LIMIT 20"


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


def deep_pagination_bundle() -> TaskBundle:
    """A valid pagination experiment: baseline OFFSET deep page, keyset page-size scan."""
    case = copy.deepcopy(_FIXTURE)
    case["spec"]["variable"] = "pagination"
    case["spec"]["levels"] = ["baseline", "candidate_pagination"]
    case["bundle"]["hypotheses"][0]["kind"] = "deep_pagination"
    case["bundle"]["hypotheses"][0]["explanation"] = "deep_pagination_keyset"
    experiment = case["bundle"]["experiments"][0]
    for prep in experiment["preparation_results"]:
        if prep["level"] == "candidate_index":
            prep["level"] = "candidate_pagination"
    for warmup in experiment["warmup_results"]:
        if warmup["level"] == "candidate_index":
            warmup["level"] = "candidate_pagination"
    for obs in experiment["observations"]:
        if obs["level"] == "candidate_index":
            obs["level"] = "candidate_pagination"
        if obs["level"] == "baseline":
            obs["sql_calls"] = [_sql_call(f"{obs['id']}-page", OFFSET_SQL, 100.0, 100020, 20, 14)]
            obs["latency_ms"] = 105.0
        else:
            obs["sql_calls"] = [_sql_call(f"{obs['id']}-page", KEYSET_SQL, 10.0, 20, 20, 14)]
            obs["latency_ms"] = 15.0
    bundle = TaskBundle.model_validate(case["bundle"])
    bundle.experiments[0].spec = ExperimentSpec.model_validate(case["spec"])
    return bundle


def test_extract_limit_offset_parses_all_spellings() -> None:
    assert extract_limit_offset("SELECT 1 LIMIT 20 OFFSET 100000") == (20, 100000)
    assert extract_limit_offset("SELECT 1 LIMIT 100000, 20") == (20, 100000)
    assert extract_limit_offset("SELECT 1 LIMIT 20") == (20, 0)
    assert extract_limit_offset("SELECT 1") == (None, None)


def test_pagination_recipe_is_strict() -> None:
    recipe = parse_pagination_recipe(
        json.dumps(
            {
                "strategy": "keyset",
                "flag": "app.pagination.mode",
                "baseline_value": "offset",
                "candidate_value": "keyset",
                "sort_column": "id",
                "query_template": (
                    "SELECT * FROM orders WHERE status = ? ORDER BY id LIMIT ? OFFSET ?"
                ),
            }
        )
    )
    assert recipe.strategy == "keyset"
    assert recipe.baseline_value != recipe.candidate_value
    with pytest.raises(ValueError, match="strategy"):
        parse_pagination_recipe(
            json.dumps(
                {
                    "strategy": "seek",
                    "flag": "f",
                    "baseline_value": "a",
                    "candidate_value": "b",
                    "sort_column": "id",
                    "query_template": "SELECT 1",
                }
            )
        )
    with pytest.raises(ValueError, match="differ"):
        parse_pagination_recipe(
            json.dumps(
                {
                    "strategy": "keyset",
                    "flag": "f",
                    "baseline_value": "a",
                    "candidate_value": "a",
                    "sort_column": "id",
                    "query_template": "SELECT 1",
                }
            )
        )


def test_deep_pagination_verified_when_keyset_collapses_scan() -> None:
    bundle = deep_pagination_bundle()
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "verified"
    assert findings[0].kind == "deep_pagination"
    assert findings[0].fix_spec is not None
    assert findings[0].fix_spec.strategy == "keyset"
    assert findings[0].fix_spec.sort_column == "id"
    assert findings[0].fix_spec.observed_offset == 100000
    assert findings[0].recommendation is not None


def test_deep_pagination_lead_when_keyset_does_not_collapse() -> None:
    bundle = deep_pagination_bundle()
    # The candidate keyset group still emits the OFFSET query: the scan did not
    # collapse, so the intervention cannot prove the mechanism.
    for obs in bundle.experiments[0].observations:
        if obs.level == "candidate_pagination":
            obs.sql_calls = [_sql_call(f"{obs.id}-page", OFFSET_SQL, 100.0, 100020, 20, 14)]
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "lead"
    assert findings[0].fix_spec is not None
    assert any("扫描量" in reason for reason in findings[0].limitations)


def test_no_offset_is_unclassified() -> None:
    bundle = deep_pagination_bundle()
    for obs in bundle.experiments[0].observations:
        if obs.level == "baseline":
            obs.sql_calls = [
                _sql_call(
                    f"{obs.id}-page",
                    "SELECT * FROM orders WHERE status = 'PAID' ORDER BY id LIMIT 20",
                    5.0,
                    20,
                    20,
                    14,
                )
            ]
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "unclassified"
    assert findings[0].recommendation is None
    assert findings[0].fix_spec is None


def test_full_scan_dominance_is_lead() -> None:
    bundle = deep_pagination_bundle()
    # rows_examined == the whole table, far beyond offset + page size: the OFFSET
    # cost is drowned by a full-table scan, so it cannot be cleanly attributed.
    for obs in bundle.experiments[0].observations:
        if obs.level == "baseline":
            obs.sql_calls = [_sql_call(f"{obs.id}-page", OFFSET_SQL, 200.0, 200000, 20, 14)]
    findings = asyncio.run(evaluate(bundle, Reader()))
    assert findings[0].status == "lead"
    assert any("整表扫描" in reason for reason in findings[0].limitations)


def test_missing_code_location_is_lead() -> None:
    bundle = deep_pagination_bundle()
    for obs in bundle.experiments[0].observations:
        if obs.level == "baseline":
            for call in obs.sql_calls:
                call.code_location = None
    result = bundle.experiments[0]
    findings = check_deep_pagination(
        result, bundle.scenarios[0], bundle.task.id, bundle.task.project.commit
    )
    assert findings[0].status == "lead"


def test_deep_pagination_hypothesis_becomes_supported_when_verified() -> None:
    from project_doctor.workflows.tools import ToolWorkflows
    from tests.diagnosis.fakes import MemoryStore, ScriptedReader, ScriptedRuntime

    bundle = deep_pagination_bundle()
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
