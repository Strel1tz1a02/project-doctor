"""Repeat a recorded index experiment in a NEW isolated task, without a model.

Only the prior task's project, hypotheses, scenario and selected recipe are reused.
No case.json, expected answer or evaluator is read. Each task retains its budget
and executes at most one index experiment. Run sequentially to avoid load skew.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, cast

from project_doctor.entrypoints.bootstrap import bootstrap
from project_doctor.entrypoints.settings import Settings
from project_doctor.integrations.docker.gateway import DockerEnvironmentGateway
from project_doctor.integrations.runtime_factory import RuntimeService
from project_doctor.models.task import CallContext, TaskBundle


def serial(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (tuple, list)):
        return [serial(item) for item in value]
    if isinstance(value, dict):
        return {key: serial(item) for key, item in value.items()}
    return value


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(serial(value), ensure_ascii=False, indent=2), encoding="utf-8")


async def run(source: Path, home: Path, image: str) -> None:
    if shutil.which("docker") is None:
        raise ValueError("Docker CLI unavailable; configure PATH before creating a retest task")
    original = TaskBundle.model_validate_json((source / "bundle.json").read_text(encoding="utf-8"))
    if len(original.experiments) != 1 or original.experiments[0].spec is None:
        raise ValueError("retest requires exactly one recorded experiment with a persisted spec")
    recorded = original.experiments[0]
    spec = recorded.spec
    assert spec is not None
    settings = Settings.model_validate_json((source / "settings.json").read_text(encoding="utf-8"))
    # Validate before creating files or performing any side effect.
    settings = Settings.model_validate(
        {
            **settings.model_dump(),
            "artifact_root": home / "artifacts",
            "workspace_root": home / "isolated",
        }
    )
    home.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    write(home / "settings.json", settings)
    write(home / "manifest.json", manifest)
    flow = bootstrap(settings, manifest)
    gateway = cast(DockerEnvironmentGateway, cast(RuntimeService, flow.runtime)._gateway)
    gateway._service_image = image  # Frozen local target image, same as the source run.
    started = time.monotonic()

    async def call(name: str, *args: Any) -> Any:
        row = {"name": name, "args": serial(args), "started_at": time.time()}
        try:
            value = await getattr(flow, name)(*args)
            row["result"] = serial(value)
            write(home / (name + "-latest.json"), value)
            return value
        except Exception as exc:
            row["error"] = str(exc)
            raise
        finally:
            row["ended_at"] = time.time()
            with (home / "business-tool-calls.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    task = await call(
        "create_task",
        original.task.project,
        original.task.limits,
        "independent-retest-" + uuid.uuid4().hex,
    )

    def context(operation: str) -> CallContext:
        return CallContext(
            task_id=task.id,
            operation_id=operation,
            missing_correlation=["agh_session_id", "tool_call_id"],
        )

    failure: Exception | None = None
    try:
        environment = await call("prepare_environment", context("prepare"))
        for scenario in manifest["scenarios"]:
            scenario["dataset"]["snapshot_id"] = environment.baseline_snapshot_id
        write(home / "manifest.json", manifest)
        scenarios = await call("discover_scenarios", context("discover"))
        scenario = next(
            s for s in scenarios if s.id == spec.scenario_id and s.version == spec.scenario_version
        )
        hypotheses = [h for h in original.hypotheses if h.id in spec.hypothesis_ids]
        await call("propose_hypotheses", context("hypotheses"), hypotheses)
        updated = spec.model_copy(
            update={
                "task_id": task.id,
                "snapshot_id": environment.baseline_snapshot_id,
                "baseline_fingerprint": environment.fingerprint,
            }
        )
        result = await call(
            "run_experiment",
            context("experiment-1"),
            environment.id,
            scenario.id,
            scenario.version,
            updated,
        )
        await call(
            "evaluate_evidence", context("evaluate"), updated.hypothesis_ids, [result.experiment_id]
        )
    except Exception as exc:
        failure = exc
    finally:
        # Restore/close even when preparation, measurement or diagnosis failed.
        report = await call("finish_task", context("finish"))
        repeated = await call("finish_task", context("finish-again-with-new-id"))
        if repeated != report:
            raise RuntimeError("terminal report changed on repeated finish")
        bundle = await flow.store.load_bundle(task.id)
        write(home / "bundle.json", bundle)
        check = await flow.reader.verify(bundle.evidence_refs + [report.json_ref, report.html_ref])
        if not check.valid:
            raise RuntimeError("retest artifacts failed verification")
        write(
            home / "retest-link.json",
            {
                "source_task_id": original.task.id,
                "source_experiment_id": recorded.experiment_id,
                "retest_task_id": task.id,
                "source_commit": original.task.project.commit,
                "recipe_ref": spec.intervention_recipe_ref,
                "source": "independent_platform_run_no_model",
            },
        )
        write(
            home / "summary.json",
            {
                "task": task.id,
                "task_status": bundle.task.status,
                "execution_mode": "independent_platform_run_no_model",
                "elapsed_seconds": time.monotonic() - started,
                "source_task_id": original.task.id,
                "findings": [
                    {"status": f.status, "limitations": f.limitations} for f in bundle.findings
                ],
                "artifact_verification": check.valid,
                "repeated_finish_identical": repeated == report,
            },
        )
    if failure:
        raise failure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-home", required=True, type=Path)
    parser.add_argument("--out-home", required=True, type=Path)
    parser.add_argument("--service-image", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.source_home.resolve(), args.out_home.resolve(), args.service_image))


if __name__ == "__main__":
    main()
