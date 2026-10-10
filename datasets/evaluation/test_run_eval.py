#!/usr/bin/env python3
"""``evaluation/run_eval.py`` 的单元测试：聚焦基线复现性的两个口径。

对应《Agent 评估方法》第三步与《数据集结构规范》验收要求：

- **验收口径**（≤ 25%）：用例入库时的硬性要求，与 Agent 侧 ``MeasurementPolicy`` 对齐；
- **运行 / 复测口径**（≤ 10%）：单次评估运行当场采集的基线是否可复现。

两者是各自命名的独立概念，不得混用。运行：

    python evaluation/test_run_eval.py
    python -m unittest discover -s evaluation -p "test_*.py"
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import run_eval as R  # noqa: E402


class BaselineThresholdTest(unittest.TestCase):
    """两个阈值常量与 ``baseline_stats`` / ``acceptance_reproducible`` 的语义。"""

    def test_two_named_thresholds_are_distinct(self):
        self.assertEqual(R.ACCEPTANCE_DISPERSION_THRESHOLD, 0.25)
        self.assertEqual(R.RETEST_DISPERSION_THRESHOLD, 0.10)
        # 复测口径更严：单次运行的采样噪声直接决定判定可靠性
        self.assertLess(R.RETEST_DISPERSION_THRESHOLD, R.ACCEPTANCE_DISPERSION_THRESHOLD)

    def test_default_baseline_uses_retest_threshold(self):
        # (118-100)/102 ≈ 0.176：过验收口径、不过复测口径 → 证明两口径确为两个概念
        mid = [100.0, 118.0, 102.0]
        self.assertFalse(R.baseline_stats(mid)["reproducible"])
        self.assertTrue(R.acceptance_reproducible(mid)["reproducible"])

    def test_stable_and_noisy_baselines(self):
        self.assertTrue(R.baseline_stats([12.1, 11.8, 12.4])["reproducible"])
        self.assertFalse(R.baseline_stats([9.1, 15.4, 8.7])["reproducible"])
        # 波动 0.736 连验收口径都过不了
        self.assertFalse(R.acceptance_reproducible([9.1, 15.4, 8.7])["reproducible"])

    def test_min_samples_gate(self):
        stats = R.baseline_stats([1.0, 2.0])
        self.assertEqual(stats["samples"], 2)
        self.assertFalse(stats["meets_min_samples"])
        self.assertFalse(stats["reproducible"])
        # 样本不足时，验收口径同样不通过
        self.assertFalse(R.acceptance_reproducible([1.0, 2.0])["reproducible"])

    def test_empty_baseline_is_safe(self):
        for stats in (R.baseline_stats([]), R.acceptance_reproducible([])):
            self.assertEqual(stats["samples"], 0)
            self.assertIsNone(stats["median_ms"])
            self.assertIsNone(stats["relative_dispersion"])
            self.assertFalse(stats["meets_min_samples"])
            self.assertFalse(stats["reproducible"])

    def test_retest_boundary_is_inclusive(self):
        # 相对离散度恰为 0.10：取「≤」应判可复现
        stats = R.baseline_stats([100.0, 110.0, 100.0])
        self.assertAlmostEqual(stats["relative_dispersion"], 0.10)
        self.assertTrue(stats["reproducible"])

    def test_acceptance_boundary_is_inclusive(self):
        stats = R.acceptance_reproducible([100.0, 125.0, 100.0])
        self.assertAlmostEqual(stats["relative_dispersion"], 0.25)
        self.assertTrue(stats["reproducible"])

    def test_report_carries_both_thresholds(self):
        bundles, cases = R._sample_bundles()
        results = []
        for case in cases:
            bundle = bundles[case["case_id"]]
            results.append(R.evaluate_case(R.EvalInput.from_raw(
                case, bundle["report"], trajectory=bundle.get("trajectory"),
                retest=bundle.get("retest"), artifacts=bundle.get("artifacts") or (),
                restore=bundle.get("restore"), cost=bundle.get("cost"))))
        md = R.render_markdown({
            "manifest": {"generated_at": "x", "evaluator_hash": "0" * 64},
            "thresholds": {
                "acceptance_dispersion": R.ACCEPTANCE_DISPERSION_THRESHOLD,
                "retest_dispersion": R.RETEST_DISPERSION_THRESHOLD,
                "baseline_min_samples": R.BASELINE_MIN_SAMPLES,
            },
            "schema_validation": {"total": 0, "failed": [], "errors": {}},
            "global": {"cases_evaluated": len(results), "cases_missing_bundle": [],
                       "all_cases_passed": True, "false_verified_count": 0,
                       "false_verified_rate": 0.0, "gate_passed": True,
                       "overall_passed": True},
            "cases": [r.to_dict() for r in results],
            "aggregate": R.aggregate(results),
        })
        self.assertIn("验收 ≤ 25%", md)
        self.assertIn("复测 ≤ 10%", md)

    def test_only_bundled_skips_unbundled_cases(self):
        """strict：缺包用例判为缺失、整轮不通过；only_bundled：跳过、整轮通过。"""
        import json
        import tempfile
        from pathlib import Path

        bundles, cases = R._sample_bundles()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for case in cases:
                case_dir = root / case["case_id"]
                case_dir.mkdir()
                (case_dir / "case.json").write_text(
                    json.dumps(case), encoding="utf-8")
            schema_dir = root / "_schema"
            schema_dir.mkdir()
            real_schema = Path(_HERE).parent / "_schema" / "case.schema.json"
            (schema_dir / "case.schema.json").write_text(
                real_schema.read_text(encoding="utf-8"), encoding="utf-8")
            runs = root / "runs"
            runs.mkdir()
            first = cases[0]["case_id"]
            (runs / f"{first}.json").write_text(
                json.dumps(bundles[first]), encoding="utf-8")
            rest = [c["case_id"] for c in cases[1:]]

            strict = R.run(runs, root / "out", cases_root=root)
            self.assertEqual(strict["global"]["cases_missing_bundle"], rest)
            self.assertEqual(strict["global"]["cases_skipped_no_bundle"], [])
            self.assertFalse(strict["global"]["overall_passed"])

            lenient = R.run(runs, root / "out", cases_root=root, only_bundled=True)
            self.assertEqual(lenient["global"]["cases_missing_bundle"], [])
            self.assertEqual(lenient["global"]["cases_skipped_no_bundle"], rest)
            self.assertEqual(lenient["global"]["cases_evaluated"], 1)
            self.assertTrue(lenient["global"]["overall_passed"])


class MultiRunAverageTest(unittest.TestCase):
    """单用例多次运行取平均：数值取均值、``false_verified`` 取或、闸门取「与」。

    单次运行（运行包无 ``runs``）必须与原行为逐位一致；多次运行时把 N 次评测结果
    聚合为一条用例结果，见 ``run_eval.merge_case_results``。
    """

    def _write_cases_root(self, root):
        import json
        from pathlib import Path
        bundles, cases = R._sample_bundles()
        for case in cases:
            case_dir = root / case["case_id"]
            case_dir.mkdir()
            (case_dir / "case.json").write_text(json.dumps(case), encoding="utf-8")
        schema_dir = root / "_schema"
        schema_dir.mkdir()
        real_schema = Path(_HERE).parent / "_schema" / "case.schema.json"
        (schema_dir / "case.schema.json").write_text(
            real_schema.read_text(encoding="utf-8"), encoding="utf-8")
        return bundles, cases

    def _evaluate(self, case, report, bundle):
        return R.evaluate_case(R.EvalInput.from_raw(
            case, report, trajectory=bundle.get("trajectory"),
            retest=bundle.get("retest"), artifacts=bundle.get("artifacts") or (),
            restore=bundle.get("restore"), cost=bundle.get("cost")))

    def test_single_bundle_counts_as_one_run(self):
        bundles, cases = R._sample_bundles()
        case = cases[0]
        bundle = bundles[case["case_id"]]
        # 无 runs → 整包视为 1 次运行
        self.assertEqual(R._case_runs(bundle), [bundle])
        good = self._evaluate(case, bundle["report"], bundle)
        # 单次运行原样返回，保证金标准逐位不变
        self.assertIs(R.merge_case_results([good]), good)

    def test_identical_runs_keep_score_and_total(self):
        bundles, cases = R._sample_bundles()
        case = cases[0]
        bundle = bundles[case["case_id"]]
        good = self._evaluate(case, bundle["report"], bundle)
        merged = R.merge_case_results([good, good, good])
        self.assertEqual(merged.reward["total"], good.reward["total"])
        self.assertEqual(merged.reward["group_scores"], good.reward["group_scores"])
        self.assertTrue(merged.passed)

    def test_numeric_metrics_are_averaged(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundles, cases = self._write_cases_root(root)
            case = cases[0]
            base = bundles[case["case_id"]]
            run_a = {k: v for k, v in base.items() if k != "baseline"}
            run_b = json.loads(json.dumps(run_a))
            run_b["cost"] = {"wall_seconds": 90.0, "tool_calls": 30, "artifact_bytes": 4096}
            bundle = {"baseline": base["baseline"], "runs": [run_a, run_b, run_a]}
            runs = root / "runs"
            runs.mkdir()
            (runs / f"{case['case_id']}.json").write_text(
                json.dumps(bundle), encoding="utf-8")

            report = R.run(runs, root / "out", cases_root=root, only_bundled=True)

        entry = report["cases"][0]
        self.assertEqual(entry["repeats"], 3)
        self.assertEqual(len(entry["repeat_totals"]), 3)
        scores = {s["name"]: s["value"] for s in entry["scores"]}
        self.assertAlmostEqual(scores["wall_seconds"], (41.0 + 90.0 + 41.0) / 3, places=4)
        self.assertAlmostEqual(scores["tool_calls"], (16 + 30 + 16) / 3, places=4)
        # 多次运行的成本评估块取均值
        self.assertEqual(entry["reward"]["cost"]["cost_score"], 1.0)
        self.assertEqual(report["global"]["repeats_total"], 3)

    def test_false_verified_in_any_run_triggers(self):
        bundles, cases = R._sample_bundles()
        case = cases[0]
        bundle = bundles[case["case_id"]]
        good = self._evaluate(case, bundle["report"], bundle)
        self.assertFalse(good.score_map()["false_verified"])

        bad_case = dict(case)
        bad_case["expected"] = dict(case["expected"], decision="lead")
        bad = self._evaluate(bad_case, bundle["report"], bundle)
        self.assertTrue(bad.score_map()["false_verified"])

        merged = R.merge_case_results([good, bad])
        # 任一次误验证 → 聚合后仍判误验证且整例不通过（零容忍）
        self.assertTrue(merged.score_map()["false_verified"])
        self.assertFalse(merged.passed)
        self.assertEqual(merged.case_id, good.case_id)


class ReservedDirTest(unittest.TestCase):
    """扫描根目录时必须与 ``tools/validate_cases.py`` 同口径：跳过保留目录。

    否则 ``_template/case.json`` 会被当作真实用例计入 ``schema_validation.total``
    与 ``cases_skipped_no_bundle``，造成统计虚高。
    """

    def test_reserved_dirs_are_not_discovered(self):
        import json
        import tempfile
        from pathlib import Path

        _, cases = R._sample_bundles()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            real = root / cases[0]["case_id"]
            real.mkdir()
            (real / "case.json").write_text(
                json.dumps(cases[0]), encoding="utf-8")
            for reserved in ("_template", "_schema", "docs", "tools", "evaluation"):
                d = root / reserved
                d.mkdir()
                (d / "case.json").write_text(
                    json.dumps(cases[0]), encoding="utf-8")

            found = [p.parent.name for p in R._iter_case_files(root)]
            self.assertEqual(found, [cases[0]["case_id"]])
            self.assertEqual(
                list(R._load_cases(root)),
                [cases[0]["case_id"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
