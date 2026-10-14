"""Structured evidence from an independent source-repair retest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from project_doctor.models.common import (
    CodeLocation,
    Contract,
    EvidenceRef,
    Identifier,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    Sha256,
    safe_relative_path,
)


@dataclass(frozen=True)
class RepairTarget:
    root: Path
    source_commit: str
    mapper_path: str
    mapper_line: int
    mapper_method: str
    child_table: str
    key_column: str
    mapper_sha256: str
    mapper_context: str
    caller_path: str
    caller_line: int
    parent_key_column: str
    caller_sha256: str
    caller_context: str


@dataclass(frozen=True)
class SourceRepairTarget:
    """Versioned application-source scope, independent of a fix mechanism."""

    root: Path
    source_commit: str
    locations: tuple[CodeLocation, ...]
    allowed_hashes: dict[str, str]
    contexts: dict[str, str]


class SourceFileView(Contract):
    path: str
    sha256: Sha256
    context: str | None = None

    _safe_path = field_validator("path")(safe_relative_path)


class CodeRepairTargetView(Contract):
    finding_id: Identifier
    source_commit: Identifier
    target_sha256: Sha256
    diagnosed_locations: list[CodeLocation] = Field(min_length=1)
    allowed_files: list[SourceFileView] = Field(min_length=1)


class RepairSample(Contract):
    request_id: Identifier
    business_valid: bool
    result_digest: Sha256
    latency_ms: NonNegativeFloat
    sql_count: NonNegativeInt
    child_count: NonNegativeInt
    parent_rows_examined: NonNegativeInt
    parent_keys: list[Identifier]
    child_parameters: list[Identifier] = Field(default_factory=list)
    batch_parameters: list[Identifier] = Field(default_factory=list)
    lock_covered: bool
    target_rows_examined: NonNegativeInt | None = None
    target_duration_ms: NonNegativeFloat | None = None
    target_offset: NonNegativeInt | None = None
    target_uses_keyset: bool | None = None


class RepairRun(Contract):
    task_id: Identifier
    experiment_id: Identifier
    source_commit: Identifier
    image_digest: Identifier
    snapshot_id: Identifier
    scenario_id: Identifier
    scenario_version: PositiveInt
    observation_config_id: Identifier
    cache_state: Literal["cold", "warm", "unknown"]
    samples: list[RepairSample] = Field(min_length=3)
    restored: bool
    artifacts_verified: bool
    evidence_ids: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_requests(self) -> RepairRun:
        ids = [sample.request_id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise ValueError("repair run has duplicate request IDs")
        if not self.image_digest.startswith("sha256:") or len(self.image_digest) != 71:
            raise ValueError("repair run needs a Docker image digest")
        return self


class RepairComparison(Contract):
    source_task_id: Identifier
    finding_id: Identifier
    baseline_task_id: Identifier
    patched_task_id: Identifier
    retest_experiment_ids: list[Identifier] = Field(min_length=2, max_length=2)
    measured_gain_percent: NonNegativeFloat
    baseline_median_ms: NonNegativeFloat
    patched_median_ms: NonNegativeFloat
    evidence_ids: list[Identifier] = Field(min_length=1)


class RepairTargetView(Contract):
    finding_id: Identifier
    source_commit: Identifier
    target_sha256: Sha256
    mapper_path: str
    mapper_line: PositiveInt
    mapper_method: Identifier
    child_table: Identifier
    key_column: Identifier
    mapper_sha256: Sha256
    mapper_context: str
    caller_path: str
    caller_line: PositiveInt
    parent_key_column: Identifier
    caller_sha256: Sha256
    caller_context: str

    _safe_mapper_path = field_validator("mapper_path")(safe_relative_path)
    _safe_caller_path = field_validator("caller_path")(safe_relative_path)


class RepairRecord(Contract):
    """Durable state for one proposed patch against one persisted finding."""

    result_type: Literal["repair"] = "repair"
    id: Identifier
    task_id: Identifier
    finding_id: Identifier
    operation_id: Identifier
    attempt_id: Identifier
    status: Literal["preparing", "built", "retesting", "retested", "failed", "needs_reconcile"]
    source_commit: Identifier
    patch_sha256: Sha256
    parent_key_column: Identifier | None = None
    source_sha256: Sha256 | None = None
    baseline_source_sha256: Sha256 | None = None
    workspace_name: Identifier | None = None
    baseline_image_digest: Identifier | None = None
    patched_image_digest: Identifier | None = None
    patch_ref: EvidenceRef | None = None
    build_ref: EvidenceRef | None = None
    retest_refs: list[EvidenceRef] = Field(default_factory=list)
    baseline_run: RepairRun | None = None
    patched_run: RepairRun | None = None
    comparison: RepairComparison | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def consistent_state(self) -> RepairRecord:
        if self.status in {"built", "retesting", "retested"} and not (
            self.source_sha256
            and self.baseline_source_sha256
            and self.workspace_name
            and self.baseline_image_digest
            and self.patched_image_digest
            and self.patch_ref
            and self.build_ref
        ):
            raise ValueError("built repair requires source, image and patch/build evidence")
        if self.status == "retested" and not (
            self.comparison and self.retest_refs and self.baseline_run and self.patched_run
        ):
            raise ValueError("retested repair requires comparison and retest evidence")
        if self.status == "retested" and not self.baseline_image_digest:
            raise ValueError("retested repair requires the original image digest")
        for digest in (self.baseline_image_digest, self.patched_image_digest):
            if digest is not None and (not digest.startswith("sha256:") or len(digest) != 71):
                raise ValueError("repair image identity must be a Docker digest")
        if self.comparison is not None and (
            self.comparison.source_task_id != self.task_id
            or self.comparison.finding_id != self.finding_id
        ):
            raise ValueError("repair comparison belongs to another finding")
        if self.status == "retested" and self.comparison is not None:
            assert self.baseline_run is not None and self.patched_run is not None
            if (
                self.baseline_run.task_id != self.comparison.baseline_task_id
                or self.patched_run.task_id != self.comparison.patched_task_id
                or [
                    self.baseline_run.experiment_id,
                    self.patched_run.experiment_id,
                ]
                != self.comparison.retest_experiment_ids
                or self.baseline_run.image_digest != self.baseline_image_digest
                or self.patched_run.image_digest != self.patched_image_digest
            ):
                raise ValueError("repair retest runs differ from the comparison")
        if self.status in {"failed", "needs_reconcile"} and not self.failure_reason:
            raise ValueError("failed or unknown repair requires a reason")
        return self
