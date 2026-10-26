"""Scoped unit confirmation and exception-first review, never formal approval."""

import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime

from .document_ai import DocumentError
from .document_evidence import valid_jan
from .document_quantity import case_quantity

TEMPLATE = "printed-inventory-movement-v3"
COMPONENT_DEFINITION = "bunsen-ball-case-each-v1"
UNITS = {"inventory": "現在ケース / 現在バラ", "shipment": "当出ケース / 当出バラ"}
FIELDS = (
    "kind",
    "jan",
    "product_code",
    "product_name",
    "location",
    "unit",
    "snapshot",
    "date",
    "expiry",
    "source_detail_date",
    "case_quantity",
    "loose_quantity",
    "units_per_case",
    "quantity",
    "case_factor",
    "page",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def stamp(doc):
    return digest([doc["extraction"], doc.get("draft"), doc["cancelled"], doc["approval"]])


def actor_reason(value):
    actor, reason = (str(value.get(k) or "").strip() for k in ("actor", "reason"))
    if not actor or not reason or len(actor) > 100 or len(reason) > 500:
        raise DocumentError("確認者と、単位ルールの確認理由を入力してください")
    return actor, reason


def day(row):
    try:
        return date.fromisoformat(
            row.get("date" if row.get("kind") == "shipment" else "snapshot") or ""
        ).isoformat()
    except (ValueError, TypeError):
        return ""


class DocumentReview:
    def __init__(self, documents):
        self.documents = documents
        with documents.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS document_unit_rules "
                "(version TEXT PRIMARY KEY, contents TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS document_rule_disables "
                "(version TEXT PRIMARY KEY, contents TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS document_review_previews "
                "(id TEXT PRIMARY KEY, contents TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS document_rule_uses (id TEXT PRIMARY KEY, contents TEXT)"
            )

    def rules(self):
        with self.documents.db() as db:
            disabled = {r[0] for r in db.execute("SELECT version FROM document_rule_disables")}
            rows = [
                json.loads(r[0])
                for r in db.execute("SELECT contents FROM document_unit_rules ORDER BY rowid")
            ]
        latest = {digest(r["scope"]): r["version"] for r in rows}
        return [
            {
                **r,
                "active": r["version"] not in disabled,
                "current": latest[digest(r["scope"])] == r["version"],
            }
            for r in rows
        ]

    def disable(self, version, value):
        actor, reason = actor_reason(value)
        if version not in {r["version"] for r in self.rules()}:
            raise DocumentError("ルールが見つかりません")
        event = {
            "version": version,
            "actor": actor,
            "reason": reason,
            "at": datetime.now(UTC).isoformat(),
        }
        with self.documents._read_lock, self.documents.db() as db:
            db.execute(
                "INSERT OR IGNORE INTO document_rule_disables VALUES(?,?)",
                (version, json.dumps(event, ensure_ascii=False)),
            )
        return self.rules()

    def blank_rule_versions(self, extraction, master_version=""):
        """Authorize a whole native read only when every inventory scope matches.

        Missing/changed source scope, an expired rule, or a newer unit-only rule
        leaves blanks untouched. This is extraction policy, never adoption.
        Caller holds the document read lock, also used by rule apply/disable.
        """
        if extraction.get("model") != TEMPLATE:
            return []
        rows = [r for r in extraction.get("rows", []) if r.get("kind") == "inventory"]
        if not rows:
            return []
        rules = [r for r in self.rules() if r["active"] and r["current"]]
        versions = set()
        for row in rows:
            scope = {"template": TEMPLATE, "warehouse": row.get("location"),
                     "master_version": master_version}
            matches = [r for r in rules if r["scope"] == scope
                       and r.get("blank_current_zero") is True
                       and day(row) and day(row) >= r["effective_date"]
                       and row.get("unit") == UNITS["inventory"]]
            if not matches or not row.get("location"):
                return []
            versions.add(matches[-1]["version"])
        return sorted(versions)

    def _document(self, identifier):
        doc = self.documents.get(identifier)
        if not doc["extraction"] or doc["approval"] or doc["cancelled"]:
            raise DocumentError("未承認・読取済みの原本を選んでください")
        return doc

    def blank_rule_error(self, extraction, master_version=""):
        versions = extraction.get("blank_rule_versions") or []
        if versions and (
            extraction.get("blank_rule_master_version", "") != master_version
            or self.blank_rule_versions(extraction, master_version) != versions
        ):
            return "空欄ルールの版・適用条件が変わりました。原本を読み直して確認してください"
        return ""

    def plan(self, identifier, *, master_version="", rows=None):
        doc = self._document(identifier)
        extraction = doc["extraction"]
        source = rows if rows is not None else (doc.get("draft") or extraction)["rows"]
        source = self.documents.exclusions.apply(source)
        rules = [r for r in self.rules() if r["active"] and r["current"]]
        output, applied = [], Counter()
        for index, original in enumerate(source):
            row = dict(original)
            scope = {
                "template": extraction.get("model"),
                "warehouse": row.get("location"),
                "master_version": master_version or row.get("master_version") or "",
            }
            matches = [
                r
                for r in rules
                if r["scope"] == scope
                and day(row)
                and day(row) >= r["effective_date"]
                and not (
                    master_version
                    and row.get("master_version")
                    and row["master_version"] != master_version
                )
                and row.get("unit") == UNITS.get(row.get("kind"))
            ]
            prior = row.get("component_rule_version")
            invalid_prior = bool(prior and prior not in {r["version"] for r in matches})
            if invalid_prior:
                # Keep the invalid reference until explicit manual confirmation;
                # otherwise saving a draft could erase the reason for the hold.
                row.update(component_confirmed=False)
            if (
                matches
                and not row.get("exclude")
                and row.get("component_rule_override") != "manual"
            ):
                rule = matches[-1]
                row.update(component_confirmed=True, component_rule_version=rule["version"])
                applied[rule["version"]] += 1
            # Confirmed business vocabulary is independent of blank/quantity validation.
            # Only the deterministic, recognized source columns inherit this definition.
            originals = extraction.get("rows", [])
            native_columns = (
                extraction.get("model") == TEMPLATE
                and index < len(originals)
                and row.get("kind") in UNITS
                and row.get("unit") == UNITS.get(row.get("kind"))
                and all(row.get(k) == originals[index].get(k) for k in ("unit", "kind"))
            )
            if row.get("component_definition_version") and not native_columns:
                row["component_confirmed"] = False
            row.pop("component_definition_version", None)
            if (
                native_columns
                and not invalid_prior
                and row.get("component_rule_override") != "manual"
            ):
                row.update(
                    component_confirmed=True, component_definition_version=COMPONENT_DEFINITION
                )
            output.append(row)
        statuses = classify(extraction, output)
        blank_error = self.blank_rule_error(extraction, master_version)
        if blank_error:
            for row, status in zip(output, statuses, strict=True):
                if row.get("kind") == "inventory":
                    status.update(status="HOLD", causes=[blank_error, *status["causes"]])
        result = {
            "rows": output,
            "classifications": statuses,
            "counts": dict(Counter(s["status"] for s in statuses)),
            "causes": dict(Counter(c for s in statuses for c in s["causes"])),
            "applied_rules": dict(applied),
            "revision": extraction.get("revision"),
            "native": extraction.get("model") == TEMPLATE,
            "blank_rule_error": blank_error,
            "notice": "機械点検通過は読取正解の保証ではありません。文書承認は別です",
        }
        # This is candidate reuse, not business adoption. Idempotent audit per input/version.
        if applied:
            event = {
                "document_id": identifier,
                "revision": extraction.get("revision"),
                "input_hash": digest(source),
                "output_hash": digest(output),
                "applied_rules": dict(applied),
                "formal_approval": False,
            }
            with self.documents.db() as db:
                db.execute(
                    "INSERT OR IGNORE INTO document_rule_uses VALUES(?,?)",
                    (digest(event), json.dumps(event, ensure_ascii=False)),
                )
        return result

    def preview(self, identifier, value):
        doc = self._document(identifier)
        actor, reason = actor_reason(value)
        rows = value.get("rows")
        if (
            not isinstance(rows, list)
            or not len(doc["extraction"]["rows"]) <= len(rows) <= 1000
            or not all(isinstance(r, dict) for r in rows)
            or value.get("revision") != doc["extraction"].get("revision")
        ):
            raise DocumentError("一覧が更新されています。再表示してください")
        if doc["extraction"].get("model") != TEMPLATE:
            raise DocumentError(
                "保存ルールは対応印刷帳票だけに適用できます。AI原本は個別確認してください"
            )
        master = str(value.get("master_version") or "")
        if master:
            with self.documents.db() as db:
                if not db.execute(
                    "SELECT 1 FROM document_masters WHERE version=?", (master,)
                ).fetchone():
                    raise DocumentError("登録済みマスター版を選んでください")
        warehouses = {r.get("location") for r in rows if not r.get("exclude")}
        if len(warehouses) != 1 or not next(iter(warehouses)):
            raise DocumentError("一括確認は同じ倉庫の原本に限定します")
        warehouse = next(iter(warehouses))
        scope = {"template": TEMPLATE, "warehouse": warehouse, "master_version": master}
        selected = [
            i
            for i, r in enumerate(rows)
            if not r.get("exclude")
            and r.get("unit") == UNITS.get(r.get("kind"))
            and (r.get("master_version") or master) == master
            and day(r)
        ]
        if not selected:
            raise DocumentError("同じ帳票・倉庫・マスター条件の対象行がありません")
        originals = doc["extraction"]["rows"]
        if any(
            i >= len(originals)
            or any(rows[i].get(k) != originals[i].get(k) for k in ("location", "unit", "kind"))
            for i in selected
        ):
            raise DocumentError("原本と異なる倉庫・列の行には保存ルールを作れません")
        try:
            effective = date.fromisoformat(value.get("effective_date") or "").isoformat()
        except (ValueError, TypeError):
            raise DocumentError("適用開始日を確認してください") from None
        if any(day(rows[i]) < effective for i in selected):
            raise DocumentError("原本日付より後のルールは今回適用できません")
        remember = value.get("remember") is True
        blank_zero = value.get("blank_current_zero", False)
        if type(blank_zero) is not bool:
            raise DocumentError("現在欄の空欄ルールを確認してください")
        if blank_zero and (
            not remember
            or doc["extraction"].get("blank_current_policy") != "CURRENT_BLANK_ZERO_EXCLUDE_EMPTY"
        ):
            raise DocumentError("現在欄の空欄＝0で原本を読み直し、次回再利用を選択してください")
        result = {
            "document_id": identifier,
            "stamp": stamp(doc),
            "rows": rows,
            "rows_hash": digest(rows),
            "revision": value["revision"],
            "scope": scope,
            "actor": actor,
            "reason": reason,
            "effective_date": effective,
            "remember": remember,
            "blank_current_zero": blank_zero,
            "indices": selected,
            "rules_hash": digest(self.rules()),
            "at": datetime.now(UTC).isoformat(),
            "changes": (
                "ボール=ケース、バラ=商品1個の列の意味だけを確認。"
                "数量・入数・日付・JANは変更しません"
            ) + ("。次回の一括読取では、この範囲の現在欄の空欄を0とし、"
                 "現在両欄が空欄の在庫明細を除外します。当出は変更しません"
                 if blank_zero else ""),
        }
        key = digest(result)
        with self.documents.db() as db:
            db.execute(
                "INSERT INTO document_review_previews VALUES(?,?)",
                (key, json.dumps(result, ensure_ascii=False)),
            )
        return {k: v for k, v in result.items() if k not in ("rows", "stamp")} | {
            "id": key,
            "target_count": len(selected),
            "skipped_count": len(rows) - len(selected),
        }

    def apply(self, identifier, value):
        with self.documents._read_lock, self.documents.db() as db:
            db.execute("BEGIN IMMEDIATE")
            stored = db.execute(
                "SELECT contents FROM document_review_previews WHERE id=?",
                (value.get("preview_id"),),
            ).fetchone()
            if not stored:
                raise DocumentError("先に対象と変更内容を確認してください")
            preview = json.loads(stored[0])
            doc = self._document(identifier)
            if (
                preview["document_id"] != identifier
                or stamp(doc) != preview["stamp"]
                or digest(value.get("rows")) != preview["rows_hash"]
                or digest(self.rules()) != preview["rules_hash"]
            ):
                raise DocumentError("原本・編集・ルールが変わりました。再度プレビューしてください")
            if value.get("confirmed") is not True:
                raise DocumentError("対象と単位定義を確認してください")
            rows = [dict(r) for r in preview["rows"]]
            rule_version = ""
            if preview["remember"]:
                rule = {k: preview[k] for k in ("scope", "actor", "reason", "effective_date", "at")}
                rule["blank_current_zero"] = preview.get("blank_current_zero") is True
                rule["source_document"] = identifier
                rule["version"] = digest(rule)
                rule_version = rule["version"]
                db.execute(
                    "INSERT OR IGNORE INTO document_unit_rules VALUES(?,?)",
                    (rule_version, json.dumps(rule, ensure_ascii=False)),
                )
            for index in preview["indices"]:
                rows[index]["component_confirmed"] = True
                rows[index]["component_rule_version"] = rule_version
                rows[index]["component_rule_override"] = ""
            draft = {
                "rows": rows,
                "revision": preview["revision"],
                "actor": preview["actor"],
                "at": datetime.now(UTC).isoformat(),
                "unit_preview_id": value["preview_id"],
            }
            db.execute(
                "INSERT INTO document_drafts VALUES(?,?)",
                (identifier, json.dumps(draft, ensure_ascii=False)),
            )
        return {
            "saved": True,
            "rule_version": rule_version,
            "target_count": len(preview["indices"]),
            "formal_approval": False,
        }


def classify(extraction, rows):
    native = extraction.get("model") == TEMPLATE
    coverage = extraction.get("coverage") or {}
    checks = extraction.get("inventory_checks") or {}
    movements = checks.get("movement_rows", [])
    repeated = {r["row"] for g in checks.get("repeated_buckets", []) for r in g["rows"]}
    original = extraction.get("rows", [])
    result, inventory_index = [], -1
    for index, row in enumerate(rows):
        holds, reviews = [], []
        if row.get("kind") == "inventory":
            inventory_index += 1
        if row.get("exclude"):
            result.append(
                {"status": "EXCLUDED", "causes": [] if row.get("reason") else ["除外理由が未入力"]}
            )
            continue
        if not valid_jan(row.get("jan", "")):
            holds.append("商品識別を確認")
        if row.get("kind") not in UNITS or not row.get("location") or not row.get("unit"):
            holds.append("種類・倉庫・単位が不明")
        if not day(row):
            holds.append("基準日・出荷日が不明")
        if row.get("kind") == "inventory":
            for field in ("expiry", "source_detail_date"):
                try:
                    date.fromisoformat(row.get(field) or "")
                except (ValueError, TypeError):
                    (holds if field == "expiry" else reviews).append(
                        "賞味期限が不明" if field == "expiry" else "倉庫入庫日を確認"
                    )
        candidate = {**row, "component_confirmed": True}
        try:
            case_quantity(candidate)
        except DocumentError:
            holds.append("数量・入数・空欄を確認")
        if not row.get("component_confirmed"):
            reviews.append("原本の数量列の対応を確認")
        if not native:
            reviews.append("AI・未対応帳票の原本照合")
        elif not coverage or coverage.get("matched") is not True:
            reviews.append("原本の行構造が未点検")
        if not extraction.get("complete"):
            holds.append("未読取部分あり")
        if not row.get("product_name"):
            reviews.append("商品名を確認")
        if native:
            movement = movements[inventory_index] if 0 <= inventory_index < len(movements) else {}
            if movement.get("status") == "mismatch":
                holds.append("数量収支が不一致")
            elif movement.get("status") != "match":
                reviews.append("数量収支を点検できない")
            if inventory_index + 1 in repeated:
                reviews.append("同条件の複数明細")
        if index >= len(original) or any(
            str(row.get(k) or "") != str(original[index].get(k) or "") for k in FIELDS
        ):
            reviews.append("原本抽出からの編集・追加行")
        result.append(
            {
                "status": "HOLD" if holds else "REVIEW" if reviews else "READY",
                "causes": list(dict.fromkeys(holds + reviews)),
            }
        )
    return result
