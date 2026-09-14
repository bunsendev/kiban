"""mappingドライランの固定契約。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FORMAT_VERSION = "kiban-mapping-dry-run-report/v1"
SUITE_ID = "kiban-mapping-dry-run/v1"
OUTCOMES = frozenset({"READY_FOR_NORMALIZATION", "REVIEW_REQUIRED", "BLOCKED"})
BLOCKING_CHECKS = frozenset(
    {
        "SOURCE_PATH_SAFE",
        "SOURCE_SIZE_LIMIT",
        "SOURCE_ENCODING",
        "MAPPING_CONTRACT",
        "HEADER_UNIQUE",
        "REQUIRED_COLUMNS",
        "CSV_STRUCTURE",
        "SAMPLE_ROWS",
        "QUANTITY_RECONCILIATION",
    }
)
CHECK_IDS = BLOCKING_CHECKS | {"SAMPLE_ACCEPTANCE"}
LIMITATIONS = (
    "sample外の行品質と全件数量は検査していない。",
    "ドライランは原本取込、台帳登録、正規化job、業務承認を実行しない。",
    "READY_FOR_NORMALIZATIONは実データ受入や予測精度を保証しない。",
)


@dataclass(frozen=True)
class DryRunLimits:
    sample_rows: int = 1_000
    max_source_bytes: int = 100_000_000
    max_mapping_bytes: int = 65_536

    def __post_init__(self) -> None:
        if not 1 <= self.sample_rows <= 10_000:
            raise ValueError("sample rowsは1以上10000以下です")
        if not 1_024 <= self.max_source_bytes <= 1_000_000_000:
            raise ValueError("source上限は1 KiB以上1 GB以下です")
        if not 1_024 <= self.max_mapping_bytes <= 1_048_576:
            raise ValueError("mapping上限は1 KiB以上1 MiB以下です")

    def as_dict(self) -> dict[str, int]:
        return {
            "sample_rows": self.sample_rows,
            "max_source_bytes": self.max_source_bytes,
            "max_mapping_bytes": self.max_mapping_bytes,
        }


DEFAULT_LIMITS = DryRunLimits()


def check(check_id: str, passed: bool, actual: Any, expected: Any) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "PASSED" if passed else "FAILED",
        "actual": actual,
        "expected": expected,
    }


class InputFailure(RuntimeError):
    def __init__(self, check_id: str) -> None:
        super().__init__("mappingドライランの入力検査に失敗しました")
        self.check_id = check_id
