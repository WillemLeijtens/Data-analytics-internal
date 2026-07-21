# Data Analytics Internal

Internal analytics app for weekly retail sellout data (DWH exports), across
multiple brands, countries, and retail banners.

## Status

**Phase 1 (this repo so far):** manual upload of DWH `.xlsx` exports → parse
→ clean → store in a normalized SQLite fact table → dashboard with
brand/country/banner filters, configurable KPIs, and "last received" /
"last analyzed" timestamps.

**Phase 2 (not yet built):** Microsoft Graph API integration to pull the
same Excel attachments automatically from Outlook every Monday morning and
run them through the same ingestion pipeline.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

The SQLite database is created at `data/analytics.db` on first run.

## Project layout

- `app/ingestion.py` — parses a DWH export file: reads the metadata block
  (Country/Formula/Brand/Weeks/Date), picks the authoritative sheet (the one
  whose row count matches its own trailing "Total" row), forward-fills the
  merged year-week header, extracts item attributes and per-week
  sales volume/value, and reconciles computed weekly totals against the
  file's own Total row and Total column.
- `app/db.py` — SQLite schema and persistence: `items` (item attributes),
  `fact_sales` (brand/country/banner/sku/year_week grain, append-only
  history), `store_counts` (manually configured, per brand+country+banner,
  with optional per-week overrides), `kpi_definitions` (config-driven KPI
  formulas), `import_log`, `app_meta` (timestamps).
- `app/kpi.py` — safe arithmetic expression evaluator for KPI formulas
  (restricted to `+ - * / ()` over a fixed set of scope variables — no
  arbitrary code execution).
- `app/streamlit_app.py` — the UI: Import, Dashboard, Settings pages.

## Data model

One shared fact table across all brands, not separate databases per brand:

```
fact_sales(brand, country, banner, sku, year_week, sales_volume, sales_value)
```

`banner` is the retail chain/formula code (e.g. `KV` = Kruidvat, `TP` =
Trekpleister) — a dimension distinct from country, both read from each
file's own metadata block (not just the filename).

## Known source-file quirks handled

- Each file has 2 sheets; the second repeats every SKU once per GTIN/PLU
  variant. The first sheet (SKU-grain) is authoritative.
- The bottom "Total" row's SKU-number cell holds a row count, not a SKU —
  excluded from data, used only to validate weekly sums.
- A trailing "Total" column pair (grand total per SKU across all weeks) sits
  after the last real week — excluded from the per-week fact rows.
- Some item-attribute columns share a header label (e.g. two "Size"
  columns) — first occurrence is kept.

## Adding a new brand/source format

Ingestion reads brand/country/banner from the file's metadata block, so a
new brand generally needs no code change. If a new export has a
structurally different layout, extend `ingestion.py`'s sheet-selection or
column-detection logic rather than writing a brand-specific pipeline.
