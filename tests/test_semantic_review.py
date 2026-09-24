import asyncio
import json
import httpx

from app import semantic_review as sr


def reviewer_with_response(monkeypatch, payload):
    sr._CACHE.clear()
    real = httpx.AsyncClient
    calls = []
    def handler(request):
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'qwen-instruct-test'}]})
        body = json.loads(request.content)
        calls.append(body)
        result = payload(body) if callable(payload) else payload
        return httpx.Response(200, json={'done_reason': 'stop', 'message': {'content': json.dumps(result)}})
    monkeypatch.setattr(sr.httpx, 'AsyncClient', lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    return sr.SemanticReviewer(), calls


def test_explicit_judgements_preserve_unknown_and_reject_duplicate_ids(monkeypatch):
    def response(body):
        prompt = body['messages'][0]['content']
        if 'A komijn' in prompt:
            return {'judgements': [{'id': 0, 'relation': 'requested_product', 'reason': 'Gewone komijn'}]}
        if 'B kaas' in prompt:
            return {'judgements': [{'id': 0, 'relation': 'requested_product', 'reason': 'Dubbel'},
                                    {'id': 0, 'relation': 'different_product', 'reason': 'Tegenstrijdig'}]}
        return {'judgements': []}
    reviewer, calls = reviewer_with_response(monkeypatch, response)
    result = asyncio.run(reviewer.review({'query': 'komijn'}, ['A komijn', 'B kaas', 'C komijn']))
    assert result['A komijn']['status'] == 'accepted'
    assert result['B kaas']['status'] == 'unreviewed'
    assert result['C komijn']['status'] == 'unreviewed'
    assert all(c['format']['properties']['judgements']['minItems'] == 1 for c in calls)


def test_decisions_are_cached_by_identity_not_list_order(monkeypatch):
    def response(body):
        relation = 'ingredient_or_flavour' if 'B smeerkaas' in body['messages'][0]['content'] else 'requested_product'
        return {'judgements': [{'id': 0, 'relation': relation, 'reason': 'Productsoort gecontroleerd'}]}
    reviewer, calls = reviewer_with_response(monkeypatch, response)
    first = asyncio.run(reviewer.review({'query': 'sambal'}, ['B smeerkaas sambal', 'A sambal']))
    second = asyncio.run(reviewer.review({'query': 'sambal'}, ['A sambal', 'B smeerkaas sambal']))
    assert first == second
    assert len(calls) == 2
    assert second['B smeerkaas sambal']['status'] == 'rejected'


def test_product_form_constraints_do_not_depend_on_model_approval():
    from app.product_identity import form_rejection
    assert form_rejection('komijn', 'Kaptein Smeerkaas Komijn 20+')
    assert form_rejection('knoflook', 'Mutti Polpa Knoflook')
    assert form_rejection('aardappelen', 'Olvarit pompoen-kip-aardappel')
    assert form_rejection('sambal', 'Smeerkaas sambal')
    assert form_rejection('komijn', 'Komijnkaas plakken')
    assert form_rejection('tomaat', 'AH Snoeptomaat') is None
    assert form_rejection('smeerkaas komijn', 'Kaptein Smeerkaas Komijn 20+') is None
