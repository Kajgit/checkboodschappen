"""Shared, conservative word matching for catalogue retrieval and family gates.

Retrieval uses the same matches as the family gate so an accepted name cannot
be lost merely because it is written as a Dutch compound or plural. These are
lexical candidates, not proof that the requested food is the product itself.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache


@lru_cache(maxsize=32768)
def words(text: str) -> tuple[str, ...]:
    folded = unicodedata.normalize('NFKD', text.casefold())
    folded = ''.join(c for c in folded if not unicodedata.combining(c))
    return tuple(re.findall(r'[a-z0-9+]+', folded))


@lru_cache(maxsize=32768)
def stem(word: str) -> str:
    inflections = {"rode": "rood", "witte": "wit", "gele": "geel", "groene": "groen",
                   "zwarte": "zwart", "bruine": "bruin", "biologische": "biologisch",
                   "parmezaanse": "parmezaan", "parmezaans": "parmezaan"}
    word = inflections.get(word, word)
    # Common inflected participles: gedroogde/gedroogd, gerookte/gerookt.
    if len(word) > 5 and word.endswith(("de", "te")) and word.startswith("ge"):
        word = word[:-1]
    # Short words are deliberately not matched inside other words: ui != fruit,
    # sla != slavink, ei != eiwit. Only ordinary inflections are collapsed.
    if len(word) > 4 and word.endswith('en'):
        word = word[:-2]
    elif len(word) > 4 and word.endswith('s') and not word.endswith(('aas', 'aus', 'ees', 'ijs', 'ous')):
        word = word[:-1]
    if word == 'uien':
        return 'ui'
    # Dutch long vowels can shorten before the plural suffix: tomaat/tomaten.
    return re.sub(r'([aeou])\1', r'\1', word) if len(word) >= 4 else word


@lru_cache(maxsize=65536)
def word_matches(actual: str, expected: str) -> bool:
    if actual == expected or stem(actual) == stem(expected):
        return True
    # Broad recall for food compounds, followed by product-identity validation.
    wanted, found = stem(expected), stem(actual)
    return len(expected) >= 4 and len(wanted) >= 3 and (
        found.startswith(wanted) or found.endswith(wanted)
        # Long nouns can sit between compound modifiers and form suffixes,
        # e.g. kippen + bouillon + blokjes. This is recall, not acceptance.
        or (len(wanted) >= 6 and wanted in found)
    )


@lru_cache(maxsize=16384)
def stemmed_words(text: str) -> tuple[str, ...]:
    """Immutable token normalization shared across repeated identity checks."""
    return tuple(stem(word) for word in words(text))


def phrase_matches(text: str, phrase: str) -> bool:
    source, wanted = words(text), words(phrase)
    return bool(wanted) and any(
        all(word_matches(a, b) for a, b in zip(source[start:start + len(wanted)], wanted))
        for start in range(len(source) - len(wanted) + 1)
    )
