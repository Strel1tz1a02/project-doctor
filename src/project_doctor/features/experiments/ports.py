from typing import Protocol

from project_doctor.models.environment import EnvironmentHandle, ProjectInput, RestoreResult
from project_doctor.models.experiment import ExperimentResult, ExperimentSpec, ReconcileResult
from project_doctor.models.finding import ReportData, ReportResult
from project_doctor.models.scenario import Scenario
from project_doctor.models.task import CallContext


class Runtime(Protocol):
    """A owns execution, reservation, environment exclusivity and verified restoration."""

    async def prepare(self, project: ProjectInput, context: CallContext) -> EnvironmentHandle: ...

    async def run(
        self,
        environment_id: str,
        scenario: Scenario,
        spec: ExperimentSpec,
        context: CallContext,
    ) -> ExperimentResult: ...

    async def reconcile(self, task_id: str) -> ReconcileResult: ...

    async def close(self, environment_id: str, context: CallContext) -> RestoreResult: ...

    async def publish_report(self, data: ReportData, context: CallContext) -> ReportResult: ...
