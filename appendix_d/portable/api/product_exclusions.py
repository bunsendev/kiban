"""Persistent, reversible JAN exclusions. Originals and approvals remain immutable."""

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime

from .document_ai import DocumentError
from .document_evidence import valid_jan


class ProductExclusions:
    def __init__(self, paths):
        self.path = paths.state / "product-exclusions.sqlite3"
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS events "
                "(jan TEXT, name TEXT, active INTEGER, reason TEXT, actor TEXT, at TEXT)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS imports (sha TEXT PRIMARY KEY)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS prefix_events "
                "(prefix TEXT, active INTEGER, reason TEXT, actor TEXT, at TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS previews "
                "(sha TEXT PRIMARY KEY, name TEXT, original BLOB, result TEXT)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS event_sources (event_rowid INTEGER, sha TEXT)")
        seed = paths.root.parent / "対象外商品設定.json"
        if seed.is_file():
            self.import_file(seed.read_bytes())

    def list(self):
        with sqlite3.connect(self.path) as db:
            exact = [
                dict(
                    zip(["jan", "product_name", "exclude", "reason", "actor", "at"], r, strict=True)
                )
                for r in db.execute(
                    "SELECT jan,name,active,reason,actor,at FROM events "
                    "WHERE rowid IN (SELECT MAX(rowid) FROM events GROUP BY jan) ORDER BY jan"
                )
            ]
            prefixes = [
                {"jan": r[0], "product_name": "JAN先頭7桁の条件", "exclude": r[1],
                 "reason": r[2], "actor": r[3], "at": r[4], "match_type": "prefix"}
                for r in db.execute(
                    "SELECT prefix,active,reason,actor,at FROM prefix_events "
                    "WHERE rowid IN (SELECT MAX(rowid) FROM prefix_events GROUP BY prefix) "
                    "ORDER BY prefix"
                )
            ]
            return prefixes + exact

    def save(self, value):
        rows = value.get("products")
        actor = str(value.get("actor") or "").strip()
        if not actor or len(actor) > 100 or not isinstance(rows, list) or len(rows) > 1000:
            raise DocumentError("対象外商品の確認者と1000件以内の設定を確認してください")
        validated = []
        prefix_records = []
        for row in rows:
            if not isinstance(row, dict):
                raise DocumentError("対象外設定の各行を確認してください")
            jan = str(row.get("jan") or "")
            reason = str(row.get("reason") or "").strip()
            match_type = row.get("match_type", "exact")
            if match_type not in ("exact", "prefix"):
                raise DocumentError("個別JANまたは先頭7桁の条件を確認してください")
            if not reason or len(reason) > 500:
                raise DocumentError("13桁JANと対象外・解除の理由を確認してください")
            if match_type == "prefix" and not re.fullmatch(r"[0-9]{7}", jan):
                raise DocumentError("JAN先頭7桁は半角数字7文字で指定してください")
            if match_type == "exact" and (len(jan) != 13 or not valid_jan(jan)):
                raise DocumentError("JANのチェック桁が不正です")
            if type(row.get("exclude")) is not bool:
                raise DocumentError("対象外の指定を確認してください")
            if match_type == "prefix":
                prefix_records.append((jan, int(row["exclude"]), reason, actor,
                                       datetime.now(UTC).isoformat()))
                continue
            validated.append(
                (
                    jan,
                    str(row.get("product_name") or "")[:200],
                    int(row["exclude"]),
                    reason,
                    actor,
                    datetime.now(UTC).isoformat(),
                )
            )
        with sqlite3.connect(self.path) as db:
            source = value.get("source_sha256")
            if source and value.get("confirmed") is not True:
                raise DocumentError("原本との照合確認が必要です")
            if (
                source
                and not db.execute("SELECT 1 FROM previews WHERE sha=?", (source,)).fetchone()
            ):
                raise DocumentError("読取元を確認できません。ファイルを読み取り直してください")
            if source:
                preview = json.loads(
                    db.execute("SELECT result FROM previews WHERE sha=?", (source,)).fetchone()[0]
                )
                if not preview["complete"] and value.get("allow_partial") is not True:
                    raise DocumentError(
                        "未取得明細があります。確認済み商品の部分登録を確認してください"
                    )
            for record in validated:
                cursor = db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", record)
                if source:
                    db.execute("INSERT INTO event_sources VALUES(?,?)", (cursor.lastrowid, source))
            db.executemany("INSERT INTO prefix_events VALUES(?,?,?,?,?)", prefix_records)
        return self.list()

    def record_preview(self, raw, result):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR IGNORE INTO previews VALUES(?,?,?,?)",
                (
                    result["source_sha256"],
                    result["source_name"],
                    raw,
                    json.dumps(result, ensure_ascii=False),
                ),
            )

    def import_file(self, raw):
        digest = hashlib.sha256(raw).hexdigest()
        with sqlite3.connect(self.path) as db:
            if db.execute("SELECT 1 FROM imports WHERE sha=?", (digest,)).fetchone():
                return self.list()
        try:
            value = json.loads(raw)
            if value.get("format") not in (
                "bunsen-product-exclusions-v1", "bunsen-product-exclusions-v2"
            ):
                raise ValueError()
            rows = value["products"]
            if not isinstance(rows, list):
                raise ValueError()
            if value.get("prefixes") and value["format"] != "bunsen-product-exclusions-v2":
                raise ValueError()
            prefixes = value.get("prefixes", [])
            if not isinstance(prefixes, list):
                raise ValueError()
            rows = rows + [
                {**r, "jan": r["prefix"], "match_type": "prefix"} for r in prefixes
            ]
            result = self.save({"actor": "担当者指定の設定ファイル", "products": rows})
            with sqlite3.connect(self.path) as db:
                db.execute("INSERT OR IGNORE INTO imports VALUES(?)", (digest,))
            return result
        except (ValueError, KeyError, TypeError, AttributeError):
            raise DocumentError("対象外商品設定JSONの形式を確認してください") from None

    def apply(self, rows, *, rules=None):
        rules = self.list() if rules is None else rules
        active = {r["jan"]: r for r in rules if r["exclude"] and r.get("match_type") != "prefix"}
        prefixes = {r["jan"]: r for r in rules if r["exclude"] and r.get("match_type") == "prefix"}
        result = []
        for source in rows:
            row = dict(source)
            rule = active.get(row.get("jan"))
            jan = str(row.get("jan") or "")
            if len(jan) == 13 and valid_jan(jan) and jan[:7] in prefixes:
                rule = prefixes[jan[:7]]
            if row.get("registered_exclusion") and not rule:
                before = json.loads(row.get("exclusion_before") or "{}")
                row.update(
                    exclude=before.get("exclude", False),
                    reason=before.get("reason", ""),
                    registered_exclusion="",
                    exclusion_before="",
                )
            if rule:
                if not row.get("registered_exclusion"):
                    row["exclusion_before"] = json.dumps(
                        {"exclude": bool(row.get("exclude")), "reason": row.get("reason", "")}
                    )
                row.update(exclude=True, reason=rule["reason"], registered_exclusion=True)
            result.append(row)
        return result
