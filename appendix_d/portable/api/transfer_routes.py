"""Local administrative transfer ledger, independent from inventory snapshots."""

import csv
import io
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from portable.transfers import TransferLedger, compare, source_digest

COLUMNS = (
    "event_id",
    "event_date",
    "movement_kind",
    "transfer_id",
    "line_id",
    "product",
    "source_location",
    "destination_location",
    "quantity",
    "unit",
    "source_file",
    "classification_evidence",
)


def register_transfers(app, paths, read_limited):
    ledger = TransferLedger(paths.state / "warehouse-transfers.sqlite3")
    sources = paths.state / "TransferSources"
    sources.mkdir(exist_ok=True)

    @app.get("/warehouse-transfers")
    def screen():
        return FileResponse(Path(__file__).parent / "static/field/transfers.html")

    @app.get("/api/warehouse-transfers/template")
    def template():
        return Response(
            "\ufeff" + ",".join(COLUMNS) + "\n",
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="warehouse-transfers.csv"'},
        )

    @app.post("/api/warehouse-transfers", status_code=201)
    async def upload(request: Request):
        try:
            raw = await read_limited(request, 10 * 1024 * 1024)
            text = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text), strict=True)
            if not set(COLUMNS) <= set(reader.fieldnames or ()):
                raise ValueError("専用CSVテンプレートの列を確認してください")
            rows = list(reader)
            if not rows:
                raise ValueError("CSVに明細がありません")
            sha = source_digest(raw)
            # Preserve exact source even if later validation quarantines the batch.
            (sources / (sha + ".csv")).write_bytes(raw)
            return ledger.ingest(rows, sha, unquote(request.headers.get("X-Bunsen-Reviewer", "")))
        except (ValueError, csv.Error) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/warehouse-transfers")
    def report(start: str, end: str):
        try:
            return ledger.report(start, end)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/warehouse-transfers/comparison")
    def comparison(
        before_start: str,
        before_end: str,
        after_start: str,
        after_end: str,
        coverage_confirmed: bool = False,
    ):
        try:
            if before_end >= after_start:
                raise ValueError("比較期間は重複せず、導入前・導入後の順で指定してください")
            before = ledger.report(before_start, before_end)
            after = ledger.report(after_start, after_end)
            return compare(before, after, coverage_confirmed=coverage_confirmed)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
