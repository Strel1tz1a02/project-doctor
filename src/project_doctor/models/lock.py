"""Request-associated lock evidence. Missing coverage never means zero wait."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from project_doctor.models.common import (
    Contract,
    EvidenceRef,
    Identifier,
    NonNegativeFloat,
    NonNegativeInt,
)

LockKind = Literal["table", "metadata", "innodb_data"]
LOCK_KINDS: set[LockKind] = {"table", "metadata", "innodb_data"}


class LockEvidence(Contract):
    status: Literal["observed", "covered_no_wait", "unknown"]
    coverage: Literal["complete", "partial", "unknown"]
    covered_kinds: list[LockKind] = Field(default_factory=list)
    missing_kinds: list[LockKind] = Field(default_factory=list)
    # Conservative upper bound on unassigned cumulative lock delay. This can
    # include global metadata acquisition time or a full sampling window. None
    # requires exact zero evidence; a value never means an actual zero metric.
    residual_ms: NonNegativeFloat | None = None
    thread_id: NonNegativeInt | None = None
    statement_event_id: NonNegativeInt | None = None
    window_start: datetime
    window_end: datetime
    reasons: list[Identifier] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_coverage(self) -> "LockEvidence":
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("lock window must include a timezone")
        if self.window_end < self.window_start:
            raise ValueError("lock window ends before it starts")
        if set(self.covered_kinds) & set(self.missing_kinds):
            raise ValueError("lock category cannot be both covered and missing")
        if self.status == "covered_no_wait" or (
            self.status == "observed" and self.coverage == "complete"
        ):
            if self.status == "observed" and self.residual_ms is None:
                raise ValueError("complete observed waits require a cumulative delay bound")
            if self.coverage != "complete":
                raise ValueError("zero wait requires complete associated coverage evidence")
            if "table" not in self.covered_kinds or "metadata" not in self.covered_kinds:
                raise ValueError("zero wait requires proven table and metadata lock coverage")
            if "innodb_data" not in self.covered_kinds and self.residual_ms is None:
                raise ValueError(
                    "zero wait requires innodb_data coverage or a declared residual bound"
                )
            if self.missing_kinds:
                raise ValueError("zero wait requires no unaddressed lock kinds")
            if self.thread_id is None or self.statement_event_id is None or not self.evidence_refs:
                raise ValueError("zero wait requires associated coverage evidence")
        if self.status == "observed" and not self.evidence_refs:
            raise ValueError("observed wait requires raw evidence")
        return self
