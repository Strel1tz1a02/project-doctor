"""Pure preparation decisions: fingerprints, compose project names and workspace paths."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_DISALLOWED = re.compile(r"[^a-z0-9]+")


def compose_project_name(task_id: str) -> str:
    """A deterministic, Docker-compose-safe project name so environments never collide.

    Compose project names must be lowercase alphanumerics plus ``-``/``_``; deriving
    from the task id keeps every isolated service under its own project.
    """
    cleaned = _DISALLOWED.sub("-", task_id.lower()).strip("-")
    if not cleaned:
        raise ValueError("task id yields an empty compose project name")
    return cleaned[:63]


def isolated_workspace_path(workspace_root: Path, task_id: str) -> Path:
    """The per-task isolated copy directory, keyed by the compose project name."""
    return workspace_root / compose_project_name(task_id)


def environment_fingerprint(*, commit: str, snapshot_id: str) -> str:
    """A deterministic fingerprint over the fixed environment identity.

    Only commit and baseline snapshot are known at prepare time and again at run time,
    so they are what the fingerprint can depend on. Observation configuration and cache
    conditions are verified separately by the diagnosis gates, and the temporary index
    change is the one allowed variable, so neither enters this hash: baseline and
    candidate groups must share a single fingerprint.
    """
    payload = f"commit={commit}\nsnapshot={snapshot_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
