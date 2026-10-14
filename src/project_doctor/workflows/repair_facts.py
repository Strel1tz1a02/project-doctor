"""Derive handoff/repair registration facts from a persisted task bundle.

The evaluation exporter (``scripts/export_evaluation_run.py``) only merges
explicitly registered ``handoff.json`` / ``repair.json`` files and never
infers them. This module is the single place that turns durable repair state
into those registrations, with hard refusals instead of half-facts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from project_doctor.features.repair.patch_files import extract_patch_locations
from project_doctor.integrations.artifacts.verify import resolve_contained
from project_doctor.models.repair import RepairRecord
from project_doctor.models.task import TaskBundle

PATCH_SUCCESS_STATES = {"built", "retesting", "retested"}


@dataclass(frozen=True)
class RepairFacts:
    handoff: dict[str, object] | None
    repair: dict[str, object] | None
    notes: tuple[str, ...] = field(default=())


def _patch_text(root: Path, record: RepairRecord) -> str:
    ref = record.patch_ref
    assert ref is not None  # guarded by the caller's patch_present check
    try:
        raw = resolve_contained(root, ref.relative_path).read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError("patch artifact is missing or corrupted") from exc
    if len(raw) != ref.size_bytes or hashlib.sha256(raw).hexdigest() != ref.sha256:
        raise ValueError("patch artifact is missing or corrupted")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("patch artifact is missing or corrupted") from exc


def build_repair_facts(
    bundle: TaskBundle,
    *,
    artifacts_root: Path,
    repair_session_id: str | None,
    repair_session_transcript: Path | None = None,
    repair_decision_id: str | None = None,
    finding_id: str | None = None,
) -> RepairFacts:
    diagnosis_session_id = bundle.task.correlation.agh_session_id or ""
    notes: list[str] = []
    # An independent repair session is the evidence that a repair Agent actually
    # ran; without it neither restraint nor a handoff chain may be registered.
    session_independent = bool(repair_session_id) and repair_session_id != diagnosis_session_id

    def persisted(finding: str) -> bool:
        return any(f.id == finding and f.task_id == bundle.task.id for f in bundle.findings)

    def handoff(repair_id: str, finding: str, build_result: str) -> dict[str, object] | None:
        if not session_independent:
            notes.append("repair session is missing or not independent; handoff omitted")
            return None
        return {
            "task_id": bundle.task.id,
            "finding_id": finding,
            "repair_id": repair_id,
            "source_commit": bundle.task.project.commit,
            "diagnosis_session_id": diagnosis_session_id,
            "repair_session_id": repair_session_id,
            "finding_from_this_run": persisted(finding),
            "build_result": build_result,
        }

    if not bundle.repairs:
        # Restraint needs an auditable independent repair session: a no-change
        # decision must not be credited from a missing session.
        transcript_ok = (
            repair_session_transcript is not None
            and repair_session_transcript.is_file()
            and bool(
                repair_session_transcript.read_text(encoding="utf-8", errors="replace").strip()
            )
        )
        if not (session_independent and transcript_ok):
            if not session_independent:
                notes.append("repair session is missing or not independent; restraint unregistered")
            return RepairFacts(handoff=None, repair=None, notes=tuple(notes))
        repair = {
            "attempted": False,
            "patch_present": False,
            "patch_files": [],
            "gain_attributable": False,
        }
        if repair_decision_id is None:
            notes.append("no repair decision id; handoff omitted")
            return RepairFacts(handoff=None, repair=repair, notes=tuple(notes))
        if finding_id is None or not persisted(finding_id):
            raise ValueError("no-change handoff requires a persisted finding from this task")
        return RepairFacts(
            handoff=handoff(repair_decision_id, finding_id, "skipped"),
            repair=repair,
            notes=tuple(notes),
        )

    if len(bundle.repairs) != 1:
        raise ValueError("multiple repair records are not supported yet")
    record = bundle.repairs[0]
    if record.task_id != bundle.task.id:
        raise ValueError("repair record belongs to another task")
    if not persisted(record.finding_id):
        raise ValueError("repair finding is not persisted in this task")
    if record.source_commit != bundle.task.project.commit:
        raise ValueError("repair source commit differs from the diagnosed commit")

    patch_present = bool(record.patch_ref and record.status in PATCH_SUCCESS_STATES)
    patch_files = (
        extract_patch_locations(_patch_text(artifacts_root, record)) if patch_present else []
    )
    build_result = "ok" if record.build_ref is not None and record.status != "failed" else "failed"
    gain = bool(
        record.status == "retested"
        and record.comparison is not None
        and record.patched_run is not None
        and all(sample.business_valid for sample in record.patched_run.samples)
    )
    return RepairFacts(
        handoff=handoff(record.id, record.finding_id, build_result),
        repair={
            "attempted": True,
            "patch_present": patch_present,
            "patch_files": patch_files,
            "gain_attributable": gain,
        },
        notes=tuple(notes),
    )
