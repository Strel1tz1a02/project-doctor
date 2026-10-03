from pathlib import Path

import pytest

from project_doctor.entrypoints.bootstrap import bootstrap
from project_doctor.entrypoints.settings import Settings


def test_missing_a_factory_does_not_silently_fall_back_to_fake() -> None:
    monkeypatch.setenv("PROJECT_DOCTOR_PLATFORM_DSN", "mock_dsn_for_test")
    root = Path(__file__).resolve().parents[2]
    settings = Settings.model_validate_json(
        (root / "config/settings.example.json").read_text("utf-8")
    )
    with pytest.raises(RuntimeError, match="工厂尚未就绪"):
        bootstrap(settings, {})
