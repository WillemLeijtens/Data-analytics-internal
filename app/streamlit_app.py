from __future__ import annotations

import os
import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import db
import ingestion
import kpi

# Vega-Lite axis that prefixes every tick label with a euro sign, so money
# charts are visually distinct from unit/volume charts.
EUR_AXIS_LABEL = "'€ ' + format(datum.value, ',.0f')"


def eur(value: float) -> str:
    """Format a number as euros for st.metric tiles and text."""
    return f"€ {value:,.0f}"

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


def _import_health():
    """Return (ok_count, total_count) over the most recent import per
    brand+country+banner feed."""
    last_imports = db.get_last_imports()
    total = len(last_imports)
    ok = sum(1 for imp in last_imports if str(imp.get("status", "")).startswith("ok"))
    return ok, total


def _import_summary_indicator():
    """One combined status light for the dashboard: green if every feed's
    latest import succeeded, yellow if some did, red if none did."""
    ok, total = _import_health()
    help_text = (
        "Overall import health across all brand feeds. Green: every brand's "
        "most recent import succeeded. Yellow: one or more failed. Red: all "
        "failed. See the 'Import status' tab for the per-brand breakdown."
    )
    if total == 0:
        st.info("No imports recorded yet — upload files on the Import tab.")
        return
    if ok == total:
        dot, colour, msg = "🟢", "green", "All imports OK"
    elif ok == 0:
        dot, colour, msg = "🔴", "red", "All imports failed"
    else:
        dot, colour, msg = "🟡", "orange", "Some imports failed"
    st.subheader("Import status", help=help_text)
    st.markdown(f"{dot} :{colour}[**{msg}** — {ok}/{total} brand feeds OK]")


def _import_status_detail():
    """Full per-brand import breakdown, shown on its own tab."""
    st.header("Import status per brand")
    st.caption(
        "The most recent import for each brand / country / banner feed. Green "
        "means that latest import succeeded; red means it failed (or the "
        "newest attempt errored). Use it to spot a brand whose weekly Monday "
        "file didn't come through."
    )
    last_imports = db.get_last_imports()
    if not last_imports:
        st.info("No imports recorded yet.")
        return
    for imp in last_imports:
        ok = str(imp.get("status", "")).startswith("ok")
        dot = "🟢" if ok else "🔴"
        ts = _fmt_ts(imp.get("imported_at"))
        colour = "green" if ok else "red"
        label = f"{imp['brand']} · {imp['country']}/{imp['banner']}"
        rows = imp.get("rows_loaded")
        detail = f"{rows} rows" if rows is not None else ""
        st.markdown(f"{dot} **{label}** — :{colour}[{ts}] {detail}")


def _highlight_tiles(scoped: pd.DataFrame, num_stores_total: int):
    """Top-of-dashboard KPI tiles for the single most recent week in scope."""
    most_recent_week = scoped["year_week"].max()
    week_df = scoped[scoped["year_week"] == most_recent_week]
    total_value = float(week_df["sales_value"].sum())
    total_volume = float(week_df["sales_volume"].sum())

    st.subheader(
        f"Most recent week — {most_recent_week}",
        help=(
            "Headline figures for the latest year-week present in the current "
            "filter selection: total sales value (€), total sellout volume "
            "(units), and average revenue per store that week (value ÷ number "
            "of stores configured in Settings)."
        ),
    )
    t1, t2, t3 = st.columns(3)
    t1.metric("Sales value (this week)", eur(total_value))
    t2.metric("Sellout volume (this week)", f"{total_volume:,.0f}")
    if num_stores_total:
        t3.metric("Avg revenue / store", eur(total_value / num_stores_total))
    else:
        t3.metric("Avg revenue / store", "—", help="Set store counts in Settings.")


def page_dashboard():
    st.header("Dashboard")
    c1, c2 = st.columns(2)
    c1.metric("Last data received", _fmt_ts(db.get_meta("last_received_at")))
    c2.metric("Last analyzed / updated", _fmt_ts(db.get_meta("last_analyzed_at")))

    _import_summary_indicator()

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

    # Store counts and targets, summed/weighted over the brand+country+banner
    # combinations actually present in the current selection.
    scoped_combos = list(
        scoped[["brand", "country", "banner"]].drop_duplicates().itertuples(index=False)
    )
    num_stores_total = 0
    target_num = 0.0
    target_den = 0
    for b, c, bn in scoped_combos:
        n = db.get_store_count(b, c, bn, "DEFAULT") or 0
        t = db.get_target(b, c, bn)
        num_stores_total += n
        if t is not None and n:
            target_num += t * n
            target_den += n
    combined_target = (target_num / target_den) if target_den else None

    _highlight_tiles(scoped, num_stores_total)

    weekly_totals = (
        scoped.groupby("year_week")[["sales_volume", "sales_value"]]
        .sum()
        .sort_index()
        .reset_index()
    )

    st.subheader(
        "Total sellout per week",
        help=(
            "Total sellout volume (units sold) summed across every SKU in the "
            "current filter selection, per year-week."
        ),
    )
    st.line_chart(weekly_totals.set_index("year_week")["sales_volume"], height=300)

    st.subheader(
        "Total sales value per week",
        help=(
            "Total sales value in euros summed across every SKU in the current "
            "filter selection, per year-week."
        ),
    )
    value_chart = (
        alt.Chart(weekly_totals)
        .mark_line(point=True)
        .encode(
            x=alt.X("year_week:O", title="Year-week"),
            y=alt.Y(
                "sales_value:Q",
                title="Sales value (€)",
                axis=alt.Axis(labelExpr=EUR_AXIS_LABEL),
            ),
            tooltip=[
                alt.Tooltip("year_week:O", title="Week"),
                alt.Tooltip("sales_value:Q", title="Value (€)", format=",.0f"),
            ],
        )
        .properties(height=300)
    )
    st.altair_chart(value_chart, use_container_width=True)

    # Average revenue per store per week, with a settable target line.
    st.subheader(
        "Avg revenue per store per week",
        help=(
            "Total sales value that week ÷ number of stores (from Settings), "
            "for the current selection. The dashed line is the target set per "
            "brand in Settings (weighted by store count when several brands "
            "are selected)."
        ),
    )
    if num_stores_total:
        avg_df = weekly_totals.copy()
        avg_df["avg_rev"] = avg_df["sales_value"] / num_stores_total
        avg_line = (
            alt.Chart(avg_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("year_week:O", title="Year-week"),
                y=alt.Y(
                    "avg_rev:Q",
                    title="Avg revenue / store (€)",
                    axis=alt.Axis(labelExpr=EUR_AXIS_LABEL),
                ),
                tooltip=[
                    alt.Tooltip("year_week:O", title="Week"),
                    alt.Tooltip("avg_rev:Q", title="Avg € / store", format=",.0f"),
                ],
            )
            .properties(height=300)
        )
        if combined_target is not None:
            rule = (
                alt.Chart(pd.DataFrame({"target": [combined_target]}))
                .mark_rule(color="red", strokeDash=[6, 4])
                .encode(y="target:Q")
            )
            text = (
                alt.Chart(pd.DataFrame({"target": [combined_target]}))
                .mark_text(align="left", dx=5, dy=-5, color="red")
                .encode(y="target:Q", text=alt.value(f"target € {combined_target:,.0f}"))
            )
            avg_line = avg_line + rule + text
        st.altair_chart(avg_line, use_container_width=True)
    else:
        st.caption("Set store counts in Settings to see this chart.")

    st.subheader(
        "Sellout per item per week",
        help=(
            "Sellout volume (units) broken down per SKU (rows) and year-week "
            "(columns) for the current selection."
        ),
    )
    item_pivot = scoped.pivot_table(
        index=["sku", "article_description"],
        columns="year_week",
        values="sales_volume",
        aggfunc="sum",
        fill_value=0,
    )
    st.dataframe(item_pivot, use_container_width=True)

    st.subheader(
        "KPIs",
        help=(
            "Configurable KPIs (defined in Settings), evaluated over the whole "
            "current filter selection across all weeks shown."
        ),
    )
    with db.get_conn() as conn:
        kpi_defs = pd.read_sql_query("SELECT name, expression, description FROM kpi_definitions", conn)

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

    st.subheader("Store counts & targets")
    st.caption(
        "Per brand + country + banner: the number of stores (used by "
        "store-based KPIs) and the weekly target for average revenue per "
        "store (drawn as a target line on the dashboard). Neither is present "
        "in the source files — set them manually here."
    )
    df = _load_facts()
    combos = sorted(set(zip(df["brand"], df["country"], df["banner"]))) if not df.empty else []

    hdr = st.columns([3, 2, 2, 1])
    hdr[0].markdown("**Brand / country / banner**")
    hdr[1].markdown("**# stores**")
    hdr[2].markdown("**Target avg € / store / week**")

    for brand, country, banner in combos:
        current = db.get_store_count(brand, country, banner, "DEFAULT") or 0
        current_target = db.get_target(brand, country, banner) or 0.0
        cols = st.columns([3, 2, 2, 1])
        cols[0].write(f"**{brand}** / {country} / {banner}")
        new_val = cols[1].number_input(
            "Stores", min_value=0, value=int(current),
            key=f"stores_{brand}_{country}_{banner}", label_visibility="collapsed",
        )
        new_target = cols[2].number_input(
            "Target", min_value=0.0, value=float(current_target), step=100.0,
            key=f"target_{brand}_{country}_{banner}", label_visibility="collapsed",
        )
        if cols[3].button("Save", key=f"save_{brand}_{country}_{banner}"):
            db.set_store_count(brand, country, banner, "DEFAULT", int(new_val))
            db.set_target(brand, country, banner, float(new_target) if new_target > 0 else None)
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


def page_import_status():
    _import_status_detail()


PAGES = {
    "Import": page_upload,
    "Dashboard": page_dashboard,
    "Import status": page_import_status,
    "Settings": page_settings,
}

st.sidebar.title("Sellout Analytics")
choice = st.sidebar.radio("Navigate", list(PAGES.keys()))
PAGES[choice]()
