"""A second Agent receives only persisted, evidence-checked diagnosis targets."""

import asyncio

import pytest

from tests.diagnosis.test_n_plus_one import Reader
from tests.repair.test_gates import _handoff


class Store:
    def __init__(self, bundle):
        self.bundle = bundle

    async def load_bundle(self, task_id):
        assert task_id == self.bundle.task.id
        return self.bundle


def test_handoff_exports_persisted_target_without_case_answers() -> None:
    from project_doctor.workflows.repair_handoff import export_repair_handoff

    bundle, finding = _handoff()
    result = asyncio.run(export_repair_handoff(Store(bundle), Reader(), bundle.task.id))
    assert result["task_id"] == bundle.task.id
    assert result["source_commit"] == bundle.task.project.commit
    assert result["context"]["task_id"] == bundle.task.id
    assert result["candidates"][0]["finding_id"] == finding.id
    assert result["candidates"][0]["kind"] == "n_plus_one"
    assert result["candidates"][0]["code_locations"]
    assert "expected_fix" not in str(result)
    assert "case_id" not in str(result)


def test_handoff_rejects_corrupt_or_stale_candidate() -> None:
    from project_doctor.workflows.repair_handoff import export_repair_handoff

    bundle, finding = _handoff()
    with pytest.raises(ValueError, match="evidence"):
        asyncio.run(export_repair_handoff(Store(bundle), Reader(False), bundle.task.id))
    finding.code_locations[0].commit = "another-commit"
    with pytest.raises(ValueError, match="commit"):
        asyncio.run(export_repair_handoff(Store(bundle), Reader(), bundle.task.id))


def test_handoff_with_no_candidate_is_explicit() -> None:
    from project_doctor.workflows.repair_handoff import export_repair_handoff

    bundle, _ = _handoff()
    bundle.findings = []
    result = asyncio.run(export_repair_handoff(Store(bundle), Reader(), bundle.task.id))
    assert result["candidates"] == []
    assert result["task_id"] == bundle.task.id
