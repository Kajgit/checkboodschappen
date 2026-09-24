from __future__ import annotations
from pathlib import Path
import json
import asyncio
import time
import hashlib
from urllib.parse import urlparse
import httpx

from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .db import Database
from .groceries import (CheckjebonPriceProvider, DemoPriceProvider, EstimatedRouteProvider,
                        OpenStreetMapRouteProvider, PrijsProfeetCatalog, clean_search_query, clean_text,
                        compare, product_intent, purchase_unit)
from .groceries import compatible_product, relevance
from .list_ai import fallback_interpret, interpret_list

CACHE_SCHEMA_VERSION = 20


class ReceiptBody(BaseModel):
    stores: list[str] = Field(min_length=1, max_length=2)


class ItemSelectionBody(BaseModel):
    product_id: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=300)
    retailer: str = Field(min_length=1, max_length=100)
    image_url: str | None = None
    product_url: str | None = None
    quantity: float = Field(gt=0, le=10000)
    unit: str


class ItemBody(BaseModel):
    query: str = Field(min_length=2, max_length=100)
    ean: str | None = None
    quantity: float = Field(default=1, gt=0, le=10000)
    unit: str = "stuk"
    preferred_brand: str | None = None
    allow_alternatives: bool = False
    selected_product_id: str | None = None
    selected_name: str | None = None
    selected_retailer: str | None = None
    selected_image_url: str | None = None
    selected_product_url: str | None = None
    display_name: str | None = None
    product_family: str | None = None
    attributes: list[str] = []
    exclusions: list[str] = []
    match_mode: str | None = None
    remember_quantity: bool = True
    review_confirmed: bool = False
class ItemQuantityBody(BaseModel):
    quantity: float = Field(gt=0, le=10000)
    unit: str
    remember: bool = True
class ItemIntentBody(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)
    product_family: str = Field(min_length=2, max_length=40)
    attributes: list[str] = []
    exclusions: list[str] = []
    match_mode: str
class CompareBody(BaseModel): postcode: str = ""; cost_per_km: float = Field(default=.25, ge=0, le=5)
class InterpretListBody(BaseModel):
    text: str = Field(min_length=2, max_length=5000)
    people: int = Field(default=4, ge=1, le=12)
    model: str | None = Field(default=None, max_length=100)
    use_ai: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    db = Database(settings.data_dir / "boodschappen.db", settings.test_mode)
    db.initialize_local()
    with db.connect(b"") as conn:
        for stored in conn.execute("SELECT * FROM shopping_items").fetchall():
            row = dict(stored)
            values = (clean_search_query(row["query"]),
                      clean_text(row["display_name"]) if row["display_name"] is not None else None,
                      clean_text(row["selected_name"]) if row["selected_name"] is not None else None)
            cleaned_row = row | dict(zip(("query", "display_name", "selected_name"), values))
            intent = product_intent(cleaned_row)
            baseline = fallback_interpret(values[1] or values[0], 4)
            explicit = baseline[0] if baseline and baseline[0]["explanation"] == "Hoeveelheid stond in de tekst" else None
            quantity = explicit["quantity"] if explicit and row["quantity"] == 1 and row["unit"] == "verpakking" else row["quantity"]
            unit = explicit["unit"] if explicit and row["quantity"] == 1 and row["unit"] == "verpakking" else row["unit"]
            unit = purchase_unit(values[0], unit)
            conn.execute("""UPDATE shopping_items SET query=?,display_name=?,selected_name=?,
                         product_family=?,attributes_json=?,exclusions_json=?,quantity=?,unit=? WHERE id=?""",
                         (*values, intent["family"], json.dumps(intent["attributes"], ensure_ascii=False),
                          json.dumps(intent["exclusions"], ensure_ascii=False), quantity, unit, row["id"]))
        conn.commit()
    allowed_image_urls: set[str] = set()
    comparison_cache_path = settings.data_dir / "comparison-cache.json"
    comparison_cache: dict[str, tuple[float, dict]] = {}
    try:
        stored_cache = json.loads(comparison_cache_path.read_text(encoding="utf-8"))
        comparison_cache = {key: (float(value["created_at"]), value["result"])
                            for key, value in stored_cache.items()
                            if isinstance(value, dict) and "created_at" in value and "result" in value}
    except Exception:
        comparison_cache = {}
    image_cache_dir = settings.data_dir / "product-images"
    catalog = PrijsProfeetCatalog()
    price_provider = CheckjebonPriceProvider(settings.data_dir / "supermarktprijzen.json", catalog=catalog)
    route_provider = OpenStreetMapRouteProvider(EstimatedRouteProvider())
    app = FastAPI(title="BoodschappenWijzer", docs_url=None, redoc_url=None)

    def clear_comparison_cache():
        comparison_cache.clear()
        comparison_cache_path.unlink(missing_ok=True)

    def save_comparison_cache():
        comparison_cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: {"created_at": created_at, "result": result}
                   for key, (created_at, result) in comparison_cache.items()}
        temporary = comparison_cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(comparison_cache_path)
        comparison_cache_path.chmod(0o600)

    def key_for(_token: str | None = None):
        return b""

    def check_origin(request: Request):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(403, "Ongeldige aanvraagbron.")

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return Response("Alleen lokale toegang toegestaan.", 403)
        check_origin(request)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/"):
            if request.headers.get("X-Requested-With") not in {"BoodschappenWijzer", "GeldWijzer"}:
                return Response("CSRF-controle mislukt.", 403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data: https:"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/shopping-items")
    def items(gw_session: str | None = Cookie(None)):
        key = key_for(gw_session)
        with db.connect(key) as conn: rows = [dict(r) for r in conn.execute("SELECT * FROM shopping_items ORDER BY id DESC")]
        allowed_image_urls.update(row["selected_image_url"] for row in rows if row.get("selected_image_url"))
        return [dict(row) | product_intent(row) for row in rows]

    @app.get("/api/products/search")
    async def product_search(q: str, gw_session: str | None = Cookie(None)):
        key_for(gw_session)
        if len(q.strip()) < 2: raise HTTPException(400, "Typ minimaal twee tekens.")
        try:
            results = await asyncio.gather(catalog.search(q.strip()), price_provider.candidates(q.strip()),
                                           return_exceptions=True)
            promos = [] if isinstance(results[0], Exception) else results[0]
            regular = [] if isinstance(results[1], Exception) else results[1]
            promos = [product for product in promos if compatible_product(q, product["name"])]
            regular = [product for product in regular if compatible_product(q, product["name"])]
            if (isinstance(results[0], Exception)
                    and (isinstance(results[1], Exception) or (price_provider.source_errors and not regular))):
                raise RuntimeError("Geen prijsbronnen bereikbaar")
            seen, combined = set(), []
            for product in promos + regular:
                identity = (product["retailer"].lower(), product["name"].lower(), product.get("quantity"))
                if identity not in seen:
                    seen.add(identity); combined.append(product)
            combined.sort(key=lambda p: (relevance(q, p["name"]), p["is_promotional"]), reverse=True)
            combined = combined[:30]
            allowed_image_urls.update(product["image_url"] for product in combined if product.get("image_url"))
            return combined
        except Exception as exc: raise HTTPException(503, "Productzoeker is tijdelijk niet bereikbaar.") from exc

    @app.get("/api/product-image")
    async def product_image(url: str, gw_session: str | None = Cookie(None)):
        key_for(gw_session)
        if url not in allowed_image_urls:
            raise HTTPException(404, "Afbeelding is niet door een prijsbron aangeleverd.")
        cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cached_image, cached_type = image_cache_dir / f"{cache_key}.img", image_cache_dir / f"{cache_key}.type"
        if cached_image.exists() and cached_type.exists():
            return Response(cached_image.read_bytes(), media_type=cached_type.read_text(encoding="utf-8"),
                            headers={"Cache-Control": "private, max-age=86400"})
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                         headers={"User-Agent": "BoodschappenWijzer/0.1"}) as client:
                response = await client.get(url)
                response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            if not content_type.startswith("image/") or len(response.content) > 5_000_000:
                raise ValueError("Geen geldige productafbeelding")
            image_cache_dir.mkdir(parents=True, exist_ok=True)
            tmp_image, tmp_type = image_cache_dir / f"{cache_key}.tmp", image_cache_dir / f"{cache_key}.type.tmp"
            tmp_image.write_bytes(response.content); tmp_type.write_text(content_type, encoding="utf-8")
            tmp_image.replace(cached_image); tmp_type.replace(cached_type)
            return Response(response.content, media_type=content_type,
                            headers={"Cache-Control": "private, max-age=86400"})
        except Exception as exc:
            raise HTTPException(502, "Productafbeelding kon niet worden geladen.") from exc

    @app.post("/api/shopping-items")
    def add_item(body: ItemBody, gw_session: str | None = Cookie(None)):
        if body.unit not in {"stuk", "verpakking", "ml", "liter", "g", "kg"}: raise HTTPException(400, "Ongeldige eenheid.")
        query = clean_text(body.query)
        body.unit = purchase_unit(query, body.unit)
        selected_name = clean_text(body.selected_name) if body.selected_name else None
        display_name = clean_text(body.display_name) if body.display_name else None
        inferred = product_intent({
            "query": query, "selected_name": selected_name,
            "selected_product_id": body.selected_product_id,
            "allow_alternatives": body.allow_alternatives,
            "display_name": display_name, "product_family": body.product_family,
            "attributes_json": body.attributes, "exclusions_json": body.exclusions,
            "match_mode": body.match_mode,
        })
        if inferred["match_mode"] not in {"basis", "exact-met-equivalenten", "strikt-exact"}:
            raise HTTPException(400, "Ongeldige vergelijkingsmodus.")
        key = key_for(gw_session)
        with db.connect(key) as conn:
            cur = conn.execute("INSERT INTO shopping_items(query,ean,quantity,unit,preferred_brand,allow_alternatives,selected_product_id,selected_name,selected_retailer,selected_image_url,selected_product_url,display_name,product_family,attributes_json,exclusions_json,match_mode,review_required) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (query, body.ean, body.quantity, body.unit, body.preferred_brand, int(body.allow_alternatives),
                 body.selected_product_id, selected_name, body.selected_retailer,
                 body.selected_image_url, body.selected_product_url, inferred["display_name"], inferred["family"],
                 json.dumps(inferred["attributes"], ensure_ascii=False),
                 json.dumps(inferred["exclusions"], ensure_ascii=False), inferred["match_mode"],
                 int(inferred["family"] == "overig" and not body.selected_product_id
                     and not body.review_confirmed))); conn.commit()
            if body.remember_quantity:
                normalized = query.lower()
                conn.execute("INSERT OR REPLACE INTO shopping_preferences(normalized_query,display_query,quantity,unit,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)",
                             (normalized, query, body.quantity, body.unit)); conn.commit()
        clear_comparison_cache()
        return {"id": cur.lastrowid}

    @app.post("/api/shopping/interpret")
    async def interpret_shopping_list(body: InterpretListBody, gw_session: str | None = Cookie(None)):
        key_for(gw_session)
        # Only the shopping text and household size go to 127.0.0.1 Ollama.
        return await interpret_list(body.text, body.people, body.model if body.use_ai or body.model else "lokale-regels")

    @app.put("/api/shopping-items/{item_id}/intent")
    def update_item_intent(item_id: int, body: ItemIntentBody, gw_session: str | None = Cookie(None)):
        if body.match_mode not in {"basis", "exact-met-equivalenten", "strikt-exact"}:
            raise HTTPException(400, "Ongeldige vergelijkingsmodus.")
        key = key_for(gw_session)
        with db.connect(key) as conn:
            changed = conn.execute("""UPDATE shopping_items SET display_name=?,product_family=?,
                attributes_json=?,exclusions_json=?,match_mode=?,allow_alternatives=?,review_required=0 WHERE id=?""",
                (body.display_name, body.product_family, json.dumps(body.attributes, ensure_ascii=False),
                 json.dumps(body.exclusions, ensure_ascii=False), body.match_mode,
                 int(body.match_mode == "exact-met-equivalenten"), item_id))
            if not changed.rowcount: raise HTTPException(404, "Boodschap niet gevonden.")
            conn.commit()
        clear_comparison_cache()
        return {"ok": True}

    @app.get("/api/shopping-preference")
    def shopping_preference(q: str, gw_session: str | None = Cookie(None)):
        key = key_for(gw_session); normalized = " ".join(q.lower().split())
        with db.connect(key) as conn:
            row = conn.execute("SELECT quantity,unit FROM shopping_preferences WHERE normalized_query=?", (normalized,)).fetchone()
        return dict(row) if row else None

    @app.put("/api/shopping-items/{item_id}/selection")
    def select_item(item_id: int, body: ItemSelectionBody, gw_session: str | None = Cookie(None)):
        if body.unit not in {"stuk", "verpakking", "ml", "liter", "g", "kg"}:
            raise HTTPException(400, "Ongeldige eenheid.")
        with db.connect(key_for(gw_session)) as conn:
            changed = conn.execute("""UPDATE shopping_items SET selected_product_id=?,selected_name=?,
                selected_retailer=?,selected_image_url=?,selected_product_url=?,quantity=?,unit=?,
                match_mode='strikt-exact',allow_alternatives=0,review_required=0 WHERE id=?""",
                (body.product_id, clean_text(body.name), body.retailer, body.image_url, body.product_url,
                 body.quantity, body.unit, item_id))
            if not changed.rowcount:
                raise HTTPException(404, "Boodschap niet gevonden.")
            conn.commit()
        clear_comparison_cache()
        return {"ok": True}

    @app.put("/api/shopping-items/{item_id}/quantity")
    def update_item_quantity(item_id: int, body: ItemQuantityBody, gw_session: str | None = Cookie(None)):
        if body.unit not in {"stuk", "verpakking", "ml", "liter", "g", "kg"}: raise HTTPException(400, "Ongeldige eenheid.")
        key = key_for(gw_session)
        with db.connect(key) as conn:
            item = conn.execute("SELECT query FROM shopping_items WHERE id=?", (item_id,)).fetchone()
            if not item: raise HTTPException(404, "Boodschap niet gevonden.")
            body.unit = purchase_unit(item["query"], body.unit)
            conn.execute("UPDATE shopping_items SET quantity=?,unit=? WHERE id=?", (body.quantity, body.unit, item_id))
            if body.remember:
                normalized = " ".join(item["query"].lower().split())
                conn.execute("INSERT OR REPLACE INTO shopping_preferences(normalized_query,display_query,quantity,unit,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)",
                             (normalized, item["query"], body.quantity, body.unit))
            conn.commit()
        clear_comparison_cache()
        return {"ok": True}

    @app.delete("/api/shopping-items")
    def clear_items(gw_session: str | None = Cookie(None)):
        key = key_for(gw_session)
        with db.connect(key) as conn:
            removed = conn.execute("SELECT COUNT(*) FROM shopping_items").fetchone()[0]
            conn.execute("DELETE FROM shopping_items")
            conn.commit()
        clear_comparison_cache()
        return {"removed": removed}

    @app.delete("/api/shopping-items/{item_id}")
    def delete_item(item_id: int, gw_session: str | None = Cookie(None)):
        key = key_for(gw_session)
        with db.connect(key) as conn: conn.execute("DELETE FROM shopping_items WHERE id=?", (item_id,)); conn.commit()
        clear_comparison_cache()
        return {"ok": True}

    @app.post("/api/shopping/receipt/{format}")
    def receipt(format: str, body: ReceiptBody, gw_session: str | None = Cookie(None)):
        key_for(gw_session)
        if format not in {"pdf", "png"}:
            raise HTTPException(400, "Kies PDF of PNG.")
        # Export server-held results, not client-supplied prices or totals.
        for _, result in sorted(comparison_cache.values(), reverse=True, key=lambda row: row[0]):
            for scenario in [result.get("single"), result.get("double"),
                             *result.get("retailers", []), *result.get("diagnostics", [])]:
                if scenario and sorted(scenario["stores"]) == sorted(body.stores):
                    from .receipt import export_receipt
                    try:
                        data = export_receipt(scenario, format)
                    except ValueError as exc:
                        raise HTTPException(400, str(exc)) from exc
                    return Response(data, media_type="application/pdf" if format == "pdf" else "image/png",
                                    headers={"Content-Disposition": f'attachment; filename="boodschappenbon.{format}"'})
        raise HTTPException(409, "Vergelijk je lijst opnieuw voordat je de bon exporteert.")

    @app.post("/api/shopping/compare")
    async def compare_basket(body: CompareBody, gw_session: str | None = Cookie(None)):
        key = key_for(gw_session)
        with db.connect(key) as conn: items_data = [dict(r) for r in conn.execute("SELECT * FROM shopping_items")]
        if not items_data: raise HTTPException(400, "Voeg eerst boodschappen toe.")
        pending = [product_intent(item)["display_name"] for item in items_data if item.get("review_required")]
        if pending:
            raise HTTPException(409, "Controleer eerst: " + ", ".join(pending))
        # Older exact milk selections were stored as a number of packs. Treat one
        # such pack as one requested litre so alternatives are compared by volume.
        cache_input = {"cache_schema": CACHE_SCHEMA_VERSION, "items": items_data,
                       "postcode": body.postcode.strip().upper(),
                       "cost_per_km": body.cost_per_km}
        cache_key = hashlib.sha256(json.dumps(cache_input, sort_keys=True, default=str).encode()).hexdigest()
        cached = comparison_cache.get(cache_key)
        if cached and time.time() - cached[0] < 6 * 3600:
            result = json.loads(json.dumps(cached[1]))
            result["cached"] = True
        else:
            result = await compare(items_data, price_provider, route_provider, body.postcode, body.cost_per_km)
            comparison_cache.clear()
            comparison_cache[cache_key] = (time.time(), json.loads(json.dumps(result)))
            save_comparison_cache()
            result["cached"] = False
        for scenario in (result.get("single"), result.get("double"),
                         *result.get("retailers", []), *result.get("diagnostics", [])):
            if scenario:
                allowed_image_urls.update(offer["image_url"] for offer in scenario["offers"] if offer.get("image_url"))
        route_example = result.get("single") or result.get("double") or next(iter(result.get("diagnostics", [])), {})
        route_note = "echte autoroute" if route_example.get("estimated") is False else "lokale routeschatting"
        used_sources = sorted({offer["source"] for scenario in result.get("retailers", [])
                               for offer in scenario["offers"] if offer.get("source")})
        result["source_note"] = (f"Prijsbronnen: {', '.join(used_sources) or 'geen'}. {price_provider.last_source}. Reisberekening: {route_note}. "
                                 "Controleer de kassaprijs en actievoorwaarden.")
        return result

    static = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app


app = create_app()
