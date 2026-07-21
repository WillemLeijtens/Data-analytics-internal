from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

import db
import ingestion
import kpi

st.set_page_config(page_title="Sellout Analytics", layout="wide")


def _check_password() -> bool:
    """Simple shared-password gate. The password is read from
    st.secrets['app_password'] (set via Render's environment/secrets, or
    .streamlit/secrets.toml locally) — never hardcoded in source."""
    configured = os.environ.get("STREAMLIT_APP_PASSWORD")
    if not configured:
        try:
            configured = st.secrets.get("app_password")
        except FileNotFoundError:
            configured = None
    if not configured:
        st.warning(
            "No app_password configured in secrets — running without a "
            "login gate. Set app_password before deploying publicly."
        )
        return True

    if st.session_state.get("authenticated"):
        return True

    st.title("Sellout Analytics — sign in")
    pwd = st.text_input("Password", type="password")
    if st.button("Sign in"):
        if pwd == configured:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


if not _check_password():
    st.stop()

db.init_db()


def _fmt_ts(value: str | None) -> str:
    if not value:
        return "never"
    return value.replace("T", " ").split(".")[0] + " UTC"


def page_upload():
    st.header("Import weekly sellout files")
    st.caption(
        "Upload one or more DWH sellout export files (.xlsx). Brand, country "
        "and retail banner are read from each file's own metadata block, "
        "cross-checked against the filename."
    )
    uploaded = st.file_uploader(
        "Excel files", type=["xlsx"], accept_multiple_files=True
    )
    if not uploaded:
        return

    for f in uploaded:
        st.subheader(f.name)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(f.getbuffer())
            tmp_path = tmp.name

        try:
            parsed = ingestion.parse_workbook(tmp_path, f.name)
        except Exception as e:
            st.error(f"Failed to parse {f.name}: {e}")
            continue
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Brand", parsed.brand or "?")
        c2.metric("Country", parsed.country or "?")
        c3.metric("Banner", parsed.banner or "?")
        c4.metric("SKUs found", len(parsed.items))

        if parsed.warnings:
            for w in parsed.warnings:
                st.warning(w)

        preview = pd.DataFrame(parsed.facts[:10])
        if not preview.empty:
            st.dataframe(preview, use_container_width=True)

        if st.button(f"Confirm & load '{f.name}'", key=f"load_{f.name}"):
            rows_loaded, _ = db.load_parsed_file(parsed)
            st.success(f"Loaded {rows_loaded} rows from {f.name}.")

    st.divider()
    st.subheader("Recent imports")
    with db.get_conn() as conn:
        log_df = pd.read_sql_query(
            "SELECT filename, brand, country, banner, imported_at, rows_loaded, status, message "
            "FROM import_log ORDER BY id DESC LIMIT 20",
            conn,
        )
    st.dataframe(log_df, use_container_width=True)


def _load_facts() -> pd.DataFrame:
    with db.get_conn() as conn:
        return pd.read_sql_query(
            """
            SELECT f.brand, f.country, f.banner, f.sku, f.year_week,
                   f.sales_volume, f.sales_value, i.article_description
            FROM fact_sales f
            LEFT JOIN items i ON i.sku = f.sku
            """,
            conn,
        )


def page_dashboard():
    st.header("Dashboard")
    c1, c2 = st.columns(2)
    c1.metric("Last data received", _fmt_ts(db.get_meta("last_received_at")))
    c2.metric("Last analyzed / updated", _fmt_ts(db.get_meta("last_analyzed_at")))

    df = _load_facts()
    if df.empty:
        st.info("No data loaded yet — go to 'Import' to upload files.")
        return

    brands = sorted(df["brand"].unique())
    countries = sorted(df["country"].unique())
    banners = sorted(df["banner"].unique())

    fc1, fc2, fc3 = st.columns(3)
    sel_brands = fc1.multiselect("Brand", brands, default=brands)
    sel_countries = fc2.multiselect("Country", countries, default=countries)
    sel_banners = fc3.multiselect("Banner", banners, default=banners)

    scoped = df[
        df["brand"].isin(sel_brands)
        & df["country"].isin(sel_countries)
        & df["banner"].isin(sel_banners)
    ]
    if scoped.empty:
        st.warning("No data matches the current filter selection.")
        return

    weekly_totals = (
        scoped.groupby("year_week")[["sales_volume", "sales_value"]]
        .sum()
        .sort_index()
        .reset_index()
    )

    st.subheader("Total sellout per week")
    st.line_chart(weekly_totals.set_index("year_week")["sales_volume"], height=300)

    st.subheader("Total sales value per week")
    st.line_chart(weekly_totals.set_index("year_week")["sales_value"], height=300)

    st.subheader("Sellout per item per week")
    item_pivot = scoped.pivot_table(
        index=["sku", "article_description"],
        columns="year_week",
        values="sales_volume",
        aggfunc="sum",
        fill_value=0,
    )
    st.dataframe(item_pivot, use_container_width=True)

    st.subheader("KPIs")
    with db.get_conn() as conn:
        kpi_defs = pd.read_sql_query("SELECT name, expression, description FROM kpi_definitions", conn)

    num_stores_total = 0
    for brand in sel_brands:
        for country in sel_countries:
            for banner in sel_banners:
                n = db.get_store_count(brand, country, banner, "DEFAULT")
                if n:
                    num_stores_total += n

    variables = {
        "total_sales_volume": float(scoped["sales_volume"].sum()),
        "total_sales_value": float(scoped["sales_value"].sum()),
        "num_stores": float(num_stores_total) if num_stores_total else float("nan"),
        "num_skus": float(scoped["sku"].nunique()),
        "num_weeks": float(scoped["year_week"].nunique()),
    }

    if not num_stores_total:
        st.warning(
            "No store count configured for the selected brand/country/banner "
            "combination(s) — set it under Settings to compute store-based KPIs."
        )

    kpi_cols = st.columns(max(len(kpi_defs), 1))
    for col, row in zip(kpi_cols, kpi_defs.itertuples()):
        try:
            value = kpi.evaluate_kpi(row.expression, variables)
            col.metric(row.name, f"{value:,.2f}", help=row.description)
        except kpi.KpiError as e:
            col.metric(row.name, "error", help=str(e))


def page_settings():
    st.header("Settings")

    st.subheader("Store counts")
    st.caption(
        "Number of stores per brand + country + banner (used by store-based "
        "KPIs). Not present in the source files — set manually. A 'DEFAULT' "
        "row applies unless a specific year-week override exists."
    )
    df = _load_facts()
    combos = sorted(set(zip(df["brand"], df["country"], df["banner"]))) if not df.empty else []

    for brand, country, banner in combos:
        current = db.get_store_count(brand, country, banner, "DEFAULT") or 0
        cols = st.columns([2, 1, 1, 1, 1])
        cols[0].write(f"**{brand}** / {country} / {banner}")
        new_val = cols[1].number_input(
            "Stores", min_value=0, value=int(current), key=f"stores_{brand}_{country}_{banner}", label_visibility="collapsed"
        )
        if cols[2].button("Save", key=f"save_{brand}_{country}_{banner}"):
            db.set_store_count(brand, country, banner, "DEFAULT", int(new_val))
            st.success("Saved.")

    if not combos:
        st.info("Import data first to configure store counts per brand/country/banner.")

    st.divider()
    st.subheader("KPI definitions")
    st.caption(
        "Available variables: total_sales_volume, total_sales_value, "
        "num_stores, num_skus, num_weeks. Only + - * / and parentheses are allowed."
    )
    with db.get_conn() as conn:
        kpi_df = pd.read_sql_query("SELECT name, expression, description FROM kpi_definitions", conn)
    st.dataframe(kpi_df, use_container_width=True)

    with st.form("new_kpi"):
        name = st.text_input("KPI name")
        expr = st.text_input("Expression", placeholder="total_sales_volume / num_stores")
        desc = st.text_area("Description")
        submitted = st.form_submit_button("Add / update KPI")
        if submitted:
            error = kpi.validate_expression(expr) if expr else "Expression is required"
            if not name:
                st.error("KPI name is required.")
            elif error:
                st.error(f"Invalid expression: {error}")
            else:
                with db.get_conn() as conn:
                    conn.execute(
                        "INSERT INTO kpi_definitions (name, expression, description) VALUES (?, ?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET expression=excluded.expression, description=excluded.description",
                        (name, expr, desc),
                    )
                st.success(f"KPI '{name}' saved.")
                st.rerun()


PAGES = {
    "Import": page_upload,
    "Dashboard": page_dashboard,
    "Settings": page_settings,
}

st.sidebar.title("Sellout Analytics")
choice = st.sidebar.radio("Navigate", list(PAGES.keys()))
PAGES[choice]()
