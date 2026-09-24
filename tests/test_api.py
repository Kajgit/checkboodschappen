import os
os.environ["GELDWIJZER_TEST_MODE"] = "1"

from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def test_app_opens_directly_without_password_or_finance_routes(tmp_path):
    client = TestClient(create_app(Settings(tmp_path, True, 900)))
    assert client.get("/").status_code == 200
    assert client.get("/api/shopping-items").status_code == 200
    assert client.get("/api/dashboard").status_code == 404
    assert client.get("/api/transactions").status_code == 404


def test_mutations_keep_local_request_protection(tmp_path):
    client = TestClient(create_app(Settings(tmp_path, True, 900)))
    assert client.delete("/api/shopping-items").status_code == 403
    assert client.delete("/api/shopping-items",
                         headers={"X-Requested-With": "BoodschappenWijzer"}).status_code == 200


def test_shopping_quantity_is_remembered_and_can_be_corrected(tmp_path):
    client = TestClient(create_app(Settings(tmp_path, True, 900)))
    csrf = {"X-Requested-With": "GeldWijzer"}
    client.post("/api/setup", headers=csrf,
                json={"password": "een-heel-veilig-wachtwoord", "password_confirm": "een-heel-veilig-wachtwoord"})
    created = client.post("/api/shopping-items", headers=csrf,
                          json={"query": "melk", "quantity": 3, "unit": "liter", "remember_quantity": True}).json()
    assert client.get("/api/shopping-preference?q=melk").json() == {"quantity": 3.0, "unit": "liter"}
    response = client.put(f"/api/shopping-items/{created['id']}/quantity", headers=csrf,
                          json={"quantity": 2.5, "unit": "liter", "remember": True})
    assert response.status_code == 200
    assert client.get("/api/shopping-preference?q=melk").json() == {"quantity": 2.5, "unit": "liter"}


def test_basic_item_has_confirmed_product_intent(tmp_path):
    client = TestClient(create_app(Settings(tmp_path, True, 900)))
    csrf = {"X-Requested-With": "GeldWijzer"}
    client.post("/api/setup", headers=csrf,
                json={"password": "een-heel-veilig-wachtwoord", "password_confirm": "een-heel-veilig-wachtwoord"})
    client.post("/api/shopping-items", headers=csrf,
                json={"query": "Halfvolle melk", "quantity": 2, "unit": "liter",
                      "match_mode": "basis", "remember_quantity": True})
    item = client.get("/api/shopping-items").json()[0]
    assert item["product_family"] == "melk"
    assert item["attributes"] == ["halfvol", "normaal"]
    assert item["review_required"] is False


def test_confirmed_ai_suggestion_does_not_require_second_review(tmp_path):
    client = TestClient(create_app(Settings(tmp_path, True, 900)))
    csrf = {"X-Requested-With": "GeldWijzer"}
    client.post("/api/setup", headers=csrf,
                json={"password": "een-heel-veilig-wachtwoord", "password_confirm": "een-heel-veilig-wachtwoord"})
    response = client.post("/api/shopping-items", headers=csrf,
                           json={"query": "Crystal Clear", "quantity": 2, "unit": "liter",
                                 "product_family": "frisdrank", "match_mode": "basis",
                                 "review_confirmed": True})
    assert response.status_code == 200
    assert client.get("/api/shopping-items").json()[0]["review_required"] is False


def test_complete_shopping_list_can_be_cleared_without_forgetting_preferences(tmp_path):
    client = TestClient(create_app(Settings(tmp_path, True, 900)))
    csrf = {"X-Requested-With": "GeldWijzer"}
    client.post("/api/setup", headers=csrf,
                json={"password": "een-heel-veilig-wachtwoord", "password_confirm": "een-heel-veilig-wachtwoord"})
    for query in ("melk", "brood"):
        client.post("/api/shopping-items", headers=csrf,
                    json={"query": query, "quantity": 1, "unit": "stuk", "remember_quantity": True})
    response = client.delete("/api/shopping-items", headers=csrf)
    assert response.json() == {"removed": 2}
    assert client.get("/api/shopping-items").json() == []
    assert client.get("/api/shopping-preference?q=melk").json() == {"quantity": 1.0, "unit": "stuk"}


def test_user_quantities_are_preserved_in_existing_list(tmp_path):
    client = TestClient(create_app(Settings(tmp_path, True, 900)))
    csrf = {"X-Requested-With": "GeldWijzer"}
    client.post("/api/setup", headers=csrf,
                json={"password": "een-heel-veilig-wachtwoord", "password_confirm": "een-heel-veilig-wachtwoord"})
    client.post("/api/shopping-items", headers=csrf,
                json={"query": "Griekse yoghurt", "quantity": 1, "unit": "stuk",
                      "product_family": "yoghurt", "attributes": ["Grieks"],
                      "match_mode": "basis", "review_confirmed": True})
    client.post("/api/shopping-items", headers=csrf,
                json={"query": "Brood", "quantity": 1, "unit": "kg",
                      "product_family": "brood", "match_mode": "basis", "review_confirmed": True})
    items = {item["display_name"]: item for item in client.get("/api/shopping-items").json()}
    assert (items["Griekse yoghurt"]["quantity"], items["Griekse yoghurt"]["unit"]) == (1, "stuk")
    assert (items["Brood"]["quantity"], items["Brood"]["unit"]) == (1, "kg")


def test_explicit_gram_amount_in_legacy_display_name_is_restored(tmp_path):
    settings = Settings(tmp_path, True, 900)
    first = TestClient(create_app(settings))
    csrf = {"X-Requested-With": "BoodschappenWijzer"}
    first.post("/api/shopping-items", headers=csrf, json={
        "query": "wortel 600gr", "display_name": "wortel 600gr", "quantity": 1,
        "unit": "verpakking", "match_mode": "basis", "review_confirmed": True})
    second = TestClient(create_app(settings))
    item = second.get("/api/shopping-items").json()[0]
    assert (item["query"], item["quantity"], item["unit"]) == ("wortel", .6, "kg")


def test_gram_and_milliliter_quantities_are_supported(tmp_path):
    client = TestClient(create_app(Settings(tmp_path, True, 900)))
    csrf = {"X-Requested-With": "GeldWijzer"}
    client.post("/api/setup", headers=csrf,
                json={"password": "een-heel-veilig-wachtwoord", "password_confirm": "een-heel-veilig-wachtwoord"})
    for query, quantity, unit in (("Sugar snaps", 250, "g"), ("Red Bull", 250, "ml"),
                                  ("Taco shells", 1, "verpakking")):
        response = client.post("/api/shopping-items", headers=csrf,
                               json={"query": query, "quantity": quantity, "unit": unit,
                                     "match_mode": "basis", "review_confirmed": True})
        assert response.status_code == 200


def test_comparison_snapshot_survives_app_restart(tmp_path, monkeypatch):
    calls = 0

    async def fake_compare(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"single": None, "double": None, "retailers": [], "diagnostics": [],
                "constraint_note": None, "source_note": "test"}

    monkeypatch.setattr("app.main.compare", fake_compare)
    csrf = {"X-Requested-With": "GeldWijzer"}
    password = "een-heel-veilig-wachtwoord"
    first = TestClient(create_app(Settings(tmp_path, True, 900)))
    first.post("/api/setup", headers=csrf, json={"password": password, "password_confirm": password})
    first.post("/api/shopping-items", headers=csrf,
               json={"query": "Halfvolle melk", "quantity": 1, "unit": "liter",
                     "match_mode": "basis", "review_confirmed": True})
    assert first.post("/api/shopping/compare", headers=csrf, json={}).json()["cached"] is False
    assert calls == 1

    second = TestClient(create_app(Settings(tmp_path, True, 900)))
    result = second.post("/api/shopping/compare", headers=csrf, json={}).json()
    assert result["cached"] is True
    assert calls == 1


def test_manual_product_confirmation_preserves_original_request(tmp_path):
    client = TestClient(create_app(Settings(tmp_path, True)))
    headers = {'X-Requested-With': 'BoodschappenWijzer'}
    item = client.post('/api/shopping-items', headers=headers, json={
        'query': 'kokosmelk', 'quantity': 1, 'unit': 'stuk', 'review_confirmed': True,
    }).json()
    selected = client.put(f"/api/shopping-items/{item['id']}/selection", headers=headers, json={
        'product_id': 'cjb:ah:123', 'name': 'AH Kokosmelk', 'retailer': 'Albert Heijn',
        'quantity': 400, 'unit': 'ml',
    })
    assert selected.status_code == 200
    actual = client.get('/api/shopping-items').json()[0]
    assert actual['query'] == 'kokosmelk'
    assert actual['quantity'] == 400 and actual['unit'] == 'ml'
    assert actual['selected_product_id'] == 'cjb:ah:123'
    assert actual['match_mode'] == 'strikt-exact'
    assert not actual['review_required']


def test_empty_catalogue_search_is_not_reported_as_source_outage(tmp_path, monkeypatch):
    from app.groceries import PrijsProfeetCatalog, CheckjebonPriceProvider
    async def no_products(*args, **kwargs): return []
    monkeypatch.setattr(PrijsProfeetCatalog, 'search', no_products)
    monkeypatch.setattr(CheckjebonPriceProvider, 'candidates', no_products)
    client = TestClient(create_app(Settings(tmp_path, True)))
    response = client.get('/api/products/search?q=molokhia')
    assert response.status_code == 200
    assert response.json() == []


def test_list_interpretation_is_local_rules_by_default(tmp_path, monkeypatch):
    async def no_model(*args, **kwargs): raise AssertionError('Default UI must not call Ollama')
    monkeypatch.setattr('app.list_ai._interpret_batch', no_model)
    client = TestClient(create_app(Settings(tmp_path, True)))
    result = client.post('/api/shopping/interpret', headers={'X-Requested-With': 'BoodschappenWijzer'},
                         json={'text': '400 g tofu\n1 verpakking misopasta', 'people': 4})
    assert result.status_code == 200
    assert result.json()['engine'] == 'lokale-regels'
    assert len(result.json()['items']) == 2


def test_coconut_legacy_units_are_migrated_without_guessing_volume(tmp_path):
    import sqlite3
    settings = Settings(tmp_path, True)
    client = TestClient(create_app(settings))
    headers = {'X-Requested-With': 'BoodschappenWijzer'}
    for qty, unit in [(1, 'stuk'), (600, 'ml')]:
        client.post('/api/shopping-items', headers=headers, json={'query': 'kokosmelk', 'quantity': qty, 'unit': unit})
    with sqlite3.connect(tmp_path / 'boodschappen.db') as db:
        db.execute("UPDATE shopping_items SET unit='stuk' WHERE quantity=1")
    restarted = TestClient(create_app(settings))
    rows = restarted.get('/api/shopping-items').json()
    assert {(r['quantity'], r['unit']) for r in rows} == {(1, 'verpakking'), (600, 'ml')}
