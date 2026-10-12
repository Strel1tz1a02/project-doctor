"""Process-held lease for one repair attempt; the OS releases it after a crash."""

from __future__ import annotations

import hashlib
import importlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class RepairBusy(ValueError):
    """Another live process is still building or retesting this repair."""


@contextmanager
def repair_lease(workspace_root: Path, repair_id: str) -> Iterator[None]:
    root = workspace_root.resolve()
    lock_dir = root / "repair-locks"
    if lock_dir.is_symlink():
        raise ValueError("repair lock directory is a symlink")
    lock_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(repair_id.encode("utf-8")).hexdigest() + ".lock"
    path = lock_dir / name
    if path.is_symlink():
        raise ValueError("repair lock file is a symlink")
    with path.open("a+b") as handle:
        if path.is_symlink():
            raise ValueError("repair lock file became a symlink")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RepairBusy("repair is still running in another process") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
