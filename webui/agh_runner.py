"""Real-run adapter: drive the external AGH CLI and export its run bundle.

This is the only part of the demo console that touches the model. The repo itself is the
MCP stdio tool server; a real run spawns the external Agent Host (AGH) with ``node`` and
hands it one case's project directory, then exports the saved run facts into a scorer
bundle via ``scripts/export_evaluation_run.py``.

The AGH command line, profile, home, and run-home layout are all configurable through
``webui/config.json``. This code can be built and linted locally but its end-to-end
behaviour depends on the AGH contract and can only be confirmed on the demo machine —
see ``webui/README.md``. Failures are reported per case and never abort the whole run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _find_run_home(config: dict[str, Any], case_id: str, root: Path) -> Path | None:
    """Locate the run home AGH produced for ``case_id``.

    AGH's output layout is a contract outside this repo. Default to
    ``run_home_root/<case_id>``; when that is absent, fall back to any directory under
    ``run_home_root`` whose ``bundle.json`` names this case.
    """
    root_home = config.get("run_home_root") or ""
    base = Path(root_home) if Path(root_home).is_absolute() else root / root_home
    if not base.is_dir():
        return None
    direct = base / case_id
    if (direct / "bundle.json").exists():
        return direct
    for candidate in sorted(base.iterdir()):
        if not candidate.is_dir():
            continue
        bundle = candidate / "bundle.json"
        if not bundle.exists():
            continue
        try:
            data = json.loads(bundle.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("case_id") == case_id:
            return candidate
    return None


def _run_export(home: Path, case_id: str, out: Path, root: Path) -> tuple[bool, str]:
    script = root / "scripts" / "export_evaluation_run.py"
    cmd = [
        sys.executable,
        str(script),
        "--home",
        str(home),
        "--case-id",
        case_id,
        "--out",
        str(out),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(root),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"导出运行包失败：{exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[-500:]
    return out.exists(), "导出产物缺失"


def run_case(case_id: str, root: Path, config: dict[str, Any], bundles_dir: Path) -> dict[str, Any]:
    """Run one case end-to-end and export its bundle. Never raises."""
    agh_cli = config.get("agh_cli") or ""
    agh_home = config.get("agh_home") or ""
    if not agh_cli:
        return {"ok": False, "error": "AGH CLI 未配置（config.json 的 agh_cli 为空）"}
    cli = Path(agh_cli) if Path(agh_cli).is_absolute() else root / agh_cli
    if not cli.exists():
        return {"ok": False, "error": f"AGH CLI 不存在：{cli}"}

    project = root / "datasets" / case_id / "project"
    if not project.is_dir():
        return {"ok": False, "error": f"用例项目目录不存在：{project}"}

    profile = config.get("agh_profile") or "local-dev"
    instructions = config.get("instructions") or "agh/diagnosis-instructions.md"
    timeout = int(config.get("per_case_timeout_seconds") or 300)
    cmd = [
        "node",
        str(cli),
        "-p",
        instructions,
        "--mode",
        "json",
        "--profile",
        profile,
        "--cwd",
        str(project),
    ]
    env = dict(os.environ)
    if agh_home:
        env["AGH_HOME"] = agh_home
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(root),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"超过 {timeout}s 超时"}
    except OSError as exc:
        return {"ok": False, "error": f"启动 AGH 失败：{exc}"}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout).strip()[-500:]}

    home = _find_run_home(config, case_id, root)
    if home is None:
        return {"ok": False, "error": "未找到 AGH 运行目录（run_home_root/<case_id>）"}
    out = bundles_dir / f"{case_id}.json"
    ok, err = _run_export(home, case_id, out, root)
    return {"ok": ok, "error": err if not ok else ""}
