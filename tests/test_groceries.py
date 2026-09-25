import asyncio, json
from app.groceries import (CheckjebonPriceProvider, OpenStreetMapRouteProvider, ProductOffer,
                           choose_retailer_options, compare, compatible_product, packages_for,
                           clean_search_query, clean_text, compatible_intent, parse_count_from_name, product_intent,
                           quantity_details, relevance,
                           valid_package_for_intent)


class Prices:
    data = {1: [("A", 200), ("B", 100)], 2: [("A", 100), ("B", 220)]}
    async def search(self, item):
        return [ProductOffer(item["id"], shop, item["query"], cents) for shop, cents in self.data[item["id"]]]


class Route:
    async def trip(self, origin, stores):
        return {"distance_km": len(stores), "duration_minutes": len(stores) * 5, "estimated": False}


def test_single_and_split_basket_include_travel_cost():
    items = [{"id": 1, "query": "Melk"}, {"id": 2, "query": "Brood"}]
    result = asyncio.run(compare(items, Prices(), Route(), "1000AA", .25))
    assert result["single"]["stores"] == ["A"]
    assert result["single"]["total_cents"] == 325
    assert result["double"]["product_cents"] == 200
    assert result["double"]["travel_cents"] == 50
    assert result["single"]["complete"] is True
    assert result["double"]["complete"] is True
    assert [scenario["stores"] for scenario in result["retailers"]] == [["A"], ["B"]]
    assert all(scenario["complete"] for scenario in result["retailers"])


def test_three_strict_retailers_explain_two_store_limit():
    class StrictPrices:
        async def search(self, item):
            return [ProductOffer(item["id"], item["selected_retailer"], item["query"], 100, exact_match=True)]

    items = [{"id": i, "query": name, "selected_product_id": str(i),
              "selected_retailer": shop, "allow_alternatives": False}
             for i, (name, shop) in enumerate([
                 ("Kaas", "Albert Heijn"), ("Koffiemelk", "Lidl"), ("Tijgerbrood", "Hoogvliet")
             ], 1)]
    result = asyncio.run(compare(items, StrictPrices(), Route(), "1000AA", .25))
    assert result["single"] is None
    assert result["double"] is None
    assert len(result["diagnostics"]) == 2
    assert "3 winkels" in result["constraint_note"]
    assert "Albert Heijn" in result["constraint_note"]


def test_checkjebon_cached_dataset_is_searched_locally(tmp_path):
    cache = tmp_path / "prices.json"
    cache.write_text(json.dumps([
        {"n": "ah", "c": "Albert Heijn", "d": [{"n": "AH Halfvolle melk", "p": 1.29, "s": "1 l"}]},
        {"n": "jumbo", "c": "Jumbo", "d": [{"n": "Jumbo Halfvolle melk", "p": 1.19, "s": "1 l"}]},
    ]))
    provider = CheckjebonPriceProvider(cache)
    offers = asyncio.run(provider.search({"id": 4, "query": "halfvolle melk", "quantity": 1, "unit": "liter", "ean": None}))
    assert {o.retailer: o.package_price_cents for o in offers} == {"Albert Heijn": 129, "Jumbo": 119}


def test_provider_cannot_choose_mini_cucumber_or_recipe_cheese(tmp_path):
    cache = tmp_path / "prices.json"
    cache.write_text(json.dumps([{"n": "ah", "c": "Albert Heijn", "d": [
        {"n": "Mini-komkommers", "p": .89, "s": "6 stuks"},
        {"n": "AH Komkommer", "p": 1.49, "s": "1 stuk"},
        {"n": "AH Pasta geraspte kaas", "p": 1.00, "s": "150 g"},
        {"n": "AH Goudse geraspte kaas jong 48+", "p": 2.00, "s": "150 g"},
    ]}]))
    provider = CheckjebonPriceProvider(cache)
    cucumber = {"id": 1, "query": "Komkommer", "quantity": 1, "unit": "stuk",
                "product_family": "komkommer", "match_mode": "basis"}
    cheese = {"id": 2, "query": "Geraspte kaas", "quantity": .15, "unit": "kg",
              "product_family": "geraspte_kaas", "match_mode": "basis"}
    assert asyncio.run(provider.search(cucumber))[0].product_name == "AH Komkommer"
    assert asyncio.run(provider.search(cheese))[0].product_name == "AH Goudse geraspte kaas jong 48+"


def test_store_chain_aliases_and_distance():
    assert OpenStreetMapRouteProvider._chain_matches("Albert Heijn", "AH Museumplein")
    assert OpenStreetMapRouteProvider._chain_matches("PLUS", "PLUS Van den Hoven")
    assert not OpenStreetMapRouteProvider._chain_matches("Jumbo", "Albert Heijn")
    km = OpenStreetMapRouteProvider._distance((52.3676, 4.9041), (52.0907, 5.1214))
    assert 30 < km < 40


def test_multi_buy_only_applies_to_complete_bundles():
    offer = ProductOffer(1, "Albert Heijn", "Koffie", 350, packages_needed=5,
                         multi_buy_quantity=2, multi_buy_price_cents=500)
    assert offer.total_cents == 1350


def test_route_result_contains_specific_store_map_link():
    provider = OpenStreetMapRouteProvider()
    provider.ready = True
    provider.store_index = {"Jumbo": 1}
    provider.store_details = {"Jumbo": {"label": "Jumbo", "lat": 52.1, "lon": 5.1, "address": "Dorpsstraat 1"}}
    provider.distances = [[0, 2000], [2200, 0]]
    provider.durations = [[0, 300], [330, 0]]
    result = asyncio.run(provider.trip("1234 AB", ("Jumbo",)))
    assert result["store_details"][0]["address"] == "Dorpsstraat 1"
    assert "openstreetmap.org" in result["store_details"][0]["map_url"]


def test_comparison_excludes_chain_without_nearby_branch():
    class NearbyRoute(Route):
        async def prepare(self, origin, stores):
            self.seen = stores

        def available_retailers(self, stores):
            return [store for store in stores if store == "A"]

    items = [{"id": 1, "query": "Melk"}, {"id": 2, "query": "Brood"}]
    result = asyncio.run(compare(items, Prices(), NearbyRoute(), "7415 HH", .25))
    assert [scenario["stores"] for scenario in result["retailers"]] == [["A"]]
    assert result["single"]["stores"] == ["A"]
    assert result["double"] is None


def test_desired_household_amount_converts_to_packages():
    assert packages_for(3, "liter", "1 l") == 3
    assert packages_for(2.5, "liter", "1,5 l") == 2
    assert packages_for(1, "kg", "300 g") == 4
    assert packages_for(6, "stuk", "4 stuks") == 2


def test_piece_count_in_product_name_overrides_misleading_package_metadata():
    assert parse_count_from_name("Deka witte bollen 6 stuks") == 6
    assert parse_count_from_name("Lidl witte bolletjes 10x50g") == 10
    assert quantity_details(6, "stuk", "Per stuk", "Witte bollen 6 stuks")[:2] == (1, 6)
    assert quantity_details(6, "stuk", "", "Witte bolletjes 4 Stuks")[:2] == (2, 4)
    assert quantity_details(6, "stuk", "50 g", "Witte bollen 10x50g")[:2] == (1, 10)
    assert quantity_details(6, "stuk", "300 Gram", "Witte bollen 6 stuks")[:2] == (1, 6)


def test_pack_optimizer_minimizes_checkout_total_before_unit_price():
    offers = []
    for name, package, price in [("Kip 100 g", "100 g", 170), ("Kip 300 g", "300 g", 450),
                                 ("Kip 500 g", "500 g", 950), ("Kip 1 kg", "1 kg", 2000)]:
        count, amount, dimension, desired, overage = quantity_details(1, "kg", package)
        offers.append(ProductOffer(1, "Jumbo", name, price, packages_needed=count,
                                   package_amount=amount, package_dimension=dimension,
                                   desired_amount=desired, delivered_amount=amount * count,
                                   overage_amount=overage))
    chosen = choose_retailer_options(offers)[0]
    assert chosen.product_name == "Kip 100 g"
    assert chosen.packages_needed == 10
    assert chosen.delivered_amount == 1000
    assert chosen.total_cents == 1700


def test_pack_optimizer_rejects_better_unit_price_above_total_price_band():
    cheap = ProductOffer(1, "Jumbo", "Kip 500 g", 500, packages_needed=2,
                         package_amount=500, package_dimension="weight", desired_amount=1000,
                         delivered_amount=1000, overage_amount=0)
    too_expensive = ProductOffer(1, "Jumbo", "Kip 1 kg", 1200, packages_needed=1,
                                 package_amount=1000, package_dimension="weight", desired_amount=1000,
                                 delivered_amount=1000, overage_amount=0)
    assert choose_retailer_options([cheap, too_expensive])[0].product_name == "Kip 500 g"


def test_pack_optimizer_preserves_large_pack_when_it_is_the_only_valid_option():
    excessive = ProductOffer(1, "PLUS", "Kaas 960 g", 700, packages_needed=2,
                              package_amount=960, package_dimension="weight", desired_amount=1000,
                              delivered_amount=1920, overage_amount=920)
    assert choose_retailer_options([excessive]) == [excessive]


def test_search_intent_rejects_accidental_category_matches():
    assert relevance("melk", "AH Halfvolle melk") > relevance("melk", "AH Koffiemelk")
    assert relevance("bolletjes", "Witte bollen tarwebrood") > relevance("bolletjes", "Tijgerbalsem rood")
    assert relevance("kip", "Verse kipfilet blokjes") > relevance("kip", "Yum Yum chicken noedels")


def test_basic_product_family_rejects_lookalikes():
    assert compatible_product("halfvolle melk", "AH Halfvolle melk")
    assert not compatible_product("halfvolle melk", "Halfvolle koffiemelk")
    assert not compatible_product("halfvolle melk", "Halfvolle yoghurt")
    assert compatible_product("bruinbrood", "Jumbo heel bruinbrood")
    assert not compatible_product("bruinbrood", "AH Naanbrood")
    assert not compatible_product("bruinbrood", "PLUS Kaasbroodje")
    assert not compatible_product("bruinbrood", "AH Stokbrood bruin")
    assert not compatible_product("bruinbrood", "Yam Brood Bruin Glutenvrij")
    assert not compatible_product("halfvolle melk", "Campina halfvolle melk proteine")
    assert not compatible_product("halfvolle melk", "Halfvolle melk houdb")
    assert not compatible_product("halfvolle melk", "Campina Langlekker halfvolle melk")
    assert compatible_product("kaas", "Jonge kaas 48+ stuk", "Melkan Jonge kaas 48+ stuk")
    assert compatible_product("Jonge kaas 48+ stuk", "AH Zaanlander Jong 48+ stuk")
    assert compatible_product("Jonge kaas 48+ stuk", "Beemster Jong 48+ stuk")
    assert not compatible_product("kaas", "Smeerkaas 48+ naturel", "Melkan Jonge kaas 48+ stuk")
    assert not compatible_product("kipfilet", "Biologische kipfilet 100 g")
    assert not compatible_product("kipfilet", "High Protein Meal Kipfilet Saté Bami Goreng 450 g")


def test_pasted_text_short_words_and_plural_forms_are_searchable():
    assert clean_text("\u2060  \u2060Ui") == "Ui"
    assert compatible_product("\u2060Ui", "Gele uien 1 kg")
    assert compatible_product("peen en uien", "Hutspot peen en uien 500 g")
    assert compatible_product("Crème fraîche", "G'woon creme fraiche 200 ml")
    assert clean_search_query("wortel 600gr") == "wortel"
    assert clean_search_query("ui 400 g") == "ui"
    assert clean_search_query("kipBouillon") == "kip Bouillon"
    assert clean_search_query("Olijfolie extraverge") == "Olijfolie extra vierge"
    assert compatible_product("kipBouillon", "Kippenbouillonblokjes")
    assert compatible_product("slavink vlees", "AH Slavink 2 stuks")
    assert compatible_product("Olijfolie extraverge", "Olijfolie extra vergine")
    assert compatible_product("wortel 600gr", "Winterwortelen 1 kg")
    assert not compatible_product("wortel 600gr", "Doperwten en wortelen")
    assert not compatible_product("wortel 600gr", "Maize sticks wortels + mais 7m+")
    assert compatible_product("ui 400gr", "Gele uien trio")
    assert not compatible_product("ui 400gr", "Mix voor gehakt met ui")
    assert not compatible_product("ui 400gr", "Jus ui")
    assert compatible_product("slavink vlees", "Slavinken 4 stuks")
    assert not compatible_product("slavink vlees", "Mini slavinken")


def test_family_inference_uses_words_not_substrings_and_respects_exclusions():
    repaired = product_intent({"query": "slavink", "product_family": "sla",
                               "attributes_json": '["krop"]'})
    assert repaired["family"] == "slavink"
    assert repaired["attributes"] == ["normaal"]
    assert product_intent({"query": "tomatenpuree", "product_family": "tomaten"})["family"] == "tomatenpuree"


def test_normal_cucumber_and_neutral_grated_cheese_beat_special_variants():
    cucumber = {"query": "Komkommer", "product_family": "overig"}
    assert compatible_intent(cucumber, "Komkommer per stuk")
    assert not compatible_intent(cucumber, "Mini-komkommers 6 stuks")
    assert not compatible_intent(cucumber, "Midi komkommers")
    assert not compatible_intent(cucumber, "Snoep komkommer")
    assert not compatible_intent(cucumber, "Rauwkost komkommerblokjes")
    assert not compatible_intent(cucumber, "Heinz Sandwich spread komkommer")
    assert not compatible_intent(cucumber, "Komkommer dille dressing")
    cheese = {"query": "Geraspte kaas", "product_family": "overig"}
    assert compatible_intent(cheese, "Goudse geraspte kaas jong 48+")
    assert not compatible_intent(cheese, "AH Pasta geraspte kaas")
    assert not compatible_intent(cheese, "Pizza kaas geraspt mozzarella mix")
    assert not compatible_intent(cheese, "AH Cheddar geraspte kaas")
    assert not compatible_intent(cheese, "Tex-mex geraspte kaas")
    assert not compatible_intent(cheese, "Emmentaler geraspte kaas")
    assert not compatible_intent(cheese, "Geitenkaas geraspt")
    assert compatible_intent(cheese, "Bio geraspte kaas")
    assert not compatible_intent(cheese, "PLUS Kaassoufflés")
    assert not compatible_intent(cheese, "G'woon kaasflips")
    assert not compatible_intent(cheese, "Oude kaas salade")


def test_managed_basic_intent_is_explainable():
    intent = product_intent({"query": "Halfvolle melk"})
    assert intent["family"] == "melk"
    assert "halfvol" in intent["attributes"]
    assert "koffiemelk" in intent["exclusions"]
    assert intent["match_mode"] == "basis"
    assert valid_package_for_intent({"query": "Kipfilet", "unit": "kg"}, 100, "weight")
    assert valid_package_for_intent({"query": "Kipfilet", "unit": "kg"}, 500, "weight")


def test_legacy_overig_family_is_recovered_from_exact_product_name():
    intent = product_intent({"query": "Campina Halfvolle melk", "selected_name": "Campina Halfvolle melk",
                             "product_family": "overig"})
    assert intent["family"] == "melk"
    assert "houdbaar" in intent["exclusions"]


def test_generic_hybrid_families_reject_shared_word_lookalikes():
    tomato = {"query": "Tomaten", "product_family": "overig"}
    assert product_intent(tomato)["family"] == "tomaten"
    assert compatible_intent(tomato, "AH trostomaten 500 g")
    assert not compatible_intent(tomato, "Knorr Tomatensoep duopak")
    assert not compatible_intent(tomato, "Appelsientje tomatensap 1 l")
    assert not compatible_intent(tomato, "3-pack tomaten frito")
    assert not compatible_intent(tomato, "Olvarit Tomaat Kip Rijst 12+ Maanden")
    assert not compatible_intent(tomato, "Tomaten basilicumdip op yoghurtbasis")
    assert not compatible_intent(tomato, "Heinz Tomaten Polpa 400g")
    butter = {"query": "Roomboter", "product_family": "overig"}
    assert compatible_intent(butter, "Deka roomboter ongezouten 250 g")
    assert not compatible_intent(butter, "Versgebakken Roomboter Croissants")
    assert not compatible_intent(butter, "Roomboter puntjes 6 stuks")
    assert not compatible_intent(butter, "PLUS Roomboter spritsen")
    assert not compatible_intent(butter, "1 de Beste Carrees roomboter")
    assert not compatible_intent(butter, "G'woon Roomboter kano's")
    assert not compatible_intent({"query": "Brood", "product_family": "brood"}, "Theha Kokosbrood")
    cheese = {"query": "Gouda jong belegen", "product_family": "overig"}
    assert compatible_intent(cheese, "Goudse jong belegen kaas stuk")
    assert not compatible_intent(cheese, "Geraspt kaas jong 48+")


def test_product_rules_reject_wrong_product_before_price_selection(tmp_path, monkeypatch):
    cache = tmp_path / "prices.json"
    cache.write_text(json.dumps([{"n": "winkel", "c": "Winkel", "d": [
        {"n": "Roomboter amandelstaaf", "p": 0.99, "s": "250 g"},
        {"n": "Ongezouten roomboter", "p": 2.49, "s": "250 g"},
    ]}]))

    async def judge(_targets, candidates):
        return {row["id"] for row in candidates if "amandelstaaf" not in row["name"].lower()}

    monkeypatch.setattr("app.matching_ai.accepted_candidate_ids", judge)
    provider = CheckjebonPriceProvider(cache)
    offers = asyncio.run(provider.search_many([{
        "id": 17, "query": "roomboter", "display_name": "Roomboter",
        "product_family": "boter", "quantity": .25, "unit": "kg",
        "attributes_json": "[]", "exclusions_json": "[]", "match_mode": "basis",
    }]))
    assert [offer.product_name for offer in offers] == ["Ongezouten roomboter"]
    assert offers[0].confidence == "lokaal gecontroleerd"


def test_pindakaas_never_matches_protein_bar():
    item = {"query": "Calvé pindakaas", "display_name": "Calvé pindakaas",
            "product_family": "kaas", "attributes_json": "[]", "exclusions_json": "[]",
            "match_mode": "basis"}
    assert product_intent(item)["family"] == "pindakaas"
    assert compatible_intent(item, "Calvé Pindakaas pot 350 g")
    assert not compatible_intent(item, "Proteïnereep pindakaas")


def test_sperziebonen_and_sugar_snaps_are_distinct_products():
    beans = {"query": "Sperziebonen", "product_family": "sperziebonen",
             "attributes_json": "[]", "exclusions_json": "[]", "match_mode": "basis"}
    snaps = {"query": "AH Sugar snaps", "product_family": "groente",
             "attributes_json": "[]", "exclusions_json": "[]", "match_mode": "basis"}
    assert compatible_intent(beans, "Sperziebonen 500 g")
    assert not compatible_intent(beans, "AH Sugar snaps 250 g")
    assert product_intent(snaps)["family"] == "sugarsnaps"
    assert compatible_intent(snaps, "AH Sugar snaps 250 g")
    assert not compatible_intent(snaps, "Sugar snaps 250 g")


def test_common_recipe_items_reject_shared_word_products():
    cases = [
        ({"query": "Boter", "product_family": "overig"}, "AH Roomboter ongezouten", True),
        ({"query": "Boter", "product_family": "overig"}, "AH Botersla", False),
        ({"query": "Gember", "product_family": "overig"}, "AH Gember", True),
        ({"query": "Gember", "product_family": "overig"}, "AH Gemberkoek", False),
        ({"query": "Peper", "product_family": "overig"}, "Verstegen Zwarte peper", True),
        ({"query": "Peper", "product_family": "overig"}, "King pepermunt", False),
        ({"query": "Zout", "product_family": "overig"}, "Jozo Tafelzout", True),
        ({"query": "Zout", "product_family": "overig"}, "AH Zoute sticks", False),
        ({"query": "Knoflook", "product_family": "overig"}, "Verse knoflook", True),
        ({"query": "Knoflook", "product_family": "overig"}, "Knoflooksaus", False),
        ({"query": "Shoarmavlees", "product_family": "overig"}, "Slagerij Shoarma", True),
        ({"query": "Shoarmavlees", "product_family": "overig"}, "Silvo Mix voor shoarma", False),
        ({"query": "Taco's", "product_family": "taco_shells"}, "AH Taco schelpen", True),
        ({"query": "Taco's", "product_family": "taco_shells"}, "Knorr Mexicaanse taco maaltijd", False),
        ({"query": "Ui", "product_family": "uien"}, "Aardappelschijfjes spek & ui", False),
        ({"query": "Knoflook", "product_family": "overig"}, "Olijven met kruiden of knoflook", False),
        ({"query": "Kipfilet vlees", "product_family": "kipfilet"}, "Kipfilet of ham", False),
        ({"query": "Aardappelen", "product_family": "aardappelen"}, "Aardappel harten", False),
        ({"query": "Tomaat", "product_family": "tomaten"}, "Maza Hoemoes tomaat", False),
        ({"query": "Mais", "product_family": "overig"}, "Mais flatbread", False),
        ({"query": "Gember", "product_family": "overig"}, "Sushi gember", False),
        ({"query": "Peper", "product_family": "overig"}, "Jalapeño peper rood", False),
        ({"query": "Mais", "product_family": "overig"}, "Geroosterde en gezouten mais", False),
        ({"query": "Zout", "product_family": "overig"}, "Scrocchi zeezout", False),
        ({"query": "Zout", "product_family": "overig"}, "Doperwten 0% zout toegevoegd", False),
        ({"query": "Zout", "product_family": "overig"}, "Klene Puur zout", False),
    ]
    for item, candidate, expected in cases:
        assert compatible_intent(item, candidate) is expected


def test_exact_selection_stays_at_selected_retailer_and_product(tmp_path):
    cache = tmp_path / "prices.json"
    cache.write_text(json.dumps([
        {"n": "ah", "c": "Albert Heijn", "u": "https://ah.example/", "d": [
            {"n": "Tijgerbalsem rood", "p": 11.69, "s": "19 g", "l": "balsem"}
        ]},
        {"n": "hoogvliet", "c": "Hoogvliet", "u": "https://hoogvliet.example/", "d": [
            {"n": "Tijgerbrood", "p": 2.49, "s": "1 stuk", "l": "brood"}
        ]},
    ]))
    provider = CheckjebonPriceProvider(cache)
    offers = asyncio.run(provider.search({
        "id": 9, "query": "brood", "quantity": 1, "unit": "stuk",
        "selected_product_id": "cjb:hoogvliet:brood", "selected_name": "Tijgerbrood",
        "selected_retailer": "Hoogvliet", "allow_alternatives": False,
    }))
    assert [(offer.retailer, offer.product_name, offer.exact_match) for offer in offers] == [
        ("Hoogvliet", "Tijgerbrood", True)
    ]


def test_dirk_product_link_uses_official_search_instead_of_placeholder():
    supermarket = {"n": "dirk", "c": "Dirk", "u": "https://www.dirk.nl/boodschappen/x/x/x/"}
    product = {"n": "Beemster jong belegen 48+ stuk", "l": "68464"}
    url = CheckjebonPriceProvider._product_url(supermarket, product)
    assert url == ("https://www.dirk.nl/boodschappen/zoeken/producten/"
                   "beemster-jong-belegen-48-stuk/68464")
    assert "/x/x/x/" not in url


def test_dekamarkt_product_link_uses_official_search_instead_of_placeholder():
    supermarket = {"n": "dekamarkt", "c": "DekaMarkt", "u": "https://www.dekamarkt.nl/boodschappen/x/x/x/"}
    product = {"n": "Zuivelmeester Halfvolle melk", "l": "477517"}
    url = CheckjebonPriceProvider._product_url(supermarket, product)
    assert url == "https://www.dekamarkt.nl/zoeken/Zuivelmeester%20Halfvolle%20melk"
    assert "/x/x/x/" not in url


def test_dirk_price_parser_supports_cent_and_euro_prices():
    assert CheckjebonPriceProvider._parse_dirk_price('<span class="price-large">85</span>') == 85
    assert CheckjebonPriceProvider._parse_dirk_price(
        '<span class="price-large">1</span><!-- --><span class="price-small">29</span>') == 129


def test_retail_packages_are_not_divided_by_piece_count():
    assert quantity_details(2, 'verpakking', '12 stuks', 'Taco shells 12 stuks') == (2, 1, 'package', 2, 0)
    assert packages_for(2, 'verpakking', '12 stuks') == 2
    assert quantity_details(14, 'stuk', '12 stuks')[0] == 2
    assert quantity_details(1, 'kg', '2 x 400 g')[:2] == (2, 800)
    assert quantity_details(1, 'liter', '6 × 200 ml')[:2] == (1, 1200)
    assert quantity_details(1, 'kg', '0 g')[1] is None


def test_taco_candy_and_hutspot_ingredient_are_not_valid_substitutes():
    assert not compatible_intent({'query': 'Tacoschelpen'}, 'Taco shells gummy snoep')
    assert compatible_intent({'query': 'Tacoschelpen'}, 'Santa Maria Taco shells')
    assert not compatible_intent({'query': 'peen en uien'}, 'Gele uien')
    assert compatible_intent({'query': 'peen en uien'}, 'Hutspot peen en uien')


def test_large_lists_are_order_independent_and_do_not_drop_fourth_cheaper_option(tmp_path, monkeypatch):
    cache = tmp_path / 'prices.json'
    cache.write_text(json.dumps([{'n': 'winkel', 'c': 'Winkel', 'd': [
        {'n': name, 'p': price, 's': '500 g'} for name, price in [
            ('Yoghurt', 2), ('Naturel yoghurt', 1.9), ('Verse yoghurt', 1.8),
            ('Huismerk natuurlijke yoghurt naturel', .9),
        ]]}]))
    provider = CheckjebonPriceProvider(cache)
    async def forbidden(*args): raise AssertionError('Price comparison must not depend on AI')
    async def refresh(offer): pass
    monkeypatch.setattr('app.matching_ai.accepted_candidate_ids', forbidden)
    monkeypatch.setattr(provider, '_refresh_official_price', refresh)
    items = [{'id': i, 'query': 'yoghurt', 'quantity': 1, 'unit': 'kg'} for i in range(44)]
    first = asyncio.run(provider.search_many(items))
    second = asyncio.run(provider.search_many(list(reversed(items))))
    expected = {i: ('Huismerk natuurlijke yoghurt naturel', 180) for i in range(44)}
    assert {o.item_id: (o.product_name, o.total_cents) for o in first} == expected
    assert {o.item_id: (o.product_name, o.total_cents) for o in second} == expected


def test_index_and_family_gate_share_compound_and_plural_semantics(tmp_path):
    store = {'d': [{'n': 'Jumbo Rundergehakt 500 g'}, {'n': 'Gehaktkruiden'},
                   {'n': 'Aardappelen vastkokend'}, {'n': 'Slavink'}]}
    provider = CheckjebonPriceProvider(tmp_path / 'not-used.json')
    assert store['d'][0] in provider._indexed_products(store, ['gehakt'])
    assert store['d'][2] in provider._indexed_products(store, ['aardappel'])
    assert store['d'][3] not in provider._indexed_products(store, ['sla'])
    assert compatible_intent({'query': 'aardappelen'}, 'Aardappelen vastkokend')
    assert compatible_intent({'query': 'gehakt'}, 'Jumbo Rundergehakt 500 g')


def test_quantity_conversion_requires_known_compatible_contents():
    from app.groceries import parse_amount
    assert quantity_details(3, 'stuk', 'Per stuk', 'Komkommer') == (3, 1, 'count', 3, 0)
    assert quantity_details(750, 'g', None, 'Rundergehakt 500 gr') == (2, 500, 'weight', 750, 250)
    assert quantity_details(1500, 'ml', '1 ltr') == (2, 1000, 'volume', 1500, 500)
    assert parse_amount('-250 g') is None
    for unit in ('g', 'kg', 'ml', 'liter', 'stuk'):
        assert not valid_package_for_intent({'unit': unit}, None, None)
    assert not valid_package_for_intent({'unit': 'stuk'}, 500, 'weight')
    assert valid_package_for_intent({'unit': 'g', 'quantity': 20}, 500, 'weight')


def test_unknown_piece_count_never_becomes_a_guessed_basket(tmp_path):
    cache = tmp_path / 'quantity.json'
    cache.write_text(json.dumps([{'n': 'ah', 'c': 'Albert Heijn', 'd': [
        {'n': 'AH Komkommer', 's': '500 g', 'p': .89},
        {'n': 'AH Komkommer', 's': 'Per stuk', 'p': .99},
    ]}]))
    provider = CheckjebonPriceProvider(cache)
    offers = asyncio.run(provider.search({'id': 1, 'query': 'komkommer', 'quantity': 3, 'unit': 'stuk'}))
    assert len(offers) == 1
    assert offers[0].total_cents == 297
    assert offers[0].delivered_amount == 3
    assert any(check['status'] == 'quantity_unknown' for check in provider.last_diagnostics[1]['checks'])


def test_explicit_variants_and_brands_survive_family_normalization():
    assert not compatible_intent({'query': 'Griekse yoghurt'}, 'De Zaanse Hoeve Magere roeryoghurt')
    assert compatible_intent({'query': 'Griekse yoghurt'}, 'Jumbo Yoghurt Griekse Stijl')
    assert not compatible_intent({'query': 'yofresh mayo'}, 'Jumbo Mayonaise Romig')
    assert compatible_intent({'query': 'yofresh mayo'}, 'Calvé Yofresh Mayonaise')
    assert not compatible_intent({'query': 'halfvolle melk'}, 'AH Volle melk')
    assert not compatible_intent({'query': 'yoghurt', 'preferred_brand': 'Campina'}, 'AH Yoghurt naturel')
    assert compatible_intent({'query': 'yoghurt', 'preferred_brand': 'Campina'}, 'Campina Yoghurt naturel')
    assert compatible_intent({'query': 'yoghurt'}, 'Campina Yoghurt naturel')


def test_unknown_brand_is_reviewable_not_a_claimed_match():
    from app.groceries import candidate_decision
    decision = candidate_decision({'query': 'olijfolie'}, 'Onbekend Merk Olijfolie')
    assert decision['status'] == 'unreviewed'
    assert candidate_decision({'query': 'olijfolie'}, 'Onbekend Merk Olijfolie', {'brand': 'Onbekend Merk'})['status'] == 'accepted'


def test_full_catalogue_failure_examples_do_not_become_automatic_matches():
    from app.groceries import candidate_decision
    failures = [
        ('gehakt', 'Iglo Spinazie fijn gehakt'), ('tomaat', 'AH Tomaten gepeld'),
        ('tomaat', 'Witte bonen tomatens'), ('mais', 'AH Tijger tarwe maïs half'),
        ('avocado', 'AH 85% groenteshot wortel avocado'),
        ('knoflook', 'AH Knoflook croutons'), ('knoflook', 'Boursin Knoflook en fijne kruiden'),
        ('olijfolie', 'Paolo Fornaccini olijfolie'), ('olijfolie', 'Princes Sardines in olijfolie'),
        ('kipfilet', 'Sheba Filets Kipfilet stukjes in saus kattenvoer'),
        ('boter', 'AH Minikriel kruidenboter'), ('boter', 'AH Roomboter appeltaartje'),
        ('gember', 'Red Bull Energy drink fuji appel & gember'),
        ('shoarmavlees', 'Dr. Oetker Big Americans shoarma'),
        ('kerriepoeder', 'Kip Kerrie Salade'), ('peper', 'Van Wijngaarden Peper Dipmix'),
        ('crème fraîche', 'Crème fraîche vegan'), ('kipfilet', 'Kipfilet plantaardig'),
        ('Parmezaanse kaas', 'Vegan parmezaan kaas'),
        ('geraspte kaas', 'AH Plantaardige geraspte kaas'),
        ('kookroom', 'AH Plantaardige kookroom'),
    ]
    for query, product in failures:
        assert candidate_decision({'query': query}, product)['status'] != 'accepted', (query, product)


def test_missing_reason_preserves_terminal_quantity_status():
    from app.groceries import missing_detail
    trace = {1: {'checks': [
        {'retailer': 'A', 'name': 'Komkommer', 'package': '500 g', 'source': 'catalogue', 'status': 'accepted'},
        {'retailer': 'A', 'name': 'Komkommer', 'package': '500 g', 'source': 'catalogue', 'status': 'quantity_unknown'},
    ]}}
    detail = missing_detail({'id': 1, 'query': 'Komkommer', 'unit': 'stuk', 'quantity': 2}, trace, ('A',))
    assert detail['candidate_count'] == 1
    assert [reason['code'] for reason in detail['reasons']] == ['quantity_unknown']
    assert missing_detail({'id': 2, 'query': 'molokhia'}, {})['reasons'][0]['code'] == 'no_source_data'


def test_duplicate_intents_share_source_results_and_failures(tmp_path, monkeypatch):
    provider = CheckjebonPriceProvider(tmp_path / 'unused')
    provider._memory_data = []
    calls = []
    async def search(item, select=False):
        calls.append(item['id'])
        provider.last_diagnostics[item['id']] = {'checks': [], 'source_errors': [{'source': 'live', 'error': 'timeout'}]}
        return [ProductOffer(item['id'], 'A', 'Olijfolie', 300)]
    monkeypatch.setattr(provider, 'search', search)
    items = [{'id': i, 'query': query, 'quantity': 1, 'unit': 'verpakking'}
             for i, query in enumerate(('Olijfolie', 'olijfolie', 'OLIJFOLIE'))]
    offers = asyncio.run(provider.search_many(items))
    assert len(calls) == 1
    assert {offer.item_id for offer in offers} == {0, 1, 2}
    assert all(provider.last_diagnostics[i]['source_errors'][0]['error'] == 'timeout' for i in range(3))


def test_invalid_source_price_cannot_win_comparison(tmp_path):
    cache = tmp_path / 'prices.json'
    cache.write_text(json.dumps([{'n': 'ah', 'c': 'Albert Heijn', 'd': [
        {'n': 'AH Avocado', 's': 'Per stuk', 'p': .01},
        {'n': 'AH Avocado eetrijp', 's': 'Per stuk', 'p': 1.49},
    ]}]))
    provider = CheckjebonPriceProvider(cache)
    offers = asyncio.run(provider.search_many([{'id': 1, 'query': 'avocado', 'quantity': 2, 'unit': 'stuk'}]))
    assert offers[0].total_cents == 298


def test_source_pagination_retains_later_cheaper_products(monkeypatch):
    import httpx
    from app.groceries import PrijsProfeetCatalog
    pages = []
    def handler(request):
        page = int(request.url.params['page'])
        pages.append(page)
        return httpx.Response(200, json={'total': 2, 'page': page, 'products': [{
            'product_id': f'product-{page}', 'name': 'Yoghurt', 'retailer': 'ah',
            'price': 2 if page == 1 else 1, 'quantity': '500 g',
        }]})
    real_client = httpx.AsyncClient
    monkeypatch.setattr('app.groceries.httpx.AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    offers = asyncio.run(PrijsProfeetCatalog().offers({'id': 1, 'query': 'yoghurt', 'unit': 'kg', 'quantity': 1}))
    assert pages == [1, 2]
    assert choose_retailer_options(offers)[0].total_cents == 200


def test_original_catalogue_regression_labels():
    from pathlib import Path
    for case in json.loads((Path(__file__).parent / 'fixtures/product_identity_cases.json').read_text()):
        assert compatible_intent({'query': case['query']}, case['product']) == case['expected'], case


def test_ambiguous_prepared_food_requires_evidence():
    from app.groceries import candidate_decision
    assert candidate_decision({'query': 'peen en uien'}, 'AH Hutspot')['status'] == 'unreviewed'
    assert candidate_decision({'query': 'peen en uien'}, 'AH Hutspot', {'unified_category': 'groenten'})['status'] == 'accepted'
    assert candidate_decision({'query': 'kipfilet'}, 'AH Kipfilet', {'s': '70 g'})['status'] == 'unreviewed'
    assert candidate_decision({'query': 'kipfilet'}, 'AH Kipfilet', {'quantity': '350 g', 'unified_category': 'vleeswaren'})['status'] == 'rejected'
    assert not compatible_intent({'query': 'Calvé pindakaas'}, 'AH Pindakaas')


def test_expired_promotional_price_is_not_used(monkeypatch):
    import httpx
    from app.groceries import PrijsProfeetCatalog
    def handler(request):
        return httpx.Response(200, json={'total': 1, 'page': 1, 'products': [{
            'product_id': 'old-deal', 'name': 'Yoghurt', 'retailer': 'ah',
            'price': 1, 'original_price': 2, 'quantity': '500 g', 'is_promotional': True,
            'promotion_status': 'expired', 'valid_until': '2020-01-01',
        }]})
    real_client = httpx.AsyncClient
    monkeypatch.setattr('app.groceries.httpx.AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    product = asyncio.run(PrijsProfeetCatalog().search('yoghurt'))[0]
    assert product['price_cents'] == 200
    assert not product['is_promotional']


def test_live_source_supersedes_older_price_for_same_named_package(tmp_path):
    cache = tmp_path / 'prices.json'
    cache.write_text(json.dumps([{'n': 'ah', 'c': 'Albert Heijn', 'd': [
        {'n': 'AH Yoghurt', 's': '500 g', 'p': 1},
        {'n': 'AH Yoghurt', 's': '1000 g', 'p': 3},
    ]}]))
    class Live:
        async def offers(self, item):
            return [ProductOffer(item['id'], 'Albert Heijn', 'AH Yoghurt', 200,
                                 packages_needed=2, unit_price='0.5 kg', source='PrijsProfeet',
                                 package_amount=500, package_dimension='weight', delivered_amount=1000)]
    provider = CheckjebonPriceProvider(cache, catalog=Live())
    offers = asyncio.run(provider.search_many([{'id': 1, 'query': 'yoghurt', 'quantity': 1, 'unit': 'kg'}]))
    assert offers[0].total_cents == 300
    assert offers[0].unit_price == '1000 g'


def test_exact_catalogue_selection_uses_id_not_shared_product_name(tmp_path):
    cache = tmp_path / 'prices.json'
    cache.write_text(json.dumps([{'n': 'ah', 'c': 'Albert Heijn', 'd': [
        {'n': 'AH Knoflook', 's': '2 stuks', 'p': 1.29, 'l': 'two-bulbs'},
        {'n': 'AH Knoflook', 's': '250 g', 'p': .99, 'l': 'other-pack'},
    ]}]))
    provider = CheckjebonPriceProvider(cache)
    offers = asyncio.run(provider.search_many([{
        'id': 1, 'query': 'knoflook', 'quantity': 1, 'unit': 'verpakking',
        'selected_product_id': 'cjb:ah:two-bulbs', 'selected_name': 'AH Knoflook',
        'selected_retailer': 'Albert Heijn', 'match_mode': 'strikt-exact',
    }]))
    assert len(offers) == 1
    assert offers[0].total_cents == 129
    assert offers[0].unit_price == '2 stuks'


def test_organic_is_not_an_implicit_exclusion_but_custom_exclusions_survive():
    from app.groceries import LEGACY_PROFILE_EXCLUSIONS
    item = {'query': 'komkommer', 'product_family': 'komkommer',
            'exclusions_json': json.dumps(LEGACY_PROFILE_EXCLUSIONS['komkommer'])}
    assert compatible_intent(item, 'AH Biologische komkommer')
    assert compatible_intent({'query': 'komkommer'}, 'AH Biologische komkommer')
    assert not compatible_intent({'query': 'komkommer', 'exclusions_json': ['biologisch']}, 'AH Biologische komkommer')


def test_source_failures_are_visible_without_fabricated_offers(tmp_path):
    class BrokenLive:
        async def offers(self, item): raise TimeoutError('test timeout')
    provider = CheckjebonPriceProvider(tmp_path / 'unused', catalog=BrokenLive())
    provider._memory_data = []
    provider.source_errors = [{'source': 'Checkjebon', 'error': 'test outage'}]
    result = asyncio.run(compare([{'id': 1, 'query': 'melk', 'quantity': 1, 'unit': 'liter'}], provider, Route(), '1012AB', .25))
    assert result['single'] is None and result['double'] is None
    assert not result['retailers']
    assert {error['source'] for error in result['source_errors']} == {'Checkjebon', 'PrijsProfeet'}
    assert result['unresolved_items'][0]['reasons'][0]['code'] == 'source_error'


def test_exact_product_source_outage_is_not_reported_as_no_results(tmp_path):
    class BrokenExact:
        async def offer(self, product_id, item): raise TimeoutError('exact source timeout')
    provider = CheckjebonPriceProvider(tmp_path / 'unused', catalog=BrokenExact())
    provider._memory_data = []
    result = asyncio.run(compare([{
        'id': 1, 'query': 'yoghurt', 'quantity': 500, 'unit': 'g',
        'selected_product_id': 'pp:123', 'selected_retailer': 'Albert Heijn',
        'selected_name': 'Yoghurt', 'match_mode': 'strikt-exact',
    }], provider, Route(), '1012AB', .25))
    assert result['unresolved_items'][0]['reasons'][0]['code'] == 'source_error'


def test_exact_product_unknown_contents_remain_a_quantity_issue(tmp_path, monkeypatch):
    import httpx
    from app.groceries import PrijsProfeetCatalog
    def handler(request):
        return httpx.Response(200, json={'name': 'Kokosmelk', 'retailer': 'ah', 'price': 2, 'quantity': '400 ml'})
    real_client = httpx.AsyncClient
    monkeypatch.setattr('app.groceries.httpx.AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    provider = CheckjebonPriceProvider(tmp_path / 'unused', catalog=PrijsProfeetCatalog())
    provider._memory_data = []
    result = asyncio.run(compare([{
        'id': 1, 'query': 'kokosmelk', 'quantity': 400, 'unit': 'g',
        'selected_product_id': 'pp:123', 'selected_retailer': 'Albert Heijn',
        'selected_name': 'Kokosmelk', 'match_mode': 'strikt-exact',
    }], provider, Route(), '1012AB', .25))
    assert result['unresolved_items'][0]['reasons'][0]['code'] == 'quantity_unknown'


def test_unfamiliar_qualifiers_cannot_disappear_inside_a_broad_family():
    assert not compatible_intent({'query': 'Parmezaanse kaas'}, 'AH Oude kaas')
    assert compatible_intent({'query': 'Parmezaanse kaas'}, 'AH Parmezaanse kaas')
    assert not compatible_intent({'query': 'zwarte knoflook'}, 'AH Knoflook')
    assert compatible_intent({'query': 'zwarte knoflook'}, 'AH Zwarte knoflook')
    assert not compatible_intent({'query': 'gerookte kaas'}, 'AH Kaas')


def test_new_product_types_can_match_literal_explained_names():
    for query, name in [('broccoli', 'AH Broccoli'), ('spaghetti', 'Jumbo Spaghetti 500 g'),
                        ('tofu', 'AH Tofu naturel'), ('koffiebonen', 'AH Koffiebonen'),
                        ('misopasta', 'Jumbo Misopasta')]:
        assert compatible_intent({'query': query}, name), (query, name)
    assert not compatible_intent({'query': 'broccoli'}, 'AH Broccoli kaas quiche')
    assert not compatible_intent({'query': 'spaghetti'}, 'AH Spaghetti bolognese maaltijd')
    assert not compatible_intent({'query': 'zalmfilet'}, 'AH Zalmfilet vegan')
    assert not compatible_intent({'query': 'gedroogde shiitake'}, 'AH Shiitake')


def test_source_unit_spelling_and_piece_counts_are_not_lost():
    assert quantity_details(700, 'ml', '720 milliliter')[:2] == (1, 720)
    assert quantity_details(1, 'kg', '500 grammen')[:2] == (2, 500)
    assert quantity_details(6, 'stuk', '6 x 200 ml', 'Minipakjes')[:2] == (1, 6)


def test_food_synonyms_keep_the_product_type_and_requested_form():
    assert compatible_intent({'query': 'Parmezaanse kaas'}, 'Galbani Parmigiano Reggiano DOP')
    assert not compatible_intent({'query': 'Parmezaanse kaas'}, 'AH Oude kaas')
    assert compatible_intent({'query': 'passata'}, 'Mutti Passata gezeefde fluweelzachte tomaten')
    assert not compatible_intent({'query': 'passata'}, 'AH Tomatensoep met passata')
    assert compatible_intent({'query': 'gedroogde shiitake'}, 'AH Shiitake gedroogd')
    assert not compatible_intent({'query': 'gedroogde shiitake'}, 'AH Shiitake vers')
    assert compatible_intent({'query': 'jackfruit'}, 'Fairtrade Jackfruit')


def test_explicit_fat_percentage_is_not_ignored():
    assert not compatible_intent({'query': 'Griekse yoghurt 10%'}, 'AH Yoghurt Griekse stijl 2%')
    assert compatible_intent({'query': 'Griekse yoghurt 10%'}, 'AH Yoghurt Griekse stijl 10%')


def test_coconut_piece_means_carton_but_volume_is_preserved(tmp_path):
    provider = CheckjebonPriceProvider(tmp_path / 'unused')
    provider._memory_data = [{'n': 'ah', 'c': 'Albert Heijn', 'd': [
        {'n': 'AH Kokosmelk', 's': '400 ml', 'p': 1.5, 'l': 'coconut'},
    ]}]
    def offers(qty, unit):
        return asyncio.run(provider.search({'id': 1, 'query': 'kokosmelk', 'quantity': qty, 'unit': unit}))
    assert offers(2, 'stuk')[0].packages_needed == 2
    assert offers(600, 'ml')[0].packages_needed == 2
    assert offers(1, 'stuk')[0].package_dimension == 'package'
    assert not offers(400, 'g')  # no guessed mass/volume conversion


def test_verified_hutspot_facts_are_bound_to_source_product(tmp_path):
    from app.product_facts import enrich_product
    from app.groceries import candidate_decision
    product = {'n': 'AH Hutspot', 'l': 'wi80568/ah-hutspot', 's': '500 g'}
    query = {'query': 'peen en uien'}
    assert candidate_decision(query, product['n'], enrich_product('ah', product))['status'] == 'accepted'
    assert candidate_decision(query, product['n'], enrich_product('other', product))['status'] == 'unreviewed'
    meal = {**product, 'n': 'AH Hutspot met rookworst'}
    assert candidate_decision(query, meal['n'], enrich_product('ah', meal))['status'] == 'rejected'


def test_scharreleieren_are_accepted_as_eggs_not_flavoured_products():
    from app.groceries import candidate_decision, quantity_details
    assert candidate_decision({"query": "eieren"}, "AH Scharreleieren")["status"] == "accepted"
    assert candidate_decision({"query": "eieren"}, "AH Scharreleieren salade")["status"] == "rejected"
    assert quantity_details(12, "stuk", "10 stuks")[0] == 2


def test_miso_paste_spacing_does_not_admit_soup_or_flavoured_food():
    from app.groceries import candidate_decision
    for query in ('misopasta', 'miso pasta', 'miso paste'):
        for name in ('AH Miso pasta', 'Miso paste', 'Misopasta'):
            assert candidate_decision({'query': query}, name)['status'] == 'accepted'
        for name in ('Miso pasta soep', 'Miso boter', 'Miso ramen', 'Miso pasta marinade'):
            assert candidate_decision({'query': query}, name)['status'] == 'rejected'


def test_generic_breakfast_and_deli_products():
    from app.groceries import candidate_decision
    pairs = [
        ('houdbare melk', 'AH Houdbare halfvolle melk'),
        ('vleeswaren kipfilet', 'AH Gebraden kipfilet'),
        ('vleeswaren chorizo', 'AH Chorizo'),
        ('smeerworst', 'Kips Smeerworst'),
        ('vlokken', 'De Ruijter Chocoladevlokken melk'),
        ('hagelslag', 'Venz Hagelslag melk'),
        ('chocopasta', 'AH Chocoladepasta melk'),
        ('fanta', 'Fanta Orange'),
    ]
    for query, name in pairs:
        assert candidate_decision({'query': query}, name)['status'] == 'accepted', (query, name)
    for query, name in [('houdbare melk', 'AH Verse halfvolle melk'),
                        ('vleeswaren kipfilet', 'AH Kipfilet'),
                        ('kipfilet', 'AH Gebraden kipfilet'),
                        ('vlokken', 'AH Havervlokken'),
                        ('smeerworst', 'AH Leverworst'),
                        ('hagelslag puur', 'Venz Hagelslag melk'),
                        ('ongezoete kokosmelk', 'AH Kokosmelk'),
                        ('fanta zero', 'Fanta Orange')]:
        assert candidate_decision({'query': query}, name)['status'] != 'accepted', (query, name)


def test_browser_explicit_selection_keeps_quantity_checks_and_excludes_other_products():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('app.browser_bridge', Path(__file__).parents[1] / 'public-site/python/bridge.py')
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    product = {'productId': 'chosen', 'retailer': 'A', 'name': 'Kips Vega smeerworst', 'package': '125 g'}
    item = {'query': 'smeerworst', 'quantity': 300, 'unit': 'g', 'selectedProduct': {k: product[k] for k in ('productId', 'retailer', 'name')}}
    chosen, other, unknown = bridge.evaluate([
        {'item': item, 'product': product},
        {'item': item, 'product': {**product, 'productId': 'other'}},
        {'item': item, 'product': {**product, 'package': ''}},
    ])
    assert chosen['status'] == 'accepted'
    assert chosen['packages'] == 3
    assert other['status'] == 'rejected'
    assert unknown['status'] == 'quantity_unknown'
