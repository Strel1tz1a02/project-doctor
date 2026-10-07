#!/usr/bin/env python3
"""Langfuse 摄入导出器（离线优先，纯标准库实现）。

职责
----
把「一次评估运行」的产物（``run_eval.py`` 的报告 dict，或一个运行包 + 用例定义）
转换为 **Langfuse Ingestion API** 可摄入的 JSON 事件批次（``{"batch": [...]}``），
**离线生成、不发起任何网络请求**。

映射（见 docs/步骤级评价与Langfuse接入方案.md §4）
--------------------------------------------------
- 一次运行 / 一个用例 -> Trace（``trace-create``），``sessionId`` = 本轮评估会话
- 一个步骤           -> Observation（``span-create``，``span.id`` 即 observationId）
- 用例分（DATASET_ITEM / RUN 作用域）-> 挂 trace 的 ``score-create``
- 步骤分（STEP 作用域，带 ``step_index``）-> 挂 observation 的 ``score-create``
- 用例集合           -> Dataset / Dataset Item（``dataset_bodies``）
- 一轮实验           -> Dataset Run（``dataset_run_item_bodies``）

设计红线（对应决策 D3 / D4）
---------------------------
- **D3：只用确定性规则。** 本模块只做「已算好的分数 -> Langfuse 事件」的确定性搬运，
  不引入任何新判定，也不依赖逐步骤正解。
- **D4：步骤分不进硬闸门 / 总分。** 步骤分只作为 observation 级 ``score`` 挂载，
  供归因下钻；trace 上的用例分即 ``cases[].scores``，其口径完全由评测器决定。
- **只读搬运：** 不访问网络 / 数据库，也不调用被测系统；默认离线产出 JSON 文本。
  是否真正写入 Langfuse 由使用方（D5：我方完成部署）另行决定。

Langfuse 事件约定（依据 Ingestion API）
--------------------------------------
- 端点 ``POST /api/public/ingestion``，请求体 ``{"batch": [<event>...]}``，
  返回 ``207``，含 ``successes`` / ``errors``；
- 每个事件形如 ``{"id", "type", "timestamp", "body"}``，``type`` 为 kebab-case：
  ``trace-create`` / ``span-create`` / ``score-create`` 等；
- **布尔分数必须以 ``1`` / ``0`` 写入**（Langfuse 要求），本模块统一转换；
- 事件 id 由 ``uuid5`` 确定性派生，重复摄入幂等（同 id 覆盖）。

用法
----
    from langfuse_export import export_report_file, write_ingestion

    result = export_report_file("evaluation/out/report.json", run_name="2026-10-02")
    write_ingestion(result, "evaluation/out/langfuse_ingestion.json")
    result.counts()      # {"trace": 8, "span": ..., "score": ...}

直接运行本文件会执行一段自检：

    python evaluation/langfuse_export.py

也可直接导出报告：

    python evaluation/langfuse_export.py --report evaluation/out/report.json \
        --out evaluation/out/langfuse_ingestion.json --run-name 2026-10-02
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# 让直接运行（python evaluation/langfuse_export.py）与从别处导入都能解析同目录模块。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_TOOLS = _HERE.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import contract as C  # noqa: E402
from metrics import EvalInput, evaluate_case  # noqa: E402

__all__ = [
    "ExportResult",
    "ENDPOINTS",
    "trace_id_for",
    "observation_id_for",
    "export_report",
    "export_report_file",
    "export_bundle",
    "case_events",
    "dataset_bodies",
    "dataset_item_body",
    "dataset_run_item_body",
    "write_ingestion",
]

#: 相关 Langfuse 端点（本模块只产出请求体，不发送请求）。
ENDPOINTS: dict[str, str] = {
    "ingestion": "/api/public/ingestion",
    "dataset": "/api/public/v2/datasets",
    "dataset_item": "/api/public/dataset-items",
    "dataset_run_item": "/api/public/dataset-run-items",
}

# 事件类型（kebab-case，与 Langfuse Ingestion API 一致）。
_TRACE_CREATE = "trace-create"
_SPAN_CREATE = "span-create"
_SCORE_CREATE = "score-create"

#: 固定命名空间：保证事件 / trace / observation id 跨进程、跨机器确定性可复现。
_NAMESPACE = uuid.UUID("6f3d2a1e-9c47-4b58-8f10-2d7c5e9a0b31")


# --------------------------------------------------------------------------- #
# 确定性 id 与时间
# --------------------------------------------------------------------------- #

def _uid(*parts: Any) -> str:
    """由若干部分确定性派生一个 uuid 字符串（同输入 -> 同输出）。"""
    return str(uuid.uuid5(_NAMESPACE, "|".join(str(p) for p in parts)))


def trace_id_for(run_name: str, case_id: str) -> str:
    """一个用例在 Langfuse 中的 trace id（确定性，跨次运行稳定）。"""
    return _uid("trace", run_name, case_id)


def observation_id_for(trace_id: str, step_index: Any) -> str:
    """一个步骤（observation）的 id（确定性）。"""
    return _uid("observation", trace_id, step_index)


def _iso(ts: Any) -> str | None:
    """把 epoch 秒（float）或 ISO 字符串归一化成带 ``Z`` 的 UTC ISO8601。"""
    if ts is None:
        return None
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        dt = _dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    return str(ts)


# --------------------------------------------------------------------------- #
# 结果容器
# --------------------------------------------------------------------------- #

@dataclass
class ExportResult:
    """一次导出的事件集合（可序列化为 Ingestion 请求体）。"""

    run_name: str
    session_id: str
    events: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """按事件类型计数：``trace`` / ``span`` / ``score``。"""
        counter = {"trace": 0, "span": 0, "score": 0}
        key_of = {_TRACE_CREATE: "trace", _SPAN_CREATE: "span", _SCORE_CREATE: "score"}
        for event in self.events:
            bucket = key_of.get(event.get("type"))
            if bucket:
                counter[bucket] += 1
        return counter

    def to_ingestion_payload(self) -> dict[str, Any]:
        """``POST /api/public/ingestion`` 的请求体。"""
        return {"batch": [dict(e) for e in self.events]}

    def to_dict(self) -> dict[str, Any]:
        """自包含快照（含计数），便于落盘审阅。"""
        return {
            "run_name": self.run_name,
            "session_id": self.session_id,
            "counts": self.counts(),
            "batch": [dict(e) for e in self.events],
        }


# --------------------------------------------------------------------------- #
# 分数值转换
# --------------------------------------------------------------------------- #

def _score_value(value: Any, data_type: str | None) -> Any:
    """按 Langfuse 要求转换分数字面量（布尔 -> 1/0）。"""
    if data_type == "BOOLEAN":
        return 1 if value else 0
    if data_type == "CATEGORICAL":
        return None if value is None else str(value)
    if data_type == "TEXT":
        return None if value is None else str(value)
    if data_type == "CORRECTION":
        return dict(value) if isinstance(value, Mapping) else value
    return value  # NUMERIC / 未知：原样透传


# --------------------------------------------------------------------------- #
# 事件构造
# --------------------------------------------------------------------------- #

def _trace_body(*, trace_id: str, name: str, session_id: str | None,
                timestamp: str | None = None, input_: Any = None, output: Any = None,
                metadata: Mapping[str, Any] | None = None,
                tags: Sequence[str] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"id": trace_id, "name": name}
    if session_id:
        body["sessionId"] = session_id
    if timestamp:
        body["timestamp"] = timestamp
    if input_ is not None:
        body["input"] = input_
    if output is not None:
        body["output"] = output
    if metadata:
        body["metadata"] = dict(metadata)
    if tags:
        body["tags"] = list(tags)
    return body


def _span_body(*, observation_id: str, trace_id: str, name: str,
               start_time: str | None = None, end_time: str | None = None,
               input_: Any = None, output: Any = None,
               metadata: Mapping[str, Any] | None = None,
               level: str | None = None, status_message: str | None = None,
               parent_observation_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"id": observation_id, "traceId": trace_id, "name": name}
    if start_time:
        body["startTime"] = start_time
    if end_time:
        body["endTime"] = end_time
    if input_ is not None:
        body["input"] = input_
    if output is not None:
        body["output"] = output
    if metadata:
        body["metadata"] = dict(metadata)
    if level and level != "DEFAULT":
        body["level"] = level
    if status_message:
        body["statusMessage"] = status_message
    if parent_observation_id:
        body["parentObservationId"] = parent_observation_id
    return body


def _score_body(*, trace_id: str, name: str, value: Any, data_type: str,
                observation_id: str | None = None, comment: str | None = None,
                metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "traceId": trace_id,
        "name": name,
        "value": _score_value(value, data_type),
        "dataType": data_type,
    }
    if observation_id:
        body["observationId"] = observation_id
    if comment:
        body["comment"] = comment
    if metadata:
        body["metadata"] = dict(metadata)
    return body


def _event(type_: str, body: Mapping[str, Any], *id_parts: Any) -> dict[str, Any]:
    """包一个 Ingestion 事件：``{"id", "type", "body"}``（id 确定性派生）。"""
    return {"id": _uid("event", type_, *id_parts), "type": type_, "body": dict(body)}


# --------------------------------------------------------------------------- #
# 单步 -> span + observation 级分数
# --------------------------------------------------------------------------- #

def _step_span_event(trace_id: str, row: Mapping[str, Any],
                     rich: "C.TraceStep | None", observation_id: str) -> dict[str, Any]:
    index = row.get("index")
    tool = row.get("tool")
    name = str(tool) if tool else f"step-{index}"

    metadata: dict[str, Any] = {
        "step_index": index,
        "phase": row.get("phase"),
        "tool": tool,
        "status": row.get("status"),
        "latency_ms": row.get("latency_ms"),
        "tokens": row.get("tokens"),
        "retry": row.get("retry"),
        "tool_argument_valid": row.get("tool_argument_valid"),
        "step_score": row.get("score"),
    }
    checks = row.get("checks") or []
    if checks:
        metadata["checks"] = list(checks)

    level = "ERROR" if str(row.get("status")) == "error" else "DEFAULT"
    status_message = str(row.get("error") or "") or None

    start_time = end_time = None
    input_ = output = None
    if rich is not None:
        start_time = _iso(rich.ts_start)
        end_time = _iso(rich.ts_end)
        input_ = rich.input
        output = rich.output
        if not tool and (rich.tool or rich.step_type):
            name = rich.tool or rich.step_type

    body = _span_body(
        observation_id=observation_id, trace_id=trace_id, name=name,
        start_time=start_time, end_time=end_time, input_=input_, output=output,
        metadata=metadata, level=level, status_message=status_message,
    )
    return _event(_SPAN_CREATE, body, trace_id, index)


def _step_score_events(trace_id: str, observation_id: str,
                       row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """单步的 observation 级分数：``step_score`` + 可测的 ``step_latency_ms`` / ``step_tokens``。"""
    events: list[dict[str, Any]] = []
    index = row.get("index")
    meta = {
        "case_scope": "step",
        "step_index": index,
        "phase": row.get("phase"),
        "tool": row.get("tool"),
    }

    if row.get("score") is not None:
        comment = "; ".join(row.get("checks") or []) or None
        body = _score_body(trace_id=trace_id, name="step_score", value=row["score"],
                           data_type="NUMERIC", observation_id=observation_id,
                           comment=comment, metadata=meta)
        events.append(_event(_SCORE_CREATE, body, trace_id, observation_id, "step_score"))
    if row.get("latency_ms") is not None:
        body = _score_body(trace_id=trace_id, name="step_latency_ms", value=row["latency_ms"],
                           data_type="NUMERIC", observation_id=observation_id, metadata=meta)
        events.append(_event(_SCORE_CREATE, body, trace_id, observation_id, "step_latency_ms"))
    if row.get("tokens") is not None:
        body = _score_body(trace_id=trace_id, name="step_tokens", value=row["tokens"],
                           data_type="NUMERIC", observation_id=observation_id, metadata=meta)
        events.append(_event(_SCORE_CREATE, body, trace_id, observation_id, "step_tokens"))
    return events


# --------------------------------------------------------------------------- #
# 单用例 -> trace + spans + scores
# --------------------------------------------------------------------------- #

def _case_timestamp(steps: Sequence[Mapping[str, Any]],
                    rich_steps: "Sequence[C.TraceStep] | None" = None) -> str | None:
    """取轨迹中最早的 ``ts_start`` 作为 trace 时间戳（无则交给 Langfuse 默认）。

    评测行（``rows``）通常不含时间戳，故同时参考运行包的原始轨迹 ``rich_steps``。
    """
    stamps = [s.get("ts_start") for s in steps if s.get("ts_start") is not None]
    for step in (rich_steps or ()):
        if step.ts_start is not None:
            stamps.append(step.ts_start)
    if not stamps:
        return None
    return _iso(min(stamps))


def case_events(case: Mapping[str, Any], *, run_name: str, session_id: str,
                rich_steps: "Sequence[C.TraceStep] | None" = None,
                case_input: Any = None) -> list[dict[str, Any]]:
    """把一个用例（``CaseResult.to_dict()`` 形状）转换为 Langfuse 事件序列。

    ``rich_steps`` 可选：来自运行包的原始轨迹（保留 ``input`` / ``output`` / 时间戳），
    按 ``index`` 与评测行对齐，用于提高 span 保真度；缺省时仅用评测行生成 span。
    """
    case_id = str(case.get("case_id", "unknown"))
    trace_id = trace_id_for(run_name, case_id)
    rows = list(case.get("steps") or [])
    scores = list(case.get("scores") or [])

    rich_by_index: dict[Any, "C.TraceStep"] = {}
    for step in (rich_steps or ()):
        rich_by_index[step.index] = step

    reward = case.get("reward") or {}
    trace_meta = {
        "case_id": case_id,
        "case_type": case.get("case_type"),
        "passed": case.get("passed"),
        "failed_gates": list(case.get("failed_gates") or []),
        "gates": dict(case.get("gates") or {}),
        "reward": dict(reward),
        "step_summary": dict(case.get("step_summary") or {}),
        "phases": list(case.get("phases") or []),
        "run_name": run_name,
    }
    decision = next((s.get("value") for s in scores if s.get("name") == "decision_match"), None)
    output = {"passed": case.get("passed"), "decision": decision, "total": reward.get("total")}
    tags = ["case", f"type:{case.get('case_type')}",
            "passed" if case.get("passed") else "failed"]

    events: list[dict[str, Any]] = [
        _event(_TRACE_CREATE,
               _trace_body(trace_id=trace_id, name=case_id, session_id=session_id,
                           timestamp=_case_timestamp(rows, rich_steps), input_=case_input,
                           output=output, metadata=trace_meta, tags=tags),
               trace_id)
    ]

    # 步骤 -> span（observation）+ observation 级分数
    obs_by_index: dict[Any, str] = {}
    for row in rows:
        index = row.get("index")
        observation_id = observation_id_for(trace_id, index)
        obs_by_index[index] = observation_id
        events.append(_step_span_event(trace_id, row, rich_by_index.get(index), observation_id))
        events.extend(_step_score_events(trace_id, observation_id, row))

    # 用例分：带 step_index 的挂 observation，其余挂 trace（含 RUN/DATASET_ITEM 与步骤聚合）
    for score in scores:
        meta = score.get("metadata") or {}
        step_index = meta.get("step_index")
        observation_id = obs_by_index.get(step_index) if step_index is not None else None
        body = _score_body(
            trace_id=trace_id, name=str(score.get("name", "")),
            value=score.get("value"), data_type=str(score.get("dataType", "NUMERIC")),
            observation_id=observation_id, comment=score.get("comment"),
            metadata=meta or None,
        )
        events.append(_event(_SCORE_CREATE, body, trace_id, observation_id or "", body["name"]))
    return events


# --------------------------------------------------------------------------- #
# 报告 / 运行包 -> 导出
# --------------------------------------------------------------------------- #

def _default_run_name(report: Mapping[str, Any]) -> str:
    manifest = report.get("manifest") or {}
    generated = manifest.get("generated_at")
    if generated:
        return str(generated)
    return "eval-run"


def export_report(report: Mapping[str, Any], *, run_name: str | None = None,
                  session_id: str | None = None) -> ExportResult:
    """从 ``run_eval.py`` 的报告 dict 导出 Ingestion 事件（用例分 + 步骤分）。"""
    name = run_name or _default_run_name(report)
    session = session_id or name
    events: list[dict[str, Any]] = []
    for case in (report.get("cases") or []):
        events.extend(case_events(case, run_name=name, session_id=session))
    return ExportResult(run_name=name, session_id=session, events=events)


def export_report_file(path: str | os.PathLike[str], *, run_name: str | None = None,
                       session_id: str | None = None) -> ExportResult:
    """读取 ``report.json`` 并导出。"""
    with Path(path).open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    return export_report(report, run_name=run_name, session_id=session_id)


def _rich_steps(bundle: Mapping[str, Any]) -> tuple["C.TraceStep", ...]:
    trajectory = bundle.get("trajectory")
    return C.Trajectory.from_obj(trajectory).steps if trajectory else ()


def export_bundle(bundle: Mapping[str, Any], case: Mapping[str, Any] | None = None,
                  *, run_name: str = "eval-run", session_id: str | None = None,
                  honesty_override: str | None = None) -> ExportResult:
    """从「运行包 + 用例定义」导出（高保真：保留步骤的 input/output/时间戳）。

    内部调用 ``metrics.evaluate_case`` 得到与 ``run_eval.py`` 完全一致的用例分，
    再叠加运行包原始轨迹生成 span。
    """
    case = case or {}
    eval_input = EvalInput.from_raw(
        case,
        bundle.get("report"),
        trajectory=bundle.get("trajectory"),
        retest=bundle.get("retest"),
        artifacts=bundle.get("artifacts") or (),
        restore=bundle.get("restore"),
        cost=bundle.get("cost"),
        honesty_override=honesty_override or bundle.get("honesty_override"),
        line_tolerance=int(bundle.get("line_tolerance", C.DEFAULT_LINE_TOLERANCE)),
    )
    result = evaluate_case(eval_input)
    session = session_id or run_name
    case_input = _case_input(case)
    events = case_events(result.to_dict(), run_name=run_name, session_id=session,
                         rich_steps=_rich_steps(bundle), case_input=case_input)
    return ExportResult(run_name=run_name, session_id=session, events=events)


def _case_input(case: Mapping[str, Any]) -> Any:
    """从用例定义里挑一个适合作为 trace ``input`` 的字段。"""
    if not case:
        return None
    if isinstance(case.get("task"), (Mapping, list, str)):
        return case.get("task")
    return case.get("case_id")


# --------------------------------------------------------------------------- #
# Dataset / Dataset Item / Dataset Run Item（另端点，仅产出请求体）
# --------------------------------------------------------------------------- #

def dataset_item_body(dataset_name: str, item_id: str, *, input_: Any = None,
                      expected_output: Any = None, metadata: Mapping[str, Any] | None = None,
                      source_trace_id: str | None = None,
                      source_observation_id: str | None = None,
                      status: str | None = None) -> dict[str, Any]:
    """``POST /api/public/dataset-items`` 的请求体。"""
    body: dict[str, Any] = {"datasetName": dataset_name, "id": item_id}
    if input_ is not None:
        body["input"] = input_
    if expected_output is not None:
        body["expectedOutput"] = expected_output
    if metadata:
        body["metadata"] = dict(metadata)
    if source_trace_id:
        body["sourceTraceId"] = source_trace_id
    if source_observation_id:
        body["sourceObservationId"] = source_observation_id
    if status:
        body["status"] = status
    return body


def dataset_run_item_body(run_name: str, dataset_item_id: str, *, trace_id: str | None = None,
                          observation_id: str | None = None,
                          run_description: str | None = None,
                          metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """``POST /api/public/dataset-run-items`` 的请求体。"""
    body: dict[str, Any] = {"runName": run_name, "datasetItemId": dataset_item_id}
    if trace_id:
        body["traceId"] = trace_id
    if observation_id:
        body["observationId"] = observation_id
    if run_description:
        body["runDescription"] = run_description
    if metadata:
        body["metadata"] = dict(metadata)
    return body


def dataset_bodies(cases: Iterable[Mapping[str, Any]], dataset_name: str, *,
                   dataset_description: str | None = None,
                   run_name: str | None = None,
                   dataset_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """产出建 Dataset / Dataset Item / Dataset Run Item 的请求体集合。

    Dataset 与 Ingestion 是**不同端点**：本函数只组装请求体，方便使用方按
    ``ENDPOINTS`` 依次调用；返回 ``{"dataset", "items", "run_items"}``。
    """
    dataset: dict[str, Any] = {"name": dataset_name}
    if dataset_description:
        dataset["description"] = dataset_description
    if dataset_metadata:
        dataset["metadata"] = dict(dataset_metadata)

    items: list[dict[str, Any]] = []
    run_items: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id", "unknown"))
        trace_id = trace_id_for(run_name, case_id) if run_name else None
        items.append(dataset_item_body(
            dataset_name, case_id,
            input_=case.get("input") or case.get("task") or {"case_id": case_id},
            metadata={"case_type": case.get("case_type")},
            source_trace_id=trace_id,
        ))
        if run_name:
            run_items.append(dataset_run_item_body(
                run_name, case_id, trace_id=trace_id,
                metadata={"passed": case.get("passed"), "case_type": case.get("case_type")},
            ))
    return {"dataset": dataset, "items": items, "run_items": run_items}


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #

def write_ingestion(result: ExportResult, path: str | os.PathLike[str]) -> Path:
    """把 ``{"batch": [...]}`` 写入文件（UTF-8，缩进 2）。"""
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result.to_ingestion_payload(), ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return target


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _sample_report() -> dict[str, Any]:
    case = {
        "case_id": "case-01-slow-query-fullscan",
        "case_type": "normal",
        "passed": True,
        "gates": {"false_verified": True},
        "failed_gates": [],
        "notes": [],
        "scores": [
            {"name": "root_cause_recall", "value": 1.0, "dataType": "NUMERIC",
             "source": "EVAL", "scope": "DATASET_ITEM", "metadata": {"group": "conclusion"}},
            {"name": "decision_match", "value": "exact", "dataType": "CATEGORICAL",
             "source": "EVAL", "scope": "DATASET_ITEM", "metadata": {"group": "conclusion"}},
            {"name": "false_verified", "value": False, "dataType": "BOOLEAN",
             "source": "EVAL", "scope": "DATASET_ITEM", "metadata": {"group": "conclusion"}},
            {"name": "wall_seconds", "value": 42.0, "dataType": "NUMERIC",
             "source": "EVAL", "scope": "RUN", "metadata": {"group": "cost"}},
            {"name": "step_phase_coverage", "value": 1.0, "dataType": "NUMERIC",
             "source": "EVAL", "scope": "STEP", "metadata": {"group": "step"}},
        ],
        "reward": {"total": 0.95, "reward_profile": "normal_single"},
        "steps": [
            {"index": 0, "phase": "baseline", "tool": "create_task", "status": "ok",
             "latency_ms": 120.0, "tokens": 300, "tool_argument_valid": True,
             "latency_score": 1.0, "tokens_score": 1.0, "retry": False, "score": 1.0,
             "error": "", "checks": []},
            {"index": 1, "phase": "localization", "tool": "evaluate_evidence",
             "status": "error", "latency_ms": None, "tokens": None,
             "tool_argument_valid": True, "latency_score": None, "tokens_score": None,
             "retry": False, "score": 0.0, "error": "boom",
             "checks": ["步骤失败（status=error）"]},
        ],
        "phases": [{"phase": "baseline", "step_count": 1, "error_count": 0,
                    "phase_score": 1.0}],
        "step_summary": {"step_status_ok": False, "step_phase_coverage": 0.2},
        "baseline": {"reproducible": True},
    }
    return {
        "manifest": {"generated_at": "2026-10-02T08:00:00Z", "evaluator_hash": "deadbeef"},
        "global": {"cases_evaluated": 1},
        "cases": [case],
        "aggregate": {},
    }


def _self_check() -> None:
    report = _sample_report()
    result = export_report(report, run_name="2026-10-02")

    # 1) 结构：1 trace + 2 span + 分数
    counts = result.counts()
    assert counts["trace"] == 1, counts
    assert counts["span"] == 2, counts
    # trace 级 5 条 + 步骤 0（score+latency+tokens=3）+ 步骤 1（score=1） = 9
    assert counts["score"] == 9, counts

    events = result.events
    trace_event = next(e for e in events if e["type"] == _TRACE_CREATE)
    assert trace_event["body"]["sessionId"] == "2026-10-02"
    assert trace_event["body"]["name"] == "case-01-slow-query-fullscan"
    assert trace_event["body"]["tags"] == ["case", "type:normal", "passed"]
    assert trace_event["body"]["metadata"]["step_summary"]["step_status_ok"] is False

    # 2) 布尔分数 -> 1/0
    fv = next(e for e in events if e["type"] == _SCORE_CREATE
              and e["body"]["name"] == "false_verified")
    assert fv["body"]["value"] == 0 and fv["body"]["dataType"] == "BOOLEAN"
    assert "observationId" not in fv["body"]

    # 3) 步骤 span：observationId 与步骤分对齐；错误步骤 level=ERROR/statusMessage
    spans = [e["body"] for e in events if e["type"] == _SPAN_CREATE]
    spans.sort(key=lambda b: b["metadata"]["step_index"])
    obs0, obs1 = spans[0]["id"], spans[1]["id"]
    assert spans[0]["metadata"]["step_index"] == 0
    assert spans[1]["level"] == "ERROR" and spans[1]["statusMessage"] == "boom"

    step_score0 = next(e for e in events if e["type"] == _SCORE_CREATE
                       and e["body"]["name"] == "step_score"
                       and e["body"].get("observationId") == obs0)
    assert step_score0["body"]["value"] == 1.0
    assert step_score0["body"]["metadata"]["step_index"] == 0

    # 4) 步骤聚合分（无 step_index）挂 trace，不挂 observation
    phase_cov = next(e for e in events if e["type"] == _SCORE_CREATE
                     and e["body"]["name"] == "step_phase_coverage")
    assert "observationId" not in phase_cov["body"]

    # 5) 确定性：同输入两次导出完全一致
    again = export_report(report, run_name="2026-10-02")
    assert json.dumps(again.to_ingestion_payload(), sort_keys=True) == \
        json.dumps(result.to_ingestion_payload(), sort_keys=True)

    # 6) 高保真：rich_steps 让 span 带上 input/output/时间戳
    rich = (C.TraceStep(index=0, phase="baseline", tool="create_task",
                        input={"task": "排查慢查询"}, output={"ok": True},
                        ts_start=1_600_000_000.0, ts_end=1_600_000_000.5),)
    rich_events = case_events(report["cases"][0], run_name="2026-10-02",
                              session_id="2026-10-02", rich_steps=rich,
                              case_input={"task": "排查慢查询"})
    span0 = next(e["body"] for e in rich_events if e["type"] == _SPAN_CREATE
                 and e["body"]["metadata"]["step_index"] == 0)
    assert span0["input"] == {"task": "排查慢查询"} and span0["output"] == {"ok": True}
    assert span0["startTime"].startswith("2020-09-13") and span0["endTime"].endswith("Z")
    trace_body = next(e["body"] for e in rich_events if e["type"] == _TRACE_CREATE)
    assert trace_body["timestamp"].startswith("2020-09-13")

    # 7) 时间归一化
    assert _iso(1_600_000_000.0) == "2020-09-13T12:26:40Z", _iso(1_600_000_000.0)
    assert _iso(None) is None

    # 8) Dataset / Dataset Run Item 请求体
    bundle = dataset_bodies([report["cases"][0]], "project-doctor-eval",
                            run_name="2026-10-02")
    assert bundle["dataset"]["name"] == "project-doctor-eval"
    assert bundle["items"][0]["datasetName"] == "project-doctor-eval"
    assert bundle["items"][0]["id"] == "case-01-slow-query-fullscan"
    assert bundle["run_items"][0]["runName"] == "2026-10-02"
    assert bundle["run_items"][0]["traceId"] == trace_event["body"]["id"]

    # 9) 落盘往返
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = write_ingestion(result, Path(tmp) / "nested" / "ingestion.json")
        reloaded = json.loads(out.read_text(encoding="utf-8"))
        assert reloaded == result.to_ingestion_payload()

    # 10) 空报告宽容
    empty = export_report({"cases": []})
    assert empty.counts() == {"trace": 0, "span": 0, "score": 0}

    print("[ OK ] langfuse_export.py 自检通过：报告/运行包 -> Ingestion 事件"
          "（用例分挂 trace、步骤分挂 observation、布尔转 1/0、确定性 id、Dataset 请求体）均符合预期")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把评估报告导出为 Langfuse 摄入 JSON（离线）。")
    parser.add_argument("--report", help="run_eval.py 产出的 report.json 路径")
    parser.add_argument("--out", help="输出文件路径（Ingestion 请求体 JSON）")
    parser.add_argument("--run-name", help="运行名（作为 trace 的 session 与 trace id 前缀）")
    parser.add_argument("--session-id", help="会话 id（缺省同 run-name）")
    args = parser.parse_args(argv)

    if not args.report:
        _self_check()
        return 0

    result = export_report_file(args.report, run_name=args.run_name,
                                session_id=args.session_id)
    out = args.out or str(Path(args.report).with_name("langfuse_ingestion.json"))
    write_ingestion(result, out)
    counts = result.counts()
    print(f"[ OK ] 已导出 {counts['trace']} trace / {counts['span']} span / "
          f"{counts['score']} score -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
