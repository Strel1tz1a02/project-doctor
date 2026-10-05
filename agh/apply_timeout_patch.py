"""Apply a narrowly scoped local AGH adapter patch; rebuild AGH afterwards.

Pinned to 2ef9b71. Does not alter business tools or provider configuration.
"""

import argparse
from pathlib import Path


def apply(root: Path) -> None:
    preset = root.resolve() / "packages/base/presets/base.yaml"
    preset_source = preset.read_text(encoding="utf-8")
    old_timeouts = "timeouts: { web_fetch: 30000, skill_helper_import: 240000 }"
    new_timeouts = (
        "timeouts: { web_fetch: 30000, skill_helper_import: 240000, "
        "mcp_pd_8d1a978e_prepare_environment: 720000, "
        "mcp_pd_8d1a978e_run_experiment: 720000, "
        "mcp_pd_8d1a978e_finish_task: 720000 }"
    )
    if new_timeouts not in preset_source:
        if preset_source.count(old_timeouts) != 1:
            raise ValueError("AGH base preset differs from pinned version")
        preset.write_text(preset_source.replace(old_timeouts, new_timeouts), encoding="utf-8")
    path = root.resolve() / "packages/base/src/mcp/connect.ts"
    source = path.read_text(encoding="utf-8")
    marker = "// Project Doctor: bounded long-running MCP calls."
    if marker in source:
        print("AGH timeout patch already applied")
        return
    old_type = "options: { signal: AbortSignal },"
    old_call = """        signal: opts.signal,
      })
      const content = result.content.map(callContent)"""
    new_call = """        signal: opts.signal,
        // Project Doctor: bounded long-running MCP calls.
        ...(() => {
          const raw = process.env['AGNES_MCP_CALL_TIMEOUT_MS']
          if (raw === undefined) return {}
          const value = Number(raw)
          if (!Number.isFinite(value) || value <= 0 || value > 3600000)
            throw new Error('AGNES_MCP_CALL_TIMEOUT_MS must be within (0, 3600000]')
          return { timeout: value }
        })(),
      })
      const content = result.content.map(callContent)"""
    if source.count(old_type) != 1 or source.count(old_call) != 1:
        raise ValueError("AGH source differs from pinned adapter; refusing to patch")
    path.write_text(
        source.replace(old_type, "options: { signal: AbortSignal; timeout?: number },").replace(
            old_call, new_call
        ),
        encoding="utf-8",
    )
    print("Patched AGH MCP timeout adapter; rebuild @agnes/cli before use")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("agh_root", type=Path)
    apply(parser.parse_args().agh_root)
