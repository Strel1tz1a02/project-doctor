#!/usr/bin/env python3
"""金标准运行包回归测试（golden run-bundle regression）。

把 `evaluation/fixtures/run-bundle/` 下十四份冻结的运行包（覆盖全部 14 个用例，
含 normal / boundary / failure 三类）喂给完整的七步打分流程，断言其产出报告的关键
数值与结构。任何对指标计算 / 聚合 / 报告渲染的无意改动都会在这里被拦截，从而保证
**评估结论可复现、可回溯**。

约定：
- 只使用标准库（unittest + tempfile），不依赖 pytest；
- 只在临时目录落盘，不污染仓库；
- 不调用被测 Agent（本测试只消费运行包，符合“数据集建设与评价方法”范围）。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import run_eval as R  # noqa: E402

FIXTURES = _HERE / "fixtures" / "run-bundle"

# --------------------------------------------------------------------------- #
# 金标准数值（冻结自 evaluation/fixtures/run-bundle 的当前打分结果）
# --------------------------------------------------------------------------- #

GOLDEN_CASES_EVALUATED = 14
GOLDEN_FALSE_VERIFIED = 0

GOLDEN_TOTALS = {
    "case-01-slow-query-fullscan": 1.0,
    "case-02-slow-query-composite": 0.7964,
    "case-03-slow-query-unreproducible": 0.965,
    "case-04-slow-query-user-index": 1.0,
    "case-05-slow-query-skewed-status": 0.7964,
    "case-06-slow-query-undersized": 0.965,
    "case-07-n-plus-one-order-user": 0.7964,
    "case-08-deep-pagination-large-offset": 0.7964,
    "case-09-connection-pool-leak": 0.7964,
    "case-10-large-response-unbounded": 0.7964,
    "case-11-connection-setup-per-request": 0.7964,
    "case-12-excessive-logging-sync-debug": 0.7964,
    "case-13-thread-pool-no-verifiable-defect": 0.965,
    "case-14-config-regression-pool-size": 0.7964,
}
GOLDEN_MEAN_TOTAL = 0.8616

GOLDEN_PROFILES = {
    "case-01-slow-query-fullscan": "normal_single",
    "case-02-slow-query-composite": "boundary_composite",
    "case-03-slow-query-unreproducible": "failure_honesty",
    "case-04-slow-query-user-index": "normal_single",
    "case-05-slow-query-skewed-status": "boundary_composite",
    "case-06-slow-query-undersized": "failure_honesty",
    "case-07-n-plus-one-order-user": "boundary_composite",
    "case-08-deep-pagination-large-offset": "boundary_composite",
    "case-09-connection-pool-leak": "boundary_composite",
    "case-10-large-response-unbounded": "boundary_composite",
    "case-11-connection-setup-per-request": "boundary_composite",
    "case-12-excessive-logging-sync-debug": "boundary_composite",
    "case-13-thread-pool-no-verifiable-defect": "failure_honesty",
    "case-14-config-regression-pool-size": "boundary_composite",
}

# E2：成本层已纳入分组得分与总分；八份 fixture 均在各自用例类型的预算内。
GOLDEN_GROUP_SCORES = {
    "case-01-slow-query-fullscan": {
        "conclusion": 1.0, "evidence": 1.0, "process": 1.0, "cost": 1.0,
    },
    "case-02-slow-query-composite": {
        "conclusion": 0.7143, "evidence": 1.0, "process": 0.5, "cost": 1.0,
    },
    "case-03-slow-query-unreproducible": {
        "conclusion": 1.0, "evidence": 1.0, "process": 0.9, "cost": 1.0,
    },
    "case-04-slow-query-user-index": {
        "conclusion": 1.0, "evidence": 1.0, "process": 1.0, "cost": 1.0,
    },
    "case-05-slow-query-skewed-status": {
        "conclusion": 0.7143, "evidence": 1.0, "process": 0.5, "cost": 1.0,
    },
    "case-06-slow-query-undersized": {
        "conclusion": 1.0, "evidence": 1.0, "process": 0.9, "cost": 1.0,
    },
    "case-07-n-plus-one-order-user": {
        "conclusion": 0.7143, "evidence": 1.0, "process": 0.5, "cost": 1.0,
    },
    "case-08-deep-pagination-large-offset": {
        "conclusion": 0.7143, "evidence": 1.0, "process": 0.5, "cost": 1.0,
    },
    "case-09-connection-pool-leak": {
        "conclusion": 0.7143, "evidence": 1.0, "process": 0.5, "cost": 1.0,
    },
    "case-10-large-response-unbounded": {
        "conclusion": 0.7143, "evidence": 1.0, "process": 0.5, "cost": 1.0,
    },
    "case-11-connection-setup-per-request": {
        "conclusion": 0.7143, "evidence": 1.0, "process": 0.5, "cost": 1.0,
    },
    "case-12-excessive-logging-sync-debug": {
        "conclusion": 0.7143, "evidence": 1.0, "process": 0.5, "cost": 1.0,
    },
    "case-13-thread-pool-no-verifiable-defect": {
        "conclusion": 1.0, "evidence": 1.0, "process": 0.9, "cost": 1.0,
    },
    "case-14-config-regression-pool-size": {
        "conclusion": 0.7143, "evidence": 1.0, "process": 0.5, "cost": 1.0,
    },
}
GOLDEN_COST_SCORE = {
    "case-01-slow-query-fullscan": 1.0,
    "case-02-slow-query-composite": 1.0,
    "case-03-slow-query-unreproducible": 1.0,
    "case-04-slow-query-user-index": 1.0,
    "case-05-slow-query-skewed-status": 1.0,
    "case-06-slow-query-undersized": 1.0,
    "case-07-n-plus-one-order-user": 1.0,
    "case-08-deep-pagination-large-offset": 1.0,
    "case-09-connection-pool-leak": 1.0,
    "case-10-large-response-unbounded": 1.0,
    "case-11-connection-setup-per-request": 1.0,
    "case-12-excessive-logging-sync-debug": 1.0,
    "case-13-thread-pool-no-verifiable-defect": 1.0,
    "case-14-config-regression-pool-size": 1.0,
}

# 失败用例的基线本就允许波动：其不可复现不作为判负依据。
GOLDEN_BASELINE_REPRODUCIBLE = {
    "case-01-slow-query-fullscan": True,
    "case-02-slow-query-composite": True,
    "case-03-slow-query-unreproducible": False,
    "case-04-slow-query-user-index": True,
    "case-05-slow-query-skewed-status": True,
    "case-06-slow-query-undersized": True,
    "case-07-n-plus-one-order-user": True,
    "case-08-deep-pagination-large-offset": True,
    "case-09-connection-pool-leak": True,
    "case-10-large-response-unbounded": True,
    "case-11-connection-setup-per-request": True,
    "case-12-excessive-logging-sync-debug": True,
    "case-13-thread-pool-no-verifiable-defect": False,
    "case-14-config-regression-pool-size": True,
}


class GoldenRunBundleTest(unittest.TestCase):
    """端到端回归：fixtures 运行包 → 报告，一次性运行、逐项断言。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="golden-bundle-")
        # only_bundled：数据集会持续新增用例，而金标准 fixture 固定；
        # 只评估有运行包的用例，使回归不受数据集扩充影响。
        cls.report = R.run(FIXTURES, Path(cls._tmp.name), only_bundled=True)
        cls.by_id = {c["case_id"]: c for c in cls.report["cases"]}
        cls.markdown = (Path(cls._tmp.name) / "report.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # ---- 前置：fixtures 必须齐全 ------------------------------------------ #

    def test_fixtures_exist(self) -> None:
        for case_id in GOLDEN_TOTALS:
            self.assertTrue((FIXTURES / f"{case_id}.json").is_file(),
                            f"缺少运行包 fixture：{case_id}.json")

    # ---- 全局门槛 --------------------------------------------------------- #

    def test_global_gate_passed(self) -> None:
        gl = self.report["global"]
        self.assertEqual(gl["cases_evaluated"], GOLDEN_CASES_EVALUATED)
        self.assertEqual(gl["cases_missing_bundle"], [])
        self.assertTrue(gl["all_cases_passed"])
        self.assertTrue(gl["gate_passed"])
        self.assertTrue(gl["overall_passed"])

    def test_unbundled_dataset_cases_are_skipped_not_missing(self) -> None:
        """数据集扩充出的、无金标准运行包的用例应被跳过，而非判定为缺包。"""
        gl = self.report["global"]
        # 跳过的用例集合与已评估集合互不相交，且跳过项不出现在 cases 列表里
        skipped = set(gl["cases_skipped_no_bundle"])
        self.assertFalse(skipped & set(self.by_id))
        for case_id in skipped:
            self.assertNotIn(case_id, gl["cases_missing_bundle"])

    def test_no_false_verified(self) -> None:
        self.assertEqual(self.report["global"]["false_verified_count"],
                         GOLDEN_FALSE_VERIFIED)
        self.assertEqual(self.report["aggregate"]["false_verified"]["count"],
                         GOLDEN_FALSE_VERIFIED)

    def test_all_cases_present_and_passed(self) -> None:
        self.assertEqual(set(self.by_id), set(GOLDEN_TOTALS))
        for case_id, case in self.by_id.items():
            self.assertTrue(case["passed"], f"{case_id} 未通过：{case['failed_gates']}")
            self.assertEqual(case["failed_gates"], [])

    # ---- 总分（E1 权重聚合） --------------------------------------------- #

    def test_case_reward_totals_match_golden(self) -> None:
        for case_id, expected in GOLDEN_TOTALS.items():
            reward = self.by_id[case_id]["reward"]
            self.assertIsNotNone(reward, f"{case_id} 缺少 reward 块")
            self.assertAlmostEqual(reward["total"], expected, places=4,
                                   msg=f"{case_id} 总分偏离金标准")
            # 硬闸门通过时 weighted_total 应等于 total
            self.assertTrue(reward["hard_gate_passed"])
            self.assertAlmostEqual(reward["total"], reward["weighted_total"], places=4)

    def test_reward_profiles_match_case_types(self) -> None:
        for case_id, profile in GOLDEN_PROFILES.items():
            self.assertEqual(self.by_id[case_id]["reward"]["reward_profile"], profile)

    def test_mean_total_matches_golden(self) -> None:
        self.assertAlmostEqual(self.report["aggregate"]["reward"]["mean_total"],
                               GOLDEN_MEAN_TOTAL, places=4)
        by_type = self.report["aggregate"]["reward"]["by_case_type"]
        self.assertEqual(set(by_type), {"normal", "boundary", "failure"})

    # ---- 成本层（E2） ---------------------------------------------------- #

    def test_cost_participates_in_group_scores(self) -> None:
        for case_id, expected in GOLDEN_GROUP_SCORES.items():
            group_scores = self.by_id[case_id]["reward"]["group_scores"]
            self.assertIn("cost", group_scores, f"{case_id} 分组得分缺少 cost")
            for group, value in expected.items():
                self.assertAlmostEqual(group_scores[group], value, places=4,
                                       msg=f"{case_id} 分组得分 {group} 偏离金标准")

    def test_cost_block_matches_golden(self) -> None:
        for case_id, expected in GOLDEN_COST_SCORE.items():
            cost = self.by_id[case_id]["reward"]["cost"]
            self.assertAlmostEqual(cost["cost_score"], expected, places=4)
            self.assertEqual(cost["exceeded"], [])
            self.assertEqual(set(cost["details"]),
                             {"wall_seconds", "tool_calls", "artifact_bytes"})
            self.assertEqual(set(cost["budget"]),
                             {"wall_seconds", "tool_calls", "artifact_bytes"})

    def test_aggregate_cost_fields(self) -> None:
        cost = self.report["aggregate"]["cost"]
        self.assertAlmostEqual(cost["cost_score_mean"], 1.0, places=4)
        self.assertEqual(cost["budget_exceeded_count"], 0)
        self.assertEqual(cost["budget_exceeded_cases"], [])

    # ---- 双口径基线（E3） ----------------------------------------------- #

    def test_thresholds_block_carries_both_calibers(self) -> None:
        th = self.report["thresholds"]
        self.assertEqual(th["acceptance_dispersion"], 0.25)
        self.assertEqual(th["retest_dispersion"], 0.10)
        self.assertEqual(th["baseline_min_samples"], 3)
        self.assertLess(th["retest_dispersion"], th["acceptance_dispersion"])

    def test_thresholds_block_carries_cost_budgets(self) -> None:
        budgets = self.report["thresholds"]["cost_budgets"]
        self.assertEqual(set(budgets), {"normal", "boundary", "failure"})
        for case_type, budget in budgets.items():
            self.assertEqual(set(budget),
                             {"wall_seconds", "tool_calls", "artifact_bytes"})
            for value in budget.values():
                self.assertGreater(value, 0)

    def test_failure_case_baseline_may_be_nonreproducible(self) -> None:
        for case_id, expected in GOLDEN_BASELINE_REPRODUCIBLE.items():
            self.assertIs(self.by_id[case_id]["baseline"]["reproducible"], expected,
                          f"{case_id} 基线可复现性偏离金标准")
        # 关键：复测口径不可复现的失败用例仍应判为通过（不以其为判负依据）
        self.assertTrue(self.by_id["case-03-slow-query-unreproducible"]["passed"])

    # ---- 报告渲染 --------------------------------------------------------- #

    def test_markdown_renders_thresholds_and_totals(self) -> None:
        self.assertIn("验收 ≤ 25%", self.markdown)
        self.assertIn("复测 ≤ 10%", self.markdown)
        self.assertIn("| 总分 |", self.markdown)  # 逐用例表含总分列
        for case_id, expected in GOLDEN_TOTALS.items():
            self.assertIn(case_id, self.markdown)
        # 平均总分一行存在
        self.assertIn("全用例平均总分", self.markdown)

    def test_report_json_is_round_trippable(self) -> None:
        with (Path(self._tmp.name) / "report.json").open("r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded["global"]["overall_passed"], True)
        self.assertEqual(len(loaded["cases"]), GOLDEN_CASES_EVALUATED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
