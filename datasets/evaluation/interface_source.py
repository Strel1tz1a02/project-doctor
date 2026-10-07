#!/usr/bin/env python3
"""阶段三 · 在线只读接口支撑（**离线计划 + 本地归一化**，零执行 / 零网络）。

定位
----
对应方案 §8「阶段三 · 在线只读接口」。本模块**不发起任何网络请求**，只做两件事：

1. **只读取数计划**：把「需要从执行侧只读拉取哪些数据」组装成一份**有序的 GET 请求
   计划**（``InterfacePlan``），并落地为可审计的 JSON + 回放脚本，交由运维在受控通道
   按需执行（与 ``langfuse_deploy.py`` 同一离线哲学）。
2. **本地加载 / 归一化**：把**已取回**的导出 JSON（任务包 / AGH 执行记录 / Trace
   API 快照）加载并归一化为 ``contract.StepTrace``，供 ``steps.py`` 打分、
   ``langfuse_export.py`` 产出摄入文件。

硬边界（务必遵守，对应决策 D1 / D2）
-------------------------------------
- **只读**：仅允许 ``GET`` / ``HEAD``；任何写方法（POST/PUT/PATCH/DELETE）一律拒绝；
- **不调用 SUT**：本模块不启动被测系统、不触发诊断工具、不产生副作用；
- **不越界**：端点必须落在只读白名单前缀内（``READONLY_PREFIXES``）。

> 端点路径模板为**占位约定**，落地前需与执行侧确认（见方案 §9 决策点 D1）。
> 确认后仅需替换 ``DEFAULT_ENDPOINTS``，其余逻辑不变。

直接运行本文件会执行一段自检：

    python evaluation/interface_source.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# 让「直接运行」与「从别处导入」都能解析同目录模块。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import trace_adapter as A  # noqa: E402  （三来源归一化）
from contract import StepTrace  # noqa: E402

__all__ = [
    "READONLY_METHODS",
    "READONLY_PREFIXES",
    "DEFAULT_ENDPOINTS",
    "ReadOnlyRequest",
    "InterfacePlan",
    "build_plan",
    "assert_read_only",
    "load_json",
    "load_dir",
    "normalize_export",
    "collect",
    "to_fixture",
]

#: 允许的只读 HTTP 方法（白名单，避免任何写操作混入）。
READONLY_METHODS: tuple[str, ...] = ("GET", "HEAD")

#: 只读端点必须命中的路径前缀（白名单）。默认与占位端点一致。
READONLY_PREFIXES: tuple[str, ...] = ("/api/read/",)

#: 端点路径模板（**占位，待与执行侧约定**）。``{case_id}`` / ``{run_id}`` 为占位符。
DEFAULT_ENDPOINTS: dict[str, str] = {
    # 任务包（用例输入、场景清单等只读元数据）
    "task": "/api/read/tasks/{case_id}",
    # AGH 执行记录（逐步工具调用/结果）
    "record": "/api/read/records/{run_id}",
    # Trace API 快照（Langfuse 兼容导出）
    "trace": "/api/read/traces/{run_id}",
}

#: 端点种类 → 归一化来源（供 ``collect`` 选择适配器）。
KIND_SOURCE: dict[str, str] = {
    "task": "interface",
    "record": "interface",
    "trace": "langfuse",
}


# --------------------------------------------------------------------------- #
# 只读请求 / 计划
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ReadOnlyRequest:
    """一条**只读**取数请求（仅描述，不执行）。"""

    seq: int
    kind: str
    endpoint: str
    method: str = "GET"
    params: dict[str, Any] = field(default_factory=dict)
    source: str = "interface"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "method": self.method,
            "endpoint": self.endpoint,
            "params": dict(self.params),
            "source": self.source,
            "note": self.note,
        }


@dataclass
class InterfacePlan:
    """有序只读取数计划（离线产出，不发送）。"""

    base_url: str = ""
    requests: list[ReadOnlyRequest] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {"total": len(self.requests)}
        for req in self.requests:
            out[req.kind] = out.get(req.kind, 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "read_only": True,
            "counts": self.counts(),
            "requests": [r.to_dict() for r in self.requests],
        }

    def write(self, out_dir: str | os.PathLike[str], *, emit_replay: bool = True) -> Path:
        """把计划与逐条请求体写入 ``out_dir``（只写文本，不联网）。"""
        target = Path(out_dir)
        (target / "requests").mkdir(parents=True, exist_ok=True)
        plan_path = target / "interface_plan.json"
        plan_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for req in self.requests:
            name = f"{req.seq:02d}-{req.kind}.json"
            (target / "requests" / name).write_text(
                json.dumps(req.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if emit_replay:
            _write_replay(target)
        return plan_path


# --------------------------------------------------------------------------- #
# 计划组装与只读校验
# --------------------------------------------------------------------------- #

def _resolve_template(template: str, *, case_id: str, run_id: str) -> str:
    return template.replace("{case_id}", case_id).replace("{run_id}", run_id)


def build_plan(
    case_ids: Iterable[str],
    *,
    run_ids: Iterable[str] | None = None,
    endpoints: Mapping[str, str] | None = None,
    base_url: str = "",
    kinds: Sequence[str] = ("task", "record", "trace"),
    include_trace: bool = True,
) -> InterfacePlan:
    """组装只读取数计划（离线，零网络）。

    - 对每个 ``case_id`` 生成 ``task`` 请求；
    - 对每个 ``run_id``（缺省与 ``case_ids`` 一一对应）生成 ``record`` / ``trace`` 请求；
    - 端点来自 ``endpoints``（缺省 ``DEFAULT_ENDPOINTS``），路径模板中的占位符被替换。

    返回前调用 :func:`assert_read_only` 做红线自检（方法/前缀）。
    """
    templates: Mapping[str, str] = endpoints or DEFAULT_ENDPOINTS
    cases = [str(c) for c in case_ids]
    runs = [str(r) for r in run_ids] if run_ids is not None else list(cases)

    requests: list[ReadOnlyRequest] = []
    kind_set = set(kinds)
    for case_id in cases:
        if "task" in kind_set and "task" in templates:
            requests.append(ReadOnlyRequest(
                seq=len(requests) + 1, kind="task",
                endpoint=_resolve_template(templates["task"], case_id=case_id, run_id=case_id),
                params={"case_id": case_id}, source="interface",
                note="只读：任务包（用例输入/场景清单）",
            ))
    for run_id in runs:
        for kind in ("record", "trace"):
            if kind not in kind_set or kind not in templates:
                continue
            if kind == "trace" and not include_trace:
                continue
            requests.append(ReadOnlyRequest(
                seq=len(requests) + 1, kind=kind,
                endpoint=_resolve_template(templates[kind], case_id=run_id, run_id=run_id),
                params={"run_id": run_id}, source=KIND_SOURCE.get(kind, "interface"),
                note=("只读：AGH 执行记录" if kind == "record" else "只读：Trace API 快照"),
            ))
    # 重编 seq，保证唯一且有序。
    requests = [ReadOnlyRequest(**{**r.to_dict(), "seq": i + 1})
                for i, r in enumerate(requests)]
    plan = InterfacePlan(base_url=base_url, requests=requests)
    assert_read_only(plan)
    return plan


def assert_read_only(plan: InterfacePlan) -> None:
    """红线：计划中不得出现写方法或越界端点，否则抛 ``ValueError``。"""
    for req in plan.requests:
        if req.method.upper() not in READONLY_METHODS:
            raise ValueError(
                f"越界：只读接口不允许 {req.method}（{req.endpoint}）；"
                f"仅允许 {READONLY_METHODS}"
            )
        if not str(req.endpoint).startswith(READONLY_PREFIXES):
            raise ValueError(
                f"越界：端点 {req.endpoint!r} 不在只读白名单前缀 {READONLY_PREFIXES} 内"
            )


# --------------------------------------------------------------------------- #
# 本地加载 / 归一化（消费「已取回」的导出 JSON）
# --------------------------------------------------------------------------- #

def load_json(path: str | os.PathLike[str]) -> Any:
    """读取单个导出 JSON（只读）。"""
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_dir(directory: str | os.PathLike[str]) -> dict[str, Any]:
    """读取目录下所有 ``*.json``，以文件名为键（只读，容忍解析失败）。"""
    out: dict[str, Any] = {}
    root = Path(directory)
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.json")):
        try:
            out[path.stem] = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
    return out


def normalize_export(
    obj: Any,
    *,
    source: str | None = None,
    case_id: str = "",
    run_id: str = "",
) -> StepTrace:
    """把一个已取回的导出对象归一化为 ``StepTrace``（自动/显式判别来源）。"""
    return A.normalize(obj, source=source, case_id=case_id, run_id=run_id)


def collect(
    documents: Mapping[str, Any] | Sequence[Any],
    *,
    source: str | None = None,
) -> dict[str, StepTrace]:
    """把一批导出对象归一化为 ``{case_id: StepTrace}``。

    ``documents`` 可为 ``{key: obj}`` 映射（键作 fallback case_id）或对象序列。
    """
    traces: dict[str, StepTrace] = {}
    items: Iterable[tuple[str, Any]]
    if isinstance(documents, Mapping):
        items = ((str(k), v) for k, v in documents.items())
    else:
        items = ((f"doc-{i:03d}", v) for i, v in enumerate(documents))
    for key, doc in items:
        trace = A.normalize(doc, source=source, case_id=key)
        resolved = trace.case_id or key
        if resolved in traces:  # 同名合并：追加步骤并重编 index
            merged = list(traces[resolved].steps) + list(trace.steps)
            trace = StepTrace(
                case_id=resolved, run_id=trace.run_id or traces[resolved].run_id,
                source=trace.source or traces[resolved].source,
                steps=tuple(
                    __import__("dataclasses").replace(s, index=i)
                    for i, s in enumerate(merged)
                ),
            )
        traces[resolved] = trace
    return traces


def to_fixture(trace: StepTrace) -> dict[str, Any]:
    """把 ``StepTrace`` 转回步骤 fixture 形状（兼容 ``fixtures/steps/*.json``）。

    仅承载可确定性观测字段；不含任何正解/金标准（D3：不做逐步骤正解）。
    """
    steps: list[dict[str, Any]] = []
    for step in trace.steps:
        steps.append({
            "index": step.index,
            "phase": step.phase,
            "tool": step.tool,
            "status": step.status,
            "input": step.input,
            "latency_ms": step.latency_ms,
            "cost": {"tokens": step.cost.tokens},
            "output": step.output,
        })
    return {
        "case_id": trace.case_id,
        "run_id": trace.run_id,
        "source": trace.source,
        "steps": steps,
    }


# --------------------------------------------------------------------------- #
# 回放脚本模板（仅 GET，只生成不执行）
# --------------------------------------------------------------------------- #

_REPLAY_PS1 = """# 由 evaluation/interface_source.py 生成：按顺序回放**只读**取数请求（仅 GET）。
# 仅生成、不自动执行；执行前请核对 interface_plan.json 与 requests/，并确认只读授权。
param(
  [Parameter(Mandatory=$true)][string]$HostUrl
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$files = Get-ChildItem -Path (Join-Path $here "requests") -Filter *.json | Sort-Object Name
foreach ($f in $files) {
  $req = Get-Content -Raw -Encoding UTF8 $f.FullName | ConvertFrom-Json
  if ($req.method -notin @("GET","HEAD")) { throw "越界：$($req.method) 非只读方法" }
  $uri = "$HostUrl$($req.endpoint)"
  Write-Host "[$($req.seq)] $($req.method) $uri"
  Invoke-RestMethod -Method $req.method -Uri $uri | Out-Null
}
Write-Host "完成：已按顺序只读取回 $($files.Count) 条请求。"
"""

_REPLAY_SH = """#!/usr/bin/env bash
# 由 evaluation/interface_source.py 生成：按顺序回放**只读**取数请求（仅 GET）。
# 仅生成、不自动执行；执行前请确认只读授权。
set -euo pipefail
: "${INTERFACE_HOST:?请设置 INTERFACE_HOST}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
i=0
for f in $(ls "$here/requests"/*.json | sort); do
  method=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['method'])" "$f")
  endpoint=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['endpoint'])" "$f")
  [ "$method" = "GET" ] || [ "$method" = "HEAD" ] || { echo "越界：$method"; exit 1; }
  echo "[$((i+1))] $method ${INTERFACE_HOST}${endpoint}"
  curl -sS -X "$method" "${INTERFACE_HOST}${endpoint}" >/dev/null
  i=$((i+1))
done
echo "完成：已按顺序只读取回 ${i} 条请求。"
"""


def _write_replay(out_dir: Path) -> None:
    (out_dir / "replay.ps1").write_text(_REPLAY_PS1, encoding="utf-8")
    (out_dir / "replay.sh").write_text(_REPLAY_SH, encoding="utf-8")


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _self_check() -> None:
    import steps as S

    # 1) 计划组装：只读、有序、覆盖 task/record/trace
    plan = build_plan(
        ["case-01-slow-query-fullscan"], run_ids=["run-01"],
        base_url="https://interface.example",
    )
    counts = plan.counts()
    assert counts["total"] == 3 and counts["task"] == 1 \
        and counts["record"] == 1 and counts["trace"] == 1, counts
    assert [r.seq for r in plan.requests] == [1, 2, 3]
    assert all(r.method == "GET" for r in plan.requests)
    assert plan.requests[0].endpoint == "/api/read/tasks/case-01-slow-query-fullscan"

    # 2) 确定性
    assert json.dumps(plan.to_dict(), sort_keys=True) == \
        json.dumps(build_plan(["case-01-slow-query-fullscan"], run_ids=["run-01"],
                              base_url="https://interface.example").to_dict(), sort_keys=True)

    # 3) 红线：写方法 / 越界端点被拒
    bad_method = InterfacePlan(requests=[ReadOnlyRequest(
        seq=1, kind="record", endpoint="/api/read/records/r1", method="POST")])
    try:
        assert_read_only(bad_method)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("写方法应被 assert_read_only 拒绝")
    bad_prefix = InterfacePlan(requests=[ReadOnlyRequest(
        seq=1, kind="record", endpoint="/api/sut/run", method="GET")])
    try:
        assert_read_only(bad_prefix)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("越界端点应被 assert_read_only 拒绝")

    # 4) 本地归一化：AGH 执行记录 / Langfuse 快照 → StepTrace
    record = {
        "task_id": "case-01-slow-query-fullscan",
        "operations": [
            {"tool_name": "create_task", "arguments": {"task": "t"}, "status": "ok"},
            {"tool_name": "discover_scenarios", "arguments": {"task": "t"}, "status": "ok"},
            {"tool_name": "propose_hypotheses", "arguments": {"obs": []}, "status": "failed"},
        ],
    }
    trace = normalize_export(record, source="interface")
    assert trace.source == "interface" and len(trace.steps) == 3
    assert trace.steps[2].status == "error"
    assert trace.steps[0].phase == "baseline"

    # 5) 批量 collect + 与 steps.py 打通
    traces = collect({"case-01-slow-query-fullscan": record})
    assert set(traces) == {"case-01-slow-query-fullscan"}
    result = S.evaluate_trace(traces["case-01-slow-query-fullscan"])
    assert result.has_steps and 0.0 <= result.summary["step_phase_coverage"] <= 1.0

    # 6) to_fixture 往返：形状可被 steps.evaluate_trace 直接评估
    fixture = to_fixture(trace)
    assert fixture["case_id"] == trace.case_id and len(fixture["steps"]) == 3
    round_trip = S.evaluate_trace(fixture)
    assert round_trip.has_steps and len(round_trip.steps) == 3

    # 7) 落盘往返 + 回放脚本
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        plan_path = plan.write(tmp)
        assert plan_path.is_file()
        reloaded = json.loads(plan_path.read_text(encoding="utf-8"))
        assert reloaded["read_only"] is True and reloaded["counts"]["total"] == 3
        assert (Path(tmp) / "replay.ps1").is_file()
        assert (Path(tmp) / "replay.sh").is_file()
        assert "GET" in (Path(tmp) / "replay.ps1").read_text(encoding="utf-8")

    # 8) 空输入宽容
    assert build_plan([]).counts()["total"] == 0

    print("[ OK ] interface_source.py 自检通过：只读取数计划（GET 白名单/越界拒绝/确定性/"
          "落盘往返）+ 本地导出归一化 + 与 steps.py 打通均符合预期")


if __name__ == "__main__":
    _self_check()
