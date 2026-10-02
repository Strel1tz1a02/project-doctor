"""Prevent SDK leakage into shared contracts and enforce generated schema freshness."""

import ast
import importlib
import inspect
import json
from pathlib import Path

from project_doctor.models.common import Contract

ROOT = Path(__file__).resolve().parents[2]


def test_models_only_import_models_and_validation_dependencies() -> None:
    for path in (ROOT / "src/project_doctor/models").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(
                    (
                        "project_doctor.features",
                        "project_doctor.integrations",
                        "project_doctor.entrypoints",
                        "project_doctor.workflows",
                        "mcp",
                        "sqlalchemy",
                        "httpx",
                    )
                ), path


def test_all_published_schemas_match_code() -> None:
    published = ROOT / "docs/contracts/v0.1"
    expected_names = set()
    for path in (ROOT / "src/project_doctor/models").glob("*.py"):
        if path.stem == "__init__":
            continue
        module = importlib.import_module(f"project_doctor.models.{path.stem}")
        for name, candidate in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(candidate, Contract)
                and candidate is not Contract
                and candidate.__module__ == module.__name__
            ):
                expected_names.add(f"{name}.json")
                schema = json.loads((published / f"{name}.json").read_text(encoding="utf-8"))
                assert schema == candidate.model_json_schema(), name
    assert {path.name for path in published.glob("*.json")} == expected_names


def test_three_ports_import_without_runtime_dependencies() -> None:
    for module in (
        "project_doctor.features.experiments.ports",
        "project_doctor.features.diagnosis.ports",
        "project_doctor.workflows.task_ports",
    ):
        importlib.import_module(module)
