from app.list_ai import _sanitize, apply_purchase_guardrails, fallback_interpret


def test_vague_list_gets_household_quantities_without_adding_products():
    result = fallback_interpret("Brood\nSperziebonen\nHamburgers\nTomaten", 4)
    by_name = {item["name"]: item for item in result}
    assert by_name["Brood"]["quantity"] == 1
    assert by_name["Sperziebonen"]["quantity"] == .8
    assert by_name["Sperziebonen"]["unit"] == "kg"
    assert by_name["Hamburgers"]["quantity"] == 4
    assert by_name["Tomaten"]["quantity"] == .6


def test_explicit_amount_wins_over_household_estimate():
    item = fallback_interpret("1kg jong belegen stuk kaas", 3)[0]
    assert item["quantity"] == 1
    assert item["unit"] == "kg"
    assert item["explanation"] == "Hoeveelheid stond in de tekst"
    assert item["search_query"] == "jong belegen stuk kaas"
    carrots = fallback_interpret("wortel 600gr", 4)[0]
    assert (carrots["search_query"], carrots["quantity"], carrots["unit"]) == ("wortel", .6, "kg")


def test_unknown_brand_is_kept_and_marked_uncertain():
    item = fallback_interpret("Pino grigio wit", 4)[0]
    assert item["search_query"] == "Pinot grigio wit"
    assert item["quantity"] == 1
    assert item["confidence"] == "middel"


def test_household_staples_are_not_multiplied_per_person_and_ocr_noise_is_removed():
    result = fallback_interpret("Roomboter\nOngezoete kokosmelk\nChiazaad\ns", 4)
    by_name = {item["name"]: item for item in result}
    assert by_name["Roomboter"]["quantity"] == .25
    assert by_name["Ongezoete kokosmelk"]["quantity"] == 1
    assert by_name["Chiazaad"]["quantity"] == .1
    assert "s" not in by_name


def test_packaged_drink_defaults_are_not_multiplied_by_household_size():
    crystal, wine = fallback_interpret("Crystal Clear\nPinot grigio rosé", 4)
    assert (crystal["quantity"], crystal["unit"]) == (1.5, "liter")
    assert (wine["quantity"], wine["unit"]) == (1, "verpakking")


def test_greek_yoghurt_uses_a_household_tub_not_a_single_serving():
    yoghurt = fallback_interpret("Griekse yoghurt", 4)[0]
    assert (yoghurt["quantity"], yoghurt["unit"]) == (1, "kg")


def test_pindakaas_and_sugar_snaps_get_normal_pack_quantities():
    peanut_butter, sugar_snaps = fallback_interpret("Calvé pindakaas\nSugar snaps", 4)
    assert (peanut_butter["family"], peanut_butter["quantity"], peanut_butter["unit"]) == (
        "pindakaas", 1, "verpakking")
    assert (sugar_snaps["family"], sugar_snaps["quantity"], sugar_snaps["unit"]) == (
        "sugarsnaps", .25, "kg")


def test_purchase_units_do_not_scale_one_package_per_person():
    tacos, lettuce, eggs = fallback_interpret("Taco shells/tortilla's\nSla\nEieren", 4)
    assert (tacos["search_query"], tacos["family"], tacos["quantity"], tacos["unit"]) == (
        "Taco shells", "taco_shells", 1, "verpakking")
    assert (lettuce["family"], lettuce["attributes"], lettuce["quantity"], lettuce["unit"]) == (
        "sla", ["krop"], 1, "stuk")
    assert (eggs["family"], eggs["quantity"], eggs["unit"]) == (
        "eieren", 1, "verpakking")


def test_packaged_meal_products_scale_by_packages_not_people():
    tacos = fallback_interpret("Taco shells", 7)[0]
    assert (tacos["quantity"], tacos["unit"]) == (2, "verpakking")
    explicit = fallback_interpret("2 pakken taco shells", 4)[0]
    assert (explicit["quantity"], explicit["unit"]) == (2, "verpakking")
    assert explicit["explanation"] == "Hoeveelheid stond in de tekst"


def test_unknown_products_default_to_one_purchase_package():
    result = fallback_interpret("Crème fraîche\nTacosaus\nBouillon\nEen nieuw supermarktproduct", 4)
    assert all((item["quantity"], item["unit"]) == (1, "verpakking") for item in result)


def test_whatsapp_format_characters_are_removed_and_sla_does_not_match_slavink():
    onion, slavink, puree = fallback_interpret("\u2060  \u2060Ui\nslavink\ntomatenpuree", 4)
    assert onion["name"] == "Ui"
    assert slavink["family"] != "sla"
    assert puree["family"] != "tomaten"


def test_regular_cucumber_and_grated_cheese_have_neutral_profiles():
    cheese, cucumber = fallback_interpret("Geraspte kaas\nKomkommer", 4)
    assert cheese["family"] == "geraspte_kaas"
    assert {"pasta", "pizza", "cheddar", "tex-mex"} <= set(cheese["exclusions"])
    assert (cucumber["family"], cucumber["quantity"], cucumber["unit"]) == (
        "komkommer", 2, "stuk")
    assert {"mini", "midi", "snoep", "rauwkost"} <= set(cucumber["exclusions"])


def test_model_cannot_turn_household_size_into_package_count():
    fallback = fallback_interpret("Crème fraîche\nTacosaus\nBouillon", 4)
    model_items = [{**item, "quantity": 4, "unit": "stuk", "family": "saus"}
                   for item in fallback]
    guarded = apply_purchase_guardrails(model_items, fallback)
    assert all((item["quantity"], item["unit"]) == (1, "verpakking") for item in guarded)
    assert [item["family"] for item in guarded] == [item["family"] for item in fallback]


def test_model_rows_are_aligned_to_source_and_implausible_units_are_repaired():
    fallback = fallback_interpret("Komkommer\nGeraspte kaas\nSlavink", 4)
    model = [
        {**fallback[0], "name": "name", "quantity": 4, "unit": "kg"},
        {**fallback[1], "name": "name", "search_query": "product", "family": "kaas"},
        {**fallback[2], "name": "name", "family": "slavink", "quantity": 4, "unit": "kg"},
    ]
    result = apply_purchase_guardrails(model, fallback)
    assert [item["name"] for item in result] == ["Komkommer", "Geraspte kaas", "Slavink"]
    assert (result[0]["quantity"], result[0]["unit"]) == (2, "stuk")
    assert result[1]["search_query"] == "Geraspte kaas"
    assert (result[2]["quantity"], result[2]["unit"]) == (1, "verpakking")


def test_ai_output_cannot_put_amounts_or_metadata_in_product_intent():
    item = _sanitize({"name": "Tomaten", "search_query": "1 kg tomaten", "family": "fruit",
                      "attributes": ["product_name", "merk", "vers"], "exclusions": [],
                      "quantity": 1, "unit": "kg", "explanation": "schatting", "confidence": "hoog"}, 4)
    assert item["search_query"] == "tomaten"
    assert item["family"] == "tomaten"
    assert item["attributes"] == ["vers"]
    assert "soep" in item["exclusions"]


def test_ai_typo_and_contradictory_drink_explanation_are_corrected():
    wine = _sanitize({"name": "Pinot grigio wit", "search_query": "Pino grigio wit", "family": "wijn",
                      "attributes": ["wit"], "exclusions": [], "quantity": 1, "unit": "stuk",
                      "explanation": "Een fles wijn", "confidence": "hoog"}, 4)
    assert wine["search_query"] == "Pinot grigio wit"
    drink = _sanitize({"name": "Crystal Clear", "search_query": "Crystal Clear", "family": "frisdrank",
                       "attributes": [], "exclusions": [], "quantity": 1.5, "unit": "liter",
                       "explanation": "Crystal Clear is een wijn", "confidence": "hoog"}, 4)
    assert "wijn" not in drink["explanation"].lower()


def test_explicit_small_counts_volumes_and_multipacks_survive_guardrails():
    cases = [('5 g komijn', .005, 'kg', 'komijn'),
             ('12 eieren', 12, 'stuk', 'Eieren'),
             ('2 x 400 g gehakt', .8, 'kg', 'gehakt'),
             ('25 cl kookroom', .25, 'liter', 'kookroom'),
             ('1 pak taco shells', 1, 'verpakking', 'Taco shells'),
             ('2 verpakkingen tortillas', 2, 'verpakking', 'Tortilla wraps')]
    for text, quantity, unit, query in cases:
        baseline = fallback_interpret(text, 4)
        model = [{**baseline[0], 'quantity': 4, 'unit': 'kg'}]
        result = apply_purchase_guardrails(model, baseline)[0]
        assert (result['quantity'], result['unit'], result['search_query']) == (quantity, unit, query)
        assert result['quantity_source'] == 'explicit'


def test_incomplete_model_output_never_drops_source_lines():
    baseline = fallback_interpret('Komkommer\nKookroom\nKookroom', 4)
    result = apply_purchase_guardrails([baseline[0]], baseline)
    assert result == baseline


def test_synthetic_long_list_uses_bounded_batches_and_preserves_duplicates(monkeypatch):
    import asyncio
    from app import list_ai
    # Exercise batching without requiring a person's private shopping list.
    text = '\n'.join(['Taco shells/tortilla’s',
                      *(f'Testproduct {i}' for i in range(40)),
                      'Kookroom', 'Kookroom', 'Sambal'])
    batches = []

    async def fake_batch(part, people, requested_model=None, context=''):
        items = fallback_interpret(part, people)
        assert context == text
        batches.append(items)
        return {'engine': 'lokale-regels', 'model': None, 'items': items}

    monkeypatch.setattr(list_ai, '_interpret_batch', fake_batch)
    items = asyncio.run(list_ai.interpret_list(text, 4))['items']
    assert len(items) == 44
    assert len(batches) == 6
    assert max(map(len, batches)) <= 8
    assert items[0]['source_text'] == 'Taco shells/tortilla’s'
    assert items[0]['family'] == 'taco_shells'
    assert items[0]['confidence'] == 'laag'
    assert all(item['duplicate_count'] == 2 for item in items if item['name'] == 'Kookroom')
    assert items[-1]['name'] == 'Sambal'
    assert all(item['quantity_source'] == 'estimate' for item in items)
    assert len(fallback_interpret('\n'.join(f'Product {i}' for i in range(65)), 4)) == 65


def test_model_source_ids_restore_order_and_reject_missing_rows(monkeypatch):
    import asyncio
    import httpx
    from app import list_ai
    real_client = httpx.AsyncClient
    baseline = fallback_interpret('Komkommer\nTacoschelpen', 4)
    rows = [{'source_id': i, **item} for i, item in enumerate(baseline)]
    rows.reverse()

    def handler(request):
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'qwen-test'}]})
        import json
        return httpx.Response(200, json={'message': {'content': json.dumps({'items': rows})}})

    monkeypatch.setattr(list_ai.httpx, 'AsyncClient', lambda **kwargs:
                        real_client(transport=httpx.MockTransport(handler), **kwargs))
    result = asyncio.run(list_ai._interpret_batch('Komkommer\nTacoschelpen', 4))
    assert result['engine'] == 'ollama'
    assert [item['name'] for item in result['items']] == ['Komkommer', 'Taco shells']
    rows.pop()
    result = asyncio.run(list_ai._interpret_batch('Komkommer\nTacoschelpen', 4))
    assert result['engine'] == 'lokale-regels'
    assert len(result['items']) == 2


def test_model_cannot_inflate_estimates_or_disagree_on_repeated_products():
    baseline = fallback_interpret('Aardappelen\nGeraspte kaas\nKomkommer\nKomkommer', 4)
    model = [{**item, 'quantity': 4} for item in baseline]
    result = apply_purchase_guardrails(model, baseline)
    assert [item['quantity'] for item in result] == [1, .24, 2, 2]
    assert all(item['quantity_source'] == 'estimate' for item in result)


def test_packaged_food_defaults_do_not_create_impossible_piece_requests():
    coconut, peanut, explicit, mince = fallback_interpret("Kokosmelk\nPindakaas\n2 stuks kokosmelk\nGehakt", 4)
    assert (coconut["quantity"], coconut["unit"]) == (1, "verpakking")
    assert peanut["unit"] == "verpakking"
    assert explicit["unit"] == "stuk" and explicit["quantity_source"] == "explicit"
    assert mince["family"] == "gehakt"


def test_ai_cannot_silently_replace_an_unfamiliar_product():
    baseline = fallback_interpret('Misopasta', 4)
    model = [{**baseline[0], 'search_query': 'chocoladepasta', 'family': 'broodbeleg',
              'attributes': ['zoet'], 'exclusions': ['soja']}]
    result = apply_purchase_guardrails(model, baseline)[0]
    assert result['search_query'] == 'Misopasta'
    assert result['family'] == baseline[0]['family']
    assert result['attributes'] == baseline[0]['attributes']
    assert result['ai_suggestion'] == 'chocoladepasta'
