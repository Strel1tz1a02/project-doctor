from typing import Annotated, Literal

from pydantic import Field

from project_doctor.models.common import Contract, Identifier, ProblemKind


class Hypothesis(Contract):
    id: Identifier
    kind: ProblemKind
    explanation: Identifier
    predictions: Annotated[list[Identifier], Field(min_length=1)]
    falsifiers: Annotated[list[Identifier], Field(min_length=1)]
    status: Literal["proposed", "supported", "refuted", "unresolved"]
    evidence_ids: list[Identifier] = Field(default_factory=list)


class HypothesisBatch(Contract):
    items: Annotated[list[Hypothesis], Field(min_length=1, max_length=3)]
