"""Inspect diagnosed application source and apply bounded diffs to isolated copies."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from project_doctor.models.common import safe_relative_path
from project_doctor.models.finding import Finding
from project_doctor.models.n_plus_one import BatchQuerySpec
from project_doctor.models.repair import RepairTarget, SourceFileView, SourceRepairTarget

_METHOD = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_MYBATIS_PARAMETER = re.compile(r"#\{[^}]+\}")
_JAVA_STRING = re.compile(r'"((?:\\.|[^"\\\n])*)"')


def _java_sql_strings(source: str) -> str:
    return " ".join(match.replace(r"\"", '"') for match in _JAVA_STRING.findall(source))


@dataclass(frozen=True)
class PatchedSource:
    root: Path
    source_commit: str
    patch_sha256: str
    source_sha256: str
    changed_paths: tuple[str, ...]
    before_hashes: dict[str, str]
    after_hashes: dict[str, str]


def _git(root: Path, *args: str, input_text: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            # Never inherit the MCP stdio transport as Git's stdin.
            input=input_text if input_text is not None else "",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Git source verification or patch application failed") from exc
    if result.returncode != 0:
        raise ValueError(
            f"Git source verification or patch application failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_tree_sha256(root: Path) -> str:
    """Bind a build to every regular file in its isolated source tree."""
    digest = hashlib.sha256()
    for file in sorted(root.rglob("*")):
        if file.is_symlink():
            raise ValueError("symlinked source is not allowed")
        if file.is_file():
            digest.update(file.relative_to(root).as_posix().encode("utf-8"))
            digest.update(file.read_bytes())
    return digest.hexdigest()


def _copy_tracked_source(root: Path, destination: Path) -> None:
    """Copy exactly committed files, excluding ignored secrets and generated output."""
    paths = [item for item in _git(root, "ls-files", "-z", "--", ".").split("\0") if item]
    if not paths:
        raise ValueError("target repository has no tracked source files")
    destination.mkdir(parents=True)
    for name in paths:
        relative = safe_relative_path(name)
        source = (root / relative).resolve(strict=True)
        if not source.is_relative_to(root) or (root / relative).is_symlink():
            raise ValueError("tracked source contains an unsafe symlink")
        if not source.is_file():
            raise ValueError("tracked source entry is not a regular file")
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)


def _context(lines: list[str], line_number: int) -> str:
    first = max(0, line_number - 21)
    last = min(len(lines), line_number + 20)
    return "".join(f"{index + 1}: {lines[index]}" for index in range(first, last))


def inspect_source_target(root: Path, finding: Finding, commit: str) -> SourceRepairTarget:
    """Expose versioned application source without choosing a repair mechanism."""
    root = root.resolve(strict=True)
    if _git(root, "rev-parse", "HEAD") != commit:
        raise ValueError("diagnostic source commit does not match the target")
    if _git(root, "status", "--porcelain", "--", "."):
        raise ValueError("target source is dirty; an exact committed baseline is required")
    names = [name for name in _git(root, "ls-files", "-z", "--", ".").split("\0") if name]
    allowed: dict[str, str] = {}
    for name in names:
        path = safe_relative_path(name)
        if not path.startswith("src/main/") or Path(path).suffix not in {".java", ".xml"}:
            continue
        file = root / path
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(root):
            raise ValueError("application source contains an unsafe path")
        if file.stat().st_size > 512_000:
            continue
        allowed[path] = _sha256(file.read_bytes())
    if not allowed or len(allowed) > 1000:
        raise ValueError("application source scope is empty or too large")
    contexts: dict[str, str] = {}
    for location in finding.code_locations:
        path = safe_relative_path(location.path)
        if location.commit != commit or path not in allowed:
            raise ValueError("diagnosed code location is outside supported application source")
        lines = (root / path).read_text(encoding="utf-8").splitlines(keepends=True)
        if location.line > len(lines):
            raise ValueError("diagnosed code location is outside the source file")
        contexts[path] = _context(lines, location.line)
    if not contexts:
        raise ValueError("repair target has no diagnosed source context")
    return SourceRepairTarget(root, commit, tuple(finding.code_locations), allowed, contexts)


def read_source_context(
    target: SourceRepairTarget, path: str, start_line: int, line_count: int
) -> SourceFileView:
    """Read a bounded window from one hashed, tracked application-source file."""
    path = safe_relative_path(path)
    if path not in target.allowed_hashes:
        raise ValueError("source path is outside the permitted application scope")
    if start_line < 1 or not 1 <= line_count <= 120:
        raise ValueError("source window must start at line 1 or later and contain 1-120 lines")
    file = target.root / path
    if file.is_symlink() or not file.resolve(strict=True).is_relative_to(target.root):
        raise ValueError("source path escaped the target root")
    if _sha256(file.read_bytes()) != target.allowed_hashes[path]:
        raise ValueError("source changed after inspection")
    lines = file.read_text(encoding="utf-8").splitlines(keepends=True)
    if start_line > len(lines):
        raise ValueError("source window starts after the last line")
    end = min(len(lines), start_line + line_count - 1)
    context = "".join(f"{index + 1}: {lines[index]}" for index in range(start_line - 1, end))
    return SourceFileView(path=path, sha256=target.allowed_hashes[path], context=context)


def inspect_target(root: Path, spec: BatchQuerySpec, commit: str) -> RepairTarget:
    """Require a clean Git source and one exact Java mapper/caller pair."""
    root = root.resolve(strict=True)
    if spec.strategy != "batch_in" or not spec.child_code_location.path.endswith(".java"):
        raise ValueError("Java/MyBatis annotation adapter only supports batch_in Java mapper")
    if commit != spec.child_code_location.commit or _git(root, "rev-parse", "HEAD") != commit:
        raise ValueError("diagnostic source commit does not match the target")
    if _git(root, "status", "--porcelain", "--", "."):
        raise ValueError("target source is dirty; an exact committed baseline is required")
    mapper_path = safe_relative_path(spec.child_code_location.path)
    mapper_file = (root / mapper_path).resolve(strict=True)
    if not mapper_file.is_relative_to(root):
        raise ValueError("mapper path escaped the target root")
    mapper_lines = mapper_file.read_text(encoding="utf-8").splitlines(keepends=True)
    target_line = spec.child_code_location.line
    if target_line > len(mapper_lines):
        raise ValueError("mapper code location is outside the source file")
    method: str | None = None
    for start, line in enumerate(mapper_lines):
        if "@Select" not in line:
            continue
        for end in range(start + 1, min(start + 30, len(mapper_lines))):
            candidate = mapper_lines[end]
            if ";" not in candidate:
                continue
            match = _METHOD.search(candidate)
            if match:
                if start + 1 <= target_line <= end + 1:
                    sql = _java_sql_strings("".join(mapper_lines[start:end]))
                    template = _MYBATIS_PARAMETER.sub("?", sql)
                    if " ".join(template.lower().split()) != " ".join(
                        spec.child_template.lower().split()
                    ):
                        raise ValueError("mapper SQL differs from the diagnostic child template")
                    method = match.group(1)
                break
        if method is not None:
            break
    if method is None:
        raise ValueError("cannot locate the diagnosed MyBatis mapper method")
    child_table_match = re.search(
        r"\bFROM\s+([A-Za-z_][A-Za-z_0-9]*)\b", spec.child_template, re.IGNORECASE
    )
    if child_table_match is None or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", spec.key_column):
        raise ValueError("child template has no simple table and association key")
    candidates: list[tuple[str, int, list[str]]] = []
    call_pattern = re.compile(r"\.\s*" + re.escape(method) + r"\s*\(")
    for file in sorted(root.rglob("*.java")):
        relative = file.relative_to(root).as_posix()
        if file == mapper_file or any(
            part in {"target", "build", ".git"} for part in Path(relative).parts
        ):
            continue
        if file.is_symlink():
            raise ValueError("symlinked Java source is not allowed")
        if not relative.startswith("src/main/java/"):
            continue
        lines = file.read_text(encoding="utf-8").splitlines(keepends=True)
        for index, line in enumerate(lines, start=1):
            if call_pattern.search(line) and not line.lstrip().startswith(("//", "*")):
                candidates.append((relative, index, lines))
    if len(candidates) != 1:
        raise ValueError("diagnosed mapper method has no unique caller")
    caller_path, caller_line, caller_lines = candidates[0]
    caller_file = root / caller_path
    argument = re.search(
        r"\.\s*" + re.escape(method) + r"\s*\(\s*\w+\.get([A-Z]\w*)\(\)\s*\)",
        caller_lines[caller_line - 1],
    )
    if argument is None:
        raise ValueError("cannot identify the parent result key passed to the child query")
    parent_key_column = re.sub(r"(?<!^)(?=[A-Z])", "_", argument.group(1)).lower()
    return RepairTarget(
        root=root,
        source_commit=commit,
        mapper_path=mapper_path,
        mapper_line=target_line,
        mapper_method=method,
        child_table=child_table_match.group(1),
        key_column=spec.key_column,
        mapper_sha256=_sha256(mapper_file.read_bytes()),
        mapper_context=_context(mapper_lines, target_line),
        caller_path=caller_path,
        caller_line=caller_line,
        parent_key_column=parent_key_column,
        caller_sha256=_sha256(caller_file.read_bytes()),
        caller_context=_context(caller_lines, caller_line),
    )


def _changed_paths(diff: str, allowed: set[str], caller_path: str | None) -> tuple[str, ...]:
    if not diff.strip() or "\x00" in diff or "GIT binary patch" in diff:
        raise ValueError("patch scope is empty or includes binary content")
    paths: list[str] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) != 4 or any(
                part.removeprefix(prefix) not in allowed
                for part, prefix in zip(parts[2:], ("a/", "b/"), strict=True)
            ):
                raise ValueError("patch scope exceeds diagnosed mapper and caller")
            if not parts[2].startswith("a/") or not parts[3].startswith("b/"):
                raise ValueError("patch scope requires existing repository paths")
            if parts[2][2:] != parts[3][2:]:
                raise ValueError("patch scope cannot rename files")
        elif line.startswith(("--- ", "+++ ")):
            value = line[4:].split("\t", 1)[0]
            if not value.startswith(("a/", "b/")):
                raise ValueError("patch scope requires existing repository paths")
            path = safe_relative_path(value[2:])
            if path not in allowed:
                raise ValueError("patch scope exceeds diagnosed mapper and caller")
            paths.append(path)
        elif line.startswith(
            ("rename ", "copy ", "new file mode", "deleted file mode", "old mode", "new mode")
        ):
            raise ValueError("patch scope cannot rename, add or delete files")
    if caller_path is not None and caller_path not in paths:
        raise ValueError("patch scope must change the unique caller")
    if not paths:
        raise ValueError("patch scope has no source file changes")
    return tuple(sorted(set(paths)))


def _patched_select_sql(mapper_source: str, method: str) -> str:
    """Read the annotation attached to the diagnosed method, not unrelated SQL."""
    lines = mapper_source.splitlines()
    method_pattern = re.compile(r"\b" + re.escape(method) + r"\s*\(")
    matches: list[str] = []
    for start, line in enumerate(lines):
        if "@Select" not in line:
            continue
        for end in range(start + 1, min(start + 30, len(lines))):
            candidate = lines[end]
            if ";" not in candidate:
                continue
            if method_pattern.search(candidate):
                matches.append(_java_sql_strings("\n".join(lines[start:end])))
            break
    if len(matches) != 1:
        raise ValueError("patched mapper must retain one diagnosed annotated method")
    return matches[0]


def apply_patch(target: RepairTarget, diff: str, workspace_root: Path) -> PatchedSource:
    """Apply the model diff only inside a new, contained source copy."""
    allowed = {target.mapper_path, target.caller_path}
    changed = _changed_paths(diff, allowed, target.caller_path)
    source_files = {path: (target.root / path).read_bytes() for path in allowed}
    before = {path: _sha256(data) for path, data in source_files.items()}
    if (
        before[target.mapper_path] != target.mapper_sha256
        or before[target.caller_path] != target.caller_sha256
    ):
        raise ValueError("source changed after inspection")
    for file in target.root.rglob("*"):
        if file.is_symlink():
            raise ValueError("symlinked source is not allowed")
    workspace_root = workspace_root.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    digest = _sha256(diff.encode("utf-8"))
    destination = workspace_root / ("repair-" + digest[:20])
    if destination.exists():
        raise ValueError("repair workspace already exists; reconcile before retry")
    _copy_tracked_source(target.root, destination)
    if not destination.resolve().is_relative_to(workspace_root):
        raise ValueError("repair workspace escaped the configured root")
    # MCP clients commonly omit the final LF when serializing a diff string.
    # Add only that terminator for Git; retain the submitted bytes for identity.
    git_diff = diff if diff.endswith("\n") else diff + "\n"
    _git(destination, "apply", "--check", "-", input_text=git_diff)
    _git(destination, "apply", "-", input_text=git_diff)
    after = {path: _sha256((destination / path).read_bytes()) for path in allowed}
    if before[target.caller_path] == after[target.caller_path]:
        raise ValueError("patch did not change the diagnosed caller")
    old_caller = source_files[target.caller_path].decode("utf-8")
    new_caller = (destination / target.caller_path).read_text(encoding="utf-8")
    marker = "." + target.mapper_method + "("
    old_calls = list(re.finditer(re.escape(marker), old_caller))
    new_calls = list(re.finditer(re.escape(marker), new_caller))
    if not old_calls:
        raise ValueError("diagnosed caller has no exact mapper invocation")
    if len(new_calls) >= len(old_calls):
        # Keeping the mapper method name preserves request/SQL instrumentation.
        # Accept it only when its sole call moves before the diagnosed loop.
        loop = list(re.finditer(r"\bfor\s*\([^)]*\)\s*\{", old_caller[: old_calls[0].start()]))
        loop_text = loop[-1].group() if loop else ""
        new_loop = new_caller.find(loop_text) if loop_text else -1
        if not (
            len(old_calls) == len(new_calls) == 1
            and new_loop >= 0
            and new_calls[0].start() < new_loop
        ):
            raise ValueError("patch did not remove the repeated child-query call")
    mapper_source = (destination / target.mapper_path).read_text(encoding="utf-8")
    annotation_sql = _patched_select_sql(mapper_source, target.mapper_method)
    batch_shape = (
        rf"\bFROM\s+{re.escape(target.child_table)}\b"
        rf"[\s\S]*?\b{re.escape(target.key_column)}\s+IN"
        r"\s*<foreach\b[^>]*\bcollection\s*=\s*['\"][A-Za-z_]\w*['\"]"
        r"[^>]*>\s*#\{[A-Za-z_]\w*\}\s*</foreach>"
    )
    if not re.search(batch_shape, annotation_sql, re.IGNORECASE):
        raise ValueError("diagnosed mapper method has no parameterized batch IN query")
    return PatchedSource(
        root=destination,
        source_commit=target.source_commit,
        patch_sha256=digest,
        source_sha256=source_tree_sha256(destination),
        changed_paths=changed,
        before_hashes=before,
        after_hashes=after,
    )


def apply_source_patch(
    target: SourceRepairTarget, diff: str, workspace_root: Path
) -> PatchedSource:
    """Apply a model diff only to tracked application source in an isolated copy."""
    allowed = target.allowed_hashes
    diagnosed = {location.path for location in target.locations}
    changed = _changed_paths(diff, set(allowed), None)
    if not diagnosed.intersection(changed):
        raise ValueError("patch scope misses the diagnosed code location")
    before = {path: _sha256((target.root / path).read_bytes()) for path in changed}
    if any(before[path] != allowed[path] for path in changed):
        raise ValueError("source changed after inspection")
    for file in target.root.rglob("*"):
        if file.is_symlink():
            raise ValueError("symlinked source is not allowed")
    workspace_root = workspace_root.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    digest = _sha256(diff.encode("utf-8"))
    destination = workspace_root / ("repair-" + digest[:20])
    if destination.exists():
        raise ValueError("repair workspace already exists; reconcile before retry")
    _copy_tracked_source(target.root, destination)
    if not destination.resolve().is_relative_to(workspace_root):
        raise ValueError("repair workspace escaped the configured root")
    git_diff = diff if diff.endswith("\n") else diff + "\n"
    _git(destination, "apply", "--check", "-", input_text=git_diff)
    _git(destination, "apply", "-", input_text=git_diff)
    after = {path: _sha256((destination / path).read_bytes()) for path in changed}
    if any(before[path] == after[path] for path in changed):
        raise ValueError("patch contains an unchanged source file")
    return PatchedSource(
        destination,
        target.source_commit,
        digest,
        source_tree_sha256(destination),
        changed,
        before,
        after,
    )


def copy_baseline_source(
    target: RepairTarget | SourceRepairTarget, workspace_root: Path
) -> PatchedSource:
    """Make an immutable-source comparison build beside the patched source."""
    workspace_root = workspace_root.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    destination = workspace_root / "baseline-source"
    if destination.exists():
        raise ValueError("baseline source copy already exists; reconcile before retry")
    if _git(target.root, "rev-parse", "HEAD") != target.source_commit:
        raise ValueError("baseline source commit changed")
    if _git(target.root, "status", "--porcelain", "--", "."):
        raise ValueError("baseline source is dirty")
    _copy_tracked_source(target.root, destination)
    return PatchedSource(
        root=destination,
        source_commit=target.source_commit,
        patch_sha256="0" * 64,
        source_sha256=source_tree_sha256(destination),
        changed_paths=(),
        before_hashes={},
        after_hashes={},
    )
