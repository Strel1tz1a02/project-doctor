"""Cancellation and orphan cleanup regressions from the real AGH probe."""

import asyncio
import json
import threading

import anyio
import pytest
from sqlalchemy import create_engine, insert

from project_doctor.integrations.mysql.migrations.schema import create_schema, operations, tasks
from project_doctor.integrations.mysql.operation_store import reserve_operation
from project_doctor.integrations.runtime_factory import RuntimeService
from project_doctor.models.task import Reservation
from tests.integration.runtime.test_restore import context, make_gateway, make_settings


def test_cancelled_prepare_drains_worker_before_cleanup(tmp_path, monkeypatch):
    gateway = make_gateway(tmp_path)
    started = threading.Event()
    release = threading.Event()
    events = []

    def blocking_prepare(*args):
        started.set()
        assert release.wait(5)
        events.append("up_finished")
        return None

    async def teardown(*args):
        events.append("down")

    monkeypatch.setattr(gateway, "_prepare_sync", blocking_prepare)
    monkeypatch.setattr(gateway, "teardown", teardown)

    async def run():
        task = asyncio.create_task(gateway.prepare(None, context()))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert events == []
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert events == ["up_finished", "down"]


def test_copy_excludes_git_and_records_source_and_stages(tmp_path, monkeypatch):
    gateway = make_gateway(tmp_path)
    target = gateway._settings.target_repo_root
    (target / ".git/objects").mkdir(parents=True)
    (target / ".git/objects/readonly").write_text("metadata")
    (target / "business.sql").write_text("SELECT 1")

    class Runner:
        def up_database(self, timeout):
            assert timeout > 0

        def up(self, timeout):
            assert timeout > 0

    class Snapshots:
        def dump(self, timeout):
            return b"baseline"

    monkeypatch.setattr(gateway, "_runner", lambda *args: Runner())
    monkeypatch.setattr(gateway, "_snapshots", lambda *args: Snapshots())
    from types import SimpleNamespace

    result = gateway._prepare_sync(SimpleNamespace(commit="frozen"), context())
    isolated = gateway._settings.workspace_root / "task-1"
    assert not (isolated / ".git").exists()
    assert (isolated / "business.sql").read_text() == "SELECT 1"
    status = json.loads((isolated / "preparation-status.json").read_text())
    assert status["commit"] == "frozen"
    assert len(status["source_hashes"]["business.sql"]) == 64
    assert set(status["stages"]) == {
        "database_ready_seconds",
        "application_seed_ready_seconds",
        "snapshot_seconds",
    }
    assert result.baseline_dump == b"baseline"


@pytest.mark.parametrize("cancelled", [False, True])
def test_failure_is_settled_with_elapsed_budget_and_cleanup(tmp_path, monkeypatch, cancelled):
    settlements = []
    cleaned = []

    class Store:
        async def reserve(self, *args):
            return Reservation(accepted=True)

        async def finish_operation(self, *args):
            settlements.append(args)

    monkeypatch.setattr(
        "project_doctor.integrations.runtime_factory.mark_operation_running", lambda *args: None
    )
    runtime = RuntimeService(make_settings(tmp_path), Store(), None, make_gateway(tmp_path))

    async def work():
        await asyncio.sleep(0.02)
        if cancelled:
            raise asyncio.CancelledError()
        raise RuntimeError("seed failed")

    async def cleanup():
        cleaned.append(True)

    async def run():
        with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError):
            await runtime._settle(
                task_id="t",
                operation_id="p",
                input_digest="a" * 64,
                request_allowance=0,
                work=work,
                failure_cleanup=cleanup,
            )

    asyncio.run(run())
    assert cleaned == [True]
    _, _, operation, usage = settlements[0]
    assert operation.state == "failed"
    assert "resources removed" in operation.failure.message
    assert usage.wall_seconds >= 0.02


def test_new_preparation_id_cannot_bypass_unknown_operation(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'state.db'}")
    create_schema(engine)
    with engine.begin() as conn:
        conn.execute(insert(tasks).values(id="t", status="created", record_json={}))
        conn.execute(
            insert(operations).values(
                task_id="t", operation_id="prepare-1", input_digest="a" * 64, state="running"
            )
        )
        result = reserve_operation(
            conn,
            task_id="t",
            operation_id="prepare-2",
            input_digest="a" * 64,
            request_allowance=0,
            exclusive_preparation=True,
        )
        assert not result.accepted
        assert "unresolved" in result.reason


def test_close_without_baseline_still_removes_orphan_environment(tmp_path):
    removed = []

    class Store:
        async def reserve(self, *args):
            return Reservation(accepted=True)

        async def finish_operation(self, *args):
            pass

    class Gateway:
        async def teardown(self, environment_id, context):
            removed.append(environment_id)

    engine = create_engine(f"sqlite:///{tmp_path / 'state.db'}")
    create_schema(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(operations).values(
                task_id="task-1", operation_id="op-close", input_digest="a" * 64, state="reserved"
            )
        )
    runtime = RuntimeService(make_settings(tmp_path), Store(), engine, Gateway())
    result = asyncio.run(runtime.close("task-1", context()))
    assert removed == ["task-1"]
    assert not result.verified
    assert "FileNotFoundError" in result.reason


def test_mcp_level_cancellation_cannot_interrupt_failure_settlement(tmp_path, monkeypatch):
    recorded = []

    class Store:
        async def reserve(self, *args):
            return Reservation(accepted=True)

        async def finish_operation(self, *args):
            await anyio.sleep(0)
            recorded.append(args)

    monkeypatch.setattr(
        "project_doctor.integrations.runtime_factory.mark_operation_running", lambda *args: None
    )
    runtime = RuntimeService(make_settings(tmp_path), Store(), None, make_gateway(tmp_path))

    async def run():
        with anyio.CancelScope() as scope:

            async def work():
                scope.cancel()
                await anyio.sleep(0)

            async def cleanup():
                await anyio.sleep(0)
                recorded.append("cleanup")

            await runtime._settle(
                task_id="t",
                operation_id="p",
                input_digest="a" * 64,
                request_allowance=0,
                work=work,
                failure_cleanup=cleanup,
            )

    anyio.run(run)
    assert recorded[0] == "cleanup"
    assert recorded[1][2].state == "failed"


def test_mcp_level_cancellation_drains_prepare_and_tears_down(tmp_path, monkeypatch):
    gateway = make_gateway(tmp_path)
    started = threading.Event()
    release = threading.Event()
    events = []

    def prepare(*args):
        started.set()
        assert release.wait(5)
        events.append("up_finished")

    async def teardown(*args):
        await anyio.sleep(0)
        events.append("down")

    monkeypatch.setattr(gateway, "_prepare_sync", prepare)
    monkeypatch.setattr(gateway, "teardown", teardown)

    async def run():
        async with anyio.create_task_group() as group:
            group.start_soon(gateway.prepare, None, context())
            await anyio.to_thread.run_sync(started.wait, 5)
            group.cancel_scope.cancel()
            release.set()

    anyio.run(run)
    assert events == ["up_finished", "down"]
