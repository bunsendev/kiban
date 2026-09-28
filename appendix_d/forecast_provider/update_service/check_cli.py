"""現場PCの起動・終業処理から更新を確認する独立CLI。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .check_service import UpdateCheckService, UpdateCheckStore


def check_update(*, trigger: str, config_dir: Path, settings_dir: Path,
                 current_version: str) -> dict:
    service = UpdateCheckService(
        store=UpdateCheckStore(settings_dir / "update-checks.sqlite3"),
        current_version=current_version, channel="pilot",
        public_key_path=config_dir / "release-update-public.pem",
    )
    return service.check(trigger=trigger)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", choices=["STARTUP", "END_OF_DAY"], required=True)
    args = parser.parse_args()
    version = os.environ.get("KIBAN_FIELD_PILOT_VERSION")
    if not version:
        raise SystemExit("UPDATE_VERSION_NOT_CONFIGURED")
    result = check_update(
        trigger=args.trigger,
        config_dir=Path("/var/lib/kiban/pilot"),
        settings_dir=Path("/var/lib/kiban/pilot-settings"),
        current_version=version,
    )
    latest = result["last_check"] or {}
    print(json.dumps({"status": latest.get("status"),
                      "available_version": latest.get("available_version")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
