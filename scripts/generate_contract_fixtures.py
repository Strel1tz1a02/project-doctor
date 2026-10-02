"""Six synthetic developer fixtures, not evaluation data or measured evidence."""

import copy
import json
from pathlib import Path

from project_doctor.models.common import EvidenceCheck
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.task import TaskBundle

ROOT = Path(__file__).resolve().parents[1]


def generate() -> None:
    evidence = {
        "artifact_id": "synthetic-evidence",
        "relative_path": "synthetic/evidence.json",
        "media_type": "application/json",
        "format_version": "synthetic-0.1",
        "sha256": "a" * 64,
        "size_bytes": 1,
    }
    location = {
        "commit": "synthetic-commit",
        "path": "app/queries.py",
        "line": 12,
        "association_evidence_ids": [evidence["artifact_id"]],
    }
    limits = {
        "max_wall_seconds": 180,
        "max_requests": 12,
        "max_experiments": 1,
        "max_artifact_bytes": 1048576,
        "restore_reserve_seconds": 30,
    }
    context = {
        "task_id": "task-1",
        "operation_id": "operation-1",
        "missing_correlation": ["agh_session_id", "tool_call_id"],
    }
    hypothesis = {
        "id": "hypothesis-1",
        "kind": "slow_query",
        "explanation": "Missing suitable index",
        "predictions": ["Candidate index reduces actual scanned rows"],
        "falsifiers": ["Actual work remains unchanged under comparable conditions"],
        "status": "supported",
        "evidence_ids": [evidence["artifact_id"]],
    }
    scenario = {
        "id": "scenario-1",
        "version": 1,
        "source": "repository",
        "purpose": "Find orders by customer",
        "preparation_recipe_ref": "recipe:seed",
        "steps": [
            {
                "method": "GET",
                "relative_path": "/orders",
                "params": {"customer_id": 10},
                "parameter_sources": {
                    "customer_id": {"source": "repository", "reference": "seed:10"}
                },
                "assertions": {
                    "status_code": 200,
                    "business": [{"json_pointer": "/items", "operator": "exists"}],
                },
            }
        ],
        "dataset": {
            "id": "dataset-1",
            "snapshot_id": "snapshot-1",
            "source": "synthetic",
            "row_counts": {"orders": 10000},
            "applicability_unknowns": ["Real-world data distribution is unknown"],
        },
        "load": {"mode": "serial"},
        "cache": {"state": "warm", "preparation_recipe_ref": "recipe:warm"},
    }
    spec = {
        "id": "experiment-1",
        "task_id": "task-1",
        "scenario_id": "scenario-1",
        "scenario_version": 1,
        "hypothesis_ids": ["hypothesis-1"],
        "variable": "index",
        "levels": ["baseline", "candidate_index"],
        "intervention_recipe_ref": "recipe:customer-index",
        "repetitions": 3,
        "limits": limits,
        "baseline_fingerprint": "fingerprint-baseline",
        "snapshot_id": "snapshot-1",
        "observation_config_id": "observation-config-1",
    }
    observations = []
    for level in spec["levels"]:
        for repetition in range(1, 4):
            call_id = f"sql-{level}-{repetition}"
            values = {
                "duration_ms": 100.0 if level == "baseline" else 10.0,
                "rows_examined": 10000 if level == "baseline" else 10,
                "rows_returned": 10,
                "lock_wait_ms": 0.0,
            }
            observations.append(
                {
                    "id": f"observation-{level}-{repetition}",
                    "experiment_id": "experiment-1",
                    "level": level,
                    "repetition": repetition,
                    "request_id": f"request-{level}-{repetition}",
                    "business_valid": True,
                    "latency_ms": values["duration_ms"] + 5,
                    "result_digest": "b" * 64,
                    "fingerprint": f"fingerprint-{level}",
                    "snapshot_id": "snapshot-1",
                    "observation_config_id": "observation-config-1",
                    "evidence_refs": [evidence],
                    "sql_calls": [
                        {
                            "id": call_id,
                            "normalized_sql": "SELECT * FROM orders WHERE customer_id = ?",
                            **values,
                            "code_location": location,
                            "plan_evidence_ids": [evidence["artifact_id"]],
                            "metric_sources": {
                                name: {
                                    "source": "synthetic_sample",
                                    "measurement": "actual",
                                    "evidence_ids": [evidence["artifact_id"]],
                                }
                                for name in values
                            },
                        }
                    ],
                }
            )
    restore = {
        "verified": True,
        "fingerprint": "fingerprint-baseline",
        "snapshot_id": "snapshot-1",
        "evidence_refs": [evidence],
    }
    finding = {
        "id": "finding-1",
        "task_id": "task-1",
        "kind": "slow_query",
        "status": "verified",
        "scenario_id": "scenario-1",
        "experiment_ids": ["experiment-1"],
        "sql_call_ids": ["sql-baseline-1"],
        "code_locations": [location],
        "evidence_refs": [evidence],
        "excluded_explanations": [
            {"explanation": "Lock waiting", "evidence_ids": [evidence["artifact_id"]]}
        ],
        "impact": {
            "method": "intervention",
            "latency_delta_ms": 90,
            "uncertainty": ["Synthetic example"],
        },
        "recommendation": {
            "action": "Evaluate an index on customer_id",
            "mechanism": "Reduce examined rows",
            "conditions": ["Actual selectivity supports index use"],
            "costs": ["Storage and write overhead"],
        },
        "limitations": ["Synthetic contract example, not a real diagnosis"],
    }
    bundle = {
        "task": {
            "id": "task-1",
            "project": {
                "repo_path": "E:/synthetic/reference",
                "commit": "synthetic-commit",
                "supplied_url": "http://localhost:8000",
                "recipe_ref": "recipe:reference",
            },
            "status": "completed",
            "limits": limits,
            "usage": {"requests": 6, "experiments": 1},
            "environment_id": "environment-1",
            "scenario_ids": ["scenario-1"],
            "experiment_ids": ["experiment-1"],
            "hypothesis_ids": ["hypothesis-1"],
            "finding_ids": ["finding-1"],
            "correlation": context,
            "coverage": ["GET /orders"],
        },
        "scenarios": [scenario],
        "hypotheses": [hypothesis],
        "experiments": [
            {
                "experiment_id": "experiment-1",
                "operation_id": "operation-1",
                "phase": "finished",
                "observations": observations,
                "restore_result": restore,
                "evidence_refs": [evidence],
            }
        ],
        "findings": [finding],
        "evidence_refs": [evidence],
    }
    destination = ROOT / "tests/contracts/fixtures"
    destination.mkdir(parents=True, exist_ok=True)
    for name in (
        "verified_slow_query",
        "missing_location",
        "missing_artifact",
        "incomparable",
        "restore_failed",
        "unknown_outcome",
    ):
        case_bundle = copy.deepcopy(bundle)
        check = {"valid": True}
        experiment = case_bundle["experiments"][0]
        if name != "verified_slow_query":
            case_bundle["findings"][0]["status"] = "lead"
            case_bundle["hypotheses"][0]["status"] = "unresolved"
            case_bundle["task"]["status"] = "partial"
        if name == "missing_location":
            case_bundle["findings"][0]["code_locations"] = []
            for item in experiment["observations"]:
                item["sql_calls"][0]["code_location"] = None
        elif name == "missing_artifact":
            check = {"valid": False, "missing_ids": [evidence["artifact_id"]]}
        elif name == "incomparable":
            experiment["observations"][-1]["snapshot_id"] = "different-snapshot"
        elif name == "restore_failed":
            experiment["restore_result"] = {"verified": False, "reason": "Snapshot restore failed"}
            experiment["failure"] = {
                "code": "environment_contaminated",
                "message": "Restore failed",
                "retry_policy": "never",
            }
        elif name == "unknown_outcome":
            experiment["phase"] = "needs_reconcile"
            experiment["restore_result"] = None
            experiment["failure"] = {
                "code": "tool_failure",
                "message": "Execution outcome unknown",
                "retry_policy": "reconcile_first",
            }
        case = {
            "synthetic": True,
            "purpose": "developer_contract_test_only",
            "expected_status": case_bundle["findings"][0]["status"],
            "bundle": TaskBundle.model_validate(case_bundle).model_dump(mode="json"),
            "spec": ExperimentSpec.model_validate(spec).model_dump(mode="json"),
            "evidence_check": EvidenceCheck.model_validate(check).model_dump(mode="json"),
        }
        (destination / f"{name}.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    generate()
