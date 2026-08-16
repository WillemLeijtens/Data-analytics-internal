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
from .periods import is_afgesloten, period_number, period_year, sort_key
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
    # Feiten uit een test-profiel tellen alleen mee zolang dát profiel het
    # actieve is; zodra er een live versie staat, horen oude testcijfers niet
    # meer in de analyses thuis.
    prof = active_profile(conn, retailer_id)
    include_test = bool(prof and prof.status == "test")
    conds, params = [], []
    for col, vals in (("merk", merk), ("land", land), ("banner", banner)):
        if vals:
            conds.append(f"AND f.{col} IN ({','.join('?' * len(vals))})")
            params.extend(vals)
    return _facts(conn, retailer_id, include_test=include_test,
                  extra=" ".join(conds), params=tuple(params))


def manual_store_settings(conn, retailer_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT merk, land, banner, aantal_winkels FROM retailer_settings "
        "WHERE retailer_id=? AND aantal_winkels IS NOT NULL", (retailer_id,))]


def stores_with_revenue(rows, jaar: int | None) -> set:
    """Winkels die in dat jaar daadwerkelijk omzet gedraaid hebben.

    Een winkellijst bevat ook filialen die het merk (nog) niet voeren of het
    hele jaar niets verkochten. Die meetellen in de noemer drukt de
    gemiddelde omzet per winkel kunstmatig omlaag. Het jaartotaal is de
    maatstaf, niet de losse maand: een winkel die in juli toevallig niets
    verkocht hoort wél bij het winkelbestand van dat jaar."""
    return {r["winkel_id"] for r in rows
            if r["winkel_id"] and r["omzet"]
            and (jaar is None or period_year(r["periode"]) == jaar)}


def store_count(conn, retailer_id: str, caps: dict, rows, peil: str | None,
                settings: list[dict] | None = None) -> tuple[int | None, bool]:
    """(aantal winkels, uit_de_feiten). Valt terug op de handmatige
    instellingen (SCHATTING).

    `peil` is een periode; het telt mee als jáár, niet als losse periode —
    zie `stores_with_revenue`. None = alle jaren in `rows`.

    Instellingen staan per merk. Hetzelfde fysieke winkelbestand komt dus
    één keer per merk voor; simpelweg optellen zou het aantal winkels
    vermenigvuldigen met het aantal merken en de omzet per winkel even zo
    vaak te laag maken. Binnen een land/banner-scope telt daarom het
    grootste ingestelde aantal, en scopes worden bij elkaar opgeteld."""
    if caps.get("winkel"):
        stores = stores_with_revenue(rows, period_year(peil) if peil else None)
        if stores:
            return len(stores), True
    if settings is None:
        settings = manual_store_settings(conn, retailer_id)
    selected = {(r["merk"], r["land"], r["banner"] if caps.get("banner") else None)
                for r in rows}
    per_scope: dict[tuple, int] = {}
    for s in settings:
        if not s["aantal_winkels"] or s["aantal_winkels"] <= 0:
            continue
        key = (s["merk"], s["land"], s["banner"] if caps.get("banner") else None)
        if key not in selected:
            continue
        scope = (s["land"], s["banner"] if caps.get("banner") else None)
        per_scope[scope] = max(per_scope.get(scope, 0), s["aantal_winkels"])
    return (sum(per_scope.values()) or None), False


ACTIEPUNT_GESTOPT = ("Neem contact op met de category manager om na te gaan "
                     "waarom deze winkel(s) geen omzet meer draaien.")

# Eén lege maand is bij een langzaamlopend merk als DEPEND gewoon ruis: veel
# winkels verkopen dan een enkele maand niets zonder dat er iets aan de hand
# is. Pas vanaf twee opeenvolgende lege maanden noemen we het gestopt; de
# winkels met één lege maand blijven wél zichtbaar, als signaal.
GESTOPT_VANAF = 2

# Onder dit aantal niet-actieperiodes in hetzelfde jaar is een basislijn geen
# meting maar een toevalstreffer; dan tonen we geen uplift-percentage.
MIN_BASISPERIODES = 3

# Een artikel dat net in het schap ligt heeft nog geen rotatie die iets zegt;
# onder dit aantal periodes met verkoop geven we geen delist-oordeel.
MIN_ACTIEVE_PERIODES = 4


def winkelanalyse(rows, caps: dict, jaar: int) -> dict:
    """Winkels die dit jaar stilgevallen zijn, en winkels die erbij kwamen.

    Per winkel én merk: een winkel kan het ene merk laten vallen en het
    andere blijven voeren, en dat is precies het gesprek met de category
    manager. Stilgevallen = dit jaar ergens omzet (of vorig jaar omzet) maar
    in de laatste maand(en) niets meer.

    Gemiste omzet wordt gemeten over hetzelfde venster als de stilstand: de
    maanden ná de laatste maand mét omzet, uit vorig jaar. Het hele vorige
    jaar nemen terwijl dit jaar pas tot juli loopt, telt maanden mee die nog
    moeten komen — op de echte ICI-data bijna een factor twee te hoog."""
    if not caps.get("winkel"):
        return {"beschikbaar": False}

    per: dict[tuple, dict] = {}
    for r in rows:
        if not r["winkel_id"]:
            continue
        j = period_year(r["periode"])
        if j not in (jaar, jaar - 1):
            continue
        k = (r["winkel_id"], r["merk"])
        w = per.setdefault(k, {"winkel_id": r["winkel_id"], "winkel_naam": r["winkel_naam"],
                               "merk": r["merk"], "nu": {}, "vorig": {}})
        bucket = w["nu"] if j == jaar else w["vorig"]
        m = period_number(r["periode"])
        bucket[m] = bucket.get(m, 0.0) + r["omzet"]

    maanden = sorted({period_number(r["periode"]) for r in rows
                      if period_year(r["periode"]) == jaar})
    # Merken zonder vorig jaar in de database: dan is "vorig jaar geen omzet"
    # geen waarneming maar een gat in de data, en zou élke winkel als nieuw
    # gemeld worden (op de echte ICI-data 244 in plaats van 2).
    met_historie = {w["merk"] for w in per.values() if any(w["vorig"].values())}
    zonder_historie = sorted({w["merk"] for w in per.values()} - met_historie,
                             key=lambda m: (m is None, m))
    leeg_resultaat = {
        "beschikbaar": True, "jaar": jaar, "gestopt": [], "signalen": [],
        "toegevoegd": [], "gemiste_omzet": 0.0, "gestopt_vanaf": GESTOPT_VANAF,
        "historie_ontbreekt": zonder_historie, "actiepunt": ACTIEPUNT_GESTOPT}
    if not maanden:
        return leeg_resultaat
    laatste = maanden[-1]

    gestopt, signalen, toegevoegd = [], [], []
    for w in per.values():
        met_omzet = sorted(m for m, v in w["nu"].items() if v)
        dit_jaar = sum(w["nu"].values())
        vorig_totaal = sum(w["vorig"].values())
        if not w["nu"].get(laatste) and (met_omzet or vorig_totaal):
            vanaf = (met_omzet[-1] if met_omzet else 0) + 1
            leeg = [m for m in maanden if m >= vanaf]
            regel = {
                "winkel_id": w["winkel_id"], "winkel_naam": w["winkel_naam"],
                "merk": w["merk"], "laatste_maand": met_omzet[-1] if met_omzet else None,
                "maanden_zonder_omzet": len(leeg),
                "omzet_dit_jaar": dit_jaar,
                # Wat we in dezelfde maanden vorig jaar wél verkochten.
                "gemist_zelfde_venster": sum(v for m, v in w["vorig"].items()
                                             if vanaf <= m <= laatste),
                "omzet_vorig_jaar": vorig_totaal}
            (gestopt if len(leeg) >= GESTOPT_VANAF else signalen).append(regel)
        elif met_omzet and not vorig_totaal and w["merk"] in met_historie:
            toegevoegd.append({
                "winkel_id": w["winkel_id"], "winkel_naam": w["winkel_naam"],
                "merk": w["merk"], "eerste_maand": met_omzet[0],
                "omzet_dit_jaar": dit_jaar})

    return {
        **leeg_resultaat,
        "laatste_maand": laatste,
        "gestopt": sorted(gestopt, key=lambda x: -x["gemist_zelfde_venster"]),
        # Nog niet gestopt, wel opvallend: één lege maand na eerdere omzet.
        "signalen": sorted(signalen, key=lambda x: -x["gemist_zelfde_venster"]),
        "toegevoegd": sorted(toegevoegd, key=lambda x: -x["omzet_dit_jaar"]),
        "gemiste_omzet": sum(g["gemist_zelfde_venster"] for g in gestopt),
    }


# ---------------------------------------------------------------- dashboard

def dashboard(conn, retailer_id: str, merk=None, land=None, banner=None) -> dict:
    caps, base_labels = retailer_caps(conn, retailer_id)
    if caps is None:
        return {"available": False, "reason": "PARSER PROFIEL ONTBREEKT"}
    res = fallback.resolve(caps, week=True, winkel=True, banner=True)
    labels = base_labels + res.labels

    # Eén query; het merk/land/banner-filter is een Python-subset zodat de
    # filterlijsten (uit all_rows) en de cijfers nooit uiteen kunnen lopen.
    all_rows = load_facts(conn, retailer_id)
    rows = [r for r in all_rows
            if (not merk or r["merk"] in merk)
            and (not land or r["land"] in land)
            and (not banner or r["banner"] in banner)]
    if not rows:
        return {"available": True, "empty": True, "resolution": res.as_dict(),
                "labels": labels, "capabilities": caps}
    settings = manual_store_settings(conn, retailer_id)

    periods = sorted({r["periode"] for r in rows}, key=sort_key)
    latest = periods[-1]
    latest_rows = [r for r in rows if r["periode"] == latest]
    # Loopt de laatste periode nog, dan is hij onvergelijkbaar met een hele
    # periode vorig jaar: de YTD rekent tot en met de laatste AFGESLOTEN
    # periode, terwijl de KPI de lopende periode wél toont — met een label.
    latest_compleet = is_afgesloten(latest)
    afgesloten = [p for p in periods if is_afgesloten(p)]
    ytd_ref = afgesloten[-1] if afgesloten else latest

    def agg(rs):
        return {"omzet": sum(r["omzet"] for r in rs),
                "volume": sum(r["volume"] for r in rs)}

    def brand_breakdown(rs, key):
        per = defaultdict(float)
        for r in rs:
            per[r["merk"] or "ONBEKEND"] += r[key]
        return sorted(({"merk": m, "waarde": v} for m, v in per.items()),
                      key=lambda x: -x["waarde"])

    def store_breakdown(periode):
        """Omzet van die periode per winkel, PER MERK — gedeeld door de
        winkels die dat merk dít jaar omzet gaven. Eén gedeeld winkelaantal
        voor alle merken samen deelt de omzet van het ene merk door het
        winkelbestand van het andere; bij ICI scheelt dat een factor: DEPEND
        verkoopt in ~100 winkels, TWEEZERMAN in ~142.

        De noemer komt uit álle rijen van het merk (het jaarfilter zit in
        store_count): een winkel die deze maand toevallig niets verkocht
        hoort er nog steeds bij."""
        per_brand: dict[str, list] = defaultdict(list)
        for r in rows:
            per_brand[r["merk"] or "ONBEKEND"].append(r)
        out = []
        for merk, brows in per_brand.items():
            n, uit_feiten = store_count(conn, retailer_id, caps, brows, periode, settings)
            rev = sum(r["omzet"] for r in brows if r["periode"] == periode)
            out.append({"merk": merk, "winkels": n, "schatting": not uit_feiten,
                        "waarde": (rev / n) if n else None})
        return sorted(out, key=lambda x: -(x["waarde"] or 0))

    kpi = agg(latest_rows)
    n_stores, from_facts = store_count(conn, retailer_id, caps, rows, latest, settings)
    if not from_facts and fallback.LABEL_SCHATTING not in labels:
        labels.append(fallback.LABEL_SCHATTING)
    per_store = (kpi["omzet"] / n_stores) if n_stores else None

    # YTD vs LYTD: same period window (1..latest number) in this and prior
    # year — geteld t/m de laatste AFGESLOTEN periode.
    y_now = period_year(ytd_ref)
    upto = period_number(ytd_ref)

    def ytd_rows(year):
        return [r for r in rows if period_year(r["periode"]) == year
                and period_number(r["periode"]) <= upto]

    # De absolute totalen tellen álles: dat is feitelijk juist.
    now_rows, prior_rows = ytd_rows(y_now), ytd_rows(y_now - 1)
    ytd_now, ytd_prior = agg(now_rows), agg(prior_rows)

    # Maar het DELTA-percentage alleen op VERGELIJKBARE basis. Merk-feeds
    # verschillen in historie en actualiteit: in de audit toonde het
    # dashboard "+42,1% YTD" terwijl 2025 één merk-feed bevatte en 2026 drie
    # — de "groei" was vooral "twee merken erbij in de feed". Daarom telt
    # per merk alleen het venster waarin dat merk in BEIDE jaren data heeft,
    # en vallen merken zonder vorig jaar buiten het percentage (wel gemeld).
    per_merk_jaar: dict[tuple, list] = defaultdict(list)
    for r in rows:
        per_merk_jaar[(r["merk"], period_year(r["periode"]))].append(r)
    vergelijkbaar, niet_vergelijkbaar = [], []
    for m in sorted({m for m, _ in per_merk_jaar}, key=lambda x: (x is None, x or "")):
        nu_r = per_merk_jaar.get((m, y_now), [])
        vorig_r = per_merk_jaar.get((m, y_now - 1), [])
        if nu_r and vorig_r:
            # Stopt de feed van dit merk eerder dan de algemene YTD-grens,
            # dan telt voor dit merk ook vorig jaar maar tot daar.
            upto_m = min(upto, max(period_number(r["periode"]) for r in nu_r))
            vergelijkbaar.append({"merk": m, "tot_periode": upto_m})
        elif nu_r or any(period_number(r["periode"]) <= upto for r in vorig_r):
            niet_vergelijkbaar.append(m)

    def comp_rows(year):
        out = []
        for v in vergelijkbaar:
            out.extend(r for r in per_merk_jaar.get((v["merk"], year), [])
                       if period_number(r["periode"]) <= v["tot_periode"])
        return out

    comp_now, comp_prior = comp_rows(y_now), comp_rows(y_now - 1)
    comp_now_agg, comp_prior_agg = agg(comp_now), agg(comp_prior)
    basis_volledig = (not niet_vergelijkbaar
                      and all(v["tot_periode"] == upto for v in vergelijkbaar))

    def stores_for(year_rows):
        # Per jaar het winkelbestand van de laatste periode in dat jaar:
        # een gegroeid of gekrompen filiaalnet maakt anders de YoY-
        # vergelijking per winkel onvergelijkbaar.
        if not year_rows:
            return None, False
        final = max((r["periode"] for r in year_rows), key=sort_key)
        return store_count(conn, retailer_id, caps, year_rows, final, settings)

    # Omzet per winkel YTD is puur een vergelijkingskaart: reken hem op de
    # vergelijkbare merken. Zonder vergelijkbare basis toont "nu" alsnog
    # alles — er valt dan simpelweg niets te vergelijken.
    basis_now = comp_now if vergelijkbaar else now_rows
    stores_now, facts_now = stores_for(basis_now)
    stores_prior, facts_prior = stores_for(comp_prior)
    per_store_now = agg(basis_now)["omzet"] / stores_now if stores_now else None
    per_store_prior = comp_prior_agg["omzet"] / stores_prior if stores_prior else None

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
    # Omzet per winkel per periode met het winkelbestand ván dat jaar:
    # één vast aantal over de hele reeks vertekent groei of krimp, maar per
    # losse periode delen zou een winkel die die maand niets verkocht uit de
    # noemer laten vallen en de reeks laten stuiteren. Het aantal is binnen
    # een jaar dus voor elke periode gelijk — één keer per jaar tellen.
    rows_by_year = defaultdict(list)
    for r in rows:
        rows_by_year[period_year(r["periode"])].append(r)
    count_by_year = {
        y: store_count(conn, retailer_id, caps, rows_by_year[y],
                       max((r["periode"] for r in rows_by_year[y]), key=sort_key),
                       settings)[0]
        for y in years}
    per_winkel: dict = {}
    for y, perline in trend["series"]["omzet"].items():
        count = count_by_year.get(y)
        per_winkel[y] = {p: value / count for p, value in perline.items()} if count else {}
    trend["series"]["per_winkel"] = per_winkel
    # Merken waarvan de feed vóór de algemene laatste periode stopt: de som
    # zakt vanaf dat punt zonder dat er minder verkocht is. De grafiek meldt
    # dat, anders leest een achterlopende levering als omzetdaling.
    laatste_per_merk: dict = {}
    for r in rows:
        m = r["merk"]
        if m not in laatste_per_merk or sort_key(r["periode"]) > sort_key(laatste_per_merk[m]):
            laatste_per_merk[m] = r["periode"]
    trend["feeds_achter"] = sorted(
        ({"merk": m, "laatste_periode": p} for m, p in laatste_per_merk.items()
         if p != latest),
        key=lambda x: (x["merk"] is None, x["merk"] or ""))

    return {
        "available": True, "empty": False, "capabilities": caps,
        "resolution": res.as_dict(), "labels": labels,
        "periode_type": caps["periode"], "laatste_periode": latest,
        "laatste_periode_compleet": latest_compleet,
        "kpi": {
            "omzet": {"waarde": kpi["omzet"], "breakdown": brand_breakdown(latest_rows, "omzet")},
            "volume": {"waarde": kpi["volume"], "breakdown": brand_breakdown(latest_rows, "volume")},
            "omzet_per_winkel": {"waarde": per_store, "winkels": n_stores,
                                 "schatting": not from_facts,
                                 "breakdown": store_breakdown(latest)},
        },
        "ytd": {
            "jaar": y_now, "tot_periode": upto,
            "basis": {"volledig": basis_volledig,
                      "vergelijkbaar": vergelijkbaar,
                      "niet_vergelijkbaar": niet_vergelijkbaar},
            "omzet": {"nu": ytd_now["omzet"], "vorig": ytd_prior["omzet"],
                      "delta_pct": delta(comp_now_agg["omzet"], comp_prior_agg["omzet"])},
            "volume": {"nu": ytd_now["volume"], "vorig": ytd_prior["volume"],
                       "delta_pct": delta(comp_now_agg["volume"], comp_prior_agg["volume"])},
            "omzet_per_winkel": {
                "nu": per_store_now, "vorig": per_store_prior,
                "delta_pct": delta(per_store_now, per_store_prior)
                if per_store_now is not None and per_store_prior is not None else None,
                "schatting": not (facts_now and facts_prior)},
        },
        "trend": trend,
        "winkelanalyse": winkelanalyse(rows, caps, y_now),
        "filters": {
            "merk": sorted({r["merk"] for r in all_rows if r["merk"]}),
            "land": sorted({r["land"] for r in all_rows if r["land"]}),
            "banner": sorted({r["banner"] for r in all_rows if r["banner"]}),
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


def prijsindex(rows, key) -> dict[tuple, dict[str, float]]:
    """Prijsindex per scope per periode, met een VASTE artikelmix.

    De stukprijs van een hele scope (omzet ÷ volume over alle artikelen)
    beweegt net zo hard mee met de verkoopmix als met de prijs. Bij Kruidvat
    lopen de artikelprijzen van € 6,09 tot € 25,22: verkoopt het goedkope
    artikel een week wat meer, dan 'daalt' de gemiddelde prijs zonder dat er
    iets is afgeprijsd. Op de echte data leverde dat 42 van de 121 weken een
    actie-suggestie op, waarvan 16 puur mixverschuiving.

    Daarom per artikel de eigen prijs volgen en die met vaste gewichten
    (het jaarvolume van dat artikel) optellen. Wat overblijft is prijs.
    Gewichten en basisprijzen zijn per JAAR, want een prijspeil dat over de
    jaren stijgt zou anders elk ouder jaar als 'afgeprijsd' bestempelen.
    """
    cell: dict[tuple, list] = defaultdict(lambda: [0, 0.0])
    for r in rows:
        if not r["artikel_ean"]:
            continue
        c = cell[(key(r), period_year(r["periode"]), r["artikel_ean"], r["periode"])]
        c[0] += r["volume"]
        c[1] += r["omzet"]

    prijzen: dict[tuple, dict] = defaultdict(dict)   # (scope, jaar, ean) -> {periode: prijs}
    gewicht: dict[tuple, int] = defaultdict(int)     # (scope, jaar, ean) -> volume
    for (scope, jaar, ean, periode), (vol, rev) in cell.items():
        if vol:
            prijzen[(scope, jaar, ean)][periode] = rev / vol
            gewicht[(scope, jaar, ean)] += vol

    index: dict[tuple, dict[str, float]] = defaultdict(dict)
    per_scope_jaar: dict[tuple, list] = defaultdict(list)
    for sleutel in prijzen:
        per_scope_jaar[(sleutel[0], sleutel[1])].append(sleutel)
    for (scope, _jaar), sleutels in per_scope_jaar.items():
        periodes = {p for s in sleutels for p in prijzen[s]}
        for periode in periodes:
            teller = noemer = 0.0
            for s in sleutels:
                prijs = prijzen[s].get(periode)
                if prijs is not None and gewicht[s]:
                    teller += prijs * gewicht[s]
                    noemer += gewicht[s]
            if noemer:
                index[scope][periode] = teller / noemer
    return index


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

    confirmed = {(r["merk"], r["land"], r["banner"], r["periode"])
                 for r in conn.execute(
                     "SELECT merk, land, banner, periode FROM promo_confirmations WHERE retailer_id=?",
                     (retailer_id,))}

    # Een prijsdaling is alleen te meten met volume (stukprijs) én
    # artikelniveau (anders meet je de verkoopmix, niet de prijs).
    methode = "prijsindex" if caps.get("volume", True) and caps.get("artikel") else "handmatig"
    suggestions = []
    if methode == "prijsindex":
        index = prijsindex(rows, key)
        for scope, per_periode in index.items():
            per_jaar = defaultdict(dict)
            for periode, waarde in per_periode.items():
                per_jaar[period_year(periode)][periode] = waarde
            for _jaar, waarden in per_jaar.items():
                med = median(waarden.values())
                for periode, waarde in sorted(waarden.items(), key=lambda kv: sort_key(kv[0])):
                    drop = (med - waarde) / med if med else 0
                    merk, land, banner = scope
                    is_confirmed = (merk, land, banner, periode) in confirmed
                    if drop >= threshold or is_confirmed:
                        suggestions.append({
                            "merk": merk, "land": land, "banner": banner, "periode": periode,
                            "suggestie": f"afgeprijsd, -{round(drop * 100)}%" if drop >= threshold else None,
                            "bevestigd": is_confirmed})
        suggestions.sort(key=lambda s: (s["merk"] or "", sort_key(s["periode"])))
    else:
        # Zonder volume bestaat er geen stukprijs en dus geen automatische
        # suggestie — maar handmatig actieperiodes markeren moet blijven
        # werken, dus elke periode per scope staat in de tabel.
        for scope, periode in sorted(per_scope_period, key=lambda k: (k[0], sort_key(k[1]))):
            merk, land, banner = scope
            suggestions.append({
                "merk": merk, "land": land, "banner": banner, "periode": periode,
                "suggestie": None,
                "bevestigd": (merk, land, banner, periode) in confirmed})

    # Uplift per bevestigde actie: de actieperiode tegen de MEDIAAN van de
    # niet-actieperiodes uit HETZELFDE JAAR.
    #
    # Over alle jaren middelen vergelijkt door omzetniveaus heen: Kruidvat
    # draaide in 2024 € 33k per week en in 2025 € 47k, dus een actie werd
    # afgezet tegen een basislijn uit een ander regime. De mediaan in plaats
    # van het gemiddelde houdt één uitschieter (een andere, niet-bevestigde
    # actie) uit de basislijn. Bevestigde periodes blijven er sowieso buiten,
    # dus herimport van een bevestigde periode verschuift niets.
    uplift = []
    for merk, land, banner, periode in sorted(confirmed, key=lambda c: sort_key(c[3])):
        scope = (merk, land, banner)
        promo_rev = per_scope_period.get((scope, periode), {}).get("omzet")
        if promo_rev is None:
            continue
        jaar = period_year(periode)
        baseline_revs = [agg["omzet"] for (s, p), agg in per_scope_period.items()
                         if s == scope and period_year(p) == jaar
                         and (merk, land, banner, p) not in confirmed]
        regel = {"merk": merk, "land": land, "banner": banner, "periode": periode,
                 "jaar": jaar, "omzet": promo_rev, "basisperiodes": len(baseline_revs)}
        if len(baseline_revs) < MIN_BASISPERIODES:
            # Eén of twee referentieperiodes is geen basislijn maar toeval.
            regel.update({"basislijn": None, "uplift_pct": None,
                          "reden": "te weinig basisperiodes"})
        else:
            base = median(baseline_revs)
            regel.update({"basislijn": base,
                          "uplift_pct": round((promo_rev - base) / base * 100, 1)
                          if base else None})
        uplift.append(regel)
    uplift.sort(key=lambda u: -(u["uplift_pct"] or 0))
    return {"available": True, "suggesties": suggestions, "uplift": uplift,
            "drempel": threshold, "periode_type": caps["periode"], "methode": methode,
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
    n_stores, from_facts = store_count(conn, retailer_id, caps, rows, None)
    if not from_facts and fallback.LABEL_SCHATTING not in labels:
        labels.append(fallback.LABEL_SCHATTING)
    periods = {r["periode"] for r in rows}
    # De rotatietarget staat in stuks per winkel per WEEK; bij een maandfeed
    # moeten de periodes naar weken omgerekend worden, anders lijkt de
    # rotatie ruim vier keer zo hoog.
    weeks = (len(periods) * 52 / 12) if caps["periode"] == "maand" else len(periods)
    weeks = weeks or 1
    targets = {r["merk"]: r["stuks_per_winkel_per_week"] for r in conn.execute(
        "SELECT merk, stuks_per_winkel_per_week FROM rotatie_targets WHERE retailer_id=?",
        (retailer_id,))}

    per_art = defaultdict(lambda: {"volume": 0, "naam": None, "merk": None,
                                   "periodes": set(), "rijen": []})
    for r in rows:
        if not r["artikel_ean"]:
            continue
        a = per_art[r["artikel_ean"]]
        a["volume"] += r["volume"]
        a["naam"] = a["naam"] or r["artikel_naam"]
        a["merk"] = a["merk"] or r["merk"]
        a["rijen"].append(r)
        if r["volume"]:
            a["periodes"].add(r["periode"])

    geordend = sorted(periods, key=sort_key)

    out = []
    for ean, a in per_art.items():
        # Delen door het hele jaar terwijl een artikel pas in week 20 is
        # geïntroduceerd, maakt van een gezonde loper een delist-kandidaat.
        # Tel daarom vanaf de eerste periode mét verkoop.
        eerste = min(a["periodes"], key=sort_key) if a["periodes"] else None
        actief = len([p for p in geordend if sort_key(p) >= sort_key(eerste)]) if eerste else 0
        actieve_weken = (actief * 52 / 12) if caps["periode"] == "maand" else actief
        # En door de winkels die dít artikel voerden, niet door het hele
        # filiaalnet van het merk.
        art_stores, art_uit_feiten = store_count(conn, retailer_id, caps, a["rijen"], None)
        noemer_winkels = art_stores if art_uit_feiten else n_stores
        rotatie = (a["volume"] / actieve_weken / noemer_winkels
                   if actieve_weken and noemer_winkels else None)
        target = targets.get(a["merk"])
        score = round(rotatie / target * 100) if rotatie is not None and target else None
        if actief and actief < MIN_ACTIEVE_PERIODES:
            # Te vers om over te oordelen: één zwakke startweek is geen bewijs.
            advies = "Te kort geleden geïntroduceerd"
            score = None
        elif score is None:
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
                    "target": target, "score": score, "advies": advies,
                    "actieve_periodes": actief, "winkels": noemer_winkels})
    out.sort(key=lambda x: (x["score"] is None, x["score"] if x["score"] is not None else 0))
    op_target = sum(1 for a in out if a["score"] is not None and a["score"] >= 100)
    onder = sum(1 for a in out if a["score"] is not None and 70 <= a["score"] < 100)
    delist = sum(1 for a in out if a["score"] is not None and a["score"] < 70)
    return {"available": True, "artikelen": out, "labels": labels,
            "resolution": res.as_dict(), "periode_type": caps["periode"],
            "stats": {"op_target": op_target, "onder_target": onder, "delist": delist}}
