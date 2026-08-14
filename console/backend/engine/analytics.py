"""Analysis queries on the canonical fact table, always routed through the
fallback resolver so every result carries {level_used, labels}.

Facts from a profile in 'test' are visible in that retailer's own screens —
there is nothing else to look at while a profile is being proven — but they
carry the extra label 'PROFIEL IN TEST' and are excluded from cross-retailer
reporting (the imports flag makes both possible).
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from . import fallback
from .periods import period_number, period_year, sort_key
from .profile import active_profile, capabilities

LABEL_TEST = "PROFIEL IN TEST"


def retailer_caps(conn, retailer_id: str) -> tuple[dict | None, list[str]]:
    """(capabilities, base_labels) for a retailer, or (None, []) without profile."""
    prof = active_profile(conn, retailer_id)
    if not prof:
        return None, []
    caps = capabilities(prof.definition)
    return caps, ([LABEL_TEST] if prof.status == "test" else [])


def _facts(conn, retailer_id: str, include_test: bool, extra: str = "", params: tuple = ()):
    statuses = "('ingelezen','test')" if include_test else "('ingelezen')"
    sql = (f"SELECT f.* FROM sellout_facts f JOIN imports im ON im.id = f.import_id "
           f"AND im.status IN {statuses} WHERE f.retailer_id = ? {extra}")
    return conn.execute(sql, (retailer_id, *params)).fetchall()


def load_facts(conn, retailer_id: str, merk=None, land=None, banner=None):
    conds, params = [], []
    for col, vals in (("merk", merk), ("land", land), ("banner", banner)):
        if vals:
            conds.append(f"AND f.{col} IN ({','.join('?' * len(vals))})")
            params.extend(vals)
    return _facts(conn, retailer_id, include_test=True,
                  extra=" ".join(conds), params=tuple(params))


def store_count(conn, retailer_id: str, caps: dict, rows, latest: str | None) -> tuple[int | None, bool]:
    """(number_of_stores, from_facts). Falls back to manual settings (SCHATTING)."""
    if caps.get("winkel"):
        stores = {r["winkel_id"] for r in rows if r["winkel_id"]
                  and (latest is None or r["periode"] == latest)}
        if stores:
            return len(stores), True
    total = conn.execute(
        "SELECT SUM(aantal_winkels) AS n FROM retailer_settings WHERE retailer_id=?",
        (retailer_id,)).fetchone()["n"]
    return total, False


# ---------------------------------------------------------------- dashboard

def dashboard(conn, retailer_id: str, merk=None, land=None, banner=None) -> dict:
    caps, base_labels = retailer_caps(conn, retailer_id)
    if caps is None:
        return {"available": False, "reason": "PARSER PROFIEL ONTBREEKT"}
    res = fallback.resolve(caps, week=True, winkel=True, banner=True)
    labels = base_labels + res.labels

    rows = load_facts(conn, retailer_id, merk, land, banner)
    if not rows:
        return {"available": True, "empty": True, "resolution": res.as_dict(),
                "labels": labels, "capabilities": caps}

    periods = sorted({r["periode"] for r in rows}, key=sort_key)
    latest = periods[-1]
    latest_rows = [r for r in rows if r["periode"] == latest]

    def agg(rs):
        return {"omzet": sum(r["omzet"] for r in rs),
                "volume": sum(r["volume"] for r in rs)}

    def brand_breakdown(rs, key):
        per = defaultdict(float)
        for r in rs:
            per[r["merk"] or "ONBEKEND"] += r[key]
        return sorted(({"merk": m, "waarde": v} for m, v in per.items()),
                      key=lambda x: -x["waarde"])

    kpi = agg(latest_rows)
    n_stores, from_facts = store_count(conn, retailer_id, caps, rows, latest)
    per_store = (kpi["omzet"] / n_stores) if n_stores else None

    # YTD vs LYTD: same period window (1..latest number) in this and prior year.
    y_now = period_year(latest)
    upto = period_number(latest)

    def ytd(year):
        return agg([r for r in rows if period_year(r["periode"]) == year
                    and period_number(r["periode"]) <= upto])

    ytd_now, ytd_prior = ytd(y_now), ytd(y_now - 1)
    stores_all, _ = store_count(conn, retailer_id, caps, rows, None)

    def delta(now, prev):
        return round((now - prev) / prev * 100, 1) if prev else None

    # Trend: three year-lines per period number.
    years = sorted({period_year(r["periode"]) for r in rows})[-3:]
    trend = {"jaren": years, "series": {}}
    for metric in ("omzet", "volume"):
        per_year = {y: defaultdict(float) for y in years}
        for r in rows:
            y = period_year(r["periode"])
            if y in per_year:
                per_year[y][period_number(r["periode"])] += r[metric]
        trend["series"][metric] = {y: dict(per_year[y]) for y in years}
    if n_stores:
        trend["series"]["per_winkel"] = {
            y: {p: v / n_stores for p, v in perline.items()}
            for y, perline in trend["series"]["omzet"].items()}

    return {
        "available": True, "empty": False, "capabilities": caps,
        "resolution": res.as_dict(), "labels": labels,
        "periode_type": caps["periode"], "laatste_periode": latest,
        "kpi": {
            "omzet": {"waarde": kpi["omzet"], "breakdown": brand_breakdown(latest_rows, "omzet")},
            "volume": {"waarde": kpi["volume"], "breakdown": brand_breakdown(latest_rows, "volume")},
            "omzet_per_winkel": {"waarde": per_store, "winkels": n_stores,
                                 "schatting": not from_facts},
        },
        "ytd": {
            "jaar": y_now, "tot_periode": upto,
            "omzet": {"nu": ytd_now["omzet"], "vorig": ytd_prior["omzet"],
                      "delta_pct": delta(ytd_now["omzet"], ytd_prior["omzet"])},
            "volume": {"nu": ytd_now["volume"], "vorig": ytd_prior["volume"],
                       "delta_pct": delta(ytd_now["volume"], ytd_prior["volume"])},
            "omzet_per_winkel": {
                "nu": ytd_now["omzet"] / stores_all if stores_all else None,
                "vorig": ytd_prior["omzet"] / stores_all if stores_all else None,
                "delta_pct": delta(ytd_now["omzet"], ytd_prior["omzet"]),
                "schatting": not from_facts},
        },
        "trend": trend,
        "filters": {
            "merk": sorted({r["merk"] for r in _facts(conn, retailer_id, True) if r["merk"]}),
            "land": sorted({r["land"] for r in _facts(conn, retailer_id, True) if r["land"]}),
            "banner": sorted({r["banner"] for r in _facts(conn, retailer_id, True) if r["banner"]}),
        },
    }


# ---------------------------------------------------------------- articles

def articles(conn, retailer_id: str) -> dict:
    caps, base_labels = retailer_caps(conn, retailer_id)
    if caps is None:
        return {"available": False, "reason": "PARSER PROFIEL ONTBREEKT"}
    res = fallback.resolve(caps, artikel=True, week=True)
    if res.level_used.get("detail") != "artikel":
        return {"available": False, "reason": "GEGEVENS NIET BESCHIKBAAR",
                "resolution": res.as_dict(), "labels": base_labels + res.labels}
    rows = load_facts(conn, retailer_id)
    if not rows:
        return {"available": True, "artikelen": [], "labels": base_labels + res.labels,
                "resolution": res.as_dict()}
    periods = sorted({r["periode"] for r in rows}, key=sort_key)
    latest = periods[-1]
    y_now, upto = period_year(latest), period_number(latest)

    per_art: dict = {}
    for r in rows:
        if not r["artikel_ean"]:
            continue
        a = per_art.setdefault(r["artikel_ean"], {
            "ean": r["artikel_ean"], "naam": r["artikel_naam"], "merk": r["merk"],
            "ytd": defaultdict(lambda: {"volume": 0, "omzet": 0.0}),
            "lytd": defaultdict(lambda: {"volume": 0, "omzet": 0.0}),
            "laatste": {"volume": 0, "omzet": 0.0}})
        y, p = period_year(r["periode"]), period_number(r["periode"])
        bucket = a["ytd"] if y == y_now else a["lytd"] if y == y_now - 1 else None
        if bucket is not None and p <= upto:
            bucket[p]["volume"] += r["volume"]
            bucket[p]["omzet"] += r["omzet"]
        if r["periode"] == latest:
            a["laatste"]["volume"] += r["volume"]
            a["laatste"]["omzet"] += r["omzet"]

    out = []
    for a in per_art.values():
        tot = {k: sum(v[k] for v in a["ytd"].values()) for k in ("volume", "omzet")}
        ltot = {k: sum(v[k] for v in a["lytd"].values()) for k in ("volume", "omzet")}
        out.append({
            "ean": a["ean"], "naam": a["naam"], "merk": a["merk"],
            "sparkline": {"ytd": {p: dict(v) for p, v in sorted(a["ytd"].items())},
                          "lytd": {p: dict(v) for p, v in sorted(a["lytd"].items())}},
            "laatste_periode": a["laatste"], "totaal_ytd": tot, "totaal_lytd": ltot,
            "ytd_delta_pct": round((tot["omzet"] - ltot["omzet"]) / ltot["omzet"] * 100, 1)
                             if ltot["omzet"] else None})
    out.sort(key=lambda x: -x["totaal_ytd"]["omzet"])
    return {"available": True, "artikelen": out, "laatste_periode": latest,
            "periode_type": caps["periode"], "labels": base_labels + res.labels,
            "resolution": res.as_dict()}


# ---------------------------------------------------------------- promotions

def _promo_scope_key(caps):
    return (lambda r: (r["merk"], r["land"], r["banner"])) if caps.get("banner") \
        else (lambda r: (r["merk"], r["land"], None))


def promotions(conn, retailer_id: str) -> dict:
    caps, base_labels = retailer_caps(conn, retailer_id)
    if caps is None:
        return {"available": False, "reason": "PARSER PROFIEL ONTBREEKT"}
    prof = active_profile(conn, retailer_id)
    threshold = prof.definition.get("thresholds", {}).get("promo_price_drop", 0.05)
    res = fallback.resolve(caps, week=True, banner=True)
    labels = base_labels + res.labels

    rows = load_facts(conn, retailer_id)
    key = _promo_scope_key(caps)
    per_scope_period = defaultdict(lambda: {"volume": 0, "omzet": 0.0})
    for r in rows:
        agg = per_scope_period[(key(r), r["periode"])]
        agg["volume"] += r["volume"]
        agg["omzet"] += r["omzet"]

    unit_prices = defaultdict(dict)
    for (scope, periode), agg in per_scope_period.items():
        if agg["volume"]:
            unit_prices[scope][periode] = agg["omzet"] / agg["volume"]

    confirmed = {(r["merk"], r["land"], r["banner"], r["periode"])
                 for r in conn.execute(
                     "SELECT merk, land, banner, periode FROM promo_confirmations WHERE retailer_id=?",
                     (retailer_id,))}

    suggestions = []
    for scope, prices in unit_prices.items():
        med = median(prices.values())
        for periode, price in sorted(prices.items(), key=lambda kv: sort_key(kv[0])):
            drop = (med - price) / med if med else 0
            merk, land, banner = scope
            is_confirmed = (merk, land, banner, periode) in confirmed
            if drop >= threshold or is_confirmed:
                suggestions.append({
                    "merk": merk, "land": land, "banner": banner, "periode": periode,
                    "suggestie": f"afgeprijsd, -{round(drop * 100)}%" if drop >= threshold else None,
                    "bevestigd": is_confirmed})

    # Uplift per confirmed promo: promo period vs mean of NON-promo periods
    # in the same scope. Confirmed periods stay out of the baseline, so
    # re-importing a confirmed period never moves the baseline (acceptance 5).
    uplift = []
    for merk, land, banner, periode in sorted(confirmed, key=lambda c: sort_key(c[3])):
        scope = (merk, land, banner)
        prices = per_scope_period
        promo_rev = prices.get((scope, periode), {}).get("omzet")
        if promo_rev is None:
            continue
        baseline_revs = [agg["omzet"] for (s, p), agg in per_scope_period.items()
                         if s == scope and (merk, land, banner, p) not in confirmed]
        if not baseline_revs:
            continue
        base = sum(baseline_revs) / len(baseline_revs)
        uplift.append({"merk": merk, "land": land, "banner": banner, "periode": periode,
                       "jaar": period_year(periode), "omzet": promo_rev, "basislijn": base,
                       "uplift_pct": round((promo_rev - base) / base * 100, 1) if base else None})
    uplift.sort(key=lambda u: -(u["uplift_pct"] or 0))
    return {"available": True, "suggesties": suggestions, "uplift": uplift,
            "drempel": threshold, "periode_type": caps["periode"],
            "labels": labels, "resolution": res.as_dict(), "capabilities": caps}


# ---------------------------------------------------------------- assortment

def assortment(conn, retailer_id: str) -> dict:
    caps, base_labels = retailer_caps(conn, retailer_id)
    if caps is None:
        return {"available": False, "reason": "PARSER PROFIEL ONTBREEKT"}
    res = fallback.resolve(caps, artikel=True, winkel=True)
    if res.level_used.get("detail") != "artikel":
        return {"available": False, "reason": "GEGEVENS NIET BESCHIKBAAR",
                "resolution": res.as_dict(), "labels": base_labels + res.labels}
    labels = base_labels + res.labels

    empty_stats = {"op_target": 0, "onder_target": 0, "delist": 0}
    all_rows = load_facts(conn, retailer_id)
    if not all_rows:
        return {"available": True, "artikelen": [], "labels": labels,
                "resolution": res.as_dict(), "stats": empty_stats}
    # Rotation runs over the CURRENT year only: averaging over the full
    # multi-year history would dilute every article's stuks/winkel/week and
    # push healthy items toward a false 'delist' as history grows.
    latest_year = max(period_year(r["periode"]) for r in all_rows)
    rows = [r for r in all_rows if period_year(r["periode"]) == latest_year]
    n_stores, _from_facts = store_count(conn, retailer_id, caps, rows, None)
    periods = {r["periode"] for r in rows}
    weeks = len(periods) or 1
    targets = {r["merk"]: r["stuks_per_winkel_per_week"] for r in conn.execute(
        "SELECT merk, stuks_per_winkel_per_week FROM rotatie_targets WHERE retailer_id=?",
        (retailer_id,))}

    per_art = defaultdict(lambda: {"volume": 0, "naam": None, "merk": None})
    for r in rows:
        if not r["artikel_ean"]:
            continue
        a = per_art[r["artikel_ean"]]
        a["volume"] += r["volume"]
        a["naam"] = a["naam"] or r["artikel_naam"]
        a["merk"] = a["merk"] or r["merk"]

    out = []
    for ean, a in per_art.items():
        rotatie = a["volume"] / weeks / n_stores if n_stores else None
        target = targets.get(a["merk"])
        score = round(rotatie / target * 100) if rotatie is not None and target else None
        if score is None:
            advies = "Geen rotatie-target ingesteld"
        elif score >= 115:
            advies = "Ruim op target"
        elif score >= 100:
            advies = "Op target"
        elif score >= 70:
            advies = "Onder target, monitoren"
        else:
            advies = "Mogelijke delist"
        out.append({"ean": ean, "naam": a["naam"], "merk": a["merk"],
                    "rotatie": round(rotatie, 2) if rotatie is not None else None,
                    "target": target, "score": score, "advies": advies})
    out.sort(key=lambda x: (x["score"] is None, x["score"] if x["score"] is not None else 0))
    op_target = sum(1 for a in out if a["score"] is not None and a["score"] >= 100)
    onder = sum(1 for a in out if a["score"] is not None and 70 <= a["score"] < 100)
    delist = sum(1 for a in out if a["score"] is not None and a["score"] < 70)
    return {"available": True, "artikelen": out, "labels": labels,
            "resolution": res.as_dict(),
            "stats": {"op_target": op_target, "onder_target": onder, "delist": delist}}
