"""Request-associated lock evidence. Missing coverage never means zero wait."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from project_doctor.models.common import Contract, EvidenceRef, Identifier, NonNegativeInt

LockKind = Literal["table", "metadata", "innodb_data"]
LOCK_KINDS: set[LockKind] = {"table", "metadata", "innodb_data"}


class LockEvidence(Contract):
    status: Literal["observed", "covered_no_wait", "unknown"]
    coverage: Literal["complete", "partial", "unknown"]
    covered_kinds: list[LockKind] = Field(default_factory=list)
    missing_kinds: list[LockKind] = Field(default_factory=list)
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
        if self.status == "covered_no_wait" and (
            self.coverage != "complete"
            or set(self.covered_kinds) != LOCK_KINDS
            or self.missing_kinds
            or self.thread_id is None
            or self.statement_event_id is None
            or not self.evidence_refs
        ):
            raise ValueError("zero wait requires complete associated coverage evidence")
        if self.status == "observed" and not self.evidence_refs:
            raise ValueError("observed wait requires raw evidence")
        return self
