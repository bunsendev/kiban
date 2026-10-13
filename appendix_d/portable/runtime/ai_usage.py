"""Local model settings and append-only, metadata-only API cost accounting."""

import calendar
import json
import math
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from forecast_provider.field_pilot.ai_request import CURRENT

PRICE_DATE = "2026-10-13"
PRICES = {
    "gpt-4.1-mini": {
        "label": "GPT-4.1 mini（現在の標準）",
        "input": 0.4,
        "cached": 0.1,
        "write": 0.4,
        "output": 1.6,
    },
    "gpt-6-luna": {
        "label": "GPT-6 Luna（低コスト）",
        "input": 0.1,
        "cached": 0.01,
        "write": 0.125,
        "output": 0.5,
    },
    "gpt-6.1-sol": {
        "label": "GPT-6.1 Sol（精度比較向け）",
        "input": 2.0,
        "cached": 0.1,
        "write": 2.5,
        "output": 10.0,
    },
    "gpt-6-astra": {
        "label": "GPT-6 Astra（難しい帳票の比較用）",
        "input": 10.0,
        "cached": 1.0,
        "write": 12.5,
        "output": 50.0,
    },
}
DEFAULT = {
    "model": "gpt-4.1-mini",
    "yen_per_usd": 150.0,
    "monthly_requests": 240,
    "monthly_budget_yen": 5000.0,
}


def now():
    return datetime.now(ZoneInfo("Asia/Tokyo"))


def counts(response):
    if not isinstance(response, dict):
        return None
    usage = response.get("usage") or {}
    if not isinstance(usage, dict):
        return None
    details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    if not isinstance(details, dict) or not isinstance(output_details, dict):
        return None
    values = {
        "input": usage.get("input_tokens"),
        "output": usage.get("output_tokens"),
        "cached": details.get("cached_tokens", 0),
        "write": details.get("cache_write_tokens", 0),
        "reasoning": output_details.get("reasoning_tokens", 0),
    }
    if any(type(v) is not int or v < 0 for v in values.values()):
        return None
    if (
        values["cached"] + values["write"] > values["input"]
        or values["reasoning"] > values["output"]
    ):
        return None
    return values


def cost(values, rates):
    # Output includes reasoning; do not add reasoning tokens twice.
    return (
        (values["input"] - values["cached"] - values["write"]) * rates["input"]
        + values["cached"] * rates["cached"]
        + values["write"] * rates["write"]
        + values["output"] * rates["output"]
    ) / 1_000_000


class AiUsage:
    def __init__(self, state):
        state.mkdir(parents=True, exist_ok=True)
        self.path = state / "ai-usage.sqlite3"
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (at TEXT, model TEXT, kind TEXT, status TEXT, "
                "elapsed REAL, tokens TEXT, cost_usd REAL, price_date TEXT, rates TEXT)"
            )

    def db(self):
        return sqlite3.connect(self.path, timeout=15)

    def settings(self):
        with self.db() as db:
            row = db.execute("SELECT value FROM settings WHERE id=1").fetchone()
        return {**DEFAULT, **(json.loads(row[0]) if row else {})}

    def save(self, value):
        if not isinstance(value, dict) or value.get("model") not in PRICES:
            raise ValueError("対応するモデルを選んでください")
        result = {key: value.get(key, default) for key, default in DEFAULT.items()}
        for key in ("yen_per_usd", "monthly_budget_yen"):
            number = result[key]
            if (
                type(number) not in (int, float)
                or not math.isfinite(number)
                or not 0 < number <= 1_000_000
            ):
                raise ValueError("為替・予算には正の数を入力してください")
        if (
            type(result["monthly_requests"]) is not int
            or not 1 <= result["monthly_requests"] <= 100_000
        ):
            raise ValueError("月間読取回数は1～100000で入力してください")
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES(1,?)", (json.dumps(result),))
        return result

    def invoke(self, kind, function):
        setting = self.settings()
        context = {"model": setting["model"], "response": None}
        token = CURRENT.set(context)
        started = time.monotonic()
        status = "failed"
        try:
            result = function()
            status = "completed"
            return result
        finally:
            CURRENT.reset(token)
            response = context["response"] or {}
            if not isinstance(response, dict):
                response = {}
            values = counts(response)
            rates = PRICES[setting["model"]]
            # Pricing scope is explicitly standard short-context; don't guess other tiers.
            compatible = response.get("service_tier", "default") in (None, "default", "standard")
            actual_model = response.get("model", setting["model"])
            compatible = compatible and (
                isinstance(actual_model, str)
                and (
                    actual_model == setting["model"]
                    or actual_model.startswith(setting["model"] + "-")
                )
            )
            compatible = compatible and (not values or values["input"] <= 100_000)
            amount = cost(values, rates) if values is not None and compatible else None
            if context.get("sent") or context["response"] is not None:
                self.record(setting["model"], kind, status, started, values, amount, rates)

    def record(self, model, kind, status, started, values, amount, rates):
        with self.db() as db:
            db.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    now().isoformat(),
                    model,
                    kind,
                    status,
                    round(time.monotonic() - started, 3),
                    json.dumps(values),
                    amount,
                    PRICE_DATE,
                    json.dumps(rates),
                ),
            )

    def summary(self, at=None):
        at = at or now()
        settings = self.settings()
        with self.db() as db:
            rows = db.execute(
                "SELECT model,kind,status,elapsed,tokens,cost_usd FROM events "
                "WHERE substr(at,1,7)=?",
                (at.strftime("%Y-%m"),),
            ).fetchall()
        groups = {}
        for model, _kind, status, elapsed, tokens, amount in rows:
            group = groups.setdefault(
                model,
                {
                    "model": model,
                    "calls": 0,
                    "failed": 0,
                    "unknown_cost": 0,
                    "usd": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "elapsed_seconds": 0.0,
                },
            )
            group["calls"] += 1
            group["failed"] += status != "completed"
            group["unknown_cost"] += amount is None
            group["usd"] += amount or 0.0
            group["elapsed_seconds"] += elapsed
            values = json.loads(tokens)
            if values:
                group["input_tokens"] += values["input"]
                group["output_tokens"] += values["output"]
                group["reasoning_tokens"] += values["reasoning"]
        usd = sum(g["usd"] for g in groups.values())
        days = calendar.monthrange(at.year, at.month)[1]
        # Use same-model document samples, otherwise disclose the assumptions.
        samples = [
            (json.loads(tokens), amount)
            for model, kind, status, elapsed, tokens, amount in rows
            if model == settings["model"]
            and kind in ("document", "exclusion-list")
            and amount is not None
        ]
        estimated_input, estimated_output = 6000.0, 5000.0
        basis = "assumed_6000_input_5000_output"
        if samples:
            estimated_input = sum(v["input"] for v, a in samples) / len(samples)
            estimated_output = sum(v["output"] for v, a in samples) / len(samples)
            per_request = sum(a for v, a in samples) / len(samples)
            basis = "this_month_same_model_document_average"
        else:
            per_request = (
                estimated_input * PRICES[settings["model"]]["input"]
                + estimated_output * PRICES[settings["model"]]["output"]
            ) / 1_000_000
        yen = usd * settings["yen_per_usd"]
        return {
            "settings": settings,
            "models": [{"id": k, **v} for k, v in PRICES.items()],
            "price_date": PRICE_DATE,
            "month": at.strftime("%Y-%m"),
            "groups": list(groups.values()),
            "calls": len(rows),
            "unknown_cost": sum(g["unknown_cost"] for g in groups.values()),
            "usd": usd,
            "yen": yen,
            "month_end_yen": yen / at.day * days if rows else None,
            "planned_yen": per_request * settings["monthly_requests"] * settings["yen_per_usd"],
            "estimate_basis": basis,
            "sample_count": len(samples),
            "budget_warning": yen >= settings["monthly_budget_yen"],
            "scope": (
                "このPC・日本時間・標準短文脈料金による税抜概算。"
                "費用不明分・他PCの利用は含みません。"
            ),
        }
