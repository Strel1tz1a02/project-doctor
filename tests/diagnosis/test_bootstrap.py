from pathlib import Path

import pytest

from project_doctor.entrypoints.bootstrap import bootstrap
from project_doctor.entrypoints.settings import Settings


def test_missing_a_factory_does_not_silently_fall_back_to_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    settings = Settings.model_validate_json(
        (root / "config/settings.example.json").read_text("utf-8")
    )

    def missing_module(name: str) -> None:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(
        "project_doctor.entrypoints.bootstrap.importlib.import_module", missing_module
    )
    with pytest.raises(RuntimeError, match="工厂尚未就绪"):
        bootstrap(settings, {})


def test_real_factories_require_platform_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[2]
    settings = Settings.model_validate_json(
        (root / "config/settings.example.json").read_text("utf-8")
    )
    monkeypatch.delenv("PROJECT_DOCTOR_PLATFORM_DSN", raising=False)
    with pytest.raises(RuntimeError, match="platform secret.*not set"):
        bootstrap(settings, {})
