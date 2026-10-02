"""Test-only scripted dependencies; they do not prove MySQL, isolation or actual evidence."""

from project_doctor.models.common import EvidenceCheck, EvidenceRef, TaskStatus, Usage
from project_doctor.models.environment import EnvironmentHandle, ProjectInput, RestoreResult
from project_doctor.models.experiment import ExperimentResult, ExperimentSpec, ReconcileResult
from project_doctor.models.finding import Finding, ReportData, ReportResult
from project_doctor.models.hypothesis import Hypothesis
from project_doctor.models.scenario import Scenario
from project_doctor.models.task import (
    CallContext,
    OperationResult,
    Reservation,
    TaskBundle,
    TaskRecord,
)


class MemoryStore:
    def __init__(self, bundle: TaskBundle) -> None:
        self.bundle = bundle.model_copy(deep=True)
        self.reservation_calls = 0

    async def create(self, task: TaskRecord) -> None:
        if self.bundle.task.id != task.id:
            self.bundle = TaskBundle(task=task)

    async def get(self, task_id: str) -> TaskRecord:
        if task_id != self.bundle.task.id:
            raise KeyError(task_id)
        return self.bundle.task.model_copy(deep=True)

    async def save_scenario(self, task_id: str, scenario: Scenario) -> None:
        await self.get(task_id)
        self.bundle.scenarios = [
            item
            for item in self.bundle.scenarios
            if (item.id, item.version) != (scenario.id, scenario.version)
        ] + [scenario]

    async def save_hypotheses(self, task_id: str, items: list[Hypothesis]) -> None:
        await self.get(task_id)
        keys = {item.id for item in items}
        self.bundle.hypotheses = [
            item for item in self.bundle.hypotheses if item.id not in keys
        ] + items

    async def save_findings(self, task_id: str, items: list[Finding]) -> None:
        await self.get(task_id)
        keys = {item.id for item in items}
        self.bundle.findings = [
            item for item in self.bundle.findings if item.id not in keys
        ] + items

    async def transition(self, task_id: str, expected: TaskStatus, target: TaskStatus) -> bool:
        await self.get(task_id)
        if self.bundle.task.status != expected:
            return False
        self.bundle.task.status = target
        return True

    async def reserve(
        self, task_id: str, operation_id: str, input_digest: str, request_allowance: int
    ) -> Reservation:
        self.reservation_calls += 1
        raise AssertionError("B must not reserve Runtime operations")

    async def finish_operation(
        self, task_id: str, operation_id: str, result: OperationResult, consumed: Usage
    ) -> None:
        raise AssertionError("B must not settle Runtime operations")

    async def load_operation(self, task_id: str, operation_id: str) -> OperationResult | None:
        await self.get(task_id)
        return None

    async def load_bundle(self, task_id: str) -> TaskBundle:
        await self.get(task_id)
        return self.bundle.model_copy(deep=True)


class ScriptedRuntime:
    def __init__(self, store: MemoryStore, restore_ok: bool = True) -> None:
        self.store = store
        self.restore_ok = restore_ok
        self.run_calls = 0
        self.replayed: dict[str, ExperimentResult] = {}
        self.report: ReportData | None = None

    async def prepare(self, project: ProjectInput, context: CallContext) -> EnvironmentHandle:
        self.store.bundle.task.environment_id = "environment-1"
        self.store.bundle.task.status = "running"
        return EnvironmentHandle(
            id="environment-1",
            isolated_base_url="http://localhost:8001",
            fingerprint="fingerprint-baseline",
            baseline_snapshot_id="snapshot-1",
            health="available",
        )

    async def run(
        self, environment_id: str, scenario: Scenario, spec: ExperimentSpec, context: CallContext
    ) -> ExperimentResult:
        if context.operation_id not in self.replayed:
            self.run_calls += 1
            result = self.store.bundle.experiments[0].model_copy(deep=True)
            result.spec = spec
            self.replayed[context.operation_id] = result
        return self.replayed[context.operation_id]

    async def reconcile(self, task_id: str) -> ReconcileResult:
        return ReconcileResult(task_id=task_id, environment_health="available")

    async def close(self, environment_id: str, context: CallContext) -> RestoreResult:
        if not self.restore_ok:
            return RestoreResult(verified=False, reason="scripted restoration failure")
        result = self.store.bundle.experiments[0].restore_result
        assert result is not None
        return result

    async def publish_report(self, data: ReportData, context: CallContext) -> ReportResult:
        self.report = data
        ref = self.store.bundle.evidence_refs[0]
        return ReportResult(
            task_id=context.task_id, task_status=data.task.status, json_ref=ref, html_ref=ref
        )


class ScriptedReader:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid

    async def verify(self, refs: list[EvidenceRef]) -> EvidenceCheck:
        return EvidenceCheck(
            valid=self.valid, reasons=[] if self.valid else ["scripted corruption"]
        )
