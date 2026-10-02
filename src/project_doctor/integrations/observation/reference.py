"""Associate a SQL call with a source code location and its supporting evidence."""

from __future__ import annotations

from dataclasses import dataclass

from project_doctor.models.common import CodeLocation
from project_doctor.models.observation import SqlCall


@dataclass(frozen=True)
class CodeReference:
    path: str
    line: int
    association_evidence_ids: list[str]


def attach_code_location(call: SqlCall, reference: CodeReference, commit: str) -> SqlCall:
    """Bind a SQL call to the current commit's code location, keeping the call immutable."""
    location = CodeLocation(
        commit=commit,
        path=reference.path,
        line=reference.line,
        association_evidence_ids=reference.association_evidence_ids,
    )
    return call.model_copy(update={"code_location": location})
