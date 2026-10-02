from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from project_doctor.models.common import (
    Contract,
    EnvironmentHealth,
    EvidenceRef,
    Identifier,
    Limits,
    PositiveInt,
)
from project_doctor.models.environment import RestoreResult
from project_doctor.models.errors import Failure
from project_doctor.models.observation import Observation

ExperimentPhase = Literal["prepared", "running", "restoring", "finished", "needs_reconcile"]


class ExperimentSpec(Contract):
    id: Identifier
    task_id: Identifier
    scenario_id: Identifier
    scenario_version: PositiveInt
    hypothesis_ids: Annotated[list[Identifier], Field(min_length=1, max_length=3)]
    variable: Literal["index"]
    levels: tuple[Literal["baseline"], Literal["candidate_index"]]
    intervention_recipe_ref: Identifier
    repetitions: Annotated[int, Field(ge=3, strict=True)]
    limits: Limits
    baseline_fingerprint: Identifier
    snapshot_id: Identifier
    observation_config_id: Identifier


class ExperimentResult(Contract):
    result_type: Literal["experiment"] = "experiment"
    experiment_id: Identifier
    operation_id: Identifier
    phase: ExperimentPhase
    observations: list[Observation] = Field(default_factory=list)
    restore_result: RestoreResult | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    failure: Failure | None = None

    @model_validator(mode="after")
    def consistent_lifecycle(self) -> ExperimentResult:
        if any(item.experiment_id != self.experiment_id for item in self.observations):
            raise ValueError("observation belongs to another experiment")
        keys = [(item.level, item.repetition, item.request_id) for item in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate observation identity")
        if self.phase == "finished":
            if self.restore_result is None:
                raise ValueError("finished experiment requires a restore result")
            if not self.restore_result.verified and self.failure is None:
                raise ValueError("unverified restore requires an explicit failure")
        return self


class ReconciledOperation(Contract):
    operation_id: Identifier
    state: Literal["completed", "failed", "needs_reconcile"]
    result: ExperimentResult | RestoreResult | None = None
    reason: str | None = None


class ReconcileResult(Contract):
    task_id: Identifier
    environment_health: EnvironmentHealth
    operation_results: list[ReconciledOperation] = Field(default_factory=list)
    unresolved_operations: list[Identifier] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def unresolved_environment_not_available(self) -> ReconcileResult:
        if self.unresolved_operations and self.environment_health == "available":
            raise ValueError("unresolved side effects cannot leave the environment available")
        return self
