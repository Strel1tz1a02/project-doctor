"""Parse MySQL EXPLAIN plans into estimated access facts and attach plan evidence.

Estimates stay in the plan; actual measurements come from execution statistics and are
never mixed in here (see :mod:`project_doctor.integrations.observation.execution_stats`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from project_doctor.models.observation import SqlCall


@dataclass(frozen=True)
class PlanEstimate:
    access_type: str | None
    estimated_rows: int | None
    key_used: str | None
    evidence_id: str


_V2_ACCESS_TYPE = {"table": "ALL"}  # v2 "table" scan == v1 "ALL" full scan


def parse_plan(plan: dict[str, Any], evidence_id: str) -> PlanEstimate:
    """Extract the first table's access facts from an ``EXPLAIN FORMAT=JSON`` document.

    Handles the legacy v1 ``query_block`` shape and the v2 tree shape
    (``json_schema_version: "2.0"`` with a ``query_plan`` node). Missing or unexpected
    shapes degrade to ``None`` rather than being fabricated.
    """
    table = _first_table_node(plan)
    rows = table.get("estimated_rows", table.get("rows_examined_per_scan", table.get("rows")))
    key_used = table.get("index_name", table.get("key"))
    access_type = table.get("access_type")
    if isinstance(access_type, str):
        access_type = _V2_ACCESS_TYPE.get(access_type, access_type)
    return PlanEstimate(
        access_type=access_type,
        estimated_rows=int(rows) if isinstance(rows, (int, float)) else None,
        key_used=key_used if isinstance(key_used, str) else None,
        evidence_id=evidence_id,
    )


def _first_table_node(plan: dict[str, Any]) -> dict[str, Any]:
    """Return the first leaf that carries a table's access facts, for v1 and v2."""
    query_plan = plan.get("query_plan")
    if isinstance(query_plan, dict):
        # v2: a tree of operations; wrapping nodes (e.g. Filter) nest the table
        # access under ``inputs``, while a single index lookup is the node itself.
        node = query_plan
        while isinstance(node.get("inputs"), list) and node["inputs"]:
            node = node["inputs"][0]
        return node

    query_block = plan.get("query_block")
    block: dict[str, Any] = query_block if isinstance(query_block, dict) else plan
    table = block.get("table")
    if isinstance(table, list):
        table = table[0] if table else None
    return table if isinstance(table, dict) else {}


def attach_plan(call: SqlCall, plan: PlanEstimate) -> SqlCall:
    """Record a plan evidence reference on a copy of ``call`` without touching metrics."""
    ids = list(call.plan_evidence_ids)
    if plan.evidence_id not in ids:
        ids.append(plan.evidence_id)
    return call.model_copy(update={"plan_evidence_ids": ids})
