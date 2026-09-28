"""公開配布RepositoryのReleaseだけを読むAdapter。資格情報を送らない。"""

from __future__ import annotations

import json
import ssl
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from .manifest import UpdateManifest, version_key

OWNER = "bunsendev"
REPOSITORY = "kiban-releases"
API_URL = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases?per_page=20"
ASSET_PREFIX = f"/{OWNER}/{REPOSITORY}/releases/download/"


class _SecureRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if (parsed.scheme != "https" or parsed.hostname not in {
                "github.com", "release-assets.githubusercontent.com",
                "objects.githubusercontent.com"}):
            raise ValueError("UPDATE_REDIRECT_NOT_ALLOWED")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _read(url: str, limit: int) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("UPDATE_TLS_REQUIRED")
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(
        _SecureRedirect(), urllib.request.HTTPSHandler(context=context),
    )
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "kiban-field-pilot-updater",
    })
    with opener.open(request, timeout=10) as response:
        value = response.read(limit + 1)
    if len(value) > limit:
        raise ValueError("UPDATE_RESPONSE_TOO_LARGE")
    return value


def _asset_url(url: str, tag: str, name: str) -> str:
    parsed = urlparse(url)
    expected = f"{ASSET_PREFIX}{tag}/{name}"
    if (parsed.scheme != "https" or parsed.hostname != "github.com"
            or parsed.path != expected or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise ValueError("UPDATE_ASSET_URL_INVALID")
    return url


@dataclass(frozen=True)
class ReleaseOffer:
    manifest: UpdateManifest
    package_url: str
    status: str


class GitHubReleaseUpdateProvider:
    def __init__(self, *, fetcher=None):
        self.fetcher = fetcher or _read

    def check(self, *, current_version: str, channel: str,
              public_pem: bytes) -> ReleaseOffer | None:
        releases = json.loads(self.fetcher(API_URL, 1_000_000))
        if not isinstance(releases, list) or len(releases) > 20:
            raise ValueError("UPDATE_RELEASE_LIST_INVALID")
        selected = []
        for release in releases:
            if not isinstance(release, dict) or release.get("draft") is not False:
                continue
            tag = release.get("tag_name")
            if not isinstance(tag, str) or not tag.startswith("v"):
                continue
            try:
                key = version_key(tag[1:])
            except ValueError:
                continue
            if (channel == "pilot") != ("-field-pilot." in tag):
                continue
            selected.append((key, tag, release))
        if not selected:
            return None
        _, tag, release = max(selected, key=lambda item: item[0])
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise ValueError("UPDATE_ASSET_LIST_INVALID")
        names = {}
        for asset in assets:
            if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
                raise ValueError("UPDATE_ASSET_LIST_INVALID")
            if asset["name"] in names:
                raise ValueError("UPDATE_ASSET_DUPLICATE")
            names[asset["name"]] = asset
        for required in ("manifest.json", "manifest.sig"):
            if required not in names:
                raise ValueError("UPDATE_MANIFEST_MISSING")
        raw = self.fetcher(_asset_url(names["manifest.json"]["browser_download_url"],
                                      tag, "manifest.json"), 65_536)
        signature = self.fetcher(_asset_url(names["manifest.sig"]["browser_download_url"],
                                            tag, "manifest.sig"), 8_192)
        manifest = UpdateManifest.parse(raw, signature, public_pem)
        if manifest.version != tag[1:] or manifest.channel != channel:
            raise ValueError("UPDATE_MANIFEST_RELEASE_MISMATCH")
        if manifest.package not in names:
            raise ValueError("UPDATE_PACKAGE_MISSING")
        package = names[manifest.package]
        if package.get("size") != manifest.size_bytes:
            raise ValueError("UPDATE_PACKAGE_SIZE_MISMATCH")
        return ReleaseOffer(
            manifest=manifest,
            package_url=_asset_url(package["browser_download_url"], tag, manifest.package),
            status=manifest.availability(current_version, channel),
        )
