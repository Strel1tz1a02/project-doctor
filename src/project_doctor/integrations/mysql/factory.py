"""Composition factory for the MySQL-backed TaskStore."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine

from project_doctor.entrypoints.settings import Settings
from project_doctor.integrations.mysql.migrations.schema import create_schema
from project_doctor.integrations.mysql.task_store import MySQLTaskStore
from project_doctor.workflows.task_ports import TaskStore


def resolve_secret_ref(ref: str) -> str:
    """Resolve an ``env:`` or ``file:`` credential reference into its secret value."""
    if ref.startswith("env:"):
        name = ref[4:]
        value = os.environ.get(name)
        if not value:
            raise RuntimeError(f"platform secret {name} is not set in the environment")
        return value
    if ref.startswith("file:"):
        path = Path(ref[5:])
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"platform secret file {path} is not readable") from exc
        if not value:
            raise RuntimeError(f"platform secret file {path} is empty")
        return value
    raise ValueError("platform_dsn_ref must use an env: or file: reference")


def build_store(settings: Settings) -> TaskStore:
    """Resolve the platform DSN, ensure the schema, and return the real store."""
    dsn = resolve_secret_ref(settings.platform_dsn_ref)
    engine = create_engine(dsn, pool_pre_ping=True)
    create_schema(engine)
    return MySQLTaskStore(engine)
