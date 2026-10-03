"""Artifact publication and verification: containment, size, checksum and atomicity."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from project_doctor.entrypoints.settings import Settings
from project_doctor.integrations.artifacts.factory import build_evidence_reader
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.models.common import EvidenceRef

CONTENT = b'{"plan": "baseline"}'


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        platform_dsn_ref="env:PROJECT_DOCTOR_PLATFORM_DSN",
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "isolated",
        target_repo_root=tmp_path / "target",
        allowed_target_network="172.28.0.0/24",
        tool_timeouts={"run_experiment": 120},
        model_config_ref="file:agh/model.local.json",
    )


def test_publish_then_verify_round_trip(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    ref = asyncio.run(
        publish_artifact(
            settings.artifact_root, "tasks/t1/plan.json", CONTENT, "application/json", "plan.v1"
        )
    )
    assert ref.sha256 == hashlib.sha256(CONTENT).hexdigest()
    assert ref.artifact_id != ref.sha256
    assert ref.size_bytes == len(CONTENT)
    check = asyncio.run(build_evidence_reader(settings).verify([ref]))
    assert check.valid
    assert not check.missing_ids and not check.corrupted_ids and not check.reasons


def test_missing_artifact_is_invalid(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    ref = EvidenceRef(
        artifact_id="missing",
        relative_path="tasks/t1/plan.json",
        media_type="application/json",
        format_version="plan.v1",
        sha256=hashlib.sha256(b"never-written").hexdigest(),
        size_bytes=13,
    )
    check = asyncio.run(build_evidence_reader(settings).verify([ref]))
    assert not check.valid
    assert check.missing_ids == ["missing"]
    assert not check.corrupted_ids


def test_corrupted_checksum_is_invalid(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    ref = asyncio.run(
        publish_artifact(
            settings.artifact_root, "tasks/t1/plan.json", CONTENT, "application/json", "plan.v1"
        )
    )
    (settings.artifact_root / ref.relative_path).write_bytes(b"tampered-content")
    check = asyncio.run(build_evidence_reader(settings).verify([ref]))
    assert not check.valid
    assert check.corrupted_ids == [ref.artifact_id]


def test_size_mismatch_is_invalid(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    ref = asyncio.run(
        publish_artifact(
            settings.artifact_root, "tasks/t1/plan.json", CONTENT, "application/json", "plan.v1"
        )
    )
    (settings.artifact_root / ref.relative_path).write_bytes(b"short")
    check = asyncio.run(build_evidence_reader(settings).verify([ref]))
    assert not check.valid
    assert check.corrupted_ids == [ref.artifact_id]


@pytest.mark.parametrize("path", ["../escape", "a/../../escape", "a\\b", "/absolute"])
def test_publish_rejects_escaping_paths(tmp_path: Path, path: str) -> None:
    settings = make_settings(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(
            publish_artifact(settings.artifact_root, path, CONTENT, "application/json", "plan.v1")
        )


def test_publish_failure_leaves_no_partial_artifact(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.artifact_root.mkdir(parents=True, exist_ok=True)
    (settings.artifact_root / "tasks").write_bytes(b"not-a-directory")
    with pytest.raises(OSError):
        asyncio.run(
            publish_artifact(
                settings.artifact_root, "tasks/t1/plan.json", CONTENT, "application/json", "plan.v1"
            )
        )
    assert not (settings.artifact_root / "tasks" / "t1" / "plan.json").exists()


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(b"secret")
    settings.artifact_root.mkdir(parents=True, exist_ok=True)
    try:
        (settings.artifact_root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks require developer mode or elevated privileges")
    ref = EvidenceRef(
        artifact_id="escape",
        relative_path="link/secret",
        media_type="text/plain",
        format_version="raw.v1",
        sha256=hashlib.sha256(b"secret").hexdigest(),
        size_bytes=6,
    )
    check = asyncio.run(build_evidence_reader(settings).verify([ref]))
    assert not check.valid
    assert check.corrupted_ids == ["escape"]
