"""Shared, versioned completeness checks for upload and drop-folder inputs."""

import csv
import hashlib
import io
import json
import re
import uuid
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from functools import cache
from itertools import pairwise
from zoneinfo import ZoneInfo

import pandas as pd

from forecast_provider.daily.contracts import FileCompleteness
from forecast_provider.daily.states import _state

from .business_archive import _business_date, _safe_members
from .business_review import latest_decisions, rebuild_reviewed_prepared, review_view
from .data_quality_rules import DEFAULT, compile_rules, text, validate_rules
from .data_quality_store import QualityStore, digest, now
from .document_evidence import valid_jan
from .forecast_capabilities import CAPABILITY, missing_capability
from .inventory_handoff import _mapped_jan
from .product_exclusions import ProductExclusions
from .source_detection import read_source

JST = ZoneInfo("Asia/Tokyo")
LABELS = {
    "FILE_MISSING": "ファイル未受信",
    "DATE_MISSING": "必要な日付のデータなし",
    "WAREHOUSE_MISSING": "倉庫の出荷データなし",
    "PRODUCT_MISSING": "対象商品のデータなし",
    "QUANTITY_MISSING": "数量が空欄・未確認",
    "DUPLICATE_RECORD": "重複・訂正版の衝突",
    "INVALID_VALUE": "値・商品対応の確認が必要",
    "DATA_DELAYED": "データの基準日・受信が遅延",
    "ABNORMAL_CHANGE": "在庫変動の確認が必要",
    "SCHEDULE_UNCONFIGURED": "受信予定は未設定",
    "MODEL_INPUT_UNSUPPORTED": "モデルが必要とする実績が不足",
}


def quantity(value):
    try:
        result = Decimal(str(value).replace(",", ""))
        return result if result.is_finite() and result >= 0 else None
    except InvalidOperation:
        return None


class DataQuality:
    def __init__(self, paths):
        self.paths = paths
        self.store = QualityStore(paths)

    def rules(self, *, as_of=None):
        rows = self.store.list("rules", limit=1000 if as_of else 1)
        if as_of:
            bounded = len(rows) == 1000
            rows = [r for r in rows if datetime.fromisoformat(r["known_at"]) <= as_of]
            if not rows and bounded:
                raise ValueError("この過去時点の品質設定を確認できません")
        return (
            rows[0]
            if rows
            else {
                "id": "default-calendar-v1",
                "rules": DEFAULT,
                "notice": "全暦日稼働。受信予定・商品省略の意味は未設定です",
            }
        )

    def save_rules(self, value):
        if not isinstance(value, dict):
            raise ValueError("品質設定を確認してください")
        actor = text(value.get("actor"), "設定者")
        reason = text(value.get("reason"), "理由", 500)
        if value.get("expected_version") != self.rules()["id"]:
            raise ValueError("品質設定が変更されました。再表示して確認してください")
        return self.store.save(
            "rules",
            "",
            {
                "rules": validate_rules(value.get("rules")),
                "actor": actor,
                "reason": reason,
                "known_at": now(),
            },
        )

    def receipt(
        self,
        raw,
        *,
        method="MANUAL_UPLOAD",
        filename="upload.zip",
        result="ACCEPTED",
        analysis_id=None,
        error=None,
    ):
        files = []
        if result in {"ACCEPTED", "REVIEW_REQUIRED"}:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for m in _safe_members(archive):
                    if m.is_dir() or not m.filename.lower().endswith(".csv"):
                        continue
                    kind, center, day, reader = read_source(archive, m)
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
                    files.append(
                        {
                            "name": m.filename,
                            "sha256": hashlib.sha256(archive.read(m)).hexdigest(),
                            "kind": kind,
                            "warehouse": center,
                            "target_dates": sorted(days),
                            "rows": len(rows),
                        }
                    )
        return self.store.save(
            "receipt",
            analysis_id or "",
            {
                "attempt_id": uuid.uuid4().hex,
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "method": method,
                "filename": str(filename)[:200],
                "received_at": now(),
                "analysis_id": analysis_id,
                "result": result,
                "error": error,
                "files": files,
            },
        )

    def check(self, analysis_id, *, checked_at=None):
        if not isinstance(analysis_id, str) or not re.fullmatch(r"[0-9a-f]{64}", analysis_id):
            raise ValueError("分析IDを確認してください")
        report_path = self.paths.analysis / f"{analysis_id}.json"
        report = json.loads(report_path.read_text("utf-8"))
        if report.get("analysis_id") != analysis_id:
            raise ValueError("分析結果の識別子が一致しません")
        # Validate immutable source bytes even when a parsed check can be reused.
        source_path = self.paths.input / f"{analysis_id}.zip"
        with source_path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != analysis_id:
                raise ValueError("原本ZIPの整合性を確認できません")
        journal = self.paths.decisions / f"{analysis_id}.jsonl"
        decisions = latest_decisions(journal)
        reviewed = review_view(report, journal)
        prepared = self.paths.prepared / f"{analysis_id}-reviewed.csv"
        if not prepared.exists():
            prepared = self.paths.prepared / f"{analysis_id}.csv"
        prepared_raw = prepared.read_bytes()
        # Rebuild only in a temporary directory to verify provenance, never replace saved inputs.
        if report.get("prepared_sha256"):
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory(prefix="bunsen-quality-") as tmp:
                base = self.paths.prepared / f"{analysis_id}.csv"
                if hashlib.sha256(base.read_bytes()).hexdigest() != report["prepared_sha256"]:
                    raise ValueError(
                        "保存した出荷集計が変更されています。原本から再集計してください"
                    )
                expected = base
                if prepared.name.endswith("-reviewed.csv"):
                    expected = Path(tmp) / "reviewed.csv"
                    rebuild_reviewed_prepared(base, expected, report, journal)
                if expected.read_bytes() != prepared_raw:
                    raise ValueError("確認済み出荷集計が変わりました。原本から再集計してください")
        values = {}
        for r in csv.DictReader(io.StringIO(prepared_raw.decode("utf-8-sig"))):
            center, jan = r["unique_id"].rsplit(":", 1)
            values[(center, jan, r["ds"])] = quantity(r["y"])
        clock = checked_at or datetime.now(UTC)
        if clock.tzinfo is None:
            raise ValueError("検証日時にはタイムゾーンが必要です")
        policy = self.rules(as_of=clock)
        lookup = compile_rules(policy["rules"])
        master_index = {
            r["warehouse"]: set(r["master_jans"])
            for r in policy["rules"]["warehouses"]
            if r.get("master_jans") is not None
        }
        exclusions = ProductExclusions(self.paths)
        exclusion_rules = exclusions.list()
        local_clock = clock.astimezone(JST)
        fingerprint = digest(
            {
                "version": "quality-check-cache-v1",
                "report": digest(report),
                "prepared": hashlib.sha256(prepared_raw).hexdigest(),
                "decisions": digest(decisions),
                "policy": policy["id"],
                "exclusions": exclusion_rules,
                "day": local_clock.date().isoformat(),
                "due": [
                    (r["warehouse"], local_clock.strftime("%H:%M") >= r["receipt_due_time"])
                    for r in policy["rules"]["warehouses"]
                ],
            }
        )
        previous = self.store.list("check", analysis_id, limit=1)
        if previous and previous[0].get("fingerprint") == fingerprint:
            return previous[0]

        @cache
        def excluded(jan):
            return exclusions.apply([{"jan": jan}], rules=exclusion_rules)[0].get("exclude", False)

        source = self._sources(analysis_id, report, decisions, excluded)
        stock_series = defaultdict(list)
        for (c, j, d), q in source["stock"].items():
            stock_series[(c, j)].append((d, q))
        clock = clock.astimezone(JST)
        products = source["products"] | {(c, j) for c, j, _ in values}
        products = {(c, j) for c, j in products if not excluded(j)}
        for rule in policy["rules"]["warehouses"]:
            products.update(
                (rule["warehouse"], p["jan"]) for p in rule["products"] if not excluded(p["jan"])
            )
        issues, summaries, daily = [], [], []

        def issue(code, center, jan, day, kind, detail, severity="WARNING"):
            item = {
                "code": code,
                "warehouse": center,
                "jan": jan,
                "product_name": source["names"].get((center, jan), ""),
                "date": day,
                "kind": kind,
                "severity": severity,
                "detail": detail,
            }
            item["issue_id"] = digest(item)
            issues.append(item)

        ends = dict(source["inventory_dates"])
        for center, dates in source["shipment_dates"].items():
            if dates:
                ends.setdefault(center, max(dates))
        for center, jan in sorted(products):
            end = ends.get(center)
            if end is None:
                # Configured warehouses with no receipts still have an expected target day.
                end = clock.date().isoformat()
            origin = pd.Timestamp(end).date()
            start = origin - timedelta(days=27)
            frame, missing, required, valid, severe = [], [], 0, 0, False
            _, _, scope_rule = lookup(center, jan, origin)
            if (
                scope_rule
                and scope_rule.get("master_jans") is not None
                and (jan not in master_index[center])
            ):
                issue(
                    "INVALID_VALUE",
                    center,
                    jan,
                    end,
                    "master",
                    "登録された商品マスターにJANがありません。別途照合してください",
                )
            if origin > clock.date():
                issue("INVALID_VALUE", center, jan, end, "date", "基準日が未来です", "ERROR")
                severe = True
            warehouse_dates = source["shipment_dates"].get(center, set())
            if not warehouse_dates:
                issue(
                    "WAREHOUSE_MISSING", center, jan, end, "shipment", "倉庫の出荷履歴がありません"
                )
            for offset in range(28):
                day = start + timedelta(days=offset)
                ds = day.isoformat()
                handled, closed, rule = lookup(center, jan, day)
                if day > clock.date():
                    continue
                q = values.get((center, jan, ds))
                if not handled:
                    if q is not None and q > 0:
                        issue(
                            "INVALID_VALUE",
                            center,
                            jan,
                            ds,
                            "shipment",
                            "取扱期間外に出荷数量があります。期間または原本を確認",
                            "ERROR",
                        )
                        severe = True
                    continue
                invalid = (center, jan, ds) in source["invalid_shipment"]
                complete = ds in source["daily_files"].get(center, set()) and not invalid
                # Existing, explicit daily export zero confirmation is still required on run.
                zero = rule["absence_means_zero"] if rule else True
                file = FileCompleteness(
                    "preview",
                    center,
                    ds,
                    "COMPLETE" if complete else "PARTIAL_OR_INVALID" if invalid else "MISSING",
                    1,
                    int(complete),
                    complete and zero,
                    clock.isoformat(),
                )
                raw = {"raw_quantity": q} if q is not None else None
                state, y, _ = _state(handled, closed, raw, file)
                # Explicit observed rows in monthly exports are evidence even without a daily file.
                if q is not None and not invalid:
                    state, y = "OBSERVED", q
                if not closed:
                    required += 1
                    if state in {"OBSERVED", "CONFIRMED_ZERO"}:
                        valid += 1
                    else:
                        missing.append(ds)
                        code = (
                            "INVALID_VALUE"
                            if invalid
                            else "PRODUCT_MISSING"
                            if complete or ds in warehouse_dates
                            else "DATE_MISSING"
                        )
                        issue(
                            code,
                            center,
                            jan,
                            ds,
                            "shipment",
                            "出荷数量の原本を追加・確認してください",
                            "ERROR" if invalid else "WARNING",
                        )
                        severe |= invalid
                        if not complete and not invalid and ds not in warehouse_dates:
                            # Without an agreed schedule, do not claim a file was due.
                            due = (
                                datetime.combine(
                                    day, time.fromisoformat(rule["receipt_due_time"]), JST
                                )
                                if rule
                                else None
                            )
                            if due and due <= clock:
                                issue(
                                    "FILE_MISSING",
                                    center,
                                    "",
                                    ds,
                                    "shipment",
                                    "予定されている日次出荷ファイルが未受信です",
                                )
                frame.append(
                    {
                        "ds": pd.Timestamp(day),
                        "y": float(y) if y is not None and state != "CLOSED" else float("nan"),
                    }
                )
                daily.append(
                    {
                        "warehouse": center,
                        "jan": jan,
                        "date": ds,
                        "state": state,
                        "quantity": str(y) if y is not None else None,
                    }
                )
            for item in source["problems"]:
                if (
                    item["warehouse"] == center
                    and item["jan"] == jan
                    and (
                        item["date"] == source["inventory_dates"].get(center)
                        or (start.isoformat() <= item["date"] <= end and item["kind"] == "shipment")
                        or not item["date"]
                    )
                ):
                    issue(
                        item["code"],
                        center,
                        jan,
                        item["date"],
                        item["kind"],
                        item["detail"],
                        item["severity"],
                    )
                    severe |= item["severity"] == "ERROR"
            inventory_date = source["inventory_dates"].get(center)
            if inventory_date and (center, jan, inventory_date) not in source["stock"]:
                issue(
                    "PRODUCT_MISSING",
                    center,
                    jan,
                    inventory_date,
                    "inventory",
                    "受信済み在庫ファイルに商品行がありません。在庫0とは判定しません",
                )
                severe = True
            stock = sorted(stock_series[(center, jan)])
            for (before_day, before), (current_day, current) in pairwise(stock):
                _, _, rule = lookup(center, jan, pd.Timestamp(current_day).date())
                if (
                    rule
                    and rule["abnormal_change_cases"] is not None
                    and source["stock_units"].get((center, jan, before_day)) == {"CASE"}
                    and source["stock_units"].get((center, jan, current_day)) == {"CASE"}
                    and (abs(current - before) > Decimal(rule["abnormal_change_cases"]))
                ):
                    issue(
                        "ABNORMAL_CHANGE",
                        center,
                        jan,
                        current_day,
                        "inventory",
                        f"{before_day}からの在庫変動が設定閾値を超えています。移動・調整等を確認",
                    )
            capability = missing_capability(pd.DataFrame(frame, columns=["ds", "y"]), origin)
            if not capability["supported"] and required:
                issue("MODEL_INPUT_UNSUPPORTED", center, jan, end, "model", capability["reason"])
            if not any(r["warehouse"] == center for r in policy["rules"]["warehouses"]):
                issue(
                    "SCHEDULE_UNCONFIGURED",
                    center,
                    "",
                    end,
                    "schedule",
                    "受信予定は未設定です。全暦日稼働の仮定で日付不足を表示しています",
                    "INFO",
                )
            if inventory_date and inventory_date < clock.date().isoformat():
                issue(
                    "DATA_DELAYED",
                    center,
                    "",
                    inventory_date,
                    "inventory",
                    "在庫基準日は今日より前です。過去データの再現として確認してください",
                )
            summaries.append(
                {
                    "warehouse": center,
                    "jan": jan,
                    "product_name": source["names"].get((center, jan), ""),
                    "required_start": start.isoformat(),
                    "required_end": end,
                    "required_records": required,
                    "valid_records": valid,
                    "missing_dates": missing,
                    "inventory_date": inventory_date,
                    "normal_eligible": not missing
                    and not severe
                    and required > 0
                    and capability["supported"],
                    "provisional_eligible": capability["supported"] and not severe and required > 0,
                    "provisional_reason": capability["reason"]
                    if not severe
                    else "原本の数量・商品・日付の重大な確認事項を先に解消してください",
                }
            )
        # File counts and affected record counts are separate measures.
        issues = sorted(
            {i["issue_id"]: i for i in issues}.values(),
            key=lambda i: (i["date"], i["warehouse"], i["jan"], i["code"]),
        )
        unconfirmed = reviewed["review"]["pending_rows"] > 0
        if unconfirmed:
            for s in summaries:
                s.update(
                    normal_eligible=False,
                    provisional_eligible=False,
                    provisional_reason="原本の確認・正式取込用データの準備を先に完了してください",
                )
        if report.get("input_history", {}).get("duplicate_files"):
            issue(
                "DUPLICATE_RECORD",
                "",
                "",
                "",
                "file",
                "同じ内容の再取込は二重登録せず既存データを使用しました",
                "INFO",
            )
        counts = Counter(i["code"] for i in issues)
        missing_records = {
            (i["warehouse"], i["jan"], i["date"], i["kind"])
            for i in issues
            if i["jan"] and i["code"] in {"DATE_MISSING", "PRODUCT_MISSING", "QUANTITY_MISSING"}
        }
        required = sum(s["required_records"] for s in summaries)
        valid = sum(s["valid_records"] for s in summaries)
        body = {
            "format": "portable-data-quality-v1",
            "analysis_id": analysis_id,
            "input_sha256": analysis_id,
            "fingerprint": fingerprint,
            "source_files": source["source_files"],
            "inventory_evidence": [
                {"warehouse": c, "jan": j, "date": d} for c, j, d in sorted(source["stock"])
            ],
            "prepared_sha256": hashlib.sha256(prepared_raw).hexdigest(),
            "decisions_sha256": digest(decisions),
            "exclusions_sha256": digest(exclusion_rules),
            "rule_version": policy["id"],
            "rules": policy["rules"],
            "capability_version": CAPABILITY,
            "as_of_date": clock.date().isoformat(),
            "status": "ERROR"
            if unconfirmed or any(i["severity"] == "ERROR" for i in issues)
            else "WARNING"
            if any(i["severity"] == "WARNING" for i in issues)
            else "NORMAL",
            "confirmation_pending": unconfirmed,
            "series": summaries,
            "daily": daily,
            "issues": issues,
            "counts": dict(counts),
            "required_records": required,
            "valid_records": valid,
            "coverage_percent": round(100 * valid / required, 2) if required else None,
            "missing_record_count": len(missing_records),
            "missing_day_count": len({r[2] for r in missing_records if r[2]}),
            "inventory_attention_count": len(
                {(i["warehouse"], i["jan"], i["date"]) for i in issues if i["kind"] == "inventory"}
            ),
            "coverage_scope": "SHIPMENT_REQUIRED_WINDOW",
            "normal_series": sum(s["normal_eligible"] for s in summaries),
            "provisional_series": sum(s["provisional_eligible"] for s in summaries),
            "required_start": min((s["required_start"] for s in summaries), default=None),
            "required_end": max((s["required_end"] for s in summaries), default=None),
        }
        return self.store.save("check", analysis_id, body)

    def _sources(self, analysis_id, report, decisions, excluded):
        result = {
            "products": set(),
            "names": {},
            "inventory_dates": {},
            "shipment_dates": defaultdict(set),
            "daily_files": defaultdict(set),
            "invalid_shipment": set(),
            "stock": {},
            "stock_units": defaultdict(set),
            "source_files": [],
            "problems": [],
        }
        path = self.paths.input / f"{analysis_id}.zip"
        with zipfile.ZipFile(path) as archive:
            for m in _safe_members(archive):
                if m.is_dir() or not m.filename.lower().endswith(".csv"):
                    continue
                kind, center, fileday, reader = read_source(archive, m)
                if not kind:
                    continue
                result["source_files"].append(
                    {
                        "sha256": hashlib.sha256(archive.read(m)).hexdigest(),
                        "kind": kind,
                        "warehouse": center,
                        "target_date": fileday.isoformat() if fileday else None,
                    }
                )
                if kind == "inventory":
                    result["inventory_dates"][center] = max(
                        fileday.isoformat(), result["inventory_dates"].get(center, "")
                    )
                elif fileday:
                    result["daily_files"][center].add(fileday.isoformat())
                    result["shipment_dates"][center].add(fileday.isoformat())
                for row in reader:
                    code = str(
                        row.get("JAN") if kind == "shipment" else row.get("商品コード") or ""
                    ).strip()
                    jan = _mapped_jan(report, decisions, code) if kind == "inventory" else code
                    if not jan or not valid_jan(jan):
                        result["problems"].append(
                            {
                                "code": "INVALID_VALUE",
                                "center": center,
                                "jan": code,
                                "day": fileday.isoformat() if fileday else "",
                                "kind": kind,
                                "detail": "JAN・商品マスターの対応を確認してください",
                                "severity": "ERROR",
                            }
                        )
                        # Do not silently drop an unknown inventory product from the check.
                        jan = code
                    if excluded(jan):
                        continue
                    result["products"].add((center, jan))
                    result["names"][(center, jan)] = str(row.get("商品名") or "")
                    day = fileday if kind == "inventory" else _business_date(row.get("出荷日", ""))
                    ds = day.isoformat() if day else ""
                    if kind == "shipment" and day:
                        result["shipment_dates"][center].add(ds)
                    raw = row.get("数量" if kind == "shipment" else "明細バラ数", "")
                    q = quantity(raw)
                    if q is None:
                        result["problems"].append(
                            {
                                "code": "QUANTITY_MISSING"
                                if not str(raw).strip()
                                else "INVALID_VALUE",
                                "center": center,
                                "jan": jan,
                                "day": ds,
                                "kind": kind,
                                "detail": "数量を原本で確認してください",
                                "severity": "ERROR",
                            }
                        )
                        if kind == "shipment":
                            result["invalid_shipment"].add((center, jan, ds))
                    elif kind == "inventory":
                        key = (center, jan, ds)
                        result["stock"][key] = result["stock"].get(key, Decimal(0)) + q
                        result["stock_units"][key].add(
                            row.get("正規化単位", row.get("単位", "UNKNOWN"))
                        )
        # Normalize source issue names to the local issue builder signature.
        for item in result["problems"]:
            item["warehouse"] = item["center"]
            item["date"] = item["day"]
        return result

    def latest_covering(self, check):
        return self.store.covering(check["id"])

    @staticmethod
    def resolution_index(latest):
        return {
            "issues": {
                tuple(r[k] for k in ("code", "warehouse", "jan", "date", "kind"))
                for r in latest["issues"]
            },
            "daily": {
                (r["warehouse"], r["jan"], r["date"])
                for r in latest["daily"]
                if r["state"] in {"OBSERVED", "CONFIRMED_ZERO", "CLOSED", "NOT_HANDLED"}
            },
            "inventory": {
                (r["warehouse"], r["jan"], r["date"]) for r in latest["inventory_evidence"]
            },
            "files": {
                (f["warehouse"], f["kind"], f["target_date"]) for f in latest["source_files"]
            },
        }

    @staticmethod
    def issue_state(item, latest):
        def key(r):
            return tuple(r[k] for k in ("code", "warehouse", "jan", "date", "kind"))

        if key(item) in latest["issues"]:
            return "UNRESOLVED"
        if item["kind"] == "shipment":
            if item["jan"]:
                valid = (item["warehouse"], item["jan"], item["date"]) in latest["daily"]
            else:
                valid = (item["warehouse"], "shipment", item["date"]) in latest["files"]
        elif item["kind"] == "inventory":
            valid = (item["warehouse"], item["jan"], item["date"]) in latest["inventory"]
        else:
            valid = False
        return "RESOLVED" if valid else "NOT_RECHECKED"

    def summary(self, check):
        receipts = self.store.list("receipt", check["analysis_id"])
        last_received = max((r["received_at"] for r in receipts), default=None)
        last_success = max(
            (r["received_at"] for r in receipts if r["result"] == "ACCEPTED"), default=None
        )
        provisional_reason = "対応する前週同曜日モデルだけ。欠損を残した暫定予測です"
        if not check["provisional_series"]:
            reasons = list(dict.fromkeys(s["provisional_reason"] for s in check["series"]))
            provisional_reason = (
                "暫定予測できる商品・倉庫がありません。" + "／".join(reasons[:3])
                if reasons else "対象商品がありません。除外条件と取込内容を確認してください"
            )
        return {
            k: v
            for k, v in check.items()
            if k not in {"issues", "daily", "rules", "series", "source_files", "inventory_evidence"}
        } | {
            "last_received_at": last_received,
            "last_successful_import_at": last_success,
            "latest_data_date": check["required_end"],
            "warehouses": sorted({s["warehouse"] for s in check["series"]}),
            "methods": {
                "A": {"enabled": check["normal_series"] > 0, "label": "不足を補充して通常予測"},
                "B": {"enabled": False, "reason": "推定補完は今後対応です（Phase 2）"},
                "C": {
                    "enabled": check["provisional_series"] > 0,
                    "reason": provisional_reason,
                },
            },
        }
