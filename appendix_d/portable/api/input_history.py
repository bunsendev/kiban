"""Candidate input history: preserve originals, deduplicate files, reject revisions."""

import hashlib
import io
import json
import sqlite3
import zipfile
from contextlib import contextmanager

from .business_archive import MAX_ZIP_BYTES, ArchiveError, _business_date, _safe_members
from .source_detection import read_source


class InputHistory:
    def __init__(self, paths):
        self.path = paths.state / "input-history.sqlite3"
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS archives (sha TEXT PRIMARY KEY, raw BLOB)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS files "
                "(sha TEXT PRIMARY KEY, name TEXT, kind TEXT, center TEXT, days TEXT, "
                "semantic TEXT, raw BLOB, archive_sha TEXT)"
            )

    @contextmanager
    def stage(self, raw):
        if not raw or len(raw) > MAX_ZIP_BYTES:
            raise ArchiveError("ZIPは1 byte以上100 MB以下にしてください")
        digest = hashlib.sha256(raw).hexdigest()
        if not zipfile.is_zipfile(io.BytesIO(raw)):
            raise ArchiveError("ZIPを読み取れません")
        incoming = []
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for member in _safe_members(archive):
                if member.is_dir() or not member.filename.lower().endswith(".csv"):
                    continue
                kind, center, day, reader = read_source(archive, member)
                if not kind:
                    continue
                rows = list(reader)
                days = (
                    {day.isoformat()}
                    if day
                    else {
                        d.isoformat()
                        for r in rows
                        if (d := _business_date(str(r.get("出荷日") or ""))) is not None
                    }
                )
                body = archive.read(member)
                semantic = hashlib.sha256(
                    json.dumps(
                        sorted(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows),
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                incoming.append(
                    (
                        # Legacy CSVs identify the warehouse in their filename.
                        # Identical bytes from different warehouses are distinct inputs.
                        hashlib.sha256(
                            json.dumps([kind, center], ensure_ascii=False).encode() + b"\0" + body
                        ).hexdigest(),
                        member.filename,
                        kind,
                        center,
                        json.dumps(sorted(days)),
                        semantic,
                        body,
                        digest,
                    )
                )
        centers = {r[3] for r in incoming}
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("BEGIN IMMEDIATE")
            previous = [
                r for r in db.execute("SELECT * FROM files ORDER BY sha") if r[3] in centers
            ]
            selected = list(previous)
            new = []
            duplicates = 0
            for item in incoming:
                same = [
                    r
                    for r in selected
                    if r[2:4] == item[2:4] and set(json.loads(r[4])) & set(json.loads(item[4]))
                ]
                if any(r[5] == item[5] and r[4] == item[4] for r in same):
                    duplicates += 1
                    continue
                if same:
                    raise ArchiveError(
                        f"{item[1]}: 同じ倉庫・種類・日付の異なるCSVがあります。"
                        f"既存 {same[0][1]} と原本を照合してください。上書き・加算していません"
                    )
                if item[0] not in {r[0] for r in selected}:
                    selected.append(item)
                    new.append(item)
                else:
                    duplicates += 1
            # Keep a first independent upload byte-identical for existing archive IDs.
            combined = raw
            inherited = [r for r in previous if r[0] not in {i[0] for i in incoming}]
            if inherited or duplicates:
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as output:
                    for item in sorted(selected, key=lambda r: (r[3], r[2], r[4], r[0])):
                        info = zipfile.ZipInfo(
                            f"History/{item[0][:16]}/{item[1]}", (1980, 1, 1, 0, 0, 0)
                        )
                        info.compress_type = zipfile.ZIP_DEFLATED
                        output.writestr(info, item[6])
                    # Keep incoming unsupported files so their errors do not disappear.
                    with zipfile.ZipFile(io.BytesIO(raw)) as source:
                        known = {i[1] for i in incoming}
                        for m in source.infolist():
                            if not m.is_dir() and m.filename not in known:
                                info = zipfile.ZipInfo(
                                    "Incoming/" + m.filename, (1980, 1, 1, 0, 0, 0)
                                )
                                info.compress_type = zipfile.ZIP_DEFLATED
                                output.writestr(info, source.read(m))
                    output.writestr(
                        zipfile.ZipInfo("History/manifest.json", (1980, 1, 1, 0, 0, 0)),
                        json.dumps(
                            {
                                "format": "portable-candidate-history-v1",
                                "sources": sorted({r[7] for r in selected}),
                                "incoming": digest,
                                "notice": "取込候補履歴。正式データ承認ではありません。",
                            },
                            ensure_ascii=False,
                        ),
                    )
                combined = stream.getvalue()
            if len(combined) > MAX_ZIP_BYTES:
                raise ArchiveError(
                    "履歴を合わせたZIPが100 MBを超えます。IT担当者へ確認してください"
                )
            metadata = {
                "incoming_sha256": digest,
                "candidate_files": len(selected),
                "new_files": len(new),
                "duplicate_files": duplicates,
                "inherited_files": len(inherited),
                "notice": "同じ倉庫の取込候補履歴を参照。正式承認とは別です。",
            }
            yield combined, metadata
            db.execute("INSERT OR IGNORE INTO archives VALUES(?,?)", (digest, raw))
            db.executemany("INSERT OR IGNORE INTO files VALUES(?,?,?,?,?,?,?,?)", new)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
