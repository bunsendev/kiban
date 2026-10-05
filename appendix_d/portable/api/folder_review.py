"""Local, append-only CSV mapping approvals; cloud suggestions never approve input."""

import csv
import hashlib
import io
import json
import sqlite3
from datetime import UTC, date, datetime

from forecast_provider.field_pilot.ai_cloud import suggest_cloud_structure

from .business_archive import MAX_ZIP_BYTES, ArchiveError, _decode

FIELDS = {
    "shipment": ("出荷日", "JAN", "数量", "商品名", "倉庫", "基準日"),
    "inventory": ("商品コード", "明細バラ数", "賞味期限", "商品名", "倉庫", "基準日"),
}
REQUIRED = {"shipment": ("出荷日", "JAN", "数量"),
            "inventory": ("商品コード", "明細バラ数", "賞味期限")}


def describe(raw):
    headers = csv.DictReader(io.StringIO(_decode(raw))).fieldnames or []
    if (not headers or len(headers) > 256 or len(set(headers)) != len(headers)
            or any(not h or len(h) > 120 for h in headers)):
        raise ArchiveError("CSVの列名が空・重複・長すぎるため確認が必要です")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "headers": headers,
            "schema": hashlib.sha256(json.dumps(headers).encode()).hexdigest()}


class FolderReview:
    def __init__(self, paths):
        self.paths = paths
        paths.state.mkdir(parents=True, exist_ok=True)
        self.db_path = paths.state / "folder-review.sqlite3"
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS approvals ("
                       "id INTEGER PRIMARY KEY, source_sha TEXT, schema_sha TEXT, "
                       "remember INTEGER, payload TEXT)")

    def db(self):
        return sqlite3.connect(self.db_path)

    def source(self, filename, expected=None):
        if (not isinstance(filename, str) or not filename or "/" in filename
                or "\\" in filename or ":" in filename or not filename.lower().endswith(".csv")):
            raise ArchiveError("投入フォルダのCSVを選択してください")
        path = self.paths.incoming / filename
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_ZIP_BYTES:
            raise ArchiveError("CSVが見つからないか100 MBを超えています")
        raw = path.read_bytes()
        info = describe(raw)
        if expected is not None and expected != info["sha256"]:
            raise ArchiveError("ファイルが変更されました。画面を更新してください")
        return raw, info

    def prior(self, info):
        with self.db() as db:
            row = db.execute("SELECT payload FROM approvals WHERE source_sha=? "
                             "ORDER BY id DESC LIMIT 1", (info["sha256"],)).fetchone()
            if row:
                return json.loads(row[0])
            row = db.execute("SELECT payload FROM approvals WHERE schema_sha=? AND remember=1 "
                             "ORDER BY id DESC LIMIT 1", (info["schema"],)).fetchone()
        if not row:
            return None
        value = json.loads(row[0])
        # Fixed dates and warehouses are never carried over to another file.
        return {**value, "center": "", "day": "", "reused": True}

    def candidates(self):
        result = []
        for path in sorted(self.paths.incoming.glob("*")):
            if path.suffix.lower() != ".csv" or not path.is_file():
                continue
            try:
                _, info = self.source(path.name)
                result.append({"filename": path.name, **info, "approval": self.prior(info)})
            except (ArchiveError, OSError) as exc:
                result.append({"filename": path.name, "error": str(exc)})
        return result

    def approve(self, payload):
        raw, info = self.source(payload.get("filename"), payload.get("sha256"))
        kind, mapping = payload.get("kind"), payload.get("mapping")
        if kind not in FIELDS or not isinstance(mapping, dict):
            raise ArchiveError("ファイルの種類と列を選択してください")
        if set(mapping) - set(FIELDS[kind]) or any(
                not isinstance(v, str) or v not in info["headers"] for v in mapping.values()):
            raise ArchiveError("元CSVに存在する列だけを指定してください")
        if not set(REQUIRED[kind]) <= set(mapping):
            raise ArchiveError("必須列の対応を選択してください")
        center = str(payload.get("center") or "").strip()
        day = str(payload.get("day") or "").strip()
        actor = str(payload.get("actor") or "").strip()
        if not actor or len(actor) > 100 or len(center) > 100:
            raise ArchiveError("確認者と倉庫名を確認してください")
        if day:
            try:
                date.fromisoformat(day)
            except ValueError as exc:
                raise ArchiveError("基準日を日付で入力してください") from exc
        value = {"kind": kind, "mapping": mapping, "center": center, "day": day,
                 "actor": actor, "at": datetime.now(UTC).isoformat(),
                 "source_sha": info["sha256"], "schema_sha": info["schema"]}
        normalized = self.normalize(raw, value)
        # Validate metadata before saving an approval, using the same formal reader.
        import zipfile

        from .source_detection import read_source

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(payload["filename"], normalized)
        with zipfile.ZipFile(buffer) as archive:
            read_source(archive, archive.infolist()[0])
        with self.db() as db:
            db.execute("INSERT INTO approvals(source_sha,schema_sha,remember,payload) "
                       "VALUES(?,?,?,?)", (info["sha256"], info["schema"],
                                           payload.get("remember") is True,
                                           json.dumps(value, ensure_ascii=False)))
        return value

    @staticmethod
    def normalize(raw, approval):
        mapping = approval["mapping"]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=FIELDS[approval["kind"]], lineterminator="\n")
        writer.writeheader()
        for row in csv.DictReader(io.StringIO(_decode(raw))):
            values = {target: row.get(source) or "" for target, source in mapping.items()}
            for target, fixed in (("倉庫", approval["center"]), ("基準日", approval["day"])):
                if fixed:
                    # Do not replace contradictory information already present in a mapped column.
                    current = str(values.get(target) or "").strip()
                    if current and current != fixed:
                        raise ArchiveError(f"{target}の入力値と元データが一致しません")
                    values[target] = fixed
            writer.writerow(values)
        return output.getvalue().encode("utf-8-sig")

    def transform(self, filename, raw):
        approval = self.prior(describe(raw))
        return (self.normalize(raw, approval), approval) if approval else (raw, None)

    def suggest(self, payload):
        if payload.get("consent") is not True:
            raise ArchiveError("列名をOpenAIへ送信する確認が必要です")
        _, info = self.source(payload.get("filename"), payload.get("sha256"))
        return suggest_cloud_structure({"headers": info["headers"], "value_types": {}},
                                       payload.get("api_key"))
