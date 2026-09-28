"""Field Pilot起動時に投入済みファイルを一度だけ分類する。"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from .improvement_events import ImprovementEventLedger
from .inbox_ledger import InboxLedger
from .inbox_processor import InboxProcessor
from .learning_service import LearningService

logger = logging.getLogger("kiban.field_pilot.inbox")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    options = parser.parse_args()
    try:
        learning = LearningService(options.inbox_root, options.policy)
        policy = learning.recognition_policy()
        ledger = InboxLedger(options.inbox_root / "inbox.sqlite3")
        events = ImprovementEventLedger(options.inbox_root / "improvement-events.sqlite3")
        count = InboxProcessor(
            options.inbox_root, policy, ledger, review_observer=learning.consider,
            improvement_events=events,
        ).scan()
    except (OSError, ValueError, sqlite3.DatabaseError) as exc:
        logger.error("inbox scan unavailable: %s", type(exc).__name__)
        print("INBOX_SCAN_FAILED")
        return 1
    print(f"INBOX_SCANNED={count}")
    if not policy.required:
        print("INBOX_POLICY_SETUP_REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
