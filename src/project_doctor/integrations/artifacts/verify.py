"""Filesystem verification of artifacts: containment, existence, size and checksum."""

from __future__ import annotations

import hashlib
from pathlib import Path

from project_doctor.models.common import EvidenceCheck, EvidenceRef


def resolve_contained(artifact_root: Path, relative_path: str) -> Path:
    """Resolve a wire-relative path inside artifact_root, rejecting filesystem escapes.

    The model layer already rejects ``..``, absolute paths, backslashes and colons;
    this check additionally resolves symlinks so that a link pointing outside the
    artifact root cannot smuggle content past the boundary.
    """
    root = artifact_root.resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("artifact path escapes the artifact root")
    return target


class FileEvidenceReader:
    """Reads artifacts from disk and verifies containment, size and sha256."""

    def __init__(self, artifact_root: Path) -> None:
        self._root = artifact_root.resolve()

    async def verify(self, refs: list[EvidenceRef]) -> EvidenceCheck:
        missing: list[str] = []
        corrupted: list[str] = []
        reasons: list[str] = []
        for ref in refs:
            try:
                path = resolve_contained(self._root, ref.relative_path)
            except ValueError:
                corrupted.append(ref.artifact_id)
                reasons.append(f"{ref.artifact_id}: artifact escapes the artifact root")
                continue
            if not path.is_file():
                missing.append(ref.artifact_id)
                reasons.append(f"{ref.artifact_id}: artifact file is missing")
                continue
            try:
                size = path.stat().st_size
            except OSError as exc:
                missing.append(ref.artifact_id)
                reasons.append(f"{ref.artifact_id}: cannot stat artifact: {exc}")
                continue
            if size != ref.size_bytes:
                corrupted.append(ref.artifact_id)
                reasons.append(
                    f"{ref.artifact_id}: size mismatch (expected {ref.size_bytes}, found {size})"
                )
                continue
            try:
                digest = self._sha256(path)
            except OSError as exc:
                corrupted.append(ref.artifact_id)
                reasons.append(f"{ref.artifact_id}: cannot read artifact: {exc}")
                continue
            if digest != ref.sha256:
                corrupted.append(ref.artifact_id)
                reasons.append(f"{ref.artifact_id}: sha256 mismatch")
        return EvidenceCheck(
            valid=not (missing or corrupted),
            missing_ids=missing,
            corrupted_ids=corrupted,
            reasons=reasons,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
