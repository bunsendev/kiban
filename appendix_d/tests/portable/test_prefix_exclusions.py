import json
import sqlite3
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.api.document_ai import DocumentError
from portable.api.product_exclusions import ProductExclusions
from portable.runtime.paths import DataPaths


def policy(tmp_path):
    paths = DataPaths(tmp_path/'Data')
    paths.state.mkdir(parents=True)
    return paths, ProductExclusions(paths)


def rule(exclude=True):
    return {'jan':'4901234', 'match_type':'prefix', 'exclude':exclude, 'reason':'人工条件'}


def test_prefix_applies_to_unlisted_valid_jan_not_invalid_or_partial(tmp_path):
    _, store = policy(tmp_path)
    store.save({'actor':'人工', 'products':[rule()]})
    source=[{'jan':jan,'quantity':'12'} for jan in
            ('4901234567894','4901234567900','4901234567895','567894','4911234567893')]
    original=deepcopy(source)
    result=store.apply(source)
    assert result[0]['exclude'] and result[1]['exclude']
    assert all(not r.get('exclude') for r in result[2:])
    assert source==original
    assert result[0]['quantity']=='12'


def test_prefix_release_restores_manual_exclusion_and_exact_rule_remains(tmp_path):
    _, store = policy(tmp_path)
    source=[{'jan':'4901234567894','exclude':True,'reason':'手動保留'}]
    store.save({'actor':'人工','products':[rule()]})
    excluded=store.apply(source)
    store.save({'actor':'人工','products':[rule(False)]})
    restored=store.apply(excluded)[0]
    assert restored['exclude'] and restored['reason']=='手動保留'
    store.save({'actor':'人工','products':[{'jan':source[0]['jan'],'exclude':True,'reason':'個別'}]})
    assert store.apply(source)[0]['reason']=='個別'
    assert len(store.list())==2


def test_v2_seed_import_once_does_not_undo_prefix_release(tmp_path):
    paths, _ = policy(tmp_path)
    seed={'format':'bunsen-product-exclusions-v2','products':[],
          'prefixes':[{'prefix':'4901234','exclude':True,'reason':'人工条件'}]}
    (tmp_path/'対象外商品設定.json').write_text(json.dumps(seed),encoding='utf-8')
    first=ProductExclusions(paths)
    assert first.apply([{'jan':'4901234567894'}])[0]['exclude']
    first.save({'actor':'人工','products':[rule(False)]})
    assert not ProductExclusions(paths).apply([{'jan':'4901234567894'}])[0].get('exclude')


@pytest.mark.parametrize('prefix',['','490123','49012345','４９０１２３４','*','49012 4'])
def test_bad_prefix_rejected_atomically(tmp_path,prefix):
    _, store=policy(tmp_path)
    with pytest.raises(DocumentError):
        store.save({'actor':'人工','products':[
            {'jan':'4901234567894','exclude':True,'reason':'個別'},
            {**rule(),'jan':prefix},
        ]})
    assert store.list()==[]


def test_http_v2_import_list_and_release(tmp_path):
    app=create_app(tmp_path/'Data')
    client=TestClient(app,base_url='http://127.0.0.1')
    seed={'format':'bunsen-product-exclusions-v2','products':[],
          'prefixes':[{'prefix':'4901234','exclude':True,'reason':'人工条件'}]}
    result=client.post('/api/product-exclusions/import',content=json.dumps(seed).encode())
    assert result.status_code==200
    assert result.json()[0]['match_type']=='prefix'
    store=app.state.documents.exclusions
    assert store.apply([{'jan':'4901234567894'}])[0]['exclude']
    client.post('/api/product-exclusions',json={'actor':'人工','products':[rule(False)]}).raise_for_status()
    assert not store.apply([{'jan':'4901234567894'}])[0].get('exclude')
    assert client.get('/api/product-exclusions').json()[0]['exclude']==0


def test_old_exact_database_migration_keeps_prior_events(tmp_path):
    paths=DataPaths(tmp_path/'Data')
    paths.state.mkdir(parents=True)
    with sqlite3.connect(paths.state/'product-exclusions.sqlite3') as db:
        db.execute('CREATE TABLE events '
                   '(jan TEXT,name TEXT,active INTEGER,reason TEXT,actor TEXT,at TEXT)')
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                   ('4901234567894','人工品',1,'旧設定','以前の確認者','2026-10-01'))
    store=ProductExclusions(paths)
    assert store.list()[0]['actor']=='以前の確認者'
    store.save({'actor':'追加確認者','products':[rule()]})
    assert len(store.list())==2
    assert store.apply([{'jan':'4901234567894'}])[0]['exclude']
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==1
