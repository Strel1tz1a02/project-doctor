"""Extract the source lines a unified diff actually touches (new-file side).

Added lines are recorded at their new-side line number; a hunk that only
removes lines is recorded once at its new-side start. Binary patches, renames
and whole-file deletions are rejected — the repair workflow forbids them.
"""

from __future__ import annotations


def _new_side_start(header: str) -> int:
    try:
        plus = header.split("@@")[1].strip().split()[1]
        return int(plus[1:].split(",")[0])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"malformed hunk header: {header}") from exc


def extract_patch_locations(diff_text: str) -> list[dict[str, object]]:
    if not diff_text.strip():
        raise ValueError("patch diff is empty")
    locations: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    path: str | None = None
    new_line = 0
    hunk_start = 0
    hunk_has_add = False
    hunk_has_del = False
    in_hunk = False

    def record(target: str, line: int) -> None:
        key = (target, line)
        if key not in seen:
            seen.add(key)
            locations.append({"path": target, "line": line})

    def flush_hunk() -> None:
        if in_hunk and hunk_has_del and not hunk_has_add and path is not None:
            record(path, hunk_start)

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git"):
            flush_hunk()
            in_hunk, path = False, None
            continue
        if not in_hunk:
            if raw.startswith(("Binary files", "GIT binary patch")):
                raise ValueError("binary patches are not supported")
            if raw.startswith(("rename from", "rename to")):
                raise ValueError("renames are not supported")
            if raw.startswith("+++ "):
                candidate = raw[4:].strip()
                if candidate == "/dev/null":
                    raise ValueError("file deletions are not supported")
                path = candidate[2:] if candidate.startswith("b/") else candidate
                continue
            if raw.startswith("@@ "):
                if path is None:
                    raise ValueError("hunk without a file header")
                new_line = _new_side_start(raw)
                hunk_start, hunk_has_add, hunk_has_del = new_line, False, False
                in_hunk = True
            continue
        if raw.startswith("@@ "):
            flush_hunk()
            new_line = _new_side_start(raw)
            hunk_start, hunk_has_add, hunk_has_del = new_line, False, False
            continue
        if raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            assert path is not None
            record(path, new_line)
            hunk_has_add = True
            new_line += 1
        elif raw.startswith("-"):
            hunk_has_del = True
        else:
            new_line += 1
    flush_hunk()
    if not locations:
        raise ValueError("patch diff touches no source lines")
    return locations
