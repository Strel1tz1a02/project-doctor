"""Environment gateway used only by the Runtime; B never drives Docker directly.

The gateway returns raw measured state (dump bytes and digests); the Runtime owns
artifact publication and domain-model assembly on top of it.
"""

from dataclasses import dataclass
from typing import Protocol

from project_doctor.models.common import EnvironmentHealth
from project_doctor.models.environment import ProjectInput
from project_doctor.models.task import CallContext


@dataclass(frozen=True)
class PreparedEnvironment:
    environment_id: str
    isolated_base_url: str
    fingerprint: str
    baseline_snapshot_id: str
    baseline_dump: bytes


@dataclass(frozen=True)
class RestoredState:
    verified: bool
    fingerprint: str | None
    snapshot_id: str | None
    index_removed: bool
    reason: str | None
    restored_dump: bytes | None


class EnvironmentGateway(Protocol):
    """Prepares an isolated service, restores it, and reports live health."""

    async def prepare(self, project: ProjectInput, context: CallContext) -> PreparedEnvironment: ...

    async def restore(
        self,
        environment_id: str,
        snapshot_id: str,
        context: CallContext,
        baseline_dump: bytes,
    ) -> RestoredState: ...

    async def health(self, task_id: str) -> EnvironmentHealth: ...

    async def execute_sql(self, environment_id: str, context: CallContext, sql: str) -> None: ...
