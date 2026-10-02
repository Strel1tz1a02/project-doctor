"""Load explicit repository-derived operation scenarios; never guess required parameters."""

from pydantic import Field

from project_doctor.features.scenarios.deduplicate import dedup_key
from project_doctor.features.scenarios.validate import validate
from project_doctor.models.common import Contract
from project_doctor.models.environment import ProjectInput
from project_doctor.models.scenario import Scenario


class RepositoryManifest(Contract):
    scenarios: list[Scenario] = Field(default_factory=list)
    uncovered_paths: list[str] = Field(default_factory=list)


def discover(project: ProjectInput, repository_manifest: dict[str, object]) -> list[Scenario]:
    ProjectInput.model_validate(project.model_dump())
    manifest = RepositoryManifest.model_validate(repository_manifest)
    results: dict[str, Scenario] = {}
    for scenario in manifest.scenarios:
        failures = validate(scenario)
        if failures:
            raise ValueError(failures[0].message)
        combined = list(dict.fromkeys(scenario.uncovered_paths + manifest.uncovered_paths))
        candidate = scenario.model_copy(update={"uncovered_paths": combined})
        key = dedup_key(candidate)
        if key in results and results[key].id != candidate.id:
            continue
        results[key] = candidate
    return list(results.values())
