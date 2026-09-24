"""Auditable source facts for ambiguous catalogue records, never inferred prices.

Verified 2026-09-24 from the retailer's description and ingredient declaration.
An exact retailer, catalogue link and title must match; prepared meals are not
accepted based on the word 'hutspot'. Keep this small evidence set reviewable.
"""
FACTS = {
    ('ah', 'wi80568/ah-hutspot'): ('AH Hutspot', 'https://www.ah.nl/producten/product/wi80568/ah-hutspot'),
    ('ah', 'wi129681/ah-hutspot-grootverpakking'): ('AH Hutspot grootverpakking', 'https://www.ah.nl/producten/product/wi129681/ah-hutspot-grootverpakking'),
}

def enrich_product(retailer, product):
    fact = FACTS.get((retailer, product.get('l')))
    if fact and product.get('n') == fact[0]:
        return {**product, 'unified_category': 'groente',
                'identity_evidence': {'url': fact[1], 'checked': '2026-09-24',
                                      'description': 'Hutspotgroente; 60% wortel, 40% ui'}}
    return product
