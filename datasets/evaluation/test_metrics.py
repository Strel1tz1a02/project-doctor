#!/usr/bin/env python3
"""``evaluation`` 包的单元测试（纯标准库 unittest）。

覆盖 ``scores.py``（评分数据模型）、``contract.py``（输出契约视图）与 ``metrics.py``
（四层指标计算 + 三类用例硬闸门）。运行：

    python evaluation/test_metrics.py
    python -m unittest discover -s evaluation -p "test_*.py"
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

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
    def test_registry_has_28_metrics(self):
        # 21 项用例级指标 + 7 项步骤级指标（group="step"，D4 只作归因不进总分）。
        # 用例级含 4 项修复能力指标（repair_warranted / repair_target_hit /
        # repair_restraint / gain_attributable），仅当用例声明 expected.repair 时才产出取值。
        self.assertEqual(len(S.METRIC_DEFINITIONS), 28)
        self.assertEqual(len(S.STEP_METRICS), 7)

    def test_applicability_invariants(self):
        normal = {d.name for d in S.definitions_for(CaseType.NORMAL)}
        boundary = {d.name for d in S.definitions_for(CaseType.BOUNDARY)}
        failure = {d.name for d in S.definitions_for(CaseType.FAILURE)}

        self.assertNotIn("honesty", normal)
        self.assertNotIn("honesty", boundary)
        self.assertIn("honesty", failure)
        # 三类用例都追加了 7 项步骤级指标：19+7 / 20+7 / 8+7；
        # normal/boundary 另含 4 项修复能力指标（不进 failure）。
        self.assertEqual(len(normal), 26)
        self.assertEqual(len(boundary), 27)
        self.assertEqual(len(failure), 15)
        self.assertIn("limitation_declared", boundary)
        self.assertNotIn("limitation_declared", normal)
        self.assertNotIn("root_cause_recall", failure)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
