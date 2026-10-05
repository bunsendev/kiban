"""Conservative scanner for operator CSVs and ZIPs placed in Data/Incoming."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import threading
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from .business_archive import MAX_ZIP_BYTES, ArchiveError
from .folder_csv import bundle_csv
from .source_detection import read_source


class DropFolderError(ValueError):
    pass


class DropFolderBusyError(RuntimeError):
    pass


LOG = logging.getLogger("portable.drop-folder")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


class DropFolderIntake:
    def __init__(self, paths, ingest, *, active, interval_seconds: float = 2.0) -> None:
        self.paths = paths
        self.ingest = ingest
        self.active = active
        self.interval_seconds = interval_seconds
        self.processed = paths.incoming / "Processed"
        self.rejected = paths.incoming / "Rejected"
        self.receipts = paths.incoming / "Receipts"
        for path in (self.processed, self.rejected, self.receipts):
            path.mkdir(parents=True, exist_ok=True)
        self._observed: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._csv_signature = None
        self._csv_attempt = None
        self._csv_changed_at = 0.0
        self.csv_message = "CSVは在庫・出荷をまとめてコピーしてください。ZIPも使用できます。"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="portable-drop-folder", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(3.0, self.interval_seconds * 2))

    def scan(self, *, force: bool = False) -> dict:
        with self._lock:
            handled = []
            current = set()
            for path in sorted(self.paths.incoming.iterdir()):
                if not path.is_file() or path.suffix.lower() != ".zip":
                    continue
                current.add(str(path))
                stat = path.stat()
                signature = (stat.st_size, stat.st_mtime_ns)
                previous = self._observed.get(str(path))
                self._observed[str(path)] = signature
                if not force and previous != signature:
                    continue
                handled.append(self._process(path))
                self._observed.pop(str(path), None)
            self._observed = {
                key: value for key, value in self._observed.items() if key in current
            }
            csv_receipt = self._scan_csv(force=force)
            if csv_receipt:
                handled.append(csv_receipt)
            return self.view(handled=handled)

    def _scan_csv(self, *, force: bool) -> dict | None:
        paths = sorted(p for p in self.paths.incoming.iterdir()
                       if p.is_file() and p.suffix.lower() == ".csv")
        signature = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
        unchanged = signature == self._csv_signature
        self._csv_signature = signature
        if not unchanged:
            self._csv_changed_at = time.monotonic()
        if not paths or (not force and time.monotonic() - self._csv_changed_at < 10):
            return None
        if not force and signature == self._csv_attempt:
            return None
        self._csv_attempt = signature
        try:
            data, originals = bundle_csv(paths)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                kinds = [read_source(archive, member)[0] for member in archive.infolist()]
            if "shipment" not in kinds:
                self.csv_message = "出荷CSVを待っています。在庫CSVはそのまま保持しています。"
                return None
        except (ArchiveError, OSError) as exc:
            self.csv_message = str(exc)
            return None
        digest = hashlib.sha256(data).hexdigest()
        target = self.paths.incoming / f"csv-{digest}.zip"
        if target.exists():
            self.csv_message = "前回のCSV受付を処理中です。しばらくお待ちください。"
            return None
        # Original CSVs remain intact until their byte-preserving ZIP is accepted.
        with target.open("xb") as stream:
            stream.write(data)
        receipt = self._process(target)
        if receipt["status"] == "PROCESSED":
            for path, original_hash in originals:
                if (path.is_file()
                        and hashlib.sha256(path.read_bytes()).hexdigest() == original_hash):
                    os.replace(path, self._destination(self.processed, path.name, digest))
            self.csv_message = "CSVをまとめて分析しました。受付済みの分析を開いてください。"
        else:
            self.csv_message = receipt["detail"]
        return receipt

    def view(self, *, handled: list[dict] | None = None) -> dict:
        pending = []
        for path in sorted(self.paths.incoming.iterdir()):
            if path.is_file() and path.suffix.lower() in {".zip", ".csv"}:
                pending.append({"filename": path.name, "size_bytes": path.stat().st_size})
        recent = []
        for path in sorted(
            self.receipts.glob("*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True
        )[:20]:
            try:
                recent.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return {
            "folder": str(self.paths.incoming),
            "pending": pending,
            "handled": handled or [],
            "recent": recent,
            "csv_message": self.csv_message,
        }

    def _process(self, path: Path) -> dict:
        try:
            before = path.stat()
            size = before.st_size
            if size < 1 or size > MAX_ZIP_BYTES:
                raise DropFolderError("ZIPは1 byte以上100 MB以下にしてください")
            data = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise DropFolderBusyError("コピー中のため次回確認時に再試行します")
            with self.active():
                report = self.ingest(data)
            status = "PROCESSED"
            detail = "分析を開始し、日次実行へ登録しました"
            analysis_id = report["analysis_id"]
            destination = self._destination(self.processed, path.name, analysis_id)
        except (ArchiveError, DropFolderError, OSError) as exc:
            data = path.read_bytes() if path.is_file() else b""
            analysis_id = hashlib.sha256(data).hexdigest()
            status = "REJECTED"
            detail = str(exc)
            destination = self._destination(self.rejected, path.name, analysis_id)
        os.replace(path, destination)
        receipt = {
            "format": "portable-drop-folder-receipt-v1",
            "receipt_id": hashlib.sha256(_canonical({
                "analysis_id": analysis_id, "filename": path.name, "status": status,
            })).hexdigest(),
            "analysis_id": analysis_id,
            "filename": path.name,
            "status": status,
            "detail": detail,
            "stored_path": str(destination.relative_to(self.paths.root)),
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        target = self.receipts / f"{receipt['receipt_id']}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(_canonical(receipt))
        os.replace(temporary, target)
        return receipt

    @staticmethod
    def _destination(root: Path, original_name: str, digest: str) -> Path:
        safe = re.sub(r"[^0-9A-Za-z._-]+", "_", original_name).strip("._") or "input.zip"
        candidate = root / f"{digest[:16]}-{safe}"
        number = 2
        while candidate.exists():
            candidate = root / f"{digest[:16]}-{number}-{safe}"
            number += 1
        return candidate

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.scan()
            except DropFolderBusyError:
                pass
            except Exception:
                # A later scan retries untouched files; API logging owns diagnostics.
                LOG.exception("drop_folder_scan_failed code=PORTABLE-DROP-001")
                time.sleep(min(self.interval_seconds, 1.0))
