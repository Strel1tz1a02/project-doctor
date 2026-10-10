"""Structural finding/report contracts; causal diagnosis is implemented by B later."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from project_doctor.models.common import (
    CodeLocation,
    Contract,
    EvidenceRef,
    Identifier,
    NonNegativeFloat,
    ProblemKind,
    TaskStatus,
)
from project_doctor.models.n_plus_one import BatchQuerySpec


class Impact(Contract):
    method: Literal["intervention", "sql_time_estimate", "unmeasured"]
    latency_delta_ms: float | None = Field(default=None, allow_inf_nan=False)
    affected_request_ids: list[Identifier] = Field(default_factory=list)
    shared_sql_call_ids: list[Identifier] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    scope: Literal["test_load"] = "test_load"


class Recommendation(Contract):
    action: Identifier
    mechanism: Identifier
    conditions: list[str]
    costs: list[str]
    validation_status: Literal["expected_mechanism", "retested"] = "expected_mechanism"
    measured_gain_percent: NonNegativeFloat | None = None
    retest_experiment_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_unmeasured_gain(self) -> Recommendation:
        if (
            self.validation_status == "expected_mechanism"
            and self.measured_gain_percent is not None
        ):
            raise ValueError("unretested recommendation cannot claim measured gain")
        if self.validation_status == "retested" and not self.retest_experiment_ids:
            raise ValueError("retested recommendation requires experiment references")
        return self


class ExcludedExplanation(Contract):
    explanation: Identifier
    evidence_ids: list[Identifier] = Field(min_length=1)


class Finding(Contract):
    id: Identifier
    task_id: Identifier
    kind: ProblemKind
    status: Literal["verified", "lead", "refuted", "unclassified"]
    scenario_id: Identifier
    experiment_ids: list[Identifier] = Field(default_factory=list)
    sql_call_ids: list[Identifier] = Field(default_factory=list)
    code_locations: list[CodeLocation] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    excluded_explanations: list[ExcludedExplanation] = Field(default_factory=list)
    impact: Impact
    recommendation: Recommendation | None = None
    fix_spec: BatchQuerySpec | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verified_requires_structural_evidence(self) -> Finding:
        if self.status == "verified" and (
            self.kind not in {"slow_query", "n_plus_one"}
            or not self.experiment_ids
            or not self.sql_call_ids
            or not self.code_locations
            or not self.evidence_refs
            or not self.excluded_explanations
            or self.recommendation is None
        ):
            raise ValueError("verified finding lacks required structural evidence")
        return self

    @model_validator(mode="after")
    def fix_spec_matches_kind_and_mechanism(self) -> Finding:
        if self.fix_spec is None:
            return self
        if self.kind != self.fix_spec.kind:
            raise ValueError("fix_spec kind must match the finding kind")
        if (
            self.recommendation is not None
            and self.recommendation.mechanism != self.fix_spec.strategy
        ):
            raise ValueError("n_plus_one recommendation mechanism must match fix_spec strategy")
        return self


class ReportTask(Contract):
    id: Identifier
    status: TaskStatus
    commit: Identifier
    environment_id: Identifier | None = None


class ReportData(Contract):
    task: ReportTask
    applicability: list[str]
    coverage: list[str]
    verified_findings: list[Finding]
    leads: list[Finding]
    unclassified: list[Finding]
    blocked_paths: list[str]
    limitations: list[str]
    json_content: str
    html_content: str


class ReportResult(Contract):
    result_type: Literal["report"] = "report"
    task_id: Identifier
    task_status: TaskStatus
    json_ref: EvidenceRef
    html_ref: EvidenceRef
    limitations: list[str] = Field(default_factory=list)
