from __future__ import annotations

import datetime as dt
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


def _strip_line_indent(html_text: str) -> str:
    """Remove leading whitespace from every line, regardless of whether it's
    uniform across the block. Markdown treats a line indented 4+ spaces as a
    preformatted code block, silently turning an entire HTML fragment into
    inert literal text instead of live markup — with no error, so it's easy
    to miss (this bit an earlier version of the sparkline table, where the
    f-string's lines carried the surrounding Python code's indentation).
    textwrap.dedent() is NOT sufficient here: it only strips the common
    prefix shared by every line, and this HTML is assembled by interpolating
    already-flush-left pieces (e.g. a <style> block) into an indented
    f-string, so there often is no common prefix for dedent to find at all."""
    return "\n".join(line.lstrip() for line in html_text.split("\n"))


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


SPARKLINE_HOVER_CSS = """
<style>
.spark-hover-cell { position: relative; display: inline-block; }
.spark-hover-cell svg { display: block; pointer-events: none; }
.spark-overlay { position: absolute; inset: 0; display: flex; }
.spark-slice { position: relative; flex: 1 1 0; height: 100%; }
.spark-slice::after {
    content: attr(data-tip);
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    margin-top: 4px;
    background: #1e2530;
    color: #f0f0f0;
    padding: 4px 9px;
    border-radius: 6px;
    font-size: 12px;
    line-height: 1.3;
    white-space: nowrap;
    box-shadow: 0 2px 10px rgba(0,0,0,0.35);
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.08s linear;
    pointer-events: none;
    z-index: 50;
}
.spark-slice:hover { background: rgba(255,255,255,0.08); }
.spark-slice:hover::after { opacity: 1; visibility: visible; }
</style>
"""


def _dual_year_sparkline_svg(cur_vals: list[float], prior_vals: list[float],
                              width: int = 170, height: int = 40) -> str:
    """Inline SVG with two overlaid polylines only (solid = current year,
    dashed = prior year) sharing one y-scale, so relative shape/height is
    comparable. Built by hand because st.column_config.LineChartColumn only
    supports a single monochrome series per cell — not the two-colour year
    overlay needed to compare against the prior year at a glance. Purely
    decorative: hovering is handled by a separate plain-HTML/CSS overlay
    (see _sparkline_cell_html) rather than any SVG hit-testing, since SVG
    <rect>/<title> hover support proved unreliable across browsers even
    with pointer-events="all"."""
    all_vals = [v for v in (cur_vals + prior_vals) if v is not None]
    vmax = max(all_vals) if all_vals else 0
    vmax = vmax or 1  # avoid div-by-zero for an all-zero row
    pad = 3
    n = len(cur_vals)
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
    svg.append("</svg>")
    return "".join(svg)


def _sparkline_cell_html(cur_vals: list[float], prior_vals: list[float],
                          week_axis: list[int], current_year: str, prior_year: str,
                          fmt_number, width: int = 170, height: int = 40) -> str:
    """The sparkline SVG plus a plain-HTML overlay of one hoverable <div> per
    week, styled by SPARKLINE_HOVER_CSS. Div :hover is unconditionally
    supported by every browser — unlike SVG element hit-testing, which
    turned out not to reliably fire pointer/hover events for a transparent
    <rect> even with pointer-events="all" set."""
    svg = _dual_year_sparkline_svg(cur_vals, prior_vals, width, height)
    slices = []
    for i, wk in enumerate(week_axis):
        cur_v = cur_vals[i] if i < len(cur_vals) else 0
        prior_v = prior_vals[i] if i < len(prior_vals) else 0
        tooltip = (
            f"Week {wk}: {fmt_number(cur_v)} ({current_year}) vs "
            f"{fmt_number(prior_v)} ({prior_year})"
        )
        slices.append(f'<div class="spark-slice" data-tip="{html.escape(tooltip)}"></div>')
    return (
        f'<div class="spark-hover-cell" style="width:{width}px;height:{height}px;">'
        f"{svg}"
        f'<div class="spark-overlay">{"".join(slices)}</div>'
        f"</div>"
    )


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


def _relative_time(iso_str: str | None) -> str:
    """'2 hours ago' style relative time from an ISO timestamp, for the
    compact status bar (the exact timestamp is still available in Details)."""
    if not iso_str:
        return "never"
    try:
        ts = dt.datetime.fromisoformat(iso_str)
    except ValueError:
        return "never"
    secs = (dt.datetime.utcnow() - ts).total_seconds()
    if secs < 0:
        secs = 0
    if secs < 60:
        return "just now"
    mins = int(secs // 60)
    if mins < 60:
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    hours = int(mins // 60)
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(hours // 24)
    return f"{days} day{'s' if days != 1 else ''} ago"


def _import_failure_notices() -> list[str]:
    """Failed-import notices — global, not scoped to the current filter
    selection, since a failed brand import is worth surfacing regardless of
    what's currently filtered."""
    notices = []
    for imp in db.get_last_imports():
        if not str(imp.get("status", "")).startswith("ok"):
            label = f"{imp['brand']} / {imp['country']}/{imp['banner']}"
            reason = imp.get("message") or "see the Import status tab for details"
            notices.append(f"Import failed for **{label}**: {reason}")
    return notices


def _status_bar(notices: list[str]):
    """One compact status bar: overall import health (dot + text), when the
    data last came in, and a notices count — replacing what used to be two
    separate metric tiles, a standalone import-health line, and an inline
    warning banner. Click 'Details' for the exact timestamps and the full
    notice text. `notices` combines global notices (failed imports) with
    ones scoped to the current brand/country/banner filter selection (e.g.
    missing store counts), passed in by the caller."""
    ok, total = _import_health()
    if total == 0:
        dot, colour, status_text = "⚪", "#888", "No imports yet"
    elif ok == total:
        dot, colour, status_text = "🟢", "#22c55e", "Data up to date"
    elif ok == 0:
        dot, colour, status_text = "🔴", "#ef4444", "All imports failed"
    else:
        dot, colour, status_text = "🟡", "#f59e0b", "Some imports failed"

    updated_ago = _relative_time(db.get_meta("last_received_at"))
    n = len(notices)
    notice_html = (
        f'<span style="color:#f59e0b;">⚠ {n} notice{"s" if n != 1 else ""}</span>'
        if n else '<span style="color:#666;">No notices</span>'
    )

    bar_html = f"""
    <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;
                background:rgba(128,128,128,0.08);border:1px solid rgba(128,128,128,0.18);
                border-radius:10px;padding:12px 18px;margin-bottom:14px;">
      <span style="color:{colour};font-weight:600;">{dot} {status_text}</span>
      <span style="color:#666;">|</span>
      <span style="color:#999;">Updated {updated_ago}</span>
      <span style="color:#666;">|</span>
      {notice_html}
    </div>
    """
    st.markdown(_strip_line_indent(bar_html), unsafe_allow_html=True)

    with st.expander(f"Details ({n})" if n else "Details"):
        st.caption(
            f"Last data received: {_fmt_ts(db.get_meta('last_received_at'))} · "
            f"Last analyzed/updated: {_fmt_ts(db.get_meta('last_analyzed_at'))}"
        )
        if notices:
            for note in notices:
                st.markdown(f"- {note}")
        else:
            st.markdown("No outstanding notices.")


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


def _pct_delta(this: float, last: float) -> str | None:
    """'+12.3% vs YTD last year' style delta string, or None if there's
    nothing to compare against (avoids a bogus divide-by-zero)."""
    if last == 0:
        return None
    pct = (this - last) / last * 100
    return f"{pct:+.1f}%"


def _ytd_slice(df: pd.DataFrame, current_year: str, current_week: int, prior_year: str):
    this_df = df[(df["year"] == current_year) & (df["week"] <= current_week)]
    last_df = df[(df["year"] == prior_year) & (df["week"] <= current_week)]
    return this_df, last_df


# ---- Redesigned KPI tiles (per design_handoff_dashboard_filters) ----------
# Categorical colour palette: a fixed hue per dimension value, reused between
# the breakdown rows here (and, conceptually, the filter chips) so a value's
# colour is stable wherever it appears.
_HUES = {"brand": [25, 80, 170, 290], "country": [200, 140], "banner": [320, 60, 250]}
_DIM_KEY = {"Brand": "brand", "Country": "country", "Banner": "banner"}


def _fmt_num(n: float) -> str:
    """Whole number with comma thousands separators, per the design spec."""
    return f"{n:,.0f}"


def _value_colors(dim: str, values) -> dict:
    """Map each value of a dimension to its palette colours, assigned by
    sorted order so the colour ↔ value pairing is stable across reruns."""
    hues = _HUES[dim]
    out = {}
    for i, v in enumerate(sorted(values)):
        h = hues[i % len(hues)]
        out[v] = {"row": f"oklch(68% 0.15 {h})"}
    return out


def _sum_rows(df_slice, dim, col, colors, fmt):
    """Breakdown rows for an additive metric (value/volume): group-sum by the
    dimension, sorted high→low, with each bar relative to the row max."""
    g = df_slice.groupby(dim, as_index=False)[col].sum()
    g = g[g[col] != 0].sort_values(col, ascending=False)
    if g.empty:
        return []
    mx = g[col].max() or 1
    return [
        # Clamp to [0, 100]: a negative weekly total (returns exceeding
        # sales) would otherwise emit an invalid negative CSS width.
        {"name": r[dim], "value": fmt(r[col]), "color": colors[r[dim]]["row"],
         "share": max(0.0, min(100.0, r[col] / mx * 100))}
        for _, r in g.iterrows()
    ]


def _avg_amounts(store_slice, dim, combos_stores) -> list[tuple[str, float]]:
    """Per dimension value: its own revenue ÷ its own store count. The
    single source for both the breakdown rows (combine off) and the
    combined figure (combine on = the SUM of exactly these amounts), so
    the two views always reconcile."""
    out = []
    for val in store_slice[dim].unique():
        stores = sum(
            n for (b, c, bn), n in combos_stores.items()
            if {"brand": b, "country": c, "banner": bn}[dim] == val
        )
        if not stores:
            continue
        out.append((val, float(store_slice[store_slice[dim] == val]["sales_value"].sum()) / stores))
    return out


def _avg_rows(store_slice, dim, combos_stores, colors, fmt):
    """Breakdown rows for avg revenue per store: each dimension value's own
    independent average (see _avg_amounts)."""
    rows = [{"val": v, "amt": a} for v, a in _avg_amounts(store_slice, dim, combos_stores) if a]
    if not rows:
        return []
    mx = max(r["amt"] for r in rows)
    rows.sort(key=lambda r: -r["amt"])
    return [
        {"name": r["val"], "value": fmt(r["amt"]), "color": colors[r["val"]]["row"],
         "share": max(0.0, min(100.0, r["amt"] / mx * 100))}
        for r in rows
    ]


def _rows_block(rows, divider=True):
    inner = ""
    for r in rows:
        inner += (
            '<div style="display:flex;flex-direction:column;gap:5px">'
            '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px">'
            '<div style="display:flex;align-items:center;gap:8px;min-width:0">'
            f'<span style="width:9px;height:9px;border-radius:50%;background:{r["color"]};flex:none"></span>'
            '<span style="font-size:13.5px;font-weight:600;color:rgba(255,255,255,0.85);'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{html.escape(str(r["name"]))}</span>'
            '</div>'
            f'<span style="font-size:14px;font-weight:700;color:#fff;white-space:nowrap">{r["value"]}</span>'
            '</div>'
            '<div style="height:4px;border-radius:2px;background:rgba(255,255,255,0.06);overflow:hidden">'
            f'<div style="height:100%;border-radius:2px;background:{r["color"]};width:{r["share"]:.0f}%"></div>'
            '</div></div>'
        )
    border = "border-top:1px solid rgba(255,255,255,0.07);padding-top:16px;" if divider else ""
    return f'<div style="display:flex;flex-direction:column;gap:10px;{border}">{inner}</div>'


def _tile(label, big=None, delta=None, rows_html="", footer=None, footer_alpha="0.4", big_size=44):
    body = f'<div style="font-size:15px;font-weight:600;color:rgba(255,255,255,0.65)">{label}</div>'
    if big is not None:
        body += (
            f'<div style="font-size:{big_size}px;font-weight:800;letter-spacing:-0.01em">{big}</div>'
        )
    if delta is not None:
        # Arrow and colour must follow the sign — the old st.metric widget
        # did this automatically; a hardcoded green ↑ showed declines as
        # green gains.
        down = str(delta).lstrip().startswith("-")
        badge_bg = "rgba(180,60,40,0.16)" if down else "rgba(46,138,90,0.16)"
        badge_fg = "oklch(70% 0.15 30)" if down else "oklch(74% 0.15 150)"
        arrow = "↓" if down else "↑"
        body += (
            '<div style="align-self:flex-start;display:flex;align-items:center;gap:6px;'
            f'background:{badge_bg};color:{badge_fg};padding:6px 12px;'
            f'border-radius:8px;font-size:13px;font-weight:700">{arrow} {delta} vs YTD last year</div>'
        )
    body += rows_html
    if footer:
        body += f'<div style="font-size:11.5px;color:rgba(255,255,255,{footer_alpha})">{footer}</div>'
    return (
        '<div style="background:#14161d;border:1px solid rgba(255,255,255,0.06);border-radius:16px;'
        f'padding:26px 28px;display:flex;flex-direction:column;gap:16px;height:100%">{body}</div>'
    )


def _section_header(title: str, tooltip: str, key: str) -> str:
    """Title + info-dot on the left, segmented control on the right. Returns
    the chosen dimension key (brand/country/banner)."""
    hc1, hc2 = st.columns([3, 2], vertical_alignment="center")
    with hc1:
        st.markdown(
            _strip_line_indent(
                '<div style="display:flex;align-items:center;gap:10px">'
                f'<h2 style="margin:0;font-size:26px;font-weight:800;letter-spacing:-0.01em">{title}</h2>'
                '<span title="' + html.escape(tooltip) + '" style="width:20px;height:20px;'
                'border-radius:50%;border:1.5px solid rgba(255,255,255,0.35);display:inline-flex;'
                'align-items:center;justify-content:center;font-size:12px;color:rgba(255,255,255,0.55);'
                'cursor:help">?</span></div>'
            ),
            unsafe_allow_html=True,
        )
    with hc2:
        choice = st.segmented_control(
            "Breakdown", ["Brand", "Country", "Banner"],
            default="Brand", key=key, label_visibility="collapsed",
        )
    return _DIM_KEY.get(choice or "Brand", "brand")


def _avg_tile(label, store_slice, dim, combos_stores, colors, combine, delta=None, big_size=44):
    """Avg-revenue-per-store tile. Combine ON sums the per-value averages —
    the exact same amounts shown as rows when the toggle is off, so
    toggling reconciles visually (e.g. € 48 + € 45 → € 93). Combine OFF
    shows those individual averages as breakdown rows."""
    if not combos_stores:
        return _tile(label, big="—", footer="Set store counts in Settings", big_size=big_size)
    if combine:
        total = sum(a for _, a in _avg_amounts(store_slice, dim, combos_stores))
        return _tile(
            label, big=eur(total), delta=delta,
            footer=f"Sum of the individual per-{dim} averages", big_size=big_size,
        )
    rows = _avg_rows(store_slice, dim, combos_stores, colors, eur)
    return _tile(
        label, rows_html=_rows_block(rows, divider=False),
        footer="Individual averages", footer_alpha="0.35", big_size=big_size,
    )


def _week_section(scoped, store_scoped, combos_stores):
    most_recent_week = scoped["year_week"].max()
    dim = _section_header(
        f"Most recent week — {most_recent_week}",
        f"Headline figures for ISO week {most_recent_week}. The segmented "
        "control picks which dimension the per-value breakdown splits by.",
        key="dim_week",
    )
    colors = _value_colors(dim, scoped[dim].unique())
    week_df = scoped[scoped["year_week"] == most_recent_week]
    store_week = store_scoped[store_scoped["year_week"] == most_recent_week]

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            _strip_line_indent(_tile(
                "Sales value (this week)", big=eur(week_df["sales_value"].sum()),
                rows_html=_rows_block(_sum_rows(week_df, dim, "sales_value", colors, eur)),
            )),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            _strip_line_indent(_tile(
                "Sellout volume (this week)", big=_fmt_num(week_df["sales_volume"].sum()),
                rows_html=_rows_block(_sum_rows(week_df, dim, "sales_volume", colors, _fmt_num)),
            )),
            unsafe_allow_html=True,
        )
    with c3:
        combine = st.toggle("Combine avg / store", value=True, key="avg_combine_week")
        st.markdown(
            _strip_line_indent(_avg_tile(
                "Avg revenue / store", store_week, dim, combos_stores, colors, combine,
            )),
            unsafe_allow_html=True,
        )


def _ytd_section(scoped, store_scoped, combos_stores):
    current_year = scoped["year"].max()
    current_week = int(scoped.loc[scoped["year"] == current_year, "week"].max())
    prior_year = str(int(current_year) - 1)
    ytd_this, ytd_last = _ytd_slice(scoped, current_year, current_week, prior_year)
    store_ytd_this, store_ytd_last = _ytd_slice(store_scoped, current_year, current_week, prior_year)

    dim = _section_header(
        f"YTD {current_year} vs YTD {prior_year} (weeks 1–{current_week})",
        "Year-to-date vs the same weeks last year. The segmented control "
        "picks which dimension the per-value breakdown splits by.",
        key="dim_ytd",
    )
    if ytd_last.empty:
        st.caption(f"No {prior_year} data in this selection to compare against yet.")

    colors = _value_colors(dim, scoped[dim].unique())
    value_this = float(ytd_this["sales_value"].sum())
    value_last = float(ytd_last["sales_value"].sum())
    volume_this = float(ytd_this["sales_volume"].sum())
    volume_last = float(ytd_last["sales_volume"].sum())

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            _strip_line_indent(_tile(
                "YTD sales value", big=eur(value_this), big_size=40,
                delta=_pct_delta(value_this, value_last),
                rows_html=_rows_block(_sum_rows(ytd_this, dim, "sales_value", colors, eur)),
            )),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            _strip_line_indent(_tile(
                "YTD sellout volume", big=_fmt_num(volume_this), big_size=40,
                delta=_pct_delta(volume_this, volume_last),
                rows_html=_rows_block(_sum_rows(ytd_this, dim, "sales_volume", colors, _fmt_num)),
            )),
            unsafe_allow_html=True,
        )
    with c3:
        # No Combine toggle here — only the top (Most recent week) avg tile
        # carries one; this tile always shows the combined (summed) figure.
        avg_delta = None
        if combos_stores:
            # Sum-of-individual-averages for both years, same dimension, so
            # the delta compares like for like.
            a_this = sum(a for _, a in _avg_amounts(store_ytd_this, dim, combos_stores))
            a_last = sum(a for _, a in _avg_amounts(store_ytd_last, dim, combos_stores))
            avg_delta = _pct_delta(a_this, a_last)
        st.markdown(
            _strip_line_indent(_avg_tile(
                "YTD avg revenue / store", store_ytd_this, dim, combos_stores, colors,
                combine=True, delta=avg_delta, big_size=40,
            )),
            unsafe_allow_html=True,
        )


def page_dashboard():
    st.header("Data analyse agent")

    # The status bar must render above the brand/country/banner filters, but
    # some of its notices (e.g. missing store counts) depend on which
    # brands are currently selected — known only after those filter widgets
    # run, further down this function. st.empty() reserves the visual slot
    # here; filling it later still draws in this position.
    status_placeholder = st.empty()
    global_notices = _import_failure_notices()

    df = _load_facts()
    if df.empty:
        with status_placeholder.container():
            _status_bar(global_notices)
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
        with status_placeholder.container():
            _status_bar(global_notices)
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
    combos_stores = {}          # (brand,country,banner) -> store count, configured combos only
    combos_without_stores = []
    num_stores_total = 0
    target_sum = 0.0            # plain sum of per-brand targets (combined method)
    any_target = False
    for b, c, bn in scoped_combos:
        n = db.get_store_count(b, c, bn, "DEFAULT") or 0
        t = db.get_target(b, c, bn)
        if n:
            combos_stores[(b, c, bn)] = n
            num_stores_total += n
            if t is not None:
                target_sum += t
                any_target = True
        else:
            combos_without_stores.append((b, c, bn))
    combos_with_stores = list(combos_stores.keys())
    # Target line = plain sum of per-brand targets, matching how the avg
    # figures sum per-brand per-store amounts.
    target_combined = target_sum if any_target else None

    if combos_with_stores:
        store_combo_df = pd.DataFrame(combos_with_stores, columns=["brand", "country", "banner"])
        store_scoped = scoped.merge(store_combo_df, on=["brand", "country", "banner"], how="inner")
    else:
        store_scoped = scoped.iloc[0:0]

    scope_notices = list(global_notices)
    if combos_without_stores:
        names = ", ".join(f"{b}/{c}/{bn}" for b, c, bn in combos_without_stores)
        scope_notices.append(
            f"No store count configured for: **{names}** (currently selected). "
            "These are included in sellout volume/value totals below, but "
            "excluded from every 'avg revenue per store' figure (tiles, "
            "chart, KPIs) so their revenue doesn't inflate an average "
            "against a store count they don't have. Set their store count "
            "in Settings to include them."
        )
    with status_placeholder.container():
        _status_bar(scope_notices)

    _week_section(scoped, store_scoped, combos_stores)
    st.divider()
    _ytd_section(scoped, store_scoped, combos_stores)
    st.divider()

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
    # Always the combined (summed) method — each brand/country/banner combo's
    # own per-store average, summed per week — matching the dashboard tiles;
    # there is deliberately no Blended/Combined control here (the only
    # combine control lives on the top avg tile).
    st.subheader(
        "Avg revenue per store per week — year-over-year",
        help=(
            "Sum of each brand/country/banner combination's own revenue per "
            "store, per week number, one coloured line per year. Only counts "
            "combinations with a configured store count. The dashed line is "
            "the sum of the per-brand targets from Settings."
        ),
    )
    target_line = target_combined
    if combos_stores:
        parts = []
        for (b, c, bn), n in combos_stores.items():
            sub = store_scoped[
                (store_scoped["brand"] == b)
                & (store_scoped["country"] == c)
                & (store_scoped["banner"] == bn)
            ].groupby(["year", "week"], as_index=False)["sales_value"].sum()
            sub["avg_rev"] = sub["sales_value"] / n
            parts.append(sub[["year", "week", "avg_rev"]])
        avg_df = pd.concat(parts).groupby(["year", "week"], as_index=False)["avg_rev"].sum()
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
        if target_line is not None:
            rule = (
                alt.Chart(pd.DataFrame({"target": [target_line]}))
                .mark_rule(color="red", strokeDash=[6, 4])
                .encode(y="target:Q")
            )
            text = (
                alt.Chart(pd.DataFrame({"target": [target_line]}))
                .mark_text(align="left", dx=5, dy=-5, color="red")
                .encode(y="target:Q", text=alt.value(f"target € {target_line:,.0f}"))
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
            "a sparkline for that week's numbers. 'Latest week' is the single "
            "most recent imported week; 'Total (YTD)' sums only the current "
            "year's weeks shown in the sparkline, not the item's full import "
            "history. Switch to the full data table for exact numbers per week."
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
            svg = _sparkline_cell_html(
                cur_vals, prior_vals, week_axis, current_year, prior_year, fmt_number,
            )
            badge = _yoy_badge_html(sum(cur_vals), sum(prior_vals))
            latest_val = all_time.loc[(sku, desc), all_week_cols[-1]] if all_week_cols else 0
            total_val = sum(cur_vals)  # YTD only (current year, weeks 1..N) — not all-time history
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
        {SPARKLINE_HOVER_CSS}
        <div style="margin-bottom:6px;font-size:0.9em;">{legend}</div>
        <div style="max-height:600px;overflow-y:auto;border:1px solid rgba(128,128,128,0.25);border-radius:8px;">
        <table style="width:100%;border-collapse:collapse;font-size:0.92em;">
        <thead style="position:sticky;top:0;background:var(--background-color,#0e1117);z-index:1;">
        <tr style="border-bottom:1px solid rgba(128,128,128,0.35);text-align:left;">
        <th style="padding:8px 12px;">SKU</th>
        <th style="padding:8px 12px;">Item</th>
        <th style="padding:8px 12px;">{metric_choice} trend (YTD)</th>
        <th style="padding:8px 12px;">YTD vs LYTD</th>
        <th style="padding:8px 12px;text-align:right;" title="The single most recent imported week for this item.">Latest week</th>
        <th style="padding:8px 12px;text-align:right;" title="Sum of the current year's weeks 1..N shown in the sparkline (YTD) — not the item's full import history.">Total (YTD)</th>
        </tr>
        </thead>
        <tbody>
        {"".join(rows_html)}
        </tbody>
        </table>
        </div>
        """
        st.markdown(_strip_line_indent(table_html), unsafe_allow_html=True)

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
