from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import os


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shopping_items(
 id INTEGER PRIMARY KEY, query TEXT NOT NULL, ean TEXT, quantity REAL NOT NULL DEFAULT 1,
 unit TEXT NOT NULL DEFAULT 'stuk', preferred_brand TEXT, allow_alternatives INTEGER NOT NULL DEFAULT 1,
 selected_product_id TEXT, selected_name TEXT, selected_retailer TEXT, selected_image_url TEXT,
 selected_product_url TEXT, display_name TEXT, product_family TEXT,
 attributes_json TEXT NOT NULL DEFAULT '[]', exclusions_json TEXT NOT NULL DEFAULT '[]',
 match_mode TEXT NOT NULL DEFAULT 'basis', review_required INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS shopping_preferences(
 normalized_query TEXT PRIMARY KEY, display_query TEXT NOT NULL, quantity REAL NOT NULL,
 unit TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS offer_cache(
 provider TEXT NOT NULL, cache_key TEXT NOT NULL, payload TEXT NOT NULL, fetched_at TEXT NOT NULL,
 PRIMARY KEY(provider, cache_key)
);
"""


class Database:
    def __init__(self, path: Path, test_mode: bool = False):
        self.path = path
        self.test_mode = test_mode

    def _driver(self):
        import sqlite3
        return sqlite3

    def initialize_local(self) -> None:
        """Create the password-free database used by BoodschappenWijzer."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect(b"") as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.execute("INSERT OR REPLACE INTO settings VALUES('vehicle_cost_per_km','0.25')")
            conn.commit()
        os.chmod(self.path, 0o600)

    @staticmethod
    def _migrate(conn) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(shopping_items)")}
        additions = {
            "allow_alternatives": "INTEGER NOT NULL DEFAULT 1",
            "selected_product_id": "TEXT", "selected_name": "TEXT", "selected_retailer": "TEXT",
            "selected_image_url": "TEXT", "selected_product_url": "TEXT",
            "display_name": "TEXT", "product_family": "TEXT",
            "attributes_json": "TEXT NOT NULL DEFAULT '[]'", "exclusions_json": "TEXT NOT NULL DEFAULT '[]'",
            "match_mode": "TEXT NOT NULL DEFAULT 'basis'", "review_required": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, kind in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE shopping_items ADD COLUMN {name} {kind}")
        conn.execute("CREATE TABLE IF NOT EXISTS shopping_preferences(normalized_query TEXT PRIMARY KEY, display_query TEXT NOT NULL, quantity REAL NOT NULL, unit TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        migrated = conn.execute("SELECT value FROM meta WHERE key='strict_exact_selection_v1'").fetchone()
        if not migrated:
            # Existing exact selections become strict once; later user choices remain intact.
            conn.execute("UPDATE shopping_items SET allow_alternatives=0 WHERE selected_product_id IS NOT NULL")
            conn.execute("INSERT INTO meta(key,value) VALUES('strict_exact_selection_v1','1')")
        intent_migrated = conn.execute("SELECT value FROM meta WHERE key='product_intent_v1'").fetchone()
        if not intent_migrated:
            conn.execute("""UPDATE shopping_items SET
                display_name=COALESCE(selected_name,query),
                product_family=CASE
                  WHEN lower(query) LIKE '%melk%' THEN 'melk'
                  WHEN lower(query) LIKE '%kaas%' THEN 'kaas'
                  WHEN lower(query) LIKE '%kip%' THEN 'kipfilet'
                  WHEN lower(query) LIKE '%bol%' THEN 'broodjes'
                  WHEN lower(query) LIKE '%brood%' THEN 'brood'
                  ELSE 'overig' END,
                match_mode=CASE WHEN selected_product_id IS NULL THEN 'basis'
                  WHEN allow_alternatives=1 THEN 'exact-met-equivalenten' ELSE 'strikt-exact' END,
                review_required=1""")
            conn.execute("INSERT INTO meta(key,value) VALUES('product_intent_v1','1')")
        conn.commit()

    @contextmanager
    def connect(self, _key: bytes = b""):
        driver = self._driver()
        conn = driver.connect(str(self.path))
        conn.row_factory = driver.Row
        try:
            yield conn
        finally:
            conn.close()
