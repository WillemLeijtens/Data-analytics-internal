"""Regressietests voor de migraties van de Streamlit-database."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


def load_legacy_db():
    path = Path(__file__).resolve().parents[1] / "app" / "db.py"
    spec = importlib.util.spec_from_file_location("legacy_app_db", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def item(brand: str, description: str) -> dict:
    return {
        "sku": "SHARED-1", "brand": brand,
        "article_description": description, "headgroup": None,
        "size": None, "colour": None, "type": None,
        "package_content": None, "consumer_price": None, "gtin": None,
    }


def test_item_key_migrates_to_include_brand(tmp_path):
    """Twee merken kunnen hetzelfde SKU-nummer voeren; met de oude sleutel
    overschreef het ene merk de artikelgegevens van het andere."""
    module = load_legacy_db()
    module.DB_PATH = tmp_path / "analytics.db"

    with sqlite3.connect(module.DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE items (
                retailer TEXT NOT NULL, sku TEXT NOT NULL, brand TEXT NOT NULL,
                article_description TEXT, headgroup TEXT, size TEXT, colour TEXT,
                type TEXT, package_content TEXT, consumer_price REAL, gtin TEXT,
                PRIMARY KEY (retailer, sku)
            )
        """)
        conn.execute(
            "INSERT INTO items (retailer, sku, brand, article_description) "
            "VALUES ('KRUIDVAT', 'SHARED-1', 'BRAND_A', 'A')")

    module.init_db()
    with module.get_conn() as conn:
        assert module._pk_columns(conn, "items") == ["retailer", "brand", "sku"]
        module.upsert_items(conn, "KRUIDVAT", [item("BRAND_B", "B")])
        rows = conn.execute(
            "SELECT brand, article_description FROM items ORDER BY brand").fetchall()
        assert [tuple(r) for r in rows] == [("BRAND_A", "A"), ("BRAND_B", "B")]
