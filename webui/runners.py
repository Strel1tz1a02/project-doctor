"""Run manager for the demo console.

Two execution adapters share one in-memory run registry:

* ``offline`` — score the already-collected golden run bundles with the frozen
  ``run_eval.run()`` scorer. Millisecond-fast, always available, no model/DB/Docker.
* ``real`` — drive the external AGH CLI (``node $aghCli``) per case, export each run
  bundle, then score the result without ``--only-bundled``.

The scorer lives outside the SUT (``datasets/`` is a standalone third party, exactly like
this ``webui/``). Import it the way ``datasets/evaluation/test_golden_bundle.py`` does:
put ``datasets/evaluation`` on ``sys.path``, then ``import run_eval``; ``run_eval.py`` adds
its own sibling + ``datasets/tools`` directories on import.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agh_runner import run_case

_EVAL_DIR = Path(__file__).resolve().parents[1] / "datasets" / "evaluation"
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

import run_eval as R  # noqa: E402

#: Directories under ``datasets/`` that are infrastructure, never a case.
RESERVED_DIRS = {"docs", "tools", "evaluation", "_schema"}

_FINISHED = {"ok", "failed", "missing", "skipped"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(config_path: Path | None) -> dict[str, Any]:
    root = repo_root()
    if config_path is None:
        config_path = root / "webui" / "config.json"
        if not config_path.exists():
            config_path = root / "webui" / "config.example.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["_config_path"] = str(config_path)
    return data


def _abs(config: dict[str, Any], key: str) -> Path | None:
    """Resolve a repo-relative config path to an absolute one; ``None`` when unset/empty."""
    value = config.get(key)
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else repo_root() / path


def list_cases(cases_root: Path) -> list[dict[str, Any]]:
    """Read the case metadata the matrix renders, skipping infra directories."""
    cases: list[dict[str, Any]] = []
    for path in sorted(cases_root.glob("*/case.json")):
        name = path.parent.name
        if name.startswith("_") or name in RESERVED_DIRS:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        expected = data.get("expected") or {}
        symptom = data.get("symptom") or {}
        cases.append(
            {
                "case_id": data.get("case_id", name),
                "title": data.get("title", name),
                "case_type": data.get("case_type", "normal"),
                "difficulty": data.get("difficulty", ""),
                "problem_kind": data.get("problem_kind", ""),
                "symptom_summary": symptom.get("summary", ""),
                "expected_decision": expected.get("decision", ""),
            }
        )
    return cases


def detect_env(config: dict[str, Any]) -> dict[str, Any]:
    root = repo_root()
    docker = shutil.which("docker") is not None
    node = shutil.which("node") is not None
    agh_cli = _abs(config, "agh_cli")
    agh_ready = node and agh_cli is not None and agh_cli.exists()
    dsn = bool(os.environ.get("PROJECT_DOCTOR_PLATFORM_DSN"))
    model_key = (root / "agh" / "model.local.json").exists()
    runs_dir = _abs(config, "runs_dir")
    runs_present = bool(runs_dir and runs_dir.is_dir() and any(runs_dir.glob("*.json")))
    return {
        "docker": docker,
        "node": node,
        "agh_ready": agh_ready,
        "platform_dsn": dsn,
        "model_key": model_key,
        "runs_dir": str(runs_dir) if runs_dir else "",
        "runs_present": runs_present,
        "real_ready": agh_ready and dsn and docker,
        "config_path": config.get("_config_path", ""),
    }


class RunManager:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._cases_root = _abs(config, "cases_root") or (repo_root() / "datasets")

    # -- public ---------------------------------------------------------------
    def start(self, mode: str, only_bundled: bool, case_ids: list[str] | None) -> str:
        run_id = uuid.uuid4().hex[:12]
        all_cases = list_cases(self._cases_root)
        ids = [c["case_id"] for c in all_cases]
        if mode == "real":
            ids = case_ids or ids
        per_case: dict[str, str] = {cid: "pending" for cid in ids}
        record: dict[str, Any] = {
            "id": run_id,
            "mode": mode,
            "only_bundled": only_bundled,
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": None,
            "error": None,
            "progress": {"total": len(ids), "current_case": None, "per_case": per_case},
            "report": None,
            "_case_ids": ids,
        }
        with self._lock:
            self._runs[run_id] = record
        target = self._run_real if mode == "real" else self._run_offline
        threading.Thread(target=target, args=(run_id,), daemon=True).start()
        return run_id

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return None
            snapshot = json.loads(json.dumps(record))
        per = snapshot["progress"]["per_case"]
        snapshot["progress"]["done"] = sum(1 for s in per.values() if s in _FINISHED)
        return snapshot

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": r["id"],
                    "mode": r["mode"],
                    "status": r["status"],
                    "started_at": r["started_at"],
                    "finished_at": r["finished_at"],
                }
                for r in self._runs.values()
            ]

    def case_detail(self, run_id: str, case_id: str) -> dict[str, Any] | None:
        snapshot = self.get(run_id)
        if snapshot is None:
            return None
        report = snapshot.get("report") or {}
        for case in report.get("cases", []):
            if case.get("case_id") == case_id:
                return case
        return None

    # -- internal -------------------------------------------------------------
    def _update(self, run_id: str, **fields: Any) -> None:
        with self._lock:
            self._runs[run_id].update(fields)

    def _set_case(self, run_id: str, case_id: str, status: str) -> None:
        with self._lock:
            rec = self._runs[run_id]
            rec["progress"]["per_case"][case_id] = status
            rec["progress"]["current_case"] = case_id if status == "running" else None

    def _finish(self, run_id: str, report: dict[str, Any] | None, error: str | None) -> None:
        with self._lock:
            rec = self._runs[run_id]
            rec["status"] = "error" if error else "done"
            rec["finished_at"] = datetime.now(UTC).isoformat()
            rec["error"] = error
            rec["report"] = report
            rec["progress"]["current_case"] = None

    def _run_offline(self, run_id: str) -> None:
        runs_dir = _abs(self._config, "runs_dir")
        out_dir = (_abs(self._config, "out_dir") or (repo_root() / "webui" / "out")) / run_id
        if runs_dir is None or not runs_dir.is_dir():
            self._finish(run_id, None, f"运行包目录不存在：{runs_dir}")
            return
        try:
            report = R.run(
                runs_dir,
                out_dir,
                cases_root=self._cases_root,
                only_bundled=self._runs[run_id]["only_bundled"],
            )
        except Exception as exc:  # noqa: BLE001 — surface any scorer failure to the UI
            self._finish(run_id, None, f"{type(exc).__name__}: {exc}")
            return
        self._apply_report_progress(run_id, report)
        self._finish(run_id, report, None)

    def _apply_report_progress(self, run_id: str, report: dict[str, Any]) -> None:
        per: dict[str, str] = {}
        for case in report.get("cases", []):
            per[case.get("case_id", "")] = "ok"
        global_summary = report.get("global", {})
        for cid in global_summary.get("cases_missing_bundle", []):
            per[cid] = "missing"
        for cid in global_summary.get("cases_skipped_no_bundle", []):
            per[cid] = "skipped"
        with self._lock:
            self._runs[run_id]["progress"]["per_case"] = per
            self._runs[run_id]["progress"]["total"] = max(
                self._runs[run_id]["progress"]["total"], len(per)
            )

    def _run_real(self, run_id: str) -> None:
        out_root = _abs(self._config, "out_dir") or (repo_root() / "webui" / "out")
        bundles_dir = out_root / run_id / "runs"
        score_dir = out_root / run_id / "score"
        bundles_dir.mkdir(parents=True, exist_ok=True)
        case_ids = self._runs[run_id]["_case_ids"]
        failures: list[str] = []
        for case_id in case_ids:
            self._set_case(run_id, case_id, "running")
            result = run_case(case_id, repo_root(), self._config, bundles_dir)
            self._set_case(run_id, case_id, "ok" if result["ok"] else "failed")
            if not result["ok"]:
                failures.append(f"{case_id}: {result['error']}")
        try:
            report = R.run(
                bundles_dir,
                score_dir,
                cases_root=self._cases_root,
                only_bundled=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._finish(run_id, None, f"{type(exc).__name__}: {exc}")
            return
        error = "; ".join(failures) or None
        if error:
            self._update(run_id, error=error)
        self._apply_report_progress(run_id, report)
        self._finish(run_id, report, error)
