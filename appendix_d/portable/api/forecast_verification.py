"""Append-only forecasts and accepted actuals; no guesses from candidate inputs."""

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def now():
    return datetime.now(UTC)


def quantity(value):
    try:
        if value is None or isinstance(value, bool) or str(value).strip() == "":
            raise ValueError("数量が未設定です")
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError("数量は0以上の有限数です")
        return result
    except InvalidOperation as exc:
        raise ValueError("数量の形式を確認してください") from exc


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str)


class ForecastVerification:
    def __init__(self, database):
        self.database = database
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS forecast_versions(source TEXT PRIMARY KEY,payload TEXT);
                CREATE TABLE IF NOT EXISTS actual_imports(id TEXT PRIMARY KEY,payload TEXT);
                CREATE TABLE IF NOT EXISTS actual_values(
                    import_id TEXT,uid TEXT,day TEXT,unit TEXT,scope TEXT,value TEXT,
                    PRIMARY KEY(import_id,uid,day,unit,scope));
                CREATE INDEX IF NOT EXISTS actual_lookup ON actual_values(uid,day,unit,scope);
                CREATE TABLE IF NOT EXISTS edit_policies(id INTEGER PRIMARY KEY,payload TEXT);
            """)

    def connect(self):
        return sqlite3.connect(self.database, timeout=30)

    def capture(self, source, rows, metadata):
        value = {"rows": rows, "metadata": metadata}
        raw = pack(value)
        with self.connect() as db:
            existing = db.execute(
                "SELECT payload FROM forecast_versions WHERE source=?", (source,)
            ).fetchone()
            if existing and existing[0] != raw:
                raise ValueError("保存済みの元予測を上書きできません")
            db.execute("INSERT OR IGNORE INTO forecast_versions VALUES(?,?)", (source, raw))

    def policy(self):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM edit_policies ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return json.loads(row[0]) if row else {"cutoff": None, "timezone": "Asia/Tokyo"}

    def set_policy(self, cutoff, actor, reason):
        if not isinstance(cutoff, str) or len(cutoff) != 5:
            raise ValueError("締め時刻はHH:MMで入力してください")
        time.fromisoformat(cutoff)
        if (
            not isinstance(actor, str)
            or not actor.strip()
            or len(actor) > 100
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 500
        ):
            raise ValueError("確認者と変更理由が必要です（100文字・500文字以内）")
        value = {
            "cutoff": cutoff,
            "actor": actor,
            "reason": reason,
            "at": now().isoformat(),
            "timezone": "Asia/Tokyo",
        }
        with self.connect() as db:
            db.execute("INSERT INTO edit_policies(payload) VALUES(?)", (pack(value),))
        return value

    def import_actuals(self, source, rows, actor):
        # Caller supplies ONLY accepted, identity/unit-confirmed rows.
        validated = []
        seen = set()
        for r in rows:
            day = datetime.fromisoformat(r["day"]).date().isoformat()
            if day > now().astimezone(JST).date().isoformat():
                raise ValueError("未来日の出荷は実績として確定できません")
            key = (r["unique_id"], day, r["unit"], r["scope"])
            if not all(key) or key in seen:
                raise ValueError("実績の対応キーが不足または重複しています")
            seen.add(key)
            validated.append((*key, str(quantity(r["quantity"]))))
        raw = pack({"source": source, "rows": sorted(validated), "actor": actor})
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO actual_imports VALUES(?,?)",
                (digest, pack({"source": source, "actor": actor, "at": now().isoformat()})),
            )
            db.executemany(
                "INSERT OR IGNORE INTO actual_values VALUES(?,?,?,?,?,?)",
                [(digest, *r) for r in validated],
            )
        return digest

    def actual(self, uid, day, unit, scope):
        with self.connect() as db:
            values = db.execute(
                "SELECT value FROM actual_values WHERE uid=? AND day=? AND unit=? AND scope=?",
                (uid, day, unit, scope),
            ).fetchall()
        values = {quantity(r[0]) for r in values}
        return {
            "status": "CONFLICT" if len(values) > 1 else "CONFIRMED" if values else "UNCONFIRMED",
            "quantity": float(next(iter(values))) if len(values) == 1 else None,
            "raw_quantity": str(next(iter(values))) if len(values) == 1 else None,
        }

    def edit_state(self, day, actual_status="UNCONFIRMED", at=None):
        at = (at or now()).astimezone(JST)
        target = datetime.fromisoformat(day).date()
        if target < at.date():
            code = "PAST_CONFIRMED" if actual_status == "CONFIRMED" else "PAST_UNCONFIRMED"
        elif actual_status in {"CONFIRMED", "CONFLICT"}:
            code = "ACTUAL_CONFIRMED" if actual_status == "CONFIRMED" else "ACTUAL_CONFLICT"
        elif target == at.date():
            cutoff = self.policy()["cutoff"]
            code = (
                "CUTOFF_UNSET"
                if cutoff is None
                else (
                    "CLOSED_TODAY"
                    if at.time().replace(tzinfo=None) >= time.fromisoformat(cutoff)
                    else "EDITABLE"
                )
            )
        else:
            code = "EDITABLE"
        reasons = {
            "PAST_CONFIRMED": "過去日・実績確定済みのため数量は変更できません。",
            "PAST_UNCONFIRMED": (
                "過去日・実績未確定です。数量変更ではなく実績データを取り込んでください。"
            ),
            "ACTUAL_CONFIRMED": "実績確定済みのため数量は変更できません。",
            "ACTUAL_CONFLICT": "実績が競合しています。取込元を確認してください。",
            "CUTOFF_UNSET": "当日の締め時刻が未設定のため数量変更を保留しています。",
            "CLOSED_TODAY": "当日の締め時刻を過ぎたため数量は変更できません。",
            "EDITABLE": "未来日または締め前の数量は理由を付けて修正できます。",
        }
        return {"editable": code == "EDITABLE", "code": code, "reason": reasons[code]}

    def sources(self):
        with self.connect() as db:
            return [
                json.loads(raw)["metadata"] | {"source": source}
                for source, raw in db.execute(
                    "SELECT source,payload FROM forecast_versions ORDER BY rowid DESC"
                )
            ]

    def compare(self, source, start=None, end=None, feedback=None):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM forecast_versions WHERE source=?", (source,)
            ).fetchone()
        if not row:
            return {
                "rows": [],
                "count": 0,
                "reason": "FORECAST_HISTORY_MISSING",
                "mae": None,
                "wape": None,
            }
        saved = json.loads(row[0])
        meta = saved["metadata"]
        output = []
        errors = []
        actuals = []
        by_product = defaultdict(list)
        by_day = defaultdict(list)
        excluded = defaultdict(int)
        actual_index = defaultdict(set)
        identities = {p["unique_id"] for p in saved["rows"]}
        with self.connect() as db:
            for uid, day, value in db.execute(
                "SELECT uid,day,value FROM actual_values WHERE unit=? AND scope=?",
                (meta.get("unit") or "", meta.get("scope") or ""),
            ):
                if uid in identities:
                    actual_index[(uid, day)].add(quantity(value))
        for p in saved["rows"]:
            day = str(p["target_date"])[:10]
            if (start and day < start) or (end and day > end):
                continue
            uid = p["unique_id"]
            unit = meta.get("unit")
            scope = meta.get("scope")
            values = actual_index[(uid, day)]
            actual = {
                "status": "CONFLICT"
                if len(values) > 1
                else "CONFIRMED"
                if values
                else "UNCONFIRMED",
                "quantity": float(next(iter(values))) if len(values) == 1 else None,
                "raw_quantity": str(next(iter(values))) if len(values) == 1 else None,
            }
            reason = None
            created = meta.get("created_at")
            if not unit or not scope:
                reason = "IDENTITY_OR_UNIT_UNKNOWN"
            elif not created:
                reason = "FORECAST_TIME_UNKNOWN"
            elif datetime.fromisoformat(created).astimezone(JST).date().isoformat() >= day:
                reason = "RETROSPECTIVE_FORECAST"
            elif actual["status"] != "CONFIRMED":
                reason = "ACTUAL_" + actual["status"]
            try:
                original = quantity(p.get("yhat"))
            except ValueError:
                original = None
                reason = "PREDICTION_MISSING"
            delta = None
            rate = None
            if reason:
                excluded[reason] += 1
            else:
                a = quantity(actual["raw_quantity"])
                error = a - original
                delta = float(error)
                rate = None if original == 0 else float(error / original * 100)
                errors.append(error)
                actuals.append(a)
                by_product[uid].append((error, a))
                by_day[day].append((error, a))
            output.append(
                p
                | {
                    "original_quantity": p.get("yhat"),
                    "adjusted_quantity": (feedback or {}).get((uid, day)),
                    "actual": actual,
                    "error": delta,
                    "error_rate_percent": rate,
                    "excluded_reason": reason,
                    "forecast_created_at": created,
                    "edit_state": self.edit_state(day, actual["status"]),
                }
            )

        def metrics(values):
            if not values:
                return {"count": 0, "mean_error": None, "mae": None, "wape": None}
            es = [e for e, a in values]
            denom = sum(a for e, a in values)
            absolute = sum(abs(e) for e in es)
            return {
                "count": len(es),
                "mean_error": float(sum(es) / len(es)),
                "mae": float(absolute / len(es)),
                "wape": None if denom == 0 else float(absolute / denom * 100),
            }

        return {
            "source": source,
            "metadata": meta,
            "rows": output,
            **metrics(list(zip(errors, actuals, strict=True))),
            "excluded": dict(excluded),
            "total": len(output),
            "by_product": {k: metrics(v) for k, v in by_product.items()},
            "by_day": {k: metrics(v) for k, v in by_day.items()},
            "notice": "元の予測を評価。修正値は集計に使用しません。WAPEの分母は確定実績合計。",
        }
