"""Immutable originals/extractions and human-reviewed document-to-CSV adapter."""

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from portable.runtime.api_credentials import ApiCredentials

from .document_ai import MAX_BYTES, DocumentError, extract, media_type


class Documents:
    def __init__(self, paths):
        self.paths = paths
        self.path = paths.state / "documents.sqlite3"
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS documents "
                "(id TEXT PRIMARY KEY, name TEXT, original BLOB, mime TEXT, "
                "extraction TEXT, approval TEXT, created TEXT)"
            )

    def db(self):
        return sqlite3.connect(self.path, timeout=30)

    def add(self, name, raw):
        if not raw or len(raw) > MAX_BYTES:
            raise DocumentError("1ファイル10 MB以内で選択してください")
        mime, _ = media_type(raw)
        identifier = hashlib.sha256(raw).hexdigest()
        name = str(name).replace("\\", "/").split("/")[-1][:200]
        with self.db() as db:
            db.execute(
                "INSERT OR IGNORE INTO documents VALUES(?,?,?,?,NULL,NULL,?)",
                (identifier, name, raw, mime, datetime.now(UTC).isoformat()),
            )
        return self.get(identifier)

    def get(self, identifier, original=False):
        with self.db() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise DocumentError("原本が見つかりません")
        if original:
            return row[2], row[3]
        return {
            "id": row[0],
            "name": row[1],
            "mime": row[3],
            "extraction": json.loads(row[4]) if row[4] else None,
            "approval": json.loads(row[5]) if row[5] else None,
            "created": row[6],
        }

    def list(self):
        with self.db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM documents ORDER BY created DESC")]
        return [self.get(i) for i in ids]

    def read(self, identifier, consent):
        if consent is not True:
            raise DocumentError("原本全体をOpenAIへ送ることへの同意が必要です")
        current = self.get(identifier)
        if current["extraction"]:
            return current  # No automatic paid retry or overwrite of extraction.
        raw, _ = self.get(identifier, original=True)
        value = extract(raw, ApiCredentials().load())
        value["model"] = "gpt-4.1-mini"
        value["at"] = datetime.now(UTC).isoformat()
        with self.db() as db:
            db.execute(
                "UPDATE documents SET extraction=? WHERE id=? AND extraction IS NULL",
                (json.dumps(value, ensure_ascii=False), identifier),
            )
        return self.get(identifier)

    def approve(self, identifier, value):
        current = self.get(identifier)
        if current["approval"]:
            return current
        extraction = current["extraction"]
        if not extraction or not extraction["complete"]:
            raise DocumentError("原本全体の読取が未完了です。分割して再投入してください")
        actor = str(value.get("actor") or "").strip()
        rows = value.get("rows")
        if (
            value.get("confirmed") is not True
            or not actor
            or len(actor) > 100
            or not isinstance(rows, list)
            or len(rows) != len(extraction["rows"])
        ):
            raise DocumentError("確認者と全行の原本確認を入力してください")
        groups = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise DocumentError("明細の形式が不正です")
            if row.get("exclude") is True:
                if not str(row.get("reason") or "").strip():
                    raise DocumentError(f"{index + 1}行目: 除外理由を入力してください")
                continue
            kind = row.get("kind")
            if kind not in ("shipment", "inventory"):
                raise DocumentError(f"{index + 1}行目: 出荷または在庫を指定してください")
            for key in ("jan", "product_code", "product_name", "location", "unit"):
                if not isinstance(row.get(key), str) or len(row[key]) > 200:
                    raise DocumentError(f"{index + 1}行目: 入力内容を確認してください")
            jan = row["jan"].strip()
            if not re.fullmatch(r"\d{8}|\d{13}", jan, flags=re.ASCII):
                raise DocumentError(f"{index + 1}行目: JANを8桁または13桁で確認してください")
            digits = list(map(int, jan))
            if (sum(digits[-2::-2]) * 3 + sum(digits[-3::-2]) + digits[-1]) % 10:
                raise DocumentError(f"{index + 1}行目: JANのチェック桁を確認してください")
            try:
                quantity = Decimal(str(row.get("quantity", "")))
                factor = Decimal(str(row.get("case_factor", "")))
                if (
                    not quantity.is_finite()
                    or not factor.is_finite()
                    or quantity < 0
                    or factor <= 0
                    or quantity > 10**12
                    or factor > 10**6
                ):
                    raise ValueError()
                quantity = quantity * factor
            except (InvalidOperation, ValueError):
                raise DocumentError(
                    f"{index + 1}行目: 数量と1単位あたりの箱数を確認してください"
                ) from None
            if not row["unit"].strip() or not row["location"].strip():
                raise DocumentError(f"{index + 1}行目: 単位と倉庫を確認してください")
            keys = ("date",) if kind == "shipment" else ("snapshot", "expiry")
            try:
                for key in keys:
                    date.fromisoformat(row.get(key, ""))
            except (ValueError, TypeError):
                raise DocumentError(
                    f"{index + 1}行目: 日付をYYYY-MM-DDで確認してください"
                ) from None
            day = row["date"] if kind == "shipment" else row["snapshot"]
            center = row["location"].strip()
            record = {
                "商品名": row["product_name"],
                "倉庫": center,
                "基準日": day,
                "原本単位": row["unit"],
                "正規化単位": "CASE",
            }
            if kind == "shipment":
                record.update({"出荷日": day, "JAN": jan, "数量": str(quantity)})
            else:
                record.update(
                    {
                        "商品コード": row["product_code"].strip() or jan,
                        "JAN": jan,
                        "明細バラ数": str(quantity),
                        "賞味期限": row["expiry"],
                    }
                )
            groups.setdefault((kind, center, day), []).append(record)
        approval = {
            "actor": actor,
            "at": datetime.now(UTC).isoformat(),
            "rows": rows,
            "source_sha": identifier,
            "files": [],
        }
        # Persist decision + outgoing contents together. Explicit dispatch is retryable and
        # keeps the original and AI result immutable even if CSV processing later fails.
        for records in groups.values():
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=list(records[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
            approval["files"].append(
                {"name": f"document-{uuid.uuid4().hex}.csv", "csv": output.getvalue()}
            )
        with self.db() as db:
            db.execute(
                "UPDATE documents SET approval=? WHERE id=? AND approval IS NULL",
                (json.dumps(approval, ensure_ascii=False), identifier),
            )
        return self.get(identifier)

    def dispatch(self, identifier):
        current = self.get(identifier)
        approval = current["approval"]
        if not approval:
            raise DocumentError("先に原本を確認して承認してください")
        # Transaction serializes concurrent dispatch; already handed-off originals cannot
        # be re-published after the folder scanner moves their CSV files.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT approval FROM documents WHERE id=?", (identifier,)).fetchone()
            approval = json.loads(row[0])
            if not approval.get("dispatched"):
                for item in approval["files"]:
                    target = self.paths.incoming / item["name"]
                    if not target.exists():
                        staging = target.with_suffix('.part')
                        with staging.open("wb") as stream:
                            stream.write(item["csv"].encode("utf-8-sig"))
                        os.replace(staging, target)
                approval["dispatched"] = datetime.now(UTC).isoformat()
                db.execute(
                    "UPDATE documents SET approval=? WHERE id=?",
                    (json.dumps(approval, ensure_ascii=False), identifier),
                )
        return self.get(identifier)
