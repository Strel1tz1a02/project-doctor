"""Unit tests for A3 observation attachments: plans and code locations."""

from __future__ import annotations

from project_doctor.integrations.observation.plans import PlanEstimate, attach_plan, parse_plan
from project_doctor.integrations.observation.reference import CodeReference, attach_code_location
from project_doctor.models.observation import SqlCall

# --- EXPLAIN plan parsing ---------------------------------------------------


def test_parse_plan_extracts_first_table_access() -> None:
    plan = {
        "query_block": {
            "table": {"access_type": "ALL", "rows_examined_per_scan": 10000, "key": None}
        }
    }
    estimate = parse_plan(plan, "plan-evidence-1")
    assert estimate == PlanEstimate(
        access_type="ALL", estimated_rows=10000, key_used=None, evidence_id="plan-evidence-1"
    )


def test_parse_plan_tolerates_missing_shape() -> None:
    assert parse_plan({}, "plan-evidence-2") == PlanEstimate(
        access_type=None, estimated_rows=None, key_used=None, evidence_id="plan-evidence-2"
    )


def test_parse_plan_reads_list_of_tables() -> None:
    plan = {"query_block": {"table": [{"access_type": "ref", "rows": 5, "key": "idx"}]}}
    estimate = parse_plan(plan, "plan-evidence-3")
    assert estimate.access_type == "ref" and estimate.estimated_rows == 5
    assert estimate.key_used == "idx"


def test_parse_plan_reads_v2_index_lookup() -> None:
    plan = {
        "json_schema_version": "2.0",
        "query_plan": {
            "operation": "Index lookup on t using idx (a = 1)",
            "access_type": "index",
            "index_name": "idx",
            "estimated_rows": 2.0,
            "key_columns": ["a"],
        },
    }
    assert parse_plan(plan, "plan-evidence-4") == PlanEstimate(
        access_type="index", estimated_rows=2, key_used="idx", evidence_id="plan-evidence-4"
    )


def test_parse_plan_reads_v2_table_scan_under_filter() -> None:
    plan = {
        "json_schema_version": "2.0",
        "query_plan": {
            "operation": "Filter",
            "access_type": "filter",
            "estimated_rows": 1.0,
            "inputs": [
                {
                    "operation": "Table scan on t",
                    "access_type": "table",
                    "estimated_rows": 10000.0,
                }
            ],
        },
    }
    assert parse_plan(plan, "plan-evidence-5") == PlanEstimate(
        access_type="ALL", estimated_rows=10000, key_used=None, evidence_id="plan-evidence-5"
    )


# --- plan evidence attachment -----------------------------------------------


def test_attach_plan_appends_without_mutating_original() -> None:
    call = SqlCall(id="sql-1", normalized_sql="SELECT 1")
    updated = attach_plan(call, PlanEstimate("ALL", 1, None, "plan-1"))
    assert updated.plan_evidence_ids == ["plan-1"]
    assert call.plan_evidence_ids == []


# --- code location attachment -----------------------------------------------


def test_attach_code_location_binds_commit_and_path() -> None:
    call = SqlCall(id="sql-2", normalized_sql="SELECT 2")
    reference = CodeReference(path="app/queries.py", line=42, association_evidence_ids=["e1"])
    updated = attach_code_location(call, reference, "commit-1")
    assert updated.code_location is not None
    assert updated.code_location.commit == "commit-1"
    assert updated.code_location.path == "app/queries.py"
    assert updated.code_location.line == 42
    assert updated.code_location.association_evidence_ids == ["e1"]
    assert call.code_location is None
