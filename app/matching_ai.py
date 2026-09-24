from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx


OLLAMA_URL = "http://127.0.0.1:11434"
_CACHE: dict[str, dict[str, dict[str, str]]] = {}

SCHEMA = {
    "type": "object",
    "properties": {
        "judgements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "accepted": {"type": "boolean"},
                    "confidence": {"type": "string", "enum": ["hoog", "middel", "laag"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "accepted", "confidence", "reason"],
            },
        }
    },
    "required": ["judgements"],
}

IDS_SCHEMA = {
    "type": "object",
    "properties": {"accepted_ids": {"type": "array", "items": {"type": "string"}}},
    "required": ["accepted_ids"],
}


async def accepted_candidate_ids(targets: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> set[str] | None:
    """Classify a complete comparison in one compact local-model pass."""
    if not candidates:
        return set()
    payload = {"targets": targets, "candidates": candidates}
    cache_key = "ids:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return set(cached)
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_URL, timeout=180, trust_env=False) as client:
            tags = await client.get("/api/tags")
            tags.raise_for_status()
            models = [x.get("name") for x in tags.json().get("models", []) if x.get("name")]
            model = (next((m for m in models if "llama3.1:8b" in m.lower()), None)
                     or next((m for m in models if "llama" in m.lower()), None)
                     or next((m for m in models if any(k in m.lower() for k in ("qwen", "gemma"))), None))
            if not model:
                return None
            prompt = """Selecteer geldige supermarktproducten voor de gekoppelde boodschappen-intentie.
Retourneer ALLEEN de ids die inhoudelijk echt overeenkomen.
- Het product zelf moet het gevraagde product zijn; een ingrediëntwoord is onvoldoende.
- Roomboterpuntjes, spritsen, carrees, croissants, koek, cake en amandelstaaf zijn geen pak roomboter.
- Pure gezouten of ongezouten roomboter in een pak/bakje is wel roomboter.
- Tomatenpuree, soep, sap en gedroogde tomaten zijn geen verse tomaten.
- Kaasbroodjes zijn geen kaas; bereide maaltijden zijn geen kipfilet.
- Voor gewone Griekse yoghurt: accepteer normale Griekse yoghurt en wijs lactofree/lactosevrij,
  drinkyoghurt, desserts en kinderbekers af als die speciale variant niet gevraagd is.
- Respecteer variantkenmerken en uitsluitingen. Bij twijfel niet opnemen.
- Verpakking en prijs bepalen niet de productsoort.
Gebruik uitsluitend bestaande kandidaat-id's. Geef geen uitleg.
Data:\n""" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            response = await client.post("/api/chat", json={
                "model": model, "stream": False, "format": IDS_SCHEMA, "think": False,
                "options": {"temperature": 0, "num_ctx": 16384,
                            "num_predict": min(3500, max(600, len(candidates) * 8))},
                "messages": [{"role": "user", "content": prompt}], "keep_alive": "15m",
            })
            response.raise_for_status()
            parsed = json.loads(response.json()["message"]["content"])
        valid_ids = {row["id"] for row in candidates}
        accepted = {str(value) for value in parsed.get("accepted_ids", []) if str(value) in valid_ids}
        _CACHE[cache_key] = {value: {} for value in accepted}
        return accepted
    except Exception:
        return None


def _offer_id(index: int) -> str:
    return f"p{index}"


async def judge_candidates(targets: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, dict[str, str]] | None:
    """Let a local model classify actual catalogue rows, never invent products.

    A None result means Ollama was unavailable. The caller must then retain its
    conservative deterministic filters instead of treating everything as valid.
    """
    if not candidates:
        return {}
    payload = {"targets": targets, "candidates": candidates}
    cache_key = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_URL, timeout=120, trust_env=False) as client:
            tags = await client.get("/api/tags")
            tags.raise_for_status()
            models = [x.get("name") for x in tags.json().get("models", []) if x.get("name")]
            # Candidate classification needs stronger semantic discrimination
            # than list parsing. Prefer the locally installed 8B Llama model;
            # small 4B models confused pastries containing butter with butter.
            model = (next((m for m in models if "llama3.1:8b" in m.lower()), None)
                     or next((m for m in models if "llama" in m.lower()), None)
                     or next((m for m in models if any(k in m.lower() for k in ("qwen", "gemma"))), None))
            if not model:
                return None
            prompt = """Beoordeel echte supermarktproducten tegenover boodschappen-intenties.

Per kandidaat:
- accepteer alleen wanneer het product zelf is wat de target vraagt, niet wanneer het doelproduct slechts een ingrediënt is;
- voor target roomboter accepteer je alleen een pak/bakje pure boter. ALLE bakkerijproducten zijn false:
  "roomboter puntjes", "roomboterpuntjes", croissants, koek, cake en amandelstaaf zijn dus accepted=false;
- tomatenpuree, tomatensoep, tomatensap en gedroogde tomaten zijn geen verse tomaten;
- Griekse yoghurt moet werkelijk Griekse yoghurt zijn; wijs lactosevrije, drink-, dessert- en kinderproducten af tenzij gevraagd;
- een kaasbroodje is geen kaas en een bereide maaltijd met kip is geen kipfilet;
- merk is vrij tenzij de target expliciet een strikt exact artikel vraagt;
- verpakking en prijs bepalen niet of de productsoort klopt;
- bij twijfel: accepted=false. Gebruik uitsluitend de opgegeven kandidaat-id's.

Geef voor iedere kandidaat precies een oordeel. reason is maximaal zes Nederlandse woorden.
Data:\n""" + json.dumps(payload, ensure_ascii=False)
            response = await client.post("/api/chat", json={
                "model": model, "stream": False, "format": SCHEMA, "think": False,
                "options": {"temperature": 0, "num_predict": min(8000, max(1200, 90 * len(candidates)))},
                "messages": [{"role": "user", "content": prompt}], "keep_alive": "5m",
            })
            response.raise_for_status()
            parsed = json.loads(response.json()["message"]["content"])
        valid_ids = {row["id"] for row in candidates}
        result = {
            row["id"]: {"accepted": bool(row["accepted"]),
                        "confidence": row.get("confidence", "laag"),
                        "reason": str(row.get("reason") or "Lokaal beoordeeld")[:140]}
            for row in parsed.get("judgements", []) if row.get("id") in valid_ids
        }
        # Missing judgements are deliberately absent from the result and are
        # rejected by the caller. Never turn a truncated model answer into the
        # broad deterministic fallback that caused false positive matches.
        _CACHE[cache_key] = result
        return result
    except Exception:
        return None
