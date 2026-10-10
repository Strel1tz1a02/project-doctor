"""Request-associated lock evidence. Missing coverage never means zero wait.

``LOCK_TIME`` from ``performance_schema.events_statements_*`` is the
authoritative per-statement lock-wait measurement: since MySQL 8.0.28 it
accumulates SQL table-lock and InnoDB row-lock (data-lock) wait time, but not
metadata-lock (MDL) waits. ``SqlCall.lock_wait_ms`` carries that measurement;
this model only adds the MDL bound that ``LOCK_TIME`` cannot see.
"""

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
    # Upper bound on the metadata-lock (MDL) delay that LOCK_TIME does not
    # measure; table + InnoDB row locks are carried on SqlCall.lock_wait_ms.
    # None requires exact zero for every kind; a value bounds only the MDL part.
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
            if self.coverage != "complete":
                raise ValueError("zero wait requires complete associated coverage evidence")
            # LOCK_TIME measures table + InnoDB row locks; metadata (MDL) is the
            # only kind that may be bounded by a residual instead of exact zero.
            if "table" not in self.covered_kinds or "innodb_data" not in self.covered_kinds:
                raise ValueError("zero wait requires proven table and InnoDB row-lock coverage")
            if "metadata" not in self.covered_kinds and self.residual_ms is None:
                raise ValueError(
                    "zero wait requires metadata coverage or a declared residual bound"
                )
            if self.missing_kinds:
                raise ValueError("zero wait requires no unaddressed lock kinds")
            if self.thread_id is None or self.statement_event_id is None or not self.evidence_refs:
                raise ValueError("zero wait requires associated coverage evidence")
        if self.status == "observed" and not self.evidence_refs:
            raise ValueError("observed wait requires raw evidence")
        return self
