"""Diagnosis-owned independent repair-effect comparison."""

from __future__ import annotations

from statistics import median

from project_doctor.features.diagnosis.compare import MeasurementPolicy, distinguishable
from project_doctor.models.deep_pagination import DeepPaginationSpec
from project_doctor.models.finding import Finding
from project_doctor.models.n_plus_one import BatchQuerySpec
from project_doctor.models.repair import RepairComparison, RepairRun


def evaluate_retest(
    finding: Finding,
    baseline: RepairRun,
    patched: RepairRun,
    policy: MeasurementPolicy | None = None,
) -> RepairComparison:
    """Compare independent old/new builds; refuse an unsupported benefit claim."""
    spec = finding.fix_spec
    if not isinstance(spec, BatchQuerySpec) or spec.strategy != "batch_in":
        raise ValueError("repair retest requires batch_in fix_spec")
    _validate_common(finding, baseline, patched)
    all_samples = baseline.samples + patched.samples
    for item in all_samples:
        if not item.parent_keys or not set(item.child_parameters + item.batch_parameters).issubset(
            set(item.parent_keys)
        ):
            raise ValueError("repair retest cannot prove parent/child parameter provenance")
    if any(item.child_count < spec.observed_child_count for item in baseline.samples):
        raise ValueError("repair baseline did not reproduce the child-query count")
    if any(item.sql_count < item.child_count for item in baseline.samples):
        raise ValueError("repair baseline SQL count is inconsistent")
    baseline_fixed_queries = min(item.sql_count - item.child_count for item in baseline.samples)
    if any(
        item.child_count > 0 or item.sql_count > baseline_fixed_queries + 1
        for item in patched.samples
    ):
        raise ValueError("repair did not collapse N+1 queries")
    if any(
        old.parent_rows_examined != new.parent_rows_examined
        for old, new in zip(baseline.samples, patched.samples, strict=True)
    ):
        raise ValueError("repair changed the parent scan workload")
    _require_distinguishable_gain(baseline, patched, policy)
    return _comparison(finding, baseline, patched)


def evaluate_slow_query_retest(
    finding: Finding,
    baseline: RepairRun,
    patched: RepairRun,
    policy: MeasurementPolicy | None = None,
) -> RepairComparison:
    """Require actual target-SQL work and request latency to improve together."""
    if finding.kind != "slow_query":
        raise ValueError("slow-query verifier requires a slow-query finding")
    _validate_common(finding, baseline, patched)
    _require_sql_work_gain(baseline, patched, policy)
    _require_distinguishable_gain(baseline, patched, policy)
    return _comparison(finding, baseline, patched)


def evaluate_deep_pagination_retest(
    finding: Finding,
    baseline: RepairRun,
    patched: RepairRun,
    policy: MeasurementPolicy | None = None,
) -> RepairComparison:
    """Prove an equivalent keyset result and less work on the same deep page."""
    spec = finding.fix_spec
    if not isinstance(spec, DeepPaginationSpec) or spec.strategy != "keyset":
        raise ValueError("deep-pagination source verifier only supports keyset")
    _validate_common(finding, baseline, patched)
    if any(
        sample.target_offset is None or sample.target_offset < spec.observed_offset
        for sample in baseline.samples
    ):
        raise ValueError("deep-pagination baseline did not reproduce the diagnosed offset")
    if any(
        sample.target_offset is not None or sample.target_uses_keyset is not True
        for sample in patched.samples
    ):
        raise ValueError("patched query did not use a cursor without OFFSET")
    _require_sql_work_gain(baseline, patched, policy)
    _require_distinguishable_gain(baseline, patched, policy)
    return _comparison(finding, baseline, patched)


def _require_sql_work_gain(
    baseline: RepairRun, patched: RepairRun, policy: MeasurementPolicy | None
) -> None:
    old_rows = [sample.target_rows_examined for sample in baseline.samples]
    new_rows = [sample.target_rows_examined for sample in patched.samples]
    old_sql_ms = [sample.target_duration_ms for sample in baseline.samples]
    new_sql_ms = [sample.target_duration_ms for sample in patched.samples]
    if any(value is None for value in old_rows + new_rows + old_sql_ms + new_sql_ms):
        raise ValueError("repair retest lacks actual target-SQL measurements")
    measured_old_rows = [float(value) for value in old_rows if value is not None]
    measured_new_rows = [float(value) for value in new_rows if value is not None]
    measured_old_sql = [float(value) for value in old_sql_ms if value is not None]
    measured_new_sql = [float(value) for value in new_sql_ms if value is not None]
    threshold = policy or MeasurementPolicy()
    if not distinguishable(measured_old_rows, measured_new_rows, threshold):
        raise ValueError("repair did not measurably reduce diagnosed SQL work")
    if not distinguishable(measured_old_sql, measured_new_sql, threshold):
        raise ValueError("repair did not measurably improve diagnosed SQL time")


def _validate_common(finding: Finding, baseline: RepairRun, patched: RepairRun) -> None:
    if (
        finding.recommendation is None
        or finding.recommendation.validation_status != "expected_mechanism"
    ):
        raise ValueError("repair retest requires an unretested recommendation")
    if baseline.task_id == patched.task_id or baseline.experiment_id == patched.experiment_id:
        raise ValueError("repair retest must use independent tasks and experiments")
    if baseline.image_digest == patched.image_digest:
        raise ValueError("patched retest reused the baseline image")
    if (
        not finding.code_locations
        or any(location.commit != baseline.source_commit for location in finding.code_locations)
        or patched.source_commit != baseline.source_commit
    ):
        raise ValueError("repair retest source commit does not match the finding")
    for field in (
        "snapshot_id",
        "scenario_id",
        "scenario_version",
        "observation_config_id",
        "cache_state",
    ):
        if getattr(baseline, field) != getattr(patched, field):
            raise ValueError(f"repair retest changed {field}")
    if baseline.scenario_id != finding.scenario_id:
        raise ValueError("repair retest used another scenario")
    if not baseline.restored or not patched.restored:
        raise ValueError("repair retest environment restoration is unverified")
    if not baseline.artifacts_verified or not patched.artifacts_verified:
        raise ValueError("repair retest artifacts are unverified")
    if {item.request_id for item in baseline.samples} & {
        item.request_id for item in patched.samples
    }:
        raise ValueError("repair retest reused request IDs")
    if len(baseline.samples) != len(patched.samples):
        raise ValueError("repair retest changed repetition count")
    all_samples = baseline.samples + patched.samples
    if not all(item.business_valid and item.lock_covered for item in all_samples):
        raise ValueError("repair retest business or lock evidence is incomplete")
    if len({item.result_digest for item in all_samples}) != 1:
        raise ValueError("repair retest changed business results")


def _require_distinguishable_gain(
    baseline: RepairRun, patched: RepairRun, policy: MeasurementPolicy | None
) -> None:
    old_latency = [item.latency_ms for item in baseline.samples]
    new_latency = [item.latency_ms for item in patched.samples]
    if not distinguishable(old_latency, new_latency, policy or MeasurementPolicy()):
        raise ValueError("repair gain is not distinguishable from measurement noise")


def _comparison(finding: Finding, baseline: RepairRun, patched: RepairRun) -> RepairComparison:
    old_latency = [item.latency_ms for item in baseline.samples]
    new_latency = [item.latency_ms for item in patched.samples]
    old_median = median(old_latency)
    new_median = median(new_latency)
    gain = (old_median - new_median) / old_median * 100
    return RepairComparison(
        source_task_id=finding.task_id,
        finding_id=finding.id,
        baseline_task_id=baseline.task_id,
        patched_task_id=patched.task_id,
        retest_experiment_ids=[baseline.experiment_id, patched.experiment_id],
        measured_gain_percent=gain,
        baseline_median_ms=old_median,
        patched_median_ms=new_median,
        evidence_ids=list(dict.fromkeys(baseline.evidence_ids + patched.evidence_ids)),
    )
