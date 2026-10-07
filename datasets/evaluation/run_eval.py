#!/usr/bin/env python3
"""打分流程编排器：一次实验运行（experiment run）的七步流程（纯标准库实现）。

对应《Agent 评估方法》「打分流程」：

    1 冻结评测器   计算评测器/验证器/阈值的 SHA-256 并记录（Agent 无权修改）
    2 装载与校验   扫描全部 ``*/case.json``，用 ``tools/validate_cases.py`` 校验结构
    3 建立基线     汇总每个用例的环境基线（≥3 次重复测量 → 中位数与相对离散度）
    4 交付给 Agent 从「运行包」载入 Agent 采样的 ReportData / 轨迹 / 成本
    5 自动评测     ``metrics.evaluate_case()`` 计算四层指标与硬闸门
    6 独立复测     读取运行包中评测方独立复测的 retest / restore 结果
    7 汇总        ``aggregate()`` 分维度聚合 + 全局门槛（误验证率必须为 0）

运行包格式（``<runs>/<case_id>.json``）::

    {
      "baseline": {"repeats_ms": [12.1, 11.8, 12.4], "environment_fingerprint": {...}},
      "report":     { ... ReportData ... },
      "trajectory": { ... },
      "retest":     {"performed": true, "improvement_percent": 82.0,
                     "business_assertions_passed": true},
      "artifacts":  [{"ref": "artifact://...", "sha256_verified": true, "readable": true}],
      "restore":    {"rolled_back": true, "verified": true},
      "cost":       {"wall_seconds": 42.0, "tool_calls": 17, "artifact_bytes": 2048}
    }

用法
----
    python evaluation/run_eval.py --runs runs/sample-2026-10-02 --out evaluation/out
    python evaluation/run_eval.py --runs evaluation/fixtures/run-bundle --only-bundled
    python evaluation/run_eval.py            # 自检（内置样例，不落盘）

``--only-bundled`` 用于**金标准回归**：数据集会持续扩充，而冻结的运行包 fixture
是固定的，二者必须解耦。开启后只评估存在运行包的用例，缺包用例计入
``cases_skipped_no_bundle`` 而非 ``cases_missing_bundle``，因此新增用例无需同步
提供运行包即可保持回归为绿。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

# 让直接运行与从别处导入都能解析同目录 / tools 目录的模块。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_TOOLS = _HERE.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import contract as C  # noqa: E402
from metrics import EvalInput, CaseResult, evaluate_case  # noqa: E402
from scores import CaseType, COST_BUDGETS, COST_METRICS  # noqa: E402
import validate_cases as V  # noqa: E402

__all__ = [
    "freeze_manifest",
    "baseline_stats",
    "acceptance_reproducible",
    "cost_budgets_block",
    "aggregate",
    "run",
    "render_markdown",
    "ACCEPTANCE_DISPERSION_THRESHOLD",
    "RETEST_DISPERSION_THRESHOLD",
    "BASELINE_MIN_SAMPLES",
]

#: 参与冻结的评测器 / 验证器 / 结构定义（相对数据集根）。
FROZEN_RELATIVE: tuple[str, ...] = (
    "evaluation/contract.py",
    "evaluation/scores.py",
    "evaluation/metrics.py",
    "evaluation/steps.py",
    "evaluation/trace_adapter.py",
    "evaluation/langfuse_export.py",
    "evaluation/run_eval.py",
    "evaluation/test_metrics.py",
    "evaluation/test_steps.py",
    "evaluation/test_run_eval.py",
    "evaluation/test_golden_bundle.py",
    "tools/validate_cases.py",
    "_schema/case.schema.json",
)

# 基线复现性涉及两个口径，含义不同、不得混用（命名为两个常量各自表达意图）：
#
# 「验收口径」= 用例入库时的硬性要求。同一负载下重复测量的相对离散度
# (max-min)/median 必须 ≤ 25%，与 Agent 侧 ``MeasurementPolicy`` 对齐。
# 不满足的用例不予收录（见《数据集结构规范》验收要求）。
ACCEPTANCE_DISPERSION_THRESHOLD = 0.25

# 「运行 / 复测口径」= 某次评估运行当场采集到的基线，其相对离散度必须 ≤ 10%
# 才认为本次测量可复现、结论可信。它比验收口径更严（10% < 25%），
# 因为单次运行的采样噪声直接决定判定的可靠性。
RETEST_DISPERSION_THRESHOLD = 0.10

#: 基线最少重复次数（《Agent 评估方法》第三步要求 ≥3 次）。
BASELINE_MIN_SAMPLES = 3


# --------------------------------------------------------------------------- #
# 第一步：冻结
# --------------------------------------------------------------------------- #

def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze_manifest(root: Path) -> dict[str, Any]:
    """计算评测器组合哈希；Agent 在运行期间无权读取或修改这些文件。"""
    files: dict[str, str | None] = {}
    for rel in FROZEN_RELATIVE:
        files[rel] = sha256_file(root / rel)
    combined = hashlib.sha256()
    for rel in sorted(files):
        combined.update(f"{rel}:{files[rel] or 'MISSING'}\n".encode("utf-8"))
    return {"files": files, "evaluator_hash": combined.hexdigest()}


# --------------------------------------------------------------------------- #
# 第三步：基线
# --------------------------------------------------------------------------- #

def baseline_stats(repeats: Iterable[float],
                   threshold: float = RETEST_DISPERSION_THRESHOLD) -> dict[str, Any]:
    """汇总一次基线的重复测量：中位数、相对离散度、是否可复现。

    默认采用**运行 / 复测口径**（10%）判定 ``reproducible``；用例收录时改用
    ``acceptance_reproducible``（验收口径 25%）。
    """
    vals = [float(x) for x in repeats]
    n = len(vals)
    if n == 0:
        return {"samples": 0, "median_ms": None, "relative_dispersion": None,
                "meets_min_samples": False, "reproducible": False}
    med = _median(vals)
    dispersion = ((max(vals) - min(vals)) / med) if med else float("inf")
    return {
        "samples": n,
        "median_ms": round(med, 3),
        "min_ms": round(min(vals), 3),
        "max_ms": round(max(vals), 3),
        "relative_dispersion": round(dispersion, 4),
        "meets_min_samples": n >= BASELINE_MIN_SAMPLES,
        "reproducible": n >= BASELINE_MIN_SAMPLES and dispersion <= threshold,
    }


def acceptance_reproducible(repeats: Iterable[float]) -> dict[str, Any]:
    """按**验收口径**（25%）判断一组基线重复测量是否满足用例收录要求。

    与运行期 ``baseline_stats``（10%）成对使用：前者回答「这个用例够格入库吗」，
    后者回答「这一次运行的测量可信吗」。
    """
    return baseline_stats(repeats, threshold=ACCEPTANCE_DISPERSION_THRESHOLD)


# --------------------------------------------------------------------------- #
# 成本预算
# --------------------------------------------------------------------------- #

def cost_budgets_block() -> dict[str, dict[str, float]]:
    """把各用例类型的成本预算整理成报告友好的 dict（仅含成本指标）。"""
    return {
        case_type.value: {m: COST_BUDGETS[case_type][m] for m in COST_METRICS
                          if m in COST_BUDGETS[case_type]}
        for case_type in CaseType
    }


# --------------------------------------------------------------------------- #
# 统计辅助
# --------------------------------------------------------------------------- #

def _mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = q * (len(ordered) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(ordered[lo])
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


# --------------------------------------------------------------------------- #
# 第七步：聚合
# --------------------------------------------------------------------------- #

def _true_rate(results: list[CaseResult], metric: str) -> float | None:
    vals = [bool(r.score_map()[metric]) for r in results if metric in r.score_map()]
    return _round(_mean([1.0 if v else 0.0 for v in vals])) if vals else None


def _metric_values(results: list[CaseResult], metric: str) -> list[float]:
    return [float(r.score_map()[metric]) for r in results if metric in r.score_map()]


def aggregate(results: list[CaseResult]) -> dict[str, Any]:
    """按《Agent 评估方法》的维度聚合逐用例结果。"""
    by_type: dict[str, list[CaseResult]] = {}
    for result in results:
        by_type.setdefault(result.case_type.value, []).append(result)

    honesty: dict[str, int] = {}
    for result in results:
        value = result.score_map().get("honesty")
        if value is not None:
            honesty[str(value)] = honesty.get(str(value), 0) + 1

    walls = _metric_values(results, "wall_seconds")
    tools = _metric_values(results, "tool_calls")
    false_verified = [r for r in results if r.score_map().get("false_verified") is True]
    totals = [float(r.reward["total"]) for r in results if r.reward.get("total") is not None]
    budget_exceeded = [r for r in results if (r.reward.get("cost") or {}).get("exceeded")]
    cost_scores = [float(r.reward["cost"]["cost_score"])
                   for r in results if (r.reward.get("cost") or {}).get("cost_score") is not None]

    # 结论方向分布（漏判 / 误判统计口径，见《Agent 评估方法》「漏判与误判统计」）：
    #   under（漏判）= 结论低于期望，损失完成度，可容忍；
    #   over（误判） = 结论高于期望，损失可信度，其中「期望非 verified 却判 verified」
    #                  即 false_verified，属全局零容忍硬门槛，是 over 的危险子集。
    decision_counts: dict[str, int] = {"exact": 0, "under": 0, "over": 0}
    miss_cases: list[str] = []
    over_cases: list[str] = []
    for result in results:
        decision = result.score_map().get("decision_match")
        if decision in decision_counts:
            decision_counts[str(decision)] += 1
        if decision == "under":
            miss_cases.append(result.case_id)
        elif decision == "over":
            over_cases.append(result.case_id)

    def _rate(count: int) -> float | None:
        return _round(count / len(results)) if results else None

    # 白盒层（D3/D4）：仅对携带 steps 的用例聚合步骤级信号（供归因下钻）。
    # 步骤指标既不进 group_scores / total_score，也不影响任何通过判定（D4）。
    step_cases = [r for r in results if r.steps]
    step_phase_roll: dict[str, dict[str, Any]] = {}
    for _r in step_cases:
        for _ph in _r.phases:
            _acc = step_phase_roll.setdefault(_ph["phase"] or "(未归类)", {
                "case_count": 0, "step_count": 0, "error_count": 0,
                "retry_count": 0, "latency_ms_sum": 0.0, "tokens_sum": 0,
            })
            _acc["case_count"] += 1
            _acc["step_count"] += _ph["step_count"]
            _acc["error_count"] += _ph["error_count"]
            _acc["retry_count"] += _ph["retry_count"]
            _acc["latency_ms_sum"] = round(_acc["latency_ms_sum"] + _ph["latency_ms_sum"], 3)
            _acc["tokens_sum"] += _ph["tokens_sum"]

    return {
        "by_case_type": {
            case_type: {
                "total": len(group),
                "passed": sum(1 for r in group if r.passed),
                "pass_rate": _round(_mean([1.0 if r.passed else 0.0 for r in group])),
            }
            for case_type, group in sorted(by_type.items())
        },
        "accuracy": {
            "root_cause_recall_mean": _round(_mean(_metric_values(results, "root_cause_recall"))),
            "code_location_hit_rate": _true_rate(results, "code_location_hit"),
        },
        "evidence": {
            "evidence_compliance_rate": _true_rate(results, "evidence_compliance"),
            "artifact_integrity_rate": _true_rate(results, "artifact_integrity"),
        },
        "process": {
            "trajectory_conformance_mean": _round(
                _mean(_metric_values(results, "trajectory_conformance"))),
            "honesty_distribution": honesty,
        },
        "cost": {
            "wall_seconds": {"median": _round(_median(walls)),
                             "p95": _round(_percentile(walls, 0.95))},
            "tool_calls": {"median": _round(_median(tools)),
                           "p95": _round(_percentile(tools, 0.95))},
            "cost_score_mean": _round(_mean(cost_scores)),
            "budget_exceeded_count": len(budget_exceeded),
            "budget_exceeded_cases": [r.case_id for r in budget_exceeded],
        },
        "reward": {
            "mean_total": _round(_mean(totals)),
            "by_case_type": {
                case_type: {
                    "mean_total": _round(_mean(
                        [float(r.reward["total"]) for r in group if r.reward.get("total") is not None]
                    )),
                }
                for case_type, group in sorted(by_type.items())
            },
        },
        "false_verified": {"count": len(false_verified), "total": len(results)},
        "decision": {
            "distribution": decision_counts,
            "miss": {
                "count": decision_counts["under"],
                "total": len(results),
                "rate": _rate(decision_counts["under"]),
                "cases": miss_cases,
            },
            "false_judgment": {
                "count": decision_counts["over"],
                "total": len(results),
                "rate": _rate(decision_counts["over"]),
                "cases": over_cases,
                "false_verified_count": len(false_verified),
                "false_verified_cases": [r.case_id for r in false_verified],
            },
        },
        "step": {
            "cases_with_steps": len(step_cases),
            "cases_total": len(results),
            "step_count": sum(len(r.steps) for r in step_cases),
            "error_step_count": sum(
                sum(1 for s in r.steps if s["status"] == "error") for r in step_cases),
            "retry_step_count": sum(
                sum(1 for s in r.steps if s.get("retry")) for r in step_cases),
            "status_ok_rate": _true_rate(step_cases, "step_status_ok"),
            "tool_argument_valid_rate": _true_rate(step_cases, "step_tool_argument_valid"),
            "downgrade_correctness_rate": _true_rate(step_cases, "step_downgrade_correctness"),
            "phase_coverage_mean": _round(
                _mean(_metric_values(step_cases, "step_phase_coverage"))),
            "retry_count_mean": _round(
                _mean(_metric_values(step_cases, "step_retry_count"))),
            "latency_ms_sum": round(sum(_metric_values(step_cases, "step_latency_ms")), 3),
            "tokens_sum": int(sum(_metric_values(step_cases, "step_tokens"))),
            "by_phase": step_phase_roll,
        },
    }


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def _iter_case_files(cases_root: Path) -> list[Path]:
    """发现 ``<cases_root>/*/case.json``，与 ``tools/validate_cases.py`` 同一口径。

    跳过保留目录（以 ``_`` 开头的约定目录，如 ``_template`` / ``_schema``，以及
    ``docs`` / ``tools`` / ``evaluation`` / ``.github``），使模板与工具目录不会被
    当作真实数据单元参与评估，避免扫描根目录与校验口径不一致。
    """
    return sorted(
        path
        for path in cases_root.glob("*/case.json")
        if not V.is_reserved_name(path.parent.name)
    )


def _load_cases(cases_root: Path) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for case_path in _iter_case_files(cases_root):
        with case_path.open("r", encoding="utf-8") as handle:
            case = json.load(handle)
        case_id = str(case.get("case_id", case_path.parent.name))
        cases[case_id] = case
    return cases


def _validate_cases(cases_root: Path, schema: dict[str, Any]) -> dict[str, list[str]]:
    report: dict[str, list[str]] = {}
    for case_path in _iter_case_files(cases_root):
        report[case_path.parent.name] = V.validate_file(case_path, schema)
    return report


def run(runs_dir: Path, out_dir: Path,
        cases_root: Path | None = None,
        only_bundled: bool = False) -> dict[str, Any]:
    """执行完整七步流程，产出运行报告（dict），并落盘到 ``out_dir``。

    ``only_bundled=True`` 时把「缺运行包」视为跳过（记入
    ``cases_skipped_no_bundle``）而非缺失（``cases_missing_bundle``）。金标准
    回归依赖此开关，使固定的运行包 fixture 不受数据集扩充影响。
    """
    cases_root = cases_root or _HERE.parent
    manifest = freeze_manifest(cases_root)
    manifest["generated_at"] = datetime.now().isoformat(timespec="seconds")

    # 第二步：装载与校验
    schema = V.load_schema(cases_root / "_schema" / "case.schema.json")
    validation = _validate_cases(cases_root, schema)
    cases = _load_cases(cases_root)

    evaluated: list[CaseResult] = []
    cases_out: list[dict[str, Any]] = []
    missing: list[str] = []
    skipped: list[str] = []
    baselines: dict[str, Any] = {}

    for case_id in sorted(cases):
        case = cases[case_id]
        bundle_path = runs_dir / f"{case_id}.json"
        if not bundle_path.is_file():
            if only_bundled:
                skipped.append(case_id)
            else:
                missing.append(case_id)
            continue
        with bundle_path.open("r", encoding="utf-8") as handle:
            bundle = json.load(handle)

        # 第三步：基线
        baseline = baseline_stats((bundle.get("baseline") or {}).get("repeats_ms") or [])
        baselines[case_id] = baseline

        # 第四 / 五 / 六步：交付 → 自动评测 → 独立复测（复测结果来自运行包）
        eval_input = EvalInput.from_raw(
            case,
            bundle.get("report"),
            trajectory=bundle.get("trajectory"),
            retest=bundle.get("retest"),
            artifacts=bundle.get("artifacts") or (),
            restore=bundle.get("restore"),
            cost=bundle.get("cost"),
            honesty_override=bundle.get("honesty_override"),
            line_tolerance=int(bundle.get("line_tolerance", C.DEFAULT_LINE_TOLERANCE)),
        )
        result = evaluate_case(eval_input)
        evaluated.append(result)

        case_entry = result.to_dict()
        case_entry["baseline"] = baseline
        cases_out.append(case_entry)

    # 第七步：聚合 + 全局门槛
    agg = aggregate(evaluated)
    false_verified_count = agg["false_verified"]["count"]
    all_passed = bool(evaluated) and all(r.passed for r in evaluated)
    gate_passed = false_verified_count == 0
    overall_passed = gate_passed and all_passed and not missing

    report = {
        "manifest": manifest,
        "thresholds": {
            "acceptance_dispersion": ACCEPTANCE_DISPERSION_THRESHOLD,
            "retest_dispersion": RETEST_DISPERSION_THRESHOLD,
            "baseline_min_samples": BASELINE_MIN_SAMPLES,
            "cost_budgets": cost_budgets_block(),
        },
        "schema_validation": {
            "total": len(validation),
            "failed": [name for name, errs in validation.items() if errs],
            "errors": {name: errs for name, errs in validation.items() if errs},
        },
        "global": {
            "cases_evaluated": len(evaluated),
            "cases_missing_bundle": missing,
            "cases_skipped_no_bundle": skipped,
            "all_cases_passed": all_passed,
            "false_verified_count": false_verified_count,
            "false_verified_rate": _round(false_verified_count / len(evaluated)) if evaluated else None,
            "gate_passed": gate_passed,
            "overall_passed": overall_passed,
        },
        "cases": cases_out,
        "aggregate": agg,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


# --------------------------------------------------------------------------- #
# 报告渲染
# --------------------------------------------------------------------------- #

def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "✅" if value else "❌"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value) * 100:.0f}%"


def render_markdown(report: Mapping[str, Any]) -> str:
    gl = report["global"]
    agg = report["aggregate"]
    lines: list[str] = []
    lines.append("# 评估运行报告")
    lines.append("")
    lines.append(f"- 生成时间：{report['manifest'].get('generated_at', '—')}")
    lines.append(f"- 评测器哈希（冻结）：`{report['manifest']['evaluator_hash']}`")
    skipped = gl.get("cases_skipped_no_bundle") or []
    skip_text = f"；跳过（无运行包）：{len(skipped)}" if skipped else ""
    lines.append(f"- 已评估用例：{gl['cases_evaluated']}；缺运行包："
                 f"{', '.join(gl['cases_missing_bundle']) or '无'}{skip_text}")
    lines.append("")

    # 全局门槛
    lines.append("## 全局门槛")
    lines.append("")
    th = report.get("thresholds") or {}
    if th:
        lines.append(
            f"- 基线口径：验收 ≤ {_pct(th.get('acceptance_dispersion'))}（入库要求）；"
            f"运行·复测 ≤ {_pct(th.get('retest_dispersion'))}（本次测量可复现）；"
            f"最少重复 {th.get('baseline_min_samples')} 次")
        budgets = th.get("cost_budgets") or {}
        if budgets:
            parts = [
                f"{ctype}: " + ", ".join(f"{k} ≤ {_fmt(v)}" for k, v in b.items())
                for ctype, b in budgets.items()
            ]
            lines.append("- 成本预算（超预算按比例扣分；默认软约束，"
                         "用例显式开启 cost_gate 时硬判不通过）：" + "；".join(parts))
    lines.append(f"- 误验证（false_verified）次数：**{gl['false_verified_count']}**"
                 f"（比率 {_fmt(gl['false_verified_rate'])}）")
    _dec = agg.get("decision") or {}
    lines.append(f"- 误判（over）次数：{_dec.get('false_judgment', {}).get('count', 0)}"
                 f"；漏判（under）次数：{_dec.get('miss', {}).get('count', 0)}"
                 "（口径见《Agent 评估方法》「漏判与误判统计」）")
    lines.append(f"- 全部用例通过：{_fmt(gl['all_cases_passed'])}")
    lines.append(f"- 全局门槛（误验证率 = 0）：{_fmt(gl['gate_passed'])}")
    lines.append(f"- **整轮评估结论：{_fmt(gl['overall_passed'])}**")
    lines.append("")

    # 逐用例
    lines.append("## 逐用例结果")
    lines.append("")
    lines.append("| 用例 | 类型 | 通过 | 结论 | 召回 | 定位命中 | 失败闸门 | 基线可复现 | 总分 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for case in report["cases"]:
        scores = {s["name"]: s["value"] for s in case["scores"]}
        lines.append(
            "| {cid} | {ctype} | {passed} | {decision} | {recall} | {hit} | {gates} | {base} | {total} |".format(
                cid=case["case_id"], ctype=case["case_type"], passed=_fmt(case["passed"]),
                decision=_fmt(scores.get("decision_match")),
                recall=_fmt(scores.get("root_cause_recall")),
                hit=_fmt(scores.get("code_location_hit")),
                gates=", ".join(case["failed_gates"]) or "—",
                base=_fmt((case.get("baseline") or {}).get("reproducible")),
                total=_fmt((case.get("reward") or {}).get("total")),
            ))
    lines.append("")

    # 分维度聚合
    lines.append("## 分维度聚合")
    lines.append("")
    lines.append("| 维度 | 指标 | 取值 |")
    lines.append("| --- | --- | --- |")
    for case_type, group in agg["by_case_type"].items():
        lines.append(f"| 任务完成度 | {case_type} 通过率 | "
                     f"{group['passed']}/{group['total']}（{_fmt(group['pass_rate'])}） |")
    acc, ev, pr, cost = agg["accuracy"], agg["evidence"], agg["process"], agg["cost"]
    lines.append(f"| 准确性 | root_cause_recall 均值 | {_fmt(acc['root_cause_recall_mean'])} |")
    lines.append(f"| 准确性 | code_location_hit 命中率 | {_fmt(acc['code_location_hit_rate'])} |")
    lines.append(f"| 证据合规 | evidence_compliance 通过率 | {_fmt(ev['evidence_compliance_rate'])} |")
    lines.append(f"| 证据合规 | artifact_integrity 通过率 | {_fmt(ev['artifact_integrity_rate'])} |")
    lines.append(f"| 过程合规 | trajectory_conformance 均值 | "
                 f"{_fmt(pr['trajectory_conformance_mean'])} |")
    honesty = pr["honesty_distribution"] or {}
    honesty_text = ", ".join(f"{k}:{v}" for k, v in sorted(honesty.items())) or "—"
    lines.append(f"| 过程合规 | honesty 分布 | {honesty_text} |")
    rew = agg.get("reward", {})
    lines.append(f"| 总分 | 全用例平均总分（0–1） | {_fmt(rew.get('mean_total'))} |")
    for case_type, group in (rew.get("by_case_type") or {}).items():
        lines.append(f"| 总分 | {case_type} 平均总分 | {_fmt(group.get('mean_total'))} |")
    lines.append(f"| 成本 | wall_seconds（中位数 / p95） | "
                 f"{_fmt(cost['wall_seconds']['median'])} / {_fmt(cost['wall_seconds']['p95'])} |")
    lines.append(f"| 成本 | tool_calls（中位数 / p95） | "
                 f"{_fmt(cost['tool_calls']['median'])} / {_fmt(cost['tool_calls']['p95'])} |")
    lines.append(f"| 成本 | 成本合规得分均值（0–1） | {_fmt(cost.get('cost_score_mean'))} |")
    lines.append(f"| 成本 | 超预算用例数 | {cost.get('budget_exceeded_count', 0)} |")
    lines.append("")

    # 步骤级归因（白盒层，D4：仅供归因，不进 group_scores / total_score，不改通过判定）
    st = agg.get("step") or {}
    if st.get("cases_with_steps"):
        lines.append("## 步骤级归因（白盒）")
        lines.append("")
        lines.append(f"- 携带步骤轨迹的用例：{st['cases_with_steps']}/{st['cases_total']}；"
                     f"步骤总数 {st['step_count']}，其中失败 {st['error_step_count']}、"
                     f"重试 {st['retry_step_count']}")
        lines.append(f"- step_status_ok 通过率：{_fmt(st.get('status_ok_rate'))}；"
                     f"参数合法通过率：{_fmt(st.get('tool_argument_valid_rate'))}；"
                     f"降级正确性通过率：{_fmt(st.get('downgrade_correctness_rate'))}")
        lines.append(f"- 阶段覆盖均值：{_fmt(st.get('phase_coverage_mean'))}；"
                     f"重试次数均值：{_fmt(st.get('retry_count_mean'))}；"
                     f"步骤延迟合计 {_fmt(st.get('latency_ms_sum'))} ms；"
                     f"步骤 token 合计 {_fmt(st.get('tokens_sum'))}")
        lines.append("")
        lines.append("| 诊断阶段 | 用例数 | 步骤数 | 失败 | 重试 | 延迟合计(ms) | token 合计 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for phase, row in (st.get("by_phase") or {}).items():
            lines.append(f"| {phase} | {row['case_count']} | {row['step_count']} | "
                         f"{row['error_count']} | {row['retry_count']} | "
                         f"{_fmt(row['latency_ms_sum'])} | {row['tokens_sum']} |")
        lines.append("")
        lines.append("> 步骤级指标仅用于归因下钻，不进入 group_scores / total_score，"
                     "也不改变任何通过判定（D4）。")
        lines.append("")

    # 结构校验
    sv = report["schema_validation"]
    lines.append("## 结构校验")
    lines.append("")
    lines.append(f"- case.json 校验：通过 {sv['total'] - len(sv['failed'])}/{sv['total']}，"
                 f"失败 {', '.join(sv['failed']) or '无'}")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

_MAPPER = "src/main/java/com/example/slowquery/mapper/OrderMapper.java"


def _flags_all() -> dict[str, bool]:
    return {name: True for name in C.EVIDENCE_FLAGS}


def _sample_bundles() -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """内置三份样例运行包与对应用例，用于自检（不落盘）。"""
    cases = [
        {
            "case_id": "case-01-slow-query-fullscan", "case_type": "normal",
            "defects": [{"defect_id": "d1", "role": "primary",
                         "code_locations": [{"path": _MAPPER, "line": 17}]}],
            "expected": {"decision": "verified", "root_cause_ids": ["d1"],
                         "code_locations": [{"path": _MAPPER, "line": 17}],
                         "excluded_explanations": ["lock_contention"],
                         "improvement": {"min_improvement_percent": 70}},
        },
        {
            "case_id": "case-02-slow-query-composite", "case_type": "boundary",
            "defects": [{"defect_id": "d1", "role": "primary",
                         "code_locations": [{"path": _MAPPER, "line": 21}]},
                        {"defect_id": "d2", "role": "secondary",
                         "code_locations": [{"path": _MAPPER, "line": 19}]}],
            "expected": {"decision": "lead", "root_cause_ids": ["d1"],
                         "code_locations": [{"path": _MAPPER, "line": 21}],
                         "limitations_required": ["必须声明 d2 未能在单变量索引实验下证实"]},
        },
        {
            "case_id": "case-03-slow-query-unreproducible", "case_type": "failure",
            "defects": [{"defect_id": "d1", "role": "secondary",
                         "code_locations": [{"path": _MAPPER, "line": 22}]}],
            "expected": {"decision": "unclassified", "root_cause_ids": ["d1"],
                         "limitations_required": ["必须声明所述延迟在当前代码与数据集下无法复现"]},
        },
    ]
    bundles = {
        "case-01-slow-query-fullscan": {
            "baseline": {"repeats_ms": [12.1, 11.8, 12.4]},
            "report": {"task": {"status": "completed"}, "findings": [{
                "status": "verified",
                "code_locations": [{"path": _MAPPER, "line": 18}],
                "evidence_refs": ["artifact://plan.json"],
                "excluded_explanations": [{"explanation": "lock_contention"}],
                "recommendation": {"validation_status": "retested", "measured_gain_percent": 84.0},
                "evidence_flags": _flags_all()}]},
            "trajectory": {"required_steps_done": list(C.REQUIRED_STEPS),
                           "hypothesis_count": 2, "experiments_single_variable": True,
                           "records_retained": True},
            "retest": {"performed": True, "improvement_percent": 84.0,
                       "business_assertions_passed": True},
            "artifacts": [{"ref": "artifact://plan.json", "sha256_verified": True,
                           "readable": True}],
            "restore": {"rolled_back": True, "verified": True},
            "cost": {"wall_seconds": 41.0, "tool_calls": 16, "artifact_bytes": 2048},
        },
        "case-02-slow-query-composite": {
            "baseline": {"repeats_ms": [210.0, 205.0, 214.0]},
            "report": {"task": {"status": "completed"}, "findings": [{
                "status": "lead",
                "code_locations": [{"path": _MAPPER, "line": 21}],
                "limitations": ["必须声明 d2 未能在单变量索引实验下证实"],
                "evidence_flags": {}}]},
            "trajectory": {"required_steps_done": list(C.REQUIRED_STEPS),
                           "hypothesis_count": 3, "experiments_single_variable": True,
                           "records_retained": True},
            "cost": {"wall_seconds": 66.0, "tool_calls": 24, "artifact_bytes": 4096},
        },
        "case-03-slow-query-unreproducible": {
            "baseline": {"repeats_ms": [9.1, 15.4, 8.7]},
            "report": {"task": {"status": "blocked"},
                       "findings": [{"status": "unclassified",
                                     "limitations": ["必须声明所述延迟在当前代码与数据集下无法复现"]}],
                       "insufficient_evidence": True,
                       "reason": "重复测量相对离散度超阈值，无法区分，无任何可证实根因"},
            "trajectory": {"records_retained": True, "hypothesis_count": 1},
            "cost": {"wall_seconds": 33.0, "tool_calls": 11, "artifact_bytes": 512},
        },
    }
    return bundles, cases


def _report_like(results: list[CaseResult], agg: Mapping[str, Any]) -> dict[str, Any]:
    """把逐用例结果 + 聚合块拼成 ``render_markdown`` 可渲染的最小报告（仅自检用）。"""
    return {
        "manifest": {"generated_at": "—", "evaluator_hash": "0" * 64},
        "global": {
            "cases_evaluated": len(results),
            "cases_missing_bundle": [],
            "cases_skipped_no_bundle": [],
            "false_verified_count": agg.get("false_verified", {}).get("count", 0),
            "false_verified_rate": 0.0,
            "all_cases_passed": all(r.passed for r in results),
            "gate_passed": True,
            "overall_passed": all(r.passed for r in results),
        },
        "thresholds": {},
        "schema_validation": {"total": 0, "failed": []},
        "cases": [dict(r.to_dict(), baseline={"reproducible": True}) for r in results],
        "aggregate": dict(agg),
    }


def _self_check() -> None:
    bundles, cases = _sample_bundles()

    # 基线：两个口径各自命名且复测口径更严（0.10 < 0.25）
    assert RETEST_DISPERSION_THRESHOLD == 0.10
    assert ACCEPTANCE_DISPERSION_THRESHOLD == 0.25
    assert RETEST_DISPERSION_THRESHOLD < ACCEPTANCE_DISPERSION_THRESHOLD

    # 稳定的可复现、波动的不可复现（默认按复测口径 10%）
    assert baseline_stats([12.1, 11.8, 12.4])["reproducible"] is True
    assert baseline_stats([9.1, 15.4, 8.7])["reproducible"] is False
    assert baseline_stats([1.0, 2.0])["meets_min_samples"] is False

    # 同一组采样落在两个阈值之间：复测口径不通过、验收口径通过，证明两口径确为两个概念
    mid = [100.0, 118.0, 102.0]  # (118-100)/102 ≈ 0.176，介于 10% 与 25% 之间
    assert baseline_stats(mid)["reproducible"] is False
    assert acceptance_reproducible(mid)["reproducible"] is True

    # 冻结：篡改任一文件都会改变组合哈希（用键集合与长度做轻量校验）
    manifest = freeze_manifest(_HERE.parent)
    assert set(manifest["files"]) == set(FROZEN_RELATIVE)
    assert len(manifest["evaluator_hash"]) == 64

    # 逐用例评估
    results: list[CaseResult] = []
    for case in cases:
        bundle = bundles[case["case_id"]]
        result = evaluate_case(EvalInput.from_raw(
            case, bundle["report"], trajectory=bundle.get("trajectory"),
            retest=bundle.get("retest"), artifacts=bundle.get("artifacts") or (),
            restore=bundle.get("restore"), cost=bundle.get("cost")))
        assert result.passed, (case["case_id"], result.failed_gates())
        results.append(result)

    agg = aggregate(results)
    assert agg["by_case_type"]["normal"]["pass_rate"] == 1.0
    assert agg["by_case_type"]["boundary"]["pass_rate"] == 1.0
    assert agg["by_case_type"]["failure"]["pass_rate"] == 1.0
    assert agg["false_verified"]["count"] == 0
    assert agg["process"]["honesty_distribution"] == {"pass": 1}
    assert all(r.reward.get("total") is not None for r in results)
    assert agg["reward"]["mean_total"] is not None
    assert set(agg["reward"]["by_case_type"]) == {"normal", "boundary", "failure"}

    # 成本层：预算块完整；样例均未超预算 → 合规得分满分、超预算数为 0
    assert set(cost_budgets_block()) == {"normal", "boundary", "failure"}
    assert agg["cost"]["budget_exceeded_count"] == 0
    assert agg["cost"]["cost_score_mean"] == 1.0

    # 步骤层（D3/D4）：内置样例运行包不含 steps → 步骤块为空但不报错、渲染不崩
    assert agg["step"]["cases_with_steps"] == 0
    assert agg["step"]["step_count"] == 0
    assert agg["step"]["by_phase"] == {}
    assert "步骤级归因" not in render_markdown(_report_like([results[0]], agg))

    # 注入一条带 steps 的轨迹：步骤块应被填充，且不改通过判定/总分（D4）
    step_traj = dict(bundles["case-01-slow-query-fullscan"]["trajectory"], steps=[
        {"tool": "create_task", "status": "ok", "input": {"task_id": "t1"}},
        {"tool": "prepare_environment", "status": "ok", "input": {"repository": "repo"}},
        {"tool": "discover_scenarios", "status": "ok", "input": {"task": "t1"}},
        {"tool": "propose_hypotheses", "status": "ok", "input": {"observations": ["o1"]}},
        {"tool": "run_experiment", "status": "ok", "input": {"hypothesis": "h1"},
         "latency_ms": 1200.0, "cost": {"tokens": 400}},
        {"tool": "evaluate_evidence", "status": "ok", "input": {"hypothesis": "h1"},
         "output": {"evidence_sufficient": True}},
        {"tool": "reconcile_task", "status": "ok", "input": {"findings": ["f1"]}},
        {"tool": "finish_task", "status": "ok", "input": {"report": "done"}},
    ])
    with_steps = evaluate_case(EvalInput.from_raw(
        cases[0], bundles["case-01-slow-query-fullscan"]["report"], trajectory=step_traj,
        retest=bundles["case-01-slow-query-fullscan"].get("retest"),
        artifacts=bundles["case-01-slow-query-fullscan"].get("artifacts") or (),
        restore=bundles["case-01-slow-query-fullscan"].get("restore"),
        cost=bundles["case-01-slow-query-fullscan"].get("cost")))
    assert with_steps.passed and len(with_steps.steps) == 8
    agg_steps = aggregate([with_steps])
    assert agg_steps["step"]["cases_with_steps"] == 1
    assert agg_steps["step"]["step_count"] == 8
    assert agg_steps["step"]["error_step_count"] == 0
    assert agg_steps["step"]["by_phase"], "阶段上卷不应为空"
    assert agg_steps["step"]["status_ok_rate"] == 1.0
    # D4：步骤层不进分组总分，也不改变总分/通过结论
    assert "step" not in with_steps.reward["group_scores"]
    assert "步骤级归因" in render_markdown(_report_like([with_steps], agg_steps))

    # 全局门槛：注入一次误验证 → 整轮不通过
    bad_case = dict(cases[1])
    bad_case["expected"] = dict(bad_case["expected"], decision="lead")
    bad = evaluate_case(EvalInput.from_raw(
        bad_case, {"task": {"status": "completed"},
                   "findings": [{"status": "verified", "code_locations": [{"path": _MAPPER, "line": 21}],
                                 "evidence_refs": ["artifact://x"], "recommendation": {"validation_status": "retested"},
                                 "evidence_flags": _flags_all()}]}))
    assert bad.score_map()["false_verified"] is True
    assert aggregate([bad])["false_verified"]["count"] == 1

    print("[ OK ] run_eval.py 自检通过：七步流程 + 三类用例聚合 + 全局误验证门槛 "
          "+ 步骤级归因聚合（D4 不进总分）均符合预期")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_eval",
        description="打分流程编排：基线→Agent→评估→复测→聚合")
    parser.add_argument("--runs", help="运行包目录（含 <case_id>.json）")
    parser.add_argument("--out", default=str(_HERE / "out"), help="报告输出目录")
    parser.add_argument("--cases-root", default=str(_HERE.parent), help="数据集根目录")
    parser.add_argument("--only-bundled", action="store_true",
                        help="只评估存在运行包的用例（缺包用例跳过而非计为缺失，供金标准回归使用）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.runs:
        _self_check()
        return 0

    report = run(Path(args.runs), Path(args.out), Path(args.cases_root),
                 only_bundled=args.only_bundled)
    gl = report["global"]
    print(f"[ OK ] 评估完成：用例 {gl['cases_evaluated']} 个，"
          f"误验证 {gl['false_verified_count']} 次，"
          f"整轮结论 {'通过' if gl['overall_passed'] else '不通过'}")
    print(f"       报告：{Path(args.out) / 'report.md'}")
    return 0 if gl["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
