from __future__ import annotations

import json
import logging
import math
from collections import Counter
import re
from typing import Any

import httpx

from .groceries import (FAMILY_RULES, clean_search_query, clean_text, contains_keyword,
                        infer_family, infer_profile)


OLLAMA_URL = "http://127.0.0.1:11434"
logger = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "search_query": {"type": "string"},
                    "family": {"type": "string"},
                    "attributes": {"type": "array", "items": {"type": "string"}},
                    "exclusions": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["hoog", "middel", "laag"]},
                },
                "required": ["source_id", "name", "search_query", "family", "attributes", "exclusions",
                             "confidence"],
            },
        }
    },
    "required": ["items"],
}


DEFAULTS = (
    (("pindakaas",), "pindakaas", 1, "verpakking"),
    (("sugar snap", "sugarsnap", "suikererwt", "peultjes"), "sugarsnaps", .25, "kg"),
    (("aardappel",), "aardappelen", .25, "kg"),
    (("rundergehakt",), "rundergehakt", .125, "kg"),
    (("gehakt",), "gehakt", .125, "kg"),
    (("sperzieboon", "sperziebon", "snijboon", "snijbon"), "groente", .20, "kg"),
    (("tomaat", "tomat"), "tomaten", .15, "kg"),
    (("komkommer",), "komkommer", .5, "stuk"),
    (("hamburger",), "hamburgers", 1, "stuk"),
    (("paprika",), "paprika", .5, "stuk"),
    (("yoghurt",), "yoghurt", .25, "kg"),
    (("brood",), "brood", .25, "stuk"),
    (("kaas",), "kaas", .06, "kg"),
    (("roomboter", "boter"), "boter", .25, "kg"),
    (("kokosmelk",), "kokosmelk", 1, "verpakking"),
    (("ijs",), "ijs", 1, "verpakking"),
    (("wijn", "pinot grigio", "pino grigio"), "wijn", 1, "verpakking"),
    (("chia",), "chiazaad", .10, "kg"),
    (("crystal clear",), "frisdrank", 1.5, "liter"),
)

FIXED_HOUSEHOLD_FAMILIES = {"boter", "kokosmelk", "wijn", "chiazaad", "frisdrank", "pindakaas", "sugarsnaps"}

# Products whose useful shopping quantity is a retail unit, not one unit per
# household member. These rules also guard local-model output so results remain
# stable across different Ollama models.
PURCHASE_PROFILES = (
    (("taco shell", "tacoshell", "taco schelp", "tacoschelp"), "taco_shells", "Taco shells", (),
     ("taco saus", "kruidenmix", "chips"), "verpakking"),
    (("tortilla", "wraps", "wrap "), "tortillas", "Tortilla wraps", (),
     ("chips", "saus", "kruidenmix"), "verpakking"),
    (("eieren", "ei doos"), "eieren", "Eieren", (), (), "verpakking"),
    (("sla", "kropsla", "ijsbergsla", "botersla"), "sla", "Sla", ("krop",),
     ("slasaus", "dressing", "melange", "slamix", "gesneden"), "stuk"),
)


def _purchase_profile(text: str) -> tuple | None:
    return next((profile for profile in PURCHASE_PROFILES
                 if any(contains_keyword(text, needle) for needle in profile[0])), None)


def _explicit_amount(text: str) -> tuple[float, str] | None:
    multiplied = re.search(r"\b(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(kg|gr|gram|g|liter|l|ml|cl|dl)\b", text.lower())
    if multiplied:
        content = _explicit_amount(f"{multiplied.group(2)} {multiplied.group(3)}")
        return int(multiplied.group(1)) * content[0], content[1]
    match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(kg|gr|gram|g|liter|l|ml|cl|dl|stuks?|x|(?:pak|pakken)|verpakking(?:en)?|zak(?:ken)?|pot(?:ten)?|fles(?:sen)?)\b", text.lower())
    if not match:
        # Bare leading counts such as '12 eieren' or '2 komkommers'.
        count = re.match(r"^\s*(\d+)\s+(?=[^\d\W])", text)
        return (float(count.group(1)), "stuk") if count else None
    value, unit = float(match.group(1).replace(",", ".")), match.group(2)
    if unit in {"g", "gr", "gram"}: return value / 1000, "kg"
    if unit in {"ml", "cl", "dl"}: return value / {"ml": 1000, "cl": 100, "dl": 10}[unit], "liter"
    if re.fullmatch(r"(?:pak|pakken)|verpakking(?:en)?|zak(?:ken)?|pot(?:ten)?|fles(?:sen)?", unit):
        return value, "verpakking"
    if unit in {"stuk", "stuks", "x"}: return value, "stuk"
    return value, "liter" if unit in {"liter", "l"} else "kg"


def _fallback_item(line: str, people: int) -> dict[str, Any]:
    cleaned = clean_text(re.sub(r"^[\s\-*•☐☑]+", "", line))
    lowered = cleaned.lower()
    explicit = _explicit_amount(cleaned)
    # Unknown products default to one retail package. Household size is only a
    # multiplier for families for which DEFAULTS defines a consumption amount.
    # This is safer for the long tail: sauces, tubs, jars, stock cubes, spices,
    # cans and new products should never become one package per person.
    family, per_person, unit = "overig", 1, "verpakking"
    purchase = _purchase_profile(cleaned)
    if purchase:
        _, family, canonical_query, attributes, exclusions, unit = purchase
        per_person = max(1, -(-people // 4)) if family in {"taco_shells", "tortillas"} else 1
    else:
        canonical_query, attributes, exclusions = cleaned, (), ()
        for needles, candidate_family, amount, candidate_unit in DEFAULTS:
            if any(contains_keyword(lowered, needle) for needle in needles):
                if candidate_family == "tomaten" and infer_family(cleaned) != "tomaten":
                    continue
                family, per_person, unit = candidate_family, amount, candidate_unit
                break
    quantity = explicit[0] if explicit else (per_person if purchase or family == "overig"
                                             or family in FIXED_HOUSEHOLD_FAMILIES
                                             else per_person * people)
    unit = explicit[1] if explicit else unit
    if not explicit:
        if unit == "stuk": quantity = max(1, round(quantity))
        else: quantity = round(max(.1, quantity), 2)
    profile = infer_profile(cleaned)
    corrected_query = clean_search_query(
        re.sub(r"\bpino\s+grigio\b", "Pinot grigio", canonical_query, flags=re.IGNORECASE))
    return {
        "source_text": cleaned,
        "quantity_source": "explicit" if explicit else "estimate",
        "name": corrected_query or cleaned, "search_query": corrected_query,
        "family": profile.get("family", family),
        "attributes": profile.get("attributes", list(attributes)),
        "exclusions": profile.get("exclusions", list(exclusions)),
        "quantity": quantity, "unit": unit,
        "explanation": ("Hoeveelheid stond in de tekst" if explicit else
                        f"Voorstel voor {people} personen; hoeveelheid niet opgegeven"),
        "confidence": "hoog" if explicit else "middel" if family != "overig" else "laag",
    }


def fallback_interpret(text: str, people: int) -> list[dict[str, Any]]:
    lines = [clean_text(part) for part in re.split(r"[\n;]+", text) if len(clean_text(part)) >= 2]
    return [_fallback_item(line, people) for line in lines]


def apply_purchase_guardrails(items: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The model interprets products; source amounts and defaults stay deterministic.

    Callers must align model rows by source ID before applying these rules.
    Unknown quantities remain visible estimates, never model-generated facts.
    """
    if len(items) != len(fallback):
        return [dict(entry) for entry in fallback]
    for item, baseline in zip(items, fallback):
        proposed = clean_search_query(item.get("search_query"))
        if proposed and _normal_name(proposed) != _normal_name(baseline["search_query"]):
            item["ai_suggestion"] = proposed
        # Even an unfamiliar ingredient keeps its original words. A proposed
        # reinterpretation is shown separately, never silently used for search.
        item.update({key: baseline[key] for key in (
            "name", "search_query", "family", "attributes", "exclusions", "source_text",
            "quantity_source", "quantity", "unit", "explanation", "confidence")})
    return items


def _sanitize(raw: dict[str, Any], people: int) -> dict[str, Any] | None:
    name = clean_text(raw.get("name") or raw.get("search_query"))[:100]
    query = clean_search_query(raw.get("search_query") or name)[:100]
    query = re.sub(r"\bpino\s+grigio\b", "Pinot grigio", query, flags=re.IGNORECASE)
    if len(query) < 2:
        return None
    unit = raw.get("unit") if raw.get("unit") in {"stuk", "verpakking", "kg", "liter"} else "stuk"
    try: quantity = float(raw.get("quantity", 1))
    except (TypeError, ValueError): quantity = 1
    if not math.isfinite(quantity):
        return None
    quantity = min(10000, max(.001, quantity))
    if unit == "stuk": quantity = max(1, round(quantity))
    profile = infer_profile(f"{name} {query}")
    intent_text = f"{name} {query}".lower()
    generic_family = infer_family(intent_text)
    family = profile.get("family") or generic_family or str(raw.get("family") or "overig")[:40]
    ignored_attributes = {"product_name", "productnaam", "merk", "hoeveelheid", "eenheid", "confidence"}
    attributes = [str(x)[:40] for x in raw.get("attributes", [])[:8]
                  if str(x).lower() not in ignored_attributes
                  and not any(str(x).lower().startswith(prefix)
                              for prefix in ("product", "merk", "hoeveel", "eenheid", "confidence"))]
    family_exclusions = list(FAMILY_RULES.get(family, ((), ()))[1])
    explanation = str(raw.get("explanation") or f"Schatting voor {people} personen")[:160]
    if family == "frisdrank" and any(term in explanation.lower() for term in ("wijn", "bier", "sterke drank")):
        explanation = "Gebruikelijke flesinhoud; pas dit gerust aan als je meerdere flessen wilt."
    return {
        "name": name or query, "search_query": query,
        "family": family,
        "attributes": profile.get("attributes") or attributes,
        "exclusions": profile.get("exclusions") or family_exclusions or
                      [str(x)[:40] for x in raw.get("exclusions", [])[:12]],
        "quantity": round(quantity, 2), "unit": unit,
        "explanation": explanation,
        "confidence": raw.get("confidence") if raw.get("confidence") in {"hoog", "middel", "laag"} else "laag",
    }


async def _interpret_batch(text: str, people: int, requested_model: str | None = None, context: str = "") -> dict[str, Any]:
    text = "\n".join(clean_text(line) for line in text.splitlines() if clean_text(line))
    fallback = fallback_interpret(text, people)
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_URL, timeout=300, trust_env=False) as client:
            tags = await client.get("/api/tags")
            tags.raise_for_status()
            models = [entry.get("name") for entry in tags.json().get("models", []) if entry.get("name")]
            model = requested_model if requested_model in models else next(
                (name for name in models if any(key in name.lower() for key in ("qwen", "llama", "gemma"))),
                models[0] if models else None)
            if not model:
                raise RuntimeError("Geen lokaal Ollama-model geïnstalleerd")
            numbered = json.dumps([{ "source_id": i, "text": entry["source_text"]}
                                   for i, entry in enumerate(fallback)], ensure_ascii=False)
            prompt = f"""Je interpreteert Nederlandse boodschappen voor {people} personen.
Gebruik de volledige lijst als maaltijdcontext, maar antwoord alleen op de genummerde regels.

Regels:
- Geef precies één product per source_id terug. Kopieer ieder source_id exact, voeg niets toe en laat niets weg.
- name behoudt het gevraagde product. search_query is de gangbare Nederlandse productnaam zonder aantallen of eenheden.
- Corrigeer duidelijke typefouten (Pino grigio -> Pinot grigio). Behoud gevraagde merken en varianten.
- family is de concrete productsoort. attributes en exclusions bevatten alleen relevante productkenmerken; verzin geen dieetwensen of varianten.
- Interpreteer het product zelf, niet een smaak of ingrediënt van iets anders. Taco shells zijn tacoschelpen, geen snoep of chips. Pindakaas is geen proteïnereep. Slavink is geen sla. Tomatenpuree is geen verse tomaat.
- Een samengesteld product zoals peen en uien blijft één groenteverpakking. Combineer of splits geen regels. Dubbele regels blijven apart.
- Bij alternatieven met / kies één genoemde productsoort en geef confidence laag. Kies geen ongevraagd alternatief.
- Verzin geen hoeveelheden. De app verwerkt expliciete aantallen en toont vaste controleerbare voorstellen voor ontbrekende hoeveelheden.
- Geef alleen JSON volgens het schema terug. Confidence slaat op productinterpretatie, niet op hoeveelheden.

Volledige lijst (alleen context):
{context or text}

Te verwerken regels:
{numbered}"""
            response = await client.post("/api/chat", json={
                "model": model, "stream": False, "format": SCHEMA,
                "think": False, "options": {"temperature": 0, "num_ctx": 16384, "num_predict": 3500},
                "messages": [{"role": "user", "content": prompt}],
                "keep_alive": "5m",
            })
            response.raise_for_status()
            parsed = json.loads(response.json()["message"]["content"])
            rows = parsed.get("items", [])
            if (len(rows) != len(fallback)
                    or any(not isinstance(row, dict) or type(row.get("source_id")) is not int for row in rows)
                    or {row["source_id"] for row in rows} != set(range(len(fallback)))):
                raise ValueError("Modeluitkomst mist regels of heeft ongeldige regel-ID's")
            rows.sort(key=lambda row: row["source_id"])
            items = [_sanitize(item, people) for item in rows]
            if any(item is None for item in items):
                raise ValueError("Ongeldige productregel in modeluitkomst")
            if len(items) == len(fallback):
                for item, original in zip(items, fallback):
                    if original["family"] != "overig" and item["family"] != original["family"]:
                        item.update({key: original[key] for key in
                                     ("name", "search_query", "family", "attributes", "exclusions")})
            return {"engine": "ollama", "model": model,
                    "items": apply_purchase_guardrails(items, fallback)}
    except Exception as exc:
        logger.warning("Lokale lijstinterpretatie viel terug op regels: %s", exc)
        return {"engine": "lokale-regels", "model": None, "items": fallback,
                "notice": "AI-interpretatie niet beschikbaar of onvolledig; voor deze regels zijn lokale voorstellen gebruikt."}


async def interpret_list(text: str, people: int, requested_model: str | None = None) -> dict[str, Any]:
    sources = fallback_interpret(text, people)
    items, engines, notices, models = [], set(), [], set()
    for start in range(0, len(sources), 8):
        batch = sources[start:start + 8]
        result = ({"engine": "lokale-regels", "items": [dict(item) for item in batch]}
                  if requested_model == "lokale-regels" else
                  await _interpret_batch("\n".join(item["source_text"] for item in batch),
                                         people, requested_model, context=text))
        items.extend(result["items"])
        engines.add(result["engine"])
        if result.get("model"):
            models.add(result["model"])
        if result.get("notice"):
            notices.append(result["notice"])
    counts = Counter(_normal_name(item["source_text"]) for item in items)
    for item in items:
        item["duplicate_count"] = counts[_normal_name(item["source_text"])]
        if "/" in item["source_text"]:
            item["explanation"] += " · bevat alternatieven; controleer de gekozen productsoort"
            item["confidence"] = "laag"
    return {"engine": next(iter(engines)) if len(engines) == 1 else "gemengd",
            "model": ", ".join(sorted(models)) or None, "items": items,
            "notice": " ".join(dict.fromkeys(notices))}


def _normal_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())
