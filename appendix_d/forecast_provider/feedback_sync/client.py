"""終業時Package生成、Outbox再送のローカル入口。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path

from .crypto import encrypt_package
from .policy import FeedbackStore
from .privacy import collect_events, manifest, minimize, validate_package
from .support import queue_support
from .transport import send_pending
from .updates import check_update


def _client_config(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    required = {"client_id", "endpoint", "public_key_file"}
    optional = {"update_manifest_url", "update_signing_key_file"}
    if (not required <= set(value) or not set(value) <= required | optional
            or ("update_manifest_url" in value) != ("update_signing_key_file" in value)
            or not value["client_id"].isascii()
            or not value["client_id"].replace("-", "").replace("_", "").isalnum()
            or not 1 <= len(value["client_id"]) <= 80):
        raise ValueError("FEEDBACK_CLIENT_CONFIG_INVALID")
    return value


def finish_day(store: FeedbackStore, *, improvement_db: Path, client: dict,
               hmac_secret: bytes, token: str, public_key: bytes,
               day=None, sender=None) -> dict:
    # 現場の業務日付は日本時間。UTCの午後に翌日へずらさない。
    day = day or (datetime.now(UTC) + timedelta(hours=9)).date()
    current = store.current()
    policy = current["policy"]
    if policy["level"] == 0 or current["version"] is None:
        return {"status": "LOCAL_ONLY", "sent": 0, "retryable": 0, "rejected": 0}
    package_id = hashlib.sha256(
        f"{client['client_id']}:{day.isoformat()}:{current['version']}".encode(),
    ).hexdigest()[:32]
    with store._db() as db:
        exists = db.execute("SELECT 1 FROM outbox WHERE package_id=?", (package_id,)).fetchone()
    if exists is None:
        payload = minimize(collect_events(improvement_db, day), policy,
                           client_id=client["client_id"], secret=hmac_secret)
        package = {"level": policy["level"], "payload": payload,
                   "manifest": manifest(payload, policy_version=current["version"],
                                        application_version=version("bunsen-forecast-provider"))}
        validate_package(package, max_level=policy["level"])
        envelope = encrypt_package(package, public_key, package_id=package_id,
                                   client_id=client["client_id"])
        store.queue(package_id, current["version"], envelope)
    result = send_pending(store, url=client["endpoint"], token=token,
                          **({"sender": sender} if sender else {}))
    status = ("NEEDS_ADMIN" if result["rejected"] else "SAVED_FOR_RETRY"
              if result["retryable"] else "COMPLETED")
    return {"status": status, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description="Field Pilot secure feedback sync")
    parser.add_argument("--inbox-root", type=Path, required=True)
    parser.add_argument("--client-config", type=Path, required=True)
    parser.add_argument("--action", choices=["finish", "retry", "support"], required=True)
    parser.add_argument("--support-file", type=Path)
    parser.add_argument("--consent-id")
    args = parser.parse_args()
    client = _client_config(args.client_config)
    # Windows DPAPIで保護された資格情報をホスト側で開き、stdinで一度だけ渡す。
    credentials = json.loads(sys.stdin.readline())
    secret = bytes.fromhex(credentials["hmac_secret_hex"])
    token = credentials["bearer_token"]
    if len(secret) < 32 or len(token) < 32:
        raise ValueError("FEEDBACK_CREDENTIAL_INVALID")
    store = FeedbackStore(args.inbox_root / "feedback.sqlite3")
    store.prune_outbox()
    if args.action == "finish":
        result = finish_day(
            store, improvement_db=args.inbox_root / "improvement-events.sqlite3",
            client=client, hmac_secret=secret, token=token,
            public_key=Path(client["public_key_file"]).read_bytes(),
        )
    elif args.action == "support":
        if args.support_file is None or not args.consent_id:
            raise ValueError("SUPPORT_INPUT_REQUIRED")
        package_id = queue_support(
            store, consent_id=args.consent_id, source=args.support_file,
            client_id=client["client_id"], destination=client["endpoint"],
            public_key=Path(client["public_key_file"]).read_bytes(),
        )
        result = send_pending(store, url=client["endpoint"], token=token)
        result["package_id"] = package_id
    else:
        result = send_pending(store, url=client["endpoint"], token=token)
    if args.action == "finish" and "update_manifest_url" in client:
        try:
            result["update"] = check_update(
                client["update_manifest_url"],
                Path(client["update_signing_key_file"]).read_bytes(),
                version("bunsen-forecast-provider"),
            )
        except Exception:  # 更新確認障害は終業処理・ローカル運用を妨げない。
            result["update"] = {"status": "UNAVAILABLE"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
