#!/usr/bin/env python3
"""白盒层「步骤级」确定性评估器（纯标准库实现）。

职责
----
消费 ``contract.StepTrace`` / ``TraceStep``（统一中间表示 IR），用**确定性规则**产出：

1. 单步检查与单步分（``evaluate_step``）；
2. 轨迹级 7 项步骤指标（``evaluate_trace``，见 ``scores.STEP_METRICS``）；
3. 按 5 个诊断阶段的上卷（phase roll-up），供「阶段→用例过程分→全局过程画像」聚合。

设计红线（对应决策 D3 / D4）
---------------------------
- **D3：只用确定性规则，不依赖逐步骤正解。** 本模块不引入任何「某一步标准答案」，
  只做结构性 / 一致性 / 预算类判定（状态、参数结构、阶段覆盖、重试、延迟、token、
  证据不足时是否降级）。
- **D4：步骤分不进硬闸门，只作评分项 / 归因。** 步骤分与阶段分**不参与**用例级
  ``group_scores`` / ``total_score``（``scores.metric_score`` 对 ``group=="step"`` 返回
  ``None``），仅出现在报告的 ``cases[].steps`` 中用于归因。
- 消费端只读：本模块不发起任何网络 / 数据库访问，也不调用被测系统。

直接运行本文件会执行一段自检：

    python evaluation/steps.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

# 让直接运行（python evaluation/steps.py）与从别处导入都能解析同目录模块。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract as C  # noqa: E402
from contract import DIAGNOSTIC_PHASES, TraceStep, StepTrace  # noqa: E402
from scores import (  # noqa: E402
    STEP_METRICS,
    DataType,
    Score,
    ScoreScope,
    ScoreSource,
    make_score,
)

__all__ = [
    "StepBudget",
    "DEFAULT_STEP_BUDGET",
    "TOOL_REQUIRED_FIELDS",
    "MCP_TOOLS",
    "TOOL_PHASE",
    "phase_for",
    "evaluate_step",
    "evaluate_trace",
    "step_scores",
    "TraceEvalResult",
    "STEP_RULES",
]

#: 8 个 MCP 工具（D6 以 8 工具为准）。
MCP_TOOLS: tuple[str, ...] = (
    "create_task",
    "prepare_environment",
    "discover_scenarios",
    "propose_hypotheses",
    "run_experiment",
    "evaluate_evidence",
    "reconcile_task",
    "finish_task",
)

#: 工具 → 诊断阶段映射（D6：以 8 工具为准）。来源未显式给出 ``phase`` 时据此推断，
#: 保证即使上游只记录工具名，``step_phase_coverage`` 与阶段上卷仍然可用。
TOOL_PHASE: dict[str, str] = {
    "create_task": "baseline",
    "prepare_environment": "baseline",
    "discover_scenarios": "hypotheses",
    "propose_hypotheses": "hypotheses",
    "run_experiment": "discriminating_experiment",
    "evaluate_evidence": "localization",
    "reconcile_task": "verification",
    "finish_task": "verification",
}


def phase_for(tool: str) -> str:
    """由工具名推导诊断阶段；未知工具返回空串（此时以上游显式 ``phase`` 为准）。"""
    return TOOL_PHASE.get(tool, "")

#: 参数别名：同一语义字段在不同实现下可能用不同键名，取「命中任一别名」即视为存在。
_ARG_ALIASES: dict[str, tuple[str, ...]] = {
    "task": ("task", "task_id", "task_description", "prompt", "instruction", "goal"),
    "repository": ("repository", "repo", "codebase", "project", "target", "target_dir",
                   "workdir", "path"),
    "observations": ("observations", "observation", "evidence", "signals", "baseline"),
    "hypothesis": ("hypothesis", "hypothesis_id", "candidate", "cause", "root_cause"),
    "findings": ("findings", "finding", "verdicts", "conclusions", "results"),
    "report": ("report", "report_data", "final_report", "summary"),
}

#: 每个 MCP 工具的结构性必填参数（用别名组表达）。仅做「结构性」校验，判定是否存在，
#: 不判断取值是否语义正确（那是执行侧的事）。未知工具不做参数校验。
TOOL_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "create_task": ("task",),
    "prepare_environment": ("repository",),
    "discover_scenarios": ("task",),
    "propose_hypotheses": ("observations",),
    "run_experiment": ("hypothesis",),
    "evaluate_evidence": ("hypothesis",),
    "reconcile_task": ("findings",),
    "finish_task": ("report",),
}


# --------------------------------------------------------------------------- #
# 单步预算
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class StepBudget:
    """单步资源预算：延迟（ms）与 token。缺省值偏宽松，避免把正常探索误判为超支。"""

    latency_ms: float = 15_000.0
    tokens: float = 8_000.0


DEFAULT_STEP_BUDGET = StepBudget()


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #

def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _field_present(input_obj: Any, field_name: str) -> bool:
    """``input_obj`` 中是否存在语义字段 ``field_name``（任一别名命中且取值非空）。"""
    obj = _as_mapping(input_obj)
    if not obj:
        return False
    for alias in _ARG_ALIASES.get(field_name, (field_name,)):
        if alias in obj:
            value = obj[alias]
            if value is None:
                continue
            if isinstance(value, (str, bytes, list, tuple, dict, set)) and len(value) == 0:
                continue
            return True
    return False


def _tool_argument_valid(tool: str, input_obj: Any) -> bool | None:
    """工具参数结构性是否合法；未知/空工具返回 ``None``（不判定）。"""
    required = TOOL_REQUIRED_FIELDS.get(tool)
    if required is None:
        return None
    if not isinstance(input_obj, Mapping):
        return False
    return all(_field_present(input_obj, name) for name in required)


def _ratio_score(raw: float | None, budget: float) -> float | None:
    """预算归一化：未超预算恒为 1.0，超预算按 budget/raw 衰减。"""
    if raw is None:
        return None
    if budget <= 0 or raw <= 0:
        return 1.0
    return min(1.0, budget / raw)


def _status_factor(status: str) -> float:
    """单步状态折算：ok=1.0 / skipped=0.5 / error=0.0。"""
    if status == "ok":
        return 1.0
    if status == "skipped":
        return 0.5
    return 0.0


def _is_retry(step: TraceStep, prev: TraceStep | None) -> bool:
    """是否与上一步重复（同工具、同参数）——确定性重试判定。"""
    if prev is None or not step.tool:
        return False
    if step.tool != prev.tool:
        return False
    return _as_mapping(step.input) == _as_mapping(prev.input)


# --------------------------------------------------------------------------- #
# 单步评估
# --------------------------------------------------------------------------- #

def evaluate_step(
    step: TraceStep,
    *,
    prev: TraceStep | None = None,
    budget: StepBudget = DEFAULT_STEP_BUDGET,
) -> dict[str, Any]:
    """对单个步骤做确定性检查，返回该步的明细与单步分。

    单步分 ``model`` = 状态因子 × 参数合法性因子：只表达「这一步是否发生了结构性错误」，
    延迟 / token 单独作为效率信号（``latency_score`` / ``tokens_score``）报告，不折进正确性分，
    以免把「慢」和「错」混为一谈。
    """
    arg_valid = _tool_argument_valid(step.tool, step.input)
    latency = step.effective_latency_ms
    tokens = step.cost.tokens

    status_factor = _status_factor(step.status)
    arg_factor = 0.0 if arg_valid is False else 1.0
    step_score = round(status_factor * arg_factor, 4)

    latency_score = _ratio_score(latency, budget.latency_ms)
    tokens_score = _ratio_score(None if tokens is None else float(tokens), budget.tokens)

    checks: list[str] = []
    if step.failed:
        checks.append("步骤失败（status=error）")
    if arg_valid is False:
        checks.append(f"工具参数结构性非法：{step.tool or step.step_type or '未知工具'}")
    if latency_score is not None and latency_score < 1.0:
        checks.append(f"单步延迟超预算：{latency:.0f}ms > {budget.latency_ms:.0f}ms")
    if tokens_score is not None and tokens_score < 1.0:
        checks.append(f"单步 token 超预算：{tokens} > {budget.tokens:.0f}")

    return {
        "index": step.index,
        "phase": step.phase or phase_for(step.tool or step.step_type),
        "tool": step.tool or step.step_type,
        "status": step.status,
        "latency_ms": None if latency is None else round(float(latency), 3),
        "tokens": tokens,
        "tool_argument_valid": arg_valid,
        "latency_score": None if latency_score is None else round(latency_score, 4),
        "tokens_score": None if tokens_score is None else round(tokens_score, 4),
        "retry": _is_retry(step, prev),
        "score": step_score,
        "error": step.error,
        "checks": checks,
    }


# --------------------------------------------------------------------------- #
# 确定性规则（轨迹级指标）
# --------------------------------------------------------------------------- #

def _rule_status_ok(steps: Sequence[TraceStep], _b: StepBudget) -> bool:
    return not any(s.failed for s in steps)


def _rule_tool_argument_valid(steps: Sequence[TraceStep], _b: StepBudget) -> bool:
    for s in steps:
        if _tool_argument_valid(s.tool, s.input) is False:
            return False
    return True


def _rule_phase_coverage(steps: Sequence[TraceStep], _b: StepBudget) -> float:
    if not DIAGNOSTIC_PHASES:
        return 1.0
    present = {s.phase for s in steps if s.phase}
    done = len(present & set(DIAGNOSTIC_PHASES))
    return round(done / len(DIAGNOSTIC_PHASES), 4)


def _rule_retry_count(steps: Sequence[TraceStep], _b: StepBudget) -> int:
    count = 0
    prev: TraceStep | None = None
    for s in steps:
        if _is_retry(s, prev):
            count += 1
        prev = s
    return count


def _rule_latency_ms(steps: Sequence[TraceStep], _b: StepBudget) -> float:
    return round(sum(s.effective_latency_ms or 0.0 for s in steps), 3)


def _rule_tokens(steps: Sequence[TraceStep], _b: StepBudget) -> int:
    return int(sum(s.cost.tokens or 0 for s in steps))


def _final_decision(steps: Sequence[TraceStep]) -> str | None:
    """取轨迹中最后一个显式给出 ``decision`` 的步骤输出。"""
    final: str | None = None
    for s in steps:
        out = _as_mapping(s.output)
        decision = out.get("decision")
        if isinstance(decision, str) and decision:
            final = decision
    return final


def _rule_downgrade_correctness(
    steps: Sequence[TraceStep], _b: StepBudget
) -> bool | None:
    """白盒核心：``evaluate_evidence`` 在证据不足时是否**没有**越级给出 verified。

    这是 ``false_verified``（硬闸门，要求比率为 0）的上游成因：若证据不足却仍在
    后续步骤给出 ``decision=verified``，即判错误（返回 ``False``）。

    返回 ``None`` 表示无法判定（无 evaluate_evidence 步骤 / 未给出证据充分性信号 /
    证据不足但未给出最终结论），此时该指标不参与统计。
    """
    ev_steps = [s for s in steps if s.tool == "evaluate_evidence"]
    if not ev_steps:
        return None

    insufficient = False
    for s in ev_steps:
        out = _as_mapping(s.output)
        if (out.get("insufficient_evidence") is True
                or out.get("evidence_sufficient") is False
                or out.get("evidence_complete") is False):
            insufficient = True
    if not insufficient:
        return None  # 证据充足：不需要降级，本项不判定

    final = _final_decision(steps)
    if final is None:
        return None
    return final != "verified"


#: 步骤指标注册表：指标名 → 确定性规则 ``(steps, budget) -> value``。
STEP_RULES: dict[str, Callable[[Sequence[TraceStep], StepBudget], Any]] = {
    "step_status_ok": _rule_status_ok,
    "step_tool_argument_valid": _rule_tool_argument_valid,
    "step_phase_coverage": _rule_phase_coverage,
    "step_retry_count": _rule_retry_count,
    "step_latency_ms": _rule_latency_ms,
    "step_tokens": _rule_tokens,
    "step_downgrade_correctness": _rule_downgrade_correctness,
}


# --------------------------------------------------------------------------- #
# 轨迹级评估 + 阶段上卷
# --------------------------------------------------------------------------- #

@dataclass
class TraceEvalResult:
    """一次运行的步骤级评估结果。"""

    case_id: str = ""
    run_id: str = ""
    source: str = "run-bundle"
    steps: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    phases: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_steps(self) -> bool:
        return bool(self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "run_id": self.run_id,
            "source": self.source,
            "step_count": len(self.steps),
            "summary": dict(self.summary),
            "phases": [dict(p) for p in self.phases],
            "steps": [dict(s) for s in self.steps],
        }


def _roll_up_phase(phase: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [r["score"] for r in rows]
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    tokens = [r["tokens"] for r in rows if r["tokens"] is not None]
    return {
        "phase": phase,
        "step_count": len(rows),
        "error_count": sum(1 for r in rows if r["status"] == "error"),
        "skipped_count": sum(1 for r in rows if r["status"] == "skipped"),
        "retry_count": sum(1 for r in rows if r["retry"]),
        "tool_call_count": sum(1 for r in rows if r["tool"]),
        "latency_ms_sum": round(sum(latencies), 3) if latencies else 0.0,
        "tokens_sum": int(sum(tokens)) if tokens else 0,
        "status_ok": not any(r["status"] == "error" for r in rows),
        "phase_score": round(sum(scores) / len(scores), 4) if scores else 1.0,
    }


def evaluate_trace(
    trace: StepTrace | Sequence[TraceStep] | Mapping[str, Any] | None,
    *,
    budget: StepBudget = DEFAULT_STEP_BUDGET,
) -> TraceEvalResult:
    """对一条步骤轨迹做完整评估，返回单步明细 + 轨迹级指标 + 阶段上卷。

    入参宽容：可传 ``StepTrace``、``TraceStep`` 序列、原始 dict，或 ``None``。
    ``None`` / 空轨迹返回空结果（``has_steps`` 为 ``False``）。
    """
    if trace is None:
        return TraceEvalResult()
    if isinstance(trace, StepTrace):
        steps_in: Sequence[TraceStep] = trace.steps
        meta = trace
    elif isinstance(trace, Mapping):
        meta = StepTrace.from_obj(trace)
        steps_in = meta.steps
    elif isinstance(trace, Sequence) and not isinstance(trace, (str, bytes)):
        steps_in = tuple(trace)
        meta = StepTrace(steps=steps_in)
    else:
        raise TypeError(f"无法解析步骤轨迹：{trace!r}")

    if not steps_in:
        return TraceEvalResult(case_id=meta.case_id, run_id=meta.run_id, source=meta.source)

    # 归一化阶段：来源只记录工具名时，据 8 工具映射补齐 phase（D6），
    # 使 step_phase_coverage 与阶段上卷在仅有工具名的轨迹上同样可用。
    steps_in = tuple(
        s if s.phase else replace(s, phase=phase_for(s.tool or s.step_type))
        for s in steps_in
    )

    rows: list[dict[str, Any]] = []
    prev: TraceStep | None = None
    for step in steps_in:
        rows.append(evaluate_step(step, prev=prev, budget=budget))
        prev = step

    # 轨迹级指标（只收录注册表内的 7 项；None 表示不可判定，跳过）
    summary: dict[str, Any] = {}
    for name in STEP_METRICS:
        rule = STEP_RULES.get(name)
        if rule is None:
            continue
        value = rule(steps_in, budget)
        if value is not None:
            summary[name] = value
    # step_retry_count 恒为 int（0 也有意义），显式保留
    summary.setdefault("step_retry_count", _rule_retry_count(steps_in, budget))

    # 阶段上卷（按 DIAGNOSTIC_PHASES 顺序，其次为未归类阶段）
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(row["phase"] or "", []).append(row)
    ordered = [p for p in DIAGNOSTIC_PHASES if p in buckets]
    ordered += [p for p in buckets if p not in DIAGNOSTIC_PHASES]
    phases = [_roll_up_phase(p, buckets[p]) for p in ordered]

    return TraceEvalResult(
        case_id=meta.case_id,
        run_id=meta.run_id,
        source=meta.source,
        steps=rows,
        summary=summary,
        phases=phases,
    )


def step_scores(result: TraceEvalResult) -> list[Score]:
    """把步骤级评估结果转成 Langfuse 友好的 ``Score`` 列表（scope=STEP）。

    - 轨迹级 7 项指标各一条（挂在该 trace 上）；
    - 每一步额外产出 ``step_score`` 与可测的 ``step_latency_ms`` / ``step_tokens``，
      ``metadata`` 带 ``step_index`` / ``phase`` / ``tool`` 以便 Langfuse 关联到 observation。
    """
    scores: list[Score] = []
    for name, value in result.summary.items():
        scores.append(make_score(name, value, metadata={"scope_id": result.case_id}))

    for row in result.steps:
        meta = {
            "scope_id": result.case_id,
            "step_index": row["index"],
            "phase": row["phase"],
            "tool": row["tool"],
        }
        scores.append(make_score("step_score", row["score"],
                                 data_type=DataType.NUMERIC,
                                 source=ScoreSource.EVAL,
                                 scope=ScoreScope.STEP,
                                 comment="; ".join(row["checks"]) or None,
                                 metadata=meta))
        if row["latency_ms"] is not None:
            scores.append(make_score("step_latency_ms", row["latency_ms"],
                                     data_type=None, metadata=meta))
        if row["tokens"] is not None:
            scores.append(make_score("step_tokens", row["tokens"],
                                     data_type=None, metadata=meta))
    return scores


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _sample_trace() -> StepTrace:
    return StepTrace.from_obj({
        "case_id": "case-01-slow-query-fullscan",
        "source": "run-bundle",
        "steps": [
            {"index": 0, "phase": "baseline", "tool": "create_task",
             "input": {"task": "排查慢查询"}, "status": "ok", "latency_ms": 120.0,
             "cost": {"tokens": 300}},
            {"index": 1, "phase": "baseline", "tool": "prepare_environment",
             "input": {"repository": "demo"}, "status": "ok", "latency_ms": 800.0},
            {"index": 2, "phase": "hypotheses", "tool": "discover_scenarios",
             "input": {"task": "排查慢查询"}, "status": "ok", "latency_ms": 1500.0},
            {"index": 3, "phase": "hypotheses", "tool": "propose_hypotheses",
             "input": {"observations": [{"slow": True}]}, "status": "ok",
             "latency_ms": 900.0, "cost": {"tokens": 1200}},
            {"index": 4, "phase": "discriminating_experiment", "tool": "run_experiment",
             "input": {"hypothesis": "missing_index"}, "status": "ok",
             "latency_ms": 5000.0, "cost": {"tokens": 2000}},
            {"index": 5, "phase": "localization", "tool": "evaluate_evidence",
             "input": {"hypothesis": "missing_index"}, "status": "ok",
             "latency_ms": 700.0,
             "output": {"insufficient_evidence": False, "decision": "verified"}},
            {"index": 6, "phase": "verification", "tool": "reconcile_task",
             "input": {"findings": [{"status": "verified"}]}, "status": "ok",
             "latency_ms": 400.0},
            {"index": 7, "phase": "verification", "tool": "finish_task",
             "input": {"report": {"decision": "verified"}}, "status": "ok",
             "latency_ms": 100.0},
        ],
    })


def _self_check() -> None:
    # 1) 正常轨迹：全绿，阶段全覆盖，无重试
    ok = evaluate_trace(_sample_trace())
    assert ok.has_steps and len(ok.steps) == 8
    s = ok.summary
    assert s["step_status_ok"] is True
    assert s["step_tool_argument_valid"] is True
    assert s["step_phase_coverage"] == 1.0, s
    assert s["step_retry_count"] == 0
    assert s["step_latency_ms"] == 9520.0, s
    assert s["step_tokens"] == 3500
    # 证据充足 → 降级正确性不判定（None → 不收录）
    assert "step_downgrade_correctness" not in s
    assert [p["phase"] for p in ok.phases] == list(DIAGNOSTIC_PHASES)
    assert all(p["status_ok"] for p in ok.phases)

    # 2) 单步分：error=0；skipped=0.5；参数非法=0
    err = evaluate_step(TraceStep(index=0, phase="baseline", tool="create_task",
                                  input={"task": "x"}, status="error"))
    assert err["score"] == 0.0 and err["checks"]
    skip = evaluate_step(TraceStep(index=1, phase="baseline", status="skipped"))
    assert skip["score"] == 0.5
    badarg = evaluate_step(TraceStep(index=2, phase="baseline", tool="run_experiment",
                                     input={}, status="ok"))
    assert badarg["tool_argument_valid"] is False and badarg["score"] == 0.0

    # 3) 重试检测：连续同工具同参数
    dup = [TraceStep(index=0, phase="hypotheses", tool="discover_scenarios",
                     input={"task": "x"}, status="ok"),
           TraceStep(index=1, phase="hypotheses", tool="discover_scenarios",
                     input={"task": "x"}, status="ok")]
    dres = evaluate_trace(dup)
    assert dres.summary["step_retry_count"] == 1, dres.summary

    # 4) 白盒核心：证据不足却 verified → 降级错误（False）
    bad_downgrade = StepTrace.from_obj({
        "case_id": "c", "steps": [
            {"index": 0, "phase": "discriminating_experiment", "tool": "run_experiment",
             "input": {"hypothesis": "h"}, "status": "ok"},
            {"index": 1, "phase": "localization", "tool": "evaluate_evidence",
             "input": {"hypothesis": "h"}, "status": "ok",
             "output": {"insufficient_evidence": True, "decision": "lead"}},
            {"index": 2, "phase": "verification", "tool": "finish_task",
             "input": {"report": {}}, "status": "ok",
             "output": {"decision": "verified"}},
        ],
    })
    assert evaluate_trace(bad_downgrade).summary["step_downgrade_correctness"] is False

    good_downgrade = StepTrace.from_obj({
        "case_id": "c", "steps": [
            {"index": 0, "phase": "localization", "tool": "evaluate_evidence",
             "input": {"hypothesis": "h"}, "status": "ok",
             "output": {"insufficient_evidence": True, "decision": "lead"}},
            {"index": 1, "phase": "verification", "tool": "finish_task",
             "input": {"report": {}}, "status": "ok", "output": {"decision": "lead"}},
        ],
    })
    assert evaluate_trace(good_downgrade).summary["step_downgrade_correctness"] is True

    # 5) 预算：超预算单步延迟衰减
    slow = evaluate_step(TraceStep(index=0, phase="baseline", tool="create_task",
                                   input={"task": "x"}, status="ok",
                                   latency_ms=30_000.0))
    assert slow["latency_score"] == 0.5, slow

    # 6) 空轨迹 / None 宽容
    assert not evaluate_trace(None).has_steps
    assert not evaluate_trace([]).has_steps
    assert not evaluate_trace(StepTrace()).has_steps

    # 7) Score 产出：scope=STEP，且带 step_index
    scores = step_scores(ok)
    assert scores and all(sc.scope.value == "STEP" for sc in scores)
    assert any("step_index" in sc.metadata for sc in scores)
    assert any(sc.name == "step_phase_coverage" for sc in scores)

    print("[ OK ] steps.py 自检通过：单步判定 + 7 项步骤指标 + 5 阶段上卷 + "
          "降级正确性（白盒核心）均符合预期")


if __name__ == "__main__":
    _self_check()
