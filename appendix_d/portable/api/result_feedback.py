"""Append-only operator observations; never mutate model predictions."""

import csv
import io
import json
import math
import sqlite3
from datetime import UTC, datetime

from portable import APP_VERSION

from .forecast_verification import ForecastVerification


class FeedbackConflict(ValueError):
    pass


class ResultFeedback:
    def __init__(self, database):
        self.database = database
        self.verification = ForecastVerification(database.parent / "forecast-verification.sqlite3")
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS result_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                item TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS feedback_source ON result_feedback(source)")

    def connect(self):
        return sqlite3.connect(self.database, timeout=20)

    def history(self, source):
        with self.connect() as db:
            return [
                json.loads(row[1]) | {"revision": row[0]}
                for row in db.execute(
                    "SELECT id,payload FROM result_feedback WHERE source=? ORDER BY id", (source,)
                )
            ]

    def view(self, source, predictions):
        history = self.history(source)
        latest = {(v["unique_id"], v["target_date"]): v for v in history}
        states = {
            (r["unique_id"], str(r["target_date"])[:10]): r["edit_state"]
            for r in self.verification.compare(source)["rows"]
        }
        return {
            "rows": [
                dict(p)
                | {
                    "feedback": latest.get((p["unique_id"], p["target_date"])),
                    "edit_state": states.get((p["unique_id"], str(p["target_date"])[:10]))
                    or self.verification.edit_state(str(p["target_date"])[:10]),
                }
                for p in predictions
            ],
            "history": history,
        }

    def row_state(self, source, p):
        comparison = self.verification.compare(source)
        match = next(
            (
                r
                for r in comparison["rows"]
                if r["unique_id"] == p["unique_id"]
                and str(r["target_date"])[:10] == str(p["target_date"])[:10]
            ),
            None,
        )
        return (
            match["edit_state"]
            if match
            else self.verification.edit_state(str(p["target_date"])[:10])
        )

    def save(self, source, predictions, payload, profile, *, exceptional=False):
        if not isinstance(payload, dict):
            raise ValueError("入力内容を確認してください")
        key = (payload.get("unique_id"), payload.get("target_date"))
        original = next((p for p in predictions if (p["unique_id"], p["target_date"]) == key), None)
        if original is None:
            raise ValueError("対象の予測結果がありません")
        quantity = payload.get("quantity")
        if quantity is not None and (
            type(quantity) not in (int, float) or not math.isfinite(quantity) or quantity < 0
        ):
            raise ValueError("修正数量は0以上の有限数で入力してください")
        fields = {}
        for name, limit in (("actor", 100), ("reason", 500), ("comment", 1000)):
            value = payload.get(name, "")
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError("入力文字数を確認してください")
            fields[name] = value.strip()
        if not fields["actor"] or (quantity is not None and not fields["reason"]):
            raise ValueError("担当者と、数量修正の場合は理由を入力してください")
        rating = payload.get("rating")
        if rating not in ("OK", "HIGH", "LOW", "UNKNOWN"):
            raise ValueError("結果への評価を選択してください")
        revision = payload.get("revision", 0)
        if type(revision) is not int or revision < 0:
            raise ValueError("履歴番号を確認してください")
        item = json.dumps(key, ensure_ascii=False)
        entry = fields | {
            "unique_id": key[0],
            "target_date": key[1],
            "original_quantity": original["yhat"],
            "quantity": quantity,
            "rating": rating,
            "app_version": APP_VERSION,
            "installation": profile,
            "created_at": datetime.now(UTC).isoformat(),
        }
        with self.verification.connect() as guard, self.connect() as db:
            guard.execute("BEGIN IMMEDIATE")
            db.execute("BEGIN IMMEDIATE")
            latest = (
                db.execute(
                    "SELECT MAX(id) FROM result_feedback WHERE source=? AND item=?", (source, item)
                ).fetchone()[0]
                or 0
            )
            previous_row = db.execute(
                "SELECT payload FROM result_feedback WHERE id=?", (latest,)
            ).fetchone()
            previous = json.loads(previous_row[0]) if previous_row else {}
            state = self.row_state(source, original)
            if quantity != previous.get("quantity") and not state["editable"] and not exceptional:
                raise ValueError(state["reason"])
            if exceptional and not fields["reason"]:
                raise ValueError("例外修正には理由が必要です")
            entry.update(
                exceptional=exceptional, before_quantity=previous.get("quantity"), edit_policy=state
            )
            if latest != revision:
                raise FeedbackConflict("別の操作で更新されました。結果を再表示して確認してください")
            cursor = db.execute(
                "INSERT INTO result_feedback(source,item,payload) VALUES(?,?,?)",
                (source, item, json.dumps(entry, ensure_ascii=False)),
            )
            return entry | {"revision": cursor.lastrowid}


def export_results(view, selected=None):
    rows = view["rows"]
    if selected is not None:
        if (
            not isinstance(selected, list)
            or not selected
            or not all(isinstance(v, str) for v in selected)
        ):
            raise ValueError("ダウンロードする商品・倉庫を選択してください")
        if set(selected) - {r["unique_id"] for r in rows}:
            raise ValueError("選択した商品・倉庫が結果にありません")
        rows = [r for r in rows if r["unique_id"] in selected]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "商品・倉庫ID",
            "予測日",
            "元の予測数量",
            "担当者修正数量",
            "確認後数量",
            "評価",
            "理由",
            "コメント",
            "担当者",
            "保存日時",
            "予測区分",
            "品質検証ID",
        ]
    )

    def safe(value):
        text = str(value)
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

    for row in rows:
        feedback = row.get("feedback") or {}
        changed = feedback.get("quantity")
        writer.writerow(
            [
                safe(row["unique_id"]),
                row["target_date"],
                row["yhat"],
                "" if changed is None else changed,
                "" if changed is None else changed,
                *[
                    safe(feedback.get(k, ""))
                    for k in ("rating", "reason", "comment", "actor", "created_at")
                ],
                "暫定予測" if view.get("provisional") else "通常予測",
                view.get("quality_check_id", ""),
            ]
        )
    return output.getvalue().encode("utf-8-sig")
