from project_doctor.models.finding import Finding


def rank(findings: list[Finding]) -> list[Finding]:
    def key(item: Finding) -> tuple[int, float, str]:
        measured = item.impact.method == "intervention" and item.impact.latency_delta_ms is not None
        return (0 if measured else 1, -(item.impact.latency_delta_ms or 0), item.id)

    return sorted(findings, key=key)


def shared_impact(findings: list[Finding]) -> bool:
    seen: set[str] = set()
    for item in findings:
        keys = {f"experiment:{key}" for key in item.experiment_ids}
        keys.update(f"sql:{key}" for key in item.sql_call_ids + item.impact.shared_sql_call_ids)
        if seen.intersection(keys):
            return True
        seen.update(keys)
    return False
