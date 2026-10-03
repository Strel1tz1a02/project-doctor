#!/usr/bin/env python3
"""guard_sut_separation 的单元测试（纯标准库 unittest）。

    python -m unittest tools.test_guard_sut_separation -v
    python tools/test_guard_sut_separation.py -v

覆盖：金标准标记扫描（含词边界正确性）、二进制跳过、scan_sut 对
「SUT 引用金标准 / SUT 干净 / SUT 目录缺失」的识别，最后对真实 SUT 目录
（若存在）做一次端到端断言。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guard_sut_separation as G  # noqa: E402


class PureFunctionsTest(unittest.TestCase):
    def test_scan_text_detects_datasets_and_case_json(self):
        text = "from pathlib import Path\npath = Path('datasets/case-01/case.json')\n"
        hits = dict((token, line) for line, token in G.scan_text(text))
        self.assertIn("datasets", hits)
        self.assertIn("case.json", hits)

    def test_scan_text_detects_ground_truth_and_root_cause_ids(self):
        text = "GROUND_TRUTH = {'defect': 1}\nroot_cause_ids = ['idx-missing']\n"
        tokens = {token for _, token in G.scan_text(text)}
        self.assertIn("ground truth", tokens)
        self.assertIn("root_cause_ids", tokens)

    def test_scan_text_ignores_legit_dataset_identifiers(self):
        # SUT 合法的 DatasetProfile / dataset.py 不应被误伤（词边界）
        self.assertEqual(G.scan_text("from project_doctor.models.dataset import DatasetProfile"), [])
        self.assertEqual(G.scan_text("class DatasetProfile: ..."), [])

    def test_scan_text_clean(self):
        self.assertEqual(G.scan_text("def diagnose(request): return None"), [])

    def test_read_text_safely_skips_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "module.pyc"
            binary.write_bytes(b"\x00\x01\x02datasets\x03")
            self.assertIsNone(G.read_text_safely(binary))


class ScanSutTest(unittest.TestCase):
    def test_flagged_when_sut_reads_ground_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            sut = Path(tmp) / "src"
            (sut / "pkg").mkdir(parents=True)
            (sut / "pkg" / "bad.py").write_text(
                "import json\nTRUTH = json.load(open('../datasets/case-01/case.json'))\n",
                encoding="utf-8",
            )
            findings = G.scan_sut(sut)
            self.assertTrue(findings)
            self.assertEqual({f.token for f in findings}, {"datasets", "case.json"})

    def test_clean_sut_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            sut = Path(tmp) / "src"
            (sut / "pkg").mkdir(parents=True)
            (sut / "pkg" / "ok.py").write_text("def run(): return 42\n", encoding="utf-8")
            self.assertEqual(G.scan_sut(sut), [])

    def test_missing_sut_dir_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(G.scan_sut(Path(tmp) / "does-not-exist"), [])

    def test_skips_pycache(self):
        with tempfile.TemporaryDirectory() as tmp:
            sut = Path(tmp) / "src"
            (sut / "__pycache__").mkdir(parents=True)
            (sut / "__pycache__" / "cached.py").write_text("datasets", encoding="utf-8")
            self.assertEqual(G.scan_sut(sut), [])


class CliTest(unittest.TestCase):
    def test_cli_returns_one_on_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            sut = Path(tmp) / "src"
            sut.mkdir(parents=True)
            (sut / "bad.py").write_text("open('case.json')", encoding="utf-8")
            self.assertEqual(G.main(["--sut", str(sut)]), 1)

    def test_cli_returns_zero_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            sut = Path(tmp) / "src"
            sut.mkdir(parents=True)
            (sut / "ok.py").write_text("x = 1", encoding="utf-8")
            self.assertEqual(G.main(["--sut", str(sut)]), 0)

    def test_cli_skips_when_sut_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(G.main(["--sut", str(Path(tmp) / "absent")]), 0)


class RealRepoTest(unittest.TestCase):
    def test_real_sut_is_isolated_if_present(self):
        # 并入仓库后 src/ 存在 → 断言 SUT 未引用金标准；独立模式下自动跳过。
        self.assertEqual(G.scan_sut(G.DEFAULT_SUT_DIR), [])


if __name__ == "__main__":
    unittest.main()
