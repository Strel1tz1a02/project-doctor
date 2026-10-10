"""N+1 query diagnosis: repeated homogeneous child queries within one valid request.

The proof is structural, not access-path based: a single ``request_id`` issues
``1 (parent) + N (child)`` queries, the N children share one parameterized
``template_sql`` and one ``code_location``, their literals are distinct, and their
count correlates with the parent's ``rows_returned``. ``verified`` additionally
requires a batch-intervention candidate level that collapses the loop to one batch
query with distinguishable latency and an unchanged parent scan.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from statistics import median
from typing import Literal

from project_doctor.features.diagnosis.compare import MeasurementPolicy, distinguishable
from project_doctor.features.diagnosis.gates import evidence_refs, experiment_failures
from project_doctor.features.diagnosis.sql_shape import extract_sql_literals, parameterize_sql
from project_doctor.models.common import CodeLocation, EvidenceRef
from project_doctor.models.experiment import ExperimentResult
from project_doctor.models.finding import ExcludedExplanation, Finding, Impact, Recommendation
from project_doctor.models.n_plus_one import BatchQuerySpec, FixStrategy
from project_doctor.models.observation import Observation, SqlCall
from project_doctor.models.scenario import Scenario

_KEY_EQ = re.compile(r"WHERE\s+`?([A-Za-z_]\w*)`?\s*=\s*\?", re.IGNORECASE)


def _template_of(call: SqlCall) -> str:
    return call.template_sql or parameterize_sql(call.normalized_sql)


def _location_key(location: CodeLocation | None) -> tuple[str, str, int] | None:
    return (location.commit, location.path, location.line) if location else None


def _child_key_column(template: str) -> str | None:
    match = _KEY_EQ.search(template)
    return match.group(1) if match else None


def _per_request_child_count(observations: list[Observation], template: str) -> list[int]:
    return [
        sum(1 for call in item.sql_calls if _template_of(call) == template) for item in observations
    ]


def _rows_examined(observations: list[Observation], template: str | None) -> list[float]:
    if template is None:
        return []
    return [
        float(call.rows_examined)
        for item in observations
        for call in item.sql_calls
        if _template_of(call) == template and call.rows_examined is not None
    ]


@dataclass
class _Pattern:
    template: str
    code_location: CodeLocation
    child_calls: list[SqlCall] = field(default_factory=list)
    parent_calls: list[SqlCall] = field(default_factory=list)


def _detect_patterns(observations: list[Observation]) -> list[_Pattern]:
    """Find homogeneous child queries repeated within a single request.

    A template qualifies when it appears at least twice inside one request and all
    occurrences share a single code location. Requests that repeat the same
    template + location accumulate into one pattern, so a one-off is not confused
    with a loop.
    """
    patterns: dict[tuple[str, str, int], _Pattern] = {}
    for item in observations:
        grouped: dict[str, list[SqlCall]] = {}
        for call in item.sql_calls:
            grouped.setdefault(_template_of(call), []).append(call)
        for template, calls in grouped.items():
            if len(calls) < 2:
                continue
            locations = {_location_key(call.code_location) for call in calls}
            if len(locations) != 1:
                continue
            key = next(iter(locations))
            if key is None:
                continue
            location = calls[0].code_location
            assert location is not None
            pattern = patterns.get(key)
            if pattern is None:
                pattern = patterns[key] = _Pattern(template=template, code_location=location)
            elif pattern.template != template:
                # One loop site emitting different shapes is not one homogeneous N+1.
                continue
            pattern.child_calls.extend(calls)
            pattern.parent_calls.extend(
                call for call in item.sql_calls if _template_of(call) != template
            )
    return list(patterns.values())


def check_n_plus_one(
    result: ExperimentResult,
    scenario: Scenario,
    task_id: str,
    commit: str,
    policy: MeasurementPolicy | None = None,
) -> list[Finding]:
    """Grade an N+1 experiment: ``verified`` only via proven batch query-count collapse."""
    policy = policy or MeasurementPolicy()
    issues = experiment_failures(result, scenario, commit)
    refs = evidence_refs(result)
    known_ids = {ref.artifact_id for ref in refs}
    baseline = [item for item in result.observations if item.level == "baseline"]
    batched = [item for item in result.observations if item.level == "candidate_batch"]

    patterns = _detect_patterns(baseline)
    if not patterns:
        return [_no_pattern_finding(result, scenario, task_id, issues, refs)]
    return [
        _grade(
            pattern, baseline, batched, result, scenario, task_id, policy, issues, refs, known_ids
        )
        for pattern in patterns
    ]


def _no_pattern_finding(
    result: ExperimentResult,
    scenario: Scenario,
    task_id: str,
    issues: list[str],
    refs: list[EvidenceRef],
) -> Finding:
    key = hashlib.sha256(
        f"{task_id}:{result.experiment_id}:no-n-plus-one".encode()
    ).hexdigest()[:20]
    status: Literal["lead", "unclassified"] = "lead" if issues else "unclassified"
    reasons = list(issues) if issues else []
    reasons.append(
        "基线请求内未检测到同一请求内同构子查询的重复（无 ≥2 次共享代码位置的参数化模板），"
        "N+1 在当前数据与代码下未复现；这不排除其他性能问题。"
    )
    return Finding(
        id=f"finding-{key}",
        task_id=task_id,
        kind="n_plus_one",
        status=status,
        scenario_id=scenario.id,
        experiment_ids=[result.experiment_id],
        sql_call_ids=[],
        code_locations=[],
        evidence_refs=refs,
        excluded_explanations=[],
        impact=Impact(
            method="unmeasured",
            uncertainty=["本次批量干预未复现同构子查询重复，N+1 机制未被证明。"],
        ),
        recommendation=None,
        limitations=reasons,
    )


def _grade(
    pattern: _Pattern,
    baseline: list[Observation],
    batched: list[Observation],
    result: ExperimentResult,
    scenario: Scenario,
    task_id: str,
    policy: MeasurementPolicy,
    issues: list[str],
    refs: list[EvidenceRef],
    known_ids: set[str],
) -> Finding:
    insufficient = list(issues)
    expected_ids: set[str] = set()
    for call in pattern.child_calls + pattern.parent_calls:
        for source in call.metric_sources.values():
            expected_ids.update(source.evidence_ids)
            if not source.evidence_ids:
                insufficient.append("统计来源缺原始证据引用。")
        if call.duration_ms is None:
            insufficient.append("缺少 SQL 耗时实测值。")
        locks = call.lock_evidence
        if locks is None or locks.status == "unknown" or locks.coverage != "complete":
            insufficient.append("锁等待覆盖证据不完整；不能证明零等待。")
        elif locks:
            expected_ids.update(ref.artifact_id for ref in locks.evidence_refs)
            if call.lock_wait_ms is None:
                insufficient.append("缺少锁等待实测指标。")
    if not expected_ids.issubset(known_ids) or not refs:
        insufficient.append("证据引用不完整。")

    literals = {
        literal
        for call in pattern.child_calls
        for literal in (call.literal_parameters or extract_sql_literals(call.normalized_sql))
    }
    if len(literals) < 2:
        insufficient.append("子查询字面参数未呈现互异的关联键值，无法证明循环内逐值查询。")

    key_column = _child_key_column(pattern.template)
    if key_column is None:
        insufficient.append("无法从子查询模板提取关联键列，无法结构化交接修复目标。")

    parent = max(pattern.parent_calls, key=lambda call: call.rows_returned or 0, default=None)
    parent_rows = parent.rows_returned if parent else None
    parent_template = _template_of(parent) if parent else None
    child_counts = _per_request_child_count(baseline, pattern.template)
    observed_child_count = max(child_counts, default=0)
    if parent is None or parent_rows is None:
        insufficient.append("缺少父查询或其返回行数，无法证明子查询次数与父结果集相关。")
    elif parent_rows < observed_child_count:
        insufficient.append("子查询次数超过父查询返回行数，计数相关不成立。")

    baseline_latency = [item.latency_ms for item in baseline]
    batched_latency = [item.latency_ms for item in batched]
    request_effect = (
        distinguishable(baseline_latency, batched_latency, policy) if batched_latency else False
    )
    batch_child_counts = _per_request_child_count(batched, pattern.template)
    loop_collapsed = (
        bool(child_counts)
        and bool(batch_child_counts)
        and median(child_counts) >= 2
        and median(batch_child_counts) <= 1
    )
    baseline_parent_rows = _rows_examined(baseline, parent_template)
    batched_parent_rows = _rows_examined(batched, parent_template)
    parent_scan_unchanged = (
        bool(baseline_parent_rows)
        and bool(batched_parent_rows)
        and median(baseline_parent_rows) == median(batched_parent_rows)
    )

    residual = max(
        (
            (call.lock_wait_ms or 0.0) + (call.lock_evidence.residual_ms or 0.0)
            for call in pattern.child_calls + pattern.parent_calls
            if call.lock_evidence is not None
        ),
        default=0.0,
    )
    if residual and (
        (not request_effect and residual >= policy.minimum_delta_ms)
        or (
            request_effect
            and median(baseline_latency) - median(batched_latency)
            <= residual + policy.minimum_delta_ms
        )
    ):
        insufficient.append("实测锁等待或残差上界足以解释耗时差异，不能排除锁因素。")

    status: Literal["verified", "lead"]
    if insufficient:
        status = "lead"
        reasons = list(insufficient)
    elif loop_collapsed and request_effect and parent_scan_unchanged:
        status = "verified"
        reasons = []
    elif not batched:
        status = "lead"
        reasons = ["检测到 N+1 结构，但没有批量化干预实验证实查询次数下降，无法证实收益。"]
    else:
        status = "lead"
        reasons = [
            "批量化干预未同时满足查询次数下降、耗时可区分与父查询扫描量不变，无法证实 N+1 收益。"
        ]

    verified = status == "verified"
    strategy: FixStrategy = "batch_in"
    child_ids = [call.id for call in pattern.child_calls]
    parent_ids = [call.id for call in pattern.parent_calls]
    fix_spec = None
    if key_column is not None:
        fix_spec = BatchQuerySpec(
            strategy=strategy,
            child_template=pattern.template,
            key_column=key_column,
            child_code_location=pattern.code_location,
            observed_child_count=observed_child_count,
            parent_sql_call_ids=parent_ids,
        )
    key = hashlib.sha256(
        f"{task_id}:{result.experiment_id}:{pattern.template}".encode()
    ).hexdigest()[:20]
    limitations = list(
        dict.fromkeys(
            reasons
            + [
                (
                    "N+1 判定依据是随父结果集大小线性增长的额外数据库往返次数，"
                    "而非单条 SQL 的执行计划。"
                ),
                (
                    f"修复策略 {strategy} 依据批量干预观察到的查询形状推断；"
                    "joinedload/selectinload 未单独实验。"
                ),
                (
                    "循环调用代码位置取子查询的 SQL 定义位置（mapper 方法）；"
                    "Java 循环代码行需修复层按该方法回溯。"
                ),
                "结论依赖列表页大小：逐条查询开销在 size 较小时可忽略。",
                f"测量策略：重复≥{policy.minimum_repetitions}，离散度(IQR)容差≤"
                f"max(相对{policy.maximum_relative_spread}×中位数, "
                f"绝对{policy.minimum_absolute_spread_ms}ms)，最小差异>{policy.minimum_delta_ms}ms。",
            ]
        )
    )
    return Finding(
        id=f"finding-{key}",
        task_id=task_id,
        kind="n_plus_one",
        status=status,
        scenario_id=scenario.id,
        experiment_ids=[result.experiment_id],
        sql_call_ids=child_ids,
        code_locations=[pattern.code_location],
        evidence_refs=refs,
        excluded_explanations=(
            [
                ExcludedExplanation(
                    explanation=(
                        "固定数据、业务结果与缓存条件下，批量干预使子查询次数由 N+1 降到 1～2，"
                        "请求耗时下降超过测量门槛及锁等待残差，且父查询扫描量不变；"
                        "仅排除足以解释本次耗时差异的已覆盖锁因素。"
                    ),
                    evidence_ids=sorted(known_ids),
                )
            ]
            if verified
            else []
        ),
        impact=Impact(
            method="intervention" if verified and request_effect else "unmeasured",
            latency_delta_ms=median(baseline_latency) - median(batched_latency)
            if verified and request_effect
            else None,
            affected_request_ids=[item.request_id for item in result.observations],
            shared_sql_call_ids=child_ids,
            uncertainty=["本次单变量批量干预，仅证明调用次数相关的耗时变化。"],
        ),
        recommendation=(
            Recommendation(
                action=(
                    f"把循环内的逐条查询改为一次批量查询（{strategy}），"
                    "消除随列表条数线性增长的数据库往返。"
                ),
                mechanism=strategy,
                conditions=[
                    f"子查询关联键列为 {key_column}。",
                    "父结果集大小与子查询次数相关，须确认去重与返回顺序。",
                ],
                costs=["IN 列表过长需分批", "需保持业务结果的去重与顺序"],
            )
            if fix_spec is not None
            else None
        ),
        fix_spec=fix_spec,
        limitations=limitations,
    )
