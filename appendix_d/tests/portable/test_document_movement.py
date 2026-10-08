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
    assert first['extraction']['model'] == 'printed-inventory-movement-v2'
    assert len(first['extraction']['rows']) == 2
    second = service.read_local(identifier, retry=True)
    assert second['extraction']['revision'] != first['extraction']['revision']
    assert first['extraction']['revision'] in [r['revision'] for r in service.history(identifier)]
