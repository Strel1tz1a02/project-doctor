import argparse
import json
from pathlib import Path

from project_doctor.entrypoints.bootstrap import bootstrap
from project_doctor.entrypoints.mcp_server import build_server
from project_doctor.entrypoints.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Project Doctor business MCP server")
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.model_validate_json(args.settings.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        parser.error("manifest must be a JSON object")
    try:
        workflows = bootstrap(settings, manifest)
    except RuntimeError as exc:
        parser.exit(2, f"{exc}\n")
    build_server(workflows, settings.tool_timeouts).run(transport="stdio")


if __name__ == "__main__":
    main()
