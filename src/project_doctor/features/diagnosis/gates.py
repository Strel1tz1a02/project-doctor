from project_doctor.features.experiments.preparation import preparation_digest
from project_doctor.models.common import EvidenceRef
from project_doctor.models.experiment import ExperimentResult
from project_doctor.models.scenario import Scenario


def evidence_refs(result: ExperimentResult) -> list[EvidenceRef]:
    refs = list(result.evidence_refs)
    refs.extend(ref for observation in result.observations for ref in observation.evidence_refs)
    refs.extend(ref for item in result.preparation_results for ref in item.evidence_refs)
    refs.extend(ref for item in result.warmup_results for ref in item.evidence_refs)
    refs.extend(
        ref
        for item in result.observations
        for call in item.sql_calls
        if call.lock_evidence
        for ref in call.lock_evidence.evidence_refs
    )
    if result.restore_result:
        refs.extend(result.restore_result.evidence_refs)
    by_id: dict[str, EvidenceRef] = {}
    for ref in refs:
        if ref.artifact_id in by_id and by_id[ref.artifact_id] != ref:
            raise ValueError("conflicting evidence metadata for the same artifact")
        by_id[ref.artifact_id] = ref
    return list(by_id.values())


def experiment_failures(result: ExperimentResult, scenario: Scenario, commit: str) -> list[str]:
    issues: list[str] = []
    spec = result.spec
    if spec is None:
        return ["缺少持久化 ExperimentSpec，无法核对实验变量与条件。"]
    if result.phase != "finished" or result.failure is not None:
        issues.append("实验未明确结束或存在工具／环境故障。")
    restore = result.restore_result
    if not restore or not restore.verified:
        issues.append("环境恢复未验证。")
    elif (
        restore.snapshot_id != spec.snapshot_id or restore.fingerprint != spec.baseline_fingerprint
    ):
        issues.append("恢复结果与实验基线不匹配。")
    if spec.scenario_id != scenario.id or spec.scenario_version != scenario.version:
        issues.append("实验与场景版本不匹配。")
    if spec.snapshot_id != scenario.dataset.snapshot_id:
        issues.append("场景数据快照与实验不匹配。")
    if scenario.cache.state == "unknown" or not scenario.cache.preparation_recipe_ref:
        issues.append("缓存准备条件未知。")
    if spec.warmup is None:
        issues.append("缺少可核验的预热协议与实际准备记录。")
    elif len(scenario.steps) != 1:
        issues.append("预热协议仅支持单步场景。")
    else:
        if scenario.cache.state != "warm":
            issues.append("预热协议与场景声明的缓存状态不一致。")
        if scenario.cache.preparation_recipe_ref != spec.warmup.preparation_recipe_ref:
            issues.append("场景缓存配方与预热协议不一致。")
        expected_digest = preparation_digest(spec.warmup, scenario.steps[0])
        for level in spec.levels:
            prepared = [item for item in result.preparation_results if item.level == level]
            warmups = [item for item in result.warmup_results if item.level == level]
            if len(prepared) != 1 or any(
                not item.verified
                or not item.evidence_refs
                or item.prepared_fingerprint != item.final_fingerprint
                or item.snapshot_id != spec.snapshot_id
                or item.observation_config_id != spec.observation_config_id
                or item.protocol_id != spec.warmup.protocol_id
                or item.recipe_digest != expected_digest
                for item in prepared
            ):
                issues.append("缺少完整且匹配的分组准备验证证据。")
            if (
                len(warmups) != spec.warmup.requests_per_level
                or {item.ordinal for item in warmups}
                != set(range(1, spec.warmup.requests_per_level + 1))
                or any(
                    not item.business_valid
                    or item.failure
                    or not item.result_digest
                    or not item.evidence_refs
                    for item in warmups
                )
            ):
                issues.append("预热次数不足、业务失败或原始证据缺失。")
            if prepared and any(
                item.fingerprint != prepared[0].prepared_fingerprint
                for item in result.observations
                if item.level == level
            ):
                issues.append("正式样本不属于已验证的准备环境。")
        all_digests = {item.result_digest for item in result.warmup_results} | {
            item.result_digest for item in result.observations
        }
        if len(all_digests) != 1 or None in all_digests:
            issues.append("预热与正式请求业务结果不一致。")
        if (
            len(result.preparation_results) != 2
            or 2 * (spec.repetitions + spec.warmup.requests_per_level) > spec.limits.max_requests
        ):
            issues.append("准备分组或预热与正式请求预算不完整。")
    request_ids = [item.request_id for item in result.observations] + [
        item.request_id for item in result.warmup_results
    ]
    if len(request_ids) != len(set(request_ids)):
        issues.append("请求标识重复，不能把同次测量重复计入样本。")
    if any(item.result_digest is None for item in result.observations):
        issues.append("缺少业务结果摘要。")
    for observation in result.observations:
        if not observation.business_valid or observation.result_digest is None:
            issues.append("请求未完成预期业务动作或缺结果摘要。")
        if (
            observation.snapshot_id != spec.snapshot_id
            or observation.observation_config_id != spec.observation_config_id
        ):
            issues.append("快照或观测配置不可比。")
        if observation.level == "baseline" and observation.fingerprint != spec.baseline_fingerprint:
            issues.append("基线环境指纹不匹配。")
        for call in observation.sql_calls:
            if call.code_location is None or call.code_location.commit != commit:
                issues.append("缺少当前提交的 SQL 到代码位置关联。")
    if len({item.result_digest for item in result.observations}) != 1:
        issues.append("两组业务结果不一致。")
    for level in spec.levels:
        items = [item for item in result.observations if item.level == level]
        if len({item.repetition for item in items}) != spec.repetitions:
            issues.append("重复测量次数不足或重复编号不完整。")
        if len(items) != spec.repetitions or {item.repetition for item in items} != set(
            range(1, spec.repetitions + 1)
        ):
            issues.append("当前判据仅支持每轮一个有效请求的测量场景。")
        if len({item.fingerprint for item in items}) != 1:
            issues.append("同组环境指纹发生变化。")
    return list(dict.fromkeys(issues))
