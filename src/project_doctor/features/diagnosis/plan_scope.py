"""Plan-estimate scope checks for diagnosis (pure, no I/O).

``EXPLAIN FORMAT=JSON`` documents nest their table nodes differently across MySQL
versions — v1 ``query_block`` with ``ordering_operation`` / ``nested_loop`` children and
v2 ``query_plan`` trees with ``inputs`` — and a joined query has several table nodes.
Only the *measured* scan rows and SQL duration may prove a root cause; a plan
``filtered`` percentage is an optimizer estimate that can at most trigger an uncertainty
review. Malformed documents degrade to "no estimate" instead of crashing diagnosis.
"""

from typing import Any

__all__ = ["all_filtered"]

#: ``filtered`` is a percentage; anything outside ``[0, 100]`` is not an estimate.
_MAX_FILTERED = 100.0


def all_filtered(plan: dict[str, Any]) -> list[float]:
    """Finite table-node ``filtered`` estimates from a v1 or v2 plan, in document order.

    Every nested table node is inspected, so a poor estimate on a joined table is seen.
    Missing, non-numeric, non-finite or out-of-range values are skipped, because an
    estimate can never stand in for a measurement. The caller may use these values as
    supporting evidence for an uncertainty review only — never as proof of a root cause
    or of a measured gain.
    """
    values: list[float] = []
    for node in _table_nodes(plan):
        raw = node.get("filtered")
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            continue
        try:
            estimate = float(raw)
        except ValueError:
            continue
        if 0.0 <= estimate <= _MAX_FILTERED:
            values.append(estimate)
    return values


def _table_nodes(plan: Any) -> list[dict[str, Any]]:
    """All nested nodes that carry a table access, across v1 and v2 layouts."""
    return [
        node
        for node in _walk(plan)
        if isinstance(node.get("table_name"), str)
        or isinstance(node.get("access_type"), str)
        or "filtered" in node
    ]


def _walk(value: Any) -> list[dict[str, Any]]:
    """Depth-first walk over JSON containers; scalars and unknown types are ignored."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk(child))
    return found
