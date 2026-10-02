from typing import Literal

from pydantic import Field

from project_doctor.models.common import Contract, Identifier, NonNegativeInt


class DatasetProfile(Contract):
    id: Identifier
    snapshot_id: Identifier
    source: Literal["authorized_sample", "project_seed", "synthetic"]
    row_counts: dict[Identifier, NonNegativeInt]
    relationship_cardinalities: dict[Identifier, NonNegativeInt] = Field(default_factory=dict)
    distribution_notes: list[str] = Field(default_factory=list)
    target_scale: dict[Identifier, NonNegativeInt] | None = None
    applicability_unknowns: list[str] = Field(default_factory=list)
