"""プロバイダー例外の区分

9.1「一時障害は指数バックオフで最大3回。データ不備は自動再試行しない」を
実装で判別可能にするための区分。プロバイダーは以下のいずれかを送出する。
未分類の例外が送出された場合、実行基盤は NonRetryable として扱う。
"""

from __future__ import annotations


class ProviderError(Exception):
    """全プロバイダー例外の基底。"""

    retryable: bool = False
    run_state: str = "FAILED"


class RetryableProviderError(ProviderError):
    """一時障害。指数バックオフで再試行する（最大3回）。

    例: イメージ取得失敗、一時的なリソース不足、外部APIの5xx。
    """

    retryable = True


class NonRetryableProviderError(ProviderError):
    """再試行しても解消しない障害。runをFAILEDとし、他runの比較は継続する。"""

    retryable = False


class InsufficientHistoryError(NonRetryableProviderError):
    """min_history_days 未満の系列。

    7.1により、当該系列は新商品区分として通常ランキングから分離される。
    run全体を失敗させず、系列単位で除外して継続すること。
    """


class ContractViolationError(NonRetryableProviderError):
    """入出力DataFrameが契約を満たさない。プロバイダー実装の不具合。"""


class TimeoutProviderError(ProviderError):
    """RunContext.deadline を超過した。"""

    retryable = False
    run_state = "TIMED_OUT"
