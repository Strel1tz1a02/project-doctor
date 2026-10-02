from project_doctor.models.errors import Failure
from project_doctor.models.scenario import Scenario


def validate(scenario: Scenario) -> list[Failure]:
    # Re-validate even a caller-created model_copy; Pydantic trusts existing instances by default.
    Scenario.model_validate(scenario.model_dump())
    sensitive_names = {
        "password",
        "token",
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "secret",
    }
    for step in scenario.steps:
        for name, value in step.params.items():
            source = step.parameter_sources[name]
            if source.source == "credential_ref":
                if source.reference not in scenario.credential_refs or value != {
                    "credential_ref": source.reference
                }:
                    return [
                        Failure(
                            code="scenario_invalid",
                            message="凭据参数必须引用已声明凭据，不能保存明文。",
                            retry_policy="never",
                        )
                    ]
            elif name.lower() in sensitive_names:
                return [
                    Failure(
                        code="scenario_invalid",
                        message="敏感参数必须使用 credential_ref。",
                        retry_policy="never",
                    )
                ]
    if not scenario.dataset.row_counts or not any(scenario.dataset.row_counts.values()):
        return [
            Failure(
                code="scenario_invalid", message="诊断场景缺少非空数据规模。", retry_policy="never"
            )
        ]
    return []
