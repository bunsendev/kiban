from test_document_review import pdf

from portable.api import document_inventory_pdf as adapter
from portable.api.app import create_app


def movement_text():
    header = ' ' * 60 + 'ケース バラ ' * 5
    cells = [('555', '9'), ('111', '8'), ('239', '6'), ('7', '4'), ('316', '3')]
    line = '4901234567894 人工品 20 26/12/23'.ljust(60)
    line += ''.join(a.ljust(4) + b.ljust(3) for a, b in cells)
    return '在庫集計日：2026/10/05 現在 当出\n' + header + '\n' + line


def test_current_and_out_are_independent(monkeypatch):
    monkeypatch.setattr(adapter, 'page_source', lambda *_: (b'', movement_text(), 1))
    result = adapter.extract_inventory(pdf(1))
    inventory, shipment = result['rows']
    assert (inventory['case_quantity'], inventory['loose_quantity']) == ('316', '3')
    assert (shipment['case_quantity'], shipment['loose_quantity']) == ('239', '6')
    assert inventory['jan'] == shipment['jan'] == '4901234567894'
    assert inventory['product_code'] == shipment['product_code'] == ''
    assert inventory['units_per_case'] == '20'
    assert shipment['date'] == '2026-10-05'
    assert shipment['snapshot'] == shipment['expiry'] == ''


def test_text_report_bypasses_ai_and_reread_retains_history(tmp_path, monkeypatch):
    service = create_app(tmp_path/'Data').state.documents
    identifier = service.add('artificial.pdf', pdf(1))['id']
    monkeypatch.setattr(adapter, 'page_source', lambda *_: (b'', movement_text(), 1))
    monkeypatch.setattr(
        'portable.api.document_intake.page_source', lambda *_: (pdf(1), movement_text(), 1)
    )
    def forbidden(*args, **kwargs):
        raise AssertionError('Text report must not call AI or load a key')
    monkeypatch.setattr('portable.api.document_intake.extract', forbidden)
    monkeypatch.setattr('portable.api.document_intake.ApiCredentials.load', forbidden)
    first = service.read(identifier, True, page=1)
    assert first['extraction']['model'] == 'printed-inventory-movement-v3'
    assert len(first['extraction']['rows']) == 2
    second = service.read_local(identifier, retry=True)
    assert second['extraction']['revision'] != first['extraction']['revision']
    assert first['extraction']['revision'] in [r['revision'] for r in service.history(identifier)]


def test_detail_date_and_blank_current_policy_do_not_change_outbound(monkeypatch):
    text = movement_text()
    line = text.splitlines()[-1]
    # Current both blank, outbound still 239 / 6.
    blank_line = line[:88]
    text = text.rsplit("\n", 1)[0] + "\n" + blank_line + "\n (2026/09/21)"
    monkeypatch.setattr(adapter, "page_source", lambda *_: (b"", text, 1))
    normal = adapter.extract_inventory(pdf(1))
    assert normal["rows"][0]["case_quantity"] == ""
    assert not normal["rows"][0].get("exclude")
    result = adapter.extract_inventory(pdf(1), blank_current_zero=True)
    inventory, shipment = result["rows"]
    assert inventory["source_detail_date"] == "2026-09-21"
    assert inventory["exclude"] is True and inventory["case_quantity"] == "0"
    assert inventory["source_current_case"] == ""
    assert shipment["exclude"] is False
    assert (shipment["case_quantity"], shipment["loose_quantity"]) == ("239", "6")
    assert result["blank_current_policy"] == "CURRENT_BLANK_ZERO_EXCLUDE_EMPTY"


def test_same_jan_expiry_different_detail_dates_are_separate(monkeypatch):
    text = movement_text()
    line = text.splitlines()[-1]
    text += "\n (2026/09/21)\n" + line + "\n (2026/09/22)"
    monkeypatch.setattr(adapter, "page_source", lambda *_: (b"", text, 1))
    inventories = [r for r in adapter.extract_inventory(pdf(1))["rows"] if r["kind"] == "inventory"]
    assert len(inventories) == 2
    assert inventories[0]["jan"] == inventories[1]["jan"]
    assert inventories[0]["expiry"] == inventories[1]["expiry"]
    assert [r["source_detail_date"] for r in inventories] == ["2026-09-21", "2026-09-22"]


def test_current_empty_loose_means_zero_only_for_selected_report_policy(monkeypatch):
    text = movement_text()
    line = text.splitlines()[-1]
    text = text.rsplit("\n", 1)[0] + "\n" + line[:92] + "\n (2026/09/22)"
    monkeypatch.setattr(adapter, "page_source", lambda *_: (b"", text, 1))
    row = adapter.extract_inventory(pdf(1), blank_current_zero=True)["rows"][0]
    assert row["case_quantity"] == "316" and row["loose_quantity"] == "0"
    assert row["source_current_loose"] == "" and not row.get("exclude")


def test_four_row_report_example_retains_three_current_inventory_rows(monkeypatch):
    header = ' ' * 60 + 'ケース バラ ' * 5
    lines = ['在庫集計日：2026/10/05 現在 当出', header]
    for exp, detail, case, loose in [
        ('26/12/23', '2026/09/29', '', ''),
        ('26/12/25', '2026/09/30', '427', '2'),
        ('26/12/28', '2026/10/02', '576', ''),
        ('27/01/02', '2026/10/07', '632', ''),
    ]:
        line = ('4901234567894 人工品 20 ' + exp).ljust(60)
        line += ''.join(a.ljust(4) + b.ljust(3) for a, b in [('', '')]*4+[(case, loose)])
        lines.extend([line, ' (' + detail + ')'])
    monkeypatch.setattr(adapter, 'page_source', lambda *_: (b'', '\n'.join(lines), 1))
    rows = adapter.extract_inventory(pdf(1), blank_current_zero=True)['rows']
    assert len(rows) == 4 and rows[0]['exclude'] is True
    kept = [r for r in rows if not r.get('exclude')]
    assert [(r['case_quantity'], r['loose_quantity']) for r in kept] == [
        ('427', '2'), ('576', '0'), ('632', '0')]
    assert [r['source_detail_date'] for r in kept] == ['2026-09-30','2026-10-02','2026-10-07']
