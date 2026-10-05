import os

import pytest

from portable.runtime.paths import DataPaths
from portable.runtime.performance import write_json


@pytest.mark.skipif(os.name != 'nt', reason='Windows extended-path behavior')
def test_deep_data_path_preserves_directory_and_checkpoint(tmp_path):
    root = tmp_path / ('日本語の配布先' * 10) / 'Data'
    paths = DataPaths(root)
    paths.ensure()
    target = paths.state / 'ForecastBatches' / ('a' * 64) / ('b' * 64 + '.json')
    assert len(str(target)) > 260
    write_json(target, {'quantity': 0})
    assert 'quantity' in target.read_text('utf-8')
    assert paths.root.samefile(root)
    assert DataPaths(paths.root).root == paths.root

@pytest.mark.skipif(os.name != 'nt', reason='Windows snapshot URI behavior')
def test_long_snapshot_uri_keeps_local_root_boundary(tmp_path):
    from pathlib import Path

    from forecast_provider.catalog.files import snapshot_path

    paths = DataPaths(tmp_path / ('配布先' * 30) / 'Data')
    paths.ensure()
    target = paths.state / ('c' * 64 + '.csv')
    target.write_text('sample', encoding='utf-8')
    uri = Path(str(target).removeprefix('\\\\?\\')).as_uri()
    resolved = snapshot_path(uri, paths.root)
    assert resolved.read_text('utf-8') == 'sample'
    with pytest.raises(ValueError):
        snapshot_path(uri, tmp_path / 'different-root')
