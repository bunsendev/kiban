"""Immutable local installation identity; never distributed with application files."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

MODES = {"FIELD": "現場利用", "IT_TEST": "IT動作確認（テスト）"}


def load_profile(data_root: Path) -> dict | None:
    path = data_root / "State" / "installation.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("mode") not in MODES or not value.get("terminal_name"):
        raise ValueError("端末設定が不正です。管理担当者へ確認してください")
    uuid.UUID(value["installation_id"])
    return value


def create_profile(data_root: Path, mode: str, terminal_name: str) -> dict:
    name = terminal_name.strip()
    if mode not in MODES or not name or len(name) > 80:
        raise ValueError("用途と80文字以内の端末名を入力してください")
    value = {"installation_id": str(uuid.uuid4()), "mode": mode,
             "terminal_name": name, "created_at": datetime.now(UTC).isoformat()}
    path = data_root / "State" / "installation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    return value


def setup_profile(data_root: Path) -> dict | None:
    import tkinter as tk
    from tkinter import messagebox

    existing = load_profile(data_root)
    if existing:
        return existing
    window = tk.Tk()
    window.title("ブンセン予測 初回設定")
    window.geometry("480x280")
    mode = tk.StringVar(value="IT_TEST")
    name = tk.StringVar()
    result = []
    tk.Label(window, text="このPCの用途を選択してください").pack(pady=12)
    for key, label in MODES.items():
        tk.Radiobutton(window, text=label, variable=mode, value=key).pack()
    tk.Label(window, text="端末名（例：神戸現場01 / IT確認01）").pack(pady=8)
    tk.Entry(window, textvariable=name, width=40).pack()
    tk.Label(window, text="このPCだけに保存します。用途は後から変更できません。").pack(pady=8)

    def save():
        try:
            result.append(create_profile(data_root, mode.get(), name.get()))
        except (ValueError, OSError) as exc:
            messagebox.showerror("初回設定", str(exc), parent=window)
            return
        window.destroy()

    tk.Button(window, text="保存して起動", command=save).pack()
    window.mainloop()
    return result[0] if result else None

