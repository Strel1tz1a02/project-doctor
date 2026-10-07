#!/usr/bin/env python3
"""阶段四 · 主观步骤的模型评分脚手架（**离线构建**，零网络 / 零执行）。

定位
----
对应方案 §8「阶段四 · 主观步骤的模型评分」。步骤层里**结构性/一致性/预算**类规则
（见 ``steps.py``）用确定性判定即可；而「假设质量 / 证据落地性 / 报告可读性」这类
**主观步骤**需要引入 **LLM-as-judge**（对齐 Langfuse `LLM` / `EVAL` 来源）。

本模块只做**离线**的三件事，**绝不发起任何网络请求、绝不调用被测系统（SUT）**：

1. **评审请求计划**：把「哪些（用例 × 主观维度）需要评审」组装成一份**有序请求计划**
   （``JudgePlan``），每条请求体是 **OpenAI 兼容的 chat/completions** 报文
   （``messages`` + JSON Schema ``response_format``），落地为可审计 JSON + 回放脚本；
2. **响应解析 / 归一化**：把评审模型返回的 JSON（``{"score": ..., "rationale": ...}``）
   解析并**校验类型 / 范围**（``parse_judge_response``）；
3. **分数映射**：把解析结果映射为 ``scores.Score``（``source=EVAL``、``scope=STEP``、
   ``metadata.group == "step"``），从而与确定性步骤分**同构**地下钻到 Langfuse observation。

硬边界（务必遵守，对应决策 D1–D4 / D7）
--------------------------------------
- **只读 / 零执行**：本模块不导入网络库、不发送请求，也不启动 SUT；真正调用评审模型由
  运维在受控通道按需执行（回放脚本即为载体），与 ``langfuse_deploy.py`` 同一离线哲学；
- **D3 不做逐步骤正解**：评审提示词只喂「可观测字段」（工具/阶段/状态/输入输出摘要），
  **不得携带** ``case.json`` 的 ``expected`` / ``defects`` 等金标准（``_assert_no_golden_leak`` 守卫）；
- **D4 不进硬闸门 / 总分**：评审分与确定性步骤分一致，``metadata.group == "step"``，
  只作归因下钻，不进入 ``group_scores`` / ``total_score``；
- **D7 摘要化**：提示词中 ``input`` / ``output`` 允许摘要化，不内联大对象。

用法
----
    # 离线产出评审请求计划 + 回放脚本（不联网）
    python evaluation/model_judge.py --report evaluation/out/report.json \
        --out evaluation/out/model_judge

    # 无参数时执行自检
    python evaluation/model_judge.py
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# 让「直接运行」与「从别处导入」都能解析同目录 / tools 模块。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_TOOLS = _HERE.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import langfuse_export as X  # noqa: E402  （复用确定性 trace/observation id）
import step_fixtures as F  # noqa: E402  （用步骤 fixture 富化真实运行包）
from langfuse_deploy import FORBIDDEN_GOLDEN_KEYS  # noqa: E402  （金标准字段单一来源）
from scores import DataType, Score, ScoreScope, ScoreSource, make_score  # noqa: E402

__all__ = [
    "DEFAULT_JUDGE_MODEL",
    "DEFAULT_JUDGE_ENDPOINT",
    "JudgeCriterion",
    "SUBJECTIVE_CRITERIA",
    "JudgeRequest",
    "JudgePlan",
    "build_messages",
    "build_judge_plan",
    "parse_judge_response",
    "judge_scores",
    "write_replay_scripts",
]

#: 默认评审模型（占位，可由 CLI / 调用方覆盖）。
DEFAULT_JUDGE_MODEL = "gpt-4o-mini"

#: 默认评审端点（OpenAI 兼容 chat/completions；**非** Langfuse / SUT 端点）。
DEFAULT_JUDGE_ENDPOINT = "/v1/chat/completions"

#: 评审请求（``request_id``）确定性派生的固定命名空间。
_NAMESPACE = uuid.UUID("b7c1e0a2-4d63-4f9a-9e21-8a5c3d6f1b04")

#: 金标准字段名 → 整词匹配模式的缓存（惰性编译，避免重复构造正则）。
_FORBIDDEN_TOKEN_RE_CACHE: dict[tuple[str, ...], "re.Pattern[str]"] = {}

_JUDGE_SYSTEM = (
    "你是一名严谨的 Agent 行为评审员。你只根据给定的单步可观测信息做判断，"
    "不臆测未给出的信息。请严格按要求的 JSON 结构输出，分数落在指定范围内。"
)


# --------------------------------------------------------------------------- #
# 评审维度（主观步骤口径）
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class JudgeCriterion:
    """一个主观评审维度：绑定到某个工具/阶段的步骤上。"""

    key: str
    label: str
    target_tool: str
    phase: str
    data_type: DataType
    question: str
    guidance: str = ""
    scale: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "target_tool": self.target_tool,
            "phase": self.phase,
            "data_type": self.data_type.value,
            "scale": list(self.scale) if self.scale else None,
            "question": self.question,
            "guidance": self.guidance,
        }


#: 默认主观评审维度（与 8 工具闭环对齐：假设 / 证据 / 交付）。
SUBJECTIVE_CRITERIA: tuple[JudgeCriterion, ...] = (
    JudgeCriterion(
        key="hypothesis_quality", label="假设质量",
        target_tool="propose_hypotheses", phase="hypotheses",
        data_type=DataType.NUMERIC, scale=(0.0, 1.0),
        question="该步提出的性能假设是否具体、可证伪、且与已知症状相关？",
        guidance="0=空泛或答非所问；0.5=方向合理但不可证伪；1=具体且可被实验证伪。",
    ),
    JudgeCriterion(
        key="evidence_grounding", label="证据落地性",
        target_tool="evaluate_evidence", phase="localization",
        data_type=DataType.BOOLEAN,
        question="该步对证据的判定是否与被观测数据一致（无凭空断言）？",
        guidance="true=结论有观测支撑；false=存在无证据支撑的断言。",
    ),
    JudgeCriterion(
        key="report_readability", label="报告可读性",
        target_tool="finish_task", phase="verification",
        data_type=DataType.NUMERIC, scale=(0.0, 1.0),
        question="最终交付报告是否结构清晰、结论与证据对应、可供他人复现？",
        guidance="0=无法阅读；0.5=可读但缺关键链路；1=结构化且可复现。",
    ),
)


def judge_request_id_for(run_name: str, case_id: str, criterion_key: str) -> str:
    """一条评审请求的确定性 id（同输入 -> 同 id，重复产出幂等）。"""
    return str(uuid.uuid5(_NAMESPACE, "|".join(("judge", run_name, case_id, criterion_key))))


# --------------------------------------------------------------------------- #
# 提示词与请求体组装
# --------------------------------------------------------------------------- #

def _display(value: Any) -> str:
    """把字段渲染为紧凑文本（缺省 ``None`` -> 空对象）。"""
    if value is None:
        return "{}"
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):  # pragma: no cover - 非 JSON 可序列化对象
        return str(value)


def build_messages(
    criterion: JudgeCriterion,
    *,
    case_id: str,
    step: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """组装评审提示词（system + user）。**只喂可观测字段，不含金标准**（D3）。"""
    lines = [
        f"用例：{case_id}",
        f"评审维度：{criterion.label}（{criterion.key}）",
        f"目标步骤：{criterion.target_tool} / 阶段 {criterion.phase}",
        f"步骤序号：{step.get('index')}；状态：{step.get('status')}；工具：{step.get('tool')}",
        f"步骤输入（可能已摘要）：{_display(step.get('input'))}",
        f"步骤输出（可能已摘要）：{_display(step.get('output'))}",
    ]
    if context:
        lines.append(f"补充上下文：{_display(dict(context))}")
    lines.append(f"评审问题：{criterion.question}")
    if criterion.guidance:
        lines.append(f"评分指引：{criterion.guidance}")
    lines.append('请仅输出 JSON：{"score": <分数>, "rationale": "<简短理由>"}。')
    return [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _response_schema(criterion: JudgeCriterion) -> dict[str, Any]:
    """评审模型应返回的 JSON Schema（绑定分数类型 / 范围）。"""
    if criterion.data_type is DataType.NUMERIC:
        low, high = criterion.scale or (0.0, 1.0)
        score_schema: dict[str, Any] = {"type": "number", "minimum": low, "maximum": high}
    elif criterion.data_type is DataType.BOOLEAN:
        score_schema = {"type": "boolean"}
    else:
        score_schema = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "score": score_schema,
            "rationale": {"type": "string"},
        },
        "required": ["score", "rationale"],
        "additionalProperties": False,
    }


def _build_body(criterion: JudgeCriterion, model: str, messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """OpenAI 兼容 chat/completions 请求体（结构化输出）。"""
    return {
        "model": model,
        "temperature": 0,
        "messages": [dict(m) for m in messages],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": f"judge_{criterion.key}",
                "schema": _response_schema(criterion),
            },
        },
    }


# --------------------------------------------------------------------------- #
# 计划值对象
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class JudgeRequest:
    """一条**离线组装**的评审请求（仅描述，不发送）。"""

    seq: int
    request_id: str
    criterion: str
    case_id: str
    run_id: str
    step_index: int | None
    scope: str
    target: dict[str, Any]
    endpoint: str
    body: dict[str, Any]
    note: str = ""
    method: str = "POST"

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "request_id": self.request_id,
            "criterion": self.criterion,
            "case_id": self.case_id,
            "run_id": self.run_id,
            "step_index": self.step_index,
            "scope": self.scope,
            "target": dict(self.target),
            "method": self.method,
            "endpoint": self.endpoint,
            "note": self.note,
            "body": self.body,
        }


@dataclass
class JudgePlan:
    """一次主观评审的有序请求计划（可落盘为 ``plan.json`` + ``requests/``）。"""

    run_name: str
    session_id: str
    model: str
    endpoint: str
    requests: list[JudgeRequest] = field(default_factory=list)
    generated_at: str | None = None

    def counts(self) -> dict[str, Any]:
        by_criterion: dict[str, int] = {}
        for request in self.requests:
            by_criterion[request.criterion] = by_criterion.get(request.criterion, 0) + 1
        return {"total": len(self.requests), "by_criterion": by_criterion}

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_name": self.run_name,
            "session_id": self.session_id,
            "model": self.model,
            "endpoint": self.endpoint,
            "generated_at": self.generated_at,
            "criteria": [c.to_dict() for c in SUBJECTIVE_CRITERIA],
            "counts": self.counts(),
            "requests": [r.to_dict() for r in self.requests],
        }

    def write(self, out_dir: str | os.PathLike[str], *, emit_replay: bool = True) -> Path:
        """把计划写入 ``out_dir``（只写文本，不联网、不执行）。"""
        target = Path(out_dir)
        requests_dir = target / "requests"
        requests_dir.mkdir(parents=True, exist_ok=True)
        plan_path = target / "plan.json"
        plan_path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                             encoding="utf-8")
        for request in self.requests:
            name = f"{request.seq:02d}-{request.criterion}.json"
            (requests_dir / name).write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8")
        if emit_replay:
            write_replay_scripts(target)
        return plan_path


# --------------------------------------------------------------------------- #
# 计划构建与红线守卫
# --------------------------------------------------------------------------- #

def _default_run_name(report: Mapping[str, Any]) -> str:
    manifest = report.get("manifest") or {}
    generated = manifest.get("generated_at")
    return str(generated) if generated else "judge-run"


def _step_tool(step: Mapping[str, Any]) -> str:
    return str(step.get("tool") or step.get("step_type") or "")


def _opt_index(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def build_judge_plan(
    report: Mapping[str, Any],
    *,
    criteria: Sequence[JudgeCriterion] = SUBJECTIVE_CRITERIA,
    model: str = DEFAULT_JUDGE_MODEL,
    endpoint: str = DEFAULT_JUDGE_ENDPOINT,
    run_name: str | None = None,
    session_id: str | None = None,
    steps_root: str | os.PathLike[str] | None = None,
    enrich_steps: bool = True,
    generated_at: str | None = None,
) -> JudgePlan:
    """从「报告 + 步骤数据」组装主观评审请求计划（离线，零网络）。

    - ``enrich_steps``：是否先用步骤 fixture 富化报告（真实运行包不含 ``steps``）；
    - 对每个用例，按 ``criteria`` 顺序，仅在**命中目标工具**的步骤上生成一条评审请求；
    - 目标 observation 的 ``trace_id`` / ``span_id`` 复用 ``langfuse_export`` 的确定性派生，
      与摄入导出**对齐**（便于把评审分挂到同一 observation）。
    """
    resolved_run = run_name or _default_run_name(report)
    resolved_session = session_id or resolved_run

    rep: Mapping[str, Any] = report
    if enrich_steps:
        rep = F.enrich_report(report, steps_root=steps_root)

    cases = [c for c in (rep.get("cases") or []) if isinstance(c, Mapping)]
    cases.sort(key=lambda c: str(c.get("case_id", "")))

    requests: list[JudgeRequest] = []
    seq = 0
    for case in cases:
        case_id = str(case.get("case_id"))
        trace_id = X.trace_id_for(resolved_run, case_id)
        steps = [s for s in (case.get("steps") or []) if isinstance(s, Mapping)]
        by_tool: dict[str, Mapping[str, Any]] = {}
        for step in steps:
            by_tool.setdefault(_step_tool(step), step)
        for criterion in criteria:
            step = by_tool.get(criterion.target_tool)
            if step is None:
                continue
            index = _opt_index(step.get("index"))
            span_id = X.observation_id_for(trace_id, index)
            seq += 1
            requests.append(JudgeRequest(
                seq=seq,
                request_id=judge_request_id_for(resolved_run, case_id, criterion.key),
                criterion=criterion.key,
                case_id=case_id,
                run_id=resolved_run,
                step_index=index,
                scope=ScoreScope.STEP.value,
                target={"trace_id": trace_id, "span_id": span_id,
                        "tool": criterion.target_tool, "phase": criterion.phase},
                endpoint=endpoint,
                body=_build_body(criterion, model, build_messages(
                    criterion, case_id=case_id, step=step)),
                note=f"主观步骤评审：{criterion.label}（{criterion.target_tool}）",
            ))

    plan = JudgePlan(
        run_name=resolved_run,
        session_id=resolved_session,
        model=model,
        endpoint=endpoint,
        requests=requests,
        generated_at=generated_at or _dt.datetime.now().isoformat(timespec="seconds"),
    )
    _assert_no_golden_leak(plan)
    return plan


def _forbidden_token_pattern(forbidden: frozenset[str]) -> "re.Pattern[str]":
    """金标准字段名的「整词」匹配模式（带缓存，边界含字母/数字/下划线）。"""
    key = tuple(sorted(forbidden))
    pattern = _FORBIDDEN_TOKEN_RE_CACHE.get(key)
    if pattern is None:
        joined = "|".join(re.escape(token) for token in key)
        # 必须用非捕获组把整条候选词括起来：否则 ``|`` 优先级最低，边界断言只会作用在
        # 首个/末个候选词上，中间的 ``expected`` 将失去边界约束而误伤 expected_latency_ms。
        pattern = re.compile(rf"(?<![0-9A-Za-z_])(?:{joined})(?![0-9A-Za-z_])")
        _FORBIDDEN_TOKEN_RE_CACHE[key] = pattern
    return pattern


def _find_forbidden_tokens(obj: Any, forbidden: frozenset[str]) -> list[str]:
    """递归查找金标准痕迹：JSON 键精确匹配 + 字符串值内的整词匹配。

    评审请求体的文案**全部装在** ``messages[].content`` 字符串里，键级匹配无从命中，
    因此对字符串值再做一次「整词」扫描；边界以字母/数字/下划线约束，避免把
    ``expected_latency_ms`` 这类可观测字段误判为金标准 ``expected``。
    """
    pattern = _forbidden_token_pattern(forbidden)
    found: list[str] = []
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if isinstance(key, str):
                found.extend(match.group(0) for match in pattern.finditer(key))
            found.extend(_find_forbidden_tokens(value, forbidden))
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            found.extend(_find_forbidden_tokens(value, forbidden))
    elif isinstance(obj, str):
        found.extend(match.group(0) for match in pattern.finditer(obj))
    return found


def _assert_no_golden_leak(plan: JudgePlan) -> None:
    """拒绝任何携带评测方私有字段的评审请求体 / 目标引用（金标准泄漏红线）。"""
    forbidden = frozenset(FORBIDDEN_GOLDEN_KEYS)
    for request in plan.requests:
        leaked = _find_forbidden_tokens(request.body, forbidden) + \
            _find_forbidden_tokens(request.target, forbidden)
        if leaked:
            raise ValueError(
                f"评审请求疑似泄漏金标准字段 {sorted(set(leaked))}（criterion={request.criterion}）")


# --------------------------------------------------------------------------- #
# 响应解析 / 分数映射
# --------------------------------------------------------------------------- #

def parse_judge_response(criterion: JudgeCriterion, payload: Any) -> Any:
    """把评审模型返回解析为合法分值（类型 / 范围校验；不符抛 ``ValueError``）。

    ``payload`` 可为 ``{"score": ..., "rationale": ...}`` 映射，或裸分值。
    """
    raw = payload.get("score") if isinstance(payload, Mapping) else payload
    if criterion.data_type is DataType.BOOLEAN:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return bool(raw)
        if isinstance(raw, str):
            low = raw.strip().lower()
            if low in ("true", "1", "yes", "是", "通过"):
                return True
            if low in ("false", "0", "no", "否", "不通过"):
                return False
        raise ValueError(f"评审分值无法解析为布尔（criterion={criterion.key}, raw={raw!r}）")
    if criterion.data_type is DataType.NUMERIC:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"评审分值无法解析为数值（criterion={criterion.key}, raw={raw!r}）")
        value = float(raw)
        low, high = criterion.scale or (None, None)
        if low is not None:
            value = max(value, float(low))
        if high is not None:
            value = min(value, float(high))
        return value
    if raw is None:
        raise ValueError(f"评审分值缺失（criterion={criterion.key}）")
    return str(raw)


def judge_scores(
    plan: JudgePlan,
    responses: Mapping[Any, Any],
    *,
    criteria: Sequence[JudgeCriterion] = SUBJECTIVE_CRITERIA,
) -> list[Score]:
    """把评审响应映射为 ``Score``（``source=EVAL`` / ``scope=STEP`` / ``group=step``）。

    ``responses`` 的键可为 ``request_id`` 或 ``seq``；缺失响应的请求被跳过。
    """
    index = {c.key: c for c in criteria}
    out: list[Score] = []
    for request in plan.requests:
        if request.request_id in responses:
            payload = responses[request.request_id]
        elif request.seq in responses:
            payload = responses[request.seq]
        else:
            continue
        criterion = index.get(request.criterion)
        if criterion is None:
            continue
        value = parse_judge_response(criterion, payload)
        rationale = ""
        if isinstance(payload, Mapping):
            rationale = str(payload.get("rationale") or "")
        out.append(make_score(
            f"judge_{criterion.key}", value,
            data_type=criterion.data_type,
            source=ScoreSource.EVAL,
            scope=ScoreScope.STEP,
            comment=rationale or None,
            metadata={
                "group": "step",
                "judge": "llm",
                "criterion": criterion.key,
                "phase": criterion.phase,
                "tool": criterion.target_tool,
                "step_index": request.step_index,
                "case_id": request.case_id,
            },
        ))
    return out


# --------------------------------------------------------------------------- #
# 回放脚本模板（仅生成，不执行）
# --------------------------------------------------------------------------- #

_REPLAY_PS1 = """# 由 evaluation/model_judge.py 生成：按顺序回放主观评审请求。
# 仅生成、不自动执行；运行前请核对 plan.json 与 requests/。
# 需先设置环境变量：JUDGE_BASE_URL / JUDGE_API_KEY（评审模型网关，非 SUT）。
$ErrorActionPreference = "Stop"
$base = $env:JUDGE_BASE_URL
$key  = $env:JUDGE_API_KEY
if (-not $base -or -not $key) { throw "请先设置 JUDGE_BASE_URL / JUDGE_API_KEY" }
$headers = @{ Authorization = "Bearer $key"; "Content-Type" = "application/json" }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$files = Get-ChildItem -Path (Join-Path $here "requests") -Filter *.json | Sort-Object Name
foreach ($f in $files) {
  $req = Get-Content -Raw -Encoding UTF8 $f.FullName | ConvertFrom-Json
  $uri = "$base$($req.endpoint)"
  Write-Host "[$($req.seq)] $($req.method) $uri"
  $json = $req.body | ConvertTo-Json -Depth 100 -Compress
  Invoke-RestMethod -Method $req.method -Uri $uri -Headers $headers -Body $json | Out-Null
}
Write-Host "完成：已按顺序回放 $($files.Count) 条评审请求。"
"""

_REPLAY_SH = """#!/usr/bin/env bash
# 由 evaluation/model_judge.py 生成：按顺序回放主观评审请求。
# 仅生成、不自动执行；运行前请核对 plan.json 与 requests/。
# 需先设置环境变量：JUDGE_BASE_URL / JUDGE_API_KEY（评审模型网关，非 SUT）。
set -euo pipefail
: "${JUDGE_BASE_URL:?请设置 JUDGE_BASE_URL}"
: "${JUDGE_API_KEY:?请设置 JUDGE_API_KEY}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
i=0
for f in $(ls "$here/requests"/*.json | sort); do
  endpoint=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['endpoint'])" "$f")
  seq=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['seq'])" "$f")
  echo "[$seq] POST ${JUDGE_BASE_URL}${endpoint}"
  curl -sS -H "Authorization: Bearer ${JUDGE_API_KEY}" \\
    -H "Content-Type: application/json" \\
    -X POST "${JUDGE_BASE_URL}${endpoint}" \\
    --data-binary @"$f" >/dev/null
  i=$((i+1))
done
echo "完成：已按顺序回放 ${i} 条评审请求。"
"""


def write_replay_scripts(out_dir: str | os.PathLike[str]) -> list[Path]:
    """把回放脚本模板写入 ``out_dir``（只写文本，不执行、不联网）。"""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    ps1 = target / "replay.ps1"
    sh = target / "replay.sh"
    ps1.write_text(_REPLAY_PS1, encoding="utf-8")
    sh.write_text(_REPLAY_SH, encoding="utf-8")
    return [ps1, sh]


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _sample_report() -> dict[str, Any]:
    """构造两个用例：case-01 覆盖全部 3 个主观维度；case-02 缺 ``finish_task``。"""

    def _step(index: int, tool: str, phase: str, **extra: Any) -> dict[str, Any]:
        base = {"index": index, "tool": tool, "phase": phase, "status": "ok",
                "input": {"task": "排查接口变慢"}, "output": {"note": "ok"}}
        base.update(extra)
        return base

    case_full = {
        "case_id": "case-01-slow-query-fullscan",
        "case_type": "normal",
        "passed": True,
        "steps": [
            _step(0, "create_task", "baseline"),
            _step(1, "propose_hypotheses", "hypotheses", output={"hypotheses": ["缺索引"]}),
            _step(2, "evaluate_evidence", "localization", output={"sufficient": True}),
            _step(3, "finish_task", "verification", output={"decision": "verified"}),
        ],
    }
    case_partial = {
        "case_id": "case-02-slow-query-composite",
        "case_type": "normal",
        "passed": True,
        "steps": [
            _step(0, "create_task", "baseline"),
            _step(1, "propose_hypotheses", "hypotheses", status="skipped"),
            _step(2, "evaluate_evidence", "localization", output={"sufficient": False}),
        ],
    }
    return {
        "manifest": {"generated_at": "2026-10-02T08:00:00Z"},
        "cases": [case_full, case_partial],
        "aggregate": {},
    }


def _self_check() -> None:
    report = _sample_report()
    plan = build_judge_plan(report, run_name="run-check", enrich_steps=False,
                            generated_at="2026-10-02T08:00:00Z")

    # 1) 计数：case-01 → 3 个维度；case-02 → 2 个（缺 finish_task）
    counts = plan.counts()
    assert counts["total"] == 5, counts
    assert counts["by_criterion"] == {
        "hypothesis_quality": 2, "evidence_grounding": 2, "report_readability": 1}, counts

    # 2) 全部 POST 到评审端点，且 seq 连续
    assert all(r.method == "POST" for r in plan.requests)
    assert all(r.endpoint == DEFAULT_JUDGE_ENDPOINT for r in plan.requests)
    assert [r.seq for r in plan.requests] == [1, 2, 3, 4, 5]

    # 3) 目标 id 与摄入导出对齐（trace/observation 确定性派生）
    first = plan.requests[0]
    trace_id = X.trace_id_for("run-check", "case-01-slow-query-fullscan")
    assert first.target["trace_id"] == trace_id
    assert first.target["span_id"] == X.observation_id_for(trace_id, 1)

    # 4) 提示词 / 请求体不含金标准，且结构性输出 schema 就位
    blob = json.dumps([r.body for r in plan.requests], ensure_ascii=False)
    assert "expected" not in blob and "defects" not in blob
    rf = first.body["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["schema"]["properties"]["score"]["type"] == "number"

    # 5) 确定性：同输入 + 同 generated_at 完全一致
    again = build_judge_plan(report, run_name="run-check", enrich_steps=False,
                             generated_at="2026-10-02T08:00:00Z")
    assert json.dumps(again.to_dict(), sort_keys=True) == \
        json.dumps(plan.to_dict(), sort_keys=True)

    # 6) 红线：携带金标准字段的评审请求被拒
    leaked = JudgePlan(run_name="r", session_id="r", model="m", endpoint=DEFAULT_JUDGE_ENDPOINT,
                       requests=[JudgeRequest(
                           seq=1, request_id="x", criterion="hypothesis_quality",
                           case_id="c", run_id="r", step_index=0, scope="STEP",
                           target={}, endpoint=DEFAULT_JUDGE_ENDPOINT,
                           body={"messages": [{"role": "user", "content": "expected: verified"}]})])
    try:
        _assert_no_golden_leak(leaked)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("携带金标准字段的评审请求应被 _assert_no_golden_leak 拒绝")

    # 7) 响应解析：数值裁剪 / 布尔宽容 / 非法拒绝
    crit_num = SUBJECTIVE_CRITERIA[0]
    crit_bool = SUBJECTIVE_CRITERIA[1]
    assert parse_judge_response(crit_num, {"score": 0.7, "rationale": "ok"}) == 0.7
    assert parse_judge_response(crit_num, {"score": 2.0}) == 1.0  # 超范围裁剪到上界
    assert parse_judge_response(crit_num, {"score": -1.0}) == 0.0
    assert parse_judge_response(crit_bool, {"score": "true"}) is True
    assert parse_judge_response(crit_bool, {"score": 0}) is False
    for bad in ("abc", None):
        try:
            parse_judge_response(crit_num, {"score": bad})
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"非法数值 {bad!r} 应被拒绝")

    # 8) 分数映射：STEP 作用域 + group=step + source=EVAL，可与确定性步骤分同构下钻
    responses = {r.request_id: {"score": 0.8, "rationale": "清晰"}
                 for r in plan.requests if r.criterion != "evidence_grounding"}
    responses.update({r.request_id: {"score": True, "rationale": "有据"}
                      for r in plan.requests if r.criterion == "evidence_grounding"})
    scores = judge_scores(plan, responses)
    assert len(scores) == 5, len(scores)
    assert all(s.scope is ScoreScope.STEP for s in scores)
    assert all(s.source is ScoreSource.EVAL for s in scores)
    assert all(s.metadata["group"] == "step" and s.metadata["judge"] == "llm" for s in scores)
    # 缺响应时跳过
    assert len(judge_scores(plan, {})) == 0

    # 9) 落盘往返 + 回放脚本
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        plan_path = plan.write(tmp, emit_replay=True)
        assert plan_path.is_file()
        reloaded = json.loads(plan_path.read_text(encoding="utf-8"))
        assert reloaded["counts"]["total"] == 5
        req_files = sorted((Path(tmp) / "requests").glob("*.json"))
        assert len(req_files) == 5
        assert (Path(tmp) / "replay.ps1").is_file() and (Path(tmp) / "replay.sh").is_file()
        assert "JUDGE_BASE_URL" in (Path(tmp) / "replay.ps1").read_text(encoding="utf-8")

    # 10) 空报告宽容
    empty = build_judge_plan({"manifest": {"generated_at": "t"}, "cases": []})
    assert empty.counts()["total"] == 0, empty.counts()

    print("[ OK ] model_judge.py 自检通过：主观步骤评审请求计划（维度×命中步骤）、"
          "提示词不含金标准、确定性 id、响应解析/类型校验、STEP 分数映射、回放脚本与落盘往返均符合预期")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="model_judge",
        description="离线组装主观步骤 LLM-as-judge 评审请求计划（不联网、不调用 SUT）")
    parser.add_argument("--report", help="run_eval.py 产出的 report.json 路径")
    parser.add_argument("--out", default=str(_HERE / "out" / "model_judge"),
                        help="评审请求计划输出目录")
    parser.add_argument("--model", default=DEFAULT_JUDGE_MODEL, help="评审模型名")
    parser.add_argument("--endpoint", default=DEFAULT_JUDGE_ENDPOINT,
                        help="评审端点（OpenAI 兼容 chat/completions）")
    parser.add_argument("--run-name", help="运行名（缺省取报告 generated_at）")
    parser.add_argument("--session-id", help="会话 id（缺省同 run-name）")
    parser.add_argument("--steps-root", default=None,
                        help="步骤 fixture 目录（缺省 evaluation/fixtures/steps）")
    parser.add_argument("--no-enrich-steps", action="store_true",
                        help="不用步骤 fixture 富化报告（报告须自带 steps）")
    parser.add_argument("--no-replay", action="store_true", help="不生成 replay 回放脚本")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.report:
        _self_check()
        return 0

    with Path(args.report).open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    plan = build_judge_plan(
        report, model=args.model, endpoint=args.endpoint,
        run_name=args.run_name, session_id=args.session_id,
        steps_root=args.steps_root, enrich_steps=not args.no_enrich_steps,
    )
    path = plan.write(args.out, emit_replay=not args.no_replay)
    counts = plan.counts()
    print(f"[ OK ] 已生成主观评审计划：共 {counts['total']} 条请求 "
          f"{counts['by_criterion']} -> {path}")
    print(f"       请求体目录：{Path(args.out) / 'requests'}（离线产出，未发送任何请求）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
