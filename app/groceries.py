from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from itertools import combinations
from typing import Protocol
import math
import json
import re
import asyncio
import copy
import unicodedata
from datetime import datetime, UTC
from pathlib import Path
from collections import defaultdict
from urllib.parse import quote
import httpx

from .product_identity import form_rejection, variant_rejection, identity_rejection, exact_phrase, unexplained_identity, requested_modifier_rejection
from .product_text import words as product_words, word_matches, phrase_matches


def clean_text(value: str | None) -> str:
    """Normalize pasted shopping text without changing its meaning."""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = "".join(" " if unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"}
                         else char for char in normalized)
    return " ".join(normalized.split()).strip()


def clean_search_query(value: str | None) -> str:
    """Turn a human list line into a provider-friendly product query."""
    text = clean_text(value)
    text = re.sub(r"(?<=[a-zà-ÿ])(?=[A-ZÀ-Ý])", " ", text)
    text = re.sub(r"\b\d+\s*[x×]\s*(?=\d)", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:kg|gr|gram|g|liter|ltr|l|ml|cl|dl|stuks?|x|(?:pak|pakken)|"
        r"verpakking(?:en)?|zak(?:ken)?|pot(?:ten)?|fles(?:sen)?)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bextra\s*verge\b|\bextraverge\b|\bextra\s*virgen\b",
                  "extra vierge", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\d+\s+(?=[^\d\W])", "", text)
    return clean_text(text).strip(" ,-:")


def normalized_words(value: str | None) -> list[str]:
    folded = unicodedata.normalize("NFKD", clean_text(value).lower())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.findall(r"[a-z0-9+]+", folded)


def contains_term(value: str | None, term: str) -> bool:
    """Match a word or phrase, never an arbitrary fragment such as sla in slavink."""
    haystack = " ".join(normalized_words(value))
    needle = " ".join(normalized_words(term))
    return bool(needle and re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack))


def contains_keyword(value: str | None, term: str) -> bool:
    return phrase_matches(clean_text(value), clean_text(term))


@dataclass
class ProductOffer:
    item_id: int
    retailer: str
    product_name: str
    package_price_cents: int
    packages_needed: int = 1
    unit_price: str | None = None
    store_id: str | None = None
    exact_match: bool = False
    loyalty_required: bool = False
    promotion: str | None = None
    valid_until: str | None = None
    product_url: str | None = None
    image_url: str | None = None
    original_price_cents: int | None = None
    promotion_type: str | None = None
    promotion_status: str | None = None
    multi_buy_quantity: int | None = None
    multi_buy_price_cents: int | None = None
    source: str = "onbekend"
    package_amount: float | None = None
    package_dimension: str | None = None
    desired_amount: float | None = None
    delivered_amount: float | None = None
    overage_amount: float | None = None
    match_reason: str = "Productsoort en variant komen overeen"
    confidence: str = "lokaal gecontroleerd"

    @property
    def total_cents(self):
        if self.multi_buy_quantity and self.multi_buy_price_cents and self.multi_buy_quantity > 1:
            groups, remainder = divmod(self.packages_needed, self.multi_buy_quantity)
            return groups * self.multi_buy_price_cents + remainder * self.package_price_cents
        return self.package_price_cents * self.packages_needed

    @property
    def original_total_cents(self):
        return self.original_price_cents * self.packages_needed if self.original_price_cents else None

    @property
    def effective_unit_cents(self):
        return self.total_cents / self.delivered_amount if self.delivered_amount else float("inf")


UNIT_FACTORS = {"g": ("weight", 1), "gram": ("weight", 1), "gr": ("weight", 1), "kilo": ("weight", 1000), "kg": ("weight", 1000),
                "ml": ("volume", 1), "cl": ("volume", 10), "dl": ("volume", 100),
                "l": ("volume", 1000), "liter": ("volume", 1000), "ltr": ("volume", 1000),
                "stuk": ("count", 1), "stuks": ("count", 1), "st": ("count", 1),
                "verpakking": ("package", 1), "verpakkingen": ("package", 1)}

for _unit, _canonical in {"kilogram": "kg", "kilogrammen": "kg", "grammen": "g",
                          "milliliter": "ml", "milliliters": "ml", "centiliter": "cl",
                          "deciliter": "dl", "liters": "liter"}.items():
    UNIT_FACTORS[_unit] = UNIT_FACTORS[_canonical]
AMOUNT_UNITS = "|".join(sorted((re.escape(unit) for unit in UNIT_FACTORS), key=len, reverse=True))


def parse_amount(value: str | None) -> tuple[float, str] | None:
    if not value: return None
    value = str(value)
    if re.fullmatch(r"\s*(?:per\s+)?stuk\s*", value, flags=re.IGNORECASE):
        return 1, "count"
    match = re.search(rf"(?<![\d.,-])(\d+(?:[.,]\d+)?)\s*({AMOUNT_UNITS})\b", value.lower())
    if not match: return None
    number, unit = float(match.group(1).replace(",", ".")), match.group(2)
    multiplier = re.search(r"(\d+)\s*[x×]\s*$", value[:match.start()].lower())
    if multiplier:
        number *= int(multiplier.group(1))
    if number <= 0 or not math.isfinite(number):
        return None
    dimension, factor = UNIT_FACTORS[unit]
    return number * factor, dimension


def packages_for(quantity: float, unit: str, package: str | None) -> int:
    target_info = UNIT_FACTORS.get(unit.lower())
    package_info = parse_amount(package)
    if not target_info or not package_info: return max(1, math.ceil(quantity))
    dimension, factor = target_info
    package_value, package_dimension = package_info
    if dimension != package_dimension or package_value <= 0: return max(1, math.ceil(quantity))
    return max(1, math.ceil(quantity * factor / package_value))


def parse_count_from_name(name: str | None) -> float | None:
    """Infer a pack's piece count when provider metadata is vague or weight-only."""
    if not name:
        return None
    lowered = name.lower().replace("×", "x")
    multiplied = re.search(r"\b(\d+)\s*x\s*\d+(?:[.,]\d+)?\s*(?:kg|g|gram|ml|cl|dl|l|liter)\b", lowered)
    if multiplied:
        return float(multiplied.group(1))
    pieces = re.search(r"\b(\d+)\s*(?:stuks?|st)\b", lowered)
    return float(pieces.group(1)) if pieces else None


def purchase_unit(query: str, unit: str) -> str:
    # A count of this packaged liquid means cans/cartons, never litres.
    # Physical volume/weight requests must not be changed.
    if unit == "stuk" and product_intent({"query": query})["family"] == "kokosmelk":
        return "verpakking"
    return unit


def quantity_details(quantity: float, unit: str, package: str | None,
                     product_name: str | None = None) -> tuple[int, float | None, str | None, float | None, float | None]:
    if unit.lower() in {"verpakking", "verpakkingen"}:
        return max(1, math.ceil(quantity)), 1, "package", quantity, math.ceil(quantity) - quantity
    target_info = UNIT_FACTORS.get(unit.lower())
    name_count = (parse_count_from_name(product_name) or parse_count_from_name(package)) if target_info and target_info[0] == "count" else None
    package_info = (name_count, "count") if name_count else parse_amount(package)
    # A product title can supply missing contents, but never overwrite explicit metadata.
    if package_info is None:
        package_info = parse_amount(product_name)
    if not target_info or not package_info or target_info[0] != package_info[1]:
        return max(1, math.ceil(quantity)), None, None, None, None
    desired = quantity * target_info[1]
    package_amount, dimension = package_info
    packages = max(1, math.ceil(desired / package_amount))
    delivered = package_amount * packages
    return packages, package_amount, dimension, desired, max(0, delivered - desired)


def choose_retailer_options(offers: list[ProductOffer]) -> list[ProductOffer]:
    """Minimize the amount paid for the requested quantity, then break ties."""
    grouped: dict[tuple[int, str], list[ProductOffer]] = {}
    for offer in offers:
        # A large pack is still a valid option when no closer package exists.
        # Dropping it made every basket incomplete for small requests such as
        # 100 g chia seeds or one pointed pepper. Overage remains a tie-breaker.
        grouped.setdefault((offer.item_id, canonical_retailer(offer.retailer)), []).append(offer)
    selected = []
    for candidates in grouped.values():
        exact = [offer for offer in candidates if offer.exact_match]
        if exact:
            candidates = exact
        selected.append(min(candidates, key=lambda offer: (
            offer.total_cents,
            offer.effective_unit_cents,
            offer.overage_amount if offer.overage_amount is not None else float("inf"),
            offer.packages_needed,
            offer.total_cents,
            0 if offer.source == "PrijsProfeet" else 1,
        )))
    return selected


BASIC_PROFILES = {
    "halfvolle melk": {"family": "melk", "attributes": ["halfvol", "normaal"],
                        "exclusions": ["koffiemelk", "yoghurt", "proteïne", "chocolade", "houdbaar", "versfilter"]},
    "bruinbrood": {"family": "brood", "attributes": ["bruin", "heel of half brood"],
                    "exclusions": ["naan", "stokbrood", "broodje", "snack", "knäckebröd", "glutenvrij"]},
    "jonge kaas 48+ stuk": {"family": "kaas", "attributes": ["jong", "48+", "stuk"],
                            "exclusions": ["plakken", "rasp", "blokjes", "smeerkaas", "broodje"]},
    "kipfilet": {"family": "kipfilet", "attributes": ["onbereid", "normaal"],
                  "exclusions": ["vleeswaren", "snack", "gepaneerd", "gekruid", "biologisch"]},
    "witte bolletjes": {"family": "broodjes", "attributes": ["wit", "bolletjes"],
                         "exclusions": ["chocolade", "kaas", "snack", "hamburger"]},
    "geraspte kaas": {"family": "geraspte_kaas", "attributes": ["geraspt", "neutraal"],
                       "exclusions": ["pasta", "pizza", "taco", "tex-mex", "mexicaans", "mozzarella",
                                      "cheddar", "emmentaler", "geiten", "parmezaan", "parrano", "gratin",
                                      "biologisch", "bio ",
                                      "specialiteit"]},
    "komkommer": {"family": "komkommer", "attributes": ["normaal", "heel"],
                   "exclusions": ["mini", "midi", "snack", "snoep", "augurk", "salade", "rauwkost",
                                  "blokjes", "dressing", "spread", "biologisch", "bio ", "zoetzuur"]},
    "wortel": {"family": "wortelen", "attributes": ["normaal", "onbewerkt"],
                "exclusions": ["doperwt", "erwt", "mix", "sap", "shot", "wrap", "baby", "olvarit",
                               "bonbébé", "bonbebe", "maanden", "maaltijd", "menu", "hapje", "puree",
                               "kat", "hond", "gourmet", "baguette", "snack", "sticks", "mais",
                               "extra fijn", "biologisch", "bio "]},
    "ui": {"family": "uien", "attributes": ["normaal", "onbewerkt"],
           "exclusions": ["mix", "jus", "poeder", "saus", "soep", "kruiden", "gehakt"]},
    "slavink": {"family": "slavink", "attributes": ["normaal"],
                 "exclusions": ["mini", "kleinverp", "biologisch", "bio ", "gemarineerd"]},
    "taco's": {"family": "taco_shells", "attributes": ["schelpen"],
                "exclusions": ["saus", "kruidenmix", "chips", "maaltijdpakket"]},
}

# Hard family gates for vague/basic shopping intents. Brands remain free, but a
# shared word may never turn fresh produce into soup, sauce or another product.
FAMILY_RULES = {
    "tomaten": (("tomaat", "tomaten"), ("puree", "soep", "sap", "saus", "ketchup", "passata", "frito", "gedroog", "poeder", "pizza", "kaas", "hummus", "hoemoes", "dip", "mascarpone", "bruschetta")),
    "boter": (("roomboter", "boter"), ("croissant", "biscuit", "koek", "cake", "saus", "aroma",
                                             "puntje", "puntjes", "koekje", "gebak", "sprits", "carree",
                                             "amandelstaaf", "kano", "kano's", "bladerdeeg", "botersla",
                                             "becel", "margarine", "halvarine", "braad", "bakproduct")),
    "yoghurt": (("yoghurt",), ("drink", "ijs", "reep", "muesli", "lactofree", "lactosevrij")),
    "kokosmelk": (("kokosmelk",), ("shampoo", "zeep", "body")),
    "pindakaas": (("pindakaas", "pinda kaas"),
                    ("proteïnereep", "proteine reep", "protein bar", "reep", "snack", "saus", "saté", "sate")),
    "sugarsnaps": (("sugar snap", "sugarsnap", "suikererwt", "peultjes"),
                    ("soep", "saus", "maaltijd", "chips", "baby", "olvarit")),
    "sperziebonen": (("sperzieboon", "sperziebon", "sperziebonen"), ("soep", "saus", "maaltijd", "chips", "baby", "olvarit")),
    "snijbonen": (("snijboon", "snijbon"), ("soep", "saus", "maaltijd", "chips", "baby", "olvarit")),
    "groente": (("sperzieboon", "sperziebon", "snijboon", "snijbon"), ("soep", "saus", "maaltijd", "chips", "baby", "olvarit")),
    "aardappelen": (("aardappel",), ("chips", "puree", "kroket", "salade", "soep", "voorgekookt",
                                          "friet", "schijf", "partjes", "wedges", "rosti", "rösti", "harten", "zoete")),
    "paprika": (("puntpaprika", "zoete paprika", "rode paprika", "paprika rood"), ("poeder", "chips", "saus", "soep", "kruiden")),
    "rundergehakt": (("rundergehakt", "rund gehakt"), ("saus", "burger", "bal", "bereid")),
    "hamburgers": (("hamburger", "runderburger"), ("broodje", "saus", "vega", "kip", "gepaneerd", "mini")),
    "chiazaad": (("chiazaad", "chia zaad"), ("reep", "pudding", "drank")),
    "wijn": (("pinot grigio", "pino grigio"), ("alcoholvrij", "azijn")),
    "frisdrank": (("crystal clear",), ("siroop", "poeder")),
    "komkommer": (("komkommer",), ("mini", "midi", "snack", "snoep", "augurk", "salade",
                                      "rauwkost", "blokjes", "dressing", "spread", "biologisch", "bio ",
                                      "zoetzuur", "smoothie", "drank", "sap")),
    "geraspte_kaas": (("geraspte kaas", "kaas geraspt"),
                        ("pasta", "pizza", "taco", "tex-mex", "mexicaans", "mozzarella", "cheddar",
                         "emmentaler", "geiten", "parmezaan", "parrano", "gratin", "biologisch", "bio ",
                         "specialiteit")),
    "wortelen": (("wortel", "wortelen", "winterwortel", "waspeen", "bospeen"),
                  ("doperwt", "erwt", "mix", "sap", "shot", "wrap", "baby", "olvarit", "bonbébé",
                   "bonbebe", "maanden", "maaltijd", "menu", "hapje", "puree", "kat", "hond",
                   "gourmet", "baguette", "snack", "sticks", "mais", "extra fijn", "biologisch", "bio ",
                   "pot", "blik", "conserven")),
    "peen_en_uien": (("peen en uien", "peen en ui", "hutspotgroente", "hutspot"), ("maaltijd", "stamppot", "rookworst", "hachee", "procureur", "saucijs", "gehaktbal", "runderlap", "kruiden", "mix", "olvarit")),
    "uien": (("ui", "uien"), ("peen", "mix", "jus", "poeder", "saus", "soep", "kruiden", "gehakt",
                                  "aardappel", "spek", "schijf", "maaltijd", "quiche", "pizza")),
    "slavink": (("slavink", "slavinken"),
                 ("mini", "kleinverp", "biologisch", "bio ", "gemarineerd")),
    "taco_shells": (("taco shell", "taco shells", "tacoshell", "tacoshells",
                      "taco schelp", "taco schelpen", "tacoschelp", "tacoschelpen"),
                     ("chips", "saus", "kruidenmix", "seasoning", "snoep", "candy", "gummi", "gummy", "chocolade")),
    "tortillas": (("tortilla", "wrap"), ("chips", "saus", "kruidenmix", "seasoning", "snoep", "candy", "gummi", "gummy", "chocolade")),
    "bouillon": (("bouillon", "kipbouillon", "groentebouillon", "stock cube", "stock pot"),
                 ("soep", "saus", "maaltijd", "fond")),
    "shoarmavlees": (("shoarma",), ("saus", "kruiden", "mix", "pizza", "pita", "sub", "broodje", "maaltijd", "vivera", "vega", "plant")),
    "pitabroodjes": (("pita", "pitabrood", "pitabroodje", "pitabroodjes"),
                     ("chips", "saus", "shoarma", "maaltijd")),
    "kerriepoeder": (("kerrie", "curry powder"),
                     ("saus", "pasta", "maaltijd", "soep", "noedel")),
    "gehakt": (("gehakt",), ("burger", "hamburger", "bal", "saus", "maaltijd", "vegetar", "vegan", "kip", "gegrild", "sate", "saté")),
    "mais": (("mais", "maïs", "sweet corn"),
             ("brood", "flatbread", "bakmix", "mix", "meel", "popcorn", "chips", "snack", "pof", "puff", "baby", "wafel", "geroosterd", "gezouten")),
    "courgette": (("courgette",), ("spaghetti", "noedel", "soep", "saus", "maaltijd", "gegrild")),
    "gember": (("gember",), ("koek", "jam", "thee", "shot", "sap", "bier", "siroop", "snoep", "poeder", "roomkaas", "gemalen", "gehakt", "sushi")),
    "dille": (("dille",), ("saus", "dressing", "mosterd", "chips", "zalm")),
    "peper": (("peper",), ("pepermunt", "pepernoot", "paprika", "adjuma", "madame", "jalape", "chilipeper", "rode peper", "groene peper", "pate", "kaas", "saus", "chips", "drop", "snoep")),
    "zout": (("zout", "zeezout", "tafelzout"),
             ("sticks", "chips", "pinda", "drop", "snoep", "popcorn", "pop corn", "rijstwafel", "kruidenmix",
              "tahin", "cracker", "scrocchi", "koek", "boter",
              "pretzel",
              "0% zout", "zonder zout", "zout toegevoegd", "ongezouten")),
    "knoflook": (("knoflook",), ("saus", "dressing", "brood", "kruidenmix", "poeder", "puree",
                                         "olijf", "olijv", "hummus", "marinade", "picos", "snack")),
    "kookroom": (("kookroom",), ("plantaardig", "soja", "haver", "vegan", "plant", "light", "lactosevrij")),
    "avocado": (("avocado", "avocado's"), ("hummus", "dip", "spread", "olie", "salade")),
    "kipfilet": (("kipfilet", "kip filet"),
                 ("ham", "vleeswaren", "plak", "beleg", "gerookt", "gegaard", "snack", "burger",
                  "schnitzel", "gepaneerd", "gekruid")),
    "eieren": (("eieren", "scharrelei", "scharreleieren", "vrije uitloop ei", "vrije uitloop eieren"), ("salade", "saus", "chocolade-ei")),
    "sla": (("sla", "kropsla", "krop sla", "ijsbergsla", "botersla", "romainesla", "little gem"),
            ("slasaus", "dressing", "melange", "slamix", "gesneden", "gemengd")),
    "kaas": (("kaas", "gouda", "beemster", "zaanlander", "uniekaas"),
             ("geraspt", "rasp", "plakken", "smeer", "blokjes", "broodje", "snack")),
    "brood": (("brood", "witbrood", "bruinbrood", "volkorenbrood", "tarwebrood", "tijgerbrood",
               "vloerbrood", "casino brood", "heel brood", "half brood"),
              ("naan", "turks", "stokbrood", "broodje", "bolletje", "croissant",
                             "cracker", "toast", "wrap", "pita", "glutenvrij", "kokosbrood",
                             "suikerbrood", "krentenbrood", "rozijnenbrood", "ontbijtkoek",
                             "rogge", "maisbrood", "maïsbrood", "broodbeleg", "gehaktbrood")),
}

# Concrete product types and normal catalogue aliases, independent of model output.
FAMILY_RULES.update({
    "misopasta": (("misopasta", "miso pasta", "miso paste"),
                  ("soep", "soup", "ramen", "noedel", "noodle", "marinade", "glaze", "boter", "maaltijd")),
    "creme_fraiche": (("creme fraiche", "crème fraîche"), ("zuurkool", "mix", "chips", "soep", "saus", "maaltijd")),
    "tacosaus": (("tacosaus", "taco saus", "taco sauce"), ("chips", "maaltijd", "kruidenmix")),
    "groentebouillon": (("groentebouillon", "groentenbouillon", "bouillon groente", "bouillonblokjes groente", "groente bouillon"), ("kip", "rund", "vlees", "vis")),
    "garam_masala": (("garam masala", "garam massala"), ("saus", "maaltijd", "kip", "rijst")),
    "komijn": (("komijn", "komijnzaad", "djinten", "djintan"), ("kaas", "plakken", "goudkuip", "cracker", "brood")),
    "sambal": (("sambal",), ("kaas", "chips", "cracker", "maaltijd")),
    "tomatenpuree": (("tomatenpuree", "tomaatpuree", "tomaten puree"), ("soep", "maaltijd")),
    "olijfolie": (("olijfolie", "olijf olie", "olive oil"), ("zeep", "shampoo", "body", "cracker", "chips")),
    "citroensap": (("citroensap", "citroen sap", "lemon juice"), ("frisdrank", "limonade", "siroop", "cocktail")),
    "passata": (("passata", "gezeefde tomaten", "tomaten gezeefd"), ("soep", "pastasaus", "maaltijd", "pizza")),
    "parmezaan": (("parmezaanse kaas", "parmezaan", "parmesan", "parmigiano reggiano"), ("salami", "pasta", "maaltijd", "saus", "snack")),
    "mayonaise": (("mayonaise", "mayo", "yofresh"), ("chips", "maaltijd", "salade")),
})

FAMILY_RULES["tomaten"] = (FAMILY_RULES["tomaten"][0], FAMILY_RULES["tomaten"][1] +
                            ("olvarit", "maanden", "kip rijst", "dip", "polpa", "blokjes",
                             "conserven", "blik", "baby"))


# Explicit noun aliases permit ordinary compounds without also approving their
# unrelated prefix neighbours (e.g. knoflookboter or the brand Mayor).
FAMILY_ALIASES = {
    "gehakt": ("rundergehakt", "varkensgehakt", "half om half gehakt", "gemengd gehakt"),
    "aardappelen": ("bakaardappelen", "tafelaardappelen"),
    "tomaten": ("cherrytomaten", "snoeptomaten", "trostomaten", "romatomaten", "pruimtomaten"),
    "mais": ("maiskorrels", "maiskolf", "mais kolven"),
    "bouillon": ("bouillonblokjes", "kippenbouillon", "runderbouillon", "groentebouillonblok"),
    "groentebouillon": ("groentebouillonblok", "groentebouillonblokjes", "bouillonblokjes groenten"),
    "kerriepoeder": ("kerriepoeder", "kerriekruiden"),
    "knoflook": ("knoflooktenen",),
    "pitabroodjes": ("pita broodjes", "pita brood"),
    "shoarmavlees": ("shoarmavlees", "kipshoarma", "varkensshoarma"),
    "boter": ("roomboter",),
    "peper": ("zwarte peper", "witte peper", "peperkorrels"),
}
for _family, _aliases in FAMILY_ALIASES.items():
    _positive, _negative = FAMILY_RULES[_family]
    FAMILY_RULES[_family] = (_positive + _aliases, _negative)

# Organic production does not make a basic food a different product. Preserve
# explicit user exclusions, but remove these old, automatically invented ones.
LEGACY_PROFILE_EXCLUSIONS = {key: list(profile["exclusions"]) for key, profile in BASIC_PROFILES.items()}
for _profile in BASIC_PROFILES.values():
    _profile["exclusions"] = [term for term in _profile["exclusions"] if term.strip() not in {"bio", "biologisch"}]
for _family, (_positive, _negative) in list(FAMILY_RULES.items()):
    FAMILY_RULES[_family] = (_positive, tuple(term for term in _negative if term.strip() not in {"bio", "biologisch"}))


def infer_profile(text: str) -> dict:
    lowered = clean_text(text).lower()
    if contains_keyword(lowered, "peen en uien"):
        return {}
    for key, profile in BASIC_PROFILES.items():
        if contains_term(lowered, key):
            return profile
    if "halfvolle" in lowered and "melk" in lowered:
        return BASIC_PROFILES["halfvolle melk"]
    if "bruin" in lowered and "brood" in lowered:
        return BASIC_PROFILES["bruinbrood"]
    if "kaas" in lowered and "jong" in lowered and "48+" in lowered:
        return BASIC_PROFILES["jonge kaas 48+ stuk"]
    if "kipfilet" in lowered or "kip filet" in lowered:
        return BASIC_PROFILES["kipfilet"]
    if ("wit" in lowered and ("bollet" in lowered or "bollen" in lowered)):
        return BASIC_PROFILES["witte bolletjes"]
    return {}


def infer_family(text: str) -> str | None:
    """Infer a family only when a positive phrase matches and no exclusion does."""
    matches: list[tuple[int, str]] = []
    for family, (positive, negative) in FAMILY_RULES.items():
        compact = "".join(normalized_words(text))
        if any("".join(normalized_words(term)) in compact for term in negative):
            continue
        matching = [term for term in positive if contains_keyword(text, term)]
        if matching:
            matches.append((max(len(normalized_words(term)) * 100 + len(term) for term in matching), family))
    return max(matches, default=(0, None))[1]


def product_intent(item: dict) -> dict:
    query = clean_text(item.get("query"))
    intent_text = clean_text(f"{query} {item.get('selected_name') or ''}").lower()
    profile = infer_profile(intent_text)
    generic_family = infer_family(intent_text)
    selected = bool(item.get("selected_product_id"))
    mode = item.get("match_mode") or ("exact-met-equivalenten" if selected and item.get("allow_alternatives")
                                       else "strikt-exact" if selected else "basis")
    def decoded(key: str):
        value = item.get(key)
        if isinstance(value, str):
            try: return json.loads(value)
            except Exception: return []
        return value or []
    exclusions = decoded("exclusions_json")
    for key, previous in LEGACY_PROFILE_EXCLUSIONS.items():
        if profile is BASIC_PROFILES[key] and exclusions == previous:
            exclusions = profile["exclusions"]
            break
    stored_family = item.get("product_family")
    known_families = set(FAMILY_RULES) | {p["family"] for p in BASIC_PROFILES.values()}
    family = ((profile.get("family") or generic_family) if stored_family not in known_families
              else stored_family)
    family_repaired = False
    if not item.get("selected_product_id") and profile and profile.get("family") != stored_family:
        family = profile["family"]
        family_repaired = True
    if (not item.get("selected_product_id") and stored_family in FAMILY_RULES
            and not profile and generic_family != stored_family):
        family = generic_family or "overig"
        family_repaired = True
    if any(term in intent_text for term in ("pindakaas", "pinda kaas")): family = "pindakaas"
    if any(term in intent_text for term in ("sugar snap", "sugarsnap", "suikererwt", "peultjes")): family = "sugarsnaps"
    if family == "groente":
        if any(term in intent_text for term in ("sperzieboon", "sperziebon")): family = "sperziebonen"
        elif any(term in intent_text for term in ("snijboon", "snijbon")): family = "snijbonen"
    return {"display_name": clean_text(item.get("display_name") or item.get("selected_name") or query),
            "family": family or profile.get("family") or "overig",
            "attributes": (profile.get("attributes", []) if family_repaired
                           else decoded("attributes_json") or profile.get("attributes", [])),
            "exclusions": exclusions or profile.get("exclusions", []),
            "match_mode": mode, "review_required": bool(item.get("review_required", False))}


def _compatible_intent(item: dict, name: str, candidate: dict | None = None,
                      intent: dict | None = None, has_managed_profile: bool | None = None) -> bool:
    intent = intent or product_intent(item)
    if has_managed_profile is None:
        has_managed_profile = bool(infer_profile(f"{item.get('query', '')} {item.get('selected_name') or ''}"))
    # Managed profiles add attributes and exclusions, but must not disable the
    # positive family gate. That previously allowed taco meal kits to pass as
    # taco shells and made broad lists look complete with the wrong products.
    family_rule = FAMILY_RULES.get(intent["family"])
    if family_rule:
        normalized = name.lower().replace("é", "e").replace("ï", "i")
        positive, negative = family_rule
        if intent["family"] == "zout":
            # A bare occurrence of "zout" usually describes another product
            # (drop, crackers, 0% zout). Require an actual retail salt name.
            positive = ("tafelzout", "zeezout", "jodium zout", "jozo zout", "ambtman tafelzout")
        positive_match = any(exact_phrase(normalized, term) for term in positive)
        if (not positive_match
                or any(clean_text(term).lower() in normalized for term in negative)):
            return False
        return not any(str(excluded).lower() in normalized for excluded in intent["exclusions"] if excluded)
    category_confirms_cheese = bool(intent["family"] == "kaas" and candidate
                                    and candidate.get("unified_category") == "kaas")
    if not category_confirms_cheese and not compatible_product(item.get("query", ""), name, item.get("selected_name")):
        return False
    if category_confirms_cheese:
        lowered = name.lower()
        if "jong" in intent["attributes"] and ("jong" not in lowered or "belegen" in lowered): return False
        if "48+" in intent["attributes"] and "48+" not in lowered: return False
        if "stuk" in intent["attributes"] and any(x in lowered for x in ("plakken", "blokjes", "rasp", "smeer")): return False
    normalized_name = name.lower().replace("é", "e").replace("ï", "i")
    for excluded in intent["exclusions"]:
        term = str(excluded).lower().replace("é", "e").replace("ï", "i")
        if term and term in normalized_name:
            return False
    return True


def candidate_decision(item: dict, name: str, candidate: dict | None = None,
                       intent: dict | None = None, has_managed_profile: bool | None = None) -> dict:
    intent = intent or product_intent(item)
    reason = (identity_rejection(item, name, intent["family"], candidate)
              or variant_rejection(item, name)) or form_rejection(
        f"{item.get('query', '')} {intent['family'].replace('_', ' ')}", name)
    if reason:
        return {"status": "rejected", "reason": reason}
    if not _compatible_intent(item, name, candidate, intent, has_managed_profile):
        return {"status": "rejected", "reason": "Productsoort, gevraagde variant of uitsluiting komt niet overeen"}
    query = clean_search_query(item.get("query"))
    aliases = FAMILY_RULES.get(intent["family"], ((intent["family"].replace("_", " "),), ()))[0]
    modifier_error = requested_modifier_rejection(query, name, aliases)
    if modifier_error:
        return {"status": "rejected", "reason": modifier_error}
    if intent["family"] == "overig":
        # New product types can still be literal, fully explained matches. An
        # unknown type does not justify guessing synonyms or dropping words.
        if not all(exact_phrase(name, word) for word in product_words(query) if word not in {"de", "het", "een", "en"}):
            return {"status": "unreviewed", "reason": "Nieuwe productsoort: geen volledige letterlijke naamovereenkomst"}
        substitutes = ("vegan", "plantaardig", "plantaardige", "vegetarisch", "hybride")
        if any(exact_phrase(name, term) and not exact_phrase(query, term) for term in substitutes):
            return {"status": "unreviewed", "reason": "Nieuwe productsoort met mogelijk een ongevraagde vervanger"}
    if intent["family"] == "peen_en_uien" and exact_phrase(name, "hutspot"):
        category = str((candidate or {}).get("unified_category") or "")
        raw_evidence = any(exact_phrase(name, term) for term in ("peen", "wortel", "ui", "hutspotgroenten"))
        if not raw_evidence and not any(exact_phrase(category, term) for term in ("groente", "groenten")):
            return {"status": "unreviewed", "reason": "Hutspot kan rauwe groente of een bereide maaltijd zijn; bron bevestigt de vorm niet"}
    if intent["family"] == "kipfilet" and candidate:
        contents = parse_amount(candidate.get("s") or candidate.get("quantity")) or parse_amount(name)
        category = str(candidate.get("unified_category") or "") + " " + str(candidate.get("retailer_category") or "")
        if any(exact_phrase(category, term) for term in ("vleeswaren", "broodbeleg")):
            return {"status": "rejected", "reason": "Broncategorie beschrijft vleeswaren, geen onbereide kipfilet"}
        if contents and contents[1] == "weight" and contents[0] < 250 and not exact_phrase(category, "vers vlees"):
            return {"status": "unreviewed", "reason": "Kleine kipfiletverpakking: bron bevestigt niet of dit rauw vlees of broodbeleg is"}
    unknown = unexplained_identity(name, intent["family"], aliases, candidate, query=query)
    if unknown:
        return {"status": "unreviewed", "reason": "Productnaam vraagt controle: " + ", ".join(unknown)}
    return {"status": "accepted", "reason": "Productsoort, variant en naam gecontroleerd met lokale regels"}


def compatible_intent(item: dict, name: str, candidate: dict | None = None,
                      intent: dict | None = None, has_managed_profile: bool | None = None) -> bool:
    return candidate_decision(item, name, candidate, intent, has_managed_profile)["status"] == "accepted"


def match_reason(item: dict, exact: bool = False) -> str:
    if exact: return "Exact gekozen artikel"
    intent = product_intent(item)
    details = ", ".join(intent["attributes"])
    return f"{intent['family']}{': ' + details if details else ''}"


def valid_package_for_intent(item: dict, amount: float | None, dimension: str | None) -> bool:
    target = UNIT_FACTORS.get(str(item.get("unit", "stuk")).lower())
    # Unknown contents cannot be converted into a guaranteed number of pieces,
    # grams or millilitres. Explicit package requests have their own dimension.
    return bool(target and amount is not None and math.isfinite(amount)
                and amount > 0 and dimension == target[0])


INTENTS = {
    "bolletjes": {"positive": ("bol", "broodje", "brood", "wit", "tarwe"),
                   "negative": ("balsem", "snoep", "chocolade", "snack", "soep", "knorr", "aardappel", "kaas", "wafel")},
    "bollen": {"positive": ("bol", "broodje", "brood", "wit", "tarwe"),
                "negative": ("balsem", "soep", "knorr", "aardappel", "kaas", "wafel")},
    "kip": {"positive": ("kipfilet", "kip filet", "kipblok", "kipdij", "kiphaas", "verse kip"),
            "negative": ("noedel", "soep", "bouillon", "chips", "yumyum", "snack", "pizza")},
    "melk": {"positive": ("halfvolle melk", "volle melk", "magere melk", "zuivel"),
             "negative": ("koffiemelk", "chocolade", "koek", "yoghurt", "poeder")},
}

FAMILY_STOPWORDS = {"ah", "plus", "jumbo", "lidl", "dirk", "aldi", "de", "het", "een",
                    "en", "of", "voor", "van", "stuk", "stuks", "pak", "verpakking", "vers", "actie"}

WORD_EQUIVALENTS = {
    "kip": {"kip", "kippen"},
    "ui": {"ui", "uien"}, "uien": {"ui", "uien"},
    "tacoshell": {"tacoshell", "tacoshells", "tacoschelp", "tacoschelpen"},
    "tacoshells": {"tacoshell", "tacoshells", "tacoschelp", "tacoschelpen"},
    "vierge": {"vierge", "vergine"}, "vergine": {"vierge", "vergine"},
}


def query_terms(value: str | None) -> list[str]:
    words = [word for word in normalized_words(clean_search_query(value))
             if not word.isdigit() and word not in FAMILY_STOPWORDS]
    if len(words) > 1:
        words = [word for word in words if word not in {"vlees", "groente", "product", "artikel"}]
    return words


def token_matches(term: str, candidate_words: set[str]) -> bool:
    alternatives = WORD_EQUIVALENTS.get(term, {term})
    return any(word_matches(word, alternative) for alternative in alternatives for word in candidate_words)


def compatible_product(query: str, name: str, selected_name: str | None = None) -> bool:
    """Conservative local product-family check used before comparing prices.

    A missing offer is preferable to comparing milk with coffee creamer or a loaf
    with naan/cheese rolls. The selected product refines the family when the user
    allows equivalents at other retailers.
    """
    q = clean_text(f"{query} {selected_name or ''}").lower()
    n = clean_text(name).lower()
    if "halfvolle" in q and "melk" in q:
        return ("halfvolle" in n and "melk" in n
                and not any(x in n for x in ("koffiemelk", "yoghurt", "chocolade", "choco", "poeder", "drink",
                                               "proteine", "protein", "mini", "multipack", "houdbaar", "houdbare",
                                               "houdb", "houd.", "langlekker", "versfilter",
                                               "biologisch", "bio ", "uht", "lactosevrij", "calcium")))
    if "bruinbrood" in q or ("bruin" in q and "brood" in q):
        return ("bruin" in n and "brood" in n
                and not any(x in n for x in ("broodje", "kaasbrood", "naan", "croissant", "pistolet", "wrap",
                                               "stokbrood", "knackebrood", "knäckebrood", "rozijn", "noten", "swirl",
                                               "glutenvrij")))
    if "tijgerbrood" in q:
        return "tijger" in n and "brood" in n and "balsem" not in n
    if query_terms(query) == ["wortel"]:
        return (any(contains_keyword(n, term) for term in ("wortel", "winterwortel", "waspeen", "bospeen"))
                and not any(x in n for x in ("doperwt", "erwt", "mix", "sap", "shot", "wrap", "baby",
                                               "olvarit", "bonbébé", "bonbebe", "maanden", "maaltijd",
                                               "menu", "hapje", "puree", "kat", "hond", "gourmet",
                                               "baguette", "snack", "sticks", "mais", "extra fijn",
                                               "biologisch", "bio ")))
    if query_terms(query) in (["ui"], ["uien"]):
        return (any(word in {"ui", "uien"} for word in normalized_words(n))
                and not any(x in n for x in ("mix", "jus", "poeder", "saus", "soep", "kruiden", "gehakt")))
    if "slavink" in query_terms(query):
        return (contains_keyword(n, "slavink")
                and not any(x in n for x in ("mini", "kleinverp", "biologisch", "bio ", "gemarineerd")))
    if "geraspte kaas" in q or ("gerasp" in q and "kaas" in q):
        return ("gerasp" in n and "kaas" in n
                and not any(x in n for x in ("pasta", "pizza", "taco", "tex-mex", "mexicaans",
                                               "mozzarella", "cheddar", "emmentaler", "geiten", "parmezaan",
                                               "parrano", "gratin", "biologisch", "bio ", "souffle", "soufflé", "flips",
                                               "chips", "knabbel", "salade", "blokjes")))
    if "kaas" in q:
        if "stuk" in q and any(x in n for x in ("smeerkaas", "plakken", "geraspt", "rasp", "blokjes", "broodje")):
            return False
        if any(x in q for x in ("jonge", "jong ")) and ("jong" not in n or "belegen" in n): return False
        if "48+" in q and "48+" not in n:
            return False
        is_cheese_name = any(term in n for term in ("kaas", "beemster", "zaanlander", "uniekaas"))
        return is_cheese_name and "broodje" not in n
    if re.search(r"\bkip\b", q) or "kipfilet" in q or "kip filet" in q:
        return (("kipfilet" in n or "kip filet" in n)
                and not any(x in n for x in (*INTENTS["kip"]["negative"], "biologisch", "bio ", "knorr",
                                              "gepaneerd", "gekruid", "schnitzel", "vleeswaren", "katten",
                                              "kattenvoer", "vega", "roasted", "flinterdun", "spinazie",
                                              "krieltjes", "pasta", "boursin", "korean", "tuinkruiden",
                                              "ovenschotel", "tomaat", "mozzarella", "blokjes", "gerookt",
                                              "gegrild", "rösti", "sperziebonen", "pepersaus", "peperroom",
                                              "wortel", "doperwt", "erwt", "saus", "americanos", "chili",
                                              "scharrel", "reepjes", "ovengebakken", "aldelis", "meal",
                                              "saté", "sate", "bami", "goreng", "high protein")))
    if "witte bolletjes" in q or "witte bollen" in q:
        return (any(x in n for x in ("witte bol", "witte brood", "wit bol"))
                and not any(x in n for x in ("chocolade", "kaas", "snack", "hamburger")))
    words = query_terms(query)
    candidate_words = set(normalized_words(name))
    return bool(words) and all(token_matches(word, candidate_words) for word in words)


def intent_terms(query: str) -> tuple[str, ...]:
    q = query.lower().strip()
    terms: list[str] = []
    for trigger, rules in INTENTS.items():
        if trigger in q or q in trigger:
            terms.extend(rules["positive"])
    return tuple(terms)


def relevance(query: str, name: str) -> tuple:
    q, n = clean_text(query).lower(), clean_text(name).lower()
    words = query_terms(q)
    candidate_words = set(normalized_words(n))
    coverage = sum(token_matches(word, candidate_words) for word in words)
    exact_phrase = q in n
    positive = negative = 0
    for trigger, rules in INTENTS.items():
        if trigger in q or q in trigger:
            positive += sum(term in n for term in rules["positive"])
            negative += sum(term in n for term in rules["negative"])
    return (-negative, positive, coverage, exact_phrase, -len(n))


class PriceProvider(Protocol):
    async def search(self, item: dict) -> list[ProductOffer]: ...


class RouteProvider(Protocol):
    async def prepare(self, origin: str, stores: list[str]) -> None: ...
    async def trip(self, origin: str, stores: tuple[str, ...]) -> dict: ...


class DemoPriceProvider:
    """Deterministische offline provider; vervangbaar door een gecontroleerde live adapter."""
    async def search(self, item: dict) -> list[ProductOffer]:
        base = max(75, (sum(item["query"].encode("utf-8")) % 450))
        offers = []
        for idx, retailer in enumerate(("Albert Heijn", "Jumbo", "PLUS")):
            price = base + (idx * 37) - ((item["id"] * (idx + 2) * 11) % 80)
            offers.append(ProductOffer(item["id"], retailer, item["query"], price,
                                       packages_needed=max(1, math.ceil(item["quantity"])),
                                       unit_price=f"€ {price / 100:.2f}/{item['unit']}",
                                       store_id=retailer.lower().replace(" ", "-"),
                                       exact_match=bool(item.get("ean")), source="demodata"))
        return offers


class CheckjebonPriceProvider:
    """Downloads the public dataset as a whole; product queries never leave the Mac."""
    URL = "https://www.checkjebon.nl/data/supermarkets.json"
    _official_price_cache: dict[str, tuple[float, int]] = {}

    def __init__(self, cache_path: Path, fallback: PriceProvider | None = None, catalog=None):
        self.cache_path = cache_path
        self.fallback = fallback
        self.catalog = catalog
        self.last_source = "Checkjebon"
        self._memory_data = None
        self._data_lock = asyncio.Lock()
        self.last_diagnostics: dict[int, dict] = {}
        self.source_errors: list[dict] = []
        self._name_indexes: dict[int, dict[str, list[dict]]] = {}

    def _indexed_products(self, supermarket: dict, anchors: list[str]) -> list[dict]:
        """Recall candidates with the same word semantics used by family gates."""
        products = supermarket.get("d", [])
        if not anchors:
            return products
        cache_key = id(supermarket)
        index = self._name_indexes.get(cache_key)
        if index is None:
            built: dict[str, list[dict]] = defaultdict(list)
            for product in products:
                for word in set(product_words(str(product.get("n", "")))):
                    built[word].append(product)
            index = dict(built)
            self._name_indexes[cache_key] = index
        wanted = {word for anchor in anchors for word in product_words(anchor)
                  if word not in {"en", "de", "het", "van", "met"}}
        found, seen = [], set()
        for word, entries in index.items():
            if not any(word_matches(word, anchor) for anchor in wanted):
                continue
            for product in entries:
                marker = id(product)
                if marker not in seen:
                    seen.add(marker)
                    found.append(product)
        return found

    async def _data(self):
        if self._memory_data is not None:
            return self._memory_data
        # A full comparison starts all product searches concurrently. Without
        # this lock every task parsed the multi-megabyte catalogue separately,
        # causing long stalls and occasionally exhausting memory on large lists.
        async with self._data_lock:
            if self._memory_data is not None:
                return self._memory_data
            if self.cache_path.exists():
                age = datetime.now(UTC).timestamp() - self.cache_path.stat().st_mtime
                if age < 24 * 3600:
                    self.last_source = "Checkjebon-cache (maximaal 24 uur oud)"
                    self._memory_data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                    return self._memory_data
            try:
                async with httpx.AsyncClient(timeout=45, follow_redirects=True,
                                             headers={"User-Agent": "BoodschappenWijzer/0.1"}) as client:
                    response = await client.get(self.URL)
                    response.raise_for_status()
                    data = response.json()
                if not isinstance(data, list): raise ValueError("Ongeldig prijsbestand")
                tmp = self.cache_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.cache_path)
                self.last_source = "Checkjebon (actueel opgehaald)"
                self._memory_data = data
                return data
            except Exception as exc:
                self.source_errors = [{"source": "Checkjebon", "error": str(exc)[:160]}]
                if self.cache_path.exists():
                    self.last_source = "Checkjebon-cache (mogelijk verouderd)"
                    self._memory_data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                    return self._memory_data
                if self.fallback:
                    self.last_source = "demodata (prijsbron niet bereikbaar)"
                    return None
                self.last_source = "Checkjebon niet bereikbaar"
                self._memory_data = []
                return []

    @staticmethod
    def _match(products: list[dict], query: str):
        direct = [p for p in products if compatible_product(query, p.get("n", ""))]
        expanded = intent_terms(query)
        extra = [p for p in products if any(term in p.get("n", "").lower() for term in expanded)]
        direct.extend(p for p in extra if p not in direct)
        return max(direct, key=lambda p: (relevance(query, p.get("n", "")), -p.get("p", math.inf)), default=None)

    @staticmethod
    def _product_url(supermarket: dict, product: dict) -> str | None:
        """Return a useful retailer link without pretending placeholder URLs are valid.

        Checkjebon's Dirk base URL contains `/x/x/x/` and its numeric IDs can lag
        behind Dirk's current catalogue. Dirk's own product search is stable and
        lands the user on the current matching product instead.
        """
        retailer = canonical_retailer(supermarket.get("c") or supermarket.get("n", ""))
        name = (product.get("n") or "").strip()
        product_id = str(product.get("l") or "").strip("/")
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if retailer == "Dirk" and name:
            if product_id:
                return f"https://www.dirk.nl/boodschappen/zoeken/producten/{slug}/{quote(product_id, safe='')}"
            return f"https://www.dirk.nl/zoeken/producten/{quote(name, safe='')}"
        if retailer == "DekaMarkt" and name:
            return f"https://www.dekamarkt.nl/zoeken/{quote(name, safe='')}"
        base, link = supermarket.get("u") or "", product.get("l") or ""
        if not base and not link:
            return None
        return base + link

    @classmethod
    def _parse_dirk_price(cls, html: str) -> int | None:
        large = re.search(r'<span class="price-large"[^>]*>(\d+)</span>', html)
        if not large:
            return None
        nearby = html[large.end():large.end() + 400]
        decimals = re.search(r'<span class="price-small"[^>]*>(\d{2})</span>', nearby)
        value = int(large.group(1))
        return value * 100 + int(decimals.group(1)) if decimals else value

    @classmethod
    async def _refresh_official_price(cls, offer: ProductOffer) -> None:
        """Use Dirk's public product page to correct a stale aggregator price."""
        if offer.retailer != "Dirk" or not offer.product_url or "dirk.nl/boodschappen/" not in offer.product_url:
            return
        now = datetime.now(UTC).timestamp()
        cached = cls._official_price_cache.get(offer.product_url)
        if cached and now - cached[0] < 15 * 60:
            offer.package_price_cents, offer.source = cached[1], "Dirk.nl (actueel)"
            return
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                         headers={"User-Agent": "BoodschappenWijzer/0.1"}) as client:
                response = await client.get(offer.product_url)
                response.raise_for_status()
            name_ok = _normal(offer.product_name) in _normal(response.text)
            cents = cls._parse_dirk_price(response.text)
            if not name_ok or cents is None:
                return
            if cents <= 0:
                return
            offer.package_price_cents = cents
            offer.source = "Dirk.nl (actueel)"
            cls._official_price_cache[offer.product_url] = (now, cents)
        except Exception:
            return

    async def search(self, item: dict, *, select: bool = True) -> list[ProductOffer]:
        item = {**item, "unit": purchase_unit(item.get("query", ""), item.get("unit", "stuk"))}
        data = await self._data()
        if data is None:
            return await self.fallback.search(item)
        offers = []
        trace = {"item_id": item["id"], "query": item["query"], "checks": [], "source_errors": list(self.source_errors)}
        self.last_diagnostics[item["id"]] = trace
        is_exact_selection = bool(item.get("selected_product_id"))
        intent = product_intent(item)
        mode = intent["match_mode"]
        has_managed_profile = bool(infer_profile(f"{item.get('query', '')} {item.get('selected_name') or ''}"))
        for supermarket in data:
            retailer = canonical_retailer(supermarket.get("c") or supermarket.get("n", "Onbekend"))
            same_retailer = _normal(retailer) == _normal(item.get("selected_retailer") or "")
            if is_exact_selection and mode == "strikt-exact" and not same_retailer:
                continue
            search_query = (item.get("selected_name") if same_retailer or not item.get("allow_alternatives", True)
                            else item["query"]) or item["query"]
            if is_exact_selection and same_retailer:
                wanted = _normal(item.get("selected_name") or "")
                wanted_id = item.get("selected_product_id", "")
                if wanted_id.startswith("cjb:"):
                    matches = [product for product in supermarket.get("d", [])
                               if f"cjb:{supermarket.get('n', '')}:{product.get('l') or product.get('n')}" == wanted_id]
                else:
                    # A product from another source is exact only when that
                    # source resolves its ID, not merely a matching title.
                    matches = []
            else:
                family_rule = FAMILY_RULES.get(intent["family"])
                anchors = list(family_rule[0]) if family_rule else query_terms(search_query)
                products = self._indexed_products(supermarket, anchors)
                matches = []
                for product in products:
                    from .product_facts import enrich_product
                    evidence = enrich_product(supermarket.get('n', ''), product)
                    decision = candidate_decision(item, product.get("n", ""), evidence, intent, has_managed_profile)
                    trace["checks"].append({"retailer": retailer, "name": product.get("n"),
                                            "package": product.get("s"), "source": "Checkjebon",
                                            "product_id": f"cjb:{supermarket.get('n', '')}:{product.get('l') or product.get('n')}",
                                            "price_cents": round(product["p"] * 100) if isinstance(product.get("p"), (int, float)) and math.isfinite(product["p"]) else None,
                                            "product_url": self._product_url(supermarket, product),
                                            "identity_evidence": evidence.get('identity_evidence'), **decision})
                    if decision["status"] == "accepted":
                        matches.append(product)
                matches.sort(key=lambda product: relevance(search_query, product.get("n", "")), reverse=True)
            for match in matches:
                if not isinstance(match.get("p"), (int, float)) or not math.isfinite(match["p"]) or match["p"] <= .01:
                    trace["checks"].append({"retailer": retailer, "name": match.get("n"), "package": match.get("s"),
                                            "source": "Checkjebon", "status": "source_quality",
                                            "reason": "Prijs ontbreekt, is ongeldig of lijkt een testprijs"})
                    continue
                package = match.get("s")
                exact = bool(is_exact_selection and same_retailer and
                             item.get("selected_product_id") == f"cjb:{supermarket.get('n', '')}:{match.get('l') or match.get('n')}")
                count, amount, dimension, desired, overage = quantity_details(
                    item["quantity"], item.get("unit", "stuk"), package, match.get("n"))
                if not valid_package_for_intent(item, amount, dimension):
                    trace["checks"].append({"retailer": retailer, "name": match.get("n"), "package": package,
                                            "source": "Checkjebon", "status": "quantity_unknown",
                                            "reason": "Verpakkingsinhoud ontbreekt, past niet bij de eenheid of hoeveelheid"})
                    continue
                offers.append(ProductOffer(
                    item_id=item["id"], retailer=retailer,
                    product_name=match.get("n", item["query"]), package_price_cents=round(match["p"] * 100),
                    packages_needed=count, unit_price=package, store_id=supermarket.get("n"),
                    exact_match=exact,
                    product_url=self._product_url(supermarket, match), source="Checkjebon",
                    package_amount=amount, package_dimension=dimension, desired_amount=desired,
                    delivered_amount=amount * count if amount else None, overage_amount=overage,
                    match_reason=match_reason(item, exact)
                ))
        if self.catalog and mode != "strikt-exact":
            try:
                live_offers = await self.catalog.offers(item)
                trace["checks"].extend(getattr(self.catalog, "last_diagnostics", {}).get(item["id"], []))
                offers.extend(live_offers)
            except Exception as exc:
                trace["source_errors"].append({"source": "PrijsProfeet", "error": str(exc)[:160]})
        if item.get("selected_product_id") and self.catalog and not item["selected_product_id"].startswith("cjb:"):
            try:
                exact_offer = await self.catalog.offer(item["selected_product_id"], item)
            except Exception as exc:
                trace["source_errors"].append({"source": "PrijsProfeet", "error": str(exc)[:160]})
                exact_offer = None
            trace["checks"].extend(getattr(self.catalog, "last_exact_diagnostics", {}).get(item["id"], []))
            if exact_offer:
                offers = [offer for offer in offers
                          if not (_normal(offer.retailer) == _normal(exact_offer.retailer) and offer.exact_match)]
                offers.append(exact_offer)
        deduped = {}
        for offer in offers:
            key = (offer.item_id, _normal(offer.retailer), _normal(offer.product_name),
                   parse_amount(offer.unit_price) or clean_text(offer.unit_price).casefold())
            if key not in deduped or offer.source == "PrijsProfeet":
                deduped[key] = offer
        candidates = list(deduped.values())
        trace["accepted_offers"] = len(candidates)
        selected = choose_retailer_options(candidates) if select else candidates
        # Raw candidate collection must not open every Dirk product page.
        # `search_many` refreshes only the final per-store winners below.
        if select:
            for offer in selected:
                await self._refresh_official_price(offer)
        return selected

    async def search_many(self, items: list[dict]) -> list[ProductOffer]:
        """Compare every accepted offer; identity decisions are deterministic.

        Local-model experiments are retained separately for reproducibility.
        A model cannot silently approve, reject or replace catalogue products.
        """
        await self._data()
        self.last_diagnostics = {}
        # Identical requests share one source snapshot, including failures.
        # IDs/display labels cannot affect candidate identity or prices.
        groups: dict[str, list[dict]] = {}
        for item in items:
            identity = {key: value for key, value in item.items()
                        if key not in {"id", "display_name", "created_at"}}
            identity["query"] = " ".join(product_words(str(item.get("query", ""))))
            groups.setdefault(json.dumps(identity, sort_keys=True, default=str), []).append(item)
        async def group_offers(group: list[dict]) -> list[ProductOffer]:
            leader = group[0]
            offers = await self.search(leader, select=False)
            result = list(offers)
            for item in group[1:]:
                result.extend(replace(offer, item_id=item["id"]) for offer in offers)
                trace = copy.deepcopy(self.last_diagnostics.get(leader["id"], {}))
                trace.update(item_id=item["id"], query=item["query"])
                self.last_diagnostics[item["id"]] = trace
            return result
        raw_groups = await asyncio.gather(*(group_offers(group) for group in groups.values()))
        # Compare one consistent set of source prices. Refreshing only a winner
        # afterwards can make it more expensive than a discarded alternative.
        return choose_retailer_options([offer for group in raw_groups for offer in group])

    async def candidates(self, query: str, per_store: int = 3) -> list[dict]:
        data = await self._data()
        if data is None: return []
        found = []
        for supermarket in data:
            compatible = [p for p in supermarket.get("d", []) if compatible_product(query, p.get("n", ""))]
            matches = list(compatible)
            expanded = intent_terms(query)
            extra = [p for p in compatible if any(term in p.get("n", "").lower() for term in expanded)]
            matches.extend(p for p in extra if p not in matches)
            matches.sort(key=lambda p: (relevance(query, p.get("n", "")), -p.get("p", math.inf)), reverse=True)
            for product in matches[:per_store]:
                code = supermarket.get("n", "")
                link = self._product_url(supermarket, product)
                found.append({"product_id": f"cjb:{code}:{product.get('l') or product.get('n')}",
                              "name": product.get("n"), "brand": None, "ean": None,
                              "retailer": canonical_retailer(supermarket.get("c") or code), "price_cents": round(product["p"] * 100),
                              "original_price_cents": None, "quantity": product.get("s"), "unit_price": None,
                              "image_url": None, "product_url": link, "is_promotional": False,
                              "promotion_type": None, "promotion_status": None, "valid_until": None,
                              "loyalty_required": False, "multi_buy_quantity": None, "multi_buy_price_cents": None})
        return found


class PrijsProfeetCatalog:
    BASE = "https://www.prijsprofeet.nl/api/v1"
    RETAILERS = {"albert_heijn": "Albert Heijn", "ah": "Albert Heijn", "jumbo": "Jumbo",
                 "plus": "PLUS", "aldi": "ALDI", "lidl": "Lidl", "dirk": "Dirk",
                 "ekoplaza": "Ekoplaza", "hoogvliet": "Hoogvliet", "dekamarkt": "DekaMarkt", "vomar": "Vomar"}

    def __init__(self):
        self.headers = {"User-Agent": "BoodschappenWijzer/0.1"}
        self.last_diagnostics: dict[int, list[dict]] = {}
        self.last_exact_diagnostics: dict[int, list[dict]] = {}

    @classmethod
    def _retailer(cls, value: str) -> str:
        return canonical_retailer(value)

    @staticmethod
    def _active(p: dict, today: str) -> bool:
        return bool(p.get("is_promotional") and p.get("promotion_status") == "active"
                    and (not p.get("valid_from") or p["valid_from"] <= today)
                    and (not p.get("valid_until") or p["valid_until"] >= today))

    async def search(self, query: str, limit: int | None = 18) -> list[dict]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=self.headers) as client:
            products, page = [], 1
            while True:
                response = await client.get(f"{self.BASE}/products/search/{quote(query, safe='')}",
                                            params={"page_size": min(limit or 100, 100), "page": page})
                response.raise_for_status()
                payload = response.json()
                batch = payload.get("products", [])
                products.extend(batch)
                total = payload.get("total", len(products))
                if limit is not None or len(products) >= total:
                    break
                if not batch or payload.get("page", page) != page:
                    raise ValueError("PrijsProfeet-paginering onvolledig; bron heeft niet alle producten geleverd")
                page += 1
        products.sort(key=lambda p: relevance(query, p.get("name", "")), reverse=True)
        if limit is not None:
            products = products[:limit]
        today = datetime.now(UTC).date().isoformat()
        return [{
            "product_id": p.get("base_product_id") or p["product_id"], "name": p["name"],
            "brand": p.get("brand"), "ean": p.get("ean"), "retailer": self._retailer(p["retailer"]),
            "price_cents": round((p["price"] if self._active(p, today) or not p.get("original_price") else p["original_price"]) * 100),
            "original_price_cents": round(p["original_price"] * 100) if p.get("original_price") else None,
            "quantity": p.get("quantity"), "unit_price": p.get("unit_price"),
            "dietary_tags": p.get("dietary_tags") or [], "private_label": p.get("private_label"),
            "retailer_category": p.get("retailer_category"), "unified_category": p.get("unified_category"),
            "image_url": p.get("image_url"), "product_url": p.get("product_url"),
            "is_promotional": self._active(p, today),
            "promotion_type": p.get("promotion_type"), "promotion_status": p.get("promotion_status"),
            "valid_until": p.get("valid_until"), "loyalty_required": p["retailer"] == "albert_heijn" and p.get("is_promotional", False),
            "multi_buy_quantity": p.get("multi_buy_quantity"),
            "multi_buy_price_cents": round(p["multi_buy_price"] * 100) if p.get("multi_buy_price") else None,
        } for p in products]

    async def offer(self, product_id: str, item: dict) -> ProductOffer | None:
        self.last_exact_diagnostics[item["id"]] = []
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=self.headers) as client:
                response = await client.get(f"{self.BASE}/products/{product_id}")
                response.raise_for_status(); p = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        today = datetime.now(UTC).date().isoformat()
        active = bool(p.get("is_promotional") and p.get("promotion_status") == "active"
                      and (not p.get("valid_from") or p["valid_from"] <= today)
                      and (not p.get("valid_until") or p["valid_until"] >= today))
        price = p.get("price")
        if not active and p.get("original_price"):
            price = p["original_price"]
        count, amount, dimension, desired, overage = quantity_details(
            item["quantity"], item.get("unit", "stuk"), p.get("quantity"), p.get("name"))
        if not valid_package_for_intent(item, amount, dimension):
            self.last_exact_diagnostics[item["id"]].append({
                "source": "PrijsProfeet", "retailer": self._retailer(p["retailer"]),
                "name": p["name"], "package": p.get("quantity"), "product_id": product_id,
                "status": "quantity_unknown", "reason": "Ook voor het exacte artikel is de verpakkingsinhoud onbekend of onverenigbaar",
            })
            return None
        return ProductOffer(
            item_id=item["id"], retailer=self._retailer(p["retailer"]), product_name=p["name"],
            package_price_cents=round(price * 100),
            packages_needed=count,
            unit_price=p.get("quantity"),
            store_id=p["retailer"], exact_match=True, loyalty_required=active and p["retailer"] == "albert_heijn",
            promotion=("Actie" if active else None), valid_until=p.get("valid_until") if active else None,
            product_url=p.get("product_url"), image_url=p.get("image_url"),
            original_price_cents=round(p["original_price"] * 100) if active and p.get("original_price") else None,
            promotion_type=p.get("promotion_type") if active else None,
            promotion_status=p.get("promotion_status"),
            multi_buy_quantity=p.get("multi_buy_quantity") if active else None,
            multi_buy_price_cents=round(p["multi_buy_price"] * 100) if active and p.get("multi_buy_price") else None,
            source="PrijsProfeet", package_amount=amount, package_dimension=dimension,
            desired_amount=desired, delivered_amount=amount * count if amount else None, overage_amount=overage,
            match_reason=match_reason(item, True)
        )

    async def offers(self, item: dict) -> list[ProductOffer]:
        """Find one compatible PrijsProfeet product per retailer for a basic item."""
        query = item.get("selected_name") or item["query"]
        if "bruinbrood" in query.lower():
            query = re.sub("bruinbrood", "bruin brood", query, flags=re.IGNORECASE)
        candidates = await self.search(query, limit=None)
        checks = self.last_diagnostics[item["id"]] = []
        compatible = []
        for p in candidates:
            decision = candidate_decision(item, p["name"], p)
            check = {"retailer": p["retailer"], "name": p["name"], "package": p.get("quantity"),
                     "source": "PrijsProfeet", "product_id": p.get("product_id"),
                     "price_cents": p.get("price_cents"), "product_url": p.get("product_url"), **decision}
            checks.append(check)
            if decision["status"] == "accepted":
                compatible.append(p)
        result = []
        for p in compatible:
            active = bool(p.get("is_promotional"))
            count, amount, dimension, desired, overage = quantity_details(
                item["quantity"], item.get("unit", "stuk"), p.get("quantity"), p.get("name"))
            if not valid_package_for_intent(item, amount, dimension):
                for check in checks:
                    if check["product_id"] == p.get("product_id"):
                        check.update(status="quantity_unknown", reason="Verpakkingsinhoud ontbreekt of past niet bij de gevraagde eenheid")
                continue
            if p["price_cents"] <= 1:
                for check in checks:
                    if check["product_id"] == p.get("product_id"):
                        check.update(status="source_quality", reason="Prijs ontbreekt of lijkt een testprijs")
                continue
            result.append(ProductOffer(
                item_id=item["id"], retailer=p["retailer"], product_name=p["name"],
                package_price_cents=p["price_cents"],
                packages_needed=count,
                unit_price=p.get("quantity"),
                exact_match=False, loyalty_required=bool(active and p.get("loyalty_required")),
                promotion="Actie" if active else None, valid_until=p.get("valid_until") if active else None,
                product_url=p.get("product_url"), image_url=p.get("image_url"),
                original_price_cents=p.get("original_price_cents") if active else None,
                promotion_type=p.get("promotion_type") if active else None,
                promotion_status=p.get("promotion_status"),
                multi_buy_quantity=p.get("multi_buy_quantity") if active else None,
                multi_buy_price_cents=p.get("multi_buy_price_cents") if active else None,
                source="PrijsProfeet", package_amount=amount, package_dimension=dimension,
                desired_amount=desired, delivered_amount=amount * count if amount else None,
                overage_amount=overage, match_reason=match_reason(item)
            ))
        return result


class EstimatedRouteProvider:
    async def prepare(self, origin: str, stores: list[str]) -> None:
        return None

    async def trip(self, origin: str, stores: tuple[str, ...]) -> dict:
        # Privacyvriendelijke offline schatting totdat een routeprovider is geconfigureerd.
        km = 4.0 + max(0, len(stores) - 1) * 3.5
        return {"distance_km": km, "duration_minutes": round(km * 2.2), "estimated": True}


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


RETAILER_NAMES = {"ah": "Albert Heijn", "albertheijn": "Albert Heijn", "albert_heijn": "Albert Heijn",
                  "jumbo": "Jumbo", "plus": "PLUS", "aldi": "ALDI", "lidl": "Lidl", "dirk": "Dirk",
                  "lidlviaboodschaapjenl": "Lidl",
                  "ekoplaza": "Ekoplaza", "hoogvliet": "Hoogvliet", "dekamarkt": "DekaMarkt",
                  "vomar": "Vomar", "spar": "SPAR", "coop": "Coop", "picnic": "Picnic"}


def canonical_retailer(value: str) -> str:
    return RETAILER_NAMES.get(value.lower(), RETAILER_NAMES.get(_normal(value), value))


class OpenStreetMapRouteProvider:
    """One postcode lookup, one nearby-store query and one driving matrix per comparison."""
    NOMINATIM = "https://nominatim.openstreetmap.org/search"
    OVERPASS = "https://overpass-api.de/api/interpreter"
    OSRM = "https://router.project-osrm.org/table/v1/driving"
    ALIASES = {"albertheijn": ("albertheijn", "ah"), "plus": ("plus",), "jumbo": ("jumbo",),
               "aldi": ("aldi",), "dirk": ("dirk",), "hoogvliet": ("hoogvliet",),
               "dekamarkt": ("dekamarkt",), "vomar": ("vomar",), "spar": ("spar",),
               "coop": ("coop",), "picnic": ("picnic",)}

    def __init__(self, fallback: RouteProvider | None = None):
        self.fallback = fallback or EstimatedRouteProvider()
        self.origin = ""
        self.store_index: dict[str, int] = {}
        self.store_details: dict[str, dict] = {}
        self.distances: list[list[float | None]] = []
        self.durations: list[list[float | None]] = []
        self.ready = False
        self.availability_known = False

    @staticmethod
    def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
        lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
        x = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
        return 6371 * 2 * math.asin(math.sqrt(x))

    @classmethod
    def _chain_matches(cls, retailer: str, label: str) -> bool:
        target, candidate = _normal(retailer), _normal(label)
        aliases = cls.ALIASES.get(target, (target,))
        return any(alias == candidate or alias in candidate for alias in aliases)

    async def prepare(self, origin: str, stores: list[str]) -> None:
        self.origin, self.ready, self.availability_known = origin.strip(), False, False
        self.store_index, self.store_details = {}, {}
        self.distances, self.durations = [], []
        if not re.fullmatch(r"\d{4}\s?[A-Za-z]{2}", self.origin):
            return
        headers = {"User-Agent": "BoodschappenWijzer/0.1 (local grocery comparison app)"}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
                geo = await client.get(self.NOMINATIM, params={"q": f"{self.origin}, Nederland", "format": "jsonv2", "limit": 1, "countrycodes": "nl"})
                geo.raise_for_status(); hits = geo.json()
                if not hits: return
                home = (float(hits[0]["lat"]), float(hits[0]["lon"]))
                query = f'[out:json][timeout:20];nwr["shop"="supermarket"](around:12000,{home[0]},{home[1]});out center tags;'
                nearby = await client.post(self.OVERPASS, content=query,
                                           headers={**headers, "Content-Type": "application/x-www-form-urlencoded"})
                nearby.raise_for_status(); elements = nearby.json().get("elements", [])
                self.availability_known = True
                branches = []
                for node in elements:
                    tags, center = node.get("tags", {}), node.get("center", node)
                    if "lat" not in center or "lon" not in center: continue
                    label = tags.get("brand") or tags.get("name") or tags.get("operator") or ""
                    branches.append({"label": label, "lat": float(center["lat"]), "lon": float(center["lon"]),
                                     "address": " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")]))})
                chosen = []
                for retailer in stores:
                    matches = [b for b in branches if self._chain_matches(retailer, b["label"])]
                    if matches:
                        branch = min(matches, key=lambda b: self._distance(home, (b["lat"], b["lon"])))
                        self.store_index[retailer] = len(chosen) + 1
                        self.store_details[retailer] = branch
                        chosen.append(branch)
                if not chosen: return
                points = [home] + [(b["lat"], b["lon"]) for b in chosen]
                coords = ";".join(f"{lon},{lat}" for lat, lon in points)
                matrix = await client.get(f"{self.OSRM}/{coords}", params={"annotations": "distance,duration"})
                matrix.raise_for_status(); body = matrix.json()
                self.distances, self.durations = body["distances"], body["durations"]
                self.ready = True
        except Exception:
            self.ready = False

    def available_retailers(self, stores: list[str]) -> list[str]:
        """Exclude chains without a branch in the 12 km store search.

        If store discovery itself failed, availability is unknown and callers
        may still use the offline route estimate. A successful lookup with no
        matching branch must never become a fictitious nearby store.
        """
        if not self.availability_known:
            return stores
        return [store for store in stores if store in self.store_index]

    async def trip(self, origin: str, stores: tuple[str, ...]) -> dict:
        if not self.ready or any(s not in self.store_index for s in stores):
            fallback = await self.fallback.trip(origin, stores)
            return fallback | {"route_source": "lokale schatting", "store_details": []}
        indices = [self.store_index[s] for s in stores]
        orders = [indices] if len(indices) == 1 else [indices, list(reversed(indices))]
        candidates = []
        for order in orders:
            legs = list(zip([0] + order, order + [0]))
            values = [(self.distances[a][b], self.durations[a][b]) for a, b in legs]
            if any(distance is None or duration is None for distance, duration in values):
                return await self.fallback.trip(origin, stores)
            distance = sum(value[0] for value in values)
            duration = sum(value[1] for value in values)
            candidates.append((distance, duration))
        distance, duration = min(candidates)
        return {"distance_km": round(distance / 1000, 1), "duration_minutes": round(duration / 60),
                "estimated": False, "route_source": "OpenStreetMap/OSRM",
                "store_details": [{"retailer": s, **self.store_details[s],
                                   "map_url": (f"https://www.openstreetmap.org/?mlat={self.store_details[s]['lat']}"
                                               f"&mlon={self.store_details[s]['lon']}#map=18/"
                                               f"{self.store_details[s]['lat']}/{self.store_details[s]['lon']}")}
                                  for s in stores]}


MISSING_REASONS = {
    "no_source_data": "Geen productdata gevonden in de geraadpleegde bronnen",
    "source_error": "Een prijsbron kon niet worden geraadpleegd; dekking is onvolledig",
    "rejected": "Gevonden producten passen niet bij de gevraagde productsoort of variant",
    "unreviewed": "Productnaam of productsoort vraagt handmatige controle",
    "quantity_unknown": "Verpakkingsinhoud ontbreekt of past niet bij de gevraagde eenheid",
    "source_quality": "Bronprijs is ongeldig of onvoldoende betrouwbaar",
    "outside_area": "Wel een passend aanbod gevonden, maar niet bij een gevonden winkel in dit gebied",
}


def missing_detail(item: dict, diagnostics: dict, stores: tuple[str, ...] | None = None) -> dict:
    trace = diagnostics.get(item["id"], {})
    # A later quantity/price check supersedes preliminary identity acceptance.
    terminal = {}
    for check in trace.get("checks", []):
        if stores is None or check.get("retailer") in stores:
            key = (check.get("retailer"), check.get("name"), check.get("package"), check.get("source"))
            terminal[key] = {**terminal.get(key, {}), **check}
    checks = list(terminal.values())
    statuses = {check["status"] for check in checks}
    reasons = [status for status in ("quantity_unknown", "unreviewed", "source_quality", "rejected")
               if status in statuses]
    if trace.get("source_errors"):
        reasons.insert(0, "source_error")
    if not reasons:
        reasons = ["outside_area" if "accepted" in statuses else "no_source_data"]
    return {"item_id": item["id"], "name": product_intent(item)["display_name"],
            "quantity": item.get("quantity"), "unit": item.get("unit"),
            "reasons": [{"code": code, "message": MISSING_REASONS[code]} for code in reasons],
            "candidate_count": len(checks),
            "candidates": [check for check in checks if check["status"] in
                           {"unreviewed", "quantity_unknown", "source_quality"}],
            "source_errors": trace.get("source_errors", [])}


async def compare(items: list[dict], price_provider: PriceProvider, route_provider: RouteProvider,
                  origin: str, cost_per_km: float) -> dict:
    search_many = getattr(price_provider, "search_many", None)
    if search_many:
        all_offers = await search_many(items)
    else:
        all_offers = []
        for item in items:
            all_offers.extend(await price_provider.search(item))
    retailers = sorted({o.retailer for o in all_offers})
    prepare = getattr(route_provider, "prepare", None)
    if prepare:
        await prepare(origin, retailers)
    available_retailers = getattr(route_provider, "available_retailers", None)
    if available_retailers:
        retailers = available_retailers(retailers)
    by_item_retailer = {(o.item_id, o.retailer): o for o in all_offers}

    async def scenario(stores: tuple[str, ...]):
        selected, missing, missing_details = [], [], []
        for item in items:
            choices = [by_item_retailer[(item["id"], s)] for s in stores if (item["id"], s) in by_item_retailer]
            if not choices:
                missing.append(product_intent(item)["display_name"])
                missing_details.append(missing_detail(item, getattr(price_provider, "last_diagnostics", {}), stores))
            else: selected.append(min(choices, key=lambda x: x.total_cents))
        route = await route_provider.trip(origin, stores)
        product_cents = sum(o.total_cents for o in selected)
        travel_cents = round(route["distance_km"] * cost_per_km * 100)
        return {"stores": list(stores), "offers": [asdict(o) | {"total_cents": o.total_cents,
                                                                  "original_total_cents": o.original_total_cents,
                                                                  "effective_unit_cents": (o.effective_unit_cents
                                                                                           if math.isfinite(o.effective_unit_cents)
                                                                                           else None)} for o in selected],
                "missing": missing, "missing_details": missing_details,
                "matched_count": len(selected), "requested_count": len(items), "complete": not missing,
                "product_cents": product_cents, "travel_cents": travel_cents,
                "total_cents": product_cents + travel_cents, **route}

    singles = [await scenario((r,)) for r in retailers]
    pairs = [await scenario(pair) for pair in combinations(retailers, 2)]
    rank = lambda s: (len(s["missing"]), s["total_cents"])
    strict_retailers = sorted({canonical_retailer(item["selected_retailer"])
                               for item in items
                               if item.get("selected_product_id") and item.get("selected_retailer")
                               and product_intent(item)["match_mode"] == "strikt-exact"})
    constraint_note = None
    if len(strict_retailers) > 2:
        constraint_note = (f"Je strikt exacte keuzes horen bij {len(strict_retailers)} winkels: "
                           f"{', '.join(strict_retailers)}. Een compleet mandje met maximaal twee "
                           "winkels is daardoor niet mogelijk.")
    complete_singles = [scenario for scenario in singles if scenario["complete"]]
    complete_pairs = [scenario for scenario in pairs if scenario["complete"]]
    diagnostics = []
    if not complete_singles and singles: diagnostics.append(min(singles, key=rank))
    if not complete_pairs and pairs: diagnostics.append(min(pairs, key=rank))
    retailer_scenarios = sorted(singles, key=lambda s: (len(s["missing"]), s["total_cents"], s["stores"][0]))
    return {"single": min(complete_singles, key=lambda s: s["total_cents"]) if complete_singles else None,
            "double": min(complete_pairs, key=lambda s: s["total_cents"]) if complete_pairs else None,
            "retailers": retailer_scenarios,
            "diagnostics": diagnostics,
            "unresolved_items": [missing_detail(item, getattr(price_provider, "last_diagnostics", {}))
                                 for item in items if not any((item["id"], store) in by_item_retailer for store in retailers)],
            "source_errors": list({(error.get("source"), error.get("error")): error
                                   for trace in getattr(price_provider, "last_diagnostics", {}).values()
                                   for error in trace.get("source_errors", [])}.values()),
            "review_summary": [{"item_id": item["id"], "name": product_intent(item)["display_name"],
                                "count": sum(check.get("status") == "unreviewed" for check in
                                             getattr(price_provider, "last_diagnostics", {}).get(item["id"], {}).get("checks", []))}
                               for item in items if any(check.get("status") == "unreviewed" for check in
                                             getattr(price_provider, "last_diagnostics", {}).get(item["id"], {}).get("checks", []))],
            "coverage_note": "Vergelijking van beschikbare bronprijzen en automatisch gecontroleerde matches; onduidelijke productnamen tellen niet mee. Geen garantie op winkelvoorraad of het volledige assortiment.",
            "constraint_note": constraint_note,
            "source_note": "Demodata. Configureer een live prijsprovider voor actuele prijsindicaties."}
