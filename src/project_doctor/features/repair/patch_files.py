"""Extract the source lines a unified diff actually touches (new-file side).

Added lines are recorded at their new-side line number; a hunk that only
removes lines is recorded once at its new-side start. Binary patches, renames
and whole-file deletions are rejected — the repair workflow forbids them.

A hunk is bounded by the line counts in its ``@@`` header, so a content line
that merely starts with ``-``/``+`` (e.g. a removed ``-- SQL`` comment) is
never mistaken for a file header, and the ``---``/``+++`` headers of a
following file are only read once the previous hunk is complete.
"""

from __future__ import annotations


def _parse_hunk(header: str) -> tuple[int, int, int]:
    """Return ``(old_count, new_count, new_start)`` for an ``@@ -a,b +c,d @@`` header."""
    try:
        old_token, new_token = header.split("@@")[1].strip().split()[:2]
    except (IndexError, ValueError) as exc:
        raise ValueError(f"malformed hunk header: {header}") from exc
    sides: list[tuple[int, int]] = []
    for token, sign in ((old_token, "-"), (new_token, "+")):
        parts = token[1:].split(",")
        if not token.startswith(sign) or len(parts) > 2:
            raise ValueError(f"malformed hunk header: {header}")
        try:
            start = int(parts[0])
            count = int(parts[1]) if len(parts) == 2 else 1
        except ValueError as exc:
            raise ValueError(f"malformed hunk header: {header}") from exc
        if start < 0 or count < 0:
            raise ValueError(f"malformed hunk header: {header}")
        sides.append((start, count))
    return sides[0][1], sides[1][1], sides[1][0]


def extract_patch_locations(diff_text: str) -> list[dict[str, object]]:
    if not diff_text.strip():
        raise ValueError("patch diff is empty")
    locations: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    path: str | None = None
    new_line = 0
    old_left = 0
    new_left = 0
    hunk_start = 0
    hunk_has_add = False
    hunk_has_del = False
    in_hunk = False

    def record(target: str, line: int) -> None:
        key = (target, line)
        if key not in seen:
            seen.add(key)
            locations.append({"path": target, "line": line})

    def end_hunk() -> None:
        nonlocal in_hunk
        if old_left or new_left:
            raise ValueError("hunk line counts do not match the diff body")
        if hunk_has_del and not hunk_has_add and path is not None:
            record(path, hunk_start)
        in_hunk = False

    for raw in diff_text.splitlines():
        if in_hunk:
            if raw.startswith("\\"):
                continue
            if raw.startswith("-"):
                old_left -= 1
                hunk_has_del = True
            elif raw.startswith("+"):
                assert path is not None
                record(path, new_line)
                new_line += 1
                new_left -= 1
                hunk_has_add = True
            else:
                new_line += 1
                old_left -= 1
                new_left -= 1
            if old_left <= 0 and new_left <= 0:
                end_hunk()
            continue
        if raw.startswith("diff --git"):
            path = None
        elif raw.startswith(("Binary files", "GIT binary patch")):
            raise ValueError("binary patches are not supported")
        elif raw.startswith(("rename from", "rename to")):
            raise ValueError("renames are not supported")
        elif raw.startswith("@@"):
            if path is None:
                raise ValueError("hunk without a file header")
            old_left, new_left, new_line = _parse_hunk(raw)
            hunk_start = new_line
            hunk_has_add = hunk_has_del = False
            in_hunk = True
        elif raw.startswith("+++ "):
            candidate = raw[4:].split("\t", 1)[0].strip()
            if candidate == "/dev/null":
                raise ValueError("file deletions are not supported")
            path = candidate[2:] if candidate.startswith("b/") else candidate
    if in_hunk:
        end_hunk()
    if not locations:
        raise ValueError("patch diff touches no source lines")
    return locations
