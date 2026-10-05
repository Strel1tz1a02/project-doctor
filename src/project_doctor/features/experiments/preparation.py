"""The versioned, controlled read-only workload preparation protocol."""

import hashlib
import json

from project_doctor.models.experiment import WarmupSpec
from project_doctor.models.scenario import RequestStep


def preparation_digest(warmup: WarmupSpec, step: RequestStep) -> str:
    content = {"warmup": warmup.model_dump(mode="json"), "request": step.model_dump(mode="json")}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
