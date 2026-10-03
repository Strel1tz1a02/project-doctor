"""Restoration orchestration tests for the Docker gateway (no Docker required).

The digest comparison and teardown discipline are exercised against scripted
snapshot/runner doubles; real container restore stays a separate, unverified probe.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from project_doctor.entrypoints.settings import Settings
from project_doctor.integrations.docker.gateway import DockerEnvironmentGateway
from project_doctor.models.task import CallContext


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


def make_gateway(tmp_path: Path) -> DockerEnvironmentGateway:
    return DockerEnvironmentGateway(
        make_settings(tmp_path),
        db_service="db",
        db_name="app",
        db_user="app",
        db_password="app",
        db_image="mysql:8.4",
        service_image="project-doctor-target:latest",
        service_port=18080,
    )


class ScriptedRunner:
    def __init__(self) -> None:
        self.down_calls = 0

    def down(self, timeout: float) -> None:
        self.down_calls += 1


class ScriptedSnapshots:
    def __init__(self, dumped: bytes) -> None:
        self.dumped = dumped
        self.restored: bytes | None = None

    def restore(self, content: bytes, timeout: float) -> None:
        self.restored = content

    def dump(self, timeout: float) -> bytes:
        return self.dumped


def context() -> CallContext:
    return CallContext(
        task_id="task-1",
        operation_id="op-close",
        missing_correlation=["agh_session_id", "tool_call_id"],
    )


def test_restore_verified_when_dump_matches_baseline(tmp_path: Path, monkeypatch) -> None:
    gateway = make_gateway(tmp_path)
    baseline = b"baseline-dump"
    snapshot_id = hashlib.sha256(baseline).hexdigest()
    runner = ScriptedRunner()

    monkeypatch.setattr(gateway, "_runner", lambda _dir, _name: runner)
    monkeypatch.setattr(gateway, "_snapshots", lambda _runner: ScriptedSnapshots(baseline))

    restored = asyncio.run(gateway.restore("environment-1", snapshot_id, context(), baseline))

    assert restored.verified is True
    assert restored.snapshot_id == snapshot_id
    assert restored.restored_dump == baseline
    assert restored.index_removed is True
    assert runner.down_calls == 0
    # A successful experiment restore must leave the environment available for
    # another experiment or the final restore verification before report publication.
    again = asyncio.run(gateway.restore("environment-1", snapshot_id, context(), baseline))
    assert again.verified
    asyncio.run(gateway.teardown("environment-1", context()))
    assert runner.down_calls == 1


def test_restore_unverified_when_dump_does_not_match(tmp_path: Path, monkeypatch) -> None:
    gateway = make_gateway(tmp_path)
    baseline = b"baseline-dump"
    snapshot_id = hashlib.sha256(baseline).hexdigest()
    runner = ScriptedRunner()

    monkeypatch.setattr(gateway, "_runner", lambda _dir, _name: runner)
    monkeypatch.setattr(gateway, "_snapshots", lambda _runner: ScriptedSnapshots(b"tampered"))

    restored = asyncio.run(gateway.restore("environment-1", snapshot_id, context(), baseline))

    assert restored.verified is False
    assert restored.snapshot_id is None
    assert restored.restored_dump is None
    assert restored.reason is not None
    assert runner.down_calls == 1


def test_restore_always_tears_down_even_when_restore_raises(tmp_path: Path, monkeypatch) -> None:
    gateway = make_gateway(tmp_path)
    baseline = b"baseline-dump"
    snapshot_id = hashlib.sha256(baseline).hexdigest()
    runner = ScriptedRunner()

    class FailingSnapshots(ScriptedSnapshots):
        def restore(self, content: bytes, timeout: float) -> None:
            raise RuntimeError("restore blew up")

    monkeypatch.setattr(gateway, "_runner", lambda _dir, _name: runner)
    monkeypatch.setattr(gateway, "_snapshots", lambda _runner: FailingSnapshots(b"baseline-dump"))

    with pytest.raises(RuntimeError):
        asyncio.run(gateway.restore("environment-1", snapshot_id, context(), baseline))
    assert runner.down_calls == 1
