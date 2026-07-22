"""SQLite persistence layer: items, fact_sales, store_counts, kpi
definitions, import log, and app-level metadata (timestamps)."""

from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "analytics.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    sku TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    article_description TEXT,
    headgroup TEXT,
    size TEXT,
    colour TEXT,
    type TEXT,
    package_content TEXT,
    consumer_price REAL,
    gtin TEXT
);

CREATE TABLE IF NOT EXISTS fact_sales (
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    banner TEXT NOT NULL,
    sku TEXT NOT NULL,
    year_week TEXT NOT NULL,
    sales_volume REAL NOT NULL DEFAULT 0,
    sales_value REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (brand, country, banner, sku, year_week)
);

CREATE TABLE IF NOT EXISTS store_counts (
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    banner TEXT NOT NULL,
    year_week TEXT NOT NULL DEFAULT 'DEFAULT',
    num_stores INTEGER NOT NULL,
    PRIMARY KEY (brand, country, banner, year_week)
);

CREATE TABLE IF NOT EXISTS kpi_definitions (
    name TEXT PRIMARY KEY,
    expression TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    brand TEXT,
    country TEXT,
    banner TEXT,
    imported_at TEXT,
    rows_loaded INTEGER,
    status TEXT,
    message TEXT
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_KPIS = [
    (
        "avg_sellout_per_store",
        "total_sales_volume / num_stores",
        "Average sellout (units) per store per week: total sales volume in "
        "scope divided by configured number of stores.",
    ),
]


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn):
    """Lightweight, idempotent schema migrations for databases created by an
    earlier version (CREATE TABLE IF NOT EXISTS never adds new columns)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(store_counts)")}
    if "target_rev_per_store" not in existing:
        # Per brand+country+banner target for average revenue per store per
        # week — drawn as a target line on the KPI chart. Set in Settings.
        conn.execute("ALTER TABLE store_counts ADD COLUMN target_rev_per_store REAL")


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        for name, expr, desc in DEFAULT_KPIS:
            conn.execute(
                "INSERT OR IGNORE INTO kpi_definitions (name, expression, description) "
                "VALUES (?, ?, ?)",
                (name, expr, desc),
            )


def upsert_items(conn, items: list[dict]):
    for it in items:
        conn.execute(
            """
            INSERT INTO items (sku, brand, article_description, headgroup, size,
                                colour, type, package_content, consumer_price, gtin)
            VALUES (:sku, :brand, :article_description, :headgroup, :size,
                    :colour, :type, :package_content, :consumer_price, :gtin)
            ON CONFLICT(sku) DO UPDATE SET
                brand=excluded.brand,
                article_description=excluded.article_description,
                headgroup=excluded.headgroup,
                size=excluded.size,
                colour=excluded.colour,
                type=excluded.type,
                package_content=excluded.package_content,
                consumer_price=excluded.consumer_price,
                gtin=excluded.gtin
            """,
            it,
        )


def upsert_facts(conn, facts: list[dict]) -> int:
    for f in facts:
        conn.execute(
            """
            INSERT INTO fact_sales (brand, country, banner, sku, year_week,
                                     sales_volume, sales_value)
            VALUES (:brand, :country, :banner, :sku, :year_week,
                    :sales_volume, :sales_value)
            ON CONFLICT(brand, country, banner, sku, year_week) DO UPDATE SET
                sales_volume=excluded.sales_volume,
                sales_value=excluded.sales_value
            """,
            f,
        )
    return len(facts)


def log_import(conn, filename, brand, country, banner, rows_loaded, status, message):
    conn.execute(
        """
        INSERT INTO import_log (filename, brand, country, banner, imported_at,
                                 rows_loaded, status, message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            filename,
            brand,
            country,
            banner,
            dt.datetime.utcnow().isoformat(),
            rows_loaded,
            status,
            message,
        ),
    )


def set_meta(conn, key: str, value: str):
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(key: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def load_parsed_file(parsed) -> tuple[int, list[str]]:
    """Persist a ParsedFile (see ingestion.py) into the database, updating
    timestamps and the import log. Returns (rows_loaded, warnings)."""
    now = dt.datetime.utcnow().isoformat()
    with get_conn() as conn:
        upsert_items(conn, parsed.items)
        rows_loaded = upsert_facts(conn, parsed.facts)
        log_import(
            conn,
            parsed.source_filename,
            parsed.brand,
            parsed.country,
            parsed.banner,
            rows_loaded,
            "ok" if not parsed.warnings else "ok_with_warnings",
            "; ".join(parsed.warnings),
        )
        set_meta(conn, "last_received_at", now)
        set_meta(conn, "last_analyzed_at", now)
    return rows_loaded, parsed.warnings


def get_store_count(brand: str, country: str, banner: str, year_week: str) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT num_stores FROM store_counts WHERE brand=? AND country=? AND banner=? AND year_week=?",
            (brand, country, banner, year_week),
        ).fetchone()
        if row:
            return row["num_stores"]
        row = conn.execute(
            "SELECT num_stores FROM store_counts WHERE brand=? AND country=? AND banner=? AND year_week='DEFAULT'",
            (brand, country, banner),
        ).fetchone()
        return row["num_stores"] if row else None


def set_store_count(brand: str, country: str, banner: str, year_week: str, num_stores: int):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO store_counts (brand, country, banner, year_week, num_stores)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(brand, country, banner, year_week) DO UPDATE SET
                num_stores=excluded.num_stores
            """,
            (brand, country, banner, year_week, num_stores),
        )


def get_target(brand: str, country: str, banner: str) -> float | None:
    """Target average revenue per store per week for a brand+country+banner
    (stored on the DEFAULT row). None if unset."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT target_rev_per_store FROM store_counts "
            "WHERE brand=? AND country=? AND banner=? AND year_week='DEFAULT'",
            (brand, country, banner),
        ).fetchone()
        return row["target_rev_per_store"] if row and row["target_rev_per_store"] is not None else None


def set_target(brand: str, country: str, banner: str, target: float | None):
    """Set (or clear, with None) the revenue-per-store target on the DEFAULT
    row, creating that row if it does not exist yet."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO store_counts (brand, country, banner, year_week, num_stores, target_rev_per_store)
            VALUES (?, ?, ?, 'DEFAULT', 0, ?)
            ON CONFLICT(brand, country, banner, year_week) DO UPDATE SET
                target_rev_per_store=excluded.target_rev_per_store
            """,
            (brand, country, banner, target),
        )


def get_last_imports() -> list[dict]:
    """Most recent import per brand+country+banner, with its status — used
    for the per-brand freshness indicator on the dashboard."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT brand, country, banner, imported_at, status, rows_loaded
            FROM import_log
            WHERE id IN (
                SELECT MAX(id) FROM import_log
                WHERE brand IS NOT NULL
                GROUP BY brand, country, banner
            )
            ORDER BY brand, country, banner
            """
        ).fetchall()
        return [dict(r) for r in rows]
