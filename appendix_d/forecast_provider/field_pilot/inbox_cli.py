"""Field Pilot起動時に投入済みファイルを一度だけ分類する。"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from .inbox_ledger import InboxLedger
from .inbox_policy import InboxPolicyError, load_inbox_policy
from .inbox_processor import InboxProcessor

logger = logging.getLogger("kiban.field_pilot.inbox")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    options = parser.parse_args()
    try:
        policy = load_inbox_policy(options.policy)
    except InboxPolicyError:
        print("INBOX_POLICY_SETUP_REQUIRED")
        return 0
    try:
        ledger = InboxLedger(options.inbox_root / "inbox.sqlite3")
        count = InboxProcessor(options.inbox_root, policy, ledger).scan()
    except (OSError, ValueError, sqlite3.DatabaseError) as exc:
        logger.error("inbox scan unavailable: %s", type(exc).__name__)
        print("INBOX_SCAN_FAILED")
        return 1
    print(f"INBOX_SCANNED={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
