from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, JsonValue, field_validator, model_validator

from project_doctor.models.common import (
    Contract,
    Identifier,
    NonNegativeFloat,
    PositiveInt,
)
from project_doctor.models.dataset import DatasetProfile


class BusinessAssertion(Contract):
    json_pointer: str
    operator: Literal["equals", "exists"]
    expected: JsonValue = None

    @field_validator("json_pointer")
    @classmethod
    def valid_pointer(cls, value: str) -> str:
        if value and not value.startswith("/"):
            raise ValueError("use a JSON pointer, not a tool-specific expression")
        return value


class Assertions(Contract):
    status_code: Annotated[int, Field(ge=100, le=599, strict=True)]
    business: Annotated[list[BusinessAssertion], Field(min_length=1)]


class ParameterSource(Contract):
    source: Literal["user_sample", "repository", "inferred", "previous_step", "credential_ref"]
    reference: Identifier


class RequestStep(Contract):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    relative_path: str
    params: dict[str, JsonValue] = Field(default_factory=dict)
    parameter_sources: dict[str, ParameterSource] = Field(default_factory=dict)
    assertions: Assertions

    @field_validator("relative_path")
    @classmethod
    def relative_request_path(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            not value.startswith("/")
            or value.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or parsed.query
            or "\\" in value
            or ".." in parsed.path.split("/")
            or any(ord(char) < 32 for char in value)
        ):
            raise ValueError("request path must be relative to the isolated service")
        return value

    @model_validator(mode="after")
    def parameters_have_sources(self) -> RequestStep:
        if set(self.params) != set(self.parameter_sources):
            raise ValueError("every parameter requires exactly one source")
        return self


class LoadProfile(Contract):
    mode: Literal["serial", "concurrency", "arrival_rate"]
    concurrency: PositiveInt = 1
    arrival_rate_per_second: NonNegativeFloat | None = None

    @model_validator(mode="after")
    def consistent_load(self) -> LoadProfile:
        if self.mode == "serial" and self.concurrency != 1:
            raise ValueError("serial load requires concurrency=1")
        if self.mode == "arrival_rate":
            if not self.arrival_rate_per_second or self.arrival_rate_per_second <= 0:
                raise ValueError("arrival-rate mode requires a positive rate")
        elif self.arrival_rate_per_second is not None:
            raise ValueError("arrival rate only applies to arrival-rate mode")
        return self


class CacheProfile(Contract):
    state: Literal["cold", "warm", "unknown"]
    preparation_recipe_ref: Identifier | None = None
    notes: list[str] = Field(default_factory=list)


class Scenario(Contract):
    id: Identifier
    version: PositiveInt
    source: Literal["user_sample", "repository", "inferred"]
    purpose: Identifier
    preparation_recipe_ref: Identifier
    steps: Annotated[list[RequestStep], Field(min_length=1)]
    dataset: DatasetProfile
    load: LoadProfile
    cache: CacheProfile
    credential_refs: list[Identifier] = Field(default_factory=list)
    uncovered_paths: list[str] = Field(default_factory=list)
