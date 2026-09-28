"""管理担当者向けの週次改善レポートと明示的な保存期限処理。"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..field_learning.store import SqliteFieldLearningStore
from .improvement_events import ImprovementEventLedger
from .improvement_report import weekly_field_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events-db", type=Path, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--field-learning-db", type=Path)
    parser.add_argument("--minimum-gap-cases")
    parser.add_argument("--repeat-days", type=int)
    parser.add_argument("--threshold-version")
    parser.add_argument("--purge-before", type=datetime.fromisoformat)
    args = parser.parse_args(argv)
    if not args.events_db.is_file():
        parser.error("events DB does not exist")
    ledger = ImprovementEventLedger(args.events_db)
    if args.purge_before is not None:
        ledger.delete_before(args.purge_before)
    report = ledger.weekly_summary(args.end_date)
    if args.field_learning_db is not None:
        if not args.field_learning_db.is_file():
            parser.error("field learning DB does not exist")
        if (args.minimum_gap_cases is None or args.repeat_days is None
                or args.threshold_version is None):
            parser.error("field report requires explicit approved thresholds")
        try:
            minimum = Decimal(args.minimum_gap_cases)
        except InvalidOperation:
            parser.error("minimum gap must be numeric")
        report["field_learning"] = weekly_field_report(
            SqliteFieldLearningStore(args.field_learning_db), args.end_date,
            minimum_gap_cases=minimum, repeat_days=args.repeat_days,
            threshold_version=args.threshold_version,
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
