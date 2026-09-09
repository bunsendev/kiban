"""版付きmappingで原本CSVを出荷行へ正規化する。"""

import csv
import hashlib
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from .contracts import Reconciliation, ShipmentRow

JST = ZoneInfo("Asia/Tokyo")


class NormalizationProcessor:
    def __init__(self, normalization_store, ingestion_store):
        self.store = normalization_store
        self.ingestion = ingestion_store

    def process_next(self):
        job = self.store.claim()
        if job is None:
            return None
        try:
            source = self.ingestion.get_file(job.source_file_id)
            mapping = self.store.get_mapping(job.mapping_id)
            if source is None or source.stored_path is None or source.encoding is None:
                raise ValueError("読取可能な原本が見つかりません")
            if mapping is None:
                raise ValueError("列mappingが見つかりません")
            data = Path(source.stored_path).read_bytes()
            if hashlib.sha256(data).hexdigest() != source.sha256:
                raise ValueError("保存原本のchecksumが一致しません")
            rows, reconciliation = normalize_csv(job.normalization_id, source, mapping.definition)
            self.store.complete(job.normalization_id, rows, reconciliation)
        except Exception as exc:
            self.store.fail(job.normalization_id, str(exc))
        return self.store.get_job(job.normalization_id)


def normalize_csv(normalization_id, source, mapping):
    with Path(source.stored_path).open(
        "r", encoding=source.encoding, errors="strict", newline=""
    ) as stream:
        reader = csv.DictReader(stream, strict=True)
        if len(reader.fieldnames or ()) != len(set(reader.fieldnames or ())):
            raise ValueError("原本headerに重複があります")
        required = _required_columns(mapping)
        missing = sorted(required - set(reader.fieldnames or ()))
        if missing:
            raise ValueError(f"mapping対象列が原本にありません: {', '.join(missing)}")
        rows = [
            _normalize_row(normalization_id, source.source_file_id, number, raw, mapping)
            for number, raw in enumerate(reader, start=2)
        ]
    parseable = sum((row.quantity for row in rows if row.quantity is not None), Decimal(0))
    accepted = sum(
        (row.quantity for row in rows if row.status == "ACCEPTED" and row.quantity is not None),
        Decimal(0),
    )
    quarantined = sum(
        (row.quantity for row in rows if row.status == "QUARANTINED" and row.quantity is not None),
        Decimal(0),
    )
    reconciliation = Reconciliation(
        normalization_id, parseable, accepted, quarantined, parseable - accepted - quarantined
    )
    return rows, reconciliation


def _required_columns(mapping):
    keys = {
        mapping["date_column"],
        mapping["jan_column"],
        mapping["product_name_column"],
        mapping["quantity_column"],
        mapping["unit_column"],
    }
    for name in ("center_column", "row_type_column", "available_at_column"):
        if mapping.get(name):
            keys.add(mapping[name])
    return keys


def _normalize_row(normalization_id, source_file_id, row_number, raw, mapping):
    errors = []
    raw_jan = _cell(raw, mapping["jan_column"])
    raw_name = _cell(raw, mapping["product_name_column"])
    unit = _cell(raw, mapping["unit_column"])
    center = (
        _cell(raw, mapping["center_column"])
        if mapping.get("center_column")
        else mapping["center_value"]
    )
    row_type = (
        _cell(raw, mapping["row_type_column"]) if mapping.get("row_type_column") else "SHIPMENT"
    )
    shipment_date = _date(_cell(raw, mapping["date_column"]), mapping["date_formats"], errors)
    quantity = _quantity(_cell(raw, mapping["quantity_column"]), errors)
    if not raw_jan:
        errors.append("JANが空です")
    if not raw_name:
        errors.append("商品名が空です")
    if not center:
        errors.append("centerが空です")
    if unit not in mapping["allowed_units"]:
        errors.append("単位が許可listにありません")
    if row_type != "SHIPMENT":
        errors.append("返品・取消・不明行区分は出荷数量から隔離します")
    available_at = _available_at(raw, mapping, shipment_date, errors)
    return ShipmentRow(
        normalization_id,
        source_file_id,
        row_number,
        center or None,
        None if shipment_date is None else shipment_date.isoformat(),
        raw_jan or None,
        raw_name or None,
        quantity,
        unit or None,
        row_type or None,
        available_at,
        "QUARANTINED" if errors else "ACCEPTED",
        "; ".join(errors) or None,
    )


def _cell(raw, name):
    value = raw.get(name)
    return "" if value is None else value.strip()


def _date(value, formats, errors):
    for date_format in formats:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            pass
    errors.append("日付形式がmappingと一致しません")
    return None


def _quantity(value, errors):
    try:
        quantity = Decimal(value)
    except InvalidOperation:
        errors.append("数量が数値ではありません")
        return None
    if not quantity.is_finite():
        errors.append("数量が有限値ではありません")
        return None
    elif quantity < 0:
        errors.append("負数量は自動補正せず隔離します")
    return quantity


def _available_at(raw, mapping, shipment_date, errors):
    if mapping["availability_mode"] == "ASSUMED":
        if shipment_date is None:
            return None
        return datetime.combine(shipment_date + timedelta(days=1), time(), JST).isoformat()
    value = _cell(raw, mapping["available_at_column"])
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        errors.append("available_atがISO datetimeではありません")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append("available_atはtimezone付きです")
        return None
    return parsed.astimezone(UTC).isoformat()
