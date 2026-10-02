from typing import Literal

from pydantic import Field

from project_doctor.models.common import Contract, EvidenceRef, Identifier

FailureCode = Literal[
    "environment_blocked",
    "scenario_invalid",
    "evidence_insufficient",
    "tool_failure",
    "environment_contaminated",
    "budget_exhausted",
    "operation_conflict",
]
RetryPolicy = Literal["never", "reconcile_first", "safe_same_input"]


class Failure(Contract):
    code: FailureCode
    message: Identifier
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    retry_policy: RetryPolicy
