"""Read-only execution-side export. Never reads case.json or launches the SUT.

The evaluator consumes this JSON with --runs; missing independent retest and API
cost stay explicitly unmeasured. Diagnosis statuses come from the saved report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from project_doctor.features.diagnosis.compare import MeasurementPolicy, distinguishable, stable
from project_doctor.features.diagnosis.gates import experiment_failures
from project_doctor.integrations.artifacts.verify import resolve_contained
from project_doctor.models.finding import Finding, ReportResult
from project_doctor.models.task import TaskBundle

PHASES = {
    "create_task": "baseline",
    "prepare_environment": "baseline",
    "discover_scenarios": "hypotheses",
    "propose_hypotheses": "hypotheses",
    "run_experiment": "discriminating_experiment",
    "evaluate_evidence": "localization",
    "reconcile_task": "verification",
    "finish_task": "verification",
}
ARGUMENTS = {
    "create_task": ("project", "limits", "operation_id"),
    "prepare_environment": ("context",),
    "discover_scenarios": ("context",),
    "propose_hypotheses": ("context", "items"),
    "run_experiment": ("context", "environment_id", "scenario_id", "scenario_version", "spec"),
    "evaluate_evidence": ("context", "hypothesis_ids", "experiment_ids"),
    "reconcile_task": ("context",),
    "finish_task": ("context",),
}


def json_lines(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(
                word in key.lower() for word in ("password", "api_key", "authorization", "secret")
            )
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def evidence_flags(bundle: TaskBundle, finding: Finding) -> dict[str, bool]:
    flags = dict.fromkeys(
        (
            "scan_rows_decreased",
            "duration_distinguishable",
            "business_result_consistent",
            "no_lock_wait",
            "cache_known",
            "linked_to_code",
        ),
        False,
    )
    results = [e for e in bundle.experiments if e.experiment_id in finding.experiment_ids]
    if not results:
        return flags
    checks = []
    for result in results:
        spec = result.spec
        scenario = next(
            (
                s
                for s in bundle.scenarios
                if spec and s.id == spec.scenario_id and s.version == spec.scenario_version
            ),
            None,
        )
        if scenario is None or experiment_failures(result, scenario, bundle.task.project.commit):
            return flags
        calls = [
            c for o in result.observations for c in o.sql_calls if c.id in finding.sql_call_ids
        ]
        groups = [
            [
                c
                for o in result.observations
                if o.level == level
                for c in o.sql_calls
                if c.id in finding.sql_call_ids
            ]
            for level in ("baseline", "candidate_index")
        ]
        if not all(groups) or any(c.duration_ms is None or c.rows_examined is None for c in calls):
            return flags
        durations = [[float(c.duration_ms or 0) for c in group] for group in groups]
        delta = median(durations[0]) - median(durations[1])
        policy = MeasurementPolicy()
        no_lock = all(
            c.lock_evidence
            and c.lock_evidence.status != "unknown"
            and c.lock_evidence.coverage == "complete"
            and c.lock_wait_ms is not None
            and c.lock_wait_ms + (c.lock_evidence.residual_ms or 0.0) + policy.minimum_delta_ms
            < delta
            for c in calls
        )
        checks.append(
            {
                "scan_rows_decreased": median(c.rows_examined or 0 for c in groups[0])
                > median(c.rows_examined or 0 for c in groups[1]),
                "duration_distinguishable": distinguishable(durations[0], durations[1], policy),
                "business_result_consistent": all(
                    o.business_valid and o.result_digest for o in result.observations
                )
                and len({o.result_digest for o in result.observations}) == 1,
                "no_lock_wait": bool(no_lock),
                "cache_known": len(result.preparation_results) == 2
                and all(p.verified for p in result.preparation_results),
                "linked_to_code": bool(calls) and all(c.code_location is not None for c in calls),
            }
        )
    return {name: all(row[name] for row in checks) for name in flags}


def export_run(home: Path, case_id: str) -> dict[str, Any]:
    bundle = TaskBundle.model_validate_json((home / "bundle.json").read_text(encoding="utf-8"))
    report_result = ReportResult.model_validate_json(
        (home / "finish_task-latest.json").read_text(encoding="utf-8")
    )
    if report_result.task_id != bundle.task.id:
        raise ValueError("report belongs to another task")
    if report_result.task_status != bundle.task.status:
        raise ValueError("report and task final states disagree")
    root = home / "artifacts"
    refs = {r.artifact_id: r for r in bundle.evidence_refs}
    refs.update({r.artifact_id: r for r in (report_result.json_ref, report_result.html_ref)})
    artifacts = []
    for ref in refs.values():
        try:
            raw = resolve_contained(root, ref.relative_path).read_bytes()
            valid = len(raw) == ref.size_bytes and hashlib.sha256(raw).hexdigest() == ref.sha256
            readable = True
        except (OSError, ValueError):
            valid = readable = False
        artifacts.append(
            {"ref": "artifact://" + ref.artifact_id, "sha256_verified": valid, "readable": readable}
        )
    valid_ids = {a["ref"] for a in artifacts if a["sha256_verified"] and a["readable"]}
    if "artifact://" + report_result.json_ref.artifact_id not in valid_ids:
        raise ValueError("saved report is missing or corrupted")
    saved = json.loads(
        resolve_contained(root, report_result.json_ref.relative_path).read_text(encoding="utf-8")
    )
    findings = [Finding.model_validate(card["finding"]) for card in saved.get("cards", [])]
    if {f.id: f for f in findings} != {f.id: f for f in bundle.findings}:
        raise ValueError("saved report and task bundle findings disagree")
    steps: list[dict[str, Any]] = []
    for call in json_lines(home / "business-tool-calls.jsonl"):
        args, output = call.get("args", []), call.get("result")
        kwargs = call.get("kwargs", {})
        context = args[0] if args and isinstance(args[0], dict) else kwargs.get("context", {})
        task_id = context.get("task_id") if isinstance(context, dict) else None
        if isinstance(output, dict):
            task_id = task_id or output.get("task_id") or output.get("id")
        if task_id != bundle.task.id:
            continue
        error = call.get("error") or (output.get("failure") if isinstance(output, dict) else None)
        inputs = dict(zip(ARGUMENTS.get(call["name"], ()), args, strict=False))
        inputs.update(kwargs)
        steps.append(
            {
                "index": len(steps),
                "tool": call["name"],
                "step_type": call["name"],
                "phase": PHASES.get(call["name"], ""),
                "status": "error" if error else "ok",
                "error": str(error or ""),
                "input": redact(inputs),
                "output": redact(output),
                "ts_start": call.get("started_at"),
                "ts_end": call.get("ended_at"),
                "cost": {"tool_calls": 1, "tokens": None, "bytes": None},
            }
        )
    session_path = home / "session.jsonl"
    events = json_lines(session_path) if session_path.exists() else []
    report_findings = []
    for finding in findings:
        flags = evidence_flags(bundle, finding)
        ids = ["artifact://" + r.artifact_id for r in finding.evidence_refs]
        if not ids or not set(ids).issubset(valid_ids):
            flags = dict.fromkeys(flags, False)
        row = finding.model_dump(mode="json")
        row.update(evidence_flags=flags, evidence_refs=ids)
        report_findings.append(row)
    observations = [o for e in bundle.experiments for o in e.observations]
    insufficient = bundle.task.status != "completed" or not any(
        finding.status == "verified" for finding in findings
    )
    diagnosis_reasons = list(report_result.limitations)
    if insufficient:
        diagnosis_reasons.extend(note for finding in findings for note in finding.limitations)
    restored = bool(bundle.experiments) and all(
        e.restore_result and e.restore_result.verified for e in bundle.experiments
    )
    final_restore_failed = any("收尾恢复未" in s for s in report_result.limitations)
    starts = [s["ts_start"] for s in steps if isinstance(s["ts_start"], (int, float))]
    ends = [s["ts_end"] for s in steps if isinstance(s["ts_end"], (int, float))]
    wall_seconds = max(
        bundle.task.usage.wall_seconds, max(ends) - min(starts) if starts and ends else 0
    )
    wall_scope = "task_usage_or_observed_tool_span"
    summary_path = home / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    elapsed = summary.get("model_elapsed_seconds", summary.get("elapsed_seconds"))
    if summary.get("task") == bundle.task.id and isinstance(elapsed, (int, float)):
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("recorded end-to-end wall time is invalid")
        if elapsed >= wall_seconds:
            wall_seconds, wall_scope = float(elapsed), "recorded_end_to_end"
        else:
            # A resumed task can have a longer tool span than its last model session.
            # Retain the larger measured span, rather than dropping the earlier attempt.
            wall_scope = "observed_tool_span_including_prior_attempts"
    return {
        "baseline": {
            "repeats_ms": [o.latency_ms for o in observations if o.level == "baseline"],
            "environment_fingerprint": observations[0].fingerprint if observations else None,
        },
        "report": {
            "task_status": bundle.task.status,
            "findings": report_findings,
            "observations": [o.business_valid for o in observations],
            "insufficient_evidence": insufficient,
            "reason": "; ".join(dict.fromkeys(diagnosis_reasons)),
        },
        "trajectory": {
            "steps": steps,
            "required_steps_done": sorted(
                {s["phase"] for s in steps if s["phase"] and s["status"] == "ok"}
            ),
            "hypothesis_count": len(bundle.hypotheses),
            "experiments_single_variable": bool(bundle.experiments)
            and all(e.spec and e.spec.variable == "index" for e in bundle.experiments),
            "records_retained": bool(events) and bool(steps),
            "tool_calls": len(steps),
        },
        "retest": {
            "performed": False,
            "improvement_percent": None,
            "business_assertions_passed": False,
        },
        "restore": {
            "rolled_back": bool(restored),
            "verified": bool(restored and not final_restore_failed),
        },
        "artifacts": artifacts,
        "cost": {
            "wall_seconds": wall_seconds,
            "tool_calls": len(steps),
            "artifact_bytes": bundle.task.usage.artifact_bytes,
        },
        "collection": {
            "case_id": case_id,
            "task_id": bundle.task.id,
            "target_commit": bundle.task.project.commit,
            "source": "actual_task_and_agh_records"
            if events
            else "actual_task_and_platform_records",
            "session_events": len(events),
            "execution_mode": summary.get("execution_mode", "agh_model_run"),
            "wall_time_scope": wall_scope,
            "platform_usage_wall_seconds": bundle.task.usage.wall_seconds,
            "missing_measurements": ["independent_retest", "api_cost", "model_tokens"],
            "policy": MeasurementPolicy().__dict__,
            "evidence_flag_semantics": {
                "no_lock_wait": (
                    "complete lock coverage; measured table+row lock wait and MDL bound cannot "
                    "explain SQL gain, not a claim of exact zero"
                ),
            },
        },
    }


def attach_retest(payload: dict[str, Any], source: Path, retest: Path, case_id: str) -> None:
    """Attach a separately executed, artifact-verified run without rewriting its parent report."""
    parent = TaskBundle.model_validate_json((source / "bundle.json").read_text(encoding="utf-8"))
    repeat = TaskBundle.model_validate_json((retest / "bundle.json").read_text(encoding="utf-8"))
    link = json.loads((retest / "retest-link.json").read_text(encoding="utf-8"))
    if (
        parent.task.id == repeat.task.id
        or parent.task.environment_id == repeat.task.environment_id
        or parent.task.project != repeat.task.project
    ):
        raise ValueError("retest must use a new task and the same project/commit")
    if len(parent.experiments) != 1 or len(repeat.experiments) != 1:
        raise ValueError("retest requires one experiment in each task")
    original, actual = parent.experiments[0], repeat.experiments[0]
    if original.spec is None or actual.spec is None:
        raise ValueError("retest requires persisted experiment specs")
    if (
        link.get("source_task_id") != parent.task.id
        or link.get("source_experiment_id") != original.experiment_id
        or link.get("retest_task_id") != repeat.task.id
        or link.get("source_commit") != parent.task.project.commit
        or link.get("recipe_ref") != original.spec.intervention_recipe_ref
    ):
        raise ValueError("retest linkage does not match the actual task/spec")
    exclude = {"task_id", "snapshot_id", "baseline_fingerprint"}
    if original.spec.model_dump(exclude=exclude) != actual.spec.model_dump(exclude=exclude):
        raise ValueError("retest changed the recorded experiment protocol")
    for filename in ("settings.json", "manifest.json"):
        before = json.loads((source / filename).read_text(encoding="utf-8"))
        after = json.loads((retest / filename).read_text(encoding="utf-8"))
        if filename == "settings.json":
            before_root, after_root = Path(before["workspace_root"]), Path(after["workspace_root"])
            if before_root.resolve().is_relative_to(after_root.resolve()) or (
                after_root.resolve().is_relative_to(before_root.resolve())
            ):
                raise ValueError("retest reused the original isolation workspace")
        else:
            # The preparation creates a new snapshot; all other recipe/scenario data is fixed.
            for doc in (before, after):
                for scenario in doc.get("scenarios", []):
                    scenario["dataset"].pop("snapshot_id", None)
            if before != after:
                raise ValueError("retest changed the manifest/recipe")
    original_ids = {o.request_id for o in original.observations + original.warmup_results}
    actual_ids = {o.request_id for o in actual.observations + actual.warmup_results}
    if original_ids & actual_ids:
        raise ValueError("retest reused original request IDs")
    # Snapshots are content-addressed: independent dumps of identical seed data
    # SHOULD have the same digest. Independence comes from task/environment/root
    # and request identity, not from artificially changing the data checksum.
    exported = export_run(retest, case_id)
    valid = (
        repeat.task.status == "completed"
        and actual.phase == "finished"
        and actual.failure is None
        and exported["restore"]["verified"]
        and all(a["sha256_verified"] and a["readable"] for a in exported["artifacts"])
    )
    groups = [
        [o.latency_ms for o in actual.observations if o.level == level]
        for level in ("baseline", "candidate_index")
    ]
    measurable = all(stable(group, MeasurementPolicy()) for group in groups)
    gain = (1 - median(groups[1]) / median(groups[0])) * 100 if valid and measurable else None
    retest_digests = {o.result_digest for o in actual.observations}
    business = (
        bool(actual.observations)
        and all(o.business_valid for o in actual.observations)
        and None not in retest_digests
        and len(retest_digests) == 1
    )
    payload["retest"] = {
        "performed": bool(valid),
        "improvement_percent": gain,
        "business_assertions_passed": bool(valid and business),
        "task_id": repeat.task.id,
        "source": link["source"],
        "metric": "request_latency_ms",
        "same_data_snapshot_digest": original.spec.snapshot_id == actual.spec.snapshot_id,
        "cross_run_business_digest_match": {o.result_digest for o in original.observations}
        == retest_digests,
        "business_check_scope": "assertions_and_equal_results_between_retest_levels",
        "repeats_ms": groups,
        "findings": exported["report"]["findings"],
        "cost": exported["cost"],
        "trajectory": exported["trajectory"],
    }
    payload["collection"]["diagnosis_cost"] = dict(payload["cost"])
    payload["collection"]["cost_scope"] = "diagnosis_plus_independent_retest"
    for name in ("wall_seconds", "tool_calls", "artifact_bytes"):
        payload["cost"][name] += exported["cost"][name]
    by_ref = {a["ref"]: a for a in payload["artifacts"] + exported["artifacts"]}
    payload["artifacts"] = list(by_ref.values())
    if valid:
        payload["collection"]["missing_measurements"].remove("independent_retest")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--retest-home", type=Path)
    args = parser.parse_args()
    payload = export_run(args.home, args.case_id)
    if args.retest_home:
        attach_retest(payload, args.home, args.retest_home, args.case_id)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
