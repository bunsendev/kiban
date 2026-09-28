"""中断再開できるRelease asset取得と完全性検証。"""

from __future__ import annotations

import hashlib
import os
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .github_release import ASSET_PREFIX, _SecureRedirect
from .manifest import UpdateManifest

CHUNK = 1024 * 1024


def _open(url: str, offset: int):
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(
        _SecureRedirect(), urllib.request.HTTPSHandler(context=context),
    )
    headers = {"User-Agent": "kiban-field-pilot-updater"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    return opener.open(urllib.request.Request(url, headers=headers), timeout=30)


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()


def download_verified(manifest: UpdateManifest, package_url: str, root: Path,
                      *, opener=None) -> Path:
    parsed = urlparse(package_url)
    if (parsed.scheme != "https" or parsed.hostname != "github.com"
            or not parsed.path.startswith(ASSET_PREFIX)
            or not parsed.path.endswith("/" + manifest.package)
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("UPDATE_ASSET_URL_INVALID")
    if root.is_symlink():
        raise ValueError("UPDATE_DIRECTORY_UNSAFE")
    root.mkdir(parents=True, exist_ok=True)
    target = root / manifest.package
    partial = root / f"{manifest.package}.part"
    if target.is_symlink() or partial.is_symlink():
        raise ValueError("UPDATE_PACKAGE_PATH_UNSAFE")
    if target.is_file():
        if target.stat().st_size == manifest.size_bytes and _digest(target) == manifest.sha256:
            return target
        raise ValueError("UPDATE_EXISTING_PACKAGE_INVALID")
    offset = partial.stat().st_size if partial.is_file() else 0
    if offset > manifest.size_bytes:
        raise ValueError("UPDATE_PARTIAL_TOO_LARGE")
    with (opener or _open)(package_url, offset) as response:
        status = response.status
        if offset and status != 206:
            # Rangeを無視するサーバーの本文を既存部分へ追記しない。
            raise ValueError("UPDATE_RESUME_NOT_SUPPORTED")
        if not offset and status != 200:
            raise ValueError("UPDATE_DOWNLOAD_STATUS_INVALID")
        if offset and not response.headers.get("Content-Range", "").startswith(
                f"bytes {offset}-"):
            raise ValueError("UPDATE_RESUME_RANGE_INVALID")
        with partial.open("ab" if offset else "wb") as output:
            total = offset
            while chunk := response.read(CHUNK):
                total += len(chunk)
                if total > manifest.size_bytes:
                    raise ValueError("UPDATE_DOWNLOAD_TOO_LARGE")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    if partial.stat().st_size != manifest.size_bytes:
        raise ValueError("UPDATE_DOWNLOAD_INCOMPLETE")
    if _digest(partial) != manifest.sha256:
        quarantine = root / f"{manifest.package}.corrupt"
        if quarantine.exists() or quarantine.is_symlink():
            raise ValueError("UPDATE_QUARANTINE_EXISTS")
        os.replace(partial, quarantine)
        raise ValueError("UPDATE_SHA256_MISMATCH")
    os.replace(partial, target)
    return target
