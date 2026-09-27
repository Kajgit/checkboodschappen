"""Transactional browser catalogue ingestion using the shared Python rules."""
import importlib.util
import json
from pathlib import Path
import pytest


def bridge():
    path = Path(__file__).resolve().parents[1] / 'public-site/python/bridge.py'
    spec = importlib.util.spec_from_file_location('app.browser_bridge_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_batches_preserve_positions_duplicates_and_atomic_replacement():
    m = bridge()
    old = [{'name': 'komkommer'}]
    m.load_catalogue_json(json.dumps(old))
    m.catalogue_batch_json('begin')
    m.catalogue_batch_json('append', json.dumps([{'name': 'kokosmelk'}] * 2000))
    assert m._catalogue == old
    m.catalogue_batch_json('append', json.dumps([{'name': 'kokosmelk'}, {'name': 'tortilla'}]))
    result = json.loads(m.catalogue_batch_json('commit'))
    assert result['products'] == 2002
    assert m._index['kokosmelk'] == list(range(2001))
    assert m._index['tortilla'] == [2001]
    m.load_catalogue_json('[]')
    assert m._catalogue == [] and m._index == {}


def test_failed_load_keeps_previous_catalogue_and_discards_staging():
    m = bridge()
    old = [{'name': 'komkommer'}]
    m.load_catalogue_json(json.dumps(old))
    with pytest.raises(KeyError):
        m.load_catalogue_json(json.dumps([{'name': 'kokosmelk'}] * 2000 + [{}]))
    assert m._catalogue == old and m._loading is None
    assert m._index == {'komkommer': [0]}
    with pytest.raises(ValueError):
        m.catalogue_batch_json('commit')


def test_browser_reports_real_contents_independently_of_requested_pack_count():
    m = bridge()
    items = []
    for size in ['250 g', '1 kg', '6 x 1 l', '']:
        items.append({'item': {'query': 'rijst', 'quantity': 2, 'unit': 'verpakking'},
                      'product': {'name': 'Rijst', 'package': size}})
    rows = m.evaluate(items)
    assert [(r['contentsAmount'], r['contentsDimension']) for r in rows] == [
        (250, 'weight'), (1000, 'weight'), (6000, 'volume'), (None, None)]
    assert all(r['packageAmount'] == 1 and r['packages'] == 2 for r in rows)
    assert rows[-1]['packageWarning']


def test_large_pack_label_does_not_hide_a_valid_size_from_store_comparison():
    m = bridge()
    products = [{'name': 'AH Hutspot', 'package': '500 g', 'category': 'groente'},
                {'name': 'AH Hutspot grootverpakking', 'package': '1 kg', 'category': 'groente'}]
    rows = m.evaluate([{'item': {'query': 'hutspot', 'quantity': 1, 'unit': 'verpakking'},
                        'product': p} for p in products])
    assert [r['status'] for r in rows] == ['accepted', 'accepted']
    assert [r['contentsAmount'] for r in rows] == [500, 1000]
    # A requested large pack must still not silently become a different-size small pack.
    specific = m.evaluate([{'item': {'query': 'hutspot grootverpakking', 'quantity': 1, 'unit': 'verpakking'},
                           'product': products[0]}])[0]
    assert specific['status'] != 'accepted'
