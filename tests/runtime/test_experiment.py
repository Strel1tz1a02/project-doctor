"""Unit tests for A3 experiment logic: recipe, validation, comparison and actual metrics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from project_doctor.features.experiments.compare import compare, summarize
from project_doctor.features.experiments.interventions import IndexRecipe, parse_index_recipe
from project_doctor.features.experiments.validate import validate_experiment
from project_doctor.integrations.observation.execution_stats import (
    RawExecutionStats,
    apply_actual_metrics,
)
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.observation import SqlCall
from project_doctor.models.task import TaskBundle

FIXTURES = Path(__file__).resolve().parents[1] / "contracts" / "fixtures"


def load_case(name: str = "verified_slow_query") -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def load_bundle_and_spec(name: str = "verified_slow_query") -> tuple[TaskBundle, ExperimentSpec]:
    case = load_case(name)
    bundle = TaskBundle.model_validate(case["bundle"])
    # The fixture is a finished task, so reset its experiment usage to leave budget headroom.
    bundle.task.usage.experiments = 0
    return bundle, ExperimentSpec.model_validate(case["spec"])


# --- index recipe validation -------------------------------------------------


def test_parse_basic_index_recipe() -> None:
    recipe = parse_index_recipe("CREATE INDEX idx_users_email ON users (email)")
    assert recipe == IndexRecipe(name="idx_users_email", table="users", columns=("email",))
    assert recipe.create_sql == "CREATE INDEX idx_users_email ON users (email)"
    assert recipe.drop_sql == "DROP INDEX idx_users_email ON users"


def test_parse_unique_multi_column_and_semicolon() -> None:
    recipe = parse_index_recipe("CREATE UNIQUE INDEX u ON t (a, b);")
    assert recipe.unique is True
    assert recipe.columns == ("a", "b")
    assert recipe.create_sql == "CREATE UNIQUE INDEX u ON t (a, b)"


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE users",
        "ALTER TABLE users ADD COLUMN x INT",
        "CREATE INDEX i ON t (a); DROP TABLE t",
        "CREATE INDEX i ON t (a) -- comment",
        "CREATE INDEX i ON t (a); /* evil */",
        "CREATE INDEX i ON t (a) WHERE a > 0",
        "CREATE INDEX i ON t (a)) OR 1=1 --",
        "CREATE INDEX i ON t (a); SELECT 1",
    ],
)
def test_reject_arbitrary_ddl(sql: str) -> None:
    with pytest.raises(ValueError):
        parse_index_recipe(sql)


# --- experiment pre-flight validation ---------------------------------------


def test_validate_accepts_consistent_spec() -> None:
    bundle, spec = load_bundle_and_spec()
    assert validate_experiment(spec, bundle.scenarios[0], bundle.task) == []


def test_validate_rejects_foreign_task() -> None:
    bundle, spec = load_bundle_and_spec()
    foreign = spec.model_copy(update={"task_id": "other-task"})
    failures = validate_experiment(foreign, bundle.scenarios[0], bundle.task)
    assert [failure.code for failure in failures] == ["scenario_invalid"]


def test_validate_rejects_unknown_hypothesis() -> None:
    bundle, spec = load_bundle_and_spec()
    unknown = spec.model_copy(update={"hypothesis_ids": ["hypothesis-2"]})
    failures = validate_experiment(unknown, bundle.scenarios[0], bundle.task)
    assert "scenario_invalid" in [failure.code for failure in failures]


def test_validate_rejects_exhausted_budget() -> None:
    bundle, spec = load_bundle_and_spec()
    usage = bundle.task.usage.model_copy(update={"experiments": bundle.task.limits.max_experiments})
    task = bundle.task.model_copy(update={"usage": usage})
    failures = validate_experiment(spec, bundle.scenarios[0], task)
    assert "budget_exhausted" in [failure.code for failure in failures]


# --- experiment comparison ---------------------------------------------------


def test_compare_groups_by_level_with_positive_deltas() -> None:
    bundle, spec = load_bundle_and_spec()
    comparison = compare(bundle.experiments[0].observations)
    assert comparison.baseline.repetitions == spec.repetitions == 3
    assert comparison.candidate_index.repetitions == spec.repetitions
    assert comparison.rows_examined_delta > 0
    assert comparison.sql_duration_delta_ms > 0
    assert comparison.latency_delta_ms > 0


def test_summarize_separates_groups() -> None:
    bundle, _ = load_bundle_and_spec()
    baseline = summarize(bundle.experiments[0].observations, "baseline")
    candidate = summarize(bundle.experiments[0].observations, "candidate_index")
    assert baseline.latency_ms == (105.0, 105.0, 105.0)
    assert candidate.latency_ms == (15.0, 15.0, 15.0)
    assert baseline.median_rows_examined == 10000.0
    assert candidate.median_rows_examined == 10.0


# --- actual metric assembly --------------------------------------------------


def test_apply_full_actual_metrics() -> None:
    call = SqlCall(id="sql-1", normalized_sql="SELECT 1")
    stats = RawExecutionStats(
        source_id="perf-schema",
        evidence_id="stat-1",
        duration_ms=12.5,
        rows_examined=100,
        rows_returned=1,
        lock_wait_ms=0.0,
    )
    updated = apply_actual_metrics(call, stats)
    assert updated.duration_ms == 12.5
    assert updated.rows_examined == 100
    assert updated.rows_returned == 1
    assert updated.lock_wait_ms == 0.0
    assert set(updated.metric_sources) == {
        "duration_ms",
        "rows_examined",
        "rows_returned",
        "lock_wait_ms",
    }
    assert all(source.measurement == "actual" for source in updated.metric_sources.values())
    assert all(source.evidence_ids == ["stat-1"] for source in updated.metric_sources.values())


def test_apply_partial_metrics_keeps_missing_null() -> None:
    call = SqlCall(id="sql-2", normalized_sql="SELECT 2")
    stats = RawExecutionStats(source_id="perf-schema", evidence_id="stat-2", duration_ms=5.0)
    updated = apply_actual_metrics(call, stats)
    assert updated.duration_ms == 5.0
    assert updated.rows_examined is None and "rows_examined" not in updated.metric_sources
    assert updated.lock_wait_ms is None and "lock_wait_ms" not in updated.metric_sources
    SqlCall.model_validate_json(updated.model_dump_json())
