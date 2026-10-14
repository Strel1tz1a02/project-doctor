"""Deep-pagination diagnosis: a large OFFSET forces the database to scan-and-discard.

``LIMIT N OFFSET M`` costs O(M) regardless of index: the executor walks the first M
rows and throws them away before returning the N requested. Detection is a single
SQL call whose text carries a positive ``OFFSET`` and whose ``rows_examined`` is
dominated by the skipped rows. ``verified`` additionally requires a keyset
intervention candidate level that drops ``rows_examined`` to page-size scale with
distinguishable latency and an identical business result.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from statistics import median
from typing import Literal

from project_doctor.features.diagnosis.compare import MeasurementPolicy, distinguishable
from project_doctor.features.diagnosis.gates import evidence_refs, experiment_failures
from project_doctor.features.diagnosis.sql_shape import parameterize_sql
from project_doctor.models.common import CodeLocation, EvidenceRef
from project_doctor.models.deep_pagination import DeepPaginationSpec, PaginationStrategy
from project_doctor.models.experiment import ExperimentResult
from project_doctor.models.finding import ExcludedExplanation, Finding, Impact, Recommendation
from project_doctor.models.observation import Observation, SqlCall
from project_doctor.models.scenario import Scenario

_LIMIT_CLAUSE = re.compile(
    r"LIMIT\s+(?:"
    r"(?P<count>\d+)\s+OFFSET\s+(?P<offset_after>\d+)"
    r"|(?P<offset_before>\d+)\s*,\s*(?P<count_comma>\d+)"
    r"|(?P<count_only>\d+)"
    r")",
    re.IGNORECASE,
)
_ORDER_BY = re.compile(
    r"ORDER\s+BY\s+(?:\w+\.)?`?([A-Za-z_]\w*)`?(?:\s+(?:ASC|DESC))?", re.IGNORECASE
)


def _template_of(call: SqlCall) -> str:
    return call.template_sql or parameterize_sql(call.normalized_sql)


def _location_key(location: CodeLocation | None) -> tuple[str, str, int] | None:
    return (location.commit, location.path, location.line) if location else None


def extract_limit_offset(sql: str) -> tuple[int | None, int | None]:
    """Return ``(limit, offset)`` for the three MySQL LIMIT spellings, else ``(None, None)``.

    Covers ``LIMIT n OFFSET m``, ``LIMIT m, n`` (offset first), and plain
    ``LIMIT n`` (offset zero).
    """
    match = _LIMIT_CLAUSE.search(sql)
    if match is None:
        return None, None
    if match.group("offset_after") is not None:
        return int(match.group("count")), int(match.group("offset_after"))
    if match.group("offset_before") is not None:
        return int(match.group("count_comma")), int(match.group("offset_before"))
    return int(match.group("count_only")), 0


def _order_by_column(template: str) -> str | None:
    match = _ORDER_BY.search(template)
    return match.group(1) if match else None


def _rows_examined_for_sort(observations: list[Observation], sort_column: str) -> list[float]:
    return [
        float(call.rows_examined)
        for item in observations
        for call in item.sql_calls
        if call.rows_examined is not None and _order_by_column(_template_of(call)) == sort_column
    ]


@dataclass
class _DeepPage:
    template: str
    code_location: CodeLocation
    calls: list[SqlCall] = field(default_factory=list)
    offset: int = 0
    limit: int = 0
    sort_column: str | None = None


def _detect_deep_pages(observations: list[Observation]) -> list[_DeepPage]:
    """Find SQL calls carrying a positive OFFSET, grouped by template + code location."""
    pages: dict[tuple[str, str, int], _DeepPage] = {}
    for item in observations:
        for call in item.sql_calls:
            limit, offset = extract_limit_offset(call.normalized_sql)
            if offset is None or offset <= 0:
                continue
            location = _location_key(call.code_location)
            if location is None:
                continue
            template = _template_of(call)
            page = pages.get(location)
            if page is None:
                location_obj = call.code_location
                assert location_obj is not None
                page = pages[location] = _DeepPage(
                    template=template,
                    code_location=location_obj,
                    offset=offset,
                    limit=limit or 0,
                    sort_column=_order_by_column(template),
                )
            elif page.template != template:
                continue
            page.calls.append(call)
            page.offset = max(page.offset, offset)
            if limit is not None:
                page.limit = limit
    return list(pages.values())


def check_deep_pagination(
    result: ExperimentResult,
    scenario: Scenario,
    task_id: str,
    commit: str,
    policy: MeasurementPolicy | None = None,
) -> list[Finding]:
    """Grade a deep-pagination experiment: ``verified`` only via proven keyset scan collapse."""
    policy = policy or MeasurementPolicy()
    issues = experiment_failures(result, scenario, commit)
    refs = evidence_refs(result)
    known_ids = {ref.artifact_id for ref in refs}
    baseline = [item for item in result.observations if item.level == "baseline"]
    keyset = [item for item in result.observations if item.level == "candidate_pagination"]

    pages = _detect_deep_pages(baseline)
    if not pages:
        return [_no_page_finding(result, scenario, task_id, issues, refs)]
    return [
        _grade(page, baseline, keyset, result, scenario, task_id, policy, issues, refs, known_ids)
        for page in pages
    ]


def _no_page_finding(
    result: ExperimentResult,
    scenario: Scenario,
    task_id: str,
    issues: list[str],
    refs: list[EvidenceRef],
) -> Finding:
    key = hashlib.sha256(
        f"{task_id}:{result.experiment_id}:no-deep-pagination".encode()
    ).hexdigest()[:20]
    status: Literal["lead", "unclassified"] = "lead" if issues else "unclassified"
    reasons = list(issues) if issues else []
    reasons.append(
        "基线请求内未检测到含正 OFFSET 的深分页 SQL，"
        "深分页在当前数据与代码下未复现；这不排除其他性能问题。"
    )
    return Finding(
        id=f"finding-{key}",
        task_id=task_id,
        kind="deep_pagination",
        status=status,
        scenario_id=scenario.id,
        experiment_ids=[result.experiment_id],
        sql_call_ids=[],
        code_locations=[],
        evidence_refs=refs,
        excluded_explanations=[],
        impact=Impact(
            method="unmeasured",
            uncertainty=["本次 keyset 干预未复现正 OFFSET 深分页，深分页机制未被证明。"],
        ),
        recommendation=None,
        limitations=reasons,
    )


def _grade(
    page: _DeepPage,
    baseline: list[Observation],
    keyset: list[Observation],
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
    for call in page.calls:
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

    page_size = page.limit or max((call.rows_returned or 0) for call in page.calls)
    sort_column = page.sort_column
    if sort_column is None:
        insufficient.append("无法从 SQL 提取稳定排序列，无法结构化交接 keyset 修复目标。")
        baseline_examined: list[float] = []
    else:
        baseline_examined = _rows_examined_for_sort(baseline, sort_column)
        if not baseline_examined:
            insufficient.append(
                "缺少深分页 SQL 的扫描行数实测值，无法确认跳过的 OFFSET 行确实被扫描。"
            )
        else:
            med = median(baseline_examined)
            if med < page.offset:
                insufficient.append("扫描行数未达 OFFSET，深分页代价未在实测中复现。")
            elif page_size > 0 and med >= 1.5 * (page.offset + page_size):
                insufficient.append(
                    "扫描行数远超 OFFSET 与页大小之和，存在整表扫描等额外成本，"
                    "深分页收益被淹没，需迭代先修整表扫描再量化 OFFSET。"
                )

    keyset_examined = _rows_examined_for_sort(keyset, sort_column) if sort_column else []
    baseline_latency = [item.latency_ms for item in baseline]
    keyset_latency = [item.latency_ms for item in keyset]
    request_effect = (
        distinguishable(baseline_latency, keyset_latency, policy) if keyset_latency else False
    )
    scan_collapsed = (
        bool(baseline_examined)
        and bool(keyset_examined)
        and median(baseline_examined) >= page.offset
        and median(keyset_examined) <= 2 * max(page_size, 1)
    )

    residual = max(
        (
            (call.lock_wait_ms or 0.0) + (call.lock_evidence.residual_ms or 0.0)
            for call in page.calls
            if call.lock_evidence is not None
        ),
        default=0.0,
    )
    if residual and (
        (not request_effect and residual >= policy.minimum_delta_ms)
        or (
            request_effect
            and median(baseline_latency) - median(keyset_latency)
            <= residual + policy.minimum_delta_ms
        )
    ):
        insufficient.append("实测锁等待或残差上界足以解释耗时差异，不能排除锁因素。")

    status: Literal["verified", "lead"]
    if insufficient:
        status = "lead"
        reasons = list(insufficient)
    elif scan_collapsed and request_effect:
        status = "verified"
        reasons = []
    elif not keyset:
        status = "lead"
        reasons = ["检测到深分页结构，但没有 keyset 干预实验证实扫描量下降，无法证实收益。"]
    else:
        status = "lead"
        reasons = ["keyset 干预未同时满足扫描量下降与耗时可区分，无法证实深分页收益。"]

    verified = status == "verified"
    strategy: PaginationStrategy = "keyset"
    call_ids = [call.id for call in page.calls]
    fix_spec = None
    if sort_column is not None:
        fix_spec = DeepPaginationSpec(
            strategy=strategy,
            query_template=page.template,
            sort_column=sort_column,
            code_location=page.code_location,
            observed_offset=page.offset,
        )
    key = hashlib.sha256(f"{task_id}:{result.experiment_id}:{page.template}".encode()).hexdigest()[
        :20
    ]
    limitations = list(
        dict.fromkeys(
            reasons
            + [
                (
                    "深分页判定依据是大 OFFSET 导致的扫描-丢弃成本，"
                    "而非单条 SQL 的执行计划或索引缺失。"
                ),
                (
                    f"修复策略 {strategy} 依据 keyset 干预观察到的扫描量下降推断；"
                    "max_page_limit 未单独实验。"
                ),
                (
                    "深分页代码位置取 OFFSET 查询的 SQL 定义位置（mapper 方法）；"
                    "触发深翻页的 Java 调用行需修复层回溯。"
                ),
                "结论依赖页大小与总行数：OFFSET 成本在数据量小或页数浅时可忽略。",
                f"测量策略：重复≥{policy.minimum_repetitions}，离散度(IQR)容差≤"
                f"max(相对{policy.maximum_relative_spread}×中位数, "
                f"绝对{policy.minimum_absolute_spread_ms}ms)，最小差异>{policy.minimum_delta_ms}ms。",
            ]
        )
    )
    return Finding(
        id=f"finding-{key}",
        task_id=task_id,
        kind="deep_pagination",
        status=status,
        scenario_id=scenario.id,
        experiment_ids=[result.experiment_id],
        sql_call_ids=call_ids,
        code_locations=[page.code_location],
        evidence_refs=refs,
        excluded_explanations=(
            [
                ExcludedExplanation(
                    explanation=(
                        "固定数据、业务结果与缓存条件下，keyset 干预使深分页查询的扫描行数"
                        "由 OFFSET+页大小 降到页大小量级，请求耗时下降超过测量门槛及锁等待残差；"
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
            latency_delta_ms=median(baseline_latency) - median(keyset_latency)
            if verified and request_effect
            else None,
            affected_request_ids=[item.request_id for item in result.observations],
            shared_sql_call_ids=call_ids,
            uncertainty=["本次单变量 keyset 干预，仅证明 OFFSET 扫描量相关的耗时变化。"],
        ),
        recommendation=(
            Recommendation(
                action=(
                    f"把 OFFSET 分页改为 keyset 分页（WHERE {sort_column} > 上次值 "
                    f"ORDER BY {sort_column} LIMIT ?），消除随页码线性增长的扫描-丢弃成本。"
                ),
                mechanism=strategy,
                conditions=[
                    f"排序列为 {sort_column}，须在其上有索引且值稳定单调。",
                    "需在服务端缓存游标（上一页最后一条的排序列值），并处理并列值。",
                ],
                costs=["游标状态需随请求传递", "随机跳页需额外方案（限制最大页）"],
            )
            if fix_spec is not None
            else None
        ),
        fix_spec=fix_spec,
        limitations=limitations,
    )
