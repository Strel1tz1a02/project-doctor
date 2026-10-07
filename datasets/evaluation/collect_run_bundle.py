#!/usr/bin/env python3
"""运行包采集模块（纯标准库，**零执行**）：原始代码 + 修改后代码 → 运行包。

定位
----
本模块解决「评测器需要哪些评分参数、这些参数怎么组织成一份运行包」的问题，
对外提供统一接口：

    collect_run_bundle(case_dir, original_code, modified_code, *, patch, backend, ...)

它负责三件事：
1. **定义契约**：把评测器（``run_eval.py`` / ``EvalInput``）读取的全部参数固化成
   ``LAYERS``（baseline / report / trajectory / retest / artifacts / restore / cost）；
2. **组装运行包**：把各层参数拼成一份符合评测器输入格式的 JSON；
3. **溯源与校验**：记录原始/修改代码的**内容指纹**（sha256 + 文件数），并校验运行包
   的完整性与类型。

硬边界（务必遵守）
------------------
本模块**不启动被测系统（SUT）、不跑实验、不压数据库**——源码中**不存在**任何
``subprocess`` / ``os.system`` / 网络调用。真正「跑实验、采数据」的动作由外部
**采集后端（CollectorBackend）** 完成，本模块只规定后端须实现哪些方法、并把结果
组装/校验成运行包。

内置后端
--------
- ``StaticBundleBackend``：从一份「已采集好的原始测量 JSON」读取各层（默认，纯离线）；
- ``DirectoryBackend``：从目录下 ``<layer>.json`` 分文件读取各层；
- ``NullBackend``：**不实现任何采集**，逐层抛出 ``CollectionNotImplemented``——
  用于显式标记「执行侧尚未接入」，也用于自检。

若执行侧要真正跑实验，请实现 ``CollectorBackend`` 的子类（在**属于执行侧**的代码里），
再把实例作为 ``backend`` 传入即可。协作边界见 ``docs/运行包采集模块交接说明.md``。

用法
----
    from collect_run_bundle import collect_run_bundle, StaticBundleBackend

    backend = StaticBundleBackend(json.load(open("measured.json", encoding="utf-8")))
    bundle = collect_run_bundle("case-01-slow-query-fullscan", "orig/", "fixed/",
                                backend=backend)

命令行
------
    # 无参数：运行自检
    python evaluation/collect_run_bundle.py

    # 从静态测量文件组装运行包
    python evaluation/collect_run_bundle.py \
        --case-dir case-01-slow-query-fullscan \
        --original orig --modified fixed \
        --backend static --from measured.json --out runs/case-01-slow-query-fullscan.json

    # 仅校验一份已有运行包
    python evaluation/collect_run_bundle.py --check runs/case-01-slow-query-fullscan.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import contract as C  # noqa: E402  （仅取 DEFAULT_LINE_TOLERANCE 常量）

__all__ = [
    "MODULE_VERSION",
    "LAYERS",
    "REQUIRED_LAYERS",
    "OPTIONAL_LAYERS",
    "CollectRequest",
    "CollectionNotImplemented",
    "CollectorBackend",
    "StaticBundleBackend",
    "DirectoryBackend",
    "NullBackend",
    "RunBundleBuilder",
    "BundleValidation",
    "code_digest",
    "collect_run_bundle",
    "validate_bundle",
]

#: 模块版本（写入运行包 ``collection.module_version``，便于溯源）。
MODULE_VERSION = "0.1.0"

#: 评测器读取的全部顶层层（顺序即组装顺序）。与 ``run_eval.run`` 的读取键一致。
LAYERS: tuple[str, ...] = (
    "baseline", "report", "trajectory", "retest", "artifacts", "restore", "cost",
)

#: 评测器判分必需：``report`` 是 ``EvalInput.from_raw`` 的必填位置参数。
REQUIRED_LAYERS: tuple[str, ...] = ("report",)

#: 建议层：缺失不会报错，但会拉低对应指标 / 触发闸门。
OPTIONAL_LAYERS: tuple[str, ...] = tuple(layer for layer in LAYERS if layer not in REQUIRED_LAYERS)

#: 计算代码指纹时跳过的目录名（避免把缓存/构建产物算进去）。
_DIGEST_SKIP_DIRS = frozenset({
    ".git", ".svn", ".hg", "__pycache__", ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode", "node_modules", "target", "build", "dist", ".gradle",
})

#: 单一文件最大读取字节（指纹计算时对超大文件做流式读取）。
_DIGEST_CHUNK = 1 << 20


# --------------------------------------------------------------------------- #
# 异常与请求
# --------------------------------------------------------------------------- #

class CollectionNotImplemented(RuntimeError):
    """某个采集层未被后端实现（属于执行 / 采集侧职责）。"""

    def __init__(self, backend: str, layer: str) -> None:
        super().__init__(
            f"采集后端 {backend!r} 未实现 {layer!r} 层：真正的实验执行/数据采集"
            f"不在本数据集工程范围内，请由执行侧实现 CollectorBackend 后接入。"
        )
        self.backend = backend
        self.layer = layer


@dataclass
class CollectRequest:
    """一次采集请求：**输入为原始代码与修改后代码**。

    参数
    ----
    case_id:      用例标识，须与目标 ``<case-id>/case.json`` 的目录名一致。
    case_dir:     用例目录（含 ``case.json``，属评测侧真相，本模块只读取用于校验）。
    original_code: 原始（未修改）代码所在目录或文件。
    modified_code: 修改后代码所在目录或文件（或与 ``patch`` 配套的工作副本）。
    patch:        可选，代码改动补丁文件（用于溯源；本模块不应用它）。
    workdir:      可选，执行侧的工作目录（仅登记，不进入）。
    line_tolerance: 代码定位行号容差；缺省取 ``contract.DEFAULT_LINE_TOLERANCE``。
    extras:       可选，附加到运行包 ``collection.extras`` 的自定义元数据。
    """

    case_id: str
    case_dir: Path
    original_code: Path
    modified_code: Path
    patch: Path | None = None
    workdir: Path | None = None
    line_tolerance: int = C.DEFAULT_LINE_TOLERANCE
    extras: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 代码指纹（只读文件，绝不执行任何东西）
# --------------------------------------------------------------------------- #

def _hash_file(path: Path, hasher: "hashlib._Hash") -> int:
    """把一个文件的字节喂给 hasher，返回字节数（流式，避免大文件爆内存）。"""
    written = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_DIGEST_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
            written += len(chunk)
    return written


def code_digest(target: str | os.PathLike[str]) -> dict[str, Any]:
    """计算代码的内容指纹（sha256）与文件数，用于把运行包绑定到确定的代码版本。

    - 目录：按相对路径排序后逐个哈希（路径 + 长度 + 内容），跳过缓存/构建目录；
    - 文件：直接哈希其字节；
    - 不存在：返回 ``{"path": ..., "exists": False}``，不抛异常（由校验层给警告）。
    """
    path = Path(target)
    result: dict[str, Any] = {"path": path.as_posix()}
    if not path.exists():
        result["exists"] = False
        return result

    hasher = hashlib.sha256()
    files = 0
    total_bytes = 0
    if path.is_file():
        files = 1
        total_bytes = _hash_file(path, hasher)
        result["kind"] = "file"
    else:
        result["kind"] = "dir"
        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d not in _DIGEST_SKIP_DIRS)
            for name in sorted(filenames):
                file_path = Path(dirpath) / name
                if file_path.is_symlink():
                    continue
                rel = file_path.relative_to(path).as_posix()
                hasher.update(rel.encode("utf-8"))
                hasher.update(b"\x00")
                size = _hash_file(file_path, hasher)
                hasher.update(b"\x00")
                files += 1
                total_bytes += size

    result.update({
        "exists": True,
        "sha256": hasher.hexdigest(),
        "files": files,
        "bytes": total_bytes,
    })
    return result


# --------------------------------------------------------------------------- #
# 采集后端（可插拔）
# --------------------------------------------------------------------------- #

class CollectorBackend:
    """采集后端基类：逐层返回已采集好的原始参数。

    子类只需覆盖关心的层。**默认全部未实现**并行 ``CollectionNotImplemented``，
    以此明确「执行/采集是外部职责」。本基类不含任何执行 SUT 的代码。
    """

    name: str = "abstract"

    def collect_baseline(self, request: CollectRequest) -> Mapping[str, Any] | None:
        raise CollectionNotImplemented(self.name, "baseline")

    def collect_report(self, request: CollectRequest) -> Mapping[str, Any] | None:
        raise CollectionNotImplemented(self.name, "report")

    def collect_trajectory(self, request: CollectRequest) -> Mapping[str, Any] | None:
        raise CollectionNotImplemented(self.name, "trajectory")

    def collect_retest(self, request: CollectRequest) -> Mapping[str, Any] | None:
        raise CollectionNotImplemented(self.name, "retest")

    def collect_artifacts(self, request: CollectRequest) -> Sequence[Any] | None:
        raise CollectionNotImplemented(self.name, "artifacts")

    def collect_restore(self, request: CollectRequest) -> Mapping[str, Any] | None:
        raise CollectionNotImplemented(self.name, "restore")

    def collect_cost(self, request: CollectRequest) -> Mapping[str, Any] | None:
        raise CollectionNotImplemented(self.name, "cost")


class StaticBundleBackend(CollectorBackend):
    """从一份「已采集好的原始测量 JSON」读取各层（纯离线，默认后端）。

    ``payload`` 是形如 ``{"baseline": {...}, "report": {...}, ...}`` 的映射；
    未包含的层返回 ``None``（由校验层判定是否必需）。
    """

    name = "static-bundle"

    def __init__(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            raise TypeError("StaticBundleBackend 需要 mapping（各层参数）作为输入")
        self._payload = payload

    def _get(self, layer: str) -> Any | None:
        value = self._payload.get(layer)
        return value

    def collect_baseline(self, request: CollectRequest) -> Any | None:
        return self._get("baseline")

    def collect_report(self, request: CollectRequest) -> Any | None:
        return self._get("report")

    def collect_trajectory(self, request: CollectRequest) -> Any | None:
        return self._get("trajectory")

    def collect_retest(self, request: CollectRequest) -> Any | None:
        return self._get("retest")

    def collect_artifacts(self, request: CollectRequest) -> Any | None:
        return self._get("artifacts")

    def collect_restore(self, request: CollectRequest) -> Any | None:
        return self._get("restore")

    def collect_cost(self, request: CollectRequest) -> Any | None:
        return self._get("cost")


class DirectoryBackend(CollectorBackend):
    """从目录下 ``<layer>.json`` 分文件读取各层（纯离线）。

    例如 ``raw/`` 下有 ``baseline.json`` / ``report.json`` / ``artifacts.json``……，
    缺失的文件对应层返回 ``None``。
    """

    name = "directory"

    def __init__(self, raw_dir: str | os.PathLike[str]) -> None:
        self._dir = Path(raw_dir)

    def _read(self, layer: str) -> Any | None:
        path = self._dir / f"{layer}.json"
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def collect_baseline(self, request: CollectRequest) -> Any | None:
        return self._read("baseline")

    def collect_report(self, request: CollectRequest) -> Any | None:
        return self._read("report")

    def collect_trajectory(self, request: CollectRequest) -> Any | None:
        return self._read("trajectory")

    def collect_retest(self, request: CollectRequest) -> Any | None:
        return self._read("retest")

    def collect_artifacts(self, request: CollectRequest) -> Any | None:
        return self._read("artifacts")

    def collect_restore(self, request: CollectRequest) -> Any | None:
        return self._read("restore")

    def collect_cost(self, request: CollectRequest) -> Any | None:
        return self._read("cost")


class NullBackend(CollectorBackend):
    """显式「未接入执行侧」的后端：逐层抛 ``CollectionNotImplemented``。

    存在的意义：把「本模块不跑实验」这条边界变成**可执行的断言**，并提供给测试使用。
    """

    name = "null-execution"


# --------------------------------------------------------------------------- #
# 运行包组装
# --------------------------------------------------------------------------- #

class RunBundleBuilder:
    """把某个采集后端的结果组装成评测器可消费的运行包。"""

    def __init__(self, backend: CollectorBackend) -> None:
        self.backend = backend

    def _collect_layer(self, layer: str, request: CollectRequest) -> tuple[Any | None, bool]:
        """返回 ``(取值, 是否已实现)``；未实现记 ``(None, False)`` 而不中断组装。"""
        try:
            value = getattr(self.backend, f"collect_{layer}")(request)
        except CollectionNotImplemented:
            return None, False
        return value, True

    def _provenance(
        self,
        request: CollectRequest,
        present: Sequence[str],
        unimplemented: Sequence[str],
    ) -> dict[str, Any]:
        patch_digest = code_digest(request.patch) if request.patch is not None else None
        return {
            "module": "collect_run_bundle",
            "module_version": MODULE_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "backend": self.backend.name,
            "case_id": request.case_id,
            "case_dir": Path(request.case_dir).as_posix(),
            "original_code": code_digest(request.original_code),
            "modified_code": code_digest(request.modified_code),
            "patch": patch_digest,
            "workdir": Path(request.workdir).as_posix() if request.workdir else None,
            "line_tolerance": int(request.line_tolerance),
            "layers_present": list(present),
            "layers_unimplemented": list(unimplemented),
            "extras": dict(request.extras),
        }

    def build(self, request: CollectRequest) -> dict[str, Any]:
        """组装并返回运行包 dict（未做完整性校验，校验请用 ``validate_bundle``）。"""
        bundle: dict[str, Any] = {}
        present: list[str] = []
        unimplemented: list[str] = []
        for layer in LAYERS:
            value, implemented = self._collect_layer(layer, request)
            if not implemented:
                unimplemented.append(layer)
                continue
            if value is None:
                continue
            bundle[layer] = value
            present.append(layer)

        bundle["collection"] = self._provenance(request, present, unimplemented)
        return bundle


def collect_run_bundle(
    case_dir: str | os.PathLike[str],
    original_code: str | os.PathLike[str],
    modified_code: str | os.PathLike[str],
    *,
    patch: str | os.PathLike[str] | None = None,
    backend: CollectorBackend | None = None,
    workdir: str | os.PathLike[str] | None = None,
    line_tolerance: int | None = None,
    extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """**对外主接口**：输入原始代码与修改后代码，产出运行包 dict。

    ``backend`` 决定「谁来提供已采集的参数」：
    - 省略时使用 ``NullBackend``（不跑实验，产出的运行包会因缺 ``report`` 而校验失败——
      这正是提醒你「执行侧尚未接入」）；
    - 传入 ``StaticBundleBackend`` / ``DirectoryBackend`` 或执行侧自定义子类即可。
    """
    case_path = Path(case_dir)
    request = CollectRequest(
        case_id=case_path.name,
        case_dir=case_path,
        original_code=Path(original_code),
        modified_code=Path(modified_code),
        patch=Path(patch) if patch is not None else None,
        workdir=Path(workdir) if workdir is not None else None,
        line_tolerance=(C.DEFAULT_LINE_TOLERANCE if line_tolerance is None
                        else int(line_tolerance)),
        extras=dict(extras or {}),
    )
    return RunBundleBuilder(backend or NullBackend()).build(request)


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #

@dataclass
class BundleValidation:
    """运行包校验结果。"""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    present_layers: list[str] = field(default_factory=list)
    missing_layers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "present_layers": list(self.present_layers),
            "missing_layers": list(self.missing_layers),
        }

    def render(self) -> str:
        lines = ["[ OK ] 运行包校验通过" if self.ok else "[FAIL] 运行包校验未通过"]
        lines.append(f"       已含层：{', '.join(self.present_layers) or '（无）'}")
        lines.append(f"       缺失层：{', '.join(self.missing_layers) or '（无）'}")
        if self.errors:
            lines.append("       错误：")
            lines += [f"         - {e}" for e in self.errors]
        if self.warnings:
            lines.append("       警告：")
            lines += [f"         - {w}" for w in self.warnings]
        return "\n".join(lines)


_LAYER_EXPECTED: dict[str, type | tuple[type, ...]] = {
    "baseline": dict,
    "report": dict,
    "trajectory": dict,
    "retest": dict,
    "artifacts": list,
    "restore": dict,
    "cost": dict,
}


def validate_bundle(
    bundle: Mapping[str, Any],
    *,
    case_dir: str | os.PathLike[str] | None = None,
) -> BundleValidation:
    """校验运行包：必需层、各层类型、基线形状、与用例的对应关系。

    只做**结构与契约**校验（不计算指标）。返回 ``BundleValidation``。
    """
    errors: list[str] = []
    warnings: list[str] = []
    present = [layer for layer in LAYERS if layer in bundle]
    missing_required = [layer for layer in REQUIRED_LAYERS if layer not in bundle]
    missing_optional = [layer for layer in OPTIONAL_LAYERS if layer not in bundle]

    for layer in missing_required:
        errors.append(f"缺少必需层 {layer!r}：评测器 ``EvalInput.from_raw`` 需要它")
    if missing_optional:
        warnings.append(f"缺少建议层 {', '.join(missing_optional)}：对应指标会按默认（多为未达标）计")

    # 逐层类型
    for layer in present:
        expected = _LAYER_EXPECTED[layer]
        if not isinstance(bundle[layer], expected):
            errors.append(f"层 {layer!r} 类型应为 {getattr(expected, '__name__', expected)}，"
                          f"实为 {type(bundle[layer]).__name__}")

    # report 细项
    report = bundle.get("report")
    if isinstance(report, Mapping):
        if "findings" in report and not isinstance(report["findings"], list):
            errors.append("report.findings 应为数组")

    # baseline 细项
    baseline = bundle.get("baseline")
    if isinstance(baseline, Mapping):
        repeats = baseline.get("repeats_ms")
        if repeats is None:
            warnings.append("baseline 缺少 repeats_ms：无法做基线可复现性判定")
        elif not isinstance(repeats, list) or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in repeats
        ):
            errors.append("baseline.repeats_ms 应为数值数组")

    # artifacts 细项
    artifacts = bundle.get("artifacts")
    if isinstance(artifacts, list):
        for index, item in enumerate(artifacts):
            if not isinstance(item, Mapping):
                errors.append(f"artifacts[{index}] 应为对象")
                break

    # 与用例的对应关系
    collection = bundle.get("collection")
    if isinstance(collection, Mapping) and collection.get("case_id"):
        if case_dir is not None and Path(case_dir).name != collection["case_id"]:
            warnings.append(
                f"运行包 collection.case_id={collection['case_id']!r} 与用例目录名 "
                f"{Path(case_dir).name!r} 不一致")
    if case_dir is not None:
        if not (Path(case_dir) / "case.json").is_file():
            errors.append(f"用例目录下未找到 case.json：{Path(case_dir).as_posix()}")

    return BundleValidation(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        present_layers=present,
        missing_layers=missing_required + missing_optional,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_run_bundle",
        description="把「原始代码 + 修改后代码」的已采集参数组装成评测器可消费的运行包"
                    "（本模块只组装/校验，不跑实验）",
    )
    parser.add_argument("--case-dir", help="用例目录（含 case.json），其目录名作为 case_id")
    parser.add_argument("--original", help="原始代码目录/文件")
    parser.add_argument("--modified", help="修改后代码目录/文件")
    parser.add_argument("--patch", help="可选的改动补丁文件（仅登记溯源）")
    parser.add_argument("--workdir", help="可选，执行侧工作目录（仅登记）")
    parser.add_argument("--line-tolerance", type=int, default=C.DEFAULT_LINE_TOLERANCE,
                        help=f"代码定位行号容差（默认 {C.DEFAULT_LINE_TOLERANCE}）")
    parser.add_argument("--backend", choices=("static", "directory", "null"), default="static",
                        help="采集后端：static（默认，读 --from）| directory（读 --raw-dir）| null")
    parser.add_argument("--from", dest="static_from", help="static 后端：原始测量 JSON 路径")
    parser.add_argument("--raw-dir", help="directory 后端：分层 JSON 所在目录")
    parser.add_argument("--out", help="运行包写出路径（省略则打印到 stdout）")
    parser.add_argument("--check", help="仅校验一份已有运行包后退出")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    return parser


def _make_backend(args: argparse.Namespace) -> CollectorBackend:
    if args.backend == "static":
        if not args.static_from:
            raise SystemExit("[错误] static 后端需要 --from <原始测量 JSON>")
        with Path(args.static_from).open("r", encoding="utf-8") as handle:
            return StaticBundleBackend(json.load(handle))
    if args.backend == "directory":
        if not args.raw_dir:
            raise SystemExit("[错误] directory 后端需要 --raw-dir <目录>")
        return DirectoryBackend(args.raw_dir)
    return NullBackend()


def main(argv: Iterable[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    if not raw:
        _self_check()
        return 0

    args = _build_parser().parse_args(raw)

    # 仅校验模式
    if args.check:
        bundle_path = Path(args.check)
        if not bundle_path.is_file():
            print(f"[错误] 运行包不存在：{bundle_path.as_posix()}", file=sys.stderr)
            return 2
        with bundle_path.open("r", encoding="utf-8") as handle:
            bundle = json.load(handle)
        validation = validate_bundle(bundle, case_dir=args.case_dir)
        print(json.dumps(validation.to_dict(), ensure_ascii=False, indent=2)
              if args.json else validation.render())
        return 0 if validation.ok else 1

    if not (args.case_dir and args.original and args.modified):
        print("[错误] 需要 --case-dir / --original / --modified（或使用 --check）",
              file=sys.stderr)
        return 2

    backend = _make_backend(args)
    bundle = collect_run_bundle(
        args.case_dir, args.original, args.modified,
        patch=args.patch, backend=backend, workdir=args.workdir,
        line_tolerance=args.line_tolerance,
    )
    validation = validate_bundle(bundle, case_dir=args.case_dir)

    payload = {"bundle": bundle, "validation": validation.to_dict()}
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.json:
            print(json.dumps({**payload, "out": out_path.as_posix()},
                             ensure_ascii=False, indent=2))
        else:
            print(validation.render())
            print(f"       运行包已写出：{out_path.as_posix()}")
    elif args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(validation.render())

    return 0 if validation.ok else 1


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def _self_check() -> None:
    import tempfile

    def _flags_all() -> dict[str, bool]:
        return {name: True for name in C.EVIDENCE_FLAGS}

    samples = {
        "case-01-slow-query-fullscan": {
            "baseline": {"repeats_ms": [12.1, 11.8, 12.4], "environment_fingerprint": "selfcheck"},
            "report": {
                "task": {"status": "completed"},
                "findings": [{
                    "status": "verified",
                    "code_locations": [{"path": "a.java", "line": 17}],
                    "evidence_refs": ["artifact://plan.json"],
                    "excluded_explanations": [{"explanation": "lock_contention"}],
                    "recommendation": {"validation_status": "retested", "measured_gain_percent": 84.0},
                    "evidence_flags": _flags_all(),
                }],
            },
            "trajectory": {"required_steps_done": list(C.REQUIRED_STEPS),
                           "hypothesis_count": 2, "experiments_single_variable": True,
                           "records_retained": True, "tool_calls": 9},
            "retest": {"performed": True, "improvement_percent": 84.0,
                       "business_assertions_passed": True},
            "artifacts": [{"ref": "artifact://plan.json", "sha256_verified": True, "readable": True}],
            "restore": {"rolled_back": True, "verified": True},
            "cost": {"wall_seconds": 41.5, "tool_calls": 9, "artifact_bytes": 2048},
        },
    }

    with tempfile.TemporaryDirectory(prefix="collect-selfcheck-") as tmp:
        tmp_path = Path(tmp)
        orig = tmp_path / "orig"
        fixed = tmp_path / "fixed"
        case_dir = tmp_path / "case-01-slow-query-fullscan"
        for directory in (orig, fixed, case_dir):
            directory.mkdir(parents=True)
        (orig / "a.java").write_text("int a = 1;\n", encoding="utf-8")
        (fixed / "a.java").write_text("int a = 2;\n", encoding="utf-8")
        (case_dir / "case.json").write_text(json.dumps({
            "case_id": case_dir.name, "case_type": "normal", "schema_version": "0.1",
        }, ensure_ascii=False), encoding="utf-8")

        # 1) 静态后端：完整运行包 → 校验通过
        bundle = collect_run_bundle(
            case_dir, orig, fixed, backend=StaticBundleBackend(samples[case_dir.name]))
        result = validate_bundle(bundle, case_dir=case_dir)
        assert result.ok, result.errors
        assert set(result.present_layers) == set(LAYERS)
        assert bundle["collection"]["case_id"] == case_dir.name
        assert bundle["collection"]["backend"] == "static-bundle"
        assert bundle["collection"]["original_code"]["exists"] is True
        assert bundle["collection"]["modified_code"]["files"] == 1

        # 2) 指纹与内容相关：改一个字节，指纹必变
        before = bundle["collection"]["modified_code"]["sha256"]
        (fixed / "a.java").write_text("int a = 3;\n", encoding="utf-8")
        after = code_digest(fixed)["sha256"]
        assert before != after, "修改代码内容后指纹应变化"

        # 3) 缺 report → 校验失败（且是 error 不是 warning）
        partial = collect_run_bundle(
            case_dir, orig, fixed,
            backend=StaticBundleBackend({"baseline": samples[case_dir.name]["baseline"]}))
        bad = validate_bundle(partial, case_dir=case_dir)
        assert not bad.ok and any("report" in e for e in bad.errors), bad.errors
        assert "report" in bad.missing_layers

        # 4) 缺建议层 → 仅警告，不失败
        assert any("建议层" in w for w in bad.warnings), bad.warnings

        # 5) 报告类型错误被抓
        wrong_type = collect_run_bundle(
            case_dir, orig, fixed, backend=StaticBundleBackend({"report": ["not-a-mapping"]}))
        assert not validate_bundle(wrong_type, case_dir=case_dir).ok

        # 6) baseline.repeats_ms 非数值数组被抓
        wrong_baseline = collect_run_bundle(
            case_dir, orig, fixed,
            backend=StaticBundleBackend({"report": {"findings": []},
                                         "baseline": {"repeats_ms": ["x"]}}))
        assert not validate_bundle(wrong_baseline, case_dir=case_dir).ok

        # 7) NullBackend：逐层未实现 → 缺 report；且异常信息指向执行侧
        null_bundle = collect_run_bundle(case_dir, orig, fixed)  # 缺省 NullBackend
        assert set(null_bundle["collection"]["layers_unimplemented"]) == set(LAYERS)
        try:
            NullBackend().collect_report(CollectRequest(case_dir.name, case_dir, orig, fixed))
        except CollectionNotImplemented as exc:
            assert exc.layer == "report" and exc.backend == "null-execution"
        else:  # pragma: no cover
            raise AssertionError("NullBackend 应当抛 CollectionNotImplemented")

        # 8) directory 后端：分文件读取
        raw = tmp_path / "raw"
        raw.mkdir()
        for layer, value in samples[case_dir.name].items():
            (raw / f"{layer}.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        dir_bundle = collect_run_bundle(case_dir, orig, fixed, backend=DirectoryBackend(raw))
        assert validate_bundle(dir_bundle, case_dir=case_dir).ok

        # 9) 模块不含任何执行 SUT 的入口
        source = Path(__file__).read_text(encoding="utf-8")
        for token in ("subprocess", "os.system", "os.popen", "socket"):
            assert f"import {token}" not in source, f"采集模块不应引入 {token}"

    print("[ OK ] collect_run_bundle.py 自检通过：3 种后端、指纹溯源、"
          "必需/建议层校验、NullBackend 边界断言均符合预期")


if __name__ == "__main__":
    raise SystemExit(main())
