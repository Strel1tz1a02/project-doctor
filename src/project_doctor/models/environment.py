from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from project_doctor.models.common import Contract, EnvironmentHealth, EvidenceRef, Identifier


def validate_service_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("use an HTTP(S) service URL without inline credentials/query/fragment")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("invalid service port") from exc
    return value


class ProjectInput(Contract):
    repo_path: Identifier
    commit: Identifier
    supplied_url: str
    recipe_ref: Identifier
    credential_refs: list[Identifier] = Field(default_factory=list)

    _validate_url = field_validator("supplied_url")(validate_service_url)


class EnvironmentHandle(Contract):
    result_type: Literal["environment"] = "environment"
    id: Identifier
    isolated_base_url: str
    fingerprint: Identifier
    baseline_snapshot_id: Identifier
    health: EnvironmentHealth

    _validate_url = field_validator("isolated_base_url")(validate_service_url)


class RestoreResult(Contract):
    result_type: Literal["restore"] = "restore"
    verified: bool
    fingerprint: Identifier | None = None
    snapshot_id: Identifier | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def verification_has_proof(self) -> RestoreResult:
        if self.verified and not (self.fingerprint and self.snapshot_id and self.evidence_refs):
            raise ValueError("verified restore requires fingerprint, snapshot and evidence")
        if not self.verified and not self.reason:
            raise ValueError("unverified restore requires a reason")
        return self
