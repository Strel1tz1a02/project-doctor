"""MySQL TaskStore: secret resolution (pure logic) and DB round-trip (skips without DSN)."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest

from project_doctor.entrypoints.settings import Settings
from project_doctor.integrations.mysql.factory import build_store, resolve_secret_ref
from project_doctor.models.common import EvidenceRef, Limits, Usage
from project_doctor.models.dataset import DatasetProfile
from project_doctor.models.environment import EnvironmentHandle, ProjectInput
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.finding import Finding, Impact, ReportResult
from project_doctor.models.hypothesis import Hypothesis
from project_doctor.models.scenario import (
    Assertions,
    BusinessAssertion,
    CacheProfile,
    LoadProfile,
    RequestStep,
    Scenario,
)
from project_doctor.models.task import CallContext, OperationResult, TaskBundle, TaskRecord

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
    task = make_task("store-round-trip-" + uuid.uuid4().hex)
    asyncio.run(store.create(task))
    assert asyncio.run(store.get(task.id)) == task

    # transition is race-safe on the status column
    assert asyncio.run(store.transition(task.id, "created", "running")) is True
    assert asyncio.run(store.transition(task.id, "created", "blocked")) is False
    assert asyncio.run(store.get(task.id)).status == "running"

    # child records upsert and appear in the bundle
    asyncio.run(store.save_scenario(task.id, make_scenario()))
    asyncio.run(store.save_hypotheses(task.id, [make_hypothesis()]))
    asyncio.run(store.save_findings(task.id, [make_finding(task_id=task.id)]))

    # reserve -> finish with an environment handle, then reload
    reservation = asyncio.run(store.reserve(task.id, "op:prepare", "a" * 64, 10))
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
        store.finish_operation(task.id, "op:prepare", result, Usage(wall_seconds=5.0, requests=3))
    )

    assert asyncio.run(store.load_operation(task.id, "op:prepare")) == result

    record = asyncio.run(store.get(task.id))
    assert record.environment_id == "environment-1"
    assert record.status == "running"
    assert record.usage.wall_seconds == 5.0
    assert record.usage.requests == 3

    bundle = asyncio.run(store.load_bundle(task.id))
    assert [item.id for item in bundle.scenarios] == ["scenario-1"]
    assert [item.id for item in bundle.hypotheses] == ["hypothesis-1"]
    assert [item.id for item in bundle.findings] == ["finding-1"]
    assert bundle.task.environment_id == "environment-1"


def test_experiment_lock_windows_round_trip_through_mysql_json(store) -> None:
    fixture = Path(__file__).resolve().parents[2] / "contracts/fixtures/verified_slow_query.json"
    case = json.loads(fixture.read_text(encoding="utf-8"))
    bundle = TaskBundle.model_validate(case["bundle"])
    result = bundle.experiments[0]
    task_id = "json-window-" + uuid.uuid4().hex
    task = make_task(task_id)
    result.spec = ExperimentSpec.model_validate(case["spec"])
    result.spec.task_id = task_id
    operation_id = "json-lock-window"
    result.operation_id = operation_id
    operation = OperationResult(
        operation_id=operation_id, state="completed", input_digest="b" * 64, payload=result
    )
    asyncio.run(store.create(task))
    assert asyncio.run(store.reserve(task_id, operation_id, "b" * 64, 0)).accepted
    asyncio.run(store.finish_operation(task_id, operation_id, operation, Usage(experiments=1)))
    loaded = asyncio.run(store.load_operation(task_id, operation_id))
    assert loaded == operation
    persisted = asyncio.run(store.load_bundle(task_id)).experiments[0]
    assert persisted == result
    assert persisted.observations[0].sql_calls[0].lock_evidence.window_start.tzinfo is not None


def test_terminal_report_can_be_loaded_with_another_operation_id(store) -> None:
    task = make_task("report-replay-" + uuid.uuid4().hex)
    ref = EvidenceRef(
        artifact_id="report-json-" + task.id,
        relative_path=f"tasks/{task.id}/report.json",
        media_type="application/json",
        format_version="report.v1",
        sha256="a" * 64,
        size_bytes=1,
    )
    report = ReportResult(
        task_id=task.id,
        task_status="completed",
        json_ref=ref,
        html_ref=ref.model_copy(
            update={
                "artifact_id": "report-html-" + task.id,
                "relative_path": f"tasks/{task.id}/report.html",
                "media_type": "text/html",
            }
        ),
    )
    asyncio.run(store.create(task))
    assert asyncio.run(store.load_report(task.id)) is None
    assert asyncio.run(store.reserve(task.id, "finish:report", "c" * 64, 0)).accepted
    asyncio.run(
        store.finish_operation(
            task.id,
            "finish:report",
            OperationResult(
                operation_id="finish:report",
                state="completed",
                input_digest="c" * 64,
                payload=report,
            ),
            Usage(),
        )
    )
    # A report for another state is not replayed until the terminal transition.
    assert asyncio.run(store.load_report(task.id)) is None
    assert asyncio.run(store.transition(task.id, "created", "completed"))
    assert asyncio.run(store.load_report(task.id)) == report


def test_parallel_preparations_with_different_ids_are_serialized(store, monkeypatch) -> None:
    import hashlib
    import threading

    task = make_task("prepare-race-" + uuid.uuid4().hex)
    digest = hashlib.sha256(task.project.model_dump_json().encode("utf-8")).hexdigest()
    barrier = threading.Barrier(2)
    original_load = store._load_task

    def read_before_lock(conn, task_id):
        record = original_load(conn, task_id)
        # Both REPEATABLE READ snapshots exist before either task lock is taken.
        # The pending operation lookup must be a current read after serialization.
        barrier.wait(timeout=10)
        return record

    monkeypatch.setattr(store, "_load_task", read_before_lock)

    async def run():
        await store.create(task)
        results = await asyncio.gather(
            store.reserve(task.id, "prepare-1", digest, 0),
            store.reserve(task.id, "prepare-2", digest, 0),
        )
        assert sum(result.accepted for result in results) == 1
        assert any("unresolved" in (result.reason or "") for result in results)

    asyncio.run(run())


def test_parallel_finishers_settle_an_operation_only_once(store) -> None:
    task = make_task("settle-race-" + uuid.uuid4().hex)
    operation_id = "finish:close"
    from project_doctor.models.environment import RestoreResult

    operation = OperationResult(
        operation_id=operation_id,
        state="completed",
        input_digest="d" * 64,
        payload=RestoreResult(verified=False, reason="settlement concurrency control"),
    )

    async def run():
        await store.create(task)
        assert (await store.reserve(task.id, operation_id, "d" * 64, 1)).accepted
        await asyncio.gather(
            store.finish_operation(task.id, operation_id, operation, Usage(requests=1)),
            store.finish_operation(task.id, operation_id, operation, Usage(requests=1)),
        )
        assert (await store.get(task.id)).usage.requests == 1
        assert await store.load_operation(task.id, operation_id) == operation

    asyncio.run(run())
