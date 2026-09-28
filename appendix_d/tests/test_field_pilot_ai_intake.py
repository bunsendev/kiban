"""AI suggestions stay local, advisory, and separate from formal ingestion."""

import json

import pytest
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.field_pilot import FieldPilotReadService
from forecast_provider.field_pilot.ai_intake import AiSuggestionUnavailable, suggest_structure
from forecast_provider.field_pilot.inbox_ledger import InboxLedger
from forecast_provider.field_pilot.inbox_processor import InboxProcessor
from forecast_provider.field_pilot.learning_service import LearningService
from forecast_provider.jobs import SqliteRunStore
from tests.test_field_pilot_unified_inbox import _policy, _stage


class _Response:
    def __init__(self, answer):
        self.answer = answer

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _size):
        return json.dumps({"response": json.dumps(self.answer)}).encode()


class _Opener:
    def __init__(self, answer):
        self.answer = answer
        self.request = None

    def open(self, request, timeout):
        self.request = request
        assert timeout <= 20
        assert request.full_url == "http://127.0.0.1:11434/api/generate"
        return _Response(self.answer)


def test_local_ai_receives_metadata_only_and_cannot_finalize():
    opener = _Opener({"kind": "WAREHOUSE_INVENTORY",
                      "columns": {"quantity": "箱数"}, "unit_hint": "UNKNOWN"})
    result = suggest_structure({"headers": ["箱数", "倉庫"],
                                "value_types": {"箱数": "NUMBER"}}, "local-model",
                               opener=opener)
    payload = json.loads(opener.request.data)
    assert "原本の秘密値" not in json.dumps(payload, ensure_ascii=False)
    assert payload["stream"] is False
    assert result == {"source": "LOCAL_AI", "kind": "WAREHOUSE_INVENTORY",
                      "columns": {"quantity": "箱数"}, "unit_hint": "UNKNOWN",
                      "needs_review": True}


def test_ai_cannot_invent_column_or_unit():
    for answer in (
        {"kind": "WAREHOUSE_INVENTORY", "columns": {"jan": "架空JAN"},
         "unit_hint": "UNKNOWN"},
        {"kind": "WAREHOUSE_INVENTORY", "columns": {}, "unit_hint": "PIECE"},
    ):
        with pytest.raises(AiSuggestionUnavailable):
            suggest_structure({"headers": ["箱数"]}, "local-model",
                              opener=_Opener(answer))


def test_pilot_ai_endpoint_is_optional_and_does_not_change_candidate(tmp_path, monkeypatch):
    _policy(tmp_path)
    root = tmp_path / "Inbox"
    root.mkdir()
    learning = LearningService(root, tmp_path / "inbox-policy.json")
    day = _policy(tmp_path)[1]
    _stage(root, "extra.csv", f"day,warehouse,cases,note\n{day},EAST,4,x\n".encode())
    InboxProcessor(root, learning.recognition_policy(),
                   InboxLedger(root / "inbox.sqlite3"),
                   review_observer=learning.consider).scan()
    cid = learning.pending_view()["candidates"][0]["candidate_id"]
    service = FieldPilotReadService(None, tmp_path / "pilot-settings.json",
                                    tmp_path / "inbox-policy.json", root)
    app = create_app(SqliteRunStore(tmp_path / "api.sqlite3"),
                     SqliteCatalogStore(tmp_path / "api.sqlite3"), "api-secret",
                     field_pilot=service)
    client = TestClient(app, base_url="http://127.0.0.1")
    url = f"/api/field-pilot/learning/{cid}/suggest"
    assert client.post(url, json={}).status_code == 503
    monkeypatch.setenv("KIBAN_FIELD_PILOT_AI_MODEL", "local-model")
    monkeypatch.setattr("forecast_provider.field_pilot.learning_service.suggest_structure",
                        lambda structure, model: {"kind": "OTHER", "columns": {},
                                                  "unit_hint": "UNKNOWN", "needs_review": True})
    blocked = client.post(url, json={}, headers={"Origin": "https://elsewhere.test"})
    assert blocked.status_code == 403
    assert client.post(url, json={}).json()["needs_review"] is True
    assert service.learning.pending_view()["candidates"][0]["status"] == "PENDING_OPERATOR"
    assert service.learning.store.active_rules() == ()
