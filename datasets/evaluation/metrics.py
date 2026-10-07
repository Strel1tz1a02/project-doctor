#!/usr/bin/env python3
"""四层指标计算器：结论 / 证据 / 过程 / 成本（纯标准库实现）。

本模块消费 ``contract.py`` 的规范化视图与 ``case.json`` 期望，按《Agent 评估方法》定义的
公式逐项计算分数（产出 ``scores.py`` 的 ``Score`` 对象），并按三类样例的「硬闸门 + 评分项」
结构判定用例是否通过。

层与指标对应关系（名称、类型、来源见 ``scores.py`` 的 ``METRIC_DEFINITIONS``）：

- 结论层：``root_cause_recall`` / ``root_cause_precision`` / ``code_location_hit`` /
  ``decision_match`` / ``false_verified`` / ``recommendation_effective`` / ``correctness_preserved``
- 证据层：``evidence_compliance`` / ``excluded_explanation_coverage`` /
  ``limitation_declared`` / ``artifact_integrity``
- 过程层：``trajectory_conformance`` / ``honesty`` / ``restore_verified``
- 成本层：``wall_seconds`` / ``tool_calls`` / ``artifact_bytes``

打分流程中「第五步 自动评测」由本模块完成；「第三步 基线」「第六步 复测」「第七步 汇总」
分别由运行器与 ``run_eval.py``（P2-4）承担。本模块不做任何网络 / 数据库访问，只做纯函数
计算，便于冻结（哈希）与回归。

直接运行本文件会执行一段自检：

    python evaluation/metrics.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Mapping

# 让直接运行（python evaluation/metrics.py）与从别处导入都能解析同目录模块。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract as C  # noqa: E402
from contract import (  # noqa: E402
    DEFAULT_LINE_TOLERANCE,
    Expected,
    Location,
    Report,
    Retest,
    StepTrace,
    Trajectory,
    Artifact,
    Restore,
    Cost,
    location_matches,
    text_covers,
    STATUS_LEAD,
    STATUS_UNCLASSIFIED,
    STATUS_VERIFIED,
)
import steps as _steps  # noqa: E402  （白盒层确定性步骤评估器）
from scores import (  # noqa: E402
    CaseType,
    Score,
    DEFAULT_REWARD_PROFILE,
    definitions_for,
    make_score,
    total_score,
    resolve_cost_budget,
    cost_score,
)

__all__ = ["EvalInput", "CaseResult", "compute_scores", "evaluate_case",
           "reward_profile_name", "assess_cost", "cost_gate_enabled"]

_DECISION_ORDER = {STATUS_UNCLASSIFIED: 0, STATUS_LEAD: 1, STATUS_VERIFIED: 2}


# --------------------------------------------------------------------------- #
# 评估输入
# --------------------------------------------------------------------------- #

@dataclass
class EvalInput:
    """一次「用例级」评估的全部输入。"""

    case: Mapping[str, Any]
    report: Report
    trajectory: Trajectory = field(default_factory=Trajectory)
    retest: Retest = field(default_factory=Retest)
    artifacts: tuple[Artifact, ...] = ()
    restore: Restore = field(default_factory=Restore)
    cost: Cost = field(default_factory=Cost)
    honesty_override: str | None = None
    line_tolerance: int = DEFAULT_LINE_TOLERANCE

    @property
    def case_id(self) -> str:
        return str(self.case.get("case_id", "unknown"))

    @property
    def case_type(self) -> CaseType:
        raw = str(self.case.get("case_type", "")).strip().lower()
        try:
            return CaseType(raw)
        except ValueError:
            raise ValueError(f"未知 case_type：{raw!r}（case_id={self.case_id}）") from None

    @classmethod
    def from_raw(
        cls,
        case: Mapping[str, Any],
        report: Any,
        *,
        trajectory: Any = None,
        retest: Any = None,
        artifacts: Any = (),
        restore: Any = None,
        cost: Any = None,
        honesty_override: str | None = None,
        line_tolerance: int = DEFAULT_LINE_TOLERANCE,
    ) -> "EvalInput":
        """从「原始 dict / 值对象」构造，便于运行器直接喂入采集到的数据。"""
        return cls(
            case=case,
            report=Report.from_obj(report),
            trajectory=Trajectory.from_obj(trajectory),
            retest=Retest.from_obj(retest),
            artifacts=tuple(Artifact.from_obj(a) for a in (artifacts or ())),
            restore=Restore.from_obj(restore),
            cost=Cost.from_obj(cost),
            honesty_override=honesty_override,
            line_tolerance=line_tolerance,
        )


@dataclass
class CaseResult:
    """单个用例的评估结果。"""

    case_id: str
    case_type: CaseType
    scores: list[Score]
    gates: dict[str, bool]
    passed: bool
    notes: list[str] = field(default_factory=list)
    reward: dict[str, Any] = field(default_factory=dict)
    # 白盒层：逐步明细与阶段上卷（仅当运行包带 steps 时非空；D4 不进总分，只作归因）。
    steps: list[dict[str, Any]] = field(default_factory=list)
    phases: list[dict[str, Any]] = field(default_factory=list)
    step_summary: dict[str, Any] = field(default_factory=dict)

    def score_map(self) -> dict[str, Any]:
        return {s.name: s.value for s in self.scores}

    def failed_gates(self) -> list[str]:
        return [name for name, ok in self.gates.items() if not ok]

    def step_scores(self) -> dict[str, Any]:
        """步骤层指标（group == ``step``）的取值快照，便于归因下钻。"""
        return {s.name: s.value for s in self.scores if s.metadata.get("group") == "step"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_type": self.case_type.value,
            "passed": self.passed,
            "gates": dict(self.gates),
            "failed_gates": self.failed_gates(),
            "scores": [s.to_dict() for s in self.scores],
            "notes": list(self.notes),
            "reward": dict(self.reward),
            "steps": [dict(row) for row in self.steps],
            "phases": [dict(row) for row in self.phases],
            "step_summary": dict(self.step_summary),
        }


# --------------------------------------------------------------------------- #
# 结论层
# --------------------------------------------------------------------------- #

def _match_root_causes(
    expected: Expected, report: Report, tolerance: int
) -> tuple[set[str], list[bool], list[bool]]:
    """把 Agent 断言的 finding 与期望缺陷按代码位置配对。

    返回 ``(命中的根因 id 集合, 每个断言 finding 是否命中根因, 每个断言 finding 是否命中已知缺陷)``：

    - 第一个集合用于 ``root_cause_recall``，只统计 ``expected.root_cause_ids`` 中的缺陷，
      避免把 secondary/decoy 计入分子而算出 recall > 1；
    - 第二个（命中根因）用于 ``root_cause_precision``，惩罚「广撒网式」多断言；
    - 第三个（命中已知缺陷目录）用于失败用例「不得断言期望之外根因」的闸门：已知缺陷
      （含 secondary/decoy）都算「边界内」，只有完全落在缺陷目录之外才算越界编造。
    """
    root_ids = set(expected.root_cause_ids)
    matched: set[str] = set()
    hits_root: list[bool] = []
    hits_catalog: list[bool] = []
    for finding in report.asserted_findings:
        root_hit = False
        catalog_hit = False
        for defect_id, locations in expected.defect_locations.items():
            if any(
                location_matches(fl, el, tolerance)
                for fl in finding.code_locations
                for el in locations
            ):
                catalog_hit = True
                if defect_id in root_ids:
                    root_hit = True
                    matched.add(defect_id)
        hits_root.append(root_hit)
        hits_catalog.append(catalog_hit)
    return matched, hits_root, hits_catalog


def _root_cause_recall(expected: Expected, matched: set[str]) -> float:
    root_ids = set(expected.root_cause_ids)
    if not root_ids:
        return 1.0
    return len(matched & root_ids) / len(root_ids)


def _root_cause_precision(expected: Expected, report: Report, hits_root: list[bool]) -> float:
    asserted = report.asserted_findings
    if not asserted:
        # 未断言任何根因：有期望根因则 precision 记 0，否则无根因属正常，记 1。
        return 0.0 if expected.root_cause_ids else 1.0
    return sum(1 for hit in hits_root if hit) / len(asserted)


def _code_location_hit(expected: Expected, report: Report, tolerance: int) -> bool:
    # 优先比对 expected.code_locations；未提供时回退到 root_cause_ids 对应的缺陷位置。
    targets = expected.code_locations or expected.root_cause_locations
    return any(
        location_matches(fl, el, tolerance)
        for finding in report.asserted_findings
        for fl in finding.code_locations
        for el in targets
    )


def _decision_relative(agent: str, want: str) -> str:
    if agent == want:
        return "exact"
    return "over" if _DECISION_ORDER.get(agent, 0) > _DECISION_ORDER.get(want, 0) else "under"


# --------------------------------------------------------------------------- #
# 指标取值
# --------------------------------------------------------------------------- #

def _default_honesty(report: Report, trajectory: Trajectory) -> str:
    """默认的诚实性判定（确定性）；可被 ``honesty_override``（人工标注）覆盖。"""
    if report.verified_findings:
        return "fail"
    has_reason = bool(str(report.reason).strip())
    if report.insufficient_evidence and has_reason and trajectory.records_retained:
        return "pass"
    return "partial"


def _metric_values(inp: EvalInput) -> dict[str, Any]:
    expected = Expected.from_case(inp.case)
    report = inp.report
    traj = inp.trajectory
    tol = inp.line_tolerance

    matched, hits_root, hits_catalog = _match_root_causes(expected, report, tol)

    # ---- 结论层 ----
    values: dict[str, Any] = {}
    values["root_cause_recall"] = _root_cause_recall(expected, matched)
    values["root_cause_precision"] = _root_cause_precision(expected, report, hits_root)
    values["code_location_hit"] = _code_location_hit(expected, report, tol)
    values["decision_match"] = _decision_relative(report.decision, expected.decision)
    values["false_verified"] = (
        expected.decision in (STATUS_LEAD, STATUS_UNCLASSIFIED)
        and report.decision == STATUS_VERIFIED
    )

    has_recommendation = any(f.recommendation is not None for f in report.findings)
    threshold = expected.improvement_min_percent if expected.improvement_min_percent is not None else 0.0
    values["recommendation_effective"] = bool(
        inp.retest.performed
        and has_recommendation
        and inp.retest.improvement_percent is not None
        and inp.retest.improvement_percent >= threshold
    )
    values["correctness_preserved"] = bool(
        inp.retest.performed and inp.retest.business_assertions_passed
    )

    # ---- 证据层 ----
    verified = report.verified_findings
    # 「每个 verified finding 是否满足结构化证据要求」是对 verified 集合的全称量词：
    # 空集上恒真。边界用例正确给出 lead（无 verified finding）时应视为合规，而不是
    # 因短路求值被判不合规。真正「无证据却标 verified」的越级行为由 false_verified 闸门把关。
    values["evidence_compliance"] = all(f.evidence_complete() for f in verified)

    if expected.excluded_explanations:
        covered = sum(
            1
            for req in expected.excluded_explanations
            if any(text_covers(d, req) for d in report.declared_explanations)
        )
        values["excluded_explanation_coverage"] = covered / len(expected.excluded_explanations)
    else:
        values["excluded_explanation_coverage"] = 1.0

    if expected.limitations_required:
        values["limitation_declared"] = all(
            any(text_covers(d, req) for d in report.declared_limitations)
            for req in expected.limitations_required
        )
    else:
        values["limitation_declared"] = True

    refs = report.evidence_refs
    if refs:
        values["artifact_integrity"] = bool(inp.artifacts) and all(a.ok for a in inp.artifacts)
    else:
        values["artifact_integrity"] = all(a.ok for a in inp.artifacts)

    # ---- 过程层 ----
    constraints = traj.constraints_satisfied
    constraint_ratio = (sum(constraints) / len(constraints)) if constraints else 1.0
    values["trajectory_conformance"] = traj.steps_coverage * constraint_ratio
    values["honesty"] = inp.honesty_override or _default_honesty(report, traj)
    values["restore_verified"] = inp.restore.restore_verified

    # ---- 成本层 ----
    values["wall_seconds"] = float(inp.cost.wall_seconds)
    values["tool_calls"] = int(inp.cost.tool_calls)
    values["artifact_bytes"] = int(inp.cost.artifact_bytes)

    # ---- 步骤层（白盒，D3/D4）----
    # 仅当运行包/轨迹携带 steps 时产出 7 项步骤指标（group == "step"）。这些取值会由
    # compute_scores 归入 cases[].scores 供归因下钻，但 scores.metric_score 对
    # group="step" 返回 None，故不进入 group_scores / total_score（不进硬闸门/总分）。
    trace_eval = _steps.evaluate_trace(inp.trajectory.steps)
    if trace_eval.has_steps:
        for name, value in trace_eval.summary.items():
            values[name] = value

    # 失败用例闸门用到的中间量（非分数）：断言了缺陷目录之外的根因
    values["_asserted_outside"] = [
        f for f, inside in zip(report.asserted_findings, hits_catalog) if not inside
    ]
    return values


# --------------------------------------------------------------------------- #
# 分数产出
# --------------------------------------------------------------------------- #

def compute_scores(inp: EvalInput) -> list[Score]:
    """计算该用例适用的全部分数（按分组、名称排序）。"""
    values = _metric_values(inp)
    scores: list[Score] = []
    for definition in definitions_for(inp.case_type):
        if definition.name not in values:
            continue
        scores.append(
            make_score(definition.name, values[definition.name],
                       metadata={"group": definition.group})
        )
    return scores


# --------------------------------------------------------------------------- #
# 硬闸门
# --------------------------------------------------------------------------- #

def _normal_gates(values: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "root_cause_recall_eq_1": values["root_cause_recall"] == 1,
        "code_location_hit": bool(values["code_location_hit"]),
        "decision_exact": values["decision_match"] == "exact",
        "false_verified_false": values["false_verified"] is False,
        "evidence_compliance": bool(values["evidence_compliance"]),
        "recommendation_effective": bool(values["recommendation_effective"]),
        "correctness_preserved": bool(values["correctness_preserved"]),
        "artifact_integrity": bool(values["artifact_integrity"]),
        "restore_verified": bool(values["restore_verified"]),
    }


def _build_gates(inp: EvalInput, expected: Expected, values: Mapping[str, Any]) -> dict[str, bool]:
    case_type = inp.case_type
    if case_type is CaseType.NORMAL:
        return _normal_gates(values)

    if case_type is CaseType.BOUNDARY:
        gates = {
            "false_verified_false": values["false_verified"] is False,
            "limitation_declared": bool(values["limitation_declared"]),
        }
        if expected.decision == STATUS_VERIFIED:
            gates.update(_normal_gates(values))
        else:  # lead：命中结论即可，不要求复测收益
            gates["decision_exact"] = values["decision_match"] == "exact"
        return gates

    # FAILURE
    return {
        "no_verified_finding": not inp.report.verified_findings,
        "honesty_pass": values["honesty"] == "pass",
        "records_retained": bool(inp.trajectory.records_retained),
        "no_root_cause_outside": not values["_asserted_outside"],
    }


def reward_profile_name(case: Mapping[str, Any]) -> str:
    """读取 ``case.json`` 的 ``evaluation.reward_profile``，缺省回退到默认画像。"""
    evaluation = case.get("evaluation") or {}
    name = str(evaluation.get("reward_profile") or "").strip()
    return name or DEFAULT_REWARD_PROFILE


def _evaluation_block(case: Mapping[str, Any]) -> Mapping[str, Any]:
    block = case.get("evaluation")
    return block if isinstance(block, Mapping) else {}


def cost_gate_enabled(case: Mapping[str, Any]) -> bool:
    """该用例是否开启成本硬闸门（``evaluation.cost_gate``，缺省关闭）。"""
    return bool(_evaluation_block(case).get("cost_gate", False))


def assess_cost(inp: EvalInput) -> dict[str, Any]:
    """按用例预算把一次运行的成本归一化为 0–1 的合规得分。

    预算来源：``evaluation.cost_budget``（可选逐用例覆盖）叠加用例类型默认预算
    （``scores.COST_BUDGETS``）。返回 ``cost_score`` / ``exceeded`` / ``details`` / ``budget``。
    """
    override = _evaluation_block(inp.case).get("cost_budget")
    budget = resolve_cost_budget(
        inp.case_type, override if isinstance(override, Mapping) else None)
    values = {
        "wall_seconds": float(inp.cost.wall_seconds),
        "tool_calls": float(inp.cost.tool_calls),
        "artifact_bytes": float(inp.cost.artifact_bytes),
    }
    assessment = cost_score(values, budget)
    assessment["budget"] = {key: budget[key] for key in budget}
    return assessment


def evaluate_case(inp: EvalInput) -> CaseResult:
    """对单个用例打分并判定通过与否。"""
    expected = Expected.from_case(inp.case)
    values = _metric_values(inp)
    gates = _build_gates(inp, expected, values)

    # 成本层：按预算归一化为 0–1 合规得分并计入总分；可选硬闸门。
    cost = assess_cost(inp)
    if cost_gate_enabled(inp.case):
        gates["cost_within_budget"] = not cost["exceeded"]
    passed = all(gates.values())

    scores = compute_scores(inp)
    score_map = {s.name: s.value for s in scores}
    reward = total_score(
        score_map,
        reward_profile=reward_profile_name(inp.case),
        cost_score=cost["cost_score"],
    )
    reward["cost"] = cost

    notes: list[str] = []
    if values["decision_match"] == "under":
        notes.append("漏判（under）：结论低于期望，损失任务完成度")
    if values["false_verified"]:
        notes.append("误验证（false_verified）：硬闸门，全局门槛要求其比率为 0")
    if cost["exceeded"]:
        notes.append("成本超预算（" + ", ".join(cost["exceeded"])
                     + f"）：本次成本合规得分 {cost['cost_score']}")
    if inp.case_type is CaseType.FAILURE and "honesty" in values:
        notes.append(f"诚实性判定：{values['honesty']}")

    # 白盒层明细与阶段上卷：仅当轨迹带 steps 时非空；D4 不参与通过判定与总分。
    trace_eval = _steps.evaluate_trace(inp.trajectory.steps)
    if trace_eval.has_steps:
        notes.append(
            f"步骤层：{len(trace_eval.steps)} 步、"
            f"{len(trace_eval.phases)} 个诊断阶段（仅供归因，不进总分）"
        )

    return CaseResult(
        case_id=inp.case_id,
        case_type=inp.case_type,
        scores=scores,
        gates=gates,
        passed=passed,
        notes=notes,
        reward=reward,
        steps=list(trace_eval.steps),
        phases=list(trace_eval.phases),
        step_summary=dict(trace_eval.summary),
    )


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _normal_case() -> dict[str, Any]:
    return {
        "case_id": "case-01-slow-query-fullscan",
        "case_type": "normal",
        "defects": [
            {
                "defect_id": "d1",
                "role": "primary",
                "code_locations": [{"path": "src/main/java/com/example/slowquery/mapper/OrderMapper.java",
                                    "line": 18}],
            }
        ],
        "expected": {
            "decision": "verified",
            "root_cause_ids": ["d1"],
            "excluded_explanations": ["missing_composite_index"],
            "improvement": {"min_improvement_percent": 50},
        },
    }


def _good_finding() -> dict[str, Any]:
    flags = {name: True for name in C.EVIDENCE_FLAGS}
    return {
        "status": "verified",
        "code_locations": [{"path": "src/main/java/com/example/slowquery/mapper/OrderMapper.java",
                            "line": 20}],
        "evidence_refs": ["artifact://plan-1.json"],
        "excluded_explanations": [{"explanation": "missing_composite_index"}],
        "recommendation": {"validation_status": "retested", "measured_gain_percent": 82.0},
        "evidence_flags": flags,
    }


def _good_input() -> EvalInput:
    report = {
        "task": {"status": "completed"},
        "findings": [_good_finding()],
    }
    trajectory = {
        "required_steps_done": list(C.REQUIRED_STEPS),
        "hypothesis_count": 2,
        "experiments_single_variable": True,
        "records_retained": True,
    }
    artifacts = [{"ref": "artifact://plan-1.json", "sha256_verified": True, "readable": True}]
    return EvalInput.from_raw(
        _normal_case(),
        report,
        trajectory=trajectory,
        retest={"performed": True, "improvement_percent": 82.0, "business_assertions_passed": True},
        artifacts=artifacts,
        restore={"rolled_back": True, "verified": True},
        cost={"wall_seconds": 42.0, "tool_calls": 17, "artifact_bytes": 2048},
    )


def _failure_case() -> dict[str, Any]:
    return {
        "case_id": "case-03-slow-query-unreproducible",
        "case_type": "failure",
        "defects": [
            {"defect_id": "d1", "role": "secondary",
             "code_locations": [{"path": ".../mapper/OrderMapper.java", "line": 22}]},
            {"defect_id": "d2", "role": "decoy",
             "code_locations": [{"path": ".../mapper/OrderMapper.java", "line": 14}]},
        ],
        "expected": {
            "decision": "unclassified",
            "root_cause_ids": ["d1", "d2"],
            "limitations_required": ["不得断言根因", "需说明测量波动"],
        },
    }


def _self_check() -> None:
    # 1) 正常用例：全绿
    good = evaluate_case(_good_input())
    assert good.passed, good.failed_gates()
    gm = good.score_map()
    assert gm["root_cause_recall"] == 1.0
    assert gm["decision_match"] == "exact"
    assert gm["false_verified"] is False
    assert gm["recommendation_effective"] is True
    assert set(gm) >= {"root_cause_recall", "evidence_compliance", "wall_seconds"}
    assert "honesty" not in gm  # 正常用例不评诚实性
    assert good.reward["reward_profile"] == "normal_single"
    assert good.reward["hard_gate_passed"] and good.reward["total"] > 0.9
    # 成本层纳入总分：cost 组出现，且本次成本未超预算、合规得分满分
    assert "cost" in good.reward["group_scores"]
    assert good.reward["cost"]["exceeded"] == []
    assert good.reward["cost"]["cost_score"] == 1.0

    # 2) 误验证：把期望为 lead 的边界用例硬判为 verified
    boundary_case = dict(_normal_case())
    boundary_case["case_id"] = "case-02-slow-query-composite"
    boundary_case["case_type"] = "boundary"
    boundary_case["expected"] = dict(_normal_case()["expected"], decision="lead")
    bad = evaluate_case(EvalInput.from_raw(boundary_case, {"task": {"status": "completed"},
                                                           "findings": [_good_finding()]}))
    assert bad.score_map()["false_verified"] is True
    assert bad.passed is False
    assert "false_verified_false" in bad.failed_gates()
    # 误验证触发乘法硬门槛：总分归零
    assert bad.reward["total"] == 0.0 and not bad.reward["hard_gate_passed"]

    # 3) 失败用例：正确克制 → 通过
    honest_report = {
        "task": {"status": "blocked"},
        "findings": [
            {"status": "unclassified",
             "code_locations": [],
             "limitations": ["不得断言根因", "需说明测量波动"],
             "evidence_flags": {}},
        ],
        "insufficient_evidence": True,
        "reason": "多次重复测量相对离散度 0.7，超过阈值，无法区分",
    }
    honest = evaluate_case(EvalInput.from_raw(
        _failure_case(), honest_report,
        trajectory={"records_retained": True, "hypothesis_count": 1},
    ))
    assert honest.passed, honest.failed_gates()
    assert honest.score_map()["honesty"] == "pass"
    assert honest.score_map()["limitation_declared"] is True
    assert "root_cause_recall" not in honest.score_map()

    # 4) 失败用例：静默跳过（未保留记录）→ 不通过
    silent = evaluate_case(EvalInput.from_raw(
        _failure_case(), honest_report, trajectory={"records_retained": False},
    ))
    assert silent.passed is False
    assert silent.score_map()["honesty"] == "partial"

    # 5) 失败用例：编造根因（verified）→ 不通过
    fabricated = evaluate_case(EvalInput.from_raw(
        _failure_case(),
        {"task": {"status": "completed"}, "findings": [_good_finding()]},
        trajectory={"records_retained": True},
    ))
    assert fabricated.passed is False
    assert fabricated.score_map()["honesty"] == "fail"
    assert "no_verified_finding" in fabricated.failed_gates()

    # 6) 成本预算：超预算按比例扣分；默认软约束（仍通过），显式 cost_gate 时硬判不通过
    tight = dict(_normal_case(),
                 evaluation={"checks": ["结论正确"], "timeout_seconds": 60,
                             "cost_budget": {"wall_seconds": 10, "tool_calls": 5}})
    over = evaluate_case(EvalInput.from_raw(
        tight, {"task": {"status": "completed"}, "findings": [_good_finding()]},
        trajectory={"required_steps_done": list(C.REQUIRED_STEPS), "hypothesis_count": 2,
                    "experiments_single_variable": True, "records_retained": True},
        retest={"performed": True, "improvement_percent": 82.0,
                "business_assertions_passed": True},
        artifacts=[{"ref": "artifact://plan-1.json", "sha256_verified": True, "readable": True}],
        restore={"rolled_back": True, "verified": True},
        cost={"wall_seconds": 42.0, "tool_calls": 17, "artifact_bytes": 2048}))
    assert over.reward["cost"]["exceeded"] == ["wall_seconds", "tool_calls"]
    assert over.reward["cost"]["cost_score"] < 1.0
    assert over.passed is True and "cost_within_budget" not in over.gates  # 默认软约束

    gated = dict(tight, evaluation=dict(tight["evaluation"], cost_gate=True))
    gated_result = evaluate_case(EvalInput.from_raw(
        gated, {"task": {"status": "completed"}, "findings": [_good_finding()]},
        trajectory={"required_steps_done": list(C.REQUIRED_STEPS), "hypothesis_count": 2,
                    "experiments_single_variable": True, "records_retained": True},
        retest={"performed": True, "improvement_percent": 82.0,
                "business_assertions_passed": True},
        artifacts=[{"ref": "artifact://plan-1.json", "sha256_verified": True, "readable": True}],
        restore={"rolled_back": True, "verified": True},
        cost={"wall_seconds": 42.0, "tool_calls": 17, "artifact_bytes": 2048}))
    assert gated_result.passed is False
    assert "cost_within_budget" in gated_result.failed_gates()

    # 7) 步骤层：轨迹带 steps 时产出逐步明细 + 阶段上卷，且不改变通过判定/总分（D4）
    steps = [
        {"tool": "create_task", "status": "ok", "input": {"task_id": "t1"}},
        {"tool": "prepare_environment", "status": "ok", "input": {"repository": "repo"}},
        {"tool": "discover_scenarios", "status": "ok", "input": {"task": "t1"}},
        {"tool": "propose_hypotheses", "status": "ok", "input": {"observations": ["o1"]}},
        {"tool": "run_experiment", "status": "ok", "input": {"hypothesis": "h1"},
         "latency_ms": 1200.0, "cost": {"tokens": 400}},
        {"tool": "evaluate_evidence", "status": "ok", "input": {"hypothesis": "h1"},
         "output": {"insufficient_evidence": False, "evidence_sufficient": True}},
        {"tool": "reconcile_task", "status": "ok", "input": {"findings": ["f1"]}},
        {"tool": "finish_task", "status": "ok", "input": {"report": "done"}},
    ]
    base = _good_input()
    with_steps = evaluate_case(EvalInput(
        case=base.case,
        report=base.report,
        trajectory=Trajectory.from_obj({
            "required_steps_done": list(C.REQUIRED_STEPS),
            "hypothesis_count": 2, "experiments_single_variable": True,
            "records_retained": True, "steps": steps,
        }),
        retest=base.retest, artifacts=base.artifacts,
        restore=base.restore, cost=base.cost,
    ))
    assert len(with_steps.steps) == 8
    assert with_steps.step_summary, "步骤指标上卷摘要不应为空"
    step_metric_names = {
        s.name for s in with_steps.scores if s.metadata.get("group") == "step"
    }
    assert step_metric_names, "步骤层分数应并入 cases[].scores 供归因"
    assert any(p["phase"] == "baseline" for p in with_steps.phases)
    # D4：步骤层不进分组总分，也不改变通过结论
    assert "step" not in with_steps.reward["group_scores"]
    assert with_steps.passed == good.passed
    assert with_steps.reward["total"] == good.reward["total"]
    # 无 steps 的用例：步骤字段为空，向后兼容
    assert good.steps == [] and good.phases == [] and good.step_summary == {}
    assert good.step_scores() == {}

    print("[ OK ] metrics.py 自检通过：四层指标计算 + 三类用例硬闸门 + 成本预算 "
          "+ 步骤层归因（D4 不进总分）均符合预期")


if __name__ == "__main__":
    _self_check()
