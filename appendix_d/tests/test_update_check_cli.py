"""起動・終業の更新確認は業務処理に独立し、結果を同じ台帳へ保存する。"""

from forecast_provider.update_service.check_cli import check_update
from forecast_provider.update_service.check_service import UpdateCheckService, UpdateCheckStore


def test_startup_and_end_of_day_share_cache_without_key(tmp_path):
    config = tmp_path / "Config"
    config.mkdir()
    settings = tmp_path / "LocalSettings"
    first = check_update(trigger="STARTUP", config_dir=config, settings_dir=settings,
                         current_version="0.1.0-field-pilot.3")
    assert first["last_check"]["status"] == "UNCONFIGURED"
    second = check_update(trigger="END_OF_DAY", config_dir=config, settings_dir=settings,
                          current_version="0.1.0-field-pilot.3")
    assert second["last_check"]["trigger"] == "STARTUP"
    assert UpdateCheckStore(settings / "update-checks.sqlite3").latest() == second["last_check"]


def test_installing_public_key_retries_an_unconfigured_check(tmp_path):
    key = tmp_path / "release-update-public.pem"
    store = UpdateCheckStore(tmp_path / "update-checks.sqlite3")

    class NoRelease:
        calls = 0

        def check(self, **_):
            self.calls += 1
            return None

    provider = NoRelease()
    service = UpdateCheckService(
        store=store, current_version="0.1.0-field-pilot.4", channel="pilot",
        public_key_path=key, provider=provider,
    )
    assert service.check(trigger="STARTUP")["last_check"]["status"] == "UNCONFIGURED"
    key.write_bytes(b"a test key")
    assert service.check(trigger="END_OF_DAY")["last_check"]["status"] == "NO_RELEASE"
    assert provider.calls == 1
