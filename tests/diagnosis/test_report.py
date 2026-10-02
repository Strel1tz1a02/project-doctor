import json

from project_doctor.features.reports.build import build_report
from project_doctor.models.task import TaskBundle


def test_report_contains_sql_operation_evidence_and_limits(bundle: TaskBundle) -> None:
    report = build_report(bundle)
    content = json.loads(report.json_content)
    assert "SELECT" in report.json_content
    assert "/orders" in report.json_content
    assert content["cards"][0]["finding"]["code_locations"][0]["line"] == 12
    assert "本次测试负载" in report.html_content
    assert "线上业务优先级" in "".join(report.limitations)


def test_html_escapes_untrusted_sql_and_ignores_model_gain(bundle: TaskBundle) -> None:
    bundle.experiments[0].observations[0].sql_calls[0].normalized_sql = "<script>alert(1)</script>"
    report = build_report(bundle)
    assert "<script>" not in report.html_content
    assert "&lt;script&gt;" in report.html_content
    assert "预计作用机制" in report.html_content


def test_report_does_not_count_shared_sql_twice(bundle: TaskBundle) -> None:
    finding = bundle.findings[0]
    second = finding.model_copy(update={"id": "finding-2"})
    bundle.findings.append(second)
    report = build_report(bundle)
    assert len(report.verified_findings) == 2
    assert "共享" in "".join(report.limitations)
    assert "total_gain_ms" not in report.json_content
