import hashlib
from statistics import median
from typing import Literal

from project_doctor.features.diagnosis.compare import MeasurementPolicy, distinguishable
from project_doctor.features.diagnosis.gates import evidence_refs, experiment_failures
from project_doctor.models.experiment import ExperimentResult
from project_doctor.models.finding import ExcludedExplanation, Finding, Impact, Recommendation
from project_doctor.models.scenario import Scenario


def check_slow_query(
    result: ExperimentResult,
    scenario: Scenario,
    task_id: str,
    commit: str,
    policy: MeasurementPolicy | None = None,
) -> list[Finding]:
    """Only index-associated work reduction is proved; ALL or missing index alone is never proof."""
    policy = policy or MeasurementPolicy()
    issues = experiment_failures(result, scenario, commit)
    refs = evidence_refs(result)
    known_ids = {ref.artifact_id for ref in refs}
    calls = [call for item in result.observations for call in item.sql_calls]
    templates = sorted({call.normalized_sql for call in calls}) or ["SQL 未采集"]
    findings: list[Finding] = []
    for template in templates:
        insufficient = list(issues)
        relevant = [call for call in calls if call.normalized_sql == template]
        if not relevant:
            insufficient.append("缺少具体 SQL 观测。")
        expected_ids: set[str] = set()
        for call in relevant:
            expected_ids.update(call.plan_evidence_ids)
            if not call.plan_evidence_ids:
                insufficient.append("缺少执行计划原始证据。")
            if call.code_location:
                expected_ids.update(call.code_location.association_evidence_ids)
            for source in call.metric_sources.values():
                expected_ids.update(source.evidence_ids)
                if not source.evidence_ids:
                    insufficient.append("统计来源缺原始证据引用。")
            if call.rows_examined is None or call.duration_ms is None:
                insufficient.append("缺少实际扫描工作量或 SQL 耗时。")
            if call.lock_wait_ms is None or call.lock_wait_ms != 0:
                insufficient.append("锁等待尚未排除；本判据要求零锁等待的可比测量。")
            locks = call.lock_evidence
            if locks is None or locks.status != "covered_no_wait" or locks.coverage != "complete":
                insufficient.append("锁等待覆盖证据不完整；轮询空结果不能证明零等待。")
            elif locks:
                expected_ids.update(ref.artifact_id for ref in locks.evidence_refs)
        if not expected_ids.issubset(known_ids) or not refs:
            insufficient.append("证据引用不完整。")
        groups = [
            [
                (item, [call for call in item.sql_calls if call.normalized_sql == template])
                for item in result.observations
                if item.level == level
            ]
            for level in ("baseline", "candidate_index")
        ]
        if any(len(group_calls) != 1 for group in groups for _, group_calls in group):
            insufficient.append("单请求同模板多次调用，暂不支持该根因判定。")
        sql_durations = [
            [float(call.duration_ms or 0) for _, cs in group for call in cs] for group in groups
        ]
        rows = [
            [float(call.rows_examined or 0) for _, cs in group for call in cs] for group in groups
        ]
        request_durations = [[item.latency_ms for item, _ in group] for group in groups]
        duration_effect = distinguishable(sql_durations[0], sql_durations[1], policy)
        rows_available = bool(rows[0]) and bool(rows[1])
        rows_decreased = rows_available and median(rows[0]) > median(rows[1])
        request_effect = distinguishable(request_durations[0], request_durations[1], policy)

        # Three-way classification: keep "lead" for insufficient evidence, "verified" only
        # for a proven scan+latency reduction, and "unclassified" when the slow-query
        # hypothesis does not reproduce (already indexed / undersized data).
        status: Literal["verified", "lead", "unclassified"]
        if insufficient:
            status = "lead"
            reasons = list(insufficient)
        elif rows_decreased and duration_effect:
            status = "verified"
            reasons = []
        elif not rows_decreased:
            if bool(sql_durations[0]) and median(sql_durations[0]) < policy.minimum_delta_ms:
                status = "unclassified"
                reasons = [
                    "索引干预未降低实际扫描工作量，且基线 SQL 耗时低于最小可区分差异，"
                    "慢查询/全表扫描在当前数据与代码下未复现（已有可用索引或数据量过小）。"
                ]
            else:
                status = "lead"
                reasons = ["未证明索引干预降低实际扫描工作量；基线仍慢，慢查询根因未解决。"]
        else:
            status = "lead"
            reasons = ["扫描工作量下降，但 SQL 耗时变化不足以区分测量波动，无法证实延迟收益。"]

        verified = status == "verified"
        key = hashlib.sha256(f"{task_id}:{result.experiment_id}:{template}".encode()).hexdigest()[
            :20
        ]
        locations = [call.code_location for call in relevant if call.code_location is not None]
        findings.append(
            Finding(
                id=f"finding-{key}",
                task_id=task_id,
                kind="slow_query",
                status=status,
                scenario_id=scenario.id,
                experiment_ids=[result.experiment_id],
                sql_call_ids=[call.id for call in relevant],
                code_locations=list(
                    {(loc.commit, loc.path, loc.line): loc for loc in locations}.values()
                ),
                evidence_refs=refs,
                excluded_explanations=[
                    ExcludedExplanation(
                        explanation=(
                            "在固定数据／业务结果与缓存准备条件下，零锁等待测量和重复样本"
                            "排除已观测的锁等待与测量波动。"
                            if verified
                            else "锁竞争已被零锁等待与有界残差测量排除；索引干预未降低扫描工作量，"
                            "缺索引/全表扫描假设在当次数据与代码下未复现。"
                        ),
                        evidence_ids=sorted(known_ids),
                    )
                ]
                if verified or status == "unclassified"
                else [],
                impact=Impact(
                    method="intervention" if verified and request_effect else "unmeasured",
                    latency_delta_ms=median(request_durations[0]) - median(request_durations[1])
                    if verified and request_effect
                    else None,
                    affected_request_ids=[item.request_id for item in result.observations],
                    shared_sql_call_ids=[call.id for call in relevant],
                    uncertainty=["本次单变量索引对照，仅证明索引相关的访问工作量与 SQL 耗时变化。"],
                ),
                recommendation=(
                    Recommendation(
                        action="评估实验配方中的索引是否适合正式业务。",
                        mechanism="通过适用索引减少访问工作量；未覆盖其他慢查询原因。",
                        conditions=["核对过滤选择性、现有索引及真实数据分布。"],
                        costs=["索引存储、写入维护及部署代价。"],
                    )
                    if status != "unclassified"
                    else None
                ),
                limitations=list(
                    dict.fromkeys(
                        reasons
                        + [
                            "不自动宣称缺索引是所有慢查询的原因，不推断线上频率或业务 SLA。",
                            f"测量策略：重复≥{policy.minimum_repetitions}，离散度(IQR)容差≤"
                            f"max(相对{policy.maximum_relative_spread}×中位数, "
                            f"绝对{policy.minimum_absolute_spread_ms}ms)，"
                            f"最小差异>{policy.minimum_delta_ms}ms。",
                        ]
                    )
                ),
            )
        )
    return findings
