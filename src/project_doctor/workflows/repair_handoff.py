"""Export evidence-checked persisted findings for an independent repair session."""

from __future__ import annotations

from typing import Any

from project_doctor.features.diagnosis.ports import EvidenceReader
from project_doctor.features.repair.gates import validate_repair_handoff
from project_doctor.workflows.task_ports import TaskStore


async def export_repair_handoff(
    store: TaskStore, reader: EvidenceReader, task_id: str
) -> dict[str, Any]:
    """Describe only diagnosis facts; repair still decides whether to change code."""
    bundle = await store.load_bundle(task_id)
    if bundle.task.id != task_id or bundle.task.status not in {"completed", "partial"}:
        raise ValueError("repair handoff requires a finished persisted diagnosis task")
    candidates: list[dict[str, Any]] = []
    for finding in bundle.findings:
        if finding.kind not in {"slow_query", "n_plus_one", "deep_pagination"} or (
            finding.status not in {"lead", "verified"}
        ):
            continue
        validate_repair_handoff(finding, bundle)
        if not (await reader.verify(finding.evidence_refs)).valid:
            raise ValueError("diagnostic handoff evidence is unavailable or corrupt")
        candidates.append(
            {
                "finding_id": finding.id,
                "kind": finding.kind,
                "status": finding.status,
                "scenario_id": finding.scenario_id,
                "experiment_ids": finding.experiment_ids,
                "sql_call_ids": finding.sql_call_ids,
                "code_locations": [item.model_dump(mode="json") for item in finding.code_locations],
                "evidence_refs": [item.model_dump(mode="json") for item in finding.evidence_refs],
                "recommendation": (
                    finding.recommendation.model_dump(mode="json")
                    if finding.recommendation is not None else None
                ),
                "limitations": finding.limitations,
            }
        )
    return {
        "task_id": bundle.task.id,
        "source_commit": bundle.task.project.commit,
        "context": {"task_id": bundle.task.id},
        "candidates": candidates,
    }
