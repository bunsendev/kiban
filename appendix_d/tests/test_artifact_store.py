"""ローカルI/Oの不完全公開・破損・参照逸脱・同時書込みの検証。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from forecast_provider.artifacts import (
    ArtifactError,
    ArtifactRef,
    ArtifactStorageError,
    LocalArtifactStore,
)


def test_local_store_is_content_addressed_and_idempotent(tmp_path):
    store = LocalArtifactStore(tmp_path)
    data = b'{"data":1}'
    with ThreadPoolExecutor(max_workers=4) as pool:
        refs = list(pool.map(store.put, [data] * 8))
    assert len(set(refs)) == 1
    assert store.get(refs[0]) == data
    assert [p.name for p in tmp_path.iterdir()] == [refs[0].sha256 + ".json"]


@pytest.mark.parametrize("digest", ["../file", "/absolute", "a" * 63, "A" * 64, None])
def test_reference_rejects_paths_and_invalid_hashes(digest):
    with pytest.raises(ArtifactError):
        ArtifactRef(digest, 1)


@pytest.mark.parametrize("size", [0, -1, True, "1"])
def test_reference_rejects_invalid_sizes(size):
    with pytest.raises(ArtifactError):
        ArtifactRef("a" * 64, size)


def test_corruption_and_truncation_are_rejected_without_overwrite(tmp_path):
    store = LocalArtifactStore(tmp_path)
    ref = store.put(b"12345")
    path = tmp_path / (ref.sha256 + ".json")
    for broken in (b"abcde", b"", b"123", b"123456"):
        path.write_bytes(broken)
        with pytest.raises(ArtifactError):
            store.get(ref)
        with pytest.raises(ArtifactError):
            store.put(b"12345")
        assert path.read_bytes() == broken
    assert not list(tmp_path.glob(".pending-*"))


def test_wrong_size_missing_file_and_limit(tmp_path):
    store = LocalArtifactStore(tmp_path, max_bytes=5)
    ref = store.put(b"12345")
    with pytest.raises(ArtifactError):
        store.get(replace(ref, size_bytes=4))
    with pytest.raises(ArtifactError):
        store.put(b"123456")
    with pytest.raises(ArtifactStorageError):
        store.get(ArtifactRef("a" * 64, 1))


def test_failed_publication_leaves_no_partial_artifact(tmp_path, monkeypatch):
    store = LocalArtifactStore(tmp_path)

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr("forecast_provider.artifacts.local.os.link", fail)
    with pytest.raises(ArtifactStorageError):
        store.put(b"12345")
    assert list(tmp_path.iterdir()) == []


def test_incomplete_temporary_file_is_never_a_published_reference(tmp_path):
    store = LocalArtifactStore(tmp_path)
    (tmp_path / ".pending-interrupted").write_bytes(b"123")
    ref = store.put(b"12345")
    assert store.get(ref) == b"12345"
    assert (tmp_path / ".pending-interrupted").read_bytes() == b"123"
