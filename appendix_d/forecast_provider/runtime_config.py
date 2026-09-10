"""process共通のsecret file読込み。"""

from pathlib import Path


def read_secret_file(path: Path, label: str, max_bytes: int = 65_536) -> str:
    try:
        if not path.is_file() or not 0 < path.stat().st_size <= max_bytes:
            raise ValueError(f"{label}のサイズが不正です")
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label}を読込めません") from exc
