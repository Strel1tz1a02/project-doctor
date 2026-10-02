from typing import Protocol

from project_doctor.models.common import TaskStatus, Usage
from project_doctor.models.finding import Finding
from project_doctor.models.hypothesis import Hypothesis
from project_doctor.models.scenario import Scenario
from project_doctor.models.task import OperationResult, Reservation, TaskBundle, TaskRecord


class TaskStore(Protocol):
    """B consumes this interface; A implements MySQL transactions and operation records."""

    async def create(self, task: TaskRecord) -> None: ...
    async def get(self, task_id: str) -> TaskRecord: ...
    async def save_scenario(self, task_id: str, scenario: Scenario) -> None: ...
    async def save_hypotheses(self, task_id: str, items: list[Hypothesis]) -> None: ...
    async def save_findings(self, task_id: str, items: list[Finding]) -> None: ...
    async def transition(self, task_id: str, expected: TaskStatus, target: TaskStatus) -> bool: ...
    async def reserve(
        self,
        task_id: str,
        operation_id: str,
        input_digest: str,
        request_allowance: int,
    ) -> Reservation: ...

    async def finish_operation(
        self,
        task_id: str,
        operation_id: str,
        result: OperationResult,
        consumed: Usage,
    ) -> None: ...

    async def load_operation(self, task_id: str, operation_id: str) -> OperationResult | None: ...
    async def load_bundle(self, task_id: str) -> TaskBundle: ...
