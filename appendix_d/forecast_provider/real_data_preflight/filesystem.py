"""原本を読まずにdata rootの実効アクセス境界を検査する。"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path

from .contracts import RootRequirement

WritableProbe = Callable[[Path], bool]


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _contains_symlink(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def _readable_directory(path: Path) -> bool:
    if not os.access(path, os.R_OK | os.X_OK):
        return False
    try:
        with os.scandir(path) as entries:
            next(entries, None)
    except OSError:
        return False
    return True


def probe_writable(path: Path) -> bool:
    """非永続の1 byte probeを作成・削除してmountの実効権限を確認する。"""
    target = path / f".kiban-preflight-{uuid.uuid4().hex}.tmp"
    descriptor = None
    try:
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(descriptor, b"1")
        return True
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)
            target.unlink(missing_ok=True)


def inspect_filesystem(
    requirements: tuple[RootRequirement, ...],
    application_root: Path,
    *,
    writable_probe: WritableProbe = probe_writable,
) -> list[dict]:
    resolved_application = application_root.resolve()
    resolved = {item.root_id: item.path.resolve() for item in requirements}
    overlaps: dict[str, list[str]] = {item.root_id: [] for item in requirements}
    for index, left in enumerate(requirements):
        for right in requirements[index + 1 :]:
            if _is_within(resolved[left.root_id], resolved[right.root_id]) or _is_within(
                resolved[right.root_id], resolved[left.root_id]
            ):
                overlaps[left.root_id].append(right.root_id)
                overlaps[right.root_id].append(left.root_id)

    observations = []
    for requirement in requirements:
        path = requirement.path
        exists = path.exists()
        directory = exists and path.is_dir()
        readable = directory and _readable_directory(path)
        writable = directory and writable_probe(path)
        observations.append(
            {
                "root_id": requirement.root_id,
                "exists": exists,
                "directory": directory,
                "contains_symlink": _contains_symlink(path),
                "readable": readable,
                "writable": writable,
                "expected_writable": requirement.writable,
                "outside_application_root": not _is_within(
                    resolved[requirement.root_id], resolved_application
                ),
                "overlaps": sorted(overlaps[requirement.root_id]),
            }
        )
    return observations
