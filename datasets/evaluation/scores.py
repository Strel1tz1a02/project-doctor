#!/usr/bin/env python3
"""评分数据模型（对齐 Langfuse score 模型，纯标准库实现）。

本模块只回答「一个分数长什么样」，不做任何指标计算。指标计算见 ``metrics.py``，
打分流程编排见 ``run_eval.py``。

设计对齐
--------
Langfuse 的 score 由 ``name`` / ``value`` / ``data_type`` / ``source`` 描述，本模块直接沿用：

- 数据类型 ``DataType``：NUMERIC / BOOLEAN / CATEGORICAL / TEXT / CORRECTION；
- 来源 ``ScoreSource``：ANNOTATION（人工标注）/ API / EVAL（代码评估器）；
- 作用域 ``ScoreScope``：本项目用两级 —— DATASET_ITEM（数据集项级）/ RUN（运行级），
  对应 Langfuse 中分数可挂载的粒度。

在此基础上额外引入 ``applies_to``（适用用例类型），用于表达《Agent 评估方法》中
「边界/失败用例级」「失败用例级」的适用范围——它比单纯的作用域更精确：``scope`` 说明
分数挂在哪一级，``applies_to`` 说明该指标对哪些用例类型才参与判定。

用法
----
    from scores import CaseType, definitions_for, make_score

    score = make_score("decision_match", "exact")
    score.to_dict()                       # -> Langfuse 友好的 dict

    [d.name for d in definitions_for(CaseType.FAILURE)]

直接运行本文件会执行一段自检：

    python evaluation/scores.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

__all__ = [
    "DataType",
    "ScoreSource",
    "ScoreScope",
    "CaseType",
    "ALL_CASE_TYPES",
    "MetricDefinition",
    "Score",
    "METRIC_DEFINITIONS",
    "get_definition",
    "definitions_for",
    "make_score",
    "RewardProfile",
    "REWARD_PROFILES",
    "DEFAULT_REWARD_PROFILE",
    "COST_METRICS",
    "COST_BUDGETS",
    "DEFAULT_COST_BUDGET",
    "resolve_cost_budget",
    "cost_score",
    "metric_score",
    "group_scores",
    "total_score",
]


# --------------------------------------------------------------------------- #
# 枚举（对齐 Langfuse）
# --------------------------------------------------------------------------- #

class DataType(str, Enum):
    """分数取值类型，取值与 Langfuse 一致。"""

    NUMERIC = "NUMERIC"
    BOOLEAN = "BOOLEAN"
    CATEGORICAL = "CATEGORICAL"
    TEXT = "TEXT"
    CORRECTION = "CORRECTION"


class ScoreSource(str, Enum):
    """分数来源，取值与 Langfuse 一致。"""

    ANNOTATION = "ANNOTATION"  # 人工标注
    API = "API"                # 外部写入
    EVAL = "EVAL"              # 代码评估器


class ScoreScope(str, Enum):
    """分数挂载粒度。"""

    DATASET_ITEM = "DATASET_ITEM"  # 数据集项级（逐用例）
    RUN = "RUN"                    # 运行级（整轮评估聚合）


class CaseType(str, Enum):
    """用例类型，与 ``case.schema.json`` 的 ``case_type`` 保持一致。"""

    NORMAL = "normal"
    BOUNDARY = "boundary"
    FAILURE = "failure"


ALL_CASE_TYPES: frozenset[CaseType] = frozenset(CaseType)


# --------------------------------------------------------------------------- #
# 类型校验
# --------------------------------------------------------------------------- #

def _check_value(data_type: DataType, value: Any) -> None:
    """校验 ``value`` 是否符合 ``data_type``，不符时抛 ``TypeError``。"""
    if data_type is DataType.BOOLEAN:
        ok = isinstance(value, bool)
    elif data_type is DataType.NUMERIC:
        # 注意：Python 中 bool 是 int 子类，必须显式排除
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif data_type in (DataType.CATEGORICAL, DataType.TEXT):
        ok = isinstance(value, str)
    elif data_type is DataType.CORRECTION:
        ok = isinstance(value, Mapping)
    else:  # pragma: no cover - 枚举已穷尽
        ok = False
    if not ok:
        raise TypeError(
            f"分数取值类型不匹配：data_type={data_type.value}，"
            f"实际为 {type(value).__name__}（value={value!r}）"
        )


# --------------------------------------------------------------------------- #
# 指标定义
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MetricDefinition:
    """一个指标（分数名）的静态定义。"""

    name: str
    data_type: DataType
    source: ScoreSource
    scope: ScoreScope
    applies_to: frozenset[CaseType]
    group: str
    description: str = ""

    def applies(self, case_type: CaseType) -> bool:
        return case_type in self.applies_to


_ITEM = ScoreScope.DATASET_ITEM
_RUN = ScoreScope.RUN
_EVAL = ScoreSource.EVAL
_ANNOTATION = ScoreSource.ANNOTATION

_NB = frozenset({CaseType.NORMAL, CaseType.BOUNDARY})
_BF = frozenset({CaseType.BOUNDARY, CaseType.FAILURE})
_F = frozenset({CaseType.FAILURE})


def _def(name: str, data_type: DataType, scope: ScoreScope,
         applies_to: frozenset[CaseType], group: str,
         source: ScoreSource = _EVAL, description: str = "") -> MetricDefinition:
    return MetricDefinition(name, data_type, source, scope, applies_to, group, description)


#: 全部指标的静态定义。分组与《Agent 评估方法》「指标定义」一节一致。
METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    d.name: d for d in (
        # ---- 结论层 ----
        _def("root_cause_recall", DataType.NUMERIC, _ITEM, _NB, "conclusion",
             description="命中且 status∈{verified,lead} 的根因数 ÷ 期望根因数数量"),
        _def("root_cause_precision", DataType.NUMERIC, _ITEM, _NB, "conclusion",
             description="命中根因数 ÷ Agent 断言为根因的总数"),
        _def("code_location_hit", DataType.BOOLEAN, _ITEM, _NB, "conclusion",
             description="存在输出位置与期望位置同文件且行号差 ≤ 容差"),
        _def("decision_match", DataType.CATEGORICAL, _ITEM, ALL_CASE_TYPES, "conclusion",
             description="结论相对期望：exact / under / over"),
        _def("false_verified", DataType.BOOLEAN, _ITEM, ALL_CASE_TYPES, "conclusion",
             description="期望为 lead/unclassified 却输出 verified（硬闸门）"),
        _def("recommendation_effective", DataType.BOOLEAN, _ITEM, _NB, "conclusion",
             description="按建议改动后目标指标改善达到期望幅度"),
        _def("correctness_preserved", DataType.BOOLEAN, _ITEM, _NB, "conclusion",
             description="复测后业务断言全部通过"),
        # ---- 证据层 ----
        _def("evidence_compliance", DataType.BOOLEAN, _ITEM, _NB, "evidence",
             description="每个 verified finding 是否满足结构化证据要求"),
        _def("excluded_explanation_coverage", DataType.NUMERIC, _ITEM, _NB, "evidence",
             description="被显式排除的期望干扰解释数 ÷ 期望干扰解释数量"),
        _def("limitation_declared", DataType.BOOLEAN, _ITEM, _BF, "evidence",
             description="是否声明 expected.limitations_required 中的全部限制项"),
        _def("artifact_integrity", DataType.BOOLEAN, _ITEM, _NB, "evidence",
             description="所有证据引用可校验、制品可读取"),
        # ---- 过程层 ----
        _def("trajectory_conformance", DataType.NUMERIC, _ITEM, ALL_CASE_TYPES, "process",
             description="必需步骤覆盖度 × 约束满足度（假设数≤3、实验单变量）"),
        _def("honesty", DataType.CATEGORICAL, _ITEM, _F, "process", source=_ANNOTATION,
             description="证据不足场景下是否正确声明并给出原因：pass / partial / fail"),
        _def("restore_verified", DataType.BOOLEAN, _ITEM, _NB, "process",
             description="环境改动已回滚且回滚后校验通过"),
        # ---- 成本层 ----
        _def("wall_seconds", DataType.NUMERIC, _RUN, ALL_CASE_TYPES, "cost",
             description="一次评估的墙钟耗时"),
        _def("tool_calls", DataType.NUMERIC, _RUN, ALL_CASE_TYPES, "cost",
             description="Agent 的工具调用总次数"),
        _def("artifact_bytes", DataType.NUMERIC, _RUN, ALL_CASE_TYPES, "cost",
             description="产出制品的总字节数"),
    )
}


def get_definition(name: str) -> MetricDefinition:
    """按名字取指标定义；未登记则抛 ``KeyError``。"""
    try:
        return METRIC_DEFINITIONS[name]
    except KeyError:
        raise KeyError(
            f"未登记的指标名 {name!r}；请先在 METRIC_DEFINITIONS 中登记，"
            f"或显式指定 data_type/source/scope"
        ) from None


def definitions_for(case_type: CaseType) -> list[MetricDefinition]:
    """返回对该用例类型适用的全部指标定义（按分组、名称排序）。"""
    group_order = {"conclusion": 0, "evidence": 1, "process": 2, "cost": 3}
    result = [d for d in METRIC_DEFINITIONS.values() if d.applies(case_type)]
    return sorted(result, key=lambda d: (group_order.get(d.group, 99), d.name))


# --------------------------------------------------------------------------- #
# 分数值对象
# --------------------------------------------------------------------------- #

@dataclass
class Score:
    """一条分数记录，可由 ``make_score`` 构造。"""

    name: str
    value: Any
    data_type: DataType
    source: ScoreSource
    scope: ScoreScope
    comment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 Langfuse 友好的 dict（枚举转字符串值）。"""
        payload: dict[str, Any] = {
            "name": self.name,
            "value": self.value,
            "dataType": self.data_type.value,
            "source": self.source.value,
            "scope": self.scope.value,
        }
        if self.comment is not None:
            payload["comment"] = self.comment
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Score":
        """从 ``to_dict`` 的产物还原，便于跨进程传递。"""
        return cls(
            name=payload["name"],
            value=payload["value"],
            data_type=DataType(payload["dataType"]),
            source=ScoreSource(payload["source"]),
            scope=ScoreScope(payload["scope"]),
            comment=payload.get("comment"),
            metadata=dict(payload.get("metadata", {})),
        )


def make_score(
    name: str,
    value: Any,
    *,
    data_type: DataType | None = None,
    source: ScoreSource | None = None,
    scope: ScoreScope | None = None,
    comment: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Score:
    """构造一条分数记录。

    若 ``name`` 已在 ``METRIC_DEFINITIONS`` 中登记，则复用其 ``data_type/source/scope``，
    并对 ``value`` 做类型校验；未登记时必须显式提供 ``data_type``（以及 source/scope）。
    """
    definition = METRIC_DEFINITIONS.get(name)
    if definition is not None:
        data_type = data_type or definition.data_type
        source = source or definition.source
        scope = scope or definition.scope
    else:
        if data_type is None:
            raise KeyError(f"未登记的指标名 {name!r}，必须显式提供 data_type")
        source = source or ScoreSource.EVAL
        scope = scope or ScoreScope.DATASET_ITEM

    _check_value(data_type, value)
    return Score(
        name=name,
        value=value,
        data_type=data_type,
        source=source,
        scope=scope,
        comment=comment,
        metadata=dict(metadata or {}),
    )


# --------------------------------------------------------------------------- #
# 奖励画像与总分聚合
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RewardProfile:
    """奖励画像：一组维度权重，把逐指标分数聚合成单用例总分（0–1）。

    ``weights`` 的键是指标分组（``conclusion`` / ``evidence`` / ``process`` / ``cost``），
    值为非负权重。``case.json`` 的 ``evaluation.reward_profile`` 指向这里的某个画像。

    ``hard_gate_metrics`` 中任一指标为真时，总分被「乘法硬门槛」直接置零——这是
    《Agent 评估方法》「误验证率必须为 0」在单用例层面的体现：``false_verified`` 一旦
    为真，该用例无论其他维度多好，总分都是 0。

    ``cost`` 参与方式：评测器按 ``COST_BUDGETS`` 与 ``cost_score()`` 把一次运行的成本
    归一化成 0–1 的合规得分，再经 ``total_score(cost_score=...)`` 计入总分；若某用例显式
    开启成本闸门（``case.json`` 的 ``evaluation.cost_gate``），则超出预算会直接判该用例不通过。
    未传入 ``cost_score`` 时成本权重在其余分组间重新归一（即成本暂不计入总分）。
    """

    name: str
    weights: Mapping[str, float]
    hard_gate_metrics: tuple[str, ...] = ("false_verified",)


#: 三个内置奖励画像，名称与现有 ``case.json`` 的 ``evaluation.reward_profile`` 一一对应。
#: 起点权重参照《Agent 评估方法》「聚合权重」：任务完成度与正确性最高，过程闭环次之。
REWARD_PROFILES: dict[str, RewardProfile] = {
    "normal_single": RewardProfile(
        "normal_single",
        {"conclusion": 0.55, "evidence": 0.20, "process": 0.15, "cost": 0.10}),
    "boundary_composite": RewardProfile(
        "boundary_composite",
        {"conclusion": 0.45, "evidence": 0.30, "process": 0.15, "cost": 0.10}),
    "failure_honesty": RewardProfile(
        "failure_honesty",
        {"conclusion": 0.20, "evidence": 0.35, "process": 0.35, "cost": 0.10}),
}

#: 未指定或未知 ``reward_profile`` 时的兜底画像。
DEFAULT_REWARD_PROFILE = "normal_single"


# --------------------------------------------------------------------------- #
# 成本层预算
# --------------------------------------------------------------------------- #

#: 参与成本合规计算的指标（与 ``METRIC_DEFINITIONS`` 中 cost 组三项一致）。
COST_METRICS: tuple[str, ...] = ("wall_seconds", "tool_calls", "artifact_bytes")

#: 成本层默认预算上限（按用例类型），值为「不得超过」的阈值。
#: 依据：边界用例定位更复杂、允许更多探索步数；正常/失败用例应更快收敛。
#: 超出预算不直接置零，而是让 ``cost_score()`` 按比例衰减；是否硬判由 ``cost_gate`` 决定。
COST_BUDGETS: dict[CaseType, dict[str, float]] = {
    CaseType.NORMAL: {
        "wall_seconds": 120.0, "tool_calls": 40.0, "artifact_bytes": 6_000_000.0,
    },
    CaseType.BOUNDARY: {
        "wall_seconds": 180.0, "tool_calls": 60.0, "artifact_bytes": 10_000_000.0,
    },
    CaseType.FAILURE: {
        "wall_seconds": 120.0, "tool_calls": 40.0, "artifact_bytes": 6_000_000.0,
    },
}

#: 无法归类时的兜底预算。
DEFAULT_COST_BUDGET: dict[str, float] = dict(COST_BUDGETS[CaseType.NORMAL])


def resolve_cost_budget(
    case_type: CaseType | str | None = None,
    override: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """取某用例类型的成本预算，并允许用 ``override``（``case.json`` 的 ``evaluation.cost_budget``）覆盖。

    只接受 ``COST_METRICS`` 中的键、且为正数的覆盖值；其余键忽略，避免脏数据污染判定。
    """
    if isinstance(case_type, str):
        try:
            case_type = CaseType(case_type.strip().lower())
        except ValueError:
            case_type = None
    budget = dict(COST_BUDGETS.get(case_type, DEFAULT_COST_BUDGET))
    if override:
        for key, value in override.items():
            if key in COST_METRICS and isinstance(value, (int, float)) \
                    and not isinstance(value, bool) and value > 0:
                budget[key] = float(value)
    return budget


def cost_score(
    cost_values: Mapping[str, Any] | None,
    budget: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """把一次运行的成本归一化为 0–1 的合规得分。

    逐指标取 ``min(1, budget/value)``：未超预算恒为满分 1.0，超预算则按比例衰减
    （例如用掉 2 倍预算得 0.5）。零消耗视为满分。返回：总分、是否超预算、逐项明细。

    ``cost_values`` 缺省键时按 0 处理，因此信息缺失不会误判为超支。
    """
    cost_values = cost_values or {}
    budget = budget or DEFAULT_COST_BUDGET
    details: dict[str, dict[str, Any]] = {}
    exceeded: list[str] = []
    per_metric: list[float] = []
    for name in COST_METRICS:
        if name not in budget:
            continue
        limit = float(budget[name])
        raw = float(cost_values.get(name, 0.0) or 0.0)
        item_score = 1.0 if raw <= 0 or limit <= 0 else min(1.0, limit / raw)
        over = raw > limit
        if over:
            exceeded.append(name)
        details[name] = {
            "value": raw,
            "budget": limit,
            "score": round(item_score, 4),
            "exceeded": over,
        }
        per_metric.append(item_score)
    total = sum(per_metric) / len(per_metric) if per_metric else 1.0
    return {"cost_score": round(total, 4), "exceeded": exceeded, "details": details}


#: 组内归一化映射：把分类取值折算到 0–1。
_CATEGORICAL_SCORES: dict[str, dict[str, float]] = {
    "decision_match": {"exact": 1.0, "under": 0.0, "over": 0.0},
    "honesty": {"pass": 1.0, "partial": 0.5, "fail": 0.0},
}

#: 负向布尔指标：取值为 False 才「好」，归一化时需取反（其余布尔指标 True 为好）。
_NEGATIVE_METRICS: frozenset[str] = frozenset({"false_verified"})


def resolve_profile(name: str | None) -> RewardProfile:
    """按名字取奖励画像；未知名字回退到 ``DEFAULT_REWARD_PROFILE``。"""
    key = str(name).strip() if name else ""
    return REWARD_PROFILES.get(key, REWARD_PROFILES[DEFAULT_REWARD_PROFILE])


def metric_score(name: str, value: Any) -> float | None:
    """把单个指标取值归一化到 0–1；不参与逐指标归一化的项（成本项、未登记项）返回 ``None``。

    成本项不走此函数（原始秒数/次数不可直接映射为 0–1），而由 ``cost_score()`` 相对预算
    单独归一化。
    """
    definition = METRIC_DEFINITIONS.get(name)
    if definition is None or definition.group == "cost":
        return None
    if definition.data_type is DataType.BOOLEAN:
        good = not bool(value) if name in _NEGATIVE_METRICS else bool(value)
        return 1.0 if good else 0.0
    if definition.data_type is DataType.NUMERIC:
        return max(0.0, min(1.0, float(value)))
    if definition.data_type is DataType.CATEGORICAL:
        return _CATEGORICAL_SCORES.get(name, {}).get(str(value))
    return None


def group_scores(score_map: Mapping[str, Any]) -> dict[str, float]:
    """按分组求组内均值，得到每个维度的 0–1 得分（只统计可归一化的指标）。"""
    buckets: dict[str, list[float]] = {}
    for name, value in score_map.items():
        normalized = metric_score(name, value)
        if normalized is None:
            continue
        group = METRIC_DEFINITIONS[name].group
        buckets.setdefault(group, []).append(normalized)
    return {group: sum(vals) / len(vals) for group, vals in buckets.items() if vals}


def total_score(
    score_map: Mapping[str, Any],
    *,
    reward_profile: str | None = None,
    cost_score: float | None = None,
) -> dict[str, Any]:
    """按奖励画像把逐指标分数聚合成单用例总分。

    返回结构包含：所用画像、各维度得分、加权总分、乘法硬门槛是否通过、以及最终总分。
    ``cost_score`` 为可选的成本归一化得分（0–1，越高越省/越合规）；缺省时成本权重在
    其余分组间重新归一，即成本暂不计入总分。
    """
    profile = resolve_profile(reward_profile)
    groups = group_scores(score_map)
    if cost_score is not None:
        groups = dict(groups, cost=max(0.0, min(1.0, float(cost_score))))

    weights = {g: w for g, w in profile.weights.items() if g in groups and w > 0}
    weight_sum = sum(weights.values())
    weighted = (
        sum(weights[g] * groups[g] for g in weights) / weight_sum if weight_sum else 0.0
    )

    triggered = [m for m in profile.hard_gate_metrics if bool(score_map.get(m))]
    hard_gate_passed = not triggered
    total = weighted if hard_gate_passed else 0.0

    return {
        "reward_profile": profile.name,
        "group_scores": {g: round(groups[g], 4) for g in sorted(groups)},
        "weighted_total": round(weighted, 4),
        "hard_gate_passed": hard_gate_passed,
        "hard_gate_triggered_by": triggered,
        "total": round(total, 4),
    }


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _self_check() -> None:
    assert len(METRIC_DEFINITIONS) == 17, len(METRIC_DEFINITIONS)

    # 每类用例的适用指标数：
    #   normal    = 15（除 honesty 外的项级指标）
    #   boundary  = 15（含 limitation_declared，不含 honesty）
    #   failure   = 6 （decision_match / false_verified / limitation_declared /
    #                   trajectory_conformance / honesty / 成本 3 项 = 但项级为 5）
    def names(case_type: CaseType) -> set[str]:
        return {d.name for d in definitions_for(case_type)}

    normal = names(CaseType.NORMAL)
    boundary = names(CaseType.BOUNDARY)
    failure = names(CaseType.FAILURE)

    assert "honesty" not in normal and "honesty" not in boundary
    assert "honesty" in failure
    assert "limitation_declared" in boundary and "limitation_declared" in failure
    assert "limitation_declared" not in normal
    assert {"decision_match", "false_verified", "trajectory_conformance"} <= failure
    assert "root_cause_recall" in normal and "root_cause_recall" not in failure

    # 类型校验生效
    make_score("decision_match", "exact")
    make_score("false_verified", False)
    make_score("wall_seconds", 12.5)
    for bad in (
        lambda: make_score("false_verified", 1),      # 非 bool
        lambda: make_score("decision_match", True),   # 非 str
        lambda: make_score("root_cause_recall", True),  # bool 不算 NUMERIC
    ):
        try:
            bad()
        except TypeError:
            pass
        else:  # pragma: no cover
            raise AssertionError("类型校验未生效")

    # round-trip
    score = make_score("decision_match", "under", comment="降级为 lead")
    assert Score.from_dict(score.to_dict()) == score

    # 奖励画像与总分聚合
    assert set(REWARD_PROFILES) == {"normal_single", "boundary_composite", "failure_honesty"}
    assert resolve_profile("不存在的画像").name == DEFAULT_REWARD_PROFILE

    # 归一化：bool → 0/1，NUMERIC 截断到 [0,1]，分类映射到 0/0.5/1，成本项不参与
    assert metric_score("code_location_hit", True) == 1.0
    assert metric_score("root_cause_recall", 1.4) == 1.0
    assert metric_score("decision_match", "under") == 0.0
    assert metric_score("honesty", "partial") == 0.5
    assert metric_score("wall_seconds", 42.0) is None

    # 成本层预算：默认值、覆盖、按预算归一化
    assert resolve_cost_budget("normal")["wall_seconds"] == 120.0
    assert resolve_cost_budget(CaseType.BOUNDARY)["tool_calls"] == 60.0
    assert resolve_cost_budget("normal", {"tool_calls": 8})["tool_calls"] == 8.0
    # 非法覆盖被忽略（键不在 COST_METRICS / 非正数）
    assert resolve_cost_budget("normal", {"sql_calls": 1, "tool_calls": -3})["tool_calls"] == 40.0

    under_budget = cost_score({"wall_seconds": 41.5, "tool_calls": 16, "artifact_bytes": 2048},
                              resolve_cost_budget("normal"))
    assert under_budget["cost_score"] == 1.0 and under_budget["exceeded"] == []

    over_budget = cost_score({"wall_seconds": 240.0, "tool_calls": 80, "artifact_bytes": 0},
                             resolve_cost_budget("normal"))
    assert over_budget["exceeded"] == ["wall_seconds", "tool_calls"], over_budget
    # wall: 120/240 = 0.5；tool: 40/80 = 0.5；bytes: 0 → 1.0；均值 = 2/3
    assert over_budget["cost_score"] == round((0.5 + 0.5 + 1.0) / 3, 4)

    # 信息缺失不误判为超支
    assert cost_score(None, resolve_cost_budget("normal"))["exceeded"] == []

    perfect = {"root_cause_recall": 1.0, "decision_match": "exact", "false_verified": False,
               "evidence_compliance": True, "trajectory_conformance": 1.0}
    result = total_score(perfect, reward_profile="normal_single")
    assert result["hard_gate_passed"] and result["total"] == 1.0, result

    # 成本得分计入总分：cost 组出现在 group_scores，且成本权重实际生效
    with_cost = total_score(perfect, reward_profile="normal_single", cost_score=0.0)
    assert "cost" in with_cost["group_scores"], with_cost
    assert with_cost["group_scores"]["cost"] == 0.0
    # 其余维度满分、成本 0 → 总分 = 其余权重和 = 1 - 0.10
    assert with_cost["total"] == round(0.9, 4), with_cost

    # 误验证触发乘法硬门槛：其余维度满分也归零
    gated = dict(perfect, false_verified=True)
    result = total_score(gated, reward_profile="boundary_composite")
    assert not result["hard_gate_passed"] and result["total"] == 0.0, result
    assert result["hard_gate_triggered_by"] == ["false_verified"]

    print("[ OK ] scores.py 自检通过：17 项指标定义；"
          f"正常/边界/失败适用数 = {len(normal)}/{len(boundary)}/{len(failure)}；"
          f"奖励画像 = {len(REWARD_PROFILES)} 个；成本预算 = {len(COST_BUDGETS)} 组")


if __name__ == "__main__":
    _self_check()
