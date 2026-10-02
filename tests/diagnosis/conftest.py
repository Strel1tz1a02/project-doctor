import json
from pathlib import Path

import pytest

from project_doctor.models.task import TaskBundle


@pytest.fixture
def bundle() -> TaskBundle:
    root = Path(__file__).resolve().parents[1]
    case = json.loads((root / "contracts/fixtures/verified_slow_query.json").read_text("utf-8"))
    return TaskBundle.model_validate(case["bundle"])
