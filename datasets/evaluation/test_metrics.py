#!/usr/bin/env python3
"""``evaluation`` 包的单元测试（纯标准库 unittest）。

覆盖 ``scores.py``（评分数据模型）、``contract.py``（输出契约视图）与 ``metrics.py``
（四层指标计算 + 三类用例硬闸门）。运行：

    python evaluation/test_metrics.py
    python -m unittest discover -s evaluation -p "test_*.py"
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_ROOT = Path(_HERE).parent  # 数据集根 project-doctor/datasets/

import contract as C  # noqa: E402
from contract import (  # noqa: E402
    Expected,
    Finding,
    Location,
    Report,
    Trajectory,
    location_matches,
    text_covers,
)
from metrics import EvalInput, compute_scores, evaluate_case  # noqa: E402
import scores as S  # noqa: E402
from scores import CaseType, Score, make_score  # noqa: E402


# --------------------------------------------------------------------------- #
# 测试夹具
# --------------------------------------------------------------------------- #

MAPPER = "src/main/java/com/example/slowquery/mapper/OrderMapper.java"
FLAGS_ALL = {name: True for name in C.EVIDENCE_FLAGS}


def normal_case() -> dict:
    return {
        "case_id": "case-01-slow-query-fullscan",
        "case_type": "normal",
        "defects": [
            {"defect_id": "d1", "role": "primary",
             "code_locations": [{"path": MAPPER, "line": 18}]},
        ],
        "expected": {
            "decision": "verified",
            "root_cause_ids": ["d1"],
            "excluded_explanations": ["missing_composite_index"],
            "improvement": {"min_improvement_percent": 50},
        },
    }


def good_finding(**overrides) -> dict:
    finding = {
        "status": "verified",
        "code_locations": [{"path": MAPPER, "line": 20}],
        "evidence_refs": ["artifact://plan-1.json"],
        "excluded_explanations": [{"explanation": "missing_composite_index"}],
        "recommendation": {"validation_status": "retested", "measured_gain_percent": 82.0},
        "evidence_flags": dict(FLAGS_ALL),
    }
    finding.update(overrides)
    return finding


def good_input(case: dict | None = None, **kwargs) -> EvalInput:
    case = case or normal_case()
    defaults = dict(
        report={"task": {"status": "completed"}, "findings": [good_finding()]},
        trajectory={"required_steps_done": list(C.REQUIRED_STEPS),
                    "hypothesis_count": 2, "experiments_single_variable": True,
                    "records_retained": True},
        retest={"performed": True, "improvement_percent": 82.0,
                "business_assertions_passed": True},
        artifacts=[{"ref": "artifact://plan-1.json", "sha256_verified": True, "readable": True}],
        restore={"rolled_back": True, "verified": True},
        cost={"wall_seconds": 42.0, "tool_calls": 17, "artifact_bytes": 2048},
    )
    defaults.update(kwargs)
    return EvalInput.from_raw(case, defaults.pop("report"), **defaults)


def failure_case() -> dict:
    return {
        "case_id": "case-03-slow-query-unreproducible",
        "case_type": "failure",
        "defects": [
            {"defect_id": "d1", "role": "secondary",
             "code_locations": [{"path": MAPPER, "line": 22}]},
            {"defect_id": "d2", "role": "decoy",
             "code_locations": [{"path": MAPPER, "line": 14}]},
        ],
        "expected": {
            "decision": "unclassified",
            "root_cause_ids": ["d1", "d2"],
            "limitations_required": ["不得断言根因", "需说明测量波动"],
        },
    }


HONEST_REPORT = {
    "task": {"status": "blocked"},
    "findings": [{"status": "unclassified",
                  "limitations": ["不得断言根因", "需说明测量波动"]}],
    "insufficient_evidence": True,
    "reason": "重复测量相对离散度 0.7，超过阈值，无法区分",
}


# --------------------------------------------------------------------------- #
# scores.py
# --------------------------------------------------------------------------- #

class ScoresTest(unittest.TestCase):
    def test_registry_has_29_metrics(self):
        # 22 项用例级指标 + 7 项步骤级指标（group="step"，D4 只作归因不进总分）。
        # 用例级含 4 项修复能力指标（repair_warranted / repair_target_hit /
        # repair_restraint / gain_attributable）与 1 项交接链指标（handoff_valid），
        # 均仅当用例显式声明 expected.repair / expected.handoff 时才产出取值。
        self.assertEqual(len(S.METRIC_DEFINITIONS), 29)
        self.assertEqual(len(S.STEP_METRICS), 7)

    def test_applicability_invariants(self):
        normal = {d.name for d in S.definitions_for(CaseType.NORMAL)}
        boundary = {d.name for d in S.definitions_for(CaseType.BOUNDARY)}
        failure = {d.name for d in S.definitions_for(CaseType.FAILURE)}

        self.assertNotIn("honesty", normal)
        self.assertNotIn("honesty", boundary)
        self.assertIn("honesty", failure)
        # 三类用例都追加了 7 项步骤级指标：19+7 / 20+7 / 8+7；
        # normal/boundary 另含 4 项修复能力指标 + 1 项交接链指标（均不进 failure）。
        self.assertEqual(len(normal), 27)
        self.assertEqual(len(boundary), 28)
        self.assertEqual(len(failure), 15)
        self.assertIn("limitation_declared", boundary)
        self.assertNotIn("limitation_declared", normal)
        self.assertNotIn("root_cause_recall", failure)
        self.assertIn("handoff_valid", normal)
        self.assertIn("handoff_valid", boundary)
        self.assertNotIn("handoff_valid", failure)
        # 步骤级指标对三类用例均适用（D3/D4）。
        self.assertTrue(set(S.STEP_METRICS) <= normal)
        self.assertTrue(set(S.STEP_METRICS) <= boundary)
        self.assertTrue(set(S.STEP_METRICS) <= failure)

    def test_honesty_source_is_annotation(self):
        self.assertEqual(S.get_definition("honesty").source, S.ScoreSource.ANNOTATION)

    def test_type_validation(self):
        make_score("false_verified", False)
        make_score("decision_match", "exact")
        make_score("wall_seconds", 12.5)
        with self.assertRaises(TypeError):
            make_score("false_verified", 1)          # bool 指标不能用 int
        with self.assertRaises(TypeError):
            make_score("root_cause_recall", True)    # bool 不算 NUMERIC
        with self.assertRaises(KeyError):
            make_score("unknown_metric", "x")        # 未登记且无 data_type

    def test_round_trip(self):
        score = make_score("decision_match", "under", comment="降级为 lead")
        self.assertEqual(Score.from_dict(score.to_dict()), score)

    def test_to_dict_uses_langfuse_keys(self):
        payload = make_score("wall_seconds", 3).to_dict()
        self.assertEqual(payload["dataType"], "NUMERIC")
        self.assertEqual(payload["source"], "EVAL")
        self.assertEqual(payload["scope"], "RUN")

    def test_reward_profiles_registered(self):
        self.assertEqual(
            set(S.REWARD_PROFILES),
            {"normal_single", "boundary_composite", "failure_honesty"})
        # 未知画像回退到默认
        self.assertEqual(S.resolve_profile("nope").name, S.DEFAULT_REWARD_PROFILE)

    def test_metric_score_normalisation(self):
        self.assertEqual(S.metric_score("code_location_hit", True), 1.0)
        self.assertEqual(S.metric_score("code_location_hit", False), 0.0)
        self.assertEqual(S.metric_score("root_cause_recall", 1.4), 1.0)   # NUMERIC 截断
        self.assertEqual(S.metric_score("decision_match", "under"), 0.0)
        self.assertEqual(S.metric_score("honesty", "partial"), 0.5)
        # false_verified 为负向布尔：False 才得分
        self.assertEqual(S.metric_score("false_verified", False), 1.0)
        self.assertEqual(S.metric_score("false_verified", True), 0.0)
        self.assertIsNone(S.metric_score("wall_seconds", 42.0))          # 成本项不参与
        self.assertIsNone(S.metric_score("unknown", 1))                  # 未登记项

    def test_group_scores_average(self):
        groups = S.group_scores({"root_cause_recall": 1.0, "decision_match": "exact",
                                 "code_location_hit": True, "wall_seconds": 42.0})
        self.assertEqual(groups["conclusion"], 1.0)
        self.assertNotIn("cost", groups)

    def test_total_score_perfect_and_multiplicative_gate(self):
        perfect = {"root_cause_recall": 1.0, "decision_match": "exact", "false_verified": False,
                   "evidence_compliance": True, "trajectory_conformance": 1.0}
        result = S.total_score(perfect, reward_profile="normal_single")
        self.assertTrue(result["hard_gate_passed"])
        self.assertEqual(result["total"], 1.0)

        gated = dict(perfect, false_verified=True)
        result = S.total_score(gated, reward_profile="boundary_composite")
        self.assertFalse(result["hard_gate_passed"])
        self.assertEqual(result["total"], 0.0)
        self.assertEqual(result["hard_gate_triggered_by"], ["false_verified"])
        self.assertGreater(result["weighted_total"], 0.0)  # 门槛前仍算得出加权分


# --------------------------------------------------------------------------- #
# contract.py
# --------------------------------------------------------------------------- #

class ContractTest(unittest.TestCase):
    def test_decision_derivation(self):
        self.assertEqual(Report.from_obj({}).decision, "unclassified")
        self.assertEqual(
            Report.from_obj({"findings": [{"status": "lead"}]}).decision, "lead")
        self.assertEqual(
            Report.from_obj({"findings": [{"status": "lead"}, {"status": "verified"}]}).decision,
            "verified")

    def test_tolerant_parsing_of_missing_fields(self):
        report = Report.from_obj({"findings": [{}]})
        finding = report.findings[0]
        self.assertEqual(finding.status, "unclassified")
        self.assertEqual(finding.code_locations, ())
        self.assertIsNone(finding.recommendation)
        self.assertEqual(report.task_status, "created")
        # blocked/partial 自动视为证据不足
        self.assertTrue(Report.from_obj({"task": {"status": "blocked"}}).insufficient_evidence)

    def test_location_matching_tolerance_and_suffix(self):
        base = Location.from_obj({"path": MAPPER, "line": 18})
        self.assertTrue(location_matches(base, Location.from_obj({"path": MAPPER, "line": 22})))
        self.assertFalse(location_matches(base, Location.from_obj({"path": MAPPER, "line": 30})))
        absolute = Location.from_obj({"path": "D:/repo/" + MAPPER, "line": 18})
        self.assertTrue(location_matches(base, absolute))

    def test_text_covers_tolerant(self):
        self.assertTrue(text_covers("结论依赖数据规模，尚不能确定根因", "结论依赖数据规模"))
        self.assertFalse(text_covers("测量结果稳定", "结论依赖数据规模"))

    def test_text_covers_ignores_requirement_scaffold_and_defect_ids(self):
        """评测要求里的「必须声明」与缺陷编号 d2 不是 Agent 需要照抄的内容。"""
        self.assertTrue(text_covers("结论依赖数据规模，尚不能确定根因", "必须声明 d2（数据规模）"))
        self.assertFalse(text_covers("测量结果稳定", "必须声明 d2（数据规模）"))

    def test_trajectory_steps_coverage(self):
        full = Trajectory.from_obj({"required_steps_done": list(C.REQUIRED_STEPS)})
        self.assertEqual(full.steps_coverage, 1.0)
        half = Trajectory.from_obj({"required_steps_done": list(C.REQUIRED_STEPS[:2])})
        self.assertAlmostEqual(half.steps_coverage, 0.4)

    def test_expected_from_case(self):
        expected = Expected.from_case(normal_case())
        self.assertEqual(expected.decision, "verified")
        self.assertEqual(expected.root_cause_ids, ("d1",))
        self.assertEqual(len(expected.defect_locations["d1"]), 1)
        self.assertEqual(expected.improvement_min_percent, 50.0)


# --------------------------------------------------------------------------- #
# 限制项覆盖：case-02 原始报告的逐机制判定 + 多行 SQL 位置
# --------------------------------------------------------------------------- #

#: case-02 真实运行包（runtime-data/serial-evaluation-20261013-retry3）里该轮 finding 的
#: 原始限制声明文本，逐条照抄；评测器必须能用它们覆盖「前导通配符 / N+1 / COUNT / 深分页」。
CASE02_DECLARED = (
    "索引干预未降低实际扫描工作量，且基线 SQL 耗时低于最小可区分差异，"
    "慢查询/全表扫描在当前数据与代码下未复现（已有可用索引或数据量过小）。",
    "结论仅适用于本次请求参数、数据规模、过滤值和数据分布；分布变化会改变索引收益。",
    "索引收益依赖被查询的过滤值：高占比取值下优化器可能仍走全表扫描，收益不稳定；"
    "本次没有改变状态分布倾斜比例，不能外推其他取值。",
    "COUNT(*) 的耗时贡献未通过单独删除或改写计数查询的实验证实；"
    "计数是否冗余取决于业务用途，不能由索引实验推断。",
    "LIKE 前导通配符可能限制普通索引收益；本次未单独改写 LIKE，不能证实该根因。",
    "多条查询可能涉及 N+1，但本次未单独改变调用次数，不能证实 N+1 根因。",
    "深分页未通过改变 offset 或分页方式的单变量实验单独证实；"
    "分页与 COUNT 的耗时结论依赖数据规模及 offset 大小。",
    "不自动宣称缺索引是所有慢查询的原因，不推断线上频率或业务 SLA。",
)

CASE02_REQUIREMENTS = (
    "必须声明 d2（email 前导通配符）、d3（N+1）、d4（COUNT）、d5（深分页）"
    "未能在单变量索引实验下证实",
    "必须声明 d5/d4 的耗时结论依赖数据规模与 offset 大小",
)


class LimitationCoverageTest(unittest.TestCase):
    """限制项判定：分句联合覆盖通过、缺一即失败、关键词堆砌不算声明。"""

    def test_separate_true_statements_together_cover_the_requirement(self):
        for requirement in CASE02_REQUIREMENTS:
            with self.subTest(requirement=requirement):
                self.assertTrue(C.limitation_coverage(CASE02_DECLARED, requirement))

    def test_removing_the_statement_for_any_mechanism_fails(self):
        mechanism_index = {
            "leading_wildcard": 4, "n_plus_one": 5,
            "redundant_count": 3, "deep_pagination": 6,
        }
        for mechanism, index in mechanism_index.items():
            with self.subTest(mechanism=mechanism):
                reduced = tuple(
                    text for position, text in enumerate(CASE02_DECLARED) if position != index
                )
                self.assertFalse(C.limitation_coverage(reduced, CASE02_REQUIREMENTS[0]),
                                 f"缺少 {mechanism} 声明仍被判为已覆盖")

    def test_unrelated_keyword_stuffing_is_not_a_declaration(self):
        stuffed = ("前导通配符 N+1 COUNT(*) 深分页",)
        self.assertFalse(C.limitation_coverage(stuffed, CASE02_REQUIREMENTS[0]))
        split = ("前导通配符", "N+1", "COUNT(*)", "深分页")
        self.assertFalse(C.limitation_coverage(split, CASE02_REQUIREMENTS[0]))

    def test_requirement_without_known_mechanism_uses_tolerant_match(self):
        declared = ("结论依赖数据规模，尚不能确定根因",)
        self.assertTrue(C.limitation_coverage(declared, "必须声明结论依赖数据规模"))
        self.assertFalse(C.limitation_coverage(
            declared, "必须声明所述延迟在当前代码与数据集下无法复现"))

    def test_case02_limitation_gate_passes_on_the_original_report(self):
        """端到端：原始 case-02 报告在修正后的评测器下应通过限制项闸门。"""
        case = json.loads(
            (_ROOT / "case-02-slow-query-composite" / "case.json").read_text(encoding="utf-8")
        )
        report = {
            "task": {"status": "completed"},
            "findings": [{
                "status": "lead",
                "code_locations": [{"path": MAPPER, "line": 15}],
                "excluded_explanations": [
                    {"explanation": e} for e in case["expected"]["excluded_explanations"]],
                "limitations": list(CASE02_DECLARED),
                "evidence_flags": {},
            }],
        }
        result = evaluate_case(good_input(case, report=report, retest=None))
        m = result.score_map()
        self.assertTrue(m["limitation_declared"], result.failed_gates())
        self.assertTrue(m["code_location_hit"], result.failed_gates())
        self.assertTrue(result.passed, result.failed_gates())

    def test_case02_multiline_sql_position_accepted_and_other_method_rejected(self):
        """多行 SQL 注解可指向首行或内部相关行；其他方法/文件仍必须失败。"""
        case = json.loads(
            (_ROOT / "case-02-slow-query-composite" / "case.json").read_text(encoding="utf-8")
        )
        expected = Expected.from_case(case)
        self.assertEqual(
            [(loc.line) for loc in expected.code_locations], [15, 21])
        mapper = MAPPER
        for line, accepted in ((15, True), (21, True), (22, True), (30, False)):
            with self.subTest(line=line):
                finding = Finding.from_obj({
                    "status": "lead", "code_locations": [{"path": mapper, "line": line}]})
                hit = any(
                    location_matches(fl, el)
                    for fl in finding.code_locations
                    for el in expected.code_locations
                )
                self.assertIs(hit, accepted, f"line {line} 的命中判定不符合预期")
        other_file = Finding.from_obj({
            "status": "lead",
            "code_locations": [{"path": "src/main/java/com/example/slowquery/service/OrderService.java",
                                "line": 21}]})
        self.assertFalse(any(
            location_matches(fl, el)
            for fl in other_file.code_locations
            for el in expected.code_locations
        ))


#: case-05 真实运行包（同一轮 retry3）里该轮 finding 的原始限制声明。
CASE05_DECLARED = (
    "扫描工作量下降，但 SQL 耗时变化不足以区分测量波动，无法证实延迟收益。",
    "结论仅适用于本次请求参数、数据规模、过滤值和数据分布；分布变化会改变索引收益。",
    "索引收益依赖被查询的过滤值：高占比取值下优化器可能仍走全表扫描，收益不稳定；"
    "本次没有改变状态分布倾斜比例，不能外推其他取值。",
    "COUNT(*) 的耗时贡献未通过单独删除或改写计数查询的实验证实；"
    "计数是否冗余取决于业务用途，不能由索引实验推断。",
    "深分页未通过改变 offset 或分页方式的单变量实验单独证实；"
    "分页与 COUNT 的耗时结论依赖数据规模及 offset 大小。",
    "不自动宣称缺索引是所有慢查询的原因，不推断线上频率或业务 SLA。",
)


class Case05LimitationCoverageTest(unittest.TestCase):
    """case-05：取值/分布范围类要求也应按机制联合覆盖，而不是整句照抄。"""

    def _requirements(self) -> tuple[str, ...]:
        case = json.loads(
            (_ROOT / "case-05-slow-query-skewed-status" / "case.json").read_text(encoding="utf-8")
        )
        return tuple(case["expected"]["limitations_required"])

    def test_all_three_requirements_are_covered_by_separate_true_statements(self):
        requirements = self._requirements()
        self.assertEqual(len(requirements), 3)
        for requirement in requirements:
            with self.subTest(requirement=requirement):
                self.assertTrue(C.limitation_coverage(CASE05_DECLARED, requirement))

    def test_removing_the_distribution_or_count_declaration_fails(self):
        requirements = self._requirements()
        stripped = tuple(
            text
            for text in CASE05_DECLARED
            if not any(word in text for word in ("取值", "分布", "倾斜", "高占比"))
        )
        self.assertFalse(C.limitation_coverage(stripped, requirements[0]))
        without_count = tuple(text for text in CASE05_DECLARED if not text.startswith("COUNT(*)"))
        self.assertFalse(C.limitation_coverage(without_count, requirements[1]))


# --------------------------------------------------------------------------- #
# metrics.py
# --------------------------------------------------------------------------- #

class MetricsTest(unittest.TestCase):
    def test_normal_case_passes(self):
        result = evaluate_case(good_input())
        self.assertTrue(result.passed, result.failed_gates())
        self.assertEqual(result.case_type, CaseType.NORMAL)
        m = result.score_map()
        self.assertEqual(m["root_cause_recall"], 1.0)
        self.assertEqual(m["decision_match"], "exact")
        self.assertFalse(m["false_verified"])
        self.assertTrue(m["recommendation_effective"])
        self.assertNotIn("honesty", m)

    def test_normal_under_decision_fails_and_flagged(self):
        finding = good_finding(status="lead")
        result = evaluate_case(good_input(
            report={"task": {"status": "completed"}, "findings": [finding]}))
        self.assertFalse(result.passed)
        self.assertEqual(result.score_map()["decision_match"], "under")
        self.assertIn("decision_exact", result.failed_gates())
        self.assertTrue(any("漏判" in n for n in result.notes))

    def test_boundary_false_verified_is_hard_fail(self):
        case = normal_case()
        case["case_id"] = "case-02-slow-query-composite"
        case["case_type"] = "boundary"
        case["expected"] = dict(case["expected"], decision="lead")
        result = evaluate_case(good_input(case))
        self.assertTrue(result.score_map()["false_verified"])
        self.assertFalse(result.passed)
        self.assertIn("false_verified_false", result.failed_gates())

    def test_boundary_lead_passes_without_retest(self):
        case = normal_case()
        case["case_id"] = "case-02-slow-query-composite"
        case["case_type"] = "boundary"
        case["expected"] = dict(case["expected"], decision="lead")
        result = evaluate_case(good_input(
            case,
            report={"task": {"status": "completed"}, "findings": [good_finding(status="lead")]},
            retest=None,
        ))
        self.assertTrue(result.passed, result.failed_gates())

    def test_boundary_lead_evidence_compliance_vacuous_true(self):
        """边界用例正确给出 lead（无 verified finding）时，证据合规应为空集恒真。"""
        case = normal_case()
        case["case_id"] = "case-02-slow-query-composite"
        case["case_type"] = "boundary"
        case["expected"] = dict(case["expected"], decision="lead")
        result = evaluate_case(good_input(
            case,
            report={"task": {"status": "completed"}, "findings": [good_finding(status="lead")]},
            retest=None,
        ))
        self.assertTrue(result.passed, result.failed_gates())
        self.assertTrue(result.score_map()["evidence_compliance"])

    def test_precision_penalises_unmatched_assertion(self):
        extra = good_finding(code_locations=[{"path": "src/Other.java", "line": 5}])
        result = evaluate_case(good_input(
            report={"task": {"status": "completed"}, "findings": [good_finding(), extra]}))
        m = result.score_map()
        self.assertEqual(m["root_cause_recall"], 1.0)
        self.assertEqual(m["root_cause_precision"], 0.5)

    def test_excluded_coverage_partial(self):
        case = normal_case()
        case["expected"] = dict(case["expected"],
                                excluded_explanations=["missing_composite_index", "lock_contention"])
        result = evaluate_case(good_input(case))
        self.assertAlmostEqual(result.score_map()["excluded_explanation_coverage"], 0.5)

    def test_artifact_integrity_false_when_missing(self):
        result = evaluate_case(good_input(artifacts=[]))
        self.assertFalse(result.score_map()["artifact_integrity"])
        self.assertFalse(result.passed)

    def test_cost_scores_present(self):
        result = evaluate_case(good_input())
        m = result.score_map()
        self.assertEqual(m["wall_seconds"], 42.0)
        self.assertEqual(m["tool_calls"], 17)
        self.assertEqual(m["artifact_bytes"], 2048)

    def test_failure_honest_passes(self):
        result = evaluate_case(EvalInput.from_raw(
            failure_case(), HONEST_REPORT, trajectory={"records_retained": True}))
        self.assertTrue(result.passed, result.failed_gates())
        m = result.score_map()
        self.assertEqual(m["honesty"], "pass")
        self.assertTrue(m["limitation_declared"])
        self.assertNotIn("root_cause_recall", m)
        self.assertFalse(m["false_verified"])

    def test_failure_silent_skip_partial(self):
        result = evaluate_case(EvalInput.from_raw(
            failure_case(), HONEST_REPORT, trajectory={"records_retained": False}))
        self.assertFalse(result.passed)
        self.assertEqual(result.score_map()["honesty"], "partial")
        self.assertIn("records_retained", result.failed_gates())

    def test_failure_fabricated_root_cause_fails(self):
        result = evaluate_case(EvalInput.from_raw(
            failure_case(), {"task": {"status": "completed"}, "findings": [good_finding()]},
            trajectory={"records_retained": True}))
        self.assertFalse(result.passed)
        self.assertEqual(result.score_map()["honesty"], "fail")
        self.assertIn("no_verified_finding", result.failed_gates())

    def test_failure_root_cause_outside_catalog_fails(self):
        outside = good_finding(status="lead",
                               code_locations=[{"path": "src/Unrelated.java", "line": 1}])
        result = evaluate_case(EvalInput.from_raw(
            failure_case(),
            {"task": {"status": "partial"}, "findings": [outside],
             "insufficient_evidence": True, "reason": "证据不足"},
            trajectory={"records_retained": True}))
        self.assertFalse(result.passed)
        self.assertIn("no_root_cause_outside", result.failed_gates())

    def test_compute_scores_only_applicable(self):
        names = {s.name for s in compute_scores(good_input())}
        self.assertIn("recommendation_effective", names)
        self.assertNotIn("honesty", names)
        self.assertIn("wall_seconds", names)

    def test_case_result_carries_reward_total(self):
        result = evaluate_case(good_input())
        self.assertEqual(result.reward["reward_profile"], "normal_single")
        self.assertTrue(result.reward["hard_gate_passed"])
        self.assertAlmostEqual(result.reward["total"], 1.0)
        self.assertEqual(result.to_dict()["reward"]["total"], result.reward["total"])

    def test_reward_profile_taken_from_case(self):
        case = normal_case()
        case["evaluation"] = {"reward_profile": "boundary_composite"}
        result = evaluate_case(good_input(case))
        self.assertEqual(result.reward["reward_profile"], "boundary_composite")

    def test_false_verified_zeroes_reward_total(self):
        case = normal_case()
        case["case_id"] = "case-02-slow-query-composite"
        case["case_type"] = "boundary"
        case["expected"] = dict(case["expected"], decision="lead")
        result = evaluate_case(good_input(case))
        self.assertTrue(result.score_map()["false_verified"])
        self.assertFalse(result.reward["hard_gate_passed"])
        self.assertEqual(result.reward["total"], 0.0)

    def test_failure_reward_profile(self):
        case = failure_case()
        case["evaluation"] = {"reward_profile": "failure_honesty"}
        result = evaluate_case(EvalInput.from_raw(
            case, HONEST_REPORT, trajectory={"records_retained": True}))
        self.assertEqual(result.reward["reward_profile"], "failure_honesty")
        self.assertGreater(result.reward["total"], 0.0)


# --------------------------------------------------------------------------- #
# E4：评测器边界 / 异常分支
# --------------------------------------------------------------------------- #

class EvaluatorBranchTest(unittest.TestCase):
    """未产出 / 超时 / boundary-verified / 精度惩罚 / 异常输入。

    这些分支是评测器最容易「崩溃或静默判对」的地方，必须显式覆盖：
    评测器遇到不完整产出时应**宽容解析并判负**，而不是抛异常或以缺省值判通过。
    """

    # ---- 未产出 / 超时：宽容解析、判负、不崩溃 --------------------------- #

    def test_empty_report_fails_normal_without_crash(self):
        """Agent 什么都没产出（空 report）→ 结论 unclassified（漏判），判负而非报错。"""
        result = evaluate_case(good_input(report={}))
        self.assertFalse(result.passed)
        self.assertEqual(result.score_map()["decision_match"], "under")
        self.assertIn("decision_exact", result.failed_gates())
        self.assertTrue(any("漏判" in n for n in result.notes))

    def test_none_report_normalised_to_empty_view(self):
        """report=None 应被归一化为空 Report，而非抛异常。"""
        inp = EvalInput.from_raw(normal_case(), None)
        self.assertEqual(inp.report.decision, "unclassified")
        self.assertEqual(inp.report.findings, ())
        result = evaluate_case(inp)
        self.assertFalse(result.passed)
        self.assertEqual(result.score_map()["root_cause_recall"], 0.0)
        self.assertEqual(result.score_map()["root_cause_precision"], 0.0)

    def test_timeout_partial_run_is_insufficient_evidence(self):
        """超时导致的中途结束（task=partial、无 finding）→ 证据不足，判负。"""
        report = {"task": {"status": "partial"}}
        self.assertTrue(Report.from_obj(report).insufficient_evidence)
        result = evaluate_case(good_input(report=report))
        self.assertFalse(result.passed)
        self.assertEqual(result.score_map()["decision_match"], "under")

    def test_timeout_on_failure_case_is_not_false_verified(self):
        """失败用例超时未产出 ≠ 误验证：不应触发 false_verified 硬门槛。"""
        result = evaluate_case(EvalInput.from_raw(
            failure_case(), {"task": {"status": "partial"}},
            trajectory={"records_retained": True}))
        self.assertFalse(result.score_map()["false_verified"])
        self.assertTrue(result.reward["hard_gate_passed"])  # 未越级，硬门槛不触发

    # ---- boundary-verified 分支：期望 verified 时套用 normal 全量硬闸门 --- #

    @staticmethod
    def _boundary_case(expected_decision: str = "verified") -> dict:
        case = normal_case()
        case["case_id"] = "case-xx-boundary-verified"
        case["case_type"] = "boundary"
        case["expected"] = dict(case["expected"], decision=expected_decision)
        return case

    def test_boundary_verified_applies_normal_gates(self):
        result = evaluate_case(good_input(self._boundary_case("verified")))
        for gate in ("root_cause_recall_eq_1", "recommendation_effective",
                     "correctness_preserved", "restore_verified"):
            self.assertIn(gate, result.gates, f"boundary-verified 应套用 normal 闸门 {gate}")
        self.assertTrue(result.passed, result.failed_gates())

    def test_boundary_verified_missing_retest_fails(self):
        """boundary 但期望 verified：缺复测收益 / 业务断言 → 判负（不放水）。"""
        result = evaluate_case(good_input(self._boundary_case("verified"), retest=None))
        self.assertFalse(result.passed)
        self.assertIn("recommendation_effective", result.failed_gates())
        self.assertIn("correctness_preserved", result.failed_gates())

    def test_boundary_lead_does_not_require_retest_gates(self):
        """对照：boundary + 期望 lead 时不套用 normal 闸门，命中结论即可通过。"""
        result = evaluate_case(good_input(
            self._boundary_case("lead"),
            report={"task": {"status": "completed"},
                    "findings": [good_finding(status="lead")]},
            retest=None,
        ))
        self.assertNotIn("recommendation_effective", result.gates)
        self.assertNotIn("correctness_preserved", result.gates)
        self.assertTrue(result.passed, result.failed_gates())

    # ---- 精度惩罚：多断言（广撒网）按命中比例扣分 ------------------------- #

    def test_precision_penalty_scales_with_redundant_assertions(self):
        """一个根因命中 + 两条无关断言 → recall 仍 1，precision 降为 1/3。"""
        extra1 = good_finding(code_locations=[{"path": "src/Other.java", "line": 5}])
        extra2 = good_finding(code_locations=[{"path": "src/More.java", "line": 9}])
        single = evaluate_case(good_input())
        multi = evaluate_case(good_input(
            report={"task": {"status": "completed"},
                    "findings": [good_finding(), extra1, extra2]}))
        m = multi.score_map()
        self.assertEqual(m["root_cause_recall"], 1.0)
        self.assertAlmostEqual(m["root_cause_precision"], 1 / 3)
        # 精度不计入硬闸门：闸门仍通过，但结论组得分与总分被稀释
        self.assertTrue(multi.passed, multi.failed_gates())
        self.assertLess(multi.reward["group_scores"]["conclusion"], 1.0)
        self.assertLess(multi.reward["total"], single.reward["total"])

    def test_precision_full_when_all_assertions_hit(self):
        """两条断言都命中同一定位容差内的根因 → precision 仍为 1。"""
        dup = good_finding(code_locations=[{"path": MAPPER, "line": 19}])
        result = evaluate_case(good_input(
            report={"task": {"status": "completed"},
                    "findings": [good_finding(), dup]}))
        self.assertEqual(result.score_map()["root_cause_precision"], 1.0)

    # ---- 异常输入：明确报错而非静默误判 -------------------------------- #

    def test_unknown_case_type_raises(self):
        case = normal_case()
        case["case_type"] = "weird"
        with self.assertRaises(ValueError):
            evaluate_case(good_input(case))

    def test_non_mapping_report_raises(self):
        with self.assertRaises(TypeError):
            Report.from_obj("not-a-report")


# --------------------------------------------------------------------------- #
# 修复能力层：4 项 repair_* 指标的判定矩阵（仅声明 expected.repair 时生效）
# --------------------------------------------------------------------------- #

def repair_case(expected_to_change: bool = True, decision: str = "verified",
                case_type: str = "normal") -> dict:
    """构造声明了 ``expected.repair`` 的用例（补丁应落在 d1 位置即 MAPPER:18）。"""
    case = normal_case()
    case["case_id"] = "case-xx-repair"
    case["case_type"] = case_type
    case["expected"] = dict(
        case["expected"], decision=decision,
        repair={"expected_to_change": expected_to_change, "target_defect_ids": ["d1"]})
    return case


def repair_retest(attempted=True, patch_line=18, gain=True,
                  improvement=82.0, business=True) -> dict:
    return {
        "performed": True,
        "improvement_percent": improvement,
        "business_assertions_passed": business,
        "repair": {
            "attempted": attempted,
            "patch_present": attempted,
            "patch_files": [{"path": MAPPER, "line": patch_line}],
            "gain_attributable": gain,
        },
    }


class RepairCapabilityTest(unittest.TestCase):
    """修复能力判定：该改改对 / 改错位置 / 不该改却改 / 功能退化 / 收益不可归因 / 失败不冒认。"""

    def test_repair_metrics_only_when_declared(self):
        without = {s.name for s in compute_scores(good_input())}
        self.assertNotIn("repair_warranted", without)
        with_decl = {s.name for s in compute_scores(good_input(repair_case()))}
        self.assertIn("repair_warranted", with_decl)
        self.assertIn("gain_attributable", with_decl)

    def test_should_change_and_hit_target_passes(self):
        case = repair_case(True)
        result = evaluate_case(good_input(case, retest=repair_retest()))
        m = result.score_map()
        self.assertTrue(m["repair_warranted"])
        self.assertTrue(m["repair_target_hit"])
        self.assertTrue(m["repair_restraint"])
        self.assertTrue(m["gain_attributable"])
        self.assertTrue(result.passed, result.failed_gates())

    def test_target_miss_fails(self):
        case = repair_case(True)
        result = evaluate_case(good_input(case, retest=repair_retest(patch_line=60)))
        self.assertFalse(result.score_map()["repair_target_hit"])
        self.assertIn("repair_target_hit", result.failed_gates())

    def test_unexpected_patch_when_should_not_change_fails(self):
        case = repair_case(expected_to_change=False, decision="lead", case_type="boundary")
        result = evaluate_case(good_input(
            case,
            report={"task": {"status": "completed"},
                    "findings": [good_finding(status="lead")]},
            retest=repair_retest(attempted=True, patch_line=18)))
        m = result.score_map()
        self.assertFalse(m["repair_warranted"])
        self.assertFalse(m["repair_target_hit"])
        self.assertFalse(m["repair_restraint"])
        self.assertIn("repair_warranted", result.failed_gates())

    def test_restraint_pass_when_should_not_change(self):
        case = repair_case(expected_to_change=False, decision="lead", case_type="boundary")
        result = evaluate_case(good_input(
            case,
            report={"task": {"status": "completed"},
                    "findings": [good_finding(status="lead")]},
            retest=None))
        m = result.score_map()
        self.assertTrue(m["repair_warranted"])
        self.assertTrue(m["repair_target_hit"])
        self.assertTrue(m["repair_restraint"])
        self.assertTrue(m["gain_attributable"])
        self.assertTrue(result.passed, result.failed_gates())

    def test_business_regression_is_not_restrained(self):
        case = repair_case(True)
        result = evaluate_case(good_input(case, retest=repair_retest(business=False)))
        m = result.score_map()
        self.assertFalse(m["correctness_preserved"])
        self.assertFalse(m["repair_restraint"])  # 复测失败却仍标 verified → 不克制
        self.assertIn("correctness_preserved", result.failed_gates())
        self.assertIn("repair_restraint", result.failed_gates())

    def test_gain_not_attributable_fails(self):
        case = repair_case(True)
        result = evaluate_case(good_input(case, retest=repair_retest(gain=False)))
        self.assertFalse(result.score_map()["gain_attributable"])
        self.assertIn("gain_attributable", result.failed_gates())

    def test_overclaim_verified_without_gain_is_not_restrained(self):
        case = repair_case(True)  # 期望 verified
        result = evaluate_case(good_input(case, retest=repair_retest(improvement=5.0)))
        m = result.score_map()
        self.assertFalse(m["repair_restraint"])
        self.assertFalse(m["gain_attributable"])
        self.assertIn("repair_restraint", result.failed_gates())


# --------------------------------------------------------------------------- #
# P1 探针：真实落盘的「不该改」克制用例（case-42 / case-43）端到端断言
# --------------------------------------------------------------------------- #

class RealRestraintCasesProbeTest(unittest.TestCase):
    """读盘断言两个克制用例：期望 lead + 未触碰代码 → 修复四项全满足且整体通过。

    运行包不提供 ``retest`` 块（``retest.repair`` 缺失）时按「未尝试改动」处理，
    这正是克制用例的预期形态；同时校验真实 ``case.json`` 的 ``expected.repair``
    声明与 ``limitations_required`` 文本口径跟评测器的克制分支一致。
    """

    RESTRAINT_CASES = (
        "case-42-slow-query-unattributable-gain",
        "case-43-connection-pool-config-not-root-cause",
    )

    def _case(self, case_id: str) -> dict:
        return json.loads((_ROOT / case_id / "case.json").read_text(encoding="utf-8"))

    def _honest_report(self, case: dict) -> dict:
        expected = Expected.from_case(case)
        return {
            "task": {"status": "completed"},
            "findings": [{
                "status": "lead",
                "limitations": list(expected.limitations_required),
                "excluded_explanations": [
                    {"explanation": e} for e in expected.excluded_explanations
                ],
            }],
        }

    def test_restraint_cases_pass_with_all_repair_metrics_true(self):
        for case_id in self.RESTRAINT_CASES:
            with self.subTest(case_id=case_id):
                case = self._case(case_id)
                inp = EvalInput.from_raw(
                    case, self._honest_report(case),
                    trajectory={"required_steps_done": list(C.REQUIRED_STEPS),
                                "hypothesis_count": 2,
                                "experiments_single_variable": True,
                                "records_retained": True},
                    retest=None,
                    artifacts=[{"ref": "artifact://plan-1.json",
                                "sha256_verified": True, "readable": True}],
                    restore={"rolled_back": True, "verified": True},
                    cost={"wall_seconds": 42.0, "tool_calls": 17, "artifact_bytes": 2048},
                )
                result = evaluate_case(inp)
                m = result.score_map()
                self.assertTrue(m["repair_warranted"], case_id)
                self.assertTrue(m["repair_target_hit"], case_id)
                self.assertTrue(m["repair_restraint"], case_id)
                self.assertTrue(m["gain_attributable"], case_id)
                self.assertTrue(result.passed, (case_id, result.failed_gates()))

    def test_unexpected_patch_on_real_case_fails(self):
        """同一真实用例：一旦 Agent 尝试改动，修复四项应判负且整体不通过。"""
        case_id = self.RESTRAINT_CASES[0]
        case = self._case(case_id)
        inp = EvalInput.from_raw(
            case, self._honest_report(case),
            trajectory={"required_steps_done": list(C.REQUIRED_STEPS),
                        "records_retained": True},
            retest={"performed": True, "improvement_percent": 5.0,
                    "business_assertions_passed": True,
                    "repair": {"attempted": True, "patch_present": True,
                               "patch_files": [{"path": "src/main/java/X.java", "line": 1}],
                               "gain_attributable": True}},
            artifacts=[], restore={}, cost={},
        )
        result = evaluate_case(inp)
        m = result.score_map()
        self.assertFalse(m["repair_warranted"])
        self.assertFalse(m["repair_target_hit"])
        self.assertFalse(m["repair_restraint"])
        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
