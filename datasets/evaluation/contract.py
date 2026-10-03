#!/usr/bin/env python3
"""被测 Agent 输出契约的规范化视图（纯标准库实现）。

评估器只读取 Agent 的**产出契约**，不读取其内部实现，因此评估标准与实现解耦。本模块把
《Agent 评估方法》中列出的字段规范化为不可变对象，并解析 ``case.json`` 里评测方一侧的
期望（``expected`` + ``defects``），供 ``metrics.py`` 计算四层指标。

覆盖的契约字段（来源：`Finding` / `ReportData`）：

- ``Finding.status``：``verified`` / ``lead`` / ``refuted`` / ``unclassified``；
- ``Finding.code_locations``：``CodeLocation``（``commit`` / ``path`` / ``line`` /
  ``association_evidence_ids``），定位准确性只比对 ``path`` 与 ``line``；
- ``Finding.excluded_explanations``：元素为对象时取其中的 ``explanation``；
- ``Finding.recommendation``：``validation_status``（``expected_mechanism`` / ``retested``）
  与 ``measured_gain_percent``；
- ``Finding.limitations``：结论适用范围；
- ``Finding.evidence_flags``：证据合规的结构化布尔位（由运行器/适配层从 ``SqlCall`` 与
  ``Observation`` 汇总而来，键见 ``EVIDENCE_FLAGS``）；
- ``ReportData.task.status``：``created`` / ``running`` / ``blocked`` / ``completed`` / ``partial``。

设计约定
--------
所有解析都对缺字段宽容：字段缺失即取默认值，**不抛异常**。Agent 产出不完整本身应由相应
指标扣分（例如 ``evidence_compliance=false``），而不是让评估器崩溃。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "STATUS_VERIFIED",
    "STATUS_LEAD",
    "STATUS_REFUTED",
    "STATUS_UNCLASSIFIED",
    "GATE_STATUSES",
    "DEFAULT_LINE_TOLERANCE",
    "REQUIRED_STEPS",
    "EVIDENCE_FLAGS",
    "paths_equal",
    "location_matches",
    "text_covers",
    "Location",
    "Recommendation",
    "Finding",
    "Report",
    "Trajectory",
    "Retest",
    "Artifact",
    "Restore",
    "Cost",
    "Expected",
]

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

STATUS_VERIFIED = "verified"
STATUS_LEAD = "lead"
STATUS_REFUTED = "refuted"
STATUS_UNCLASSIFIED = "unclassified"

#: 视为「断言了根因」的状态，参与 recall / precision / 定位命中。
GATE_STATUSES = (STATUS_VERIFIED, STATUS_LEAD)

DEFAULT_LINE_TOLERANCE = 5

#: 诊断闭环的必需步骤（对应《Agent 评估方法》过程层「必需步骤」）。
REQUIRED_STEPS: tuple[str, ...] = (
    "baseline",
    "hypotheses",
    "discriminating_experiment",
    "localization",
    "verification",
)

#: ``verified`` finding 必须具备的结构化证据位。
EVIDENCE_FLAGS: tuple[str, ...] = (
    "scan_rows_decreased",       # 索引干预前后扫描行数下降
    "duration_distinguishable",  # 耗时可区分
    "business_result_consistent",# 业务结果一致
    "no_lock_wait",              # 无锁等待
    "cache_known",               # 缓存状态已知
    "linked_to_code",            # 能关联到代码位置
)


# --------------------------------------------------------------------------- #
# 匹配辅助
# --------------------------------------------------------------------------- #

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+")
_STOPWORDS = frozenset({"the", "a", "an", "of", "to", "and", "or", "is", "in", "on",
                        "的", "了", "与", "和", "或", "是", "在", "对", "为"})


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", str(text).strip().lower())


def paths_equal(a: str, b: str) -> bool:
    """判断两个路径是否指向同一文件（容忍分隔符与绝对/相对前缀差异）。"""
    na = _norm(a).replace("\\", "/").strip("/")
    nb = _norm(b).replace("\\", "/").strip("/")
    if not na or not nb:
        return False
    return na == nb or na.endswith("/" + nb) or nb.endswith("/" + na)


def location_matches(a: "Location", b: "Location",
                     tolerance: int = DEFAULT_LINE_TOLERANCE) -> bool:
    """两个代码位置是否同文件且行号差 ≤ 容差。"""
    return paths_equal(a.path, b.path) and abs(int(a.line) - int(b.line)) <= tolerance


def text_covers(declared: str, required: str) -> bool:
    """判断 ``declared`` 是否覆盖了 ``required`` 这一限制项/解释项。

    容错匹配，按两级判定：先看规范化子串，再看显著词元覆盖率（≥ 0.6）。
    这样 Agent 用自己的措辞表述同一限制时仍可判定为「已声明」。
    """
    d = _norm(declared)
    r = _norm(required)
    if not r:
        return True
    if r in d:
        return True
    tokens = [t for t in _TOKEN_RE.findall(r) if len(t) >= 2 and t not in _STOPWORDS]
    if not tokens:
        return False
    hit = sum(1 for t in tokens if t in d)
    return hit / len(tokens) >= 0.6


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    out = []
    for item in value:
        if isinstance(item, Mapping):
            item = item.get("explanation") or item.get("text") or item.get("description") or ""
        out.append(str(item))
    return tuple(out)


def _as_flag_map(value: Any) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        return {}
    return {str(k): bool(v) for k, v in value.items()}


# --------------------------------------------------------------------------- #
# 值对象
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Location:
    """``CodeLocation`` 的规范化视图（比对只用到 ``path`` 与 ``line``）。"""

    path: str
    line: int
    commit: str | None = None
    association_evidence_ids: tuple[str, ...] = ()

    @classmethod
    def from_obj(cls, obj: Any) -> "Location":
        if isinstance(obj, cls):
            return obj
        if not isinstance(obj, Mapping):
            raise TypeError(f"无法解析 CodeLocation：{obj!r}")
        evidence = obj.get("association_evidence_ids") or ()
        return cls(
            path=str(obj.get("path", "")),
            line=int(obj.get("line", 0) or 0),
            commit=obj.get("commit"),
            association_evidence_ids=tuple(str(x) for x in evidence),
        )


@dataclass(frozen=True)
class Recommendation:
    """``Recommendation`` 的规范化视图。"""

    validation_status: str
    measured_gain_percent: float | None = None

    @property
    def retested(self) -> bool:
        return self.validation_status == "retested"

    @classmethod
    def from_obj(cls, obj: Any) -> "Recommendation | None":
        if obj is None or isinstance(obj, cls):
            return obj
        if not isinstance(obj, Mapping):
            # 允许把裸字符串当作建议描述
            return cls(validation_status="expected_mechanism")
        gain = obj.get("measured_gain_percent")
        return cls(
            validation_status=str(obj.get("validation_status", "expected_mechanism")),
            measured_gain_percent=(None if gain is None else float(gain)),
        )


@dataclass(frozen=True)
class Finding:
    """``Finding`` 的规范化视图。"""

    status: str = STATUS_UNCLASSIFIED
    code_locations: tuple[Location, ...] = ()
    excluded_explanations: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    recommendation: Recommendation | None = None
    evidence_flags: Mapping[str, bool] = field(default_factory=dict)

    @property
    def asserts_root_cause(self) -> bool:
        return self.status in GATE_STATUSES

    def evidence_complete(self) -> bool:
        """结构性证据要求是否全部满足（见《Agent 评估方法》证据层）。"""
        if not self.code_locations or not self.evidence_refs:
            return False
        if self.recommendation is None:
            return False
        return all(bool(self.evidence_flags.get(flag, False)) for flag in EVIDENCE_FLAGS)

    @classmethod
    def from_obj(cls, obj: Any) -> "Finding":
        if isinstance(obj, cls):
            return obj
        if not isinstance(obj, Mapping):
            raise TypeError(f"无法解析 Finding：{obj!r}")
        refs = obj.get("evidence_refs") or ()
        refs = (refs,) if isinstance(refs, str) else tuple(str(x) for x in refs)
        return cls(
            status=str(obj.get("status", STATUS_UNCLASSIFIED)),
            code_locations=tuple(Location.from_obj(x) for x in (obj.get("code_locations") or ())),
            excluded_explanations=_as_str_tuple(obj.get("excluded_explanations")),
            limitations=_as_str_tuple(obj.get("limitations")),
            evidence_refs=refs,
            recommendation=Recommendation.from_obj(obj.get("recommendation")),
            evidence_flags=_as_flag_map(obj.get("evidence_flags")),
        )


@dataclass(frozen=True)
class Report:
    """``ReportData`` 的规范化视图。"""

    findings: tuple[Finding, ...] = ()
    task_status: str = "created"
    observations: tuple[bool, ...] = ()
    insufficient_evidence: bool = False
    reason: str = ""

    # ---- 派生属性 ----
    @property
    def decision(self) -> str:
        """由 findings 归并出的整体结论，取值 ``verified`` / ``lead`` / ``unclassified``。"""
        if any(f.status == STATUS_VERIFIED for f in self.findings):
            return STATUS_VERIFIED
        if any(f.status == STATUS_LEAD for f in self.findings):
            return STATUS_LEAD
        return STATUS_UNCLASSIFIED

    @property
    def asserted_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.asserts_root_cause)

    @property
    def verified_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.status == STATUS_VERIFIED)

    @property
    def declared_explanations(self) -> tuple[str, ...]:
        out: list[str] = []
        for f in self.findings:
            out.extend(f.excluded_explanations)
        return tuple(out)

    @property
    def declared_limitations(self) -> tuple[str, ...]:
        out: list[str] = []
        for f in self.findings:
            out.extend(f.limitations)
        return tuple(out)

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        out: list[str] = []
        for f in self.findings:
            out.extend(f.evidence_refs)
        return tuple(out)

    @classmethod
    def from_obj(cls, obj: Any) -> "Report":
        if isinstance(obj, cls):
            return obj
        obj = obj or {}
        if not isinstance(obj, Mapping):
            raise TypeError(f"无法解析 ReportData：{obj!r}")

        task = obj.get("task")
        task_status = obj.get("task_status")
        if task_status is None:
            task_status = task.get("status") if isinstance(task, Mapping) else None
        task_status = str(task_status or "created")

        obs_raw = obj.get("observations") or ()
        observations: list[bool] = []
        for item in obs_raw:
            if isinstance(item, Mapping):
                observations.append(bool(item.get("business_valid", item.get("valid", False))))
            else:
                observations.append(bool(item))

        insufficient = bool(obj.get("insufficient_evidence", False))
        if not insufficient and task_status in ("blocked", "partial"):
            insufficient = True

        return cls(
            findings=tuple(Finding.from_obj(x) for x in (obj.get("findings") or ())),
            task_status=task_status,
            observations=tuple(observations),
            insufficient_evidence=insufficient,
            reason=str(obj.get("reason", "") or ""),
        )


@dataclass(frozen=True)
class Trajectory:
    """Agent 执行轨迹的规范化视图。"""

    required_steps_done: frozenset[str] = frozenset()
    hypothesis_count: int = 0
    experiments_single_variable: bool = False
    records_retained: bool = False
    tool_calls: int | None = None

    @property
    def steps_coverage(self) -> float:
        if not REQUIRED_STEPS:
            return 1.0
        done = len(set(REQUIRED_STEPS) & set(self.required_steps_done))
        return done / len(REQUIRED_STEPS)

    @property
    def constraints_satisfied(self) -> tuple[bool, ...]:
        return (self.hypothesis_count <= 3, bool(self.experiments_single_variable))

    @classmethod
    def from_obj(cls, obj: Any) -> "Trajectory":
        if obj is None or isinstance(obj, cls):
            return obj or cls()
        if not isinstance(obj, Mapping):
            raise TypeError(f"无法解析 Trajectory：{obj!r}")
        steps = obj.get("required_steps_done") or obj.get("steps") or ()
        if isinstance(steps, Mapping):
            steps = [k for k, v in steps.items() if v]
        return cls(
            required_steps_done=frozenset(str(s) for s in steps),
            hypothesis_count=int(obj.get("hypothesis_count", 0) or 0),
            experiments_single_variable=bool(obj.get("experiments_single_variable", False)),
            records_retained=bool(obj.get("records_retained", False)),
            tool_calls=(None if obj.get("tool_calls") is None else int(obj["tool_calls"])),
        )


@dataclass(frozen=True)
class Retest:
    """评测方独立复测的结果。"""

    performed: bool = False
    improvement_percent: float | None = None
    business_assertions_passed: bool = False

    @classmethod
    def from_obj(cls, obj: Any) -> "Retest":
        if obj is None or isinstance(obj, cls):
            return obj or cls()
        gain = obj.get("improvement_percent")
        return cls(
            performed=bool(obj.get("performed", False)),
            improvement_percent=(None if gain is None else float(gain)),
            business_assertions_passed=bool(obj.get("business_assertions_passed", False)),
        )


@dataclass(frozen=True)
class Artifact:
    """一条制品引用及其完整性校验结果。"""

    ref: str = ""
    sha256_verified: bool = False
    readable: bool = False

    @property
    def ok(self) -> bool:
        return self.sha256_verified and self.readable

    @classmethod
    def from_obj(cls, obj: Any) -> "Artifact":
        if isinstance(obj, cls):
            return obj
        if not isinstance(obj, Mapping):
            return cls(ref=str(obj), sha256_verified=False, readable=False)
        return cls(
            ref=str(obj.get("ref", "")),
            sha256_verified=bool(obj.get("sha256_verified", False)),
            readable=bool(obj.get("readable", False)),
        )


@dataclass(frozen=True)
class Restore:
    """环境回滚结果。"""

    rolled_back: bool = False
    verified: bool = False

    @property
    def restore_verified(self) -> bool:
        return self.rolled_back and self.verified

    @classmethod
    def from_obj(cls, obj: Any) -> "Restore":
        if obj is None or isinstance(obj, cls):
            return obj or cls()
        return cls(rolled_back=bool(obj.get("rolled_back", False)),
                   verified=bool(obj.get("verified", False)))


@dataclass(frozen=True)
class Cost:
    """运行级成本。"""

    wall_seconds: float = 0.0
    tool_calls: int = 0
    artifact_bytes: int = 0

    @classmethod
    def from_obj(cls, obj: Any) -> "Cost":
        if obj is None or isinstance(obj, cls):
            return obj or cls()
        return cls(
            wall_seconds=float(obj.get("wall_seconds", 0.0) or 0.0),
            tool_calls=int(obj.get("tool_calls", 0) or 0),
            artifact_bytes=int(obj.get("artifact_bytes", 0) or 0),
        )


@dataclass(frozen=True)
class Expected:
    """``case.json`` 中评测方一侧的期望视图。"""

    decision: str
    root_cause_ids: tuple[str, ...]
    defect_locations: Mapping[str, tuple[Location, ...]]
    code_locations: tuple[Location, ...] = ()
    excluded_explanations: tuple[str, ...] = ()
    improvement_min_percent: float | None = None
    limitations_required: tuple[str, ...] = ()

    @property
    def root_cause_locations(self) -> tuple[Location, ...]:
        """仅 ``root_cause_ids`` 对应的缺陷位置，用于 recall / precision 的配对。"""
        out: list[Location] = []
        for defect_id in self.root_cause_ids:
            out.extend(self.defect_locations.get(defect_id, ()))
        return tuple(out)

    @property
    def catalog_locations(self) -> tuple[Location, ...]:
        """全部已知缺陷位置（含 secondary / decoy），用作「不得越界断言」的边界。"""
        out: list[Location] = []
        for locs in self.defect_locations.values():
            out.extend(locs)
        return tuple(out)

    @classmethod
    def from_case(cls, case: Mapping[str, Any]) -> "Expected":
        expected = case.get("expected") or {}
        defects = case.get("defects") or ()

        defect_locations: dict[str, tuple[Location, ...]] = {}
        for defect in defects:
            if not isinstance(defect, Mapping):
                continue
            did = str(defect.get("defect_id", ""))
            if not did:
                continue
            locs = tuple(Location.from_obj(x) for x in (defect.get("code_locations") or ()))
            defect_locations[did] = locs

        improvement = expected.get("improvement") or {}
        min_pct = improvement.get("min_improvement_percent")
        return cls(
            decision=str(expected.get("decision", STATUS_UNCLASSIFIED)),
            root_cause_ids=tuple(str(x) for x in (expected.get("root_cause_ids") or ())),
            defect_locations=defect_locations,
            code_locations=tuple(
                Location.from_obj(x) for x in (expected.get("code_locations") or ())
            ),
            excluded_explanations=_as_str_tuple(expected.get("excluded_explanations")),
            improvement_min_percent=(None if min_pct is None else float(min_pct)),
            limitations_required=_as_str_tuple(expected.get("limitations_required")),
        )
