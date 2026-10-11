"""Deep-pagination fix-handoff contracts. No I/O occurs here.

``DeepPaginationSpec`` is the structured handoff the diagnosis layer produces for
the permanent code rewrite (keyset pagination or a max-page limit). It is distinct
from the temporary, reversible ``PaginationRecipe`` (in
``features/experiments/interventions.py``) that the experiment runtime applies to
*prove* the mechanism: the recipe toggles a runtime flag, this spec tells the fix
layer what to rewrite.
"""

from __future__ import annotations

from typing import Literal

from project_doctor.models.common import CodeLocation, Contract, Identifier, NonNegativeInt

PaginationStrategy = Literal["keyset", "max_page_limit"]


class DeepPaginationSpec(Contract):
    kind: Literal["deep_pagination"] = "deep_pagination"
    strategy: PaginationStrategy
    query_template: Identifier
    sort_column: Identifier
    code_location: CodeLocation
    observed_offset: NonNegativeInt
