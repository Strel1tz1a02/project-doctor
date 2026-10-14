import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from project_doctor.integrations import agent_version
from project_doctor.models.task import AgentVersion, TaskBundle
from project_doctor.workflows.tasks import create_task
from tests.diagnosis.fakes import MemoryStore


def test_agent_version_changes_with_source_content(tmp_path: Path, monkeypatch):
    source = tmp_path / "src/project_doctor/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    instructions = tmp_path / "agh/diagnosis-instructions.md"
    instructions.parent.mkdir()
    instructions.write_text("diagnose\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    def fake_git(args, **kwargs):
        assert kwargs["stdin"] == agent_version.subprocess.DEVNULL
        assert kwargs["timeout"] == 5
        if args[1] == "rev-parse":
            return SimpleNamespace(returncode=0, stdout="a" * 40)
        return SimpleNamespace(returncode=0, stdout=" M src/project_doctor/example.py\n")

    monkeypatch.setattr(agent_version.subprocess, "run", fake_git)
    first = agent_version.capture_agent_version(tmp_path)
    assert first.commit == "a" * 40
    assert first.dirty is True
    source.write_text("VALUE = 2\n", encoding="utf-8")
    second = agent_version.capture_agent_version(tmp_path)
    assert first.source_sha256 != second.source_sha256


def test_agent_version_without_git_keeps_source_identity(tmp_path: Path, monkeypatch):
    source = tmp_path / "src/project_doctor/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(agent_version.subprocess, "run", missing_git)
    version = agent_version.capture_agent_version(tmp_path)
    assert version.commit is None
    assert version.dirty is None
    assert len(version.source_sha256) == 64


def test_agent_version_git_timeout_keeps_source_identity(tmp_path: Path, monkeypatch):
    source = tmp_path / "src/project_doctor/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    def timed_out_git(*args, **kwargs):
        raise agent_version.subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(agent_version.subprocess, "run", timed_out_git)
    version = agent_version.capture_agent_version(tmp_path)
    assert version.commit is None
    assert version.dirty is None
    assert len(version.source_sha256) == 64


def test_task_keeps_captured_agent_version_on_idempotent_retry():
    fixture = Path(__file__).parents[1] / "contracts/fixtures/verified_slow_query.json"
    bundle = TaskBundle.model_validate(json.loads(fixture.read_text(encoding="utf-8"))["bundle"])
    store = MemoryStore(bundle)
    first_version = AgentVersion(commit="a" * 40, source_sha256="b" * 64, dirty=False)
    second_version = AgentVersion(commit="a" * 40, source_sha256="c" * 64, dirty=True)
    first = asyncio.run(
        create_task(
            bundle.task.project,
            bundle.task.limits,
            "version-capture-test",
            store,
            lambda: first_version,
        )
    )
    retry = asyncio.run(
        create_task(
            bundle.task.project,
            bundle.task.limits,
            "version-capture-test",
            store,
            lambda: second_version,
        )
    )
    assert first.agent_version == first_version
    assert retry.agent_version == first_version
