from portable.api.document_master import candidates


def master():
    return {'products': [
        {'jan':'4901234012349', 'product_code':'A', 'product_name':'人工商品A', 'cell':'C2'},
        {'jan':'4901241012349', 'product_code':'B', 'product_name':'人工商品B', 'cell':'C3'},
        {'jan':'4901234567894', 'product_code':'C', 'product_name':'人工商品C', 'cell':'C4'},
    ]}


def test_partial_jan_preserves_zero_and_returns_all_suffix_collisions():
    for raw in ['012349', '234012349', '０１２３４９']:
        result = candidates(master(), {'jan':raw})
        assert [p['product_code'] for p in result] == ['A','B']
        assert all(p['match_basis']=='JAN下6桁一致' for p in result)
        assert master()['products'][0]['jan']=='4901234012349'


def test_exact_match_ranks_before_suffix_and_no_invented_prefix():
    result = candidates(master(), {'jan':'4901241012349'})
    assert result[0]['match_basis']=='JAN完全一致' and result[0]['product_code']=='B'
    assert result[1]['match_basis']=='JAN下6桁一致'
    for raw in ['12349','abc012349','012349X','']:
        assert candidates(master(), {'jan':raw}) == []
