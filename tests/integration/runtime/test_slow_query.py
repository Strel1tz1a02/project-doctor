"""A3 measurement orchestration against scripted gateway, store and HTTP doubles.

No Docker, MySQL or network is touched: the RuntimeService is exercised through its
fakes to prove reservation, two-level measurement, budget checks and restoration.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.environments.ports import PreparedEnvironment, RestoredState
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.integrations.http.requests import HttpResponse, RestrictedHttpClient
from project_doctor.integrations.mysql.migrations.schema import create_schema, environment_health
from project_doctor.integrations.observation.sql_probe import SqlCollection
from project_doctor.integrations.runtime_factory import RuntimeService
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.task import (
    CallContext,
    OperationResult,
    Reservation,
    TaskBundle,
    TaskRecord,
)

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


def load_bundle_and_spec() -> tuple[TaskBundle, ExperimentSpec]:
    case = json.loads((FIXTURES / "verified_slow_query.json").read_text(encoding="utf-8"))
    bundle = TaskBundle.model_validate(case["bundle"])
    bundle.task.usage.experiments = 0
    bundle.task.usage.requests = 0
    spec = ExperimentSpec.model_validate(case["spec"])
    spec.warmup = None  # These tests cover the legacy execution path.
    return bundle, spec


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        platform_dsn_ref="env:PROJECT_DOCTOR_PLATFORM_DSN",
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "isolated",
        target_repo_root=tmp_path / "target",
        allowed_target_network="172.28.0.0/24",
        tool_timeouts={"run_experiment": 120, "prepare_environment": 120},
        model_config_ref="file:agh/model.local.json",
    )


class FakeStore:
    def __init__(self, task: TaskRecord) -> None:
        self.task = task
        self.results: dict[str, OperationResult] = {}
        self.consumed: object | None = None

    async def get(self, task_id: str) -> TaskRecord:
        return self.task

    async def reserve(
        self, task_id: str, operation_id: str, input_digest: str, request_allowance: int
    ) -> Reservation:
        if operation_id in self.results:
            return Reservation(accepted=False, replay_result=self.results[operation_id])
        return Reservation(accepted=True)

    async def finish_operation(
        self, task_id: str, operation_id: str, result: OperationResult, consumed: object
    ) -> None:
        self.results[operation_id] = result
        self.consumed = consumed


class FakeGateway:
    def __init__(self) -> None:
        self.sql_applied: list[str] = []
        self.restore_calls = 0

    async def prepare(self, project: object, context: CallContext) -> PreparedEnvironment:
        return PreparedEnvironment(
            environment_id="environment-1",
            isolated_base_url="http://127.0.0.1:18080",
            fingerprint="fingerprint-baseline",
            baseline_snapshot_id="snapshot-1",
            baseline_dump=b"baseline",
        )

    async def restore(
        self, environment_id: str, snapshot_id: str, context: CallContext, baseline_dump: bytes
    ) -> RestoredState:
        self.restore_calls += 1
        return RestoredState(
            verified=True,
            fingerprint=None,
            snapshot_id=snapshot_id,
            index_removed=True,
            reason=None,
            restored_dump=b"restored",
        )

    async def fingerprint(self, environment_id: str, context: CallContext, commit: str) -> str:
        return "fingerprint-candidate" if self.sql_applied else "fingerprint-baseline"

    async def health(self, task_id: str) -> str:
        return "available"

    async def teardown(self, environment_id: str, context: CallContext) -> None:
        pass

    async def execute_sql(self, environment_id: str, context: CallContext, sql: str) -> None:
        self.sql_applied.append(sql)


def seed_environment(engine, task_id: str = "task-1") -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(environment_health).values(
                task_id=task_id,
                health="available",
                environment_id="environment-1",
                fingerprint="fingerprint-baseline",
                baseline_snapshot_id="snapshot-1",
            )
        )


def write_baseline(settings: Settings) -> None:
    path = settings.artifact_root / "tasks" / "task-1" / "environment" / "environment-1"
    path.mkdir(parents=True, exist_ok=True)
    (path / "baseline.sql").write_bytes(b"baseline")


def write_recipe(settings: Settings) -> None:
    recipes = settings.target_repo_root / "recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    (recipes / "customer-index.sql").write_text(
        "CREATE INDEX idx_customer ON orders (customer_id)", encoding="utf-8"
    )


def build_runtime(
    tmp_path: Path, task: TaskRecord
) -> tuple[RuntimeService, FakeGateway, FakeStore]:
    settings = make_settings(tmp_path)
    engine = create_engine(f"sqlite:///{tmp_path / 'state.db'}")
    create_schema(engine)
    seed_environment(engine)
    write_baseline(settings)
    write_recipe(settings)
    store = FakeStore(task)
    gateway = FakeGateway()
    runtime = RuntimeService(settings, store, engine, gateway)
    return runtime, gateway, store


def context(operation_id: str) -> CallContext:
    return CallContext(
        task_id="task-1",
        operation_id=operation_id,
        missing_correlation=["agh_session_id", "tool_call_id"],
    )


def test_run_measures_both_levels_and_restores(tmp_path: Path, monkeypatch) -> None:
    bundle, spec = load_bundle_and_spec()
    runtime, gateway, store = build_runtime(tmp_path, bundle.task)

    async def fake_request(self, step: object) -> HttpResponse:
        return HttpResponse(
            status_code=200, body={"items": [1, 2, 3]}, latency_ms=105.0, headers={}
        )

    monkeypatch.setattr(RestrictedHttpClient, "request", fake_request)

    result = asyncio.run(runtime.run("environment-1", bundle.scenarios[0], spec, context("op-run")))

    assert result.phase == "finished"
    assert len(result.observations) == 6
    baseline = [o for o in result.observations if o.level == "baseline"]
    candidate = [o for o in result.observations if o.level == "candidate_index"]
    assert len(baseline) == len(candidate) == 3
    assert gateway.sql_applied == ["CREATE INDEX idx_customer ON orders (customer_id)"]
    assert gateway.restore_calls == 1
    assert result.restore_result is not None and result.restore_result.verified
    assert all(o.business_valid for o in result.observations)
    assert "op-run" in store.results


def test_run_rejects_when_request_budget_exhausted(tmp_path: Path) -> None:
    bundle, spec = load_bundle_and_spec()
    bundle.task.usage.requests = 7
    runtime, _, store = build_runtime(tmp_path, bundle.task)

    result = asyncio.run(
        runtime.run("environment-1", bundle.scenarios[0], spec, context("op-budget"))
    )

    assert result.failure is not None
    assert result.failure.code == "budget_exhausted"
    assert result.observations == []
    assert "op-budget" not in store.results


def test_run_rejects_foreign_environment(tmp_path: Path) -> None:
    bundle, spec = load_bundle_and_spec()
    runtime, _, _ = build_runtime(tmp_path, bundle.task)

    result = asyncio.run(
        runtime.run("other-environment", bundle.scenarios[0], spec, context("op-foreign"))
    )

    assert result.failure is not None and result.failure.code == "environment_blocked"


def test_run_preserves_partial_observations_and_still_restores(tmp_path: Path, monkeypatch) -> None:
    bundle, spec = load_bundle_and_spec()
    runtime, gateway, _ = build_runtime(tmp_path, bundle.task)
    calls = {"n": 0}

    async def flaky_request(self, step: object) -> HttpResponse:
        calls["n"] += 1
        if calls["n"] > 3:
            raise TimeoutError("request timed out")
        return HttpResponse(status_code=200, body={"items": [1]}, latency_ms=105.0, headers={})

    monkeypatch.setattr(RestrictedHttpClient, "request", flaky_request)

    result = asyncio.run(
        runtime.run("environment-1", bundle.scenarios[0], spec, context("op-flaky"))
    )

    assert len(result.observations) == 3
    assert all(o.level == "baseline" for o in result.observations)
    assert result.failure is not None and result.failure.code == "tool_failure"
    assert result.phase == "needs_reconcile"
    assert gateway.restore_calls == 1


@pytest.mark.parametrize(
    "reference", ["CREATE INDEX i ON t (a)", "recipe:../outside", "recipe:/absolute"]
)
def test_recipe_rejects_inline_sql_and_escaping_paths(tmp_path: Path, reference: str) -> None:
    bundle, _ = load_bundle_and_spec()
    runtime, _, _ = build_runtime(tmp_path, bundle.task)
    with pytest.raises(ValueError):
        runtime._resolve_recipe(reference)


def test_changed_live_baseline_is_rejected_and_restored(tmp_path: Path, monkeypatch) -> None:
    bundle, spec = load_bundle_and_spec()
    runtime, gateway, _ = build_runtime(tmp_path, bundle.task)

    async def changed(*args):
        return "unexpected-live-state"

    async def forbidden(*args):
        raise AssertionError("mismatched baseline must not send an HTTP request")

    monkeypatch.setattr(gateway, "fingerprint", changed)
    monkeypatch.setattr(RestrictedHttpClient, "request", forbidden)
    result = asyncio.run(
        runtime.run("environment-1", bundle.scenarios[0], spec, context("changed"))
    )
    assert result.failure is not None
    assert "live baseline" in result.failure.message
    assert result.observations == []
    assert gateway.restore_calls == 1


def test_runtime_settles_observation_artifacts_and_uses_measured_fingerprints(
    tmp_path: Path, monkeypatch
) -> None:
    bundle, spec = load_bundle_and_spec()
    runtime, _, store = build_runtime(tmp_path, bundle.task)
    counter = 0

    async def request(*args):
        return HttpResponse(200, {"items": [1]}, 1, {})

    async def probe(*args):
        nonlocal counter
        counter += 1
        ref = await publish_artifact(
            runtime._settings.artifact_root,
            f"observations/{counter}.json",
            b"{}",
            "application/json",
            "raw.v1",
        )
        return SqlCollection([], [ref])

    runtime._probe = probe
    monkeypatch.setattr(RestrictedHttpClient, "request", request)
    result = asyncio.run(runtime.run("environment-1", bundle.scenarios[0], spec, context("budget")))
    refs = {ref.artifact_id: ref for ref in result.evidence_refs}
    for observation in result.observations:
        refs.update({ref.artifact_id: ref for ref in observation.evidence_refs})
    assert store.consumed.artifact_bytes == sum(ref.size_bytes for ref in refs.values())
    assert store.consumed.artifact_bytes > sum(ref.size_bytes for ref in result.evidence_refs)
    assert {o.fingerprint for o in result.observations if o.level == "candidate_index"} == {
        "fingerprint-candidate"
    }
