"""A0 target probe: reference target shape (offline) and real end-to-end (skip-gated).

The offline tests assert the reference bundle in ``demo/reference/`` is a valid
Project Doctor target shape: a single-index recipe, a strict-contract scenario
manifest, and a Dockerfile bound to the isolated service port + DB env vars.

The end-to-end test drives the real Docker gateway (compose up -> baseline dump ->
one valid request -> restore -> digest verify). It skips unless ``docker`` and
``PROJECT_DOCTOR_TARGET_REPO`` are available, and the app image has been built:

    docker build -t project-doctor-target:latest <target_repo>
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.experiments.interventions import parse_index_recipe
from project_doctor.features.scenarios.discover import discover
from project_doctor.integrations.docker.gateway import DockerEnvironmentGateway
from project_doctor.integrations.http.requests import RestrictedHttpClient, check_assertions
from project_doctor.models.environment import ProjectInput
from project_doctor.models.scenario import Scenario
from project_doctor.models.task import CallContext

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "demo" / "reference"
RECIPE_REF = "recipe:orders-status-created"
COMMIT = "9f497db5d4ea09d37f3d07bcda3471c71c815031"
TARGET_REPO_ENV = "PROJECT_DOCTOR_TARGET_REPO"


def load_manifest() -> dict[str, object]:
    return json.loads((REFERENCE / "manifest.json").read_text(encoding="utf-8"))


def make_project() -> ProjectInput:
    return ProjectInput(
        repo_path="local:slow-query-demo",
        commit=COMMIT,
        supplied_url="http://127.0.0.1:18080",
        recipe_ref=RECIPE_REF,
    )


# -- offline: the reference target shape -------------------------------------


def test_recipe_ref_resolves_to_a_single_index_recipe() -> None:
    name = RECIPE_REF.removeprefix("recipe:")
    recipe_file = REFERENCE / "recipes" / f"{name}.sql"
    assert recipe_file.is_file()
    recipe = parse_index_recipe(recipe_file.read_text(encoding="utf-8"))
    assert recipe.name == "idx_orders_status_created"
    assert recipe.table == "orders"
    assert recipe.columns == ("status", "created_at")
    assert recipe.unique is False
    assert recipe.drop_sql == "DROP INDEX idx_orders_status_created ON orders"


def test_reference_dockerfile_targets_service_port_and_db_env() -> None:
    dockerfile = (REFERENCE / "Dockerfile").read_text(encoding="utf-8")
    assert "EXPOSE 8080" in dockerfile
    assert "DB_HOST" in dockerfile
    assert "DB_PORT" in dockerfile


def test_manifest_discovers_one_valid_scenario() -> None:
    scenarios = discover(make_project(), load_manifest())
    assert [scenario.id for scenario in scenarios] == ["slow-query-orders-search"]
    scenario = scenarios[0]
    # Round-trips the strict contract (extra=forbid, validate_assignment).
    Scenario.model_validate(scenario.model_dump())
    step = scenario.steps[0]
    assert step.relative_path == "/api/orders/search"
    assert set(step.params) == {"email", "status", "page", "size"}
    assert step.assertions.status_code == 200
    assert scenario.cache.state == "cold"
    assert scenario.cache.preparation_recipe_ref


def test_manifest_flags_deferred_concerns_as_uncovered_paths() -> None:
    scenario = discover(make_project(), load_manifest())[0]
    assert any("N+1" in path for path in scenario.uncovered_paths)
    assert any("deep-pagination" in path for path in scenario.uncovered_paths)
    assert any("leading-wildcard" in path for path in scenario.uncovered_paths)


def test_project_input_commits_to_the_fixed_target_commit() -> None:
    project = make_project()
    assert project.commit == COMMIT
    assert project.recipe_ref == RECIPE_REF
    ProjectInput.model_validate(project.model_dump())


# -- real end-to-end probe (skips without Docker + target repo; 未验证) ------


def _make_settings(tmp_path: Path, target_repo: Path) -> Settings:
    return Settings(
        platform_dsn_ref="env:PROJECT_DOCTOR_PLATFORM_DSN",
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "isolated",
        target_repo_root=target_repo,
        # The isolated service is published on the host loopback port.
        allowed_target_network="127.0.0.0/8",
        tool_timeouts={"prepare_environment": 600.0, "run_experiment": 600.0},
        model_config_ref="file:agh/model.local.json",
    )


@pytest.fixture
def real_target(tmp_path: Path) -> tuple[Path, Path]:
    if not shutil.which("docker"):
        pytest.skip("docker not available; real target probe not run (未验证)")
    target_repo = os.environ.get(TARGET_REPO_ENV)
    if not target_repo:
        pytest.skip(f"{TARGET_REPO_ENV} not set; real target probe not run (未验证)")
    root = Path(target_repo).resolve()
    if not (root / "Dockerfile").is_file() or not (root / "recipes").is_dir():
        pytest.skip("target repo lacks Dockerfile/recipes; real target probe not run (未验证)")
    return tmp_path, root


def test_target_probe_end_to_end(real_target: tuple[Path, Path]) -> None:
    """Compose up -> baseline dump -> one valid request -> restore -> digest verify."""
    tmp_path, target_repo = real_target
    settings = _make_settings(tmp_path, target_repo)
    gateway = DockerEnvironmentGateway(
        settings,
        db_service="db",
        db_name="app",
        db_user="app",
        db_password="app",
        db_image="mysql:8.4",
        service_image="project-doctor-target:latest",
        service_port=18080,
    )
    context = CallContext(
        task_id="task-a0-probe",
        operation_id="op:prepare",
        agh_session_id="session-a0",
        tool_call_id="call-a0",
    )

    prepared = asyncio.run(gateway.prepare(make_project(), context))
    assert prepared.baseline_snapshot_id

    step = discover(make_project(), load_manifest())[0].steps[0]
    http = RestrictedHttpClient(
        base_url=prepared.isolated_base_url,
        allowed_network=settings.allowed_target_network,
        timeout=60.0,
    )
    response = asyncio.run(http.request(step))
    valid, reasons = check_assertions(step.assertions, response)
    assert response.status_code == 200, f"unexpected status {response.status_code}"
    assert valid, reasons

    restored = asyncio.run(
        gateway.restore(
            prepared.environment_id,
            prepared.baseline_snapshot_id,
            context,
            prepared.baseline_dump,
        )
    )
    assert restored.verified, restored.reason
