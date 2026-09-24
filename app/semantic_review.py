"""Explicit per-product judgements, independent of retailer, quantity and list IDs."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx

from .product_text import words

OLLAMA_URL = 'http://127.0.0.1:11434'
PROMPT_VERSION = 'identity-1'
logger = logging.getLogger(__name__)
_CACHE: dict[str, dict] = {}


def canonical(value: str) -> str:
    return ' '.join(words(value))


def semantic_intent(item: dict, intent: dict) -> dict:
    return {
        'query': canonical(item.get('query', '')),
        'name': canonical(intent['display_name']),
        'family': intent['family'],
        'attributes': sorted({canonical(str(x)) for x in intent['attributes']}),
        'exclusions': sorted({canonical(str(x)) for x in intent['exclusions']}),
        'mode': intent['match_mode'],
    }


def identity_key(intent: dict, name: str) -> str:
    payload = [PROMPT_VERSION, intent, canonical(name)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def unresolved(reason: str, model: str | None = None) -> dict:
    return {'status': 'unreviewed', 'reason': reason, 'model': model}


class SemanticReviewer:
    """One intent per request, explicit results and no silent fallback approval."""

    def __init__(self, model: str | None = None):
        self.requested_model = model
        self.model: str | None = None
        self._discovered = False
        self.requests: list[dict] = []

    async def _discover(self, client: httpx.AsyncClient):
        if self._discovered:
            return
        self._discovered = True
        response = await client.get('/api/tags', timeout=3)
        response.raise_for_status()
        models = [row['name'] for row in response.json().get('models', []) if row.get('name')]
        if self.requested_model:
            self.model = self.requested_model if self.requested_model in models else None
            return
        # Use the same instruction-tuned model as list interpretation when possible.
        self.model = next((m for m in models if 'qwen' in m.lower() and 'instruct' in m.lower()), None)
        self.model = self.model or next((m for m in models if 'llama3.1:8b' in m.lower()), None)
        self.model = self.model or next((m for m in models if any(x in m.lower() for x in ['qwen','llama','gemma'])), None)

    async def review(self, intent: dict, names: list[str]) -> dict[str, dict]:
        unique = {canonical(name): name for name in sorted(names)}
        result: dict[str, dict] = {}
        try:
            async with httpx.AsyncClient(base_url=OLLAMA_URL, trust_env=False,
                                         timeout=httpx.Timeout(120, connect=3)) as client:
                await self._discover(client)
                if not self.model:
                    return {name: unresolved('Geen geschikt lokaal model beschikbaar') for name in names}
                pending = []
                for key, name in sorted(unique.items()):
                    cache_key = self.model + ':' + identity_key(intent, name)
                    if cache_key in _CACHE:
                        result[key] = dict(_CACHE[cache_key])
                    else:
                        pending.append((key, name, cache_key))
                for start in range(0, len(pending), 1):
                    batch = pending[start:start + 1]
                    rows = [{'id': i, 'name': row[1]} for i, row in enumerate(batch)]
                    schema = {
                        'type': 'object', 'required': ['judgements'], 'additionalProperties': False,
                        'properties': {'judgements': {'type': 'array', 'minItems': len(rows), 'maxItems': len(rows),
                            'items': {'type': 'object', 'additionalProperties': False,
                                'required': ['id', 'relation', 'reason'], 'properties': {
                                    'id': {'type': 'integer', 'enum': list(range(len(rows)))},
                                    'relation': {'type': 'string', 'enum': ['requested_product', 'ingredient_or_flavour', 'different_product', 'different_variant', 'uncertain']},
                                    'reason': {'type': 'string'},
                                }}}}}
                    prompt = '''Beoordeel alle winkelproducten tegenover deze ene boodschappenwens.
Geef voor elk id precies één oordeel en een concrete reden van maximaal acht woorden in het Nederlands.
requested_product: het product zelf is wat gevraagd wordt, eventueel van een ander merk als geen merk gevraagd is.
ingredient_or_flavour: het gevraagde is slechts smaak of ingrediënt van een ander product.
different_product: andere productsoort of bereid gerecht in plaats van ingrediënt.
different_variant: een expliciet gevraagde eigenschap ontbreekt of een uitgesloten variant.
uncertain: de naam biedt onvoldoende informatie.
Beoordeel identiteit, niet hoeveelheden, verpakking, prijs of winkel. Een kruidenmix garam masala is garam masala; kaas met komijn is geen pot komijn. Een gewone pot sambal oelek is sambal. Een zak rauwe hutspotgroenten is peen en ui; een bereide hutspotmaaltijd niet. Biologisch is geen afwijzingsreden tenzij expliciet uitgesloten.
Verzin geen uitsluitingen, dieetwensen of merkvoorkeuren. Beoordeel ieder product afzonderlijk.
''' + json.dumps({'intent': intent, 'products': rows}, ensure_ascii=False)
                    response = await client.post('/api/chat', json={
                        'model': self.model, 'stream': False, 'think': False, 'format': schema,
                        'options': {'temperature': 0, 'num_ctx': 8192, 'num_predict': 500},
                        'messages': [{'role': 'user', 'content': prompt}], 'keep_alive': '15m'})
                    response.raise_for_status()
                    body = response.json()
                    raw = json.loads(body['message']['content'])
                    judgements = raw.get('judgements', [])
                    self.requests.append({'model': self.model, 'intent': intent, 'candidates': rows,
                                          'response': raw, 'done_reason': body.get('done_reason')})
                    by_id: dict[int, list] = {}
                    for row in judgements if isinstance(judgements, list) else []:
                        if isinstance(row, dict) and type(row.get('id')) is int:
                            by_id.setdefault(row['id'], []).append(row)
                    for i, (key, name, cache_key) in enumerate(batch):
                        entries = by_id.get(i, [])
                        decision = unresolved('AI-oordeel ontbreekt of is ongeldig', self.model)
                        if len(entries) == 1 and body.get('done_reason') != 'length':
                            row = entries[0]
                            relation, reason = row.get('relation'), row.get('reason')
                            allowed = schema['properties']['judgements']['items']['properties']['relation']['enum']
                            if relation in allowed and isinstance(reason, str) and reason.strip():
                                status = 'accepted' if relation == 'requested_product' else 'unreviewed' if relation == 'uncertain' else 'rejected'
                                decision = {'status': status, 'relation': relation, 'reason': reason[:240], 'model': self.model}
                                if status != 'unreviewed':
                                    _CACHE[cache_key] = dict(decision)
                        result[key] = decision
        except Exception as exc:
            logger.warning('Productbeoordeling onvolledig: %s', exc)
            self.requests.append({'model': self.model, 'intent': intent, 'error': str(exc)[:200]})
        return {name: result.get(canonical(name), unresolved('AI-controle niet beschikbaar of mislukt', self.model)) for name in names}
