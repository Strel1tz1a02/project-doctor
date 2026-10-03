#!/usr/bin/env python3
"""答案隔离守卫（纯标准库实现，无第三方依赖）。

背景
----
《数据集结构规范》要求：评估运行时只把 ``<case-id>/project/`` 暴露给被测 Agent，
``case.json``、用例级 ``README.md``（维护者文档，含答案）、``docs/``、``_schema/``
一律不得对 Agent 可见；且 ``project/`` 内部不得通过符号链接、构建脚本或初始化数据
反向引用这些评测方资产。

本脚本把这些约定从「文档里的自觉」变成**可执行断言**：扫描每个数据单元的
``project/``，发现下列任一情况即判定为隔离泄漏（退出码 1）：

1. ``project/`` 目录缺失 —— 无法隔离，用例不可用；
2. ``project/`` 本身是符号链接 —— 暴露目录可被指向别处；
3. ``project/`` 内出现敏感文件（``case.json`` / ``case.schema.json``）；
4. ``project/`` 内存在指向 ``project/`` 之外的符号链接 —— 旁路读取答案；
5. ``project/`` 内的文本文件引用了答案资产（``case.json``、``_schema``、
   ``Datasets/docs``、``ground truth``、``root_cause_ids`` 等）；
6. ``project/`` 内出现版本库目录（``.git``）—— 可能连带携带答案历史与分支。

用法
----
    python tools/isolation_guard.py                 # 扫描所有数据单元
    python tools/isolation_guard.py --json          # 机器可读输出
    python tools/isolation_guard.py --root <Datasets>

退出码
------
    0  全部通过
    1  存在隔离泄漏
    2  用法 / IO 错误
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

#: 本文件位于 <Datasets>/tools/isolation_guard.py，数据集根即上两级目录
DATASETS_ROOT = Path(__file__).resolve().parent.parent

#: 保留目录/文件：以 ``_`` 开头，或被显式点名，均不作为数据单元
RESERVED_NAMES = frozenset({"docs", "tools", "evaluation", "_schema", ".github"})

#: 不得出现在 ``project/`` 内的敏感文件名（评测方资产）
SENSITIVE_FILENAMES = frozenset({"case.json", "case.schema.json"})

#: 版本库/编辑器目录，若混入 ``project/`` 视为风险
VCS_NAMES = frozenset({".git", ".svn", ".hg"})

#: 文本文件中一旦出现即视为「引用了答案资产」的标记（统一小写比对）
LEAK_TOKENS = (
    "case.json",
    "case.schema.json",
    "_schema",
    "datasets/docs",
    "../docs/",
    "ground truth",
    "ground_truth",
    "root_cause_ids",
)

#: 超过该大小（字节）的文件不做文本扫描，避免拖慢 CI
MAX_SCAN_BYTES = 512 * 1024


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Finding:
    """一条隔离泄漏记录。"""

    case_id: str
    path: str          # 相对数据集根（或相对用例根，见调用处）
    kind: str          # missing_project / symlink_project / symlink_escape /
                       # sensitive_file / vcs_dir / answer_reference
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# 纯函数（便于单元测试）
# --------------------------------------------------------------------------- #

def is_reserved_name(name: str) -> bool:
    """以 ``_`` 开头的名字，或显式保留名，都不是数据单元。"""
    return name.startswith("_") or name in RESERVED_NAMES


def escapes_root(target: Path, root: Path) -> bool:
    """判断 ``target`` 解析后是否落在 ``root`` 之外（符号链接越界检测）。"""
    try:
        target_real = target.resolve()
        root_real = root.resolve()
    except OSError:
        # 解析失败（断链等）时保守判为越界，交由上层记录
        return True
    if target_real == root_real:
        return False
    return root_real not in target_real.parents


def scan_text(text: str) -> list[tuple[int, str]]:
    """在文本中查找答案资产标记，返回 ``(行号, 命中的标记)``，每个标记只报首个。"""
    lowered = text.lower()
    hits: list[tuple[int, str]] = []
    for token in LEAK_TOKENS:
        index = lowered.find(token)
        if index < 0:
            continue
        line_no = lowered.count("\n", 0, index) + 1
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


# --------------------------------------------------------------------------- #
# 目录遍历
# --------------------------------------------------------------------------- #

def discover_cases(root: Path) -> list[Path]:
    """发现 ``<root>/*/case.json`` 所属的数据单元目录。"""
    cases = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or is_reserved_name(child.name):
            continue
        if (child / "case.json").is_file():
            cases.append(child)
    return cases


def _rel(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_regular_files(project: Path) -> Iterator[Path]:
    """遍历 ``project/`` 下的普通文件（不跟随符号链接）。"""
    for dirpath, _dirnames, filenames in os.walk(project, followlinks=False):
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            yield path


# --------------------------------------------------------------------------- #
# 核心扫描
# --------------------------------------------------------------------------- #

def scan_case(case_dir: Path) -> list[Finding]:
    """扫描单个数据单元，返回全部泄漏记录（空表示隔离合规）。"""
    case_id = case_dir.name
    project = case_dir / "project"
    findings: list[Finding] = []

    if not project.exists():
        return [Finding(case_id, _rel(project, case_dir), "missing_project",
                        "未找到 project/ 目录，无法进行答案隔离")]

    if project.is_symlink():
        findings.append(Finding(case_id, _rel(project, case_dir), "symlink_project",
                                "project/ 本身是符号链接，暴露目录可能被指向别处"))

    # 1) 目录树元数据检查：敏感文件、越界符号链接、版本库目录
    for dirpath, dirnames, filenames in os.walk(project, followlinks=False, onerror=None):
        dirpath_p = Path(dirpath)
        for name in list(dirnames) + list(filenames):
            entry = dirpath_p / name
            rel = _rel(entry, case_dir)
            if entry.is_symlink():
                if escapes_root(entry, project):
                    try:
                        link_target = os.readlink(entry)
                    except OSError:
                        link_target = "<?>"
                    findings.append(Finding(case_id, rel, "symlink_escape",
                                            f"符号链接指向 project/ 之外：{link_target}"))
                continue
            if name in VCS_NAMES:
                findings.append(Finding(case_id, rel, "vcs_dir",
                                        f"版本库目录 {name!r} 不应出现在 project/ 内"))
            if name in SENSITIVE_FILENAMES:
                findings.append(Finding(case_id, rel, "sensitive_file",
                                        f"敏感文件 {name!r} 出现在 project/ 内"))

    # 2) 文本内容检查：是否引用了答案资产
    for path in _iter_regular_files(project):
        text = read_text_safely(path)
        if text is None:
            continue
        for line_no, token in scan_text(text):
            findings.append(Finding(case_id, _rel(path, case_dir), "answer_reference",
                                    f"第 {line_no} 行引用了答案资产标记 {token!r}"))

    return findings


def scan_all(root: Path) -> tuple[list[Path], list[Finding]]:
    """扫描根目录下全部数据单元，返回 ``(用例目录列表, 泄漏记录列表)``。"""
    cases = discover_cases(root)
    findings: list[Finding] = []
    for case_dir in cases:
        findings.extend(scan_case(case_dir))
    return cases, findings


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="isolation_guard",
        description="断言 <case-id>/project/ 内不含任何评测方答案资产（答案隔离守卫）",
    )
    parser.add_argument("--root", default=str(DATASETS_ROOT),
                        help="数据集根目录，缺省为本脚本上两级目录")
    parser.add_argument("--json", action="store_true", help="以 JSON 形式输出结果")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    root = Path(args.root)

    if not root.is_dir():
        print(f"[错误] 数据集根目录不存在：{root}", file=sys.stderr)
        return 2

    cases, findings = scan_all(root)
    ok = not findings

    if args.json:
        print(json.dumps({
            "root": str(root),
            "cases": [c.name for c in cases],
            "findings": [f.as_dict() for f in findings],
            "ok": ok,
        }, ensure_ascii=False, indent=2))
    else:
        if not cases:
            print("[warn] 未发现任何数据单元（缺少 */case.json）")
        for case_dir in cases:
            case_findings = [f for f in findings if f.case_id == case_dir.name]
            if case_findings:
                print(f"[FAIL] {case_dir.name}")
                for item in case_findings:
                    print(f"        - {item.kind}: {item.path} —— {item.detail}")
            else:
                print(f"[ OK ] {case_dir.name}：project/ 无答案泄漏")
        print(f"\n合计 {len(cases)} 个用例，隔离合规 {len(cases) - len({f.case_id for f in findings})}，"
              f"存在泄漏 {len({f.case_id for f in findings})}")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
