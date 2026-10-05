"""Durable UI jobs and append-only period observations, separate from forecasts."""

import json
import math
import sqlite3
from datetime import UTC, datetime

from .result_feedback import FeedbackConflict


def now():
    return datetime.now(UTC).isoformat()


class FieldStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observations(
                    id INTEGER PRIMARY KEY, result TEXT NOT NULL, item TEXT NOT NULL,
                    payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS observation_result ON observations(result,item);
                CREATE TABLE IF NOT EXISTS help_feedback(
                    id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            """)
            for key, raw in db.execute("SELECT id,payload FROM jobs").fetchall():
                value = json.loads(raw)
                if value["status"] == "RUNNING":
                    value.update(
                        status="INTERRUPTED",
                        message="処理が中断されました。保存済みデータを確認して再開してください。",
                    )
                    db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(value), key))

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def put_job(self, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?)", (value["id"], json.dumps(value)))
        return value

    def jobs(self):
        with self.connect() as db:
            return sorted(
                (json.loads(r[0]) for r in db.execute("SELECT payload FROM jobs")),
                key=lambda v: v["created_at"],
                reverse=True,
            )

    def history(self, result):
        with self.connect() as db:
            return [
                json.loads(raw) | {"revision": key}
                for key, raw in db.execute(
                    "SELECT id,payload FROM observations WHERE result=? ORDER BY id", (result,)
                )
            ]

    def save(self, result, row, payload):
        if not isinstance(payload, dict):
            raise ValueError("判断内容を確認してください")
        fields = {}
        for key, limit in (("actor", 100), ("reason", 500), ("comment", 1000)):
            value = payload.get(key, "")
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError("入力文字数を確認してください")
            fields[key] = value.strip()
        choice = payload.get("choice")
        quantity = payload.get("quantity")
        revision = payload.get("revision", 0)
        if type(revision) is not int or revision < 0:
            raise ValueError("保存版を確認してください")
        if choice not in {"ACCEPT", "CHANGE", "HOLD"} or not fields["actor"]:
            raise ValueError("担当者と判断を入力してください")
        if row["forecast"] is None and choice != "HOLD":
            raise ValueError("予測できない商品は理由を付けて保留してください")
        if choice == "CHANGE":
            if type(quantity) not in (int, float) or not math.isfinite(quantity) or quantity < 0:
                raise ValueError("修正数量は0以上の有限数で入力してください")
        elif quantity is not None:
            raise ValueError("数量変更以外では修正数量を指定できません")
        if choice in {"CHANGE", "HOLD"} and not fields["reason"]:
            raise ValueError("数量変更・保留の理由を入力してください")
        entry = fields | {
            "item": row["item"],
            "choice": choice,
            "quantity": quantity,
            "original_quantity": row["forecast"],
            "period": row["period"],
            "unit": row["unit"],
            "created_at": now(),
        }
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = (
                db.execute(
                    "SELECT MAX(id) FROM observations WHERE result=? AND item=?",
                    (result, row["item"]),
                ).fetchone()[0]
                or 0
            )
            if latest != revision:
                raise FeedbackConflict(
                    "別の操作で保存されました。最新の判断を確認してください。入力は残しています。"
                )
            cursor = db.execute(
                "INSERT INTO observations(result,item,payload) VALUES(?,?,?)",
                (result, row["item"], json.dumps(entry, ensure_ascii=False)),
            )
            return entry | {"revision": cursor.lastrowid}

    def feedback(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("内容を確認してください")
        text = payload.get("comment", "")
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError("困ったことを2000文字以内で入力してください")
        step = payload.get("step")
        if type(step) is not int or step not in range(1, 5):
            raise ValueError("工程を確認してください")
        ref = payload.get("analysis_id")
        if ref is not None and (
            not isinstance(ref, str)
            or len(ref) != 64
            or any(c not in "0123456789abcdef" for c in ref)
        ):
            raise ValueError("分析を確認してください")
        entry = {"comment": text.strip(), "step": step, "analysis_id": ref, "created_at": now()}
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO help_feedback(payload) VALUES(?)", (json.dumps(entry),)
            )
            return {"id": cursor.lastrowid, "created_at": entry["created_at"]}
