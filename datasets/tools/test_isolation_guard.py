#!/usr/bin/env python3
"""isolation_guard 的单元测试（纯标准库 unittest）。

    python -m unittest tools.test_isolation_guard -v
    python tools/test_isolation_guard.py -v

覆盖：保留名判定、越界符号链接判定、文本标记扫描、二进制跳过，
以及 scan_case 对敏感文件 / 答案引用 / 缺失 project / 版本库目录的识别，
最后对仓库内真实数据单元做一次端到端隔离断言。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation_guard as G  # noqa: E402


class PureFunctionsTest(unittest.TestCase):
    def test_reserved_names(self):
        for name in ("_schema", "_tmp", "docs", "tools", "evaluation", ".github"):
            self.assertTrue(G.is_reserved_name(name), name)
        for name in ("case-01-slow-query-fullscan", "project", "case02"):
            self.assertFalse(G.is_reserved_name(name), name)

    def test_escapes_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "case-01" / "project"
            (root / "src").mkdir(parents=True)
            inside = root / "src" / "Main.java"
            inside.write_text("x", encoding="utf-8")
            sibling = Path(tmp) / "case-01" / "case.json"
            sibling.write_text("{}", encoding="utf-8")

            self.assertFalse(G.escapes_root(inside, root))
            self.assertFalse(G.escapes_root(root, root))
            self.assertTrue(G.escapes_root(sibling, root))

    def test_scan_text_reports_line_and_token(self):
        text = "line one\nreferences case.json here\nanother _schema mention"
        hits = G.scan_text(text)
        mapping = dict((token, line) for line, token in hits)
        self.assertEqual(mapping.get("case.json"), 2)
        self.assertEqual(mapping.get("_schema"), 3)

    def test_scan_text_clean(self):
        self.assertEqual(G.scan_text("public class Main { }"), [])

    def test_read_text_safely_skips_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "app.class"
            binary.write_bytes(b"\x00\x01\x02\x03case.json")
            self.assertIsNone(G.read_text_safely(binary))
            text = Path(tmp) / "Main.java"
            text.write_text("class Main {}", encoding="utf-8")
            self.assertEqual(G.read_text_safely(text), "class Main {}")


class ScanCaseTest(unittest.TestCase):
    def _make_case(self, tmp: str, with_project: bool = True) -> Path:
        case_dir = Path(tmp) / "case-99-slow-query-sample"
        case_dir.mkdir(parents=True)
        (case_dir / "case.json").write_text('{"case_id": "x"}', encoding="utf-8")
        if with_project:
            project = case_dir / "project"
            (project / "src").mkdir(parents=True)
            (project / "pom.xml").write_text("<project/>", encoding="utf-8")
        return case_dir

    def test_missing_project_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case(tmp, with_project=False)
            findings = G.scan_case(case_dir)
            self.assertTrue(any(f.kind == "missing_project" for f in findings))

    def test_clean_project_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case(tmp)
            (case_dir / "project" / "src" / "Main.java").write_text(
                "class Main { /* normal */ }", encoding="utf-8")
            self.assertEqual(G.scan_case(case_dir), [])

    def test_sensitive_file_inside_project_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case(tmp)
            (case_dir / "project" / "case.json").write_text("{}", encoding="utf-8")
            findings = G.scan_case(case_dir)
            self.assertTrue(any(f.kind == "sensitive_file" for f in findings))

    def test_answer_reference_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case(tmp)
            (case_dir / "project" / "README.md").write_text(
                "生成的答案见 ../case.json", encoding="utf-8")
            findings = G.scan_case(case_dir)
            refs = [f for f in findings if f.kind == "answer_reference"]
            self.assertTrue(refs)
            self.assertIn("case.json", refs[0].detail)

    def test_vcs_dir_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case(tmp)
            (case_dir / "project" / ".git").mkdir()
            findings = G.scan_case(case_dir)
            self.assertTrue(any(f.kind == "vcs_dir" for f in findings))

    def test_symlink_escape_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = self._make_case(tmp)
            outside = Path(tmp) / "secret.txt"
            outside.write_text("hidden", encoding="utf-8")
            link = case_dir / "project" / "leak.txt"
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError):
                self.skipTest("当前平台不允许创建符号链接")
            findings = G.scan_case(case_dir)
            self.assertTrue(any(f.kind == "symlink_escape" for f in findings))


class RealRepoTest(unittest.TestCase):
    """对仓库内真实数据单元做端到端隔离断言。"""

    def test_all_shipped_cases_isolated(self):
        cases, findings = G.scan_all(G.DATASETS_ROOT)
        self.assertTrue(cases, "应至少发现一个数据单元")
        messages = "\n".join(f"{f.case_id}:{f.kind}:{f.path}:{f.detail}" for f in findings)
        self.assertEqual(findings, [], f"真实数据单元存在隔离泄漏：\n{messages}")

    def test_discover_excludes_reserved_dirs(self):
        cases = G.discover_cases(G.DATASETS_ROOT)
        names = {c.name for c in cases}
        self.assertNotIn("docs", names)
        self.assertNotIn("tools", names)
        self.assertNotIn("evaluation", names)
        self.assertNotIn("_schema", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
