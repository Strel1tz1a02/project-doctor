#!/usr/bin/env python3
"""``tools/validate_cases.py`` 的单元测试（纯标准库 unittest）。

运行：
    python -m unittest discover -s tools -p "test_*.py" -v
    python tools/test_validate_cases.py -v
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
DATASETS_ROOT = TOOLS_DIR.parent
FIXTURES_DIR = TOOLS_DIR / "fixtures"
VALID_CASE_PATH = FIXTURES_DIR / "valid_case.json"

# 允许直接运行本文件时导入同目录下的被测模块
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import validate_cases  # noqa: E402


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class ValidatorUnitTests(unittest.TestCase):
    """针对校验器关键字行为的白盒测试。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = validate_cases.load_schema(validate_cases.DEFAULT_SCHEMA_PATH)
        cls.valid_case = _load_json(VALID_CASE_PATH)

    def _errors_for(self, case: dict) -> list[str]:
        return validate_cases.SchemaValidator(self.schema).validate(case)

    # -- 正常路径 ----------------------------------------------------------- #
    def test_valid_case_passes(self) -> None:
        self.assertEqual(self._errors_for(copy.deepcopy(self.valid_case)), [])

    def test_schema_root_is_object(self) -> None:
        self.assertIsInstance(self.schema, dict)
        self.assertEqual(self.schema.get("$id"),
                         "https://project-doctor.local/datasets/case.schema.json")

    # -- json pointer ------------------------------------------------------- #
    def test_resolve_ref_local_pointer(self) -> None:
        node = validate_cases.resolve_ref(self.schema, "#/$defs/code_location")
        self.assertEqual(node["required"], ["path", "line"])

    def test_resolve_ref_rejects_remote(self) -> None:
        with self.assertRaises(ValueError):
            validate_cases.resolve_ref(self.schema, "https://example.com/x.json")

    def test_resolve_ref_missing_path(self) -> None:
        with self.assertRaises(KeyError):
            validate_cases.resolve_ref(self.schema, "#/$defs/does_not_exist")

    # -- 关键字 ------------------------------------------------------------- #
    def test_missing_required_top_level(self) -> None:
        case = copy.deepcopy(self.valid_case)
        del case["case_type"]
        errors = self._errors_for(case)
        self.assertTrue(any("case_type" in e for e in errors), errors)

    def test_bad_enum(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["case_type"] = "smoke"
        errors = self._errors_for(case)
        self.assertTrue(any("允许枚举" in e for e in errors), errors)

    def test_bad_case_id_pattern(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["case_id"] = "CASE_01_bad"
        errors = self._errors_for(case)
        self.assertTrue(any("不匹配正则" in e for e in errors), errors)

    def test_additional_properties_rejected(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["unexpected_field"] = 1
        errors = self._errors_for(case)
        self.assertTrue(any("additionalProperties" in e for e in errors), errors)

    def test_nested_additional_properties_rejected(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["symptom"]["extra"] = "x"
        errors = self._errors_for(case)
        self.assertTrue(any("$.symptom.extra" in e for e in errors), errors)

    def test_code_location_requires_line(self) -> None:
        case = copy.deepcopy(self.valid_case)
        del case["expected"]["code_locations"][0]["line"]
        errors = self._errors_for(case)
        self.assertTrue(any("line" in e and "缺少必填字段" in e for e in errors), errors)

    def test_code_location_line_minimum(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["expected"]["code_locations"][0]["line"] = 0
        errors = self._errors_for(case)
        self.assertTrue(any("应 >= 1" in e for e in errors), errors)

    def test_array_min_items(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["defects"] = []
        errors = self._errors_for(case)
        self.assertTrue(any("元素个数应 >= 1" in e for e in errors), errors)

    def test_row_counts_non_negative(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["dataset_profile"]["row_counts"]["users"] = -1
        errors = self._errors_for(case)
        self.assertTrue(any("应 >= 0" in e for e in errors), errors)

    def test_row_counts_rejects_empty(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["dataset_profile"]["row_counts"] = {}
        errors = self._errors_for(case)
        self.assertTrue(any("字段数应 >= 1" in e for e in errors), errors)

    def test_schema_version_const(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["schema_version"] = "0.2"
        errors = self._errors_for(case)
        self.assertTrue(any("恒等于" in e for e in errors), errors)

    def test_integer_rejects_bool_and_float(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["evaluation"]["timeout_seconds"] = True
        self.assertTrue(self._errors_for(case))
        case["evaluation"]["timeout_seconds"] = 1.5
        self.assertTrue(self._errors_for(case))

    # -- 错误路径定位 ------------------------------------------------------- #
    def test_error_path_is_json_pointer_like(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["defects"][0]["role"] = "primary2"
        errors = self._errors_for(case)
        self.assertTrue(any(e.startswith("$.defects[0].role") for e in errors), errors)

    def test_deep_copy_mutation_does_not_leak(self) -> None:
        case = copy.deepcopy(self.valid_case)
        case["case_type"] = "invalid"
        self._errors_for(case)
        # 原始 fixture 仍然合法
        self.assertEqual(self._errors_for(copy.deepcopy(self.valid_case)), [])


class RepoCaseTests(unittest.TestCase):
    """对仓库内真实 case.json 的端到端校验。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = validate_cases.load_schema(validate_cases.DEFAULT_SCHEMA_PATH)

    def test_all_discovered_cases_valid(self) -> None:
        cases = validate_cases.discover_cases()
        if not cases:
            self.skipTest("仓库中暂无已归档的 case.json")
        failures: list[str] = []
        for case_path in cases:
            errors = validate_cases.validate_file(case_path, self.schema)
            if errors:
                failures.append(f"{case_path}: {errors}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_valid_fixture_array_of_defects_shape(self) -> None:
        # 保证 fixture 自身可被文件级接口读取
        self.assertEqual(
            validate_cases.validate_file(VALID_CASE_PATH, self.schema), []
        )


class ProblemKindEnumTests(unittest.TestCase):
    """锁定 ``problem_kind`` 枚举取值域，防止设计文档与数据集之间无声漂移。

    取值域对齐 ``project-doctor`` 设计文档 ``design/performance-agent-modular-design.md``
    划定的 9 类性能问题；改动枚举时本测试必须同步更新，作为「先改 schema 再补用例」流程的守卫。
    """

    EXPECTED_PROBLEM_KINDS = (
        "slow_query",
        "n_plus_one",
        "connection_pool",
        "deep_pagination",
        "large_response",
        "connection_setup",
        "excessive_logging",
        "thread_pool",
        "config_regression",
    )

    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = validate_cases.load_schema(validate_cases.DEFAULT_SCHEMA_PATH)

    def test_schema_enum_matches_design(self) -> None:
        enum = self.schema["properties"]["problem_kind"]["enum"]
        self.assertEqual(list(enum), list(self.EXPECTED_PROBLEM_KINDS))

    def test_every_case_kind_within_enum(self) -> None:
        enum = set(self.schema["properties"]["problem_kind"]["enum"])
        for case_path in validate_cases.discover_cases():
            data = _load_json(case_path)
            self.assertIn(data["problem_kind"], enum, str(case_path))

    def test_currently_covered_kinds_present(self) -> None:
        enum = set(self.schema["properties"]["problem_kind"]["enum"])
        for kind in ("slow_query", "n_plus_one", "deep_pagination"):
            self.assertIn(kind, enum)


class DiscoveryTests(unittest.TestCase):
    """``discover_cases`` / 保留名过滤行为。"""

    def test_is_reserved_name(self) -> None:
        for name in ("_template", "_schema", "docs", "tools", "evaluation", ".github"):
            self.assertTrue(validate_cases.is_reserved_name(name), name)

    def test_real_case_dirs_not_reserved(self) -> None:
        for name in ("case-01-slow-query-fullscan", "case-06-slow-query-undersized"):
            self.assertFalse(validate_cases.is_reserved_name(name), name)

    def test_discover_cases_skips_reserved_dirs(self) -> None:
        original_root = validate_cases.DATASETS_ROOT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                real = root / "case-01-demo"
                real.mkdir()
                (real / "case.json").write_text("{}", encoding="utf-8")
                # 约定目录：以 "_" 开头（模板）与保留清单（tools）
                for reserved in ("_template", "tools"):
                    d = root / reserved
                    d.mkdir()
                    (d / "case.json").write_text("{}", encoding="utf-8")
                validate_cases.DATASETS_ROOT = root
                found = validate_cases.discover_cases()
        finally:
            validate_cases.DATASETS_ROOT = original_root

        names = [p.parent.name for p in found]
        self.assertEqual(names, ["case-01-demo"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
