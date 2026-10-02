"""Explicit settings passed at composition time; no global environment reads."""

from __future__ import annotations

import ipaddress
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from project_doctor.models.common import Contract, Identifier


class Settings(Contract):
    platform_dsn_ref: Identifier
    artifact_root: Path
    workspace_root: Path
    target_repo_root: Path
    allowed_target_network: str
    tool_timeouts: dict[str, float] = Field(min_length=1)
    model_config_ref: Identifier

    @field_validator("allowed_target_network")
    @classmethod
    def validate_network(cls, value: str) -> str:
        network = ipaddress.ip_network(value, strict=True)
        if network.prefixlen == 0:
            raise ValueError("unrestricted target networks are not allowed")
        return str(network)

    @field_validator("tool_timeouts")
    @classmethod
    def positive_timeouts(cls, value: dict[str, float]) -> dict[str, float]:
        import math

        if any(not math.isfinite(seconds) or seconds <= 0 for seconds in value.values()):
            raise ValueError("timeouts must be finite positive seconds")
        return value

    @model_validator(mode="after")
    def roots_are_separate(self) -> Settings:
        roots = [self.artifact_root, self.workspace_root, self.target_repo_root]
        if any(not root.is_absolute() for root in roots):
            raise ValueError("all roots must be absolute")
        resolved = [root.resolve() for root in roots]
        for index, root in enumerate(resolved):
            for other in resolved[index + 1 :]:
                if root.is_relative_to(other) or other.is_relative_to(root):
                    raise ValueError(
                        "artifact, isolated workspace and target repository must not overlap"
                    )
        return self
