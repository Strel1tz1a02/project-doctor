"""Docker-backed environment gateway: isolated compose project plus a baseline snapshot.

Only the Runtime drives this; B never touches Docker. ``prepare`` copies the target
repository into an isolated workspace, brings up a dedicated compose project, captures
a baseline database snapshot and returns its fingerprint. ``restore`` returns the
database to that snapshot and verifies it; final teardown is a separate close step.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import shutil
import stat
import time
from pathlib import Path

import anyio

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.environments.ports import PreparedEnvironment, RestoredState
from project_doctor.features.environments.prepare import (
    compose_project_name,
    environment_fingerprint,
    isolated_workspace_path,
)
from project_doctor.features.environments.restore import restore_verified
from project_doctor.integrations.docker.compose import ComposeRunner, render_compose
from project_doctor.integrations.docker.snapshots import SnapshotManager
from project_doctor.models.common import EnvironmentHealth
from project_doctor.models.environment import ProjectInput
from project_doctor.models.task import CallContext


class DockerEnvironmentGateway:
    def __init__(
        self,
        settings: Settings,
        *,
        db_service: str,
        db_name: str,
        db_user: str,
        db_password: str,
        db_image: str,
        service_image: str,
        service_port: int,
    ) -> None:
        self._settings = settings
        self._db_service = db_service
        self._db_name = db_name
        self._db_user = db_user
        self._db_password = db_password
        self._db_image = db_image
        self._service_image = service_image
        self._service_port = service_port

    def _runner(self, project_dir: Path, project_name: str) -> ComposeRunner:
        return ComposeRunner(project_dir, project_name)

    def _snapshots(self, runner: ComposeRunner) -> SnapshotManager:
        return SnapshotManager(
            runner,
            db_service=self._db_service,
            db_name=self._db_name,
            db_user=self._db_user,
            db_password=self._db_password,
        )

    def _prepare_sync(self, project: ProjectInput, context: CallContext) -> PreparedEnvironment:
        project_name = compose_project_name(context.task_id)
        isolated_dir = isolated_workspace_path(self._settings.workspace_root, context.task_id)
        root = self._settings.workspace_root.resolve()
        if not isolated_dir.resolve().is_relative_to(root) or isolated_dir.resolve() == root:
            raise ValueError("isolated workspace escaped configured root")
        if isolated_dir.exists():
            # Old workspaces may contain Windows read-only Git objects.
            def writable_remove(function: object, path: str, error: BaseException) -> None:
                if not isinstance(error, PermissionError):
                    raise error
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                os.remove(path)

            shutil.rmtree(isolated_dir, onexc=writable_remove)
        shutil.copytree(
            self._settings.target_repo_root,
            isolated_dir,
            ignore=shutil.ignore_patterns(".git", ".hg", ".svn"),
        )
        source_hashes = {
            path.relative_to(isolated_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(isolated_dir.rglob("*"))
            if path.is_file()
        }
        status: dict[str, object] = {
            "commit": project.commit,
            "source_hashes": source_hashes,
            "stages": {},
        }
        timings: dict[str, float] = {}
        deadline = time.monotonic() + self._settings.tool_timeouts["prepare_environment"]

        def record(stage: str, start: float) -> None:
            timings[stage] = time.monotonic() - start
            status["stages"] = timings
            (isolated_dir / "preparation-status.json").write_text(
                json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        def remaining() -> float:
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError("environment preparation budget exhausted")
            return seconds

        compose = render_compose(
            service_image=self._service_image,
            service_port=self._service_port,
            db_image=self._db_image,
            db_name=self._db_name,
            db_user=self._db_user,
            db_password=self._db_password,
        )
        (isolated_dir / "docker-compose.yml").write_text(compose, encoding="utf-8")
        # The SQL probe reads performance_schema as the application user; the MySQL
        # entrypoint grants that user privileges only on the app database, so an
        # initdb script (run as root after user creation) grants perf_schema read.
        # PROCESS is also needed so data_lock_waits can report InnoDB row-lock waits
        # held by *other* connections (the request's connection), not just this one.
        initdb_dir = isolated_dir / "initdb"
        initdb_dir.mkdir(parents=True, exist_ok=True)
        (initdb_dir / "grant-perf-schema.sql").write_text(
            f"GRANT SELECT ON performance_schema.* TO '{self._db_user}'@'%';\n"
            f"GRANT PROCESS ON *.* TO '{self._db_user}'@'%';\n"
            "FLUSH PRIVILEGES;\n",
            encoding="utf-8",
        )
        runner = self._runner(isolated_dir, project_name)
        started = time.monotonic()
        runner.up_database(timeout=remaining())
        record("database_ready_seconds", started)
        started = time.monotonic()
        runner.up(timeout=remaining())
        record("application_seed_ready_seconds", started)
        started = time.monotonic()
        baseline_dump = self._snapshots(runner).dump(timeout=remaining())
        record("snapshot_seconds", started)
        snapshot_id = SnapshotManager.digest(baseline_dump)
        return PreparedEnvironment(
            environment_id=project_name,
            isolated_base_url=f"http://127.0.0.1:{self._service_port}",
            fingerprint=environment_fingerprint(commit=project.commit, snapshot_id=snapshot_id),
            baseline_snapshot_id=snapshot_id,
            baseline_dump=baseline_dump,
        )

    def _restore_sync(
        self,
        environment_id: str,
        snapshot_id: str,
        context: CallContext,
        baseline_dump: bytes,
    ) -> RestoredState:
        isolated_dir = isolated_workspace_path(self._settings.workspace_root, context.task_id)
        runner = self._runner(isolated_dir, environment_id)
        try:
            snapshots = self._snapshots(runner)
            snapshots.restore(baseline_dump, timeout=self._settings.tool_timeouts["run_experiment"])
            restored_dump = snapshots.dump(timeout=self._settings.tool_timeouts["run_experiment"])
            actual_snapshot_id = SnapshotManager.digest(restored_dump)
            verified, reason = restore_verified(
                actual_snapshot_id=actual_snapshot_id,
                expected_snapshot_id=snapshot_id,
                index_removed=True,
            )
            if not verified:
                runner.down(timeout=self._settings.tool_timeouts["run_experiment"])
            return RestoredState(
                verified=verified,
                fingerprint=None,
                snapshot_id=snapshot_id if verified else None,
                index_removed=True,
                reason=reason,
                restored_dump=restored_dump if verified else None,
            )
        except BaseException:
            runner.down(timeout=self._settings.tool_timeouts["run_experiment"])
            raise

    async def prepare(self, project: ProjectInput, context: CallContext) -> PreparedEnvironment:
        worker = asyncio.create_task(asyncio.to_thread(self._prepare_sync, project, context))
        try:
            return await asyncio.shield(worker)
        except BaseException:
            # to_thread cannot stop Docker. Drain it before teardown, otherwise
            # a delayed `up` could recreate containers after `down` completed.
            with anyio.CancelScope(shield=True):
                try:
                    await asyncio.shield(worker)
                except BaseException:
                    pass
                await self.teardown(compose_project_name(context.task_id), context)
            raise

    async def restore(
        self,
        environment_id: str,
        snapshot_id: str,
        context: CallContext,
        baseline_dump: bytes,
    ) -> RestoredState:
        return await asyncio.to_thread(
            self._restore_sync, environment_id, snapshot_id, context, baseline_dump
        )

    async def health(self, task_id: str) -> EnvironmentHealth:
        project_name = compose_project_name(task_id)
        isolated_dir = isolated_workspace_path(self._settings.workspace_root, task_id)

        def check() -> EnvironmentHealth:
            if not isolated_dir.exists():
                return "quarantined"
            runner = self._runner(isolated_dir, project_name)
            return "available" if runner.is_up(timeout=15) else "quarantined"

        return await asyncio.to_thread(check)

    async def fingerprint(self, environment_id: str, context: CallContext, commit: str) -> str:
        """Measure live database state; candidate index intentionally changes the hash."""

        def measure() -> str:
            isolated_dir = isolated_workspace_path(self._settings.workspace_root, context.task_id)
            dump = self._snapshots(self._runner(isolated_dir, environment_id)).dump(
                timeout=self._settings.tool_timeouts["run_experiment"]
            )
            return environment_fingerprint(commit=commit, snapshot_id=SnapshotManager.digest(dump))

        return await asyncio.to_thread(measure)

    async def teardown(self, environment_id: str, context: CallContext) -> None:
        isolated_dir = isolated_workspace_path(self._settings.workspace_root, context.task_id)
        if not (isolated_dir / "docker-compose.yml").is_file():
            return
        await asyncio.to_thread(
            self._runner(isolated_dir, environment_id).down,
            timeout=self._settings.tool_timeouts["run_experiment"],
        )

    async def execute_sql(self, environment_id: str, context: CallContext, sql: str) -> None:
        """Run one SQL statement on the target database inside the isolated project."""

        def run_sync() -> None:
            isolated_dir = isolated_workspace_path(self._settings.workspace_root, context.task_id)
            runner = self._runner(isolated_dir, environment_id)
            runner.exec(
                self._db_service,
                [
                    "sh",
                    "-c",
                    (
                        f"mysql -u{self._db_user} -p{self._db_password} {self._db_name} "
                        f"-e {shlex.quote(sql)}"
                    ),
                ],
                timeout=self._settings.tool_timeouts["run_experiment"],
            )

        await asyncio.to_thread(run_sync)

    async def query_sql(self, environment_id: str, context: CallContext, sql: str) -> str:
        """Run a read-only SQL statement on the target DB and return its stdout.

        Used by the SQL probe to read ``performance_schema``; the caller parses the
        ``--batch --skip-column-names`` output.
        """

        def run_sync() -> str:
            isolated_dir = isolated_workspace_path(self._settings.workspace_root, context.task_id)
            runner = self._runner(isolated_dir, environment_id)
            return runner.exec(
                self._db_service,
                [
                    "sh",
                    "-c",
                    (
                        f"mysql -u{self._db_user} -p{self._db_password} {self._db_name} "
                        f"--batch --skip-column-names --raw -e {shlex.quote(sql)}"
                    ),
                ],
                timeout=self._settings.tool_timeouts["run_experiment"],
            )

        return await asyncio.to_thread(run_sync)
