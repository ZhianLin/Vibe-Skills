from __future__ import annotations

import os
from pathlib import Path
import stat


def assert_local_destination(destination: Path, *, target_root: Path) -> None:
    """Reject destinations outside the declared root and linked path components."""
    root = target_root.absolute()
    path = destination.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"Materialization destination is outside target root: {destination}") from exc
    if ".." in relative.parts:
        raise RuntimeError(f"Materialization destination is outside target root: {destination}")

    current = path
    while True:
        try:
            status = current.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(status.st_mode) or (
                os.name == "nt"
                and status.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise RuntimeError(f"Refusing linked or reparse-point materialization path: {current}")
        if current == root:
            break
        current = current.parent

    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise RuntimeError(f"Materialization destination is outside target root: {destination}") from exc
