"""Product-form constraints independent of an LLM's judgement.

A lexical hit means a name deserves inspection, not that the ingredient is the
product. These form categories protect that boundary for ordinary groceries.
"""
from functools import lru_cache
from .product_text import phrase_matches, stemmed_words

# Category markers describe the product being sold. Requested categories may
# contain their own markers; otherwise an ingredient/flavour hit is insufficient.
FORMS = (
    ('babyvoeding', ('olvarit', 'babyvoeding', 'maaltijdhapje', 'maanden'), ('baby', 'olvarit', 'babyvoeding')),
    ('kaasproduct', ('smeerkaas', 'roomkaas', 'kaas', 'goudkuipje', 'goudkuip'), ('kaas', 'smeerkaas', 'roomkaas', 'goudkuipje', 'cheddar', 'mozzarella', 'parmezaan')),
    ('bereide maaltijd', ('maaltijd', 'hachee', 'gehaktballen in jus', 'met rookworst', 'kant en klaar'), ('maaltijd', 'kant en klaar', 'hachee')),
    ('soep', ('soep', 'soup'), ('soep', 'soup', 'bouillon')),
    ('saus of spread', ('tapenade', 'spread', 'polpa', 'pastasaus', 'pesto'), ('tapenade', 'spread', 'polpa', 'pastasaus', 'pesto')),
    ('bakkerijproduct', ('brood', 'broodje', 'croissant', 'koek', 'biscuit', 'cake'), ('brood', 'broodje', 'pita', 'croissant', 'koek', 'biscuit', 'cake')),
    ('bereid bijgerecht', ('wafel', 'gratin', 'lachebek', 'friet', 'kroket', 'aardappel anders'), ('wafel', 'gratin', 'lachebek', 'friet', 'kroket', 'aardappel anders')),
    ('bereid vlees', ('gebraden', 'gegaard', 'gegrild', 'vleeswaren'), ('gebraden', 'gegaard', 'gegrild', 'vleeswaren')),
    ('kruiden of bereidingsmix', ('mix voor', 'kruidenmix voor'), ('mix', 'kruidenmix')),
    ('snoep', ('snoep', 'candy', 'gummy', 'gummi', 'chocolade'), ('snoep', 'candy', 'chocolade')),
)


def form_rejection(query: str, candidate: str) -> str | None:
    for category, markers, requested in FORMS:
        if any(phrase_matches(candidate, term) for term in markers) and not any(
                phrase_matches(query, term) for term in requested):
            # 'snoeptomaat' is a vegetable, not candy: the category marker must
            # be a complete word here, not a compound prefix.
            if category == 'snoep':
                from .product_text import words
                if not set(words(candidate)) & set(markers):
                    continue
            return f'Andere productvorm: {category}; een ingrediënt of smaak is onvoldoende'
    return None


# Only explicit wording creates these requirements. Defaults inferred by an
# input model must not invent a brand, fat percentage or dietary restriction.
VARIANTS = (
    ('Griekse yoghurt', ('grieks', 'griekse', 'greek'), ('grieks', 'griekse', 'greek')),
    ('halfvol', ('halfvol', 'halfvolle'), ('halfvol', 'halfvolle')),
    ('vol', ('vol', 'volle'), ('vol', 'volle')),
    ('mager', ('mager', 'magere'), ('mager', 'magere')),
    ('lactosevrij', ('lactosevrij', 'lactofree'), ('lactosevrij', 'lactofree')),
    ('glutenvrij', ('glutenvrij',), ('glutenvrij',)),
    ('biologisch', ('biologisch', 'biologische', 'bio'), ('biologisch', 'biologische', 'bio')),
    ('plantaardig', ('vegan', 'plantaardig', 'plantaardige'), ('vegan', 'plantaardig', 'plantaardige')),
    ('YoFresh', ('yofresh',), ('yofresh',)),
)


def variant_rejection(item: dict, candidate: str) -> str | None:
    from .product_text import words, stem
    import re
    percentages = lambda text: {float(number.replace(',', '.')) for number in re.findall(r'(\d+(?:[.,]\d+)?)\s*%', text)}
    if not percentages(str(item.get('query', ''))).issubset(percentages(candidate)):
        return 'Gevraagd percentage ontbreekt in de productnaam'
    requested_words = {stem(word) for word in words(str(item.get('query', '')))}
    candidate_words = {stem(word) for word in words(candidate)}
    for label, requests, equivalents in VARIANTS:
        if requested_words.intersection(stem(word) for word in requests) and not candidate_words.intersection(
                stem(word) for word in equivalents):
            return f'Gevraagde variant ontbreekt: {label}'
    for requested_brand in requested_brands(str(item.get('query', ''))):
        if not exact_phrase(candidate, requested_brand):
            return f'Gevraagd merk ontbreekt: {requested_brand}'
    brand = item.get('preferred_brand')
    if brand:
        brand_words = tuple(words(str(brand)))
        actual = tuple(words(candidate))
        if not any(actual[start:start + len(brand_words)] == brand_words
                   for start in range(len(actual) - len(brand_words) + 1)):
            return f'Gevraagd merk ontbreekt: {brand}'
    return None


# Independent food groups catch ingredient/flavour hits across *all* families.
# Unlike retrieval, classification never uses arbitrary prefix matching: mayo
# must not classify the brand Casa Mayor as mayonnaise.
PRODUCT_GROUPS = (
    ('dierenvoer', ('kattenvoer', 'hondenvoer', 'dierenvoeding', 'sheba', 'whiskas', 'felix'), ()),
    ('drank', ('bruiswater', 'frisdrank', 'limonade', 'lemonade', 'juice', 'shot', 'groenteshot', 'smoothie', 'thee', 'bier'), ('frisdrank',)),
    ('bakkerij', ('crouton', 'croutons', 'baguette', 'picos', 'cracker', 'crackers', 'tarwe', 'tijger', 'wrap', 'wraps', 'boterhamkorrels'), ('brood', 'broodjes', 'tortillas', 'pitabroodjes')),
    ('vleessnack', ('frikandel', 'bitterbal', 'kroket', 'kipnugget'), ()),
    ('kruidenbereiding', ('dipmix', 'knoflookkruiden', 'kruidenboter'), ()),
    ('tomatenbereiding', ('frito', 'passata', 'gezeefde', 'gepelde', 'gepeld'), ('tomatenpuree', 'passata')),
    ('aardappelgerecht', ('minikriel', 'kriel', 'aardappelen', 'aardappel'), ('aardappelen',)),
    ('spinazie', ('spinazie',), ()),
    ('bonen', ('bonen', 'boon'), ('sperziebonen', 'snijbonen', 'groente')),
    ('vleeswaren', ('flinterdun', 'achterham', 'beenham', 'boterhamworst'), ()),
)


def exact_phrase(text: str, phrase: str) -> bool:
    actual = stemmed_words(text)
    expected = stemmed_words(phrase)
    return bool(expected) and any(actual[start:start + len(expected)] == expected
                                  for start in range(len(actual) - len(expected) + 1))


@lru_cache(maxsize=1024)
def requested_brands(query: str) -> tuple[str, ...]:
    """The explicit brand requirement is constant across catalogue candidates."""
    return tuple(brand for brands in FAMILY_BRANDS.values() for brand in brands
                 if exact_phrase(query, brand))


def identity_rejection(item: dict, name: str, family: str, candidate: dict | None = None) -> str | None:
    if family in {'kipfilet', 'gehakt', 'rundergehakt', 'slavink', 'shoarmavlees',
                  'creme_fraiche', 'boter', 'yoghurt', 'melk', 'kaas',
                  'geraspte_kaas', 'parmezaan', 'kookroom'}:
        substitutes = ('vegan', 'plantaardig', 'plantaardige', 'vegetarisch', 'vegetarische', 'hybride')
        if any(exact_phrase(name, marker) for marker in substitutes) and not any(
                exact_phrase(str(item.get('query', '')), marker) for marker in substitutes):
            return 'Plantaardige of hybride vervanger is niet expliciet gevraagd'
    for label, markers, allowed in PRODUCT_GROUPS:
        if family not in allowed and any(exact_phrase(name, marker) for marker in markers):
            # An explicit request for the group can be reviewed/selected in its
            # own right; an ingredient request cannot silently change category.
            if not any(exact_phrase(str(item.get('query', '')), marker) for marker in markers):
                return f'Andere productcategorie: {label}'
    if candidate:
        category = str(candidate.get('unified_category') or '') + ' ' + str(candidate.get('retailer_category') or '')
        if any(exact_phrase(category, marker) for marker in ('dierenvoer', 'kattenvoer', 'hondenvoer')):
            return 'Broncategorie is dierenvoer'
    return None


# Finite, inspectable vocabulary for automated matches. Unexplained words are
# review evidence, never silently ignored. This is intentionally stricter than
# search: people can still select an unfamiliar brand or type explicitly.
HOUSE_BRANDS = ('ah', 'albert heijn', 'jumbo', 'plus', 'lidl', 'aldi', 'g woon', '1 de beste',
                'de zaanse hoeve', 'oing', 'melkan', 'zuivelmeester', 'milbona', 'bio+',
                'vers voordeel', 'vleeschmeesters', 'slagerskwaliteit', 'deka', 'hoogvliet', 'vomar', 'spar', 'huismerk', 'slagerij')
FAMILY_BRANDS = {
    'pindakaas': ('calve', 'de pindakaaswinkel'),
    'passata': ('mutti', 'cirio', 'heinz', 'del monte'),
    'parmezaan': ('galbani', 'zanetti', 'parmareggio', 'agriform'),
    'gehakt': ('vleeschmeesters',), 'kipfilet': ('vleeschmeesters', 'kipster'),
    'geraspte_kaas': ('milner', 'old amsterdam', 'uniekaas', 'beemster', 'frico'),
    'kaas': ('milner', 'old amsterdam', 'uniekaas', 'beemster', 'frico'),
    'taco_shells': ('santa maria', 'banderos', 'old el paso', 'la fiesta'),
    'tortillas': ('santa maria', 'banderos', 'old el paso'),
    'bouillon': ('maggi', 'knorr', 'kania', 'zonnatura'),
    'groentebouillon': ('maggi', 'knorr', 'kania', 'zonnatura'),
    'tacosaus': ('santa maria', 'banderos', 'old el paso'),
    'komijn': ('silvo', 'verstegen', 'euroma', 'kokki djawa', 'conimex', 'kumar'),
    'garam_masala': ('silvo', 'verstegen', 'euroma', 'santa maria', 'jonnie boer', 'kumar'),
    'kerriepoeder': ('silvo', 'verstegen', 'euroma', 'conimex', 'kokki djawa'),
    'peper': ('silvo', 'verstegen', 'euroma', 'kan ia'),
    'zout': ('jozo', 'ambtman', 'la baleine'),
    'sambal': ('conimex', 'inproba', 'go tan', 'koningsvogel', 'flower brand'),
    'mayonaise': ('calve', 'van wijngaarden', 'zaanse', 'heinz', 'oliehoorn', 'remia'),
    'olijfolie': ('bertolli', 'carbonell', 'monini', 'carapelli', 'la espanola', 'gkazas', 'terra di bari'),
    'boter': ('campina', 'lille', 'president', 'kerrygold', 'lurpak'),
    'kookroom': ('campina', 'president', 'elle et vire'),
    'creme_fraiche': ('campina', 'president', 'oing'),
    'yoghurt': ('campina', 'fage', 'kolios', 'dodoni', 'elinas', 'zuivelhoeve'),
    'melk': ('campina', 'arla'),
    'mais': ('bonduelle', 'hak', 'del monte', 'green giant'),
    'tomatenpuree': ('mutti', 'del monte', 'cirio', 'heinz'),
    'citroensap': ('limochef', 'polenghi', 'sicilia'),
    'kokosmelk': ('fairtrade original', 'go tan', 'conimex', 'aroy d', 'kara', 'suzi wan'),
    'sperziebonen': ('hak', 'bonduelle'),
}
COMMON_LABEL_WORDS = '''bio biologisch biologische vers verse naturel original normaal normale
    voordeel voordeelverpakking kleinverpakking verpakking groot grote klein kleine mini
    kilo kg g gr gram ml cl dl l liter stuk stuks st ca circa per pak zak net pot blik fles
    met zonder en de het van in uit a x s vegan plantaardig plantaardige halal
    duurzaam beter leven ster sterren voordeelverpak natuurlijk natuurlijke fairtrade msc asc'''.split()
FAMILY_LABEL_WORDS = {
    'passata': 'tomaat tomaten gezeefd gezeefde fluweelzacht fluweelzachte di pomodoro fijn',
    'parmezaan': 'dop grattugiato intensita geraspt geraspte geraspte stuk blok parmigiano reggiano',
    'gehakt': 'half om rund runder varken varkens gemengd mager magere vers',
    'kipfilet': 'scharrel boeren mais hele heel borst borstfilet blokjes reepjes',
    'geraspte_kaas': 'gouda goudse jong jonge belegen geraspte geraspt rasp',
    'kaas': 'gouda goudse jong jonge belegen oude oud stuk',
    'taco_shells': 'crunchy crispy shells taco schelpen',
    'tortillas': 'mais tarwe volkoren zacht zachte wraps wrap tortilla tortillas',
    'tomaten': 'roma tros cherry snoep cocktail rood rode mix zoet zoete',
    'aardappelen': 'kruimig kruimige vastkokend vastkokende iets kruim droog kokend los ongeschild tafelaardappelen',
    'knoflook': 'bol bollen tenen roze solo streng',
    'uien': 'ui uien rood rode wit witte geel gele zoet zoete los gesneden',
    'komkommer': 'komkommers los heel hele',
    'sla': 'groen groene rood rode krop little gem romaine ijsberg',
    'avocado': 'avocados hass eetrijp eetrijpe ready to eat',
    'courgette': 'courgettes groen groene geel gele',
    'wortelen': 'bos winter wortel wortelen peen waspeen geschrapt geschrapte',
    'mais': 'crispy korrels knapperig fris zoet zoete sweet corn kolven',
    'peen_en_uien': 'gesneden gewassen wortel wortelen ui uien peen hutspotgroenten',
    'slavink': 'slavinken ambachtelijk ambachtelijke',
    'shoarmavlees': 'kip varken varkens gekruid gekruide reepjes zonvarken',
    'pitabroodjes': 'wit witte volkoren mini',
    'gember': 'los wortel',
    'dille': 'gedroogd gedroogde',
    'komijn': 'zaad zaden gemalen heel hele djinten djintan ground cumin',
    'garam_masala': 'by world spice blend spicemix kruiden kruidenmix gemalen massala',
    'kerriepoeder': 'gemalen mild madras kerriekruiden',
    'peper': 'zwart zwarte wit witte vier seizoenen vierseizoenen korrels gemalen heel hele mild mix',
    'zout': 'jodium gejodeerd fijn fijne grof grove extra tafel zee',
    'tacosaus': 'mild hot pittig pittige',
    'sambal': 'oelek badjak brandal manis extra hot mild kokos',
    'tomatenpuree': 'geconcentreerd geconcentreerde dubbel gecon',
    'citroensap': 'concentraat geconcentreerd',
    'olijfolie': 'extra vierge vergine virgin classico classic mild traditioneel traditionele koken bakken',
    'boter': 'ongezouten gezouten room roomboter',
    'creme_fraiche': 'vet creme fraiche',
    'kookroom': 'vet panna di cucina classic',
    'kokosmelk': 'kokosnoot light romig romige',
    'yoghurt': 'grieks griekse greek stijl style turks turkse bulgaars bulgaarse roer roeryoghurt mager magere halfvol halfvolle vol volle vet naturel romig romige',
    'melk': 'mager magere halfvol halfvolle vol volle houdbaar houdbare',
    'bouillon': 'kip rund groente groenten vlees blokjes blok poeder tabletten',
    'groentebouillon': 'groente groenten blokjes blok poeder tabletten',
    'mayonaise': 'yofresh romig romige mayo mayonaise yoghurt',
    'sperziebonen': 'gebroken heel hele fijn fijne extra',
}


def unexplained_identity(name: str, family: str, aliases: tuple[str, ...], candidate: dict | None = None, query: str = "") -> list[str]:
    import re
    from .product_text import stem, words
    normalized = ' '.join(words(name))
    brands = HOUSE_BRANDS + FAMILY_BRANDS.get(family, ())
    if candidate and candidate.get('brand'):
        brands += (str(candidate['brand']),)
    for brand in sorted(brands, key=len, reverse=True):
        phrase = ' '.join(words(brand))
        normalized = re.sub(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', ' ', normalized)
    known = {stem(word) for word in COMMON_LABEL_WORDS}
    known.update(stem(word) for word in words(query))
    known.update(stem(word) for word in words(family.replace('_', ' ')))
    known.update(stem(word) for alias in aliases for word in words(alias))
    known.update(stem(word) for word in FAMILY_LABEL_WORDS.get(family, '').split())
    return sorted({word for word in words(normalized)
                   if not re.fullmatch(r'\d+(?:kg|g|gr|ml|l|st|m)?\+?', word)
                   and stem(word) not in known})


def requested_modifier_rejection(query: str, candidate: str, aliases: tuple[str, ...]) -> str | None:
    """A broad family never grants permission to erase an explicit qualifier.

    Family nouns can have registered synonyms. Every remaining query word must
    be present in the candidate or handled by an explicit variant equivalence.
    This covers new qualifiers without needing a blacklist of bad products.
    """
    from .product_text import stem, words, word_matches
    wanted = list(words(query))
    consumed = set()
    for alias in aliases:
        phrase = words(alias)
        for start in range(len(wanted) - len(phrase) + 1):
            if phrase and all(stem(a) == stem(b) for a, b in zip(wanted[start:], phrase)):
                consumed.update(range(start, start + len(phrase)))
    handled_variants = {word for _, requests, _ in VARIANTS for phrase in requests for word in words(phrase)}
    actual = words(candidate)
    missing = [word for index, word in enumerate(wanted)
               if index not in consumed and word not in {'en', 'of', 'de', 'het', 'een', 's'}
               and word not in handled_variants and not word.isdigit()
               and not any(word_matches(found, word) for found in actual)]
    return 'Gevraagde kenmerken ontbreken: ' + ', '.join(missing) if missing else None
