from project_doctor.models.scenario import Scenario


def applicability(scenario: Scenario) -> list[str]:
    notes = list(scenario.dataset.applicability_unknowns)
    if scenario.dataset.source == "synthetic":
        notes.append("合成数据：不能声称代表实际使用分布。")
    if scenario.source == "inferred":
        notes.append("场景由模型推断，实际业务适用性待确认。")
    if scenario.dataset.target_scale is None:
        notes.append("目标环境数据规模未知；结论仅适用于本次实验条件。")
    if scenario.cache.state == "unknown":
        notes.append("缓存条件未知，实验归因可能受影响。")
    return list(dict.fromkeys(notes))
