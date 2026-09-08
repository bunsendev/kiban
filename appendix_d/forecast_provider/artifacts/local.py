"""ローカルの内容アドレス保存。ファイル全体を書いてから排他的に公開する。"""

import os
import tempfile
from pathlib import Path

from .contracts import ArtifactError, ArtifactRef, ArtifactStorageError, reference_for, verify_bytes


class LocalArtifactStore:
    def __init__(self, root: Path, *, max_bytes: int = 256 * 1024 * 1024) -> None:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytesは正整数です")
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ArtifactStorageError("artifact保存先を作成できません") from exc

    def _path(self, ref: ArtifactRef) -> Path:
        path = self.root / f"{ref.sha256}.json"
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ArtifactError("artifact保存先の参照逸脱")
        return path

    def put(self, data: bytes) -> ArtifactRef:
        ref = reference_for(data)
        if ref.size_bytes > self.max_bytes:
            raise ArtifactError("artifactサイズ上限超過")
        path = self._path(ref)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".pending-", delete=False) as f:
                temporary = Path(f.name)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            try:
                # 同一ファイルシステムのhard linkで、既存ファイルを置換せず公開する。
                os.link(temporary, path)
            except FileExistsError:
                self.get(ref)  # 同一内容なら冪等、破損していれば上書きせず拒否。
        except OSError as exc:
            raise ArtifactStorageError("artifactを保存できません") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return ref

    def get(self, ref: ArtifactRef) -> bytes:
        if ref.size_bytes > self.max_bytes:
            raise ArtifactError("artifactサイズ上限超過")
        try:
            with self._path(ref).open("rb") as f:
                data = f.read(min(ref.size_bytes, self.max_bytes) + 1)
        except OSError as exc:
            raise ArtifactStorageError("artifactを読み込めません") from exc
        verify_bytes(ref, data)
        return data
