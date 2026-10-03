"""Atomic artifact publication: write, hash, then move into place."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from project_doctor.integrations.artifacts.verify import resolve_contained
from project_doctor.models.common import EvidenceRef, safe_relative_path


async def publish_artifact(
    artifact_root: Path,
    relative_path: str,
    content: bytes,
    media_type: str,
    format_version: str,
) -> EvidenceRef:
    """Write ``content`` to a sibling temp file, then atomically rename it into place.

    A ref is returned only after the file is fully written and fsynced. Any failure
    leaves no partial artifact and therefore no usable index entry; the caller never
    receives a ref for a file that was not durably placed.
    """
    safe_relative_path(relative_path)
    target = resolve_contained(artifact_root, relative_path)
    digest = hashlib.sha256(content).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".publish-", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return EvidenceRef(
        artifact_id=hashlib.sha256(
            f"{relative_path}\n{media_type}\n{format_version}\n{digest}".encode()
        ).hexdigest(),
        relative_path=relative_path,
        media_type=media_type,
        format_version=format_version,
        sha256=digest,
        size_bytes=len(content),
    )
