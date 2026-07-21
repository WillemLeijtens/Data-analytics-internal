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

The SQLite database is created at `data/analytics.db` on first run. Set
`STREAMLIT_APP_PASSWORD` in the environment to require a password before the
app loads (recommended once any real data is in it); without it, the app
runs with no login and shows a warning.

## Deploying (Render.com)

This repo includes a `Dockerfile` and `render.yaml` set up for Render, with
a **persistent disk** mounted at `/app/data` — required so the SQLite
database (and all accumulated weekly history) survives future deploys.
Plain Streamlit Community Cloud is not used here because its filesystem
resets on every redeploy, which would silently wipe historical data.

Steps:
1. Push this repo to GitHub (already done if you're reading this from the
   deployed branch).
2. In the Render dashboard: New → Blueprint → connect this repo. Render
   will read `render.yaml` and provision the web service + disk
   automatically (uses their "Starter" plan, the cheapest tier that
   supports a persistent disk — check current pricing on Render's site).
3. In the service's Environment tab, set `STREAMLIT_APP_PASSWORD` to a
   password of your choice (marked `sync: false` in render.yaml so Render
   prompts you for it rather than storing it in the repo).
4. Deploy. Render gives you a public `https://<service-name>.onrender.com`
   URL — that's the "access from anywhere" link. Bookmark it; share the
   password separately (e.g. a password manager), not over email/chat.

To redeploy after future code changes, just push to this branch (or merge
to main and point Render at that branch) — the persistent disk means
`data/analytics.db` is untouched by the redeploy.

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
