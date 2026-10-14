"""Read-only export of one persisted diagnosis for a separate repair Agent."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import create_engine

from project_doctor.entrypoints.settings import Settings
from project_doctor.integrations.artifacts.verify import FileEvidenceReader
from project_doctor.integrations.mysql.factory import resolve_secret_ref
from project_doctor.integrations.mysql.task_store import MySQLTaskStore
from project_doctor.workflows.repair_handoff import export_repair_handoff


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    settings = Settings.model_validate_json(args.settings.read_text(encoding="utf-8"))
    engine = create_engine(resolve_secret_ref(settings.platform_dsn_ref), pool_pre_ping=True)
    try:
        payload = asyncio.run(export_repair_handoff(
            MySQLTaskStore(engine), FileEvidenceReader(settings.artifact_root), args.task_id
        ))
    finally:
        engine.dispose()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
