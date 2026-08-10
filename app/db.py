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

CREATE TABLE IF NOT EXISTS promotions (
    brand TEXT NOT NULL,
    country TEXT NOT NULL,
    banner TEXT NOT NULL,
    year_week TEXT NOT NULL,
    is_promo INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (brand, country, banner, year_week)
);

-- One row per Outlook message+attachment the auto-importer has handled, so
-- a restart or an overlapping poll never re-imports the same mail.
CREATE TABLE IF NOT EXISTS email_imports (
    message_id TEXT NOT NULL,
    attachment_name TEXT NOT NULL,
    subject TEXT,
    received_at TEXT,
    processed_at TEXT,
    status TEXT,
    message TEXT,
    PRIMARY KEY (message_id, attachment_name)
);
"""

# Superseded default expressions for avg_sellout_per_store, in historical
# order. A deployed database whose stored expression still matches one of
# these gets auto-upgraded to the current default; a user-edited expression
# never matches and is left untouched.
_OLD_AVG_SELLOUT_EXPRS = [
    # v1: divided ALL selected brands' volume by only the configured stores.
    "total_sales_volume / num_stores",
    # v2: fixed the numerator scope, but despite being named/described
    # "per store per week" it summed volume across every week in the
    # selection without dividing by the number of weeks.
    "store_sales_volume / num_stores",
]

DEFAULT_KPIS = [
    (
        "avg_sellout_per_store",
        "store_sales_volume / num_stores / num_weeks",
        "Average sellout (units) per store per week: sales volume from "
        "brand/country/banner combos that have a configured store count, "
        "divided by that store count and by the number of weeks in the "
        "current selection. Combos without a store count are excluded from "
        "both sides so they can't skew the average.",
    ),
]


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout: wait up to 15s for a competing writer instead of failing with
    # "database is locked" when two browser sessions import at once. WAL
    # journal lets readers proceed while a write transaction is open.
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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

    # Upgrade the built-in avg_sellout_per_store KPI on already-deployed
    # databases whenever its stored expression still matches a superseded
    # default (see _OLD_AVG_SELLOUT_EXPRS for what each old version got
    # wrong) — a user's own edit never matches and is never overwritten.
    # The description is refreshed along with the expression so the shown
    # explanation always matches the formula actually being evaluated.
    placeholders = ",".join("?" for _ in _OLD_AVG_SELLOUT_EXPRS)
    conn.execute(
        f"UPDATE kpi_definitions SET expression = ?, description = ? "
        f"WHERE name = 'avg_sellout_per_store' AND expression IN ({placeholders})",
        (DEFAULT_KPIS[0][1], DEFAULT_KPIS[0][2], *_OLD_AVG_SELLOUT_EXPRS),
    )

    # Purge rows written by the pre-per-row-brand parser: a multi-brand export
    # ("Brand: ALESSANDRO;DEPEND GEL IQ") used to land under one combined
    # brand literally containing ';'. Real brand names never contain ';', so
    # these rows are unambiguously corrupt — they polluted the brand filter
    # and sat outside each brand's own history. Re-importing the same file
    # restores the data under the correct brands.
    conn.execute("DELETE FROM fact_sales WHERE brand LIKE '%;%'")
    conn.execute("DELETE FROM items WHERE brand LIKE '%;%'")
    conn.execute("DELETE FROM store_counts WHERE brand LIKE '%;%'")
    conn.execute("DELETE FROM promotions WHERE brand LIKE '%;%'")


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


def get_promotions() -> set[tuple[str, str, str, str]]:
    """Set of (brand, country, banner, year_week) keys marked as a promotion
    week by the user."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT brand, country, banner, year_week FROM promotions WHERE is_promo = 1"
        ).fetchall()
        return {(r["brand"], r["country"], r["banner"], r["year_week"]) for r in rows}


def set_promotions(rows: list[tuple]):
    """Upsert a batch of (brand, country, banner, year_week, is_promo) marks
    in a single transaction."""
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO promotions (brand, country, banner, year_week, is_promo)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(brand, country, banner, year_week) DO UPDATE SET
                is_promo=excluded.is_promo
            """,
            [(b, c, bn, yw, int(bool(p))) for (b, c, bn, yw, p) in rows],
        )


def set_meta_value(key: str, value: str):
    """Standalone setter for app_meta (set_meta needs a caller-held conn)."""
    with get_conn() as conn:
        set_meta(conn, key, value)


def is_email_processed(message_id: str, attachment_name: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM email_imports WHERE message_id=? AND attachment_name=?",
            (message_id, attachment_name),
        ).fetchone()
        return row is not None


def record_email_import(message_id, attachment_name, subject, received_at, status, message):
    """Mark a message+attachment as handled. Recorded for failures too, but
    with a 'failed' status — see auto_import for the retry policy."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO email_imports
                (message_id, attachment_name, subject, received_at, processed_at, status, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id, attachment_name) DO UPDATE SET
                processed_at=excluded.processed_at,
                status=excluded.status,
                message=excluded.message
            """,
            (message_id, attachment_name, subject, received_at,
             dt.datetime.utcnow().isoformat(), status, message),
        )


def get_email_imports(limit: int = 25) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT message_id, attachment_name, subject, received_at, processed_at, "
            "status, message FROM email_imports ORDER BY processed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


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
