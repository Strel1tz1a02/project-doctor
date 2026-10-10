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
    Sha256,
)
from project_doctor.models.environment import RestoreResult
from project_doctor.models.errors import Failure
from project_doctor.models.observation import CandidateLevel, ExperimentLevel, Observation

ExperimentPhase = Literal["prepared", "running", "restoring", "finished", "needs_reconcile"]


class WarmupSpec(Contract):
    protocol_id: Literal["serial-readonly-warmup.v1"] = "serial-readonly-warmup.v1"
    preparation_recipe_ref: Literal["builtin:serial-readonly-warmup.v1"] = (
        "builtin:serial-readonly-warmup.v1"
    )
    requests_per_level: PositiveInt = 5


class PreparationResult(Contract):
    level: ExperimentLevel
    protocol_id: Identifier
    snapshot_id: Identifier
    observation_config_id: Identifier
    prepared_fingerprint: Identifier
    final_fingerprint: Identifier | None = None
    recipe_digest: Sha256
    verified: bool = False
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class WarmupResult(Contract):
    level: ExperimentLevel
    ordinal: PositiveInt
    request_id: Identifier
    business_valid: bool
    result_digest: Sha256 | None = None
    failure: Failure | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class ExperimentSpec(Contract):
    id: Identifier
    task_id: Identifier
    scenario_id: Identifier
    scenario_version: PositiveInt
    hypothesis_ids: Annotated[list[Identifier], Field(min_length=1, max_length=3)]
    variable: Literal["index", "query_shape"]
    levels: tuple[Literal["baseline"], CandidateLevel]
    intervention_recipe_ref: Identifier
    repetitions: Annotated[int, Field(ge=3, strict=True)]
    limits: Limits
    baseline_fingerprint: Identifier
    snapshot_id: Identifier
    observation_config_id: Identifier
    warmup: WarmupSpec | None = None

    @model_validator(mode="after")
    def variable_matches_candidate_level(self) -> ExperimentSpec:
        expected: CandidateLevel = (
            "candidate_index" if self.variable == "index" else "candidate_batch"
        )
        if self.levels[1] != expected:
            raise ValueError("experiment variable must match its candidate level")
        return self


class ExperimentResult(Contract):
    result_type: Literal["experiment"] = "experiment"
    experiment_id: Identifier
    operation_id: Identifier
    phase: ExperimentPhase
    observations: list[Observation] = Field(default_factory=list)
    restore_result: RestoreResult | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    failure: Failure | None = None
    spec: ExperimentSpec | None = None
    preparation_results: list[PreparationResult] = Field(default_factory=list)
    warmup_results: list[WarmupResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_lifecycle(self) -> ExperimentResult:
        if self.spec is not None and self.spec.id != self.experiment_id:
            raise ValueError("persisted spec belongs to another experiment")
        if any(item.experiment_id != self.experiment_id for item in self.observations):
            raise ValueError("observation belongs to another experiment")
        keys = [(item.level, item.repetition, item.request_id) for item in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate observation identity")
        request_ids = [item.request_id for item in self.observations] + [
            item.request_id for item in self.warmup_results
        ]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("duplicate request identity across warmup and measurement")
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
