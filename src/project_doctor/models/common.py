"""Shared units, identifiers and artifact references. No I/O occurs here."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
TaskStatus = Literal["created", "running", "blocked", "completed", "partial"]
ProblemKind = Literal["slow_query", "n_plus_one", "unclassified"]
EnvironmentHealth = Literal["available", "restoring", "quarantined"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    schema_version: Literal["0.1"] = "0.1"


def safe_relative_path(value: str) -> str:
    """Wire paths are POSIX-relative; filesystem containment is checked by A."""
    path = PurePosixPath(value)
    if (
        not value
        or value != value.strip()
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 for char in value)
        or path.is_absolute()
        or ".." in path.parts
        or str(path) == "."
    ):
        raise ValueError("expected a safe POSIX relative path")
    return value


class EvidenceRef(Contract):
    artifact_id: Identifier
    relative_path: str
    media_type: Identifier
    format_version: Identifier
    sha256: Sha256
    size_bytes: NonNegativeInt

    _validate_path = field_validator("relative_path")(safe_relative_path)


class CodeLocation(Contract):
    commit: Identifier
    path: str
    line: PositiveInt
    association_evidence_ids: Annotated[list[Identifier], Field(min_length=1)]

    _validate_path = field_validator("path")(safe_relative_path)


class EvidenceCheck(Contract):
    valid: bool
    missing_ids: list[Identifier] = Field(default_factory=list)
    corrupted_ids: list[Identifier] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_result(self) -> EvidenceCheck:
        if self.valid and (self.missing_ids or self.corrupted_ids or self.reasons):
            raise ValueError("valid evidence cannot include verification failures")
        if not self.valid and not (self.missing_ids or self.corrupted_ids or self.reasons):
            raise ValueError("invalid evidence requires a reason")
        return self


class Limits(Contract):
    max_wall_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    max_requests: PositiveInt
    max_experiments: PositiveInt
    max_artifact_bytes: PositiveInt
    restore_reserve_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def recovery_fits_budget(self) -> Limits:
        if self.restore_reserve_seconds >= self.max_wall_seconds:
            raise ValueError("restore reserve must be smaller than the wall-time budget")
        return self


class Usage(Contract):
    wall_seconds: NonNegativeFloat = 0
    requests: NonNegativeInt = 0
    experiments: NonNegativeInt = 0
    artifact_bytes: NonNegativeInt = 0
