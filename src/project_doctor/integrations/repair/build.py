"""Build a repaired target from its isolated source and retain the image identity."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from project_doctor.integrations.repair.source import PatchedSource, source_tree_sha256

_IMAGE_DIGEST = re.compile(r"\Asha256:[0-9a-f]{64}\Z")


def inspect_image_digest(image: str, *, timeout_seconds: float = 30.0) -> str:
    """Resolve an existing baseline tag to the immutable local image ID."""
    if shutil.which("docker") is None:
        raise ValueError("Docker CLI is unavailable")
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("baseline image inspection failed") from exc
    digest = result.stdout.strip()
    if result.returncode != 0 or not _IMAGE_DIGEST.fullmatch(digest):
        raise ValueError("baseline image has no valid immutable digest")
    return digest


@dataclass(frozen=True)
class BuiltImage:
    tag: str
    digest: str
    source_sha256: str
    patch_sha256: str
    build_log: str


def build_image(
    source: PatchedSource,
    *,
    timeout_seconds: float = 600.0,
    tag_prefix: str = "project-doctor-repair",
) -> BuiltImage:
    """A source hash, unique tag and Docker image ID bind the code to the retest."""
    if shutil.which("docker") is None:
        raise ValueError("Docker CLI is unavailable")
    if timeout_seconds <= 0:
        raise ValueError("image build timeout must be positive")
    if not (source.root / "Dockerfile").is_file():
        raise ValueError("patched source has no Dockerfile")
    if source_tree_sha256(source.root) != source.source_sha256:
        raise ValueError("patched source changed after validation")
    if tag_prefix not in {"project-doctor-repair", "project-doctor-baseline"}:
        raise ValueError("unsupported repair image tag prefix")
    tag = tag_prefix + ":" + source.source_sha256[:20]
    with tempfile.TemporaryDirectory(prefix="repair-build-", dir=source.root.parent) as temp:
        from pathlib import Path

        iid_file = Path(temp) / "image-id"
        try:
            result = subprocess.run(
                [
                    "docker",
                    "build",
                    "--tag",
                    tag,
                    "--iidfile",
                    str(iid_file),
                    str(source.root),
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("repaired target image build did not finish") from exc
        log = result.stdout + result.stderr
        if result.returncode != 0:
            raise ValueError("repaired target image build failed: " + log[-4000:])
        if not iid_file.is_file():
            raise ValueError("Docker build returned no image digest")
        digest = iid_file.read_text(encoding="utf-8").strip()
        if not _IMAGE_DIGEST.fullmatch(digest):
            raise ValueError("Docker build returned an invalid image digest")
    return BuiltImage(
        tag=tag,
        digest=digest,
        source_sha256=source.source_sha256,
        patch_sha256=source.patch_sha256,
        build_log=log,
    )
