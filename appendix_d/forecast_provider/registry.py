"""プロバイダーレジストリ

PRV-001（交換性）の実装点。プロバイダーの追加は
「ForecastProviderの実装」＋「本レジストリへの登録」の2手順で完了し、
画面・API・DBスキーマの変更を要さない。

実行基盤はレジストリ越しにのみプロバイダーへアクセスし、
具体クラスをimportしてはならない。
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable

from .contracts import ForecastProvider, ProviderMetadata
from .errors import NonRetryableProviderError

ProviderFactory = Callable[[], ForecastProvider]


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, provider_id: str, factory: ProviderFactory) -> None:
        if not isinstance(provider_id, str) or not provider_id:
            raise NonRetryableProviderError("provider_idは空でない文字列で指定します")
        if provider_id in self._factories:
            raise NonRetryableProviderError(f"provider_idが重複しています: {provider_id}")
        try:
            provider = factory()
            metadata = provider.metadata()
        except Exception as exc:
            raise NonRetryableProviderError(
                f"provider factory/metadataの検証に失敗しました: {provider_id}"
            ) from exc
        if metadata.provider_id != provider_id:
            raise NonRetryableProviderError(
                f"registry key={provider_id!r} と metadata.provider_id="
                f"{metadata.provider_id!r} が一致しません"
            )
        self._factories[provider_id] = factory

    def create(self, provider_id: str) -> ForecastProvider:
        try:
            factory = self._factories[provider_id]
        except KeyError as exc:
            raise NonRetryableProviderError(f"未登録のプロバイダーです: {provider_id}") from exc
        provider = factory()
        metadata = provider.metadata()
        if metadata.provider_id != provider_id:
            raise NonRetryableProviderError(
                f"registry key={provider_id!r} と metadata.provider_id="
                f"{metadata.provider_id!r} が一致しません"
            )
        return provider

    def list_metadata(self) -> list[ProviderMetadata]:
        """GET /forecast-providers（8.2）の応答元。

        画面はこの一覧のみを参照するため、プロバイダーが増えても
        画面側の変更を要さない。
        """
        return [self.create(pid).metadata() for pid in sorted(self._factories)]


registry = ProviderRegistry()


def _register_providers() -> None:
    from .providers import builtin_baseline

    registry.register(builtin_baseline.PROVIDER_ID, builtin_baseline.build)
    if importlib.util.find_spec("statsforecast") is not None:
        from .providers import statsforecast_ets

        registry.register(statsforecast_ets.PROVIDER_ID, statsforecast_ets.build)


_register_providers()
