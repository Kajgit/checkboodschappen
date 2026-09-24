"""JSON boundary for the same matcher in CPython and browser WebAssembly."""
import json
import math
import re
from .groceries import candidate_decision, quantity_details, purchase_unit, product_intent


def evaluate(data):
    results = []
    intents = {}
    purchase_units = {}
    for entry in data:
        item, product = entry['item'], entry['product']
        # Explicit alternatives are separate intents, not concatenated keywords.
        queries = [part.strip() for part in re.split(r'\s*/\s*|\s+of\s+', item['query']) if part.strip()]
        if not queries:
            results.append({'status': 'rejected', 'reason': 'Productnaam ontbreekt'})
            continue
        decisions = []
        for query in queries:
            alternative = {**item, 'query': query}
            key = json.dumps(alternative, sort_keys=True)
            if key not in intents:
                intents[key] = product_intent(alternative)
            decision = candidate_decision(alternative, product['name'], {
                **product, 'quantity': product.get('package'),
                'unified_category': product.get('category') or product.get('unified_category')}, intent=intents[key], has_managed_profile=True)
            decisions.append({**decision, 'alternative': query})
        decision = next((d for d in decisions if d['status'] == 'accepted'),
                        next((d for d in decisions if d['status'] == 'unreviewed'), decisions[0]))
        quantity = item.get('quantity', 1)
        # The purchase unit depends on the request, never on the candidate.
        # Piece requests can trigger family inference, so do this once per
        # distinct request instead of once for every catalogue candidate.
        unit_key = (item['query'], item.get('unit', 'verpakking'))
        if unit_key not in purchase_units:
            purchase_units[unit_key] = purchase_unit(*unit_key)
        unit = purchase_units[unit_key]
        if not isinstance(quantity, (int, float)) or isinstance(quantity, bool) or not math.isfinite(quantity) or quantity <= 0:
            results.append({'status': 'quantity_unknown', 'reason': 'Ongeldige gevraagde hoeveelheid'})
            continue
        count, amount, dimension, desired, overage = quantity_details(quantity, unit, product.get('package'), product['name'])
        if decision['status'] == 'accepted' and amount is None:
            decision = {**decision, 'status': 'quantity_unknown', 'reason': 'Verpakkingsinhoud ontbreekt of past niet bij de gevraagde eenheid'}
        results.append({**decision, 'packages': count, 'packageAmount': amount,
                        'dimension': dimension, 'desired': desired, 'overage': overage})
    return results


def evaluate_json(text):
    return json.dumps(evaluate(json.loads(text)), ensure_ascii=False, allow_nan=False)


_catalogue = []
_index = {}


_loading = None


def catalogue_batch_json(action, text='[]'):
    """Build in bounded JSON batches; publish only after a complete load."""
    from .product_text import words
    global _catalogue, _index, _loading
    if action == 'begin':
        _loading = ([], {})
    elif action == 'abort':
        _loading = None
    elif action == 'append':
        if _loading is None:
            raise ValueError('Geen actieve catalogusimport')
        products = json.loads(text)
        target, index = _loading
        if not isinstance(products, list) or len(products) > 2000 or len(target) + len(products) > 150000:
            raise ValueError('Ongeldige catalogus')
        offset = len(target)
        for number, product in enumerate(products, offset):
            for word in set(words(product['name'])):
                index.setdefault(word, []).append(number)
        target.extend(products)
    elif action == 'commit':
        if _loading is None:
            raise ValueError('Geen actieve catalogusimport')
        _catalogue, _index = _loading
        _loading = None
    else:
        raise ValueError('Ongeldige catalogusopdracht')
    return json.dumps({'products': len(_catalogue), 'tokens': len(_index)})


def load_catalogue_json(text):
    products = json.loads(text)
    if not isinstance(products, list) or len(products) > 150000:
        raise ValueError('Ongeldige catalogus')
    catalogue_batch_json('begin')
    try:
        for offset in range(0, len(products), 2000):
            catalogue_batch_json('append', json.dumps(products[offset:offset + 2000]))
        return catalogue_batch_json('commit')
    except Exception:
        catalogue_batch_json('abort')
        raise


def match_item_json(text):
    from .groceries import FAMILY_RULES, query_terms
    from .product_text import words, word_matches
    request = json.loads(text)
    item = request['item']
    wanted = set()
    for query in re.split(r'\s*/\s*|\s+of\s+', item['query']):
        if not query.strip():
            continue
        family = product_intent({**item, 'query': query})['family']
        anchors = FAMILY_RULES.get(family, (query_terms(query), ()))[0]
        wanted.update(word for phrase in anchors for word in words(phrase)
                      if word not in {'en', 'de', 'het', 'van', 'met'})
    identifiers = set()
    for token, identifiers_for_word in _index.items():
        if any(word_matches(token, anchor) for anchor in wanted):
            identifiers.update(identifiers_for_word)
    products = [_catalogue[index] for index in sorted(identifiers)] + request.get('extra', [])
    decisions = evaluate([{'item': item, 'product': product} for product in products])
    return json.dumps({'candidates': [dict(product=product, decision=decision)
                                      for product, decision in zip(products, decisions)
                                      if decision['status'] != 'rejected'],
                       'checked': len(products)}, ensure_ascii=False, allow_nan=False)
