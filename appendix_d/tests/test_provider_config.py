"""前処理識別の必須性と不変性。"""

from dataclasses import FrozenInstanceError, replace

import pytest

from forecast_provider import ProviderConfig


@pytest.mark.parametrize("version", ["", "   ", None, 1, False, []])
def test_preprocessing_version_rejects_invalid_values(version):
    with pytest.raises(ValueError, match="preprocessing_version"):
        ProviderConfig("builtin-baseline", "seasonal_naive_7", preprocessing_version=version)


def test_preprocessing_version_is_required_and_frozen():
    with pytest.raises(TypeError, match="preprocessing_version"):
        ProviderConfig("builtin-baseline", "seasonal_naive_7")
    config = ProviderConfig("p", "m", preprocessing_version="preprocess-v1")
    assert config.preprocessing_version == "preprocess-v1"
    with pytest.raises(FrozenInstanceError):
        config.preprocessing_version = "preprocess-v2"
    assert replace(config, preprocessing_version="preprocess-v2").preprocessing_version != (
        config.preprocessing_version
    )
