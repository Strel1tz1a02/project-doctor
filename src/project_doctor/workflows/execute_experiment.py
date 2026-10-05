"""Pure experiment execution logic: digests, budget math and result assembly."""

from __future__ import annotations

import hashlib
import json

from project_doctor.models.common import EvidenceRef
from project_doctor.models.environment import RestoreResult
from project_doctor.models.errors import Failure
from project_doctor.models.experiment import (
    ExperimentPhase,
    ExperimentResult,
    ExperimentSpec,
)
from project_doctor.models.observation import Observation


def experiment_input_digest(spec: ExperimentSpec) -> str:
    """The idempotency key for an experiment operation: the canonical spec bytes."""
    return hashlib.sha256(spec.model_dump_json().encode("utf-8")).hexdigest()


def needed_requests(spec: ExperimentSpec) -> int:
    """One business request per repetition per level (baseline and candidate_index)."""
    warmup = spec.warmup.requests_per_level if spec.warmup else 0
    return (spec.repetitions + warmup) * len(spec.levels)


def normalized_result_digest(body: object) -> str:
    """A stable digest of the de-identified business result, shared across both groups."""
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def determine_phase(failure: Failure | None, restore: RestoreResult | None) -> ExperimentPhase:
    """Finished only when there is no failure and the restore was verified."""
    if failure is None and restore is not None and restore.verified:
        return "finished"
    return "needs_reconcile"


def assemble_result(
    *,
    spec: ExperimentSpec,
    operation_id: str,
    observations: list[Observation],
    restore: RestoreResult | None,
    failure: Failure | None,
    evidence_refs: list[EvidenceRef],
) -> ExperimentResult:
    """Assemble a persisted result whose spec id, observations and restore are consistent."""
    return ExperimentResult(
        experiment_id=spec.id,
        operation_id=operation_id,
        phase=determine_phase(failure, restore),
        observations=observations,
        restore_result=restore,
        evidence_refs=evidence_refs,
        failure=failure,
        spec=spec,
    )
