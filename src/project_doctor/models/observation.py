from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from project_doctor.models.common import (
    CodeLocation,
    Contract,
    EvidenceRef,
    Identifier,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    Sha256,
)
from project_doctor.models.lock import LockEvidence

ExperimentLevel = Literal["baseline", "candidate_index"]
MetricName = Literal["duration_ms", "rows_examined", "rows_returned", "lock_wait_ms"]


class MetricSource(Contract):
    source: Identifier
    measurement: Literal["actual", "estimated"]
    evidence_ids: list[Identifier] = Field(default_factory=list)


class ParameterProvenance(Contract):
    parameter: Identifier
    source_ref: Identifier
    evidence_ids: list[Identifier] = Field(default_factory=list)


class SqlCall(Contract):
    id: Identifier
    normalized_sql: Identifier
    duration_ms: NonNegativeFloat | None = None
    rows_examined: NonNegativeInt | None = None
    rows_returned: NonNegativeInt | None = None
    lock_wait_ms: NonNegativeFloat | None = None
    metric_sources: dict[MetricName, MetricSource] = Field(default_factory=dict)
    parameter_provenance: list[ParameterProvenance] = Field(default_factory=list)
    code_location: CodeLocation | None = None
    plan_evidence_ids: list[Identifier] = Field(default_factory=list)
    span_id: Identifier | None = None
    lock_evidence: LockEvidence | None = None

    @model_validator(mode="after")
    def measurements_have_actual_sources(self) -> SqlCall:
        for name in ("duration_ms", "rows_examined", "rows_returned", "lock_wait_ms"):
            value = getattr(self, name)
            source = self.metric_sources.get(name)
            if value is not None and (source is None or source.measurement != "actual"):
                raise ValueError(
                    f"{name} requires an actual metric source; estimates belong in plans"
                )
            if value is None and source is not None:
                raise ValueError(f"{name} source cannot stand in for a missing value")
        if self.lock_evidence is not None:
            status = self.lock_evidence.status
            if status == "covered_no_wait" and self.lock_wait_ms != 0:
                raise ValueError("covered_no_wait requires an actual zero lock metric")
            if status != "covered_no_wait" and self.lock_wait_ms == 0:
                raise ValueError("incomplete or observed lock evidence cannot assert zero wait")
        return self


class Observation(Contract):
    id: Identifier
    experiment_id: Identifier
    level: ExperimentLevel
    repetition: PositiveInt
    request_id: Identifier
    business_valid: bool
    latency_ms: NonNegativeFloat
    result_digest: Sha256 | None = None
    sql_calls: list[SqlCall]
    fingerprint: Identifier
    snapshot_id: Identifier
    observation_config_id: Identifier
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
