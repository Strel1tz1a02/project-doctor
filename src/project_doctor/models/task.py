from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from project_doctor.models.common import (
    Contract,
    EvidenceRef,
    Identifier,
    Limits,
    Sha256,
    TaskStatus,
    Usage,
)
from project_doctor.models.environment import EnvironmentHandle, ProjectInput, RestoreResult
from project_doctor.models.errors import Failure
from project_doctor.models.experiment import ExperimentResult
from project_doctor.models.finding import Finding, ReportResult
from project_doctor.models.hypothesis import Hypothesis
from project_doctor.models.scenario import Scenario

OperationState = Literal["reserved", "running", "completed", "failed", "needs_reconcile"]
OperationPayload = Annotated[
    EnvironmentHandle | ExperimentResult | RestoreResult | ReportResult,
    Field(discriminator="result_type"),
]


class CallContext(Contract):
    task_id: Identifier
    operation_id: Identifier
    agh_session_id: Identifier | None = None
    tool_call_id: Identifier | None = None
    missing_correlation: list[Literal["agh_session_id", "tool_call_id"]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def missing_ids_explicit(self) -> CallContext:
        expected = {
            name for name in ("agh_session_id", "tool_call_id") if getattr(self, name) is None
        }
        if expected != set(self.missing_correlation):
            raise ValueError("missing AGH correlation IDs must be explicitly recorded")
        return self


class OperationResult(Contract):
    operation_id: Identifier
    state: OperationState
    input_digest: Sha256
    payload: OperationPayload | None = None
    failure: Failure | None = None

    @model_validator(mode="after")
    def consistent_operation(self) -> OperationResult:
        if self.state == "completed" and (self.payload is None or self.failure is not None):
            raise ValueError("completed operation requires a payload and no failure")
        if self.state == "failed" and self.failure is None:
            raise ValueError("failed operation requires a failure")
        return self


class Reservation(Contract):
    accepted: bool
    reason: str | None = None
    replay_result: OperationResult | None = None

    @model_validator(mode="after")
    def reserve_or_replay(self) -> Reservation:
        if self.accepted and (self.replay_result is not None or self.reason is not None):
            raise ValueError("new reservation cannot also replay or reject")
        if not self.accepted and self.replay_result is None and not self.reason:
            raise ValueError("rejected reservation requires a reason or prior operation")
        return self


class TaskRecord(Contract):
    id: Identifier
    project: ProjectInput
    status: TaskStatus
    limits: Limits
    usage: Usage
    environment_id: Identifier | None = None
    scenario_ids: list[Identifier] = Field(default_factory=list)
    experiment_ids: list[Identifier] = Field(default_factory=list)
    hypothesis_ids: list[Identifier] = Field(default_factory=list)
    finding_ids: list[Identifier] = Field(default_factory=list)
    correlation: CallContext
    coverage: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def context_matches_task(self) -> TaskRecord:
        if self.correlation.task_id != self.id:
            raise ValueError("correlation belongs to another task")
        return self


class TaskBundle(Contract):
    task: TaskRecord
    scenarios: list[Scenario] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    experiments: list[ExperimentResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
