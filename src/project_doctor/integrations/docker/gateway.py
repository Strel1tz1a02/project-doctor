"""Docker-backed environment gateway: isolated compose project plus a baseline snapshot.

Only the Runtime drives this; B never touches Docker. ``prepare`` copies the target
repository into an isolated workspace, brings up a dedicated compose project, captures
a baseline database snapshot and returns its fingerprint. ``restore`` returns the
database to that snapshot, verifies it and tears the project down.
"""

from __future__ import annotations

import asyncio
import shlex
import shutil
from pathlib import Path

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
        if isolated_dir.exists():
            shutil.rmtree(isolated_dir)
        shutil.copytree(self._settings.target_repo_root, isolated_dir)
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
        initdb_dir = isolated_dir / "initdb"
        initdb_dir.mkdir(parents=True, exist_ok=True)
        (initdb_dir / "grant-perf-schema.sql").write_text(
            f"GRANT SELECT ON performance_schema.* TO '{self._db_user}'@'%';\nFLUSH PRIVILEGES;\n",
            encoding="utf-8",
        )
        runner = self._runner(isolated_dir, project_name)
        runner.up(timeout=self._settings.tool_timeouts["prepare_environment"])
        baseline_dump = self._snapshots(runner).dump(
            timeout=self._settings.tool_timeouts["prepare_environment"]
        )
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
            return RestoredState(
                verified=verified,
                fingerprint=None,
                snapshot_id=snapshot_id if verified else None,
                index_removed=True,
                reason=reason,
                restored_dump=restored_dump if verified else None,
            )
        finally:
            runner.down(timeout=self._settings.tool_timeouts["run_experiment"])

    async def prepare(self, project: ProjectInput, context: CallContext) -> PreparedEnvironment:
        return await asyncio.to_thread(self._prepare_sync, project, context)

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
