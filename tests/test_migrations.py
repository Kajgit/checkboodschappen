import sqlite3
from app.db import Database


def test_existing_shopping_table_gets_selector_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE shopping_items(id INTEGER PRIMARY KEY, query TEXT)")
    Database._migrate(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(shopping_items)")}
    assert {"allow_alternatives", "selected_product_id", "selected_image_url", "selected_product_url"} <= columns
    assert {"product_family", "attributes_json", "match_mode", "review_required"} <= columns


def test_existing_item_requires_one_time_intent_review():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE shopping_items(id INTEGER PRIMARY KEY, query TEXT, allow_alternatives INTEGER, selected_product_id TEXT, selected_name TEXT)")
    conn.execute("INSERT INTO shopping_items(query,allow_alternatives) VALUES('Halfvolle melk',1)")
    Database._migrate(conn)
    row = conn.execute("SELECT product_family,match_mode,review_required FROM shopping_items").fetchone()
    assert row == ("melk", "basis", 1)
