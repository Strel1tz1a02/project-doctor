from typing import cast

from pydantic import JsonValue

from project_doctor.features.reports.rank import rank, shared_impact
from project_doctor.features.reports.render_html import render_html
from project_doctor.features.reports.render_json import render_json
from project_doctor.features.scenarios.applicability import applicability
from project_doctor.models.finding import ReportData, ReportTask
from project_doctor.models.task import TaskBundle


def build_report(bundle: TaskBundle) -> ReportData:
    verified = rank([item for item in bundle.findings if item.status == "verified"])
    leads = [item for item in bundle.findings if item.status in {"lead", "refuted"}]
    unknown = [item for item in bundle.findings if item.status == "unclassified"]
    limits = ["影响仅对应本次测试负载，不代表线上业务优先级。"]
    if shared_impact(verified):
        limits.append("多项诊断共享 SQL／实验耗时，不累计为总收益。")
    if bundle.task.correlation.missing_correlation:
        limits.append(
            "部分 AGH 关联标识缺失：" + ", ".join(bundle.task.correlation.missing_correlation)
        )
    notes = list(dict.fromkeys(note for item in bundle.scenarios for note in applicability(item)))
    blocked = list(
        dict.fromkeys(path for item in bundle.scenarios for path in item.uncovered_paths)
    )
    report = ReportData(
        task=ReportTask(
            id=bundle.task.id,
            status=bundle.task.status,
            commit=bundle.task.project.commit,
            environment_id=bundle.task.environment_id,
        ),
        applicability=notes,
        coverage=bundle.task.coverage,
        verified_findings=verified,
        leads=leads,
        unclassified=unknown,
        blocked_paths=blocked,
        limitations=limits,
        json_content="",
        html_content="",
    )
    payload: dict[str, JsonValue] = report.model_dump(
        mode="json", exclude={"json_content", "html_content"}
    )
    cards: list[JsonValue] = []
    for finding in verified + leads + unknown:
        scenario = next((item for item in bundle.scenarios if item.id == finding.scenario_id), None)
        experiments = [
            item for item in bundle.experiments if item.experiment_id in finding.experiment_ids
        ]
        cards.append(
            {
                "finding": finding.model_dump(mode="json"),
                "scenario": scenario.model_dump(mode="json") if scenario else None,
                "experiments": [item.model_dump(mode="json") for item in experiments],
            }
        )
    payload["cards"] = cards
    payload["measurement_protocols"] = [
        {
            "experiment_id": result.experiment_id,
            "warmup_protocol": result.spec.warmup.model_dump(mode="json")
            if result.spec and result.spec.warmup
            else None,
            "warmup_attempts": len(result.warmup_results),
            "warmup_successes": sum(
                item.business_valid and item.failure is None for item in result.warmup_results
            ),
            "formal_samples": len(result.observations),
            "preparation_verified": len(result.preparation_results) == 2
            and all(item.verified for item in result.preparation_results),
            "lock_statuses": [
                {
                    "request_id": item.request_id,
                    "sql_call_id": call.id,
                    "status": call.lock_evidence.status if call.lock_evidence else "unknown",
                    "coverage": call.lock_evidence.coverage if call.lock_evidence else "unknown",
                    "missing_kinds": cast(JsonValue, call.lock_evidence.missing_kinds)
                    if call.lock_evidence
                    else ["table", "metadata", "innodb_data"],
                    "reasons": cast(JsonValue, call.lock_evidence.reasons)
                    if call.lock_evidence
                    else ["缺少锁覆盖证据。"],
                }
                for item in result.observations
                for call in item.sql_calls
            ],
        }
        for result in bundle.experiments
    ]
    report.limitations.append("预热只证明规定准备动作已执行；轮询空结果不证明零锁等待。")
    payload["limitations"] = list(report.limitations)
    report.json_content = render_json(payload)
    report.html_content = render_html(report.json_content)
    return report
