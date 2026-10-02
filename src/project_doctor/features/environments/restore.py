"""Pure restoration verdicts: decide verified vs quarantined from measured evidence."""

from __future__ import annotations


def restore_verified(
    *,
    actual_snapshot_id: str | None,
    expected_snapshot_id: str,
    index_removed: bool,
) -> tuple[bool, str | None]:
    """Return ``(verified, reason)`` from the post-restore measurements.

    A restore only counts as verified when the restored database dump matches the
    baseline snapshot *and* the temporary index is gone; a restart alone never passes.
    """
    if actual_snapshot_id != expected_snapshot_id:
        return False, "restored snapshot does not match the baseline snapshot"
    if not index_removed:
        return False, "temporary index was not removed during restore"
    return True, None
