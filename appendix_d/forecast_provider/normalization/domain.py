"""列mappingの検証と内容アドレス識別。"""

import hashlib
import json

from .contracts import ColumnMapping


def make_mapping(definition: dict) -> ColumnMapping:
    required = {
        "date_column",
        "jan_column",
        "product_name_column",
        "quantity_column",
        "unit_column",
        "date_formats",
        "allowed_units",
        "availability_mode",
        "file_mode",
    }
    missing = sorted(required - definition.keys())
    if missing:
        raise ValueError(f"列mappingの必須項目がありません: {', '.join(missing)}")
    unknown = sorted(
        definition.keys()
        - required
        - {"center_column", "center_value", "row_type_column", "available_at_column"}
    )
    if unknown:
        raise ValueError(f"列mappingに未知の項目があります: {', '.join(unknown)}")
    for name in required - {"date_formats", "allowed_units"}:
        if not isinstance(definition[name], str) or not definition[name]:
            raise ValueError(f"{name}は空でない文字列です")
    if bool(definition.get("center_column")) == bool(definition.get("center_value")):
        raise ValueError("center_columnとcenter_valueは一方だけ指定します")
    if definition["availability_mode"] not in {"ASSUMED", "OBSERVED"}:
        raise ValueError("availability_modeが不正です")
    if definition["availability_mode"] == "OBSERVED" and not definition.get("available_at_column"):
        raise ValueError("OBSERVEDにはavailable_at_columnが必要です")
    if definition["availability_mode"] == "ASSUMED" and definition.get("available_at_column"):
        raise ValueError("ASSUMEDではavailable_at_columnを指定しません")
    if definition["file_mode"] not in {"FULL", "DELTA"}:
        raise ValueError("file_modeはFULLまたはDELTAです")
    for name in ("date_formats", "allowed_units"):
        value = definition[name]
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(x, str) and x for x in value)
        ):
            raise ValueError(f"{name}は空でない文字列listです")
    columns = [
        definition[name]
        for name in (
            "date_column",
            "jan_column",
            "product_name_column",
            "quantity_column",
            "unit_column",
            "center_column",
            "row_type_column",
            "available_at_column",
        )
        if definition.get(name)
    ]
    if len(columns) != len(set(columns)):
        raise ValueError("一つの原本列を複数の意味へmappingできません")
    if len(definition["allowed_units"]) != len(set(definition["allowed_units"])):
        raise ValueError("allowed_unitsに重複があります")
    canonical = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return ColumnMapping(f"map-{digest}", 1, digest, json.loads(canonical))
