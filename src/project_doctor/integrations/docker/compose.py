"""Docker Compose adapter: isolated project names, rendered files and subprocess calls.

The target service is published on a dedicated host port and internal-only network, so
the experiment address can never be the original production address.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from project_doctor.features.environments.prepare import compose_project_name

__all__ = ["compose_project_name", "render_compose", "ComposeRunner"]


def render_compose(
    *,
    service_image: str,
    service_port: int,
    db_image: str,
    db_name: str,
    db_user: str,
    db_password: str,
) -> str:
    """Render a minimal isolated compose file for a service plus its database.

    The database container receives the MySQL initialization variables so the
    application database and credentials actually exist; the application receives
    the connection variables pointing at that database. The db also enables the
    ``events_statements_history_long`` consumer (off by default) and mounts the
    caller-provided ``./initdb`` directory so the SQL probe can read
    ``performance_schema`` as the application user.
    """
    db_env = "\n".join(
        f"      {key}: {value}"
        for key, value in sorted(
            {
                "MYSQL_DATABASE": db_name,
                "MYSQL_USER": db_user,
                "MYSQL_PASSWORD": db_password,
                "MYSQL_ROOT_PASSWORD": db_password,
            }.items()
        )
    )
    app_env = (
        "      DB_HOST: db\n"
        '      DB_PORT: "3306"\n'
        f"      DB_NAME: {db_name}\n"
        f"      DB_USER: {db_user}\n"
        f"      DB_PASSWORD: {db_password}\n"
    )
    return (
        "services:\n"
        "  app:\n"
        f"    image: {service_image}\n"
        "    depends_on:\n"
        "      - db\n"
        f"    ports:\n"
        f'      - "{service_port}:8080"\n'
        "    environment:\n"
        f"{app_env}"
        "    networks:\n"
        "      - internal\n"
        "  db:\n"
        f"    image: {db_image}\n"
        "    command: --performance-schema-consumer-events-statements-history-long=ON\n"
        "    environment:\n"
        f"{db_env}"
        "    volumes:\n"
        "      - ./initdb:/docker-entrypoint-initdb.d:ro\n"
        "    networks:\n"
        "      - internal\n"
        "networks:\n"
        "  internal:\n"
        "    internal: true\n"
    )


class ComposeRunner:
    """Run ``docker compose`` for one isolated project; every call is synchronous."""

    def __init__(self, project_dir: Path, project_name: str) -> None:
        self._project_dir = project_dir
        self._project_name = project_name

    def _run(self, *args: str, timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "compose", "-p", self._project_name, *args],
            cwd=self._project_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def up(self, timeout: float) -> None:
        result = self._run("up", "-d", "--wait", timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"docker compose up failed: {result.stderr.strip()}")

    def down(self, timeout: float) -> None:
        result = self._run("down", "-v", "--remove-orphans", timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"docker compose down failed: {result.stderr.strip()}")

    def is_up(self, timeout: float) -> bool:
        result = self._run("ps", "--services", "--filter", "status=running", timeout=timeout)
        return result.returncode == 0 and bool(result.stdout.strip())

    def exec(self, service: str, command: list[str], timeout: float) -> str:
        result = self._run("exec", "-T", service, *command, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"docker compose exec failed: {result.stderr.strip()}")
        return result.stdout

    def exec_with_input(self, service: str, command: list[str], data: str, timeout: float) -> str:
        result = subprocess.run(
            ["docker", "compose", "-p", self._project_name, "exec", "-T", service, *command],
            cwd=self._project_dir,
            input=data,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"docker compose exec failed: {result.stderr.strip()}")
        return result.stdout
