#!/usr/bin/env python3
"""步骤轨迹 fixture 装载与合并（非冻结辅助模块）。

背景
----
白盒层（步骤级）轨迹以**独立 fixture** 的形式存放在
``evaluation/fixtures/steps/<case_id>.json``，与运行包（``fixtures/run-bundle/``）
分离：运行包保留 7 层金标准评测数据，步骤 fixture 只承载「逐步行为」。

``langfuse_export.case_events`` 的 span（observation）来源是 ``case["steps"]``。
真实运行包**不含** ``steps``，因此直接导出会产生 **0 个 observation span**。本模块
负责把步骤 fixture **合并**进下面两个去处：

1. **运行包**（run bundle）的 ``trajectory.steps`` —— 供 ``langfuse_export.export_bundle``
   以高保真方式产出 span（保留 ``input`` / ``output`` / 时间戳）；
2. **评估报告**（report）的用例条目 —— 供 ``langfuse_export.export_report`` 产出 span
   与 7 项步骤指标分数（``group == "step"``）。

红线（与整体工作边界一致）
--------------------------
- 只读、离线、零网络；不接触被测系统（SUT）。
- 报告富化**只新增**步骤层字段（``steps`` / ``phases`` / ``step_summary``）与
  ``group == "step"`` 的分数，**绝不改动** ``passed`` / ``gates`` / ``failed_gates`` /
  ``reward`` / 非步骤分数（D4：步骤层不进硬闸门与总分）。
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

# 让「直接运行」与「从 langfuse_deploy / 测试导入」都能解析同目录模块。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import steps as _steps  # noqa: E402  （确定性步骤评估器）
from scores import STEP_METRICS, make_score  # noqa: E402

__all__ = [
    "DEFAULT_STEPS_DIR",
    "load_step_fixtures",
    "load_step_fixture",
    "merge_bundle",
    "enrich_report",
    "evaluate_fixture",
]

#: 缺省步骤 fixture 目录：``evaluation/fixtures/steps``。
DEFAULT_STEPS_DIR: Path = _HERE / "fixtures" / "steps"


# --------------------------------------------------------------------------- #
# 装载
# --------------------------------------------------------------------------- #

def load_step_fixtures(
    steps_root: str | os.PathLike[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """扫描 ``<steps_root>/*.json``，返回 ``{case_id: fixture}``。

    ``case_id`` 取 fixture 内字段，缺失时退化为文件名（去扩展名）。目录不存在时返回空字典
    （宽容，便于在尚无步骤 fixture 的场景下继续运行）。
    """
    root = Path(steps_root) if steps_root is not None else DEFAULT_STEPS_DIR
    out: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                fixture = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(fixture, Mapping):
            continue
        case_id = str(fixture.get("case_id") or path.stem)
        out[case_id] = dict(fixture)
    return out


def load_step_fixture(
    case_id: str, steps_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """按 ``case_id`` 取单个步骤 fixture（不存在返回 ``None``）。"""
    return load_step_fixtures(steps_root).get(case_id)


# --------------------------------------------------------------------------- #
# 合并进运行包
# --------------------------------------------------------------------------- #

def merge_bundle(
    bundle: Mapping[str, Any],
    fixture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """把步骤 fixture 合并进运行包副本的 ``trajectory.steps``（不修改入参）。

    - ``fixture`` 为空时原样返回运行包（深拷贝）；
    - 保留 ``trajectory`` 既有字段（如 ``required_steps_done`` / ``tool_calls``），
      仅新增/覆盖 ``steps``（对象序列，兼容 ``contract.Trajectory.from_obj``）。
    """
    merged: dict[str, Any] = copy.deepcopy(dict(bundle))
    if not fixture:
        return merged
    steps = fixture.get("steps") or []
    if not steps:
        return merged
    trajectory = merged.get("trajectory")
    if not isinstance(trajectory, dict):
        trajectory = {}
    trajectory["steps"] = [dict(step) for step in steps]
    merged["trajectory"] = trajectory
    return merged


# --------------------------------------------------------------------------- #
# 富化报告用例（D4 安全）
# --------------------------------------------------------------------------- #

def evaluate_fixture(fixture: Mapping[str, Any]) -> "_steps.TraceEvalResult":
    """把步骤 fixture 归一为 ``TraceEvalResult``（供断言 / 复用）。

    **以整个 fixture 映射入参**（而非裸 ``steps`` 列表）：``evaluate_trace`` 只在
    ``Mapping`` 分支经 ``StepTrace.from_obj`` 把 dict 步骤正规化为 ``TraceStep``；
    裸序列分支不做元素正规化，会因 ``dict`` 无 ``phase`` 属性而报错。
    """
    if not fixture:
        return _steps.evaluate_trace(None)
    if isinstance(fixture, Mapping) and "steps" in fixture:
        return _steps.evaluate_trace(fixture)
    # 容错：仅给了裸步骤序列时，包一层映射以触发元素正规化。
    raw = fixture.get("steps") if isinstance(fixture, Mapping) else fixture
    return _steps.evaluate_trace({"steps": list(raw or [])})


def _step_score_dicts(trace: "_steps.TraceEvalResult") -> list[dict[str, Any]]:
    """按 ``metrics.compute_scores`` 同口径，把轨迹级步骤指标转成分数 dict。

    仅收录 ``scores.STEP_METRICS`` 内、且摘要里非空的值，``metadata.group == "step"``。
    """
    scores: list[dict[str, Any]] = []
    for name in STEP_METRICS:
        if name not in trace.summary:
            continue
        value = trace.summary[name]
        if value is None:
            continue
        scores.append(make_score(name, value, metadata={"group": "step"}).to_dict())
    return scores


def enrich_report(
    report: Mapping[str, Any],
    fixtures: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    steps_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """返回**报告副本**：为携带步骤 fixture 的用例补齐步骤层字段与步骤分数。

    - 用例无对应 fixture / fixture 为空时保持不变；
    - 只新增 ``steps`` / ``phases`` / ``step_summary``，并用 ``group == "step"`` 的分数
      **替换**同类旧分数（正常情况下本就不存在，因无 steps 时不会产出）；
    - ``passed`` / ``gates`` / ``failed_gates`` / ``reward`` / 非步骤分数一律保持原值（D4）。
    """
    resolved: Mapping[str, Mapping[str, Any]]
    if fixtures is not None:
        resolved = fixtures
    else:
        resolved = load_step_fixtures(steps_root)

    enriched: dict[str, Any] = copy.deepcopy(dict(report))
    for case in (enriched.get("cases") or []):
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id"))
        fixture = resolved.get(case_id)
        if not fixture:
            continue
        trace = evaluate_fixture(fixture)
        if not trace.has_steps:
            continue
        case["steps"] = [dict(row) for row in trace.steps]
        case["phases"] = [dict(row) for row in trace.phases]
        case["step_summary"] = dict(trace.summary)
        kept = [s for s in (case.get("scores") or [])
                if (s.get("metadata") or {}).get("group") != "step"]
        case["scores"] = kept + _step_score_dicts(trace)
    return enriched


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _self_check() -> None:
    """离线自检：装载 / 归一化 / 合并 / 富化 / D4 安全 / 确定性（零网络、零 SUT）。"""
    import tempfile

    fixture = {
        "case_id": "case-x-demo",
        "run_id": "run-x-0001",
        "source": "run-bundle",
        "steps": [
            {"index": 0, "tool": "create_task", "phase": "baseline", "status": "ok",
             "input": {"task": "接口变慢"}, "output": {}},
            {"index": 1, "tool": "discover_scenarios", "phase": "baseline", "status": "ok"},
            {"index": 2, "tool": "propose_hypotheses", "phase": "hypotheses", "status": "ok"},
            {"index": 3, "tool": "run_experiment", "phase": "discriminating_experiment",
             "status": "ok"},
            {"index": 4, "tool": "evaluate_evidence", "phase": "localization", "status": "ok"},
            {"index": 5, "tool": "finish_task", "phase": "verification", "status": "ok"},
        ],
    }

    # 1) 装载：临时目录 -> {case_id: fixture}，缺失键返回 None
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "case-x-demo.json").write_text(
            json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        loaded = load_step_fixtures(tmp)
        assert set(loaded) == {"case-x-demo"}, loaded
        assert load_step_fixture("case-x-demo", tmp) is not None
        assert load_step_fixture("missing", tmp) is None

    # 2) evaluate_fixture：dict 步骤被正规化为 TraceStep，has_steps 为真
    trace = evaluate_fixture(fixture)
    assert trace.has_steps is True
    assert len(trace.steps) == 6, len(trace.steps)

    # 3) merge_bundle：只新增 trajectory.steps，绝不修改入参
    bundle = {"trajectory": {"required_steps_done": True}}
    merged = merge_bundle(bundle, fixture)
    assert len(merged["trajectory"]["steps"]) == 6
    assert merged["trajectory"]["required_steps_done"] is True
    assert "steps" not in bundle["trajectory"], "merge_bundle 不得修改入参"

    # 4) enrich_report：新增步骤层字段，D4 字段（passed/gates/reward）原样保持
    report = {
        "manifest": {"generated_at": "t"},
        "cases": [{
            "case_id": "case-x-demo",
            "passed": True,
            "gates": {"false_verified": True},
            "failed_gates": [],
            "reward": {"total": 0.9, "group_scores": {"conclusion": 1.0}},
            "scores": [{"name": "decision_match", "value": "exact",
                        "metadata": {"group": "conclusion"}}],
        }],
    }
    enriched = enrich_report(report, {"case-x-demo": fixture})
    case = enriched["cases"][0]
    assert case["passed"] is True
    assert case["gates"] == {"false_verified": True}
    assert case["failed_gates"] == []
    assert case["reward"] == {"total": 0.9, "group_scores": {"conclusion": 1.0}}
    assert len(case["steps"]) == 6
    assert "phases" in case and "step_summary" in case
    groups = {(s.get("metadata") or {}).get("group") for s in case["scores"]}
    assert "conclusion" in groups  # 非步骤分保留
    assert groups <= {"conclusion", "step"}  # 分数只可能是这两类
    assert "steps" not in report["cases"][0], "enrich_report 不得修改入参"

    # 5) 无 fixture 的用例保持不变（宽容）
    assert "steps" not in enrich_report(report, {})["cases"][0]

    # 6) 确定性：同输入两次结果一致
    _dump = lambda _r: json.dumps(enrich_report(_r, {"case-x-demo": fixture}),
                                  ensure_ascii=False, sort_keys=True)
    assert _dump(report) == _dump(report)

    print("[ OK ] step_fixtures.py 自检通过：装载/归一化、merge_bundle 不修改入参、"
          "enrich_report 仅新增步骤层字段（D4 安全）、确定性均符合预期")


if __name__ == "__main__":
    _self_check()
