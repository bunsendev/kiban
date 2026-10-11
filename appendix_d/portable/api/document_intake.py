"""Immutable originals/extractions and human-reviewed document-to-CSV adapter."""

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime

from portable.runtime.api_credentials import ApiCredentials

from .document_ai import MAX_BYTES, DocumentError, extract, media_type
from .document_inventory_pdf import extract_inventory
from .document_pages import page_source, pdf_reader
from .document_quantity import case_quantity


class Documents:
    def __init__(self, paths):
        self.paths = paths
        self._read_lock = threading.Lock()
        self.path = paths.state / "documents.sqlite3"
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS documents "
                "(id TEXT PRIMARY KEY, name TEXT, original BLOB, mime TEXT, "
                "extraction TEXT, approval TEXT, created TEXT)"
            )

            db.execute(
                "CREATE TABLE IF NOT EXISTS document_attempts "
                "(document_id TEXT, revision TEXT PRIMARY KEY, result TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS document_pages "
                "(document_id TEXT, page INTEGER, result TEXT, PRIMARY KEY(document_id,page))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS document_masters "
                "(version TEXT PRIMARY KEY, contents TEXT)"
            )

            db.execute(
                "CREATE TABLE IF NOT EXISTS document_controls "
                "(document_id TEXT PRIMARY KEY, generation INTEGER, cancelled INTEGER)"
            )

    def save_draft(self, identifier, value):
        if not isinstance(value.get("rows"), list) or len(value["rows"]) > 1000:
            raise DocumentError("明細は1000行以内で保存してください")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT extraction,approval FROM documents WHERE id=?", (identifier,)
            ).fetchone()
            if not row or not row[0] or row[1]:
                raise DocumentError("未承認の読取結果だけ途中保存できます")
            extraction = json.loads(row[0])
            if value.get("revision") != extraction.get("revision"):
                raise DocumentError("読取結果が更新されています。再表示してください")
            if not all(isinstance(r, dict) for r in value["rows"]):
                raise DocumentError("明細の形式を確認してください")
            self.check_control(db, identifier, self.control(identifier)[0])
            draft = {
                "rows": value["rows"],
                "revision": value["revision"],
                "actor": str(value.get("actor") or "")[:100],
                "at": datetime.now(UTC).isoformat(),
            }
            db.execute(
                "CREATE TABLE IF NOT EXISTS document_drafts (document_id TEXT, contents TEXT)"
            )
            db.execute(
                "INSERT INTO document_drafts VALUES(?,?)",
                (identifier, json.dumps(draft, ensure_ascii=False)),
            )
        return draft

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

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
        try:
            count = len(pdf_reader(row[2]).pages) if row[3] == "application/pdf" else 1
        except DocumentError:
            count = 1
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS document_drafts (document_id TEXT, contents TEXT)"
            )
            saved = db.execute(
                "SELECT contents FROM document_drafts WHERE document_id=? "
                "ORDER BY rowid DESC LIMIT 1",
                (identifier,),
            ).fetchone()
        extraction = json.loads(row[4]) if row[4] else None
        draft = json.loads(saved[0]) if saved else None
        if draft and (not extraction or draft["revision"] != extraction.get("revision")):
            draft = None
        return {
            "draft": draft,
            "page_count": count,
            "id": row[0],
            "name": row[1],
            "mime": row[3],
            "extraction": json.loads(row[4]) if row[4] else None,
            "approval": json.loads(row[5]) if row[5] else None,
            "created": row[6],
            "cancelled": self.control(identifier)[1],
        }

    def list(self):
        with self.db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM documents ORDER BY created DESC")]
        return [self.get(i) for i in ids]

    def control(self, identifier):
        with self.db() as db:
            value = db.execute(
                "SELECT generation,cancelled FROM document_controls WHERE document_id=?",
                (identifier,),
            ).fetchone()
        return (value[0], bool(value[1])) if value else (0, False)

    def check_control(self, db, identifier, generation):
        value = db.execute(
            "SELECT generation,cancelled FROM document_controls WHERE document_id=?",
            (identifier,),
        ).fetchone()
        if value and (value[0] != generation or value[1]):
            raise DocumentError("読み取りを取りやめました。送信済みのAPI処理・料金は取り消せません")

    def set_cancelled(self, identifier, cancelled=True):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT approval FROM documents WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise DocumentError("原本が見つかりません")
            if row[0]:
                raise DocumentError("確認済みデータは取りやめできません。判断履歴は変更しません")
            db.execute(
                "INSERT INTO document_controls VALUES(?,1,?) "
                "ON CONFLICT(document_id) DO UPDATE SET generation=generation+1,cancelled=?",
                (identifier, int(cancelled), int(cancelled)),
            )
            db.execute(
                "INSERT INTO document_attempts VALUES(?,?,?)",
                (
                    identifier,
                    uuid.uuid4().hex,
                    json.dumps(
                        {
                            "status": "cancelled" if cancelled else "resumed",
                            "at": datetime.now(UTC).isoformat(),
                        }
                    ),
                ),
            )
        return self.get(identifier)

    def read(self, identifier, consent, retry=False, page=None):
        if consent is not True:
            raise DocumentError("原本全体をOpenAIへ送ることへの同意が必要です")
        generation = self.control(identifier)[0]
        with self._read_lock:
            with self.db() as db:
                self.check_control(db, identifier, generation)
            current = self.get(identifier)
            if current["approval"]:
                raise DocumentError("確認済みの原本は再読取できません。判断履歴は変更しません")
            raw, mime = self.get(identifier, original=True)
            embedded = ""
            if page is not None:
                if mime == "application/pdf":
                    raw, embedded, count = page_source(raw, page)
                elif type(page) is int and page == 1:
                    count = 1
                else:
                    raise DocumentError("ページ番号を確認してください")
                with self.db() as db:
                    previous = current["extraction"]
                    if previous:
                        for p in range(1, count + 1):
                            prior_rows = [r for r in previous["rows"] if r.get("page") == str(p)]
                            if prior_rows or previous["complete"]:
                                db.execute(
                                    "INSERT OR IGNORE INTO document_pages VALUES(?,?,?)",
                                    (
                                        identifier,
                                        p,
                                        json.dumps(
                                            {"rows": prior_rows, "complete": previous["complete"]},
                                            ensure_ascii=False,
                                        ),
                                    ),
                                )
                    cached = db.execute(
                        "SELECT result FROM document_pages WHERE document_id=? AND page=?",
                        (identifier, page),
                    ).fetchone()
                if cached and not retry:
                    return current
            elif current["extraction"] and not retry:
                return current
            revision = uuid.uuid4().hex
            try:
                # A recognised text-layer report is more reliable than visual OCR:
                # its JAN may be clipped on screen but intact in the source text.
                if mime == "application/pdf" and "在庫集計日" in embedded and "現在" in embedded:
                    value = extract_inventory(raw)
                else:
                    key = ApiCredentials().load()
                    value = (
                        extract(raw, key, embedded_text=embedded) if embedded else extract(raw, key)
                    )
            except DocumentError as exc:
                with self.db() as db:
                    db.execute(
                        "INSERT INTO document_attempts VALUES(?,?,?)",
                        (
                            identifier,
                            revision,
                            json.dumps(
                                {
                                    "status": "failed",
                                    "page": page,
                                    "at": datetime.now(UTC).isoformat(),
                                    "error": str(exc),
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    )
                raise
            model = value.get("model", "gpt-4.1-mini")
            if page is not None:
                for item in value["rows"]:
                    item["page"] = str(page)
                with self.db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    self.check_control(db, identifier, generation)
                    page_result = json.dumps(value, ensure_ascii=False)
                    pages = {
                        p: json.loads(r)
                        for p, r in db.execute(
                            "SELECT page,result FROM document_pages "
                            "WHERE document_id=? ORDER BY page",
                            (identifier,),
                        )
                    }
                    pages[page] = value
                    if sum(len(v["rows"]) for v in pages.values()) > 1000:
                        raise DocumentError("明細が1000行を超えました。文書を分割してください")
                value = {
                    "rows": [r for v in pages.values() for r in v["rows"]],
                    "complete": len(pages) == count and all(v["complete"] for v in pages.values()),
                    "pages_read": sorted(pages),
                    "page_count": count,
                }
            if len(value["rows"]) > 1000:
                raise DocumentError("明細が1000行を超えました。文書を分割してください")
            value.update(model=model, at=datetime.now(UTC).isoformat(), revision=revision)
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                self.check_control(db, identifier, generation)
                stored = db.execute(
                    "SELECT approval,extraction FROM documents WHERE id=?", (identifier,)
                ).fetchone()
                if (
                    stored[0]
                    or (json.loads(stored[1]) if stored[1] else None) != current["extraction"]
                ):
                    raise DocumentError(
                        "別の画面で更新されています。再読取結果は採用せず画面を更新してください"
                    )
                if page is not None:
                    db.execute(
                        "INSERT OR REPLACE INTO document_pages VALUES(?,?,?)",
                        (identifier, page, page_result),
                    )
                previous = current["extraction"]
                if previous:
                    db.execute(
                        "INSERT OR IGNORE INTO document_attempts VALUES(?,?,?)",
                        (
                            identifier,
                            previous.get("revision", "legacy-" + identifier),
                            json.dumps(previous, ensure_ascii=False),
                        ),
                    )
                db.execute(
                    "INSERT INTO document_attempts VALUES(?,?,?)",
                    (identifier, revision, json.dumps(value, ensure_ascii=False)),
                )
                db.execute(
                    "UPDATE documents SET extraction=? WHERE id=? AND approval IS NULL",
                    (json.dumps(value, ensure_ascii=False), identifier),
                )
            return self.get(identifier)

    def read_local(self, identifier, retry=False, blank_current_zero=False):
        generation = self.control(identifier)[0]
        with self._read_lock:
            with self.db() as db:
                self.check_control(db, identifier, generation)
            current = self.get(identifier)
            if current["approval"]:
                raise DocumentError("確認済みの原本は変更できません")
            if current["extraction"] and not retry:
                raise DocumentError("既に読取済みです。指定ページの再読取を使用してください")
            raw, mime = self.get(identifier, original=True)
            if mime != "application/pdf":
                raise DocumentError("印刷在庫表PDFを選んでください")
            value = (
                extract_inventory(raw, blank_current_zero=True)
                if blank_current_zero
                else extract_inventory(raw)
            )
            value.update(at=datetime.now(UTC).isoformat(), revision=uuid.uuid4().hex)
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                self.check_control(db, identifier, generation)
                stored = db.execute(
                    "SELECT approval,extraction FROM documents WHERE id=?", (identifier,)
                ).fetchone()
                if (
                    stored[0]
                    or (json.loads(stored[1]) if stored[1] else None) != current["extraction"]
                ):
                    raise DocumentError("別の画面で更新されています。画面を更新してください")
                previous = current["extraction"]
                if previous:
                    db.execute(
                        "INSERT OR IGNORE INTO document_attempts VALUES(?,?,?)",
                        (
                            identifier,
                            previous.get("revision", "legacy-" + identifier),
                            json.dumps(previous, ensure_ascii=False),
                        ),
                    )
                    db.execute("DELETE FROM document_pages WHERE document_id=?", (identifier,))
                for p in value["pages_read"]:
                    rows = [r for r in value["rows"] if r["page"] == str(p)]
                    db.execute(
                        "INSERT INTO document_pages VALUES(?,?,?)",
                        (
                            identifier,
                            p,
                            json.dumps(
                                {"rows": rows, "complete": value["complete"]}, ensure_ascii=False
                            ),
                        ),
                    )
                db.execute(
                    "INSERT INTO document_attempts VALUES(?,?,?)",
                    (identifier, value["revision"], json.dumps(value, ensure_ascii=False)),
                )
                db.execute(
                    "UPDATE documents SET extraction=? WHERE id=? AND approval IS NULL",
                    (json.dumps(value, ensure_ascii=False), identifier),
                )
            return self.get(identifier)

    def history(self, identifier):
        self.get(identifier)
        with self.db() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT result FROM document_attempts WHERE document_id=? ORDER BY rowid",
                    (identifier,),
                )
            ]

    def approve(self, identifier, value):
        with self._read_lock:
            return self._approve(identifier, value)

    def _approve(self, identifier, value):
        current = self.get(identifier)
        if current["approval"]:
            return current
        if current["cancelled"]:
            raise DocumentError("取りやめ済みです。再開してから確認してください")
        generation = self.control(identifier)[0]
        extraction = current["extraction"]
        if not extraction:
            raise DocumentError("先に原本を読み取ってください")
        if not extraction["complete"] and (
            value.get("partial_confirmed") is not True
            or not str(value.get("partial_reason") or "").strip()
        ):
            raise DocumentError(
                "未読取部分の扱いと、確認できた行だけ採用する理由を入力してください"
            )
        if value.get("revision") != extraction.get("revision"):
            # Legacy callers may omit the revision only before any explicit retry/page workflow.
            with self.db() as db:
                attempts = db.execute(
                    "SELECT COUNT(*) FROM document_attempts WHERE document_id=?", (identifier,)
                ).fetchone()[0]
            if value.get("revision") or attempts > 1 or extraction.get("pages_read"):
                raise DocumentError(
                    "読み取り結果が更新されています。画面を更新して確認し直してください"
                )
        actor = str(value.get("actor") or "").strip()
        rows = value.get("rows")
        if (
            value.get("confirmed") is not True
            or not actor
            or len(actor) > 100
            or not isinstance(rows, list)
            or not len(extraction["rows"]) <= len(rows) <= 1000
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
                quantity = case_quantity(row)
            except DocumentError as exc:
                raise DocumentError(f"{index + 1}行目: {exc}") from None
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
                        "ムロオ倉庫入庫日": str(row.get("source_detail_date") or ""),
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
            "extraction_revision": extraction.get("revision"),
            "partial_confirmed": value.get("partial_confirmed") is True,
            "partial_reason": str(value.get("partial_reason") or ""),
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
            db.execute("BEGIN IMMEDIATE")
            self.check_control(db, identifier, generation)
            stored = db.execute(
                "SELECT extraction,approval FROM documents WHERE id=?", (identifier,)
            ).fetchone()
            if stored[1]:
                return self.get(identifier)
            if json.loads(stored[0]) != extraction:
                raise DocumentError("読み取り結果が更新されています。確認し直してください")
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
                    expected = item["csv"].encode("utf-8-sig")
                    if target.exists():
                        if target.is_symlink() or target.read_bytes() != expected:
                            raise DocumentError(
                                "受渡し先CSVが変更されています。IT担当者に確認してください"
                            )
                    else:
                        staging = target.with_suffix(".part")
                        with staging.open("wb") as stream:
                            stream.write(expected)
                        os.replace(staging, target)
                approval["dispatched"] = datetime.now(UTC).isoformat()
                db.execute(
                    "UPDATE documents SET approval=? WHERE id=?",
                    (json.dumps(approval, ensure_ascii=False), identifier),
                )
        return self.get(identifier)
