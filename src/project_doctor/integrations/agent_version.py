"""Capture the code and checked-in instructions used by an Agent task."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from project_doctor.models.task import AgentVersion


def capture_agent_version(root: Path | None = None) -> AgentVersion:
    if root is None:
        checkout = Path(__file__).resolve().parents[3]
        root = (
            checkout
            if (checkout / "src/project_doctor").is_dir()
            else Path(__file__).resolve().parents[1]
        )
    source_root = root / "src/project_doctor" if (root / "src/project_doctor").is_dir() else root
    paths = sorted(
        [
            *source_root.rglob("*.py"),
            *root.joinpath("agh").glob("*.md"),
            *root.joinpath("agh").glob("*.json"),
            *(p for p in (root / "pyproject.toml", root / "uv.lock") if p.is_file()),
        ],
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not paths:
        raise ValueError("Agent source files are unavailable")
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    if not (root / ".git").exists():
        commit = None
        dirty = None
    else:
        try:
            command = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
                timeout=5,
            )
            status = subprocess.run(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--",
                    "src/project_doctor",
                    "agh",
                    "pyproject.toml",
                    "uv.lock",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            commit = None
            dirty = None
        else:
            commit = command.stdout.strip() if command.returncode == 0 else None
            dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return AgentVersion(
        commit=commit,
        source_sha256=digest.hexdigest(),
        dirty=dirty,
    )
