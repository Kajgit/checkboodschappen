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
