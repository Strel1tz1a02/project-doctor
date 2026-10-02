"""MySQL TaskStore: secret resolution (pure logic) and DB round-trip (skips without DSN)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from project_doctor.entrypoints.settings import Settings
from project_doctor.integrations.mysql.factory import build_store, resolve_secret_ref
from project_doctor.models.common import Limits, Usage
from project_doctor.models.dataset import DatasetProfile
from project_doctor.models.environment import EnvironmentHandle, ProjectInput
from project_doctor.models.finding import Finding, Impact
from project_doctor.models.hypothesis import Hypothesis
from project_doctor.models.scenario import (
    Assertions,
    BusinessAssertion,
    CacheProfile,
    LoadProfile,
    RequestStep,
    Scenario,
)
from project_doctor.models.task import CallContext, OperationResult, TaskRecord

DSN_ENV = "PROJECT_DOCTOR_PLATFORM_DSN"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        platform_dsn_ref="env:PROJECT_DOCTOR_PLATFORM_DSN",
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "isolated",
        target_repo_root=tmp_path / "target",
        allowed_target_network="172.28.0.0/24",
        tool_timeouts={"run_experiment": 120},
        model_config_ref="file:agh/model.local.json",
    )


def make_task(task_id: str = "task-1") -> TaskRecord:
    return TaskRecord(
        id=task_id,
        project=ProjectInput(
            repo_path="git@github.com:example/demo.git",
            commit="c0ffee" * 8,
            supplied_url="http://service:8000",
            recipe_ref="recipes/slow-query.json",
        ),
        status="created",
        limits=Limits(
            max_wall_seconds=3600,
            max_requests=100,
            max_experiments=10,
            max_artifact_bytes=100_000_000,
            restore_reserve_seconds=300,
        ),
        usage=Usage(),
        correlation=CallContext(
            task_id=task_id,
            operation_id="op:create",
            agh_session_id="session-1",
            tool_call_id="call-1",
        ),
    )


def make_scenario(scenario_id: str = "scenario-1") -> Scenario:
    return Scenario(
        id=scenario_id,
        version=1,
        source="user_sample",
        purpose="slow-query-checkout",
        preparation_recipe_ref="recipes/prep.json",
        steps=[
            RequestStep(
                method="GET",
                relative_path="/orders",
                assertions=Assertions(
                    status_code=200,
                    business=[BusinessAssertion(json_pointer="/count", operator="exists")],
                ),
            )
        ],
        dataset=DatasetProfile(
            id="ds-1",
            snapshot_id="snapshot-1",
            source="synthetic",
            row_counts={"orders": 1000},
        ),
        load=LoadProfile(mode="serial"),
        cache=CacheProfile(state="cold"),
    )


def make_hypothesis(hypothesis_id: str = "hypothesis-1") -> Hypothesis:
    return Hypothesis(
        id=hypothesis_id,
        kind="slow_query",
        explanation="full table scan on orders",
        predictions=["candidate scans fewer rows"],
        falsifiers=["baseline and candidate scan the same rows"],
        status="proposed",
    )


def make_finding(finding_id: str = "finding-1", task_id: str = "task-1") -> Finding:
    return Finding(
        id=finding_id,
        task_id=task_id,
        kind="slow_query",
        status="lead",
        scenario_id="scenario-1",
        impact=Impact(method="unmeasured"),
    )


# -- pure logic: resolve_secret_ref ----------------------------------------


def test_resolve_env_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DSN_ENV, "mysql+pymysql://user:pass@db/test")
    assert resolve_secret_ref(f"env:{DSN_ENV}") == "mysql+pymysql://user:pass@db/test"


def test_resolve_env_ref_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DSN_ENV, raising=False)
    with pytest.raises(RuntimeError, match="not set"):
        resolve_secret_ref(f"env:{DSN_ENV}")


def test_resolve_file_ref(tmp_path: Path) -> None:
    secret = tmp_path / "dsn.txt"
    secret.write_text("mysql+pymysql://u:p@db/test\n", encoding="utf-8")
    assert resolve_secret_ref(f"file:{secret}") == "mysql+pymysql://u:p@db/test"


def test_resolve_file_ref_missing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="not readable"):
        resolve_secret_ref(f"file:{tmp_path / 'nope.txt'}")


def test_resolve_file_ref_empty(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="empty"):
        resolve_secret_ref(f"file:{empty}")


def test_resolve_rejects_bare_secret() -> None:
    with pytest.raises(ValueError, match="env: or file:"):
        resolve_secret_ref("mysql+pymysql://u:p@db/test")


def test_fixtures_construct() -> None:
    assert make_task().id == "task-1"
    assert make_scenario().id == "scenario-1"
    assert make_hypothesis().id == "hypothesis-1"
    assert make_finding().id == "finding-1"


# -- DB round-trip (skips without PROJECT_DOCTOR_PLATFORM_DSN; 未验证) ------


@pytest.fixture
def store(tmp_path: Path):
    if DSN_ENV not in os.environ:
        pytest.skip("PROJECT_DOCTOR_PLATFORM_DSN not set; MySQL round-trip not run (未验证)")
    return build_store(make_settings(tmp_path))


def test_store_round_trip(store) -> None:
    task = make_task()
    asyncio.run(store.create(task))
    assert asyncio.run(store.get("task-1")) == task

    # transition is race-safe on the status column
    assert asyncio.run(store.transition("task-1", "created", "running")) is True
    assert asyncio.run(store.transition("task-1", "created", "blocked")) is False
    assert asyncio.run(store.get("task-1")).status == "running"

    # child records upsert and appear in the bundle
    asyncio.run(store.save_scenario("task-1", make_scenario()))
    asyncio.run(store.save_hypotheses("task-1", [make_hypothesis()]))
    asyncio.run(store.save_findings("task-1", [make_finding()]))

    # reserve -> finish with an environment handle, then reload
    reservation = asyncio.run(store.reserve("task-1", "op:prepare", "a" * 64, 10))
    assert reservation.accepted
    result = OperationResult(
        operation_id="op:prepare",
        state="completed",
        input_digest="a" * 64,
        payload=EnvironmentHandle(
            id="environment-1",
            isolated_base_url="http://isolated:8001",
            fingerprint="fingerprint-baseline",
            baseline_snapshot_id="snapshot-1",
            health="available",
        ),
    )
    asyncio.run(
        store.finish_operation("task-1", "op:prepare", result, Usage(wall_seconds=5.0, requests=3))
    )

    assert asyncio.run(store.load_operation("task-1", "op:prepare")) == result

    record = asyncio.run(store.get("task-1"))
    assert record.environment_id == "environment-1"
    assert record.status == "running"
    assert record.usage.wall_seconds == 5.0
    assert record.usage.requests == 3

    bundle = asyncio.run(store.load_bundle("task-1"))
    assert [item.id for item in bundle.scenarios] == ["scenario-1"]
    assert [item.id for item in bundle.hypotheses] == ["hypothesis-1"]
    assert [item.id for item in bundle.findings] == ["finding-1"]
    assert bundle.task.environment_id == "environment-1"
