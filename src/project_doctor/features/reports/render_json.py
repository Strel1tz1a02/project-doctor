import json

from pydantic import JsonValue


def render_json(payload: dict[str, JsonValue]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
