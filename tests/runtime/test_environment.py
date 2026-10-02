"""Unit tests for A2 environment isolation, fingerprinting and compose rendering."""

from __future__ import annotations

import re

import pytest

from project_doctor.features.environments.prepare import (
    compose_project_name,
    environment_fingerprint,
    isolated_workspace_path,
)
from project_doctor.features.environments.restore import restore_verified
from project_doctor.integrations.docker.compose import render_compose

# --- compose project names --------------------------------------------------


def test_compose_project_name_lowercases_and_dashes() -> None:
    assert compose_project_name("Task-1_ABC") == "task-1-abc"
    assert compose_project_name("  Mixed.Case/Id  ") == "mixed-case-id"


def test_compose_project_name_truncates_to_63_chars() -> None:
    name = compose_project_name("a" * 100)
    assert len(name) == 63
    assert name == "a" * 63


def test_compose_project_name_rejects_empty() -> None:
    with pytest.raises(ValueError):
        compose_project_name("___")


def test_isolated_workspace_path_is_per_task(tmp_path) -> None:
    assert isolated_workspace_path(tmp_path, "Task-1") == tmp_path / "task-1"


# --- environment fingerprint ------------------------------------------------


def test_fingerprint_is_deterministic_sha256() -> None:
    fingerprint = environment_fingerprint(commit="commit-1", snapshot_id="snapshot-1")
    assert fingerprint == environment_fingerprint(commit="commit-1", snapshot_id="snapshot-1")
    assert re.fullmatch(r"[0-9a-f]{64}", fingerprint)


def test_fingerprint_changes_with_commit_or_snapshot() -> None:
    base = environment_fingerprint(commit="commit-1", snapshot_id="snapshot-1")
    assert base != environment_fingerprint(commit="commit-2", snapshot_id="snapshot-1")
    assert base != environment_fingerprint(commit="commit-1", snapshot_id="snapshot-2")


# --- restore verdicts -------------------------------------------------------


def test_restore_verified_when_digest_matches_and_index_removed() -> None:
    assert restore_verified(
        actual_snapshot_id="abc", expected_snapshot_id="abc", index_removed=True
    ) == (True, None)


def test_restore_unverified_on_digest_mismatch() -> None:
    verified, reason = restore_verified(
        actual_snapshot_id="tampered", expected_snapshot_id="baseline", index_removed=True
    )
    assert verified is False
    assert reason is not None


def test_restore_unverified_when_index_remains() -> None:
    verified, reason = restore_verified(
        actual_snapshot_id="abc", expected_snapshot_id="abc", index_removed=False
    )
    assert verified is False
    assert reason and "index" in reason


# --- compose rendering ------------------------------------------------------


def test_render_compose_puts_db_credentials_on_db_service() -> None:
    text = render_compose(
        service_image="project-doctor-target:latest",
        service_port=18080,
        db_image="mysql:8.4",
        db_name="app",
        db_user="app",
        db_password="secret",
    )
    assert "  db:" in text
    # MySQL initialization variables belong to the db service, not the app service.
    assert text.index("MYSQL_DATABASE: app") > text.index("  db:")
    assert "MYSQL_ROOT_PASSWORD: secret" in text
    assert "MYSQL_PASSWORD: secret" in text


def test_render_compose_gives_app_connection_vars() -> None:
    text = render_compose(
        service_image="project-doctor-target:latest",
        service_port=18080,
        db_image="mysql:8.4",
        db_name="app",
        db_user="app",
        db_password="secret",
    )
    assert "DB_HOST: db" in text
    assert "DB_NAME: app" in text
    assert "DB_USER: app" in text
    assert "DB_PASSWORD: secret" in text


def test_render_compose_isolates_on_internal_network_and_host_port() -> None:
    text = render_compose(
        service_image="project-doctor-target:latest",
        service_port=18080,
        db_image="mysql:8.4",
        db_name="app",
        db_user="app",
        db_password="secret",
    )
    assert "internal: true" in text
    # The experiment address is the isolated host port, never an external host.
    assert '"18080:8080"' in text
    assert "http://" not in text
