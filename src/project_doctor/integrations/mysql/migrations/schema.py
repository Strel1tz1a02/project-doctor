"""Minimal MySQL tables: key columns for lookup plus versioned JSON summary columns."""

from __future__ import annotations

from sqlalchemy import JSON, Column, Engine, Integer, MetaData, String, Table

metadata = MetaData()

tasks = Table(
    "tasks",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("status", String(16), nullable=False),
    Column("record_json", JSON, nullable=False),
)

scenarios = Table(
    "scenarios",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("scenario_id", String(64), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("record_json", JSON, nullable=False),
)

hypotheses = Table(
    "hypotheses",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("hypothesis_id", String(64), primary_key=True),
    Column("record_json", JSON, nullable=False),
)

findings = Table(
    "findings",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("finding_id", String(64), primary_key=True),
    Column("record_json", JSON, nullable=False),
)

experiments = Table(
    "experiments",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("experiment_id", String(64), primary_key=True),
    Column("record_json", JSON, nullable=False),
)

operations = Table(
    "operations",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("operation_id", String(64), primary_key=True),
    Column("input_digest", String(64), nullable=False),
    Column("state", String(16), nullable=False),
    Column("request_allowance", Integer, nullable=False, default=0),
    Column("result_json", JSON, nullable=True),
    Column("consumed_json", JSON, nullable=True),
)

evidence_index = Table(
    "evidence_index",
    metadata,
    Column("artifact_id", String(64), primary_key=True),
    Column("record_json", JSON, nullable=False),
)

environment_health = Table(
    "environment_health",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("health", String(16), nullable=False),
    Column("environment_id", String(64), nullable=True),
    Column("fingerprint", String(64), nullable=True),
    Column("baseline_snapshot_id", String(64), nullable=True),
)


def create_schema(engine: Engine) -> None:
    """Create missing tables (idempotent)."""
    metadata.create_all(engine)
