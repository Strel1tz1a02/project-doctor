#!/usr/bin/env python3
"""case.json 校验脚本（纯标准库实现，无第三方依赖）。

背景
----
本仓库运行环境只保证有 CPython（>=3.10）标准库，未安装 pydantic / jsonschema，
因此这里实现了一个「聚焦子集」的 JSON Schema (draft 2020-12) 校验器，
只覆盖 ``_schema/case.schema.json`` 实际使用到的关键字：

    $ref / $defs、type（含多类型）、enum、const、
    required、properties、additionalProperties（bool 或 schema）、minProperties、
    items、minItems、minLength、pattern、minimum、maximum

用法
----
    python tools/validate_cases.py                # 校验本目录下所有 */case.json
    python tools/validate_cases.py path/to/case.json [...]
    python tools/validate_cases.py --schema path --quiet --json

退出码
------
    0  全部通过
    1  存在校验失败
    2  用法 / IO / schema 自身错误
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

#: 本文件位于 <Datasets>/tools/validate_cases.py，数据集根即上两级目录
DATASETS_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = DATASETS_ROOT / "_schema" / "case.schema.json"

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    # 注意：Python 中 bool 是 int 的子类，必须显式排除
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


# --------------------------------------------------------------------------- #
# JSON Pointer
# --------------------------------------------------------------------------- #

def resolve_ref(root: Any, ref: str) -> Any:
    """解析本地 JSON Pointer（``#/...``）。不支持远程 / 相对文件引用。"""
    if not ref.startswith("#"):
        raise ValueError(f"仅支持本地引用（以 '#' 开头），收到: {ref!r}")
    pointer = ref[1:]
    if pointer in ("", "/"):
        return root
    node = root
    for raw_token in pointer.lstrip("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict):
            if token not in node:
                raise KeyError(f"引用路径不存在: {ref!r}（在 {token!r} 处中断）")
            node = node[token]
        else:
            raise KeyError(f"引用路径无法继续: {ref!r}（在 {token!r} 处中断）")
    return node


# --------------------------------------------------------------------------- #
# 校验器
# --------------------------------------------------------------------------- #

class SchemaValidator:
    """覆盖本项目所需关键字的 JSON Schema 子集校验器。"""

    MAX_DEPTH = 64

    def __init__(self, schema: dict[str, Any]) -> None:
        self.root = schema
        self.errors: list[str] = []

    # -- 对外入口 ----------------------------------------------------------- #
    def validate(self, instance: Any) -> list[str]:
        self.errors = []
        self._walk(instance, self.root, "$", 0)
        return list(self.errors)

    # -- 内部实现 ----------------------------------------------------------- #
    def _add(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def _walk(self, value: Any, schema: Any, path: str, depth: int) -> None:
        if depth > self.MAX_DEPTH:
            self._add(path, "schema 递归深度超限（可能存在循环引用）")
            return
        if not isinstance(schema, dict):
            return

        # 1) $ref：解析后先按被引用 schema 校验，再合并同级关键字
        if "$ref" in schema:
            target = resolve_ref(self.root, schema["$ref"])
            self._walk(value, target, path, depth + 1)

        # 2) type
        if "type" in schema:
            declared = schema["type"]
            types = [declared] if isinstance(declared, str) else list(declared)
            if not any(_TYPE_CHECKS[t](value) for t in types):
                self._add(path, f"类型应为 {declared!r}，实际为 {type(value).__name__}")
                # 类型不符时，后续结构性关键字无意义，直接返回
                return

        # 3) const / enum
        if "const" in schema and value != schema["const"]:
            self._add(path, f"应恒等于 {schema['const']!r}，实际为 {value!r}")
        if "enum" in schema and value not in schema["enum"]:
            self._add(path, f"取值 {value!r} 不在允许枚举 {schema['enum']!r} 中")

        # 4) 数值
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                self._add(path, f"应 >= {schema['minimum']}，实际为 {value!r}")
            if "maximum" in schema and value > schema["maximum"]:
                self._add(path, f"应 <= {schema['maximum']}，实际为 {value!r}")

        # 5) 字符串
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                self._add(path, f"长度应 >= {schema['minLength']}，实际为 {len(value)}")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                self._add(path, f"长度应 <= {schema['maxLength']}，实际为 {len(value)}")
            if "pattern" in schema and re.search(schema["pattern"], value) is None:
                self._add(path, f"内容 {value!r} 不匹配正则 {schema['pattern']!r}")

        # 6) 数组
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                self._add(path, f"元素个数应 >= {schema['minItems']}，实际为 {len(value)}")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                self._add(path, f"元素个数应 <= {schema['maxItems']}，实际为 {len(value)}")
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    self._walk(item, item_schema, f"{path}[{index}]", depth + 1)

        # 7) 对象
        if isinstance(value, dict):
            properties = schema.get("properties", {})
            if "minProperties" in schema and len(value) < schema["minProperties"]:
                self._add(path, f"字段数应 >= {schema['minProperties']}，实际为 {len(value)}")

            for key in schema.get("required", []):
                if key not in value:
                    self._add(path, f"缺少必填字段 {key!r}")

            additional = schema.get("additionalProperties", True)
            for key, item in value.items():
                child_path = f"{path}.{key}"
                if key in properties:
                    self._walk(item, properties[key], child_path, depth + 1)
                elif additional is False:
                    self._add(child_path, "不允许出现该字段（additionalProperties=false）")
                elif isinstance(additional, dict):
                    self._walk(item, additional, child_path, depth + 1)


# --------------------------------------------------------------------------- #
# 文件级校验
# --------------------------------------------------------------------------- #

def load_schema(schema_path: Path) -> dict[str, Any]:
    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise ValueError(f"schema 根节点必须是 object: {schema_path}")
    return schema


def validate_file(case_path: Path, schema: dict[str, Any]) -> list[str]:
    """校验单个 case.json，返回错误列表（空表示通过）。"""
    with case_path.open("r", encoding="utf-8") as handle:
        instance = json.load(handle)
    return SchemaValidator(schema).validate(instance)


#: 与 isolation_guard 保持一致的保留目录名（非数据单元）
RESERVED_NAMES = frozenset({"docs", "tools", "evaluation", "_schema", ".github"})


def is_reserved_name(name: str) -> bool:
    """判断目录名是否为保留名（约定：以 ``_`` 开头，或落在保留清单内）。"""
    return name.startswith("_") or name in RESERVED_NAMES


def discover_cases() -> list[Path]:
    """发现 <Datasets>/*/case.json。

    跳过保留目录（以 ``_`` 开头的约定目录，如 ``_template`` / ``_schema``，
    以及 ``docs`` / ``tools`` / ``evaluation`` / ``.github``），
    使模板与工具目录不会被当作真实数据单元参与校验。
    """
    return sorted(
        path
        for path in DATASETS_ROOT.glob("*/case.json")
        if not is_reserved_name(path.parent.name)
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_cases",
        description="校验数据单元问题卡 case.json 是否符合 case.schema.json",
    )
    parser.add_argument("files", nargs="*", help="待校验的 case.json；缺省时扫描 */case.json")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH), help="schema 路径")
    parser.add_argument("--quiet", action="store_true", help="只输出失败项")
    parser.add_argument("--json", action="store_true", help="以 JSON 形式输出结果")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    schema_path = Path(args.schema)
    try:
        schema = load_schema(schema_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[schema 错误] {schema_path}: {exc}", file=sys.stderr)
        return 2

    if args.files:
        targets = [Path(item) for item in args.files]
    else:
        targets = discover_cases()

    if not targets:
        print("[warn] 未发现任何 case.json（数据单元可能尚未归档）")
        return 0

    results: list[dict[str, Any]] = []
    for target in targets:
        try:
            errors = validate_file(target, schema)
        except (OSError, json.JSONDecodeError) as exc:
            errors = [f"读取/解析失败: {exc}"]
        results.append({"file": str(target), "ok": not errors, "errors": errors})

    failed = [item for item in results if not item["ok"]]

    if args.json:
        print(json.dumps({"total": len(results), "failed": len(failed), "results": results},
                         ensure_ascii=False, indent=2))
    else:
        for item in results:
            if item["ok"]:
                if not args.quiet:
                    print(f"[ OK ] {item['file']}")
            else:
                print(f"[FAIL] {item['file']}")
                for message in item["errors"]:
                    print(f"        - {message}")
        print(f"\n合计 {len(results)} 个用例，通过 {len(results) - len(failed)}，失败 {len(failed)}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
