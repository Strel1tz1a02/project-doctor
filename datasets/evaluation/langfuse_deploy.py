#!/usr/bin/env python3
"""Langfuse 部署就绪包（离线优先，纯标准库实现）。

职责（对应决策 D5「我方完成部署」）
----------------------------------
把「一次评估运行」在 Langfuse 上**需要落地的所有写请求**编排成一份**有序请求计划**
（request plan），并在本地**离线**产出：

1. ``plan.json``            —— 有序请求清单（含依赖顺序、计数、说明）；
2. ``requests/NN-*.json``   —— 每一条请求的**请求体**（HTTP method + 端点 + body）；
3. ``replay.ps1`` / ``replay.sh`` —— **可选**的回放脚本模板（读取 ``requests/`` 依次 POST）。

**本模块只组装请求、绝不发起任何网络请求，也不接触被测系统（SUT）。** 真正把请求
POST 到 Langfuse 的动作，由持有凭证的操作者在 Langfuse 实例就绪后自行执行
（回放脚本即为该动作的载体）。

依赖顺序（Langfuse 端点的先后约束）
-----------------------------------
```
1) dataset          POST /api/public/v2/datasets       建 Dataset（按 name 幂等）
2) ingestion        POST /api/public/ingestion         摄入 trace/span/score（建出 trace）
3) dataset_item     POST /api/public/dataset-items     建 Dataset Item（可引用 sourceTraceId）
4) dataset_run_item POST /api/public/dataset-run-items 建 Dataset Run Item（引用 traceId）
```
> 先建 trace 再建 item / run item，是因为两者都可能引用 ``traceId``。

红线（与整体工作边界一致）
--------------------------
- **只读搬运**：本模块不导入任何网络库、不做 IO 之外的副作用；
- **金标准不泄漏**：``_assert_no_golden_leak`` 会拒绝任何携带 ``expected`` / ``defects`` /
  ``root_cause_ids`` 等评测方私有字段的请求体；
- **端点白名单**：所有请求端点必须落在 ``langfuse_export.ENDPOINTS`` 之内。

用法
----
    # 离线产出部署计划 + 回放脚本（不联网）
    python evaluation/langfuse_deploy.py --report evaluation/out/report.json \
        --dataset-name project-doctor-eval --out evaluation/out/langfuse_deploy

    # 无参数时执行自检
    python evaluation/langfuse_deploy.py
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# 让直接运行（python evaluation/langfuse_deploy.py）与从别处导入都能解析同目录 / tools 模块。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_TOOLS = _HERE.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import langfuse_export as X  # noqa: E402
import step_fixtures as F  # noqa: E402  （步骤 fixture 合并，修复真实运行包 0 span）
import validate_cases as V  # noqa: E402

__all__ = [
    "DeployRequest",
    "DeployPlan",
    "ENDPOINTS",
    "DEPLOY_KINDS",
    "DEFAULT_DATASET_NAME",
    "FORBIDDEN_GOLDEN_KEYS",
    "load_cases",
    "build_plan",
    "dry_run",
    "write_replay_scripts",
    "main",
]

#: 相关 Langfuse 端点（与 ``langfuse_export.ENDPOINTS`` 同源，本模块只产出请求体）。
ENDPOINTS: dict[str, str] = dict(X.ENDPOINTS)

#: 部署请求的种类，元组顺序即**依赖顺序**。
DEPLOY_KINDS: tuple[str, ...] = ("dataset", "ingestion", "dataset_item", "dataset_run_item")

#: 缺省数据集名。
DEFAULT_DATASET_NAME = "project-doctor-eval"

#: 评测方私有（金标准）字段名：任何部署请求体都不得携带（防泄漏红线）。
FORBIDDEN_GOLDEN_KEYS: tuple[str, ...] = (
    "expected",
    "defects",
    "root_cause_ids",
    "ground_truth",
    "expected_steps",
)

_HTTP_METHOD = "POST"


# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #

def load_cases(cases_root: str | os.PathLike[str]) -> dict[str, dict[str, Any]]:
    """扫描 ``<cases_root>/*/case.json``，返回 ``{case_id: case}``（跳过保留目录）。

    与 ``run_eval._iter_case_files`` / ``tools/validate_cases.py`` 同口径，避免把
    ``docs`` / ``tools`` / ``evaluation`` / ``_template`` 等目录误当作数据单元。
    """
    root = Path(cases_root)
    out: dict[str, dict[str, Any]] = {}
    for case_path in sorted(root.glob("*/case.json")):
        if V.is_reserved_name(case_path.parent.name):
            continue
        with case_path.open("r", encoding="utf-8") as handle:
            case = json.load(handle)
        out[str(case.get("case_id", case_path.parent.name))] = case
    return out


def _normalize_cases(cases: Any) -> list[dict[str, Any]]:
    """把 cases 入参（mapping / iterable / None）归一成按 ``case_id`` 排序的列表。"""
    if cases is None:
        return []
    if isinstance(cases, Mapping):
        items = list(cases.values())
    else:
        items = list(cases)
    return sorted(items, key=lambda c: str(c.get("case_id", "")))


def _item_input(case: Mapping[str, Any]) -> Any:
    """给 Dataset Item 挑一个合适的 ``input``（优先真实任务文本，退化为摘要）。"""
    if case.get("task") is not None:
        return case.get("task")
    if case.get("input") is not None:
        return case.get("input")
    symptom = case.get("symptom") or {}
    summary = symptom.get("summary") if isinstance(symptom, Mapping) else None
    return {
        "case_id": case.get("case_id"),
        "title": case.get("title"),
        "symptom": summary,
    }


def _shape_for_dataset(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把 case dict 塑形为 ``dataset_bodies`` 期望的输入（补上可控的 ``input``）。"""
    shaped: list[dict[str, Any]] = []
    for case in cases:
        shaped.append({
            "case_id": case.get("case_id"),
            "case_type": case.get("case_type"),
            "passed": case.get("passed"),
            "input": _item_input(case),
        })
    return shaped


def _default_run_name(report: Mapping[str, Any]) -> str:
    manifest = report.get("manifest") or {}
    generated = manifest.get("generated_at")
    return str(generated) if generated else "eval-run"


# --------------------------------------------------------------------------- #
# 计划值对象
# --------------------------------------------------------------------------- #

@dataclass
class DeployRequest:
    """一条部署写请求：方法 + 端点 + 请求体（离线组装，不发送）。"""

    seq: int
    kind: str
    endpoint: str
    body: dict[str, Any]
    note: str = ""
    method: str = _HTTP_METHOD

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "method": self.method,
            "endpoint": self.endpoint,
            "note": self.note,
            "body": self.body,
        }


@dataclass
class DeployPlan:
    """一次 Langfuse 部署的有序请求计划（可落盘为 plan.json + requests/）。"""

    run_name: str
    session_id: str
    dataset_name: str
    requests: list[DeployRequest] = field(default_factory=list)
    generated_at: str | None = None

    # -- 统计 -------------------------------------------------------------- #

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {kind: 0 for kind in DEPLOY_KINDS}
        for request in self.requests:
            counts[request.kind] = counts.get(request.kind, 0) + 1
        counts["total"] = len(self.requests)
        return counts

    def kinds_in_order(self) -> list[str]:
        """按出现顺序去重后的种类序列（用于校验依赖顺序）。"""
        seen: list[str] = []
        for request in self.requests:
            if request.kind not in seen:
                seen.append(request.kind)
        return seen

    # -- 序列化 ------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_name": self.run_name,
            "session_id": self.session_id,
            "dataset_name": self.dataset_name,
            "generated_at": self.generated_at,
            "dependency_order": list(DEPLOY_KINDS),
            "endpoints": dict(ENDPOINTS),
            "counts": self.counts(),
            "requests": [request.to_dict() for request in self.requests],
        }

    # -- 落盘 -------------------------------------------------------------- #

    def write(self, out_dir: str | os.PathLike[str], *,
              emit_replay: bool = True) -> Path:
        """把计划写入 ``out_dir``：``plan.json`` + ``requests/NN-<kind>.json``。

        ``emit_replay=True`` 时另写 ``replay.ps1`` / ``replay.sh`` 回放脚本模板
        （**模板本身不执行**，由操作者在 Langfuse 就绪后运行）。
        """
        target = Path(out_dir)
        requests_dir = target / "requests"
        requests_dir.mkdir(parents=True, exist_ok=True)

        plan_path = target / "plan.json"
        plan_path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                             encoding="utf-8")

        for request in self.requests:
            name = f"{request.seq:02d}-{request.kind}.json"
            (requests_dir / name).write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8")

        if emit_replay:
            write_replay_scripts(target)
        return plan_path


# --------------------------------------------------------------------------- #
# 计划构建
# --------------------------------------------------------------------------- #

def build_plan(report: Mapping[str, Any], cases: Any = None, *,
               dataset_name: str = DEFAULT_DATASET_NAME,
               dataset_description: str | None = None,
               run_name: str | None = None,
               session_id: str | None = None,
               generated_at: str | None = None,
               steps_root: str | os.PathLike[str] | None = None,
               enrich_steps: bool = True) -> DeployPlan:
    """从「评估报告 + 用例集合」组装 Langfuse 部署请求计划（离线，零网络）。

    - ``report``：``run_eval.py`` 产出的报告 dict；
    - ``cases``：用例集合（``load_cases()`` 的 mapping，或任意 case dict 序列）；
      缺省时退化为报告内 ``cases``（此时 Dataset Item 的 input 仅含 ``case_id``）；
    - ``enrich_steps``：是否用**步骤 fixture** 富化报告（默认 ``True``）。真实运行包
      不含 ``steps``，直接导出会产出 **0 个 observation span**；富化后为每个用例补回
      逐步明细与 7 项步骤分（``group == "step"``），使 ``span`` 正常产出。此过程只读、
      离线，且**不改动** ``passed`` / ``gates`` / ``reward``（D4）；
    - ``steps_root``：步骤 fixture 目录，缺省 ``evaluation/fixtures/steps``。
    """
    resolved_run = run_name or _default_run_name(report)
    resolved_session = session_id or resolved_run

    case_list = _normalize_cases(cases)
    if not case_list:
        case_list = _normalize_cases(report.get("cases") or [])
    shaped = _shape_for_dataset(case_list)

    dataset_bundle = X.dataset_bodies(
        shaped, dataset_name,
        dataset_description=dataset_description,
        run_name=resolved_run,
        dataset_metadata={"source": "project-doctor/datasets",
                          "case_count": len(shaped)},
    )
    report_for_export: Mapping[str, Any] = report
    if enrich_steps:
        report_for_export = F.enrich_report(report, steps_root=steps_root)
    export = X.export_report(report_for_export, run_name=resolved_run,
                             session_id=resolved_session)

    requests: list[DeployRequest] = []
    seq = 0

    def _add(kind: str, body: Mapping[str, Any], note: str) -> None:
        nonlocal seq
        seq += 1
        requests.append(DeployRequest(seq=seq, kind=kind,
                                      endpoint=ENDPOINTS[kind],
                                      body=dict(body), note=note))

    if shaped:
        _add("dataset", dataset_bundle["dataset"],
             f"建 Dataset（{len(shaped)} 个用例，按 name 幂等）")
    if export.events:
        counts = export.counts()
        _add("ingestion", export.to_ingestion_payload(),
             f"摄入 {counts['trace']} trace / {counts['span']} span / {counts['score']} score")
    for item in dataset_bundle["items"]:
        _add("dataset_item", item, f"建 Dataset Item：{item.get('id')}")
    for run_item in dataset_bundle["run_items"]:
        _add("dataset_run_item", run_item,
             f"建 Dataset Run Item：{run_item.get('datasetItemId')}")

    plan = DeployPlan(
        run_name=resolved_run,
        session_id=resolved_session,
        dataset_name=dataset_name,
        requests=requests,
        generated_at=generated_at or _dt.datetime.now().isoformat(timespec="seconds"),
    )
    _assert_endpoints(plan)
    _assert_kind_order(plan)
    _assert_no_golden_leak(plan)
    return plan


# --------------------------------------------------------------------------- #
# 结构断言（离线自检 / 红线守卫）
# --------------------------------------------------------------------------- #

def _assert_endpoints(plan: DeployPlan) -> None:
    """所有请求端点必须落在 Langfuse 白名单内（拒绝任何越界目标）。"""
    allowed = set(ENDPOINTS.values())
    for request in plan.requests:
        if request.endpoint not in allowed:
            raise ValueError(f"越界端点：{request.endpoint}（kind={request.kind}）")


def _assert_kind_order(plan: DeployPlan) -> None:
    """种类出现顺序必须符合依赖顺序 dataset → ingestion → item → run_item。"""
    seen = plan.kinds_in_order()
    expected = [k for k in DEPLOY_KINDS if k in seen]
    if seen != expected:
        raise ValueError(f"部署请求顺序不符依赖约束：{seen} != {expected}")


def _find_forbidden_keys(obj: Any, forbidden: frozenset[str]) -> list[str]:
    """递归查找对象中出现的金标准字段名（JSON 键级精确匹配）。"""
    found: list[str] = []
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if isinstance(key, str) and key in forbidden:
                found.append(key)
            found.extend(_find_forbidden_keys(value, forbidden))
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            found.extend(_find_forbidden_keys(value, forbidden))
    return found


def _assert_no_golden_leak(plan: DeployPlan) -> None:
    """拒绝任何携带评测方私有字段的请求体（金标准泄漏红线）。"""
    forbidden = frozenset(FORBIDDEN_GOLDEN_KEYS)
    for request in plan.requests:
        leaked = _find_forbidden_keys(request.body, forbidden)
        if leaked:
            raise ValueError(
                f"部署请求体疑似泄漏金标准字段 {sorted(set(leaked))}（kind={request.kind}）")


# --------------------------------------------------------------------------- #
# 回放脚本模板（仅生成文本，不执行）
# --------------------------------------------------------------------------- #

_REPLAY_PS1 = """# 由 evaluation/langfuse_deploy.py 生成：按依赖顺序回放 Langfuse 部署请求。
# 仅生成、不自动执行；运行前请核对 plan.json 与 requests/。
# 需先设置环境变量：LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY。
$ErrorActionPreference = "Stop"
$hostUrl = $env:LANGFUSE_HOST
$public  = $env:LANGFUSE_PUBLIC_KEY
$secret  = $env:LANGFUSE_SECRET_KEY
if (-not $hostUrl -or -not $public -or -not $secret) {
  throw "请先设置 LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY"
}
$pair = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$public`:$secret"))
$headers = @{ Authorization = "Basic $pair"; "Content-Type" = "application/json" }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$files = Get-ChildItem -Path (Join-Path $here "requests") -Filter *.json | Sort-Object Name
foreach ($f in $files) {
  $req = Get-Content -Raw -Encoding UTF8 $f.FullName | ConvertFrom-Json
  $uri = "$hostUrl$($req.endpoint)"
  Write-Host "[$($req.seq)] $($req.method) $uri"
  $json = $req.body | ConvertTo-Json -Depth 100 -Compress
  Invoke-RestMethod -Method $req.method -Uri $uri -Headers $headers -Body $json | Out-Null
}
Write-Host "完成：已按顺序回放 $($files.Count) 条请求。"
"""

_REPLAY_SH = """#!/usr/bin/env bash
# 由 evaluation/langfuse_deploy.py 生成：按依赖顺序回放 Langfuse 部署请求。
# 仅生成、不自动执行；运行前请核对 plan.json 与 requests/。
# 需先设置环境变量：LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY。
set -euo pipefail
: "${LANGFUSE_HOST:?请设置 LANGFUSE_HOST}"
: "${LANGFUSE_PUBLIC_KEY:?请设置 LANGFUSE_PUBLIC_KEY}"
: "${LANGFUSE_SECRET_KEY:?请设置 LANGFUSE_SECRET_KEY}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
i=0
for f in $(ls "$here/requests"/*.json | sort); do
  endpoint=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['endpoint'])" "$f")
  seq=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['seq'])" "$f")
  echo "[$seq] POST ${LANGFUSE_HOST}${endpoint}"
  curl -sS -u "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" \\
    -H "Content-Type: application/json" \\
    -X POST "${LANGFUSE_HOST}${endpoint}" \\
    --data-binary @"$f" >/dev/null
  i=$((i+1))
done
echo "完成：已按顺序回放 ${i} 条请求。"
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
# 便捷入口：从报告文件一键 dry-run
# --------------------------------------------------------------------------- #

def dry_run(report_path: str | os.PathLike[str], out_dir: str | os.PathLike[str], *,
            cases_root: str | os.PathLike[str] | None = None,
            dataset_name: str = DEFAULT_DATASET_NAME,
            dataset_description: str | None = None,
            run_name: str | None = None,
            session_id: str | None = None,
            steps_root: str | os.PathLike[str] | None = None,
            enrich_steps: bool = True,
            emit_replay: bool = True) -> tuple[DeployPlan, Path]:
    """读取 ``report.json``（+ 可选用例目录），离线产出完整部署计划目录。

    ``steps_root`` / ``enrich_steps`` 透传给 :func:`build_plan`：默认用步骤 fixture
    富化报告，修复真实运行包 **0 span** 问题（只读、离线，不改动 D4 字段）。
    """
    with Path(report_path).open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    cases = load_cases(cases_root) if cases_root else None
    plan = build_plan(report, cases, dataset_name=dataset_name,
                      dataset_description=dataset_description,
                      run_name=run_name, session_id=session_id,
                      steps_root=steps_root, enrich_steps=enrich_steps)
    path = plan.write(out_dir, emit_replay=emit_replay)
    return plan, path


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _sample_report() -> dict[str, Any]:
    def _case(case_id: str, case_type: str, passed: bool) -> dict[str, Any]:
        return {
            "case_id": case_id,
            "case_type": case_type,
            "passed": passed,
            "gates": {"false_verified": True},
            "failed_gates": [],
            "scores": [
                {"name": "decision_match", "value": "exact", "dataType": "CATEGORICAL",
                 "source": "EVAL", "scope": "DATASET_ITEM", "metadata": {"group": "conclusion"}},
                {"name": "false_verified", "value": False, "dataType": "BOOLEAN",
                 "source": "EVAL", "scope": "DATASET_ITEM", "metadata": {"group": "conclusion"}},
                {"name": "step_phase_coverage", "value": 1.0, "dataType": "NUMERIC",
                 "source": "EVAL", "scope": "STEP", "metadata": {"group": "step"}},
            ],
            "reward": {"total": 0.9, "reward_profile": "normal_single"},
            "steps": [
                {"index": 0, "phase": "baseline", "tool": "create_task", "status": "ok",
                 "latency_ms": 120.0, "tokens": 300, "tool_argument_valid": True,
                 "retry": False, "score": 1.0, "error": "", "checks": []},
            ],
            "phases": [{"phase": "baseline", "step_count": 1, "error_count": 0, "phase_score": 1.0}],
            "step_summary": {"step_status_ok": True, "step_phase_coverage": 1.0},
            "baseline": {"reproducible": True},
        }

    return {
        "manifest": {"generated_at": "2026-10-02T08:00:00Z", "evaluator_hash": "deadbeef"},
        "global": {"cases_evaluated": 2},
        "cases": [_case("case-01-slow-query-fullscan", "normal", True),
                  _case("case-09-connection-pool-leak", "boundary", True)],
        "aggregate": {},
    }


def _self_check() -> None:
    report = _sample_report()
    cases = {
        "case-01-slow-query-fullscan": {"case_id": "case-01-slow-query-fullscan",
                                        "case_type": "normal", "title": "全表扫描",
                                        "symptom": {"summary": "列表接口变慢"}},
        "case-09-connection-pool-leak": {"case_id": "case-09-connection-pool-leak",
                                         "case_type": "boundary", "title": "连接池泄漏",
                                         "symptom": {"summary": "连接耗尽"}},
    }

    plan = build_plan(report, cases, dataset_name="project-doctor-eval",
                      generated_at="2026-10-02T08:00:00Z")

    # 1) 结构：2 dataset_item + 2 dataset_run_item + 1 dataset + 1 ingestion
    counts = plan.counts()
    assert counts["dataset"] == 1, counts
    assert counts["ingestion"] == 1, counts
    assert counts["dataset_item"] == 2, counts
    assert counts["dataset_run_item"] == 2, counts
    assert counts["total"] == 6, counts

    # 2) 依赖顺序
    assert plan.kinds_in_order() == ["dataset", "ingestion", "dataset_item", "dataset_run_item"], \
        plan.kinds_in_order()

    # 3) 端点白名单 + method 一致
    allowed = set(ENDPOINTS.values())
    assert all(r.endpoint in allowed for r in plan.requests)
    assert all(r.method == "POST" for r in plan.requests)

    # 4) dataset item 的 input 来自用例标题/症状，且不含金标准
    item = next(r for r in plan.requests if r.kind == "dataset_item")
    assert item.body["datasetName"] == "project-doctor-eval"
    assert item.body["input"]["case_id"] == "case-01-slow-query-fullscan"
    assert "expected" not in json.dumps(item.body, ensure_ascii=False)

    # 5) run item 与 trace id 对齐
    ingestion = next(r for r in plan.requests if r.kind == "ingestion")
    trace_events = [e for e in ingestion.body["batch"] if e["type"] == "trace-create"]
    assert len(trace_events) == 2
    run_trace_ids = {r.body.get("traceId") for r in plan.requests
                     if r.kind == "dataset_run_item"}
    assert run_trace_ids == {e["body"]["id"] for e in trace_events}, run_trace_ids

    # 6) 确定性：同输入 + 同 generated_at -> 完全一致
    again = build_plan(report, cases, dataset_name="project-doctor-eval",
                       generated_at="2026-10-02T08:00:00Z")
    assert json.dumps(again.to_dict(), sort_keys=True) == \
        json.dumps(plan.to_dict(), sort_keys=True)

    # 7) 落盘往返 + 回放脚本生成
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        plan_path = plan.write(tmp, emit_replay=True)
        assert plan_path.is_file()
        reloaded = json.loads(plan_path.read_text(encoding="utf-8"))
        assert reloaded["counts"]["total"] == 6
        req_files = sorted((Path(tmp) / "requests").glob("*.json"))
        assert len(req_files) == 6
        assert (Path(tmp) / "replay.ps1").is_file()
        assert (Path(tmp) / "replay.sh").is_file()
        assert "LANGFUSE_HOST" in (Path(tmp) / "replay.ps1").read_text(encoding="utf-8")

    # 8) 红线：携带金标准字段的请求被拒
    leaked = DeployPlan(run_name="r", session_id="r", dataset_name="d",
                        requests=[DeployRequest(seq=1, kind="dataset_item",
                                                endpoint=ENDPOINTS["dataset_item"],
                                                body={"expected": {"decision": "verified"}})])
    try:
        _assert_no_golden_leak(leaked)
    except ValueError:
        pass
    else:  # pragma: no cover - 理论上不可达
        raise AssertionError("携带金标准字段的请求体应被 _assert_no_golden_leak 拒绝")

    # 9) 越界端点被拒
    bad = DeployPlan(run_name="r", session_id="r", dataset_name="d",
                     requests=[DeployRequest(seq=1, kind="dataset",
                                             endpoint="/api/public/sut/run", body={})])
    try:
        _assert_endpoints(bad)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("越界端点应被 _assert_endpoints 拒绝")

    # 10) 空报告宽容
    empty = build_plan({"manifest": {"generated_at": "t"}, "cases": []})
    assert empty.counts()["total"] == 0, empty.counts()

    print("[ OK ] langfuse_deploy.py 自检通过：有序部署请求计划（dataset→ingestion→item→run_item）、"
          "端点白名单、金标准不泄漏、确定性、回放脚本与落盘往返均符合预期")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="langfuse_deploy",
        description="离线组装 Langfuse 部署请求计划（不联网、不调用 SUT）")
    parser.add_argument("--report", help="run_eval.py 产出的 report.json 路径")
    parser.add_argument("--cases-root", default=str(_HERE.parent),
                        help="数据集根目录（用于读取 case.json 作为 Dataset Item 输入）")
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME, help="Langfuse 数据集名")
    parser.add_argument("--dataset-description", help="数据集描述")
    parser.add_argument("--run-name", help="Dataset Run 名（缺省取报告 generated_at）")
    parser.add_argument("--session-id", help="会话 id（缺省同 run-name）")
    parser.add_argument("--steps-root", default=None,
                        help="步骤 fixture 目录（缺省 evaluation/fixtures/steps）")
    parser.add_argument("--no-enrich-steps", action="store_true",
                        help="不用步骤 fixture 富化报告（将使真实运行包产出 0 span）")
    parser.add_argument("--out", default=str(_HERE / "out" / "langfuse_deploy"),
                        help="部署计划输出目录")
    parser.add_argument("--no-replay", action="store_true", help="不生成 replay 回放脚本")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.report:
        _self_check()
        return 0

    plan, path = dry_run(
        args.report, args.out,
        cases_root=args.cases_root,
        dataset_name=args.dataset_name,
        dataset_description=args.dataset_description,
        run_name=args.run_name,
        session_id=args.session_id,
        steps_root=args.steps_root,
        enrich_steps=not args.no_enrich_steps,
        emit_replay=not args.no_replay,
    )
    counts = plan.counts()
    print(f"[ OK ] 已生成部署计划：dataset×{counts['dataset']}、"
          f"ingestion×{counts['ingestion']}、dataset_item×{counts['dataset_item']}、"
          f"dataset_run_item×{counts['dataset_run_item']} -> {path}")
    print(f"       请求体目录：{Path(args.out) / 'requests'}（离线产出，未发送任何请求）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
