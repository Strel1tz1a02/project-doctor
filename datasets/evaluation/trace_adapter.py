#!/usr/bin/env python3
"""步骤轨迹适配器（纯标准库，**零执行 / 零网络**）。

职责
----
把两条来源的「步骤记录」**归一化**为统一中间表示 ``contract.StepTrace``，
供 ``steps.py`` 做确定性打分、供 ``langfuse_export.py`` 产出摄入文件：

- ``FromRunBundle``：路径甲（离线）—— 执行侧把过程导出为运行包 / 步骤 JSON；
- ``FromInterface``：路径乙（在线只读）—— 任务包 / AGH 执行记录等只读导出；
- ``FromLangfuse``：路径乙（在线只读）—— Langfuse Trace/Observation 导出 JSON。

硬边界（务必遵守）
------------------
本模块**只做数据形状转换**：不发起网络请求、不启动被测系统（SUT）、不调用任何
诊断工具。真正的「取回」动作由调用方在**读操作**通道上完成，本模块只接收已取回
的普通 ``dict`` / ``list``。

设计红线（对应决策 D2 / D3 / D6）
---------------------------------
- **D2**：执行侧产出记录，我方只消费 + 打分——本模块只读入、只归一化；
- **D3**：不依赖逐步骤正解——适配器只搬运客观字段，不做正确性判断；
- **D6**：以 8 个 MCP 工具为准——由工具名推导所属诊断阶段（``TOOL_PHASE``）。

直接运行本文件会执行一段自检：

    python evaluation/trace_adapter.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

# 让直接运行（python evaluation/trace_adapter.py）与从别处导入都能解析同目录模块。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from contract import DIAGNOSTIC_PHASES, StepCost, StepTrace, TraceStep  # noqa: E402
from steps import MCP_TOOLS, TOOL_PHASE, phase_for  # noqa: E402

__all__ = [
    "TOOL_PHASE",
    "TOOL_ORDER",
    "phase_for",
    "FromRunBundle",
    "FromInterface",
    "FromLangfuse",
    "normalize",
]

# --------------------------------------------------------------------------- #
# 工具 → 诊断阶段（D6：以 8 工具为准，上卷到 5 诊断阶段；见方案 §5.2）
# 规范的 ``TOOL_PHASE`` / ``phase_for`` 定义在 ``steps.py``，此处复用以免两处漂移。
# --------------------------------------------------------------------------- #

#: 工具的规范闭环顺序（用于缺 ``index`` 时按出现序编号、以及可读性校验）。
TOOL_ORDER: tuple[str, ...] = (
    "create_task", "prepare_environment", "discover_scenarios", "propose_hypotheses",
    "run_experiment", "evaluate_evidence", "reconcile_task", "finish_task",
)

#: 状态别名 → 契约取值（ok / error / skipped）。
_STATUS_ALIASES: dict[str, str] = {
    "ok": "ok", "success": "ok", "succeeded": "ok", "done": "ok", "completed": "ok",
    "error": "error", "failed": "error", "failure": "error", "exception": "error",
    "skipped": "skipped", "skip": "skipped", "noop": "skipped",
}

#: 时间戳单位阈值：大于此值视为毫秒（Langfuse/部分接口用毫秒 epoch）。
_MS_EPOCH_THRESHOLD = 1e12


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #

def _first(obj: Mapping[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    """按优先级取第一个非 ``None`` 的字段值。"""
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return default


def _canon_status(value: Any) -> str:
    if value is None:
        return "ok"
    text = str(value).strip().lower()
    return _STATUS_ALIASES.get(text, text or "ok")


def _parse_ts(value: Any) -> float | None:
    """把时间戳解析为 epoch 秒（float）。

    - 数字：视为 epoch（大于阈值按毫秒折算为秒）；
    - 字符串：ISO 8601（兼容结尾 ``Z``，3.10 的 ``fromisoformat`` 不认 ``Z``）；
    - 其它/无法解析：返回 ``None``。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number / 1000.0 if number > _MS_EPOCH_THRESHOLD else number
    text = str(value).strip()
    if not text:
        return None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _tokens_from_usage(usage: Any) -> int | None:
    """从 Langfuse ``usage`` / ``usageDetails`` 提取总 token 数。"""
    if not isinstance(usage, Mapping):
        return None
    total = _first(usage, ("total", "totalTokens", "total_tokens"))
    if total is not None:
        try:
            return int(total)
        except (TypeError, ValueError):
            return None
    parts = [
        _first(usage, ("input", "promptTokens", "prompt_tokens", "inputTokens")),
        _first(usage, ("output", "completionTokens", "completion_tokens", "outputTokens")),
    ]
    numbers = []
    for part in parts:
        if part is None:
            continue
        try:
            numbers.append(int(part))
        except (TypeError, ValueError):
            continue
    return sum(numbers) if numbers else None


def _coerce_step(obj: Any, index: int) -> TraceStep | None:
    """把一条原始记录归一化为 ``TraceStep``（补齐 tool / phase / status）。

    返回 ``None`` 表示该条记录不是可识别的步骤（跳过）。
    """
    if isinstance(obj, TraceStep):
        step = obj
    elif isinstance(obj, Mapping):
        # 兼容常见字段别名后再交给契约解析。
        raw = dict(obj)
        if "tool" not in raw:
            raw["tool"] = _first(raw, ("tool_name", "name", "toolName"), "")
        if "input" not in raw:
            raw["input"] = _first(raw, ("arguments", "args", "parameter", "params"))
        if "output" not in raw:
            raw["output"] = _first(raw, ("result", "response", "observation"))
        if "step_type" not in raw:
            raw["step_type"] = _first(raw, ("type", "name"), "")
        step = TraceStep.from_obj(raw, index=index)
    else:
        return None

    # 归一化 status（兼容 success/failed 等别名）。
    status = _canon_status(step.status)
    # 工具名：优先显式 tool，其次 step_type 命中 8 工具之一。
    tool = step.tool
    if not tool and step.step_type in MCP_TOOLS:
        tool = step.step_type
    # 阶段：显式 phase 优先，否则由工具名推导（不臆造）。
    phase = step.phase or phase_for(tool)

    if status != step.status or tool != step.tool or phase != step.phase or step.index != index:
        step = replace(step, index=index, status=status, tool=tool, phase=phase)
    return step


def _coerce_steps(raw_steps: Any, *, start_index: int = 0) -> tuple[TraceStep, ...]:
    """把原始步骤序列归一化为 ``TraceStep`` 序列（跳过不可识别项，重编 index）。"""
    if raw_steps is None:
        return ()
    if isinstance(raw_steps, Mapping):
        raw_steps = [raw_steps]
    if isinstance(raw_steps, (str, bytes)) or not isinstance(raw_steps, Sequence):
        return ()
    out: list[TraceStep] = []
    for item in raw_steps:
        step = _coerce_step(item, start_index + len(out))
        if step is not None:
            out.append(step)
    return tuple(out)


def _observations_from(trace_obj: Mapping[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    """从 Langfuse 导出对象里取出 observations 列表与 trace 级元信息。"""
    raw_trace = trace_obj.get("trace")
    trace_meta: dict[str, Any] = dict(raw_trace) if isinstance(raw_trace, Mapping) else {}
    observations = trace_obj.get("observations")
    if observations is None and isinstance(raw_trace, Mapping):
        observations = raw_trace.get("observations")
    if observations is None:
        observations = trace_obj.get("spans")
    if observations is None:
        observations = trace_obj.get("children")
    if isinstance(observations, Mapping):
        observations = [observations]
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        observations = []
    for key in ("id", "name", "metadata", "input", "output", "userId", "sessionId"):
        if key in trace_obj and key not in trace_meta:
            trace_meta[key] = trace_obj[key]
    return list(observations), trace_meta


# --------------------------------------------------------------------------- #
# 路径甲：运行包 / 离线步骤 JSON
# --------------------------------------------------------------------------- #

class FromRunBundle:
    """把（运行包 / 轨迹层 / 裸步骤 JSON）归一化为 ``StepTrace``（source=``run-bundle``）。"""

    source = "run-bundle"

    @classmethod
    def normalize(
        cls,
        bundle: Any,
        *,
        case_id: str = "",
        run_id: str = "",
    ) -> StepTrace:
        if isinstance(bundle, StepTrace):
            return bundle
        if not isinstance(bundle, Mapping):
            return StepTrace(case_id=case_id, run_id=run_id, source=cls.source,
                             steps=_coerce_steps(bundle))

        collection = bundle.get("collection") if isinstance(bundle.get("collection"), Mapping) else {}
        trajectory = bundle.get("trajectory")
        resolved_case = case_id or str(collection.get("case_id") or "")

        raw_steps: Any = None
        if isinstance(trajectory, Mapping):
            raw_steps = trajectory.get("steps")
        elif trajectory is not None:
            raw_steps = trajectory
        if raw_steps is None:
            # 也允许直接传入「含 steps 的轨迹层」或裸载荷。
            raw_steps = bundle.get("steps")

        resolved_run = run_id or str(
            bundle.get("run_id") or collection.get("run_id") or ""
        )
        return StepTrace(
            case_id=resolved_case,
            run_id=resolved_run,
            source=cls.source,
            steps=_coerce_steps(raw_steps),
        )


# --------------------------------------------------------------------------- #
# 路径乙（a）：只读接口 / AGH 执行记录
# --------------------------------------------------------------------------- #

class FromInterface:
    """把只读接口导出（任务包 / AGH 执行记录）归一化为 ``StepTrace``（source=``interface``）。"""

    source = "interface"

    #: 可能的步骤列表字段名（按优先级）。
    _STEP_KEYS = ("steps", "operations", "tool_calls", "toolCalls", "events", "records")

    @classmethod
    def normalize(
        cls,
        record: Any,
        *,
        case_id: str = "",
        run_id: str = "",
    ) -> StepTrace:
        if isinstance(record, StepTrace):
            return record
        if isinstance(record, Mapping):
            raw_steps: Any = None
            for key in cls._STEP_KEYS:
                if record.get(key) is not None:
                    raw_steps = record[key]
                    break
            resolved_case = case_id or str(
                _first(record, ("case_id", "task_id", "taskId"), "") or ""
            )
            resolved_run = run_id or str(
                _first(record, ("run_id", "runId", "session_id", "sessionId"), "") or ""
            )
        else:
            raw_steps = record
            resolved_case, resolved_run = case_id, run_id
        return StepTrace(
            case_id=resolved_case,
            run_id=resolved_run,
            source=cls.source,
            steps=_coerce_steps(raw_steps),
        )


# --------------------------------------------------------------------------- #
# 路径乙（b）：Langfuse Trace / Observation 导出
# --------------------------------------------------------------------------- #

class FromLangfuse:
    """把 Langfuse 导出对象归一化为 ``StepTrace``（source=``langfuse``）。

    期望形状（字段均可缺）::

        {
          "id": "trace-xxx", "name": "case-01", "sessionId": "...",
          "observations": [
            {"id": "obs-1", "name": "run_experiment", "type": "SPAN",
             "startTime": "2026-10-06T12:00:00Z", "endTime": "2026-10-06T12:00:05Z",
             "input": {...}, "output": {...}, "level": "DEFAULT",
             "statusMessage": null, "usage": {"input": 100, "output": 200},
             "metadata": {"phase": "..."}}
          ]
        }
    """

    source = "langfuse"

    @classmethod
    def normalize(
        cls,
        trace_obj: Any,
        *,
        case_id: str = "",
        run_id: str = "",
    ) -> StepTrace:
        if isinstance(trace_obj, StepTrace):
            return trace_obj
        if not isinstance(trace_obj, Mapping):
            return StepTrace(case_id=case_id, run_id=run_id, source=cls.source)

        observations, meta = _observations_from(trace_obj)
        resolved_case = case_id or str(meta.get("name") or meta.get("case_id") or "")
        resolved_run = run_id or str(
            meta.get("id") or meta.get("sessionId") or meta.get("run_id") or ""
        )

        steps: list[TraceStep] = []
        for item in observations:
            step = cls._observation_to_step(item, index=len(steps))
            if step is not None:
                steps.append(step)
        return StepTrace(
            case_id=resolved_case,
            run_id=resolved_run,
            source=cls.source,
            steps=tuple(steps),
        )

    @classmethod
    def _observation_to_step(cls, obs: Any, *, index: int) -> TraceStep | None:
        if not isinstance(obs, Mapping):
            return None
        metadata = obs.get("metadata") if isinstance(obs.get("metadata"), Mapping) else {}

        # 名称：优先 metadata.tool / metadata.phase，其次 observation.name。
        name = str(_first(obs, ("name", "tool_name"), "") or "")
        tool = str(metadata.get("tool") or (name if name in MCP_TOOLS else ""))
        phase = str(
            metadata.get("phase")
            or _first(obs, ("phase",), "")
            or phase_for(tool or name)
            or ""
        )

        # 状态：level=ERROR / statusMessage 存在 → error；否则 ok。
        level = str(_first(obs, ("level",), "") or "").upper()
        error_text = str(_first(obs, ("statusMessage", "status_message", "error"), "") or "")
        if level == "ERROR" or error_text:
            status = "error"
        else:
            status = _canon_status(_first(obs, ("status",), "ok"))

        ts_start = _parse_ts(_first(obs, ("startTime", "start_time", "timestamp", "ts"), None))
        ts_end = _parse_ts(_first(obs, ("endTime", "end_time", "ts_end"), None))
        latency_ms = None
        if ts_start is not None and ts_end is not None:
            latency_ms = round((ts_end - ts_start) * 1000.0, 3)

        tokens = _tokens_from_usage(_first(obs, ("usage", "usageDetails", "usage_details"), None))

        raw = {
            "index": index,
            "step_type": str(_first(obs, ("type", "name"), "") or name),
            "phase": phase,
            "status": status,
            "tool": tool,
            "input": _first(obs, ("input",), metadata.get("input")),
            "output": _first(obs, ("output",), None),
            "ts_start": ts_start,
            "ts_end": ts_end,
            "latency_ms": latency_ms,
            "cost": StepCost(tokens=tokens),
            "error": error_text,
        }
        return _coerce_step(raw, index)


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #

def normalize(
    obj: Any,
    *,
    source: str | None = None,
    case_id: str = "",
    run_id: str = "",
) -> StepTrace:
    """统一归一化入口：把任意来源归一到 ``StepTrace``。

    ``source`` 可显式指定 ``run-bundle`` / ``interface`` / ``langfuse``；
    省略时按结构自动判别（``observations`` → langfuse；``operations``/``tool_calls``
    → interface；其余含 ``trajectory`` / ``steps`` → run-bundle）。
    """
    if isinstance(obj, StepTrace):
        return obj
    if source == "run-bundle":
        return FromRunBundle.normalize(obj, case_id=case_id, run_id=run_id)
    if source == "interface":
        return FromInterface.normalize(obj, case_id=case_id, run_id=run_id)
    if source == "langfuse":
        return FromLangfuse.normalize(obj, case_id=case_id, run_id=run_id)
    if source is not None:
        raise ValueError(f"未知来源 {source!r}（应为 run-bundle / interface / langfuse）")

    # 自动判别
    if isinstance(obj, Mapping):
        if any(k in obj for k in ("observations", "spans")) or "trace" in obj:
            return FromLangfuse.normalize(obj, case_id=case_id, run_id=run_id)
        if any(k in obj for k in FromInterface._STEP_KEYS if k != "steps"):
            return FromInterface.normalize(obj, case_id=case_id, run_id=run_id)
    return FromRunBundle.normalize(obj, case_id=case_id, run_id=run_id)


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _self_check() -> None:
    import steps as S

    # 1) 路径甲：运行包 → StepTrace，工具名推导阶段，index 重编
    bundle = {
        "trajectory": {"steps": [
            {"tool": "create_task", "input": {"task": "t"}, "status": "ok"},
            {"tool": "prepare_environment", "input": {"repository": "r"}, "status": "ok"},
            {"tool": "run_experiment", "input": {"hypothesis": "h"}, "status": "success"},
            {"tool": "evaluate_evidence", "input": {"hypothesis": "h"}, "status": "ok",
             "output": {"insufficient_evidence": False, "decision": "verified"}},
        ]},
        "collection": {"case_id": "case-01-slow-query-fullscan"},
    }
    rb = FromRunBundle.normalize(bundle)
    assert rb.source == "run-bundle" and rb.case_id == "case-01-slow-query-fullscan"
    assert [s.index for s in rb.steps] == [0, 1, 2, 3]
    assert rb.steps[0].phase == "baseline" and rb.steps[2].phase == "discriminating_experiment"
    assert rb.steps[2].status == "ok", "success 应归一为 ok"

    # 2) 路径乙（a）：AGH 执行记录（operations）
    record = {
        "task_id": "task-9",
        "operations": [
            {"tool_name": "discover_scenarios", "arguments": {"task": "t"},
             "result": {"scenarios": [1]}, "status": "ok"},
            {"name": "propose_hypotheses", "args": {"observations": []}, "status": "failed"},
        ],
    }
    iface = FromInterface.normalize(record)
    assert iface.source == "interface" and iface.case_id == "task-9"
    assert len(iface.steps) == 2
    assert iface.steps[0].tool == "discover_scenarios" and iface.steps[0].phase == "hypotheses"
    assert iface.steps[1].status == "error", "failed 应归一为 error"

    # 3) 路径乙（b）：Langfuse 导出
    langfuse = {
        "id": "trace-abc", "name": "case-01",
        "observations": [
            {"id": "o1", "name": "run_experiment", "type": "SPAN",
             "startTime": "2026-10-06T12:00:00Z", "endTime": "2026-10-06T12:00:05Z",
             "input": {"hypothesis": "h"}, "output": {"ok": True},
             "level": "DEFAULT", "usage": {"input": 100, "output": 200}},
            {"id": "o2", "name": "evaluate_evidence", "type": "SPAN",
             "startTime": "2026-10-06T12:00:05Z", "endTime": "2026-10-06T12:00:06Z",
             "metadata": {"phase": "localization"}, "level": "ERROR",
             "statusMessage": "boom"},
        ],
    }
    lf = FromLangfuse.normalize(langfuse)
    assert lf.source == "langfuse" and lf.run_id == "trace-abc"
    assert len(lf.steps) == 2
    assert lf.steps[0].phase == "discriminating_experiment"
    assert lf.steps[0].latency_ms == 5000.0, lf.steps[0].latency_ms
    assert lf.steps[0].cost.tokens == 300, lf.steps[0].cost
    assert lf.steps[1].status == "error" and lf.steps[1].error == "boom"
    assert lf.steps[1].phase == "localization"

    # 4) 统一入口自动判别
    assert normalize(bundle).source == "run-bundle"
    assert normalize(record).source == "interface"
    assert normalize(langfuse).source == "langfuse"
    assert normalize(record, source="interface").case_id == "task-9"
    try:
        normalize(bundle, source="unknown")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("未知来源应抛 ValueError")

    # 5) 与 steps.py 打通：三种来源都能跑确定性评估
    for trace in (rb, iface, lf):
        result = S.evaluate_trace(trace)
        assert result.has_steps, trace.source
        assert 0.0 <= result.summary["step_phase_coverage"] <= 1.0
        assert all(p["phase"] in DIAGNOSTIC_PHASES for p in result.phases)

    # 6) 空/异常输入宽容
    assert not normalize(None).steps
    assert not normalize({}).steps
    assert not normalize([], source="interface").steps

    print("[ OK ] trace_adapter.py 自检通过：run-bundle / interface / langfuse "
          "三来源归一化 + 自动判别 + 与 steps.py 打通均符合预期")


if __name__ == "__main__":
    _self_check()
