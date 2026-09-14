"""ローカルデータ検証の実動受入。"""

from .runner import AcceptanceError, AcceptanceResult, run_acceptance

__all__ = ["AcceptanceError", "AcceptanceResult", "run_acceptance"]
