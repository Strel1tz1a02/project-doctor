import pytest
from pydantic import ValidationError

from project_doctor.features.scenarios.applicability import applicability
from project_doctor.features.scenarios.deduplicate import dedup_key
from project_doctor.features.scenarios.discover import discover
from project_doctor.models.task import TaskBundle


def test_discovery_preserves_sources_and_unknowns(bundle: TaskBundle) -> None:
    scenarios = discover(bundle.task.project, {"scenarios": [bundle.scenarios[0].model_dump()]})
    assert scenarios[0].source == "repository"
    assert any("合成" in item for item in applicability(scenarios[0]))


def test_same_url_different_preparation_not_deduplicated(bundle: TaskBundle) -> None:
    original = bundle.scenarios[0]
    other = original.model_copy(update={"preparation_recipe_ref": "recipe:other"})
    assert dedup_key(original) != dedup_key(other)


def test_same_url_different_parameter_or_load_not_deduplicated(bundle: TaskBundle) -> None:
    original = bundle.scenarios[0]
    data = original.model_dump(mode="json")
    data["steps"][0]["params"]["customer_id"] = 20
    changed = type(original).model_validate(data)
    assert dedup_key(original) != dedup_key(changed)


def test_missing_business_assertion_rejected(bundle: TaskBundle) -> None:
    candidate = bundle.scenarios[0].model_dump()
    candidate["steps"][0]["assertions"]["business"] = []
    with pytest.raises(ValidationError):
        discover(bundle.task.project, {"scenarios": [candidate]})


def test_plaintext_credential_is_not_persisted(bundle: TaskBundle) -> None:
    candidate = bundle.scenarios[0].model_dump()
    candidate["steps"][0]["params"]["password"] = "do-not-store"
    candidate["steps"][0]["parameter_sources"]["password"] = {
        "source": "user_sample",
        "reference": "user-provided",
    }
    with pytest.raises(ValueError, match="敏感参数"):
        discover(bundle.task.project, {"scenarios": [candidate]})
