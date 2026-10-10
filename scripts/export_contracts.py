"""Export deterministic public JSON schemas; run with uv run python scripts/export_contracts.py."""

import importlib
import inspect
import json
from pathlib import Path

from project_doctor.models.common import Contract

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "common",
    "dataset",
    "environment",
    "errors",
    "experiment",
    "finding",
    "hypothesis",
    "lock",
    "n_plus_one",
    "observation",
    "scenario",
    "task",
)


def export() -> None:
    destination = ROOT / "docs" / "contracts" / "v0.1"
    destination.mkdir(parents=True, exist_ok=True)
    for name in MODULES:
        module = importlib.import_module(f"project_doctor.models.{name}")
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(candidate, Contract)
                and candidate is not Contract
                and candidate.__module__ == module.__name__
            ):
                content = json.dumps(candidate.model_json_schema(), ensure_ascii=False, indent=2)
                # Force LF so the export is byte-stable across Windows/Unix checkouts.
                with (destination / f"{candidate.__name__}.json").open(
                    "w", encoding="utf-8", newline="\n"
                ) as handle:
                    handle.write(content + "\n")


if __name__ == "__main__":
    export()
