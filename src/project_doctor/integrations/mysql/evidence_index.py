"""Evidence index: artifact_id to EvidenceRef, for orphan detection and report indexing."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from project_doctor.integrations.mysql.migrations.schema import evidence_index
from project_doctor.models.common import EvidenceRef


def index_evidence(conn: Connection, ref: EvidenceRef) -> None:
    """Upsert one artifact ref; called inside the caller's transaction."""
    conn.execute(
        mysql_insert(evidence_index)
        .values(artifact_id=ref.artifact_id, record_json=ref.model_dump())
        .on_duplicate_key_update(record_json=ref.model_dump())
    )


def list_evidence(conn: Connection) -> list[EvidenceRef]:
    """Return every indexed ref; used by reconcile to detect orphaned artifacts."""
    rows: Sequence[Any] = conn.execute(select(evidence_index.c.record_json)).scalars().all()
    return [EvidenceRef.model_validate(row) for row in rows]
