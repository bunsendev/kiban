from copy import deepcopy

from test_document_movement import movement_text
from test_document_review import pdf

from portable.api import document_inventory_pdf as adapter
from portable.api.app import create_app
from portable.api.document_inventory_checks import inventory_checks


def report(cells=None):
    text = movement_text()
    prefix = text.splitlines()[-1][:60]
    cells = cells or [('52', '2'), ('', ''), ('52', '2'), ('', ''), ('', '')]
    return ('在庫集計日：2026/10/05 現在 当出 ㈱ムロオ 人工倉庫\n'
            + text.splitlines()[1] + '\n' + prefix
            + ''.join(a.ljust(4) + b.ljust(3) for a, b in cells)
            + '\n (2026/09/21)')


def test_balance_blank_policy_keeps_raw_and_never_approves(monkeypatch):
    monkeypatch.setattr(adapter, 'page_source', lambda *_: (b'', report(), 1))
    result = adapter.extract_inventory(pdf(1))
    check = result['inventory_checks']
    assert check['match'] == 1 and check['mismatch'] == 0
    assert check['field_issues'] == []
    assert result['rows'][0]['case_quantity'] == ''
    assert not result['rows'][0].get('exclude')
    assert result['rows'][1]['case_quantity'] == '52'
    assert check['movement_rows'][0]['cells'][-1] == ['', '']
    normalized = adapter.extract_inventory(pdf(1), blank_current_zero=True)
    assert normalized['rows'][0]['exclude'] is True
    assert normalized['inventory_checks'] == check


def test_signed_adjustment_is_applied_once_in_diagnostic_only(monkeypatch):
    text = report([('94',''), ('',''), ('44',''), ('-26',''), ('24','')])
    monkeypatch.setattr(adapter, 'page_source', lambda *_: (b'', text, 1))
    result = adapter.extract_inventory(pdf(1))
    assert result['inventory_checks']['match'] == 1
    assert result['rows'][0]['case_quantity'] == '24'
    assert result['rows'][1]['case_quantity'] == '44'
    text = text.replace('24 ', '25 ')
    result = adapter.extract_inventory(pdf(1))
    assert result['inventory_checks']['mismatch'] == 1
    assert result['inventory_checks']['movement_rows'][0]['difference'] == -20


def test_invalid_pack_and_date_are_not_silently_certified(monkeypatch):
    text = report().replace('人工品 20', '人工品  0').replace('2026/09/21','2026/02/30')
    monkeypatch.setattr(adapter, 'page_source', lambda *_: (b'', text, 1))
    check = adapter.extract_inventory(pdf(1))['inventory_checks']
    assert check['unverifiable'] == 1
    assert 'source_detail_date' in check['field_issues'][0]['fields']


def test_same_receipt_bucket_retains_both_rows_and_input():
    row = {'kind': 'inventory', 'jan': '4901234567894', 'location': '人工倉庫',
               'product_name': '人工品', 'snapshot': '2026-10-05', 'expiry': '2026-12-23',
               'source_detail_date': '2026-09-21', 'page': '1'}
    rows = [row, {**row, 'page':'2'}, {**row, 'source_detail_date':'2026-09-22'}]
    original = deepcopy(rows)
    result = inventory_checks(rows, [])
    assert result['unchecked'] == 3
    assert len(result['repeated_buckets']) == 1
    assert len(result['repeated_buckets'][0]['rows']) == 2
    assert rows == original


def test_multi_page_local_retry_diagnostics_persist_without_ai(tmp_path, monkeypatch):
    service = create_app(tmp_path/'Data').state.documents
    identifier = service.add('synthetic.pdf', pdf(2))['id']
    monkeypatch.setattr(adapter, 'page_source', lambda *_: (b'', report(), 2))
    first = service.read_local(identifier)
    assert first['extraction']['inventory_checks']['match'] == 2
    assert len(first['extraction']['inventory_checks']['repeated_buckets']) == 1
    monkeypatch.setattr('portable.api.document_intake.page_source',
                        lambda *_: (pdf(1), report(), 2))
    result = service.read(identifier, True, retry=True, page=2)
    checks = result['extraction']['inventory_checks']
    assert checks['match'] == 2 and checks['unchecked'] == 0
    assert [r['page'] for r in checks['movement_rows']] == ['1', '2']
    assert result['approval'] is None
    fresh = create_app(tmp_path/'Data').state.documents.get(identifier)
    assert fresh['extraction']['inventory_checks'] == checks
