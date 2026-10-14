"""Write handoff.json / repair.json for one run home from its persisted bundle.

Run this before ``export_evaluation_run.py``; the exporter only merges the
registered files and never infers them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from project_doctor.models.task import TaskBundle
from project_doctor.workflows.repair_facts import build_repair_facts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--artifacts-root", type=Path, default=None)
    parser.add_argument("--repair-session-id", default=None)
    parser.add_argument("--repair-session-transcript", type=Path, default=None)
    parser.add_argument("--repair-decision-id", default=None)
    parser.add_argument("--finding-id", default=None)
    args = parser.parse_args()
    home: Path = args.home
    bundle = TaskBundle.model_validate_json((home / "bundle.json").read_text(encoding="utf-8"))
    facts = build_repair_facts(
        bundle,
        artifacts_root=args.artifacts_root or home / "artifacts",
        repair_session_id=args.repair_session_id,
        repair_session_transcript=args.repair_session_transcript,
        repair_decision_id=args.repair_decision_id,
        finding_id=args.finding_id,
    )
    for name, payload in (("handoff.json", facts.handoff), ("repair.json", facts.repair)):
        target = home / name
        if payload is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for note in facts.notes:
        print(f"note: {note}")


if __name__ == "__main__":
    main()
