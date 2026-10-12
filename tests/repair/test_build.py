"""A repaired source must produce a content-addressed image, never latest."""

import subprocess
from pathlib import Path

import pytest

from project_doctor.integrations.repair.build import build_image
from project_doctor.integrations.repair.source import PatchedSource, source_tree_sha256


def _source(tmp_path: Path) -> PatchedSource:
    root = tmp_path / "repair-source"
    root.mkdir()
    (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    return PatchedSource(
        root=root,
        source_commit="base",
        patch_sha256="a" * 64,
        source_sha256=source_tree_sha256(root),
        changed_paths=("src/main/java/App.java",),
        before_hashes={"src/main/java/App.java": "c" * 64},
        after_hashes={"src/main/java/App.java": "d" * 64},
    )


def test_build_records_digest_of_patched_image(tmp_path: Path, monkeypatch) -> None:
    source = _source(tmp_path)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        iid = Path(args[args.index("--iidfile") + 1])
        iid.write_text("sha256:" + "e" * 64, encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="built", stderr="")

    monkeypatch.setattr("project_doctor.integrations.repair.build.shutil.which", lambda _: "docker")
    monkeypatch.setattr("project_doctor.integrations.repair.build.subprocess.run", fake_run)
    image = build_image(source)
    assert image.digest == "sha256:" + "e" * 64
    assert image.tag == "project-doctor-repair:" + source.source_sha256[:20]
    assert calls[0][-1] == str(source.root)
    assert "latest" not in image.tag


def test_build_rejects_missing_docker_or_digest(tmp_path: Path, monkeypatch) -> None:
    source = _source(tmp_path)
    monkeypatch.setattr("project_doctor.integrations.repair.build.shutil.which", lambda _: None)
    with pytest.raises(ValueError, match="Docker"):
        build_image(source)
    monkeypatch.setattr("project_doctor.integrations.repair.build.shutil.which", lambda _: "docker")
    monkeypatch.setattr(
        "project_doctor.integrations.repair.build.subprocess.run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="built", stderr=""),
    )
    with pytest.raises(ValueError, match="digest"):
        build_image(source)
