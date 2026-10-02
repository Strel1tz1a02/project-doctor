"""Target-database snapshots: dump, restore and verify against a baseline digest."""

from __future__ import annotations

import hashlib

from project_doctor.integrations.docker.compose import ComposeRunner


class SnapshotManager:
    """Create and restore database snapshots through the compose runner's exec channel."""

    def __init__(
        self,
        runner: ComposeRunner,
        *,
        db_service: str,
        db_name: str,
        db_user: str,
        db_password: str,
    ) -> None:
        self._runner = runner
        self._db_service = db_service
        self._db_name = db_name
        self._db_user = db_user
        self._db_password = db_password

    def dump(self, timeout: float) -> bytes:
        """Dump the current database; the bytes are the snapshot content and digest."""
        return self._runner.exec(
            self._db_service,
            [
                "sh",
                "-c",
                (
                    f"mysqldump --single-transaction --skip-comments --skip-dump-date "
                    f"-u{self._db_user} -p{self._db_password} {self._db_name}"
                ),
            ],
            timeout,
        ).encode("utf-8")

    def restore(self, content: bytes, timeout: float) -> None:
        """Restore the database from a previously captured dump."""
        self._runner.exec_with_input(
            self._db_service,
            ["sh", "-c", f"mysql -u{self._db_user} -p{self._db_password} {self._db_name}"],
            content.decode("utf-8"),
            timeout,
        )

    @staticmethod
    def digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()
