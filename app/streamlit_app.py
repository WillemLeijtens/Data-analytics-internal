from __future__ import annotations

import html
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


def fmt_yw(year_week) -> str:
    """Display a canonical YYYYWW value as YYYY-WW (e.g. 202601 -> 2026-01)."""
    s = str(year_week)
    return f"{s[:4]}-{s[4:]}" if len(s) >= 6 else s


def nl_int(value: float) -> str:
    """Whole number with '.' as the thousands separator (e.g. 51473 -> '51.473')."""
    return f"{value:,.0f}".replace(",", ".")


def nl_money(value: float) -> str:
    """Euro amount with '.' thousands / ',' decimals (e.g. 1234.5 -> '€ 1.234,50')."""
    sign = "-" if value < 0 else ""
    value = abs(value)
    whole = int(value)
    cents = round((value - whole) * 100)
    if cents == 100:  # rounding carried into the next whole euro
        whole += 1
        cents = 0
    whole_str = f"{whole:,}".replace(",", ".")
    return f"{sign}€ {whole_str},{cents:02d}"


_SPARK_CUR_COLOR = "#ef4444"  # solid line: most recent year
_SPARK_PRIOR_COLOR = "#38bdf8"  # dashed line: prior year


def _dual_year_sparkline_svg(cur_vals: list[float], prior_vals: list[float],
                              week_axis: list[int], current_year: str, prior_year: str,
                              fmt_number, width: int = 170, height: int = 40) -> str:
    """Inline SVG with two overlaid polylines (solid = current year, dashed =
    prior year) sharing one y-scale, so relative shape/height is comparable.
    Built by hand because st.column_config.LineChartColumn only supports a
    single monochrome series per cell — not the two-colour year overlay
    needed to compare against the prior year at a glance.

    A transparent, hoverable vertical slice sits behind each week (rather
    than a tiny point marker, which would be hard to land a cursor on given
    how little horizontal space one week gets) carrying a native SVG
    <title> — the browser's own tooltip, no JS needed — showing that
    week's number plus its year-over-year value."""
    all_vals = [v for v in (cur_vals + prior_vals) if v is not None]
    vmax = max(all_vals) if all_vals else 0
    vmax = vmax or 1  # avoid div-by-zero for an all-zero row
    pad = 3
    n = len(week_axis)
    step = (width - 2 * pad) / (n - 1) if n > 1 else 0

    def _points(vals: list[float]) -> str:
        if len(vals) < 2:
            return ""
        pts = []
        for i, v in enumerate(vals):
            x = pad + i * step
            y = height - pad - (v / vmax) * (height - 2 * pad)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    cur_pts = _points(cur_vals)
    prior_pts = _points(prior_vals)
    svg = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           f'xmlns="http://www.w3.org/2000/svg" style="display:block">']
    if prior_pts:
        svg.append(
            f'<polyline points="{prior_pts}" fill="none" stroke="{_SPARK_PRIOR_COLOR}" '
            f'stroke-width="1.5" stroke-dasharray="4,3" opacity="0.9" '
            f'stroke-linecap="round" stroke-linejoin="round" />'
        )
    if cur_pts:
        svg.append(
            f'<polyline points="{cur_pts}" fill="none" stroke="{_SPARK_CUR_COLOR}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />'
        )
    # Hover slices, one per week, on top of the lines.
    slice_width = max(step, 4)
    for i, wk in enumerate(week_axis):
        x = pad + i * step - slice_width / 2
        cur_v = cur_vals[i] if i < len(cur_vals) else 0
        prior_v = prior_vals[i] if i < len(prior_vals) else 0
        tooltip = (
            f"Week {wk}: {fmt_number(cur_v)} ({current_year}) vs "
            f"{fmt_number(prior_v)} ({prior_year})"
        )
        svg.append(
            f'<rect x="{x:.1f}" y="0" width="{slice_width:.1f}" height="{height}" '
            f'fill="transparent"><title>{html.escape(tooltip)}</title></rect>'
        )
    svg.append("</svg>")
    return "".join(svg)


def _yoy_badge_html(cur_total: float, prior_total: float) -> str:
    """Small colour-coded pill: ▲/▼ + percentage vs. the same weeks last
    year, or a neutral dash when there's nothing to compare against."""
    if not prior_total:
        return '<span style="color:#888;">–</span>'
    pct = (cur_total - prior_total) / prior_total * 100
    up = pct >= 0
    bg = "rgba(34,197,94,0.15)" if up else "rgba(249,115,22,0.15)"
    fg = "#22c55e" if up else "#f97316"
    arrow = "▲" if up else "▼"
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 9px;'
        f"border-radius:999px;font-weight:600;font-size:0.85em;"
        f'white-space:nowrap;display:inline-block;">{arrow} {abs(pct):.0f}%</span>'
    )


def _augment_year_week(df: pd.DataFrame) -> pd.DataFrame:
    """Add year / week / yw_label columns derived from the canonical YYYYWW
    year_week, so visuals can compare the same week number across years."""
    out = df.copy()
    yw = out["year_week"].astype(str)
    out["year"] = yw.str[:4]
    out["week"] = pd.to_numeric(yw.str[4:], errors="coerce")
    out["yw_label"] = yw.str[:4] + "-" + yw.str[4:]
    return out


def _yoy_chart(data: pd.DataFrame, value_col: str, y_title: str, money: bool):
    """Year-over-year line chart: week number on the x-axis, one coloured line
    per year with a legend. `data` must already have year / week columns."""
    agg = data.groupby(["year", "week"], as_index=False)[value_col].sum()
    y_axis = alt.Axis(labelExpr=EUR_AXIS_LABEL) if money else alt.Axis()
    tip_fmt = ",.0f"
    return (
        alt.Chart(agg)
        .mark_line(point=True, interpolate="monotone")
        .encode(
            x=alt.X("week:Q", title="Week number", scale=alt.Scale(domain=[1, 53])),
            y=alt.Y(f"{value_col}:Q", title=y_title, axis=y_axis),
            color=alt.Color("year:N", title="Year"),
            tooltip=[
                alt.Tooltip("year:N", title="Year"),
                alt.Tooltip("week:Q", title="Week"),
                alt.Tooltip(f"{value_col}:Q", title=y_title, format=tip_fmt),
            ],
        )
        .properties(height=300)
    )

st.set_page_config(page_title="Data analyse agent", layout="wide")


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

    st.title("Data analyse agent — sign in")
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


def _highlight_tiles(scoped: pd.DataFrame, store_scoped: pd.DataFrame, num_stores_total: int):
    """Top-of-dashboard KPI tiles for the single most recent week in scope."""
    most_recent_week = scoped["year_week"].max()
    week_df = scoped[scoped["year_week"] == most_recent_week]
    total_value = float(week_df["sales_value"].sum())
    total_volume = float(week_df["sales_volume"].sum())
    store_week_value = float(
        store_scoped.loc[store_scoped["year_week"] == most_recent_week, "sales_value"].sum()
    )

    st.subheader(
        f"Most recent week — {most_recent_week}",
        help=(
            "Headline figures for the latest year-week present in the current "
            "filter selection: total sales value (€), total sellout volume "
            "(units), and average revenue per store that week (value ÷ number "
            "of stores configured in Settings). The avg-per-store figure only "
            "counts brand/country/banner combinations that actually have a "
            "store count set — others are excluded from both the euro total "
            "and the store count for this figure, so it stays a fair average "
            "rather than diluting it with unconfigured brands' revenue."
        ),
    )
    t1, t2, t3 = st.columns(3)
    t1.metric("Sales value (this week)", eur(total_value))
    t2.metric("Sellout volume (this week)", f"{total_volume:,.0f}")
    if num_stores_total:
        t3.metric("Avg revenue / store", eur(store_week_value / num_stores_total))
    else:
        t3.metric("Avg revenue / store", "—", help="Set store counts in Settings.")


def _pct_delta(this: float, last: float) -> str | None:
    """'+12.3% vs YTD last year' style delta string for st.metric, or None
    if there's nothing to compare against (avoids a bogus divide-by-zero)."""
    if last == 0:
        return None
    pct = (this - last) / last * 100
    return f"{pct:+.1f}% vs YTD last year"


def _ytd_slice(df: pd.DataFrame, current_year: str, current_week: int, prior_year: str):
    this_df = df[(df["year"] == current_year) & (df["week"] <= current_week)]
    last_df = df[(df["year"] == prior_year) & (df["week"] <= current_week)]
    return this_df, last_df


def _ytd_tiles(scoped: pd.DataFrame, store_scoped: pd.DataFrame, num_stores_total: int):
    """Year-to-date tiles: sum of weeks 1..N of the latest year present vs.
    the same weeks 1..N of the prior year, where N is the latest week
    number actually present for the current year (not the calendar week) —
    so it stays a fair like-for-like comparison regardless of when the app
    is opened."""
    current_year = scoped["year"].max()
    current_week = int(scoped.loc[scoped["year"] == current_year, "week"].max())
    prior_year = str(int(current_year) - 1)

    ytd_this, ytd_last = _ytd_slice(scoped, current_year, current_week, prior_year)
    store_ytd_this, store_ytd_last = _ytd_slice(store_scoped, current_year, current_week, prior_year)

    st.subheader(
        f"YTD {current_year} vs YTD {prior_year} (weeks 1–{current_week})",
        help=(
            "Year-to-date comparison: weeks 1 through the latest week number "
            "present for the current year, summed, versus the same weeks 1 "
            "through that number in the prior year. 'Avg revenue / store' "
            "only counts brand/country/banner combinations that have a store "
            "count configured, using the count currently set in Settings for "
            "both years (store counts aren't tracked historically)."
        ),
    )

    if ytd_last.empty:
        st.caption(f"No {prior_year} data in this selection to compare against yet.")
        return

    value_this = float(ytd_this["sales_value"].sum())
    value_last = float(ytd_last["sales_value"].sum())
    volume_this = float(ytd_this["sales_volume"].sum())
    volume_last = float(ytd_last["sales_volume"].sum())
    store_value_this = float(store_ytd_this["sales_value"].sum())
    store_value_last = float(store_ytd_last["sales_value"].sum())

    y1, y2, y3 = st.columns(3)
    y1.metric("YTD sales value", eur(value_this), delta=_pct_delta(value_this, value_last))
    y2.metric("YTD sellout volume", f"{volume_this:,.0f}", delta=_pct_delta(volume_this, volume_last))
    if num_stores_total:
        avg_this = store_value_this / num_stores_total
        avg_last = store_value_last / num_stores_total
        y3.metric("YTD avg revenue / store", eur(avg_this), delta=_pct_delta(avg_this, avg_last))
    else:
        y3.metric("YTD avg revenue / store", "—", help="Set store counts in Settings.")


def page_dashboard():
    st.header("Data analyse agent")
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

    scoped = _augment_year_week(scoped)

    # Store counts and targets, summed/weighted over the brand+country+banner
    # combinations actually present in the current selection. Combinations
    # without a configured store count are tracked separately: they must be
    # excluded from BOTH the euro numerator and the store-count denominator
    # of every "per store" figure below. Including their revenue in the
    # numerator while their stores are missing from the denominator would
    # silently inflate every average — mixing full-scope totals with a
    # partial-scope store count.
    scoped_combos = list(
        scoped[["brand", "country", "banner"]].drop_duplicates().itertuples(index=False)
    )
    combos_with_stores = []
    combos_without_stores = []
    num_stores_total = 0
    target_num = 0.0
    target_den = 0
    for b, c, bn in scoped_combos:
        n = db.get_store_count(b, c, bn, "DEFAULT") or 0
        t = db.get_target(b, c, bn)
        if n:
            combos_with_stores.append((b, c, bn))
            num_stores_total += n
            if t is not None:
                target_num += t * n
                target_den += n
        else:
            combos_without_stores.append((b, c, bn))
    combined_target = (target_num / target_den) if target_den else None

    if combos_with_stores:
        store_combo_df = pd.DataFrame(combos_with_stores, columns=["brand", "country", "banner"])
        store_scoped = scoped.merge(store_combo_df, on=["brand", "country", "banner"], how="inner")
    else:
        store_scoped = scoped.iloc[0:0]

    if combos_without_stores:
        names = ", ".join(f"{b}/{c}/{bn}" for b, c, bn in combos_without_stores)
        st.warning(
            f"No store count configured for: **{names}**. These are included "
            "in sellout volume/value totals below, but excluded from every "
            "'avg revenue per store' figure (tiles, chart, KPIs) so their "
            "revenue doesn't inflate an average against a store count they "
            "don't have. Set their store count in Settings to include them."
        )

    _highlight_tiles(scoped, store_scoped, num_stores_total)
    _ytd_tiles(scoped, store_scoped, num_stores_total)

    st.subheader(
        "Total sellout per week — year-over-year",
        help=(
            "Total sellout volume (units sold) per week number, with one "
            "coloured line per year so the same week compares across years "
            "(e.g. week 1 of 2025 vs 2026). Summed across every SKU in the "
            "current selection."
        ),
    )
    st.altair_chart(
        _yoy_chart(scoped, "sales_volume", "Sellout volume (units)", money=False),
        use_container_width=True,
    )

    st.subheader(
        "Total sales value per week — year-over-year",
        help=(
            "Total sales value (€) per week number, with one coloured line per "
            "year so the same week compares across years (e.g. week 1 of 2025 "
            "vs 2026). Summed across every SKU in the current selection."
        ),
    )
    st.altair_chart(
        _yoy_chart(scoped, "sales_value", "Sales value (€)", money=True),
        use_container_width=True,
    )
    years_in_view = sorted(scoped["year"].unique())
    if len(years_in_view) < 2:
        st.info(
            f"Only **{years_in_view[0]}** is in view, so there is a single "
            "line. These DWH exports label weeks by ISO year-week, so week "
            "**2026-01 starts on 29 Dec 2025** — that date in the file header "
            "is *not* separate 2025 data; every week column in these files is "
            "labelled 2026. A second year line appears automatically once you "
            "import a file that actually contains 2025 week columns "
            "(e.g. 2025-48 … 2025-52)."
        )

    # Average revenue per store per week, year-over-year, with a target line.
    st.subheader(
        "Avg revenue per store per week — year-over-year",
        help=(
            "Sales value that week ÷ number of stores (from Settings), per "
            "week number with one coloured line per year so weeks compare "
            "across years. Only counts brand/country/banner combinations "
            "with a configured store count. The dashed line is the target "
            "set per brand in Settings (weighted by store count when "
            "several brands are selected)."
        ),
    )
    if num_stores_total:
        avg_df = store_scoped.groupby(["year", "week"], as_index=False)["sales_value"].sum()
        avg_df["avg_rev"] = avg_df["sales_value"] / num_stores_total
        avg_line = (
            alt.Chart(avg_df)
            .mark_line(point=True, interpolate="monotone")
            .encode(
                x=alt.X("week:Q", title="Week number", scale=alt.Scale(domain=[1, 53])),
                y=alt.Y(
                    "avg_rev:Q",
                    title="Avg revenue / store (€)",
                    axis=alt.Axis(labelExpr=EUR_AXIS_LABEL),
                ),
                color=alt.Color("year:N", title="Year"),
                tooltip=[
                    alt.Tooltip("year:N", title="Year"),
                    alt.Tooltip("week:Q", title="Week"),
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

    # Per-item analysis with year-over-year comparison (volume + value).
    st.subheader(
        "Item analysis — year-over-year",
        help=(
            "Pick an item to see its sellout volume and sales value per week "
            "number, with one coloured line per year so weeks compare across "
            "years. Below, the full per-item volume table for all items."
        ),
    )
    item_options = (
        scoped[["sku", "article_description"]]
        .drop_duplicates()
        .sort_values("article_description")
    )
    item_labels = {
        f"{r.sku} — {r.article_description}": r.sku for r in item_options.itertuples()
    }
    chosen_label = st.selectbox("Item", list(item_labels.keys()))
    chosen_sku = item_labels[chosen_label]
    item_df = scoped[scoped["sku"] == chosen_sku]

    ic1, ic2 = st.columns(2)
    with ic1:
        st.caption("Volume per week")
        st.altair_chart(
            _yoy_chart(item_df, "sales_volume", "Volume (units)", money=False),
            use_container_width=True,
        )
    with ic2:
        st.caption("Value per week (€)")
        st.altair_chart(
            _yoy_chart(item_df, "sales_value", "Value (€)", money=True),
            use_container_width=True,
        )

    st.subheader(
        "Sellout per item per week (all items)",
        help=(
            "Sellout volume or value broken down per item, for the current "
            "selection. The sparkline view compares this year's weekly shape "
            "year-to-date (solid) against the same weeks last year (dashed, "
            "'LYTD'), with a percentage badge for that YTD-vs-LYTD total — "
            "both sides cover the same week range, so a partial current year "
            "is never compared against a full prior year. Hover any point on "
            "a sparkline for that week's numbers. Switch to the full data "
            "table for exact numbers per week."
        ),
    )
    view_col, metric_col_ui, _spacer = st.columns([1, 1, 3])
    with view_col:
        view = st.radio(
            "Item table view",
            ["Sparkline", "Data table"],
            horizontal=True,
        )
    with metric_col_ui:
        if view == "Sparkline":
            metric_choice = st.radio(
                "Metric", ["Volume", "Value"], horizontal=True, key="item_sparkline_metric",
            )
        else:
            metric_choice = "Volume"  # Data table view is volume-only; selector n/a

    if view == "Data table":
        item_pivot = scoped.pivot_table(
            index=["sku", "article_description"],
            columns="year_week",
            values="sales_volume",
            aggfunc="sum",
            fill_value=0,
        ).sort_index(axis=1)
        item_pivot.columns = [fmt_yw(c) for c in item_pivot.columns]
        st.dataframe(item_pivot, use_container_width=True)
    else:
        metric_col = "sales_volume" if metric_choice == "Volume" else "sales_value"
        fmt_number = nl_int if metric_choice == "Volume" else nl_money

        current_year = scoped["year"].max()
        prior_year = str(int(current_year) - 1)

        # All-time pivot (every year) drives the Latest-week and Total
        # columns; chronologically sorted so "latest" really means newest.
        all_time = scoped.pivot_table(
            index=["sku", "article_description"], columns="year_week",
            values=metric_col, aggfunc="sum", fill_value=0,
        ).sort_index(axis=1)

        # Current-year / prior-year pivots, restricted to weeks 1..N where N
        # is the latest week actually present for the current year (its
        # YTD cutoff) — applied to BOTH years, i.e. YTD vs LYTD. Using the
        # union of every week present in either year (the previous approach)
        # compared a partial current year against a full prior year, making
        # every item look like it underperformed simply because "this year"
        # only had a few months in it yet.
        current_week = int(scoped.loc[scoped["year"] == current_year, "week"].max())
        week_axis = list(range(1, current_week + 1))
        cur_pivot = scoped[scoped["year"] == current_year].pivot_table(
            index="sku", columns="week", values=metric_col, aggfunc="sum", fill_value=0,
        ).reindex(columns=week_axis, fill_value=0)
        prior_pivot = scoped[scoped["year"] == prior_year].pivot_table(
            index="sku", columns="week", values=metric_col, aggfunc="sum", fill_value=0,
        ).reindex(columns=week_axis, fill_value=0)

        has_prior_year = prior_year in scoped["year"].values
        ytd_label = f"YTD (wk 1–{current_week})"
        legend = (
            f'<span style="color:{_SPARK_CUR_COLOR};font-weight:600;">● {current_year} {ytd_label}</span>'
            f'&nbsp;&nbsp;<span style="color:{_SPARK_PRIOR_COLOR};font-weight:600;">- - {prior_year} same weeks (LYTD)</span>'
            if has_prior_year else
            f'<span style="color:{_SPARK_CUR_COLOR};font-weight:600;">● {current_year} {ytd_label}</span> '
            f'<span style="color:#888;">(no {prior_year} data in this selection)</span>'
        )

        all_week_cols = list(all_time.columns)
        rows_html = []
        for (sku, desc) in all_time.index:
            cur_vals = cur_pivot.loc[sku].tolist() if sku in cur_pivot.index else [0.0] * len(week_axis)
            prior_vals = prior_pivot.loc[sku].tolist() if sku in prior_pivot.index else [0.0] * len(week_axis)
            svg = _dual_year_sparkline_svg(
                cur_vals, prior_vals, week_axis, current_year, prior_year, fmt_number,
            )
            badge = _yoy_badge_html(sum(cur_vals), sum(prior_vals))
            latest_val = all_time.loc[(sku, desc), all_week_cols[-1]] if all_week_cols else 0
            total_val = all_time.loc[(sku, desc), all_week_cols].sum() if all_week_cols else 0
            rows_html.append(
                "<tr>"
                f'<td style="padding:8px 12px;white-space:nowrap;">{html.escape(str(sku))}</td>'
                f'<td style="padding:8px 12px;">{html.escape(str(desc))}</td>'
                f'<td style="padding:6px 12px;">{svg}</td>'
                f'<td style="padding:8px 12px;">{badge}</td>'
                f'<td style="padding:8px 12px;text-align:right;white-space:nowrap;">{fmt_number(latest_val)}</td>'
                f'<td style="padding:8px 12px;text-align:right;white-space:nowrap;">{fmt_number(total_val)}</td>'
                "</tr>"
            )

        table_html = f"""
        <div style="margin-bottom:6px;font-size:0.9em;">{legend}</div>
        <div style="max-height:600px;overflow-y:auto;border:1px solid rgba(128,128,128,0.25);border-radius:8px;">
        <table style="width:100%;border-collapse:collapse;font-size:0.92em;">
        <thead style="position:sticky;top:0;background:var(--background-color,#0e1117);z-index:1;">
        <tr style="border-bottom:1px solid rgba(128,128,128,0.35);text-align:left;">
        <th style="padding:8px 12px;">SKU</th>
        <th style="padding:8px 12px;">Item</th>
        <th style="padding:8px 12px;">{metric_choice} trend (YTD)</th>
        <th style="padding:8px 12px;">YTD vs LYTD</th>
        <th style="padding:8px 12px;text-align:right;">Latest week</th>
        <th style="padding:8px 12px;text-align:right;">Total</th>
        </tr>
        </thead>
        <tbody>
        {"".join(rows_html)}
        </tbody>
        </table>
        </div>
        """
        st.markdown(table_html, unsafe_allow_html=True)

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
        # Same two totals but restricted to brand/country/banner combos that
        # have a configured store count — pair these with num_stores in any
        # formula that divides by store count, so brands without a count
        # don't inflate the average (see the warning above when partial).
        "store_sales_volume": float(store_scoped["sales_volume"].sum()),
        "store_sales_value": float(store_scoped["sales_value"].sum()),
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
        "in the source files — set them manually here. Edit as many rows as "
        "you like, then click **Save all** once at the bottom — a single "
        "atomic save avoids the easy mistake of editing several rows but "
        "only clicking one row's save button."
    )
    df = _load_facts()
    combos = sorted(set(zip(df["brand"], df["country"], df["banner"]))) if not df.empty else []

    if not combos:
        st.info("Import data first to configure store counts per brand/country/banner.")
    else:
        with st.form("store_counts_form"):
            hdr = st.columns([3, 2, 2])
            hdr[0].markdown("**Brand / country / banner**")
            hdr[1].markdown("**# stores**")
            hdr[2].markdown("**Target avg € / store / week**")

            field_keys = []
            for brand, country, banner in combos:
                current = db.get_store_count(brand, country, banner, "DEFAULT") or 0
                current_target = db.get_target(brand, country, banner) or 0.0
                cols = st.columns([3, 2, 2])
                cols[0].write(f"**{brand}** / {country} / {banner}")
                stores_key = f"stores_{brand}_{country}_{banner}"
                target_key = f"target_{brand}_{country}_{banner}"
                cols[1].number_input(
                    "Stores", min_value=0, value=int(current),
                    key=stores_key, label_visibility="collapsed",
                )
                cols[2].number_input(
                    "Target", min_value=0.0, value=float(current_target), step=100.0,
                    key=target_key, label_visibility="collapsed",
                )
                field_keys.append((brand, country, banner, stores_key, target_key))

            submitted = st.form_submit_button("Save all")
            if submitted:
                for brand, country, banner, stores_key, target_key in field_keys:
                    db.set_store_count(brand, country, banner, "DEFAULT", int(st.session_state[stores_key]))
                    new_target = float(st.session_state[target_key])
                    db.set_target(brand, country, banner, new_target if new_target > 0 else None)
                st.success(f"Saved {len(field_keys)} row(s).")

    st.divider()
    st.subheader("KPI definitions")
    st.caption(
        "Available variables: total_sales_volume, total_sales_value "
        "(everything in the current filter selection), store_sales_volume, "
        "store_sales_value (same, but only brand/country/banner combos that "
        "have a store count configured — pair these with num_stores in any "
        "formula that divides by store count), num_stores, num_skus, "
        "num_weeks. Only + - * / and parentheses are allowed."
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

st.sidebar.title("Data analyse agent")
choice = st.sidebar.radio("Navigate", list(PAGES.keys()))
PAGES[choice]()
