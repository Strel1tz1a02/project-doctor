#!/usr/bin/env python3
"""SUT 隔离守卫（纯标准库实现，无第三方依赖）。

背景
----
本数据集以「方案 B：并入 project-doctor」并入被测仓库的 ``datasets/`` 目录后，
金标准答案（``case.json`` 的 defects/expected、``docs/``、``_schema/``）与被测系统
（SUT，``src/project_doctor``）将处于同一仓库。原有的 ``isolation_guard.py`` 只能保证
「单个用例的 ``project/`` 不泄漏答案」，无法覆盖「SUT 源码反过来读取金标准」这一新增风险。

本脚本补上这道防线：扫描 SUT 源码，一旦发现对数据集金标准的引用
（目录名 ``datasets``、``case.json``、``ground truth``、``root_cause_ids`` 等）
即判定为隔离泄漏（退出码 1）。

用法
----
    python tools/guard_sut_separation.py                 # 默认扫描 <repo>/src
    python tools/guard_sut_separation.py --sut <dir>     # 指定 SUT 源码目录
    python tools/guard_sut_separation.py --json          # 机器可读输出

退出码
------
    0  通过（或未找到 SUT 目录：独立数据集模式，跳过）
    1  发现 SUT 引用了金标准
    2  用法 / IO 错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

#: 本文件位于 <repo>/datasets/tools/guard_sut_separation.py，数据集根即上两级目录
DATASETS_ROOT = Path(__file__).resolve().parent.parent

#: 仓库根（并入后 = project-doctor 根；独立数据集模式下无意义）
REPO_ROOT = DATASETS_ROOT.parent

#: SUT 源码目录（相对仓库根）
DEFAULT_SUT_DIR = REPO_ROOT / "src"

#: 遍历时跳过的目录名
SKIP_DIR_NAMES = frozenset({"__pycache__", ".git", ".svn", ".hg", ".mypy_cache", ".ruff_cache"})

#: 一旦出现在 SUT 源码中即视为「引用了数据集金标准」的标记（统一小写比对）
#: 注意：使用词边界，避免 ``DatasetProfile`` / ``dataset.py`` 等 SUT 合法标识被误伤。
FORBIDDEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![A-Za-z0-9_])datasets(?![A-Za-z0-9_])"), "datasets"),
    (re.compile(r"case\.json"), "case.json"),
    (re.compile(r"case\.schema\.json"), "case.schema.json"),
    (re.compile(r"ground[_ ]truth"), "ground truth"),
    (re.compile(r"root_cause_ids"), "root_cause_ids"),
)

#: 超过该大小（字节）的文件不做文本扫描，避免拖慢 CI
MAX_SCAN_BYTES = 512 * 1024


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Finding:
    """一条 SUT 引用金标准的记录。"""

    path: str   # 相对 SUT 根
    line: int   # 行号（1 起）
    token: str  # 命中的标记

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# 纯函数（便于单元测试）
# --------------------------------------------------------------------------- #

def scan_text(text: str) -> list[tuple[int, str]]:
    """在文本中查找金标准标记，返回 ``(行号, 命中的标记)``，每个标记只报首个。"""
    lowered = text.lower()
    hits: list[tuple[int, str]] = []
    for pattern, token in FORBIDDEN_PATTERNS:
        match = pattern.search(lowered)
        if match is None:
            continue
        line_no = lowered.count("\n", 0, match.start()) + 1
        hits.append((line_no, token))
    return hits


def read_text_safely(path: Path) -> str | None:
    """尽量把文件读成文本；判定为二进制或过大时返回 ``None``（跳过扫描）。"""
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _rel(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


# --------------------------------------------------------------------------- #
# 目录遍历与扫描
# --------------------------------------------------------------------------- #

def iter_source_files(sut_root: Path) -> Iterator[Path]:
    """遍历 SUT 源码目录下的普通文本文件（不跟随符号链接，跳过缓存/版本库目录）。"""
    for dirpath, dirnames, filenames in os.walk(sut_root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            yield path


def scan_sut(sut_root: Path) -> list[Finding]:
    """扫描 SUT 源码目录，返回全部「引用金标准」记录（空表示合规）。

    若 ``sut_root`` 不存在（例如数据集仍以独立仓库形式存在），返回空列表 ——
    视为「无 SUT 可检查」，交由 CLI 打印跳过提示。
    """
    if not sut_root.is_dir():
        return []

    findings: list[Finding] = []
    for path in iter_source_files(sut_root):
        text = read_text_safely(path)
        if text is None:
            continue
        for line_no, token in scan_text(text):
            findings.append(Finding(_rel(path, sut_root), line_no, token))
    return findings


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guard_sut_separation",
        description="断言被测系统（SUT）源码未引用数据集金标准（SUT 隔离守卫）",
    )
    parser.add_argument("--sut", default=str(DEFAULT_SUT_DIR),
                        help="SUT 源码目录，缺省为本脚本上三级目录下的 src/")
    parser.add_argument("--json", action="store_true", help="以 JSON 形式输出结果")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    sut_root = Path(args.sut)

    if not sut_root.is_dir():
        message = (f"[skip] 未找到 SUT 目录：{sut_root}（独立数据集模式，跳过 SUT 隔离检查）")
        if args.json:
            print(json.dumps({"sut": str(sut_root), "skipped": True, "findings": [], "ok": True},
                             ensure_ascii=False, indent=2))
        else:
            print(message)
        return 0

    findings = scan_sut(sut_root)
    ok = not findings

    if args.json:
        print(json.dumps({
            "sut": str(sut_root),
            "findings": [f.as_dict() for f in findings],
            "ok": ok,
        }, ensure_ascii=False, indent=2))
    else:
        if findings:
            print(f"[FAIL] SUT 源码引用了数据集金标准（{len(findings)} 处）：")
            for item in findings:
                print(f"        - {item.path}:{item.line} —— 命中标记 {item.token!r}")
            print("\nSUT 不得读取金标准：答案必须保持与被测系统隔离。")
        else:
            print(f"[ OK ] SUT 源码（{sut_root}）未引用任何数据集金标准")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
