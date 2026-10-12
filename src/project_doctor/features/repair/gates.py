"""Pure handoff and post-repair gates. These functions perform no I/O."""

from __future__ import annotations

from project_doctor.models.finding import Finding, Recommendation
from project_doctor.models.n_plus_one import BatchQuerySpec
from project_doctor.models.repair import RepairComparison
from project_doctor.models.task import TaskBundle


def validate_handoff(finding: Finding, bundle: TaskBundle) -> BatchQuerySpec:
    """Only a persisted, traceable N+1 target may enter source repair."""
    if finding.task_id != bundle.task.id or finding.id not in {item.id for item in bundle.findings}:
        raise ValueError("finding is not persisted in this task")
    if finding.kind != "n_plus_one" or finding.status not in {"lead", "verified"}:
        raise ValueError("only a diagnosed N+1 finding can enter repair")
    spec = finding.fix_spec
    if spec is None:
        raise ValueError("finding has no fix_spec")
    if not isinstance(spec, BatchQuerySpec):
        raise ValueError("repair requires an N+1 BatchQuerySpec")
    if spec.strategy != "batch_in":
        raise ValueError("Java/MyBatis adapter only supports batch_in")
    recommendation = finding.recommendation
    if recommendation is None or recommendation.validation_status != "expected_mechanism":
        raise ValueError("repair requires an unretested recommendation")
    if recommendation.mechanism != spec.strategy:
        raise ValueError("recommendation and fix_spec disagree")
    if spec.child_code_location.commit != bundle.task.project.commit:
        raise ValueError("source commit differs from diagnostic code location")
    if spec.child_code_location not in finding.code_locations:
        raise ValueError("fix_spec location differs from finding")
    if not any(item.id == finding.scenario_id for item in bundle.scenarios):
        raise ValueError("finding scenario is not persisted")
    experiments = [
        item for item in bundle.experiments if item.experiment_id in finding.experiment_ids
    ]
    if len(experiments) != len(set(finding.experiment_ids)) or not experiments:
        raise ValueError("finding experiment references are not persisted")
    call_ids = {
        call.id
        for experiment in experiments
        for obs in experiment.observations
        for call in obs.sql_calls
    }
    if not set(finding.sql_call_ids).issubset(call_ids):
        raise ValueError("finding SQL references are not persisted")
    if not spec.parent_sql_call_ids or not set(spec.parent_sql_call_ids).issubset(call_ids):
        raise ValueError("parent SQL references are unavailable")
    artifact_ids = {ref.artifact_id for ref in bundle.evidence_refs}
    if not finding.evidence_refs or not {ref.artifact_id for ref in finding.evidence_refs}.issubset(
        artifact_ids
    ):
        raise ValueError("finding evidence references are unavailable")
    location_evidence = set(spec.child_code_location.association_evidence_ids)
    if not location_evidence or not location_evidence.issubset(
        {ref.artifact_id for ref in finding.evidence_refs}
    ):
        raise ValueError("mapper location lacks finding evidence")
    return spec


def apply_retest_fields(finding: Finding, comparison: RepairComparison) -> Finding:
    """Revalidate a deep copy so only the agreed Recommendation fields can change."""
    if comparison.source_task_id != finding.task_id or comparison.finding_id != finding.id:
        raise ValueError("repair comparison belongs to another finding")
    if (
        finding.recommendation is None
        or finding.recommendation.validation_status != "expected_mechanism"
    ):
        raise ValueError("finding has no unretested recommendation")
    recommendation = Recommendation.model_validate(
        {
            **finding.recommendation.model_dump(),
            "validation_status": "retested",
            "measured_gain_percent": comparison.measured_gain_percent,
            "retest_experiment_ids": comparison.retest_experiment_ids,
        }
    )
    return Finding.model_validate(
        {**finding.model_dump(), "recommendation": recommendation.model_dump()}
    )
