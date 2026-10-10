"""N+1 fix-handoff contracts. No I/O occurs here.

``BatchQuerySpec`` is the structured handoff the diagnosis layer produces for the
permanent code rewrite. It is distinct from the temporary, reversible
``QueryShapeRecipe`` (in ``features/experiments/interventions.py``) that the
experiment runtime applies to *prove* the mechanism: the recipe toggles a runtime
flag, this spec tells the fix layer what to rewrite.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from project_doctor.models.common import CodeLocation, Contract, Identifier, NonNegativeInt

FixStrategy = Literal["batch_in", "joinedload", "selectinload"]


class BatchQuerySpec(Contract):
    kind: Literal["n_plus_one"] = "n_plus_one"
    strategy: FixStrategy
    child_template: Identifier
    key_column: Identifier
    child_code_location: CodeLocation
    observed_child_count: NonNegativeInt
    parent_sql_call_ids: list[Identifier] = Field(default_factory=list)
