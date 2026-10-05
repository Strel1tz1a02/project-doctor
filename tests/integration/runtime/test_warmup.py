import asyncio
from pathlib import Path

import pytest

from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.integrations.http.requests import HttpResponse, RestrictedHttpClient
from project_doctor.integrations.observation.lock_probe import LockProbe
from project_doctor.models.experiment import WarmupSpec
from project_doctor.workflows.execute_experiment import needed_requests
from tests.integration.runtime.test_slow_query import build_runtime, context, load_bundle_and_spec


def prepared_case():
    bundle, spec = load_bundle_and_spec()
    spec.warmup = WarmupSpec()
    spec.repetitions = 10
    spec.limits.max_requests = bundle.task.limits.max_requests = 30
    bundle.scenarios[0].cache.preparation_recipe_ref = spec.warmup.preparation_recipe_ref
    return bundle, spec


def test_thirty_attempts_only_twenty_formal_samples(tmp_path: Path, monkeypatch) -> None:
    bundle, spec = prepared_case()
    runtime, gateway, store = build_runtime(tmp_path, bundle.task)
    events = []
    original_restore = gateway.restore

    async def restore(*args):
        events.append("restore")
        gateway.sql_applied.clear()
        return await original_restore(*args)

    async def fingerprint(*args):
        events.append("fingerprint")
        return "fingerprint-candidate" if gateway.sql_applied else "fingerprint-baseline"

    async def request(self, step, *, request_id=None):
        events.append("request")
        return HttpResponse(200, {"items": [1]}, 1, {}, request_id)

    monkeypatch.setattr(gateway, "restore", restore)
    monkeypatch.setattr(gateway, "fingerprint", fingerprint)
    monkeypatch.setattr(RestrictedHttpClient, "request", request)
    result = asyncio.run(runtime.run("environment-1", bundle.scenarios[0], spec, context("warm")))
    assert result.failure is None
    assert needed_requests(spec) == store.consumed.requests == 30
    assert len(result.observations) == 20 and len(result.warmup_results) == 10
    assert len({item.request_id for item in result.observations + result.warmup_results}) == 30
    assert events == (["restore", "fingerprint"] + ["request"] * 15 + ["fingerprint"]) * 2 + [
        "restore"
    ]
    assert all(item.verified for item in result.preparation_results)


@pytest.mark.parametrize("fault", ["timeout", "business"])
def test_failed_warmup_counts_attempt_and_still_restores(
    tmp_path: Path, monkeypatch, fault
) -> None:
    bundle, spec = prepared_case()
    runtime, gateway, store = build_runtime(tmp_path, bundle.task)

    async def request(self, step, *, request_id=None):
        if fault == "timeout":
            raise TimeoutError("warmup request timed out")
        return HttpResponse(500, {}, 1, {}, request_id)

    monkeypatch.setattr(RestrictedHttpClient, "request", request)
    result = asyncio.run(runtime.run("environment-1", bundle.scenarios[0], spec, context("fail")))
    assert result.failure and result.restore_result.verified
    assert result.observations == [] and len(result.warmup_results) == 1
    assert result.warmup_results[0].failure and result.warmup_results[0].evidence_refs
    assert store.consumed.requests == 1 and gateway.restore_calls == 2


def test_budget_accounts_for_preheating_before_side_effects(tmp_path: Path) -> None:
    bundle, spec = prepared_case()
    bundle.task.limits.max_requests = 29
    runtime, gateway, store = build_runtime(tmp_path, bundle.task)
    result = asyncio.run(runtime.run("environment-1", bundle.scenarios[0], spec, context("budget")))
    assert result.failure.code == "budget_exhausted"
    assert gateway.restore_calls == 0 and store.consumed is None


def test_restore_exception_is_persisted_for_reconcile(tmp_path: Path, monkeypatch) -> None:
    bundle, spec = prepared_case()
    runtime, gateway, store = build_runtime(tmp_path, bundle.task)

    async def restore(*args):
        raise RuntimeError("restore process unavailable")

    monkeypatch.setattr(gateway, "restore", restore)
    result = asyncio.run(
        runtime.run("environment-1", bundle.scenarios[0], spec, context("restore-fail"))
    )
    assert result.phase == "needs_reconcile"
    assert result.restore_result.verified is False
    assert result.failure and "restore" in result.failure.message
    assert store.results["restore-fail"].state == "needs_reconcile"
    assert store.consumed.requests == 0


@pytest.mark.parametrize("budget", ["time", "artifacts"])
def test_preparation_budget_stops_before_requests_and_restores(tmp_path: Path, budget: str) -> None:
    bundle, spec = prepared_case()
    if budget == "time":
        bundle.task.usage.wall_seconds = (
            bundle.task.limits.max_wall_seconds - spec.limits.restore_reserve_seconds + 1
        )
    else:
        spec.limits.max_artifact_bytes = 1
    runtime, gateway, store = build_runtime(tmp_path, bundle.task)
    result = asyncio.run(runtime.run("environment-1", bundle.scenarios[0], spec, context("limit")))
    assert result.failure
    assert result.restore_result.verified
    assert store.consumed.requests == 0
    assert gateway.restore_calls == 1


def test_changed_group_is_not_verified_even_after_successful_requests(
    tmp_path: Path, monkeypatch
) -> None:
    bundle, spec = prepared_case()
    runtime, gateway, store = build_runtime(tmp_path, bundle.task)
    fingerprints = iter(["fingerprint-baseline", "changed-after-measurement"])

    async def fingerprint(*args):
        return next(fingerprints)

    async def request(self, step, *, request_id=None):
        return HttpResponse(200, {"items": [1]}, 1, {}, request_id)

    monkeypatch.setattr(gateway, "fingerprint", fingerprint)
    monkeypatch.setattr(RestrictedHttpClient, "request", request)
    result = asyncio.run(
        runtime.run("environment-1", bundle.scenarios[0], spec, context("changed-group"))
    )
    assert result.failure and result.phase == "needs_reconcile"
    assert len(result.observations) == 10 and store.consumed.requests == 15
    assert result.preparation_results[0].verified is False
    assert result.restore_result.verified


def test_failed_formal_request_keeps_lock_window_evidence(tmp_path: Path, monkeypatch) -> None:
    bundle, spec = prepared_case()
    runtime, gateway, store = build_runtime(tmp_path, bundle.task)
    attempts = 0

    async def query(context, sql):
        return "{}" if "JSON_ARRAYAGG" in sql else ""

    async def publish(path, raw, media, version):
        return await publish_artifact(runtime._settings.artifact_root, path, raw, media, version)

    runtime._lock_probe = LockProbe(query=query, publish=publish)

    async def request(self, step, *, request_id=None):
        nonlocal attempts
        attempts += 1
        if attempts == 6:
            raise TimeoutError("formal request timed out")
        return HttpResponse(200, {"items": [1]}, 1, {}, request_id)

    monkeypatch.setattr(RestrictedHttpClient, "request", request)
    result = asyncio.run(
        runtime.run("environment-1", bundle.scenarios[0], spec, context("formal-failure"))
    )
    assert result.failure and result.restore_result.verified
    assert result.observations == [] and len(result.warmup_results) == 5
    assert store.consumed.requests == 6 and gateway.restore_calls == 2
    assert sum(ref.format_version == "lock-sampling.v1" for ref in result.evidence_refs) == 3
    assert any("measurement-failures" in ref.relative_path for ref in result.evidence_refs)


def test_task_artifact_budget_clamps_larger_experiment_budget(tmp_path: Path) -> None:
    bundle, spec = prepared_case()
    bundle.task.usage.artifact_bytes = bundle.task.limits.max_artifact_bytes - 1
    runtime, gateway, store = build_runtime(tmp_path, bundle.task)
    result = asyncio.run(
        runtime.run("environment-1", bundle.scenarios[0], spec, context("task-artifacts"))
    )
    assert result.failure and "artifact budget" in result.failure.message
    assert store.consumed.requests == 0 and gateway.restore_calls == 1


def test_experiment_request_budget_rejects_warmup_before_side_effects(tmp_path: Path) -> None:
    bundle, spec = prepared_case()
    spec.limits.max_requests = 29
    runtime, gateway, store = build_runtime(tmp_path, bundle.task)
    result = asyncio.run(
        runtime.run("environment-1", bundle.scenarios[0], spec, context("spec-budget"))
    )
    assert result.failure.code == "budget_exhausted"
    assert store.consumed is None and gateway.restore_calls == 0
