import hashlib
import json

from project_doctor.models.scenario import Scenario


def dedup_key(scenario: Scenario) -> str:
    data = scenario.model_dump(mode="json", exclude={"id", "version", "uncovered_paths"})
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
