"""Analysis queries on the canonical fact table, always routed through the
fallback resolver so every result carries {level_used, labels}.

Facts from a profile in 'test' are visible in that retailer's own screens —
there is nothing else to look at while a profile is being proven — but they
carry the extra label 'PROFIEL IN TEST' and are excluded from cross-retailer
reporting (the imports flag makes both possible).
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from statistics import median

from . import dekking as dekking_mod
from . import fallback
from .periods import (is_afgesloten, period_number, period_type_of,
                      period_year, sort_key)
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
    # Ook rijen zonder winkelaantal: die kunnen wél een target dragen (bij
    # ICI komt het aantal uit de feed en is alleen het target invulbaar).
    return [dict(r) for r in conn.execute(
        "SELECT merk, land, banner, aantal_winkels, target_per_winkel "
        "FROM retailer_settings WHERE retailer_id=?", (retailer_id,))]


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


def periode_einddatum(periode: str) -> dt.date:
    """Laatste dag van een periode — het ijkpunt waartegen een meetdatum
    ('geldig vanaf') afgezet wordt."""
    jaar, nummer = period_year(periode), period_number(periode)
    if period_type_of(periode) == "maand":
        return (dt.date(jaar + (nummer == 12), (nummer % 12) + 1, 1)
                - dt.timedelta(days=1))
    try:
        return dt.date.fromisocalendar(jaar, nummer, 7)
    except ValueError:               # week 53 in een 52-weekjaar
        return dt.date.fromisocalendar(jaar, 52, 7)


# Voortschrijdend venster voor het winkelaantal uit de feiten. De maandtelling
# van een langzaamloper springt van 66 naar 102 winkels (DEPEND bij ICI) —
# dat is geen distributie die op en neer gaat maar een winkel die die maand
# toevallig niets verkocht. Over een kwartaal is dezelfde reeks stabiel.
VENSTER = {"maand": 3, "week": 13}


def winkels_per_periode(conn, retailer_id: str, caps: dict, rows, periodes: list[str],
                        settings: list[dict] | None = None,
                        historie: list[dict] | None = None) -> dict[str, tuple]:
    """{periode: (aantal_winkels, bron)} met bron feiten|gemeten|aangenomen.

    Twee bronnen, afhankelijk van wat de retailer levert:
      * winkelniveau in de feed -> unieke winkels mét omzet in een
        voortschrijdend venster (zie VENSTER);
      * anders -> stapfunctie uit de handmatige metingen: per periode de
        laatste meting die op of vóór het einde van die periode gold. Vóór de
        eerste meting rekenen we door met dat oudste getal, maar gemarkeerd
        als 'aangenomen' — anders zou de hele historie stilzwijgend door het
        winkelaantal van vandaag gedeeld worden.
    """
    if caps.get("winkel"):
        n = VENSTER.get(caps.get("periode"), 3)
        per_periode: dict[str, set] = defaultdict(set)
        for r in rows:
            if r["winkel_id"] and r["omzet"]:
                per_periode[r["periode"]].add(r["winkel_id"])
        out = {}
        for i, p in enumerate(periodes):
            venster = periodes[max(0, i - n + 1):i + 1]
            winkels = set().union(*[per_periode.get(v, set()) for v in venster]) \
                if venster else set()
            out[p] = (len(winkels) or None, "feiten")
        return out

    if historie is None:
        historie = [dict(r) for r in conn.execute(
            "SELECT merk, land, banner, aantal_winkels, geldig_vanaf "
            "FROM winkelaantal_historie WHERE retailer_id=? AND geldig_vanaf IS NOT NULL "
            "ORDER BY geldig_vanaf", (retailer_id,))]
    if settings is None:
        settings = manual_store_settings(conn, retailer_id)

    # Alleen de scopes die in deze (gefilterde) rijen voorkomen tellen mee,
    # en per land/banner het grootste aantal — zelfde regel als store_count,
    # zodat merken elkaar niet vermenigvuldigen.
    selected = {(r["merk"], r["land"], r["banner"] if caps.get("banner") else None)
                for r in rows}

    def totaal_op(datum: dt.date | None) -> tuple[int | None, bool]:
        per_scope: dict[tuple, int] = {}
        gemeten = False
        for merk, land, banner in selected:
            metingen = [h for h in historie
                        if h["merk"] == merk and h["land"] == land
                        and (not caps.get("banner") or h["banner"] == banner)]
            if not metingen:
                continue
            geldig = [h for h in metingen
                      if datum is None or dt.date.fromisoformat(h["geldig_vanaf"]) <= datum]
            if geldig:
                waarde, gemeten = geldig[-1]["aantal_winkels"], True
            else:
                waarde = metingen[0]["aantal_winkels"]      # oudste, aangenomen
            scope = (land, banner)
            per_scope[scope] = max(per_scope.get(scope, 0), waarde)
        return (sum(per_scope.values()) or None), gemeten

    terugval: tuple | None = None
    out = {}
    for p in periodes:
        aantal, gemeten = totaal_op(periode_einddatum(p))
        if aantal is None:
            # Geen historie: val terug op de huidige instelling, en wees
            # eerlijk dat dat een aanname is voor het verleden.
            #
            # Eén keer berekenen, niet per periode: zonder winkelniveau in de
            # feed kijkt store_count helemaal niet naar `peil`, dus komt er
            # voor elke periode hetzelfde getal uit. Wél elke keer aanroepen
            # kostte bij Kruidvat honderden volledige scans over alle rijen
            # per dashboard (1674 in een meting van drie aanroepen).
            if terugval is None:
                terugval = store_count(conn, retailer_id, caps, rows, p, settings)
            aantal = terugval[0]
            gemeten = False
        out[p] = (aantal, "gemeten" if gemeten else "aangenomen")
    return out


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
    filters = {
        "merk": sorted({r["merk"] for r in all_rows if r["merk"]}),
        "land": sorted({r["land"] for r in all_rows if r["land"]}),
        "banner": sorted({r["banner"] for r in all_rows if r["banner"]}),
    }
    if not rows:
        # gefilterd=True: er ís data, alleen niet voor deze filterkeuze. De
        # filters gaan mee zodat het scherm de chips kan blijven tonen —
        # anders zit de gebruiker vast in "Nog geen data geïmporteerd".
        return {"available": True, "empty": True, "gefilterd": bool(all_rows),
                "filters": filters, "resolution": res.as_dict(),
                "labels": labels, "capabilities": caps}
    settings = manual_store_settings(conn, retailer_id)
    # Gedateerde winkelaantallen: hiermee wordt elke periode gedeeld door het
    # winkelbestand zoals dat TÓEN gold, in plaats van door dat van vandaag.
    historie = [dict(r) for r in conn.execute(
        "SELECT merk, land, banner, aantal_winkels, geldig_vanaf "
        "FROM winkelaantal_historie WHERE retailer_id=? AND geldig_vanaf IS NOT NULL "
        "ORDER BY geldig_vanaf", (retailer_id,))]

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

    def dim_breakdown(rs, key, dim="merk"):
        """Verdeling van een KPI over een dimensie (merk / land / banner).

        `label` is wat het scherm toont; bij merk staat `merk` er nog naast
        zodat de merkkleuren en bestaande consumenten blijven werken. Een
        samengestelde bannerwaarde als "KV;TP" blijft één categorie: die
        omzet is in de feiten niet over formules te splitsen, dus splitsen
        zou een verdeling verzinnen die de bron niet levert."""
        per = defaultdict(float)
        for r in rs:
            per[r[dim] or "ONBEKEND"] += r[key]
        out = [{"label": k, "waarde": v} for k, v in per.items()]
        if dim == "merk":
            for o in out:
                o["merk"] = o["label"]
        return sorted(out, key=lambda x: -x["waarde"])

    def brand_breakdown(rs, key):
        return dim_breakdown(rs, key, "merk")

    def store_breakdown(periode, dim="merk"):
        """Omzet van die periode per winkel, per groep (merk / land /
        formule) — gedeeld door de winkels die die groep dít jaar omzet gaven. Eén gedeeld winkelaantal
        voor alle merken samen deelt de omzet van het ene merk door het
        winkelbestand van het andere; bij ICI scheelt dat een factor: DEPEND
        verkoopt in ~100 winkels, TWEEZERMAN in ~142.

        De noemer komt uit álle rijen van het merk (het jaarfilter zit in
        store_count): een winkel die deze maand toevallig niets verkocht
        hoort er nog steeds bij."""
        per_groep: dict[str, list] = defaultdict(list)
        for r in rows:
            per_groep[r[dim] or "ONBEKEND"].append(r)
        # Ingestelde target per merk (€ per winkel per periode) uit
        # Instellingen — vóór deze koppeling werd dat veld nergens gebruikt.
        # Targets zijn per merk vastgelegd, dus alleen op die dimensie
        # zinvol; over land of formule zou optellen een target verzinnen.
        targets_per_merk: dict = {}
        for s in settings:
            t = s.get("target_per_winkel")
            if t:
                targets_per_merk[s["merk"]] = max(targets_per_merk.get(s["merk"], 0), t)
        out = []
        for sleutel, brows in per_groep.items():
            n, uit_feiten = store_count(conn, retailer_id, caps, brows, periode, settings)
            rev = sum(r["omzet"] for r in brows if r["periode"] == periode)
            item = {"label": sleutel, "winkels": n, "schatting": not uit_feiten,
                    "waarde": (rev / n) if n else None,
                    "target": targets_per_merk.get(sleutel) if dim == "merk" else None}
            if dim == "merk":
                item["merk"] = sleutel
            out.append(item)
        return sorted(out, key=lambda x: -(x["waarde"] or 0))

    # Welke uitsplitsingen kán deze retailer tonen? Alleen dimensies die de
    # feed levert én die in de laatste periode daadwerkelijk gevuld zijn —
    # anders krijgt de gebruiker een knop die één balk "ONBEKEND" laat zien.
    # Twee of meer waarden: bij één waarde (Etos levert alleen NL) is de
    # "verdeling" één balk ter grootte van het totaal — een knop die niets
    # toevoegt. Filtert de gebruiker terug naar één land, dan verdwijnt de
    # knop om dezelfde reden.
    #
    # Gemeten over álle periodes, niet alleen de laatste: bij Kruidvat loopt
    # de BE-feed een week achter op NL, en dan zou de knop wekelijks komen en
    # gaan. De verdeling zelf gaat wél over de laatste periode; ontbreekt een
    # land daarin, dan staat het er niet bij (een balk van € 0 zou "niets
    # verkocht" suggereren terwijl de feed simpelweg nog niet geleverd heeft).
    dimensies = ["merk"] + [d for d in ("land", "banner")
                            if caps.get(d) and len({r[d] for r in rows if r[d]}) > 1]

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
    pWoord = "maand" if caps.get("periode") == "maand" else "week"

    def bereik(rs):
        """(eerste, laatste) periodenummer van een reeks rijen."""
        nummers = [period_number(r["periode"]) for r in rs]
        return (min(nummers), max(nummers)) if nummers else None

    dekking = {}
    for jaar in (y_now, y_now - 1):
        jaar_rijen = [r for r in rows if period_year(r["periode"]) == jaar]
        b = bereik(jaar_rijen)
        if b:
            dekking[jaar] = {"van": b[0], "tot": b[1]}

    def nummers(rs):
        """De periodenummers (t/m upto) waarin een reeks daadwerkelijk data heeft."""
        return {period_number(r["periode"]) for r in rs
                if period_number(r["periode"]) <= upto}

    # Het venster waarin BEIDE jaren data hebben, als DOORSNEDE van de
    # geleverde periodenummers — niet als bereik. Een bereik ziet binnengaten
    # niet: laadt iemand van 2025 alleen Q1 en Q4, dan telt "week 19 t/m 52"
    # de ontbrekende kwartalen als nul omzet en meldt het dashboard -46%
    # terwijl er niets gedaald is (gereproduceerd op de echte Etos-bestanden).
    vergelijkbaar, niet_vergelijkbaar = [], []
    venster_per_merk: dict = {}                  # merk -> set periodenummers
    for m in sorted({m for m, _ in per_merk_jaar}, key=lambda x: (x is None, x or "")):
        nu_r = per_merk_jaar.get((m, y_now), [])
        vorig_r = per_merk_jaar.get((m, y_now - 1), [])
        nu_n, vorig_n = nummers(nu_r), nummers(vorig_r)
        gedeeld = nu_n & vorig_n
        if gedeeld:
            van_m, tot_m = min(gedeeld), max(gedeeld)
            vergelijkbaar.append({
                "merk": m, "van_periode": van_m, "tot_periode": tot_m,
                # Wat er bínnen het venster ontbreekt: periodes die één van
                # beide jaren wél heeft maar de ander niet — die tellen in de
                # vergelijking niet mee en het scherm hoort dat te melden.
                # Periodes die geen van beide jaren levert zijn geen gat.
                "ontbrekend": sorted(n for n in (nu_n | vorig_n) - gedeeld
                                     if van_m <= n <= tot_m)})
            venster_per_merk[m] = gedeeld
            continue
        if nu_r or (vorig_r and min(nummers(vorig_r), default=upto + 1) <= upto):
            niet_vergelijkbaar.append(m)

    def comp_rows(year):
        out = []
        for v in vergelijkbaar:
            sel = venster_per_merk[v["merk"]]
            out.extend(r for r in per_merk_jaar.get((v["merk"], year), [])
                       if period_number(r["periode"]) in sel)
        return out

    comp_now, comp_prior = comp_rows(y_now), comp_rows(y_now - 1)
    comp_now_agg, comp_prior_agg = agg(comp_now), agg(comp_prior)
    def dekt_alles(v):
        """Valt er omzet van DIT jaar buiten het vergelijkingsvenster?

        Niet afmeten aan periode 1: een feed die in beide jaren pas in juni
        begint (ICI) vergelijkt juni-juli met juni-juli en verzwijgt niets.
        Het gaat erom of er iets van dit jaar buiten de boot valt — of dat er
        bínnen het venster periodes ontbreken (een niet-geladen kwartaal):
        ook dan wijkt de vergelijkingsbasis af en hoort de voetnoot te staan."""
        return not v["ontbrekend"] and \
            nummers(per_merk_jaar.get((v["merk"], y_now), [])) \
            <= venster_per_merk[v["merk"]]

    basis_volledig = not niet_vergelijkbaar and all(dekt_alles(v) for v in vergelijkbaar)

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

    # YTD per merk, op regelniveau. Elke regel gebruikt het EIGEN venster van
    # dat merk (1..tot_periode, op beide jaren toegepast) zodat de regel
    # intern appels-met-appels is; een merk zonder vorig jaar krijgt geen
    # delta maar een reden.
    randen_per_merk = {v["merk"]: (v["van_periode"], v["tot_periode"])
                       for v in vergelijkbaar}
    ontbrekend_per_merk = {v["merk"]: v["ontbrekend"] for v in vergelijkbaar}
    ytd_per_merk = []
    for m in sorted({m for m, _ in per_merk_jaar}, key=lambda x: (x is None, x or "")):
        van_m, tot_m = randen_per_merk.get(m, (1, upto))
        sel = venster_per_merk.get(m) or set(range(1, upto + 1))
        def merk_agg(year, _m=m, _sel=sel):
            return agg([r for r in per_merk_jaar.get((_m, year), [])
                        if period_number(r["periode"]) in _sel])
        nu_m, vorig_m = merk_agg(y_now), merk_agg(y_now - 1)
        if not nu_m["omzet"] and not nu_m["volume"] \
                and not vorig_m["omzet"] and not vorig_m["volume"]:
            continue
        heeft_basis = m in randen_per_merk
        reden = None
        if not heeft_basis:
            nu_b = bereik(per_merk_jaar.get((m, y_now), []))
            vorig_b = bereik(per_merk_jaar.get((m, y_now - 1), []))
            if nu_b and vorig_b:
                # Wél beide jaren, maar geen enkele gedeelde periode. Noem de
                # feiten, anders leest een leeg vakje als "niets verkocht".
                reden = (f"{y_now - 1} dekt {pWoord} {vorig_b[0]} t/m "
                         f"{vorig_b[1]}, {y_now} {pWoord} {nu_b[0]} t/m "
                         f"{min(upto, nu_b[1])} — geen gedeelde {pWoord}")
            else:
                reden = (f"geen {y_now - 1}" if nu_b else f"geen {y_now}")
        ytd_per_merk.append({
            "merk": m, "van_periode": van_m, "tot_periode": tot_m,
            "ontbrekend": ontbrekend_per_merk.get(m, []),
            "vergelijkbaar": heeft_basis, "reden": reden,
            "dekking": {str(j): bereik(per_merk_jaar.get((m, j), []))
                        for j in (y_now, y_now - 1)
                        if per_merk_jaar.get((m, j))},
            "omzet": {"nu": nu_m["omzet"], "vorig": vorig_m["omzet"],
                      "delta_pct": delta(nu_m["omzet"], vorig_m["omzet"])
                      if heeft_basis else None},
            "volume": {"nu": nu_m["volume"], "vorig": vorig_m["volume"],
                       "delta_pct": delta(nu_m["volume"], vorig_m["volume"])
                       if heeft_basis else None},
        })
    ytd_per_merk.sort(key=lambda x: -x["omzet"]["nu"])

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

    # ---- Tijdlijn: omzet per winkel mét het winkelbestand eronder --------
    # Een stijgend gemiddelde kan twee dingen betekenen — beter verkopen, of
    # minder winkels. Alleen als beide reeksen op dezelfde tijdas staan is
    # dat te scheiden, en de decompositie maakt het exact.
    tijdlijn_periodes = periods                      # chronologisch gesorteerd
    n_venster = VENSTER.get(caps["periode"], 3) if caps.get("winkel") else 1

    def reeks(rs) -> dict:
        omzet_p = defaultdict(float)
        for r in rs:
            omzet_p[r["periode"]] += r["omzet"]
        tellingen = winkels_per_periode(conn, retailer_id, caps, rs,
                                        tijdlijn_periodes, settings, historie)
        if caps.get("winkel"):
            ruw_sets: dict = defaultdict(set)
            for r in rs:
                if r["winkel_id"] and r["omzet"]:
                    ruw_sets[r["periode"]].add(r["winkel_id"])
            ruwe_tellingen = {p: len(w) or None for p, w in ruw_sets.items()}
        else:
            # Zonder winkelniveau is er geen venster: ruw == gladgestreken.
            ruwe_tellingen = {p: v[0] for p, v in tellingen.items()}
        omzet, winkels, per_winkel, bron = [], [], [], []
        winkels_ruw, per_winkel_ruw = [], []
        for i, p in enumerate(tijdlijn_periodes):
            aantal, herkomst = tellingen.get(p, (None, "aangenomen"))
            o = omzet_p.get(p, 0.0)
            omzet.append(round(o, 2))
            winkels.append(aantal)
            # Bij een voortschrijdend winkelaantal hoort een voortschrijdende
            # omzet: 1 maand omzet delen door 3 maanden winkels zou het
            # gemiddelde kunstmatig omlaag halen (in de proef 31 -> 21).
            venster = tijdlijn_periodes[max(0, i - n_venster + 1):i + 1]
            o_venster = sum(omzet_p.get(v, 0.0) for v in venster) / len(venster)
            per_winkel.append(round(o_venster / aantal, 2) if aantal else None)
            bron.append(herkomst)
            # Ongewogen naast de gladgestreken reeks: de decompositie moet
            # exact opgaan (omzet = winkels x omzet/winkel), en dat kan alleen
            # als teller en noemer over dezelfde periode gaan.
            ruw = ruwe_tellingen.get(p)
            winkels_ruw.append(ruw)
            per_winkel_ruw.append(round(o / ruw, 2) if ruw else None)
        return {"omzet": omzet, "winkels": winkels,
                "per_winkel": per_winkel, "bron": bron,
                "winkels_ruw": winkels_ruw, "per_winkel_ruw": per_winkel_ruw}

    per_merk_reeks = []
    for m in sorted({r["merk"] for r in rows}, key=lambda x: (x is None, x or "")):
        rs = [r for r in rows if r["merk"] == m]
        per_merk_reeks.append({"merk": m or "ONBEKEND", **reeks(rs)})
    totaal_reeks = reeks(rows)

    def decomponeer(serie: dict, nu_i: int, toen_i: int) -> dict | None:
        """omzet_t/omzet_0 = (winkels_t/winkels_0) x (perwinkel_t/perwinkel_0).
        Exact multiplicatief, dus de drie percentages sluiten op elkaar aan."""
        if nu_i < 0 or toen_i < 0:
            return None
        o_nu, o_toen = serie["omzet"][nu_i], serie["omzet"][toen_i]
        w_nu, w_toen = serie["winkels_ruw"][nu_i], serie["winkels_ruw"][toen_i]
        p_nu, p_toen = serie["per_winkel_ruw"][nu_i], serie["per_winkel_ruw"][toen_i]
        if not (o_toen and w_nu and w_toen and p_nu and p_toen):
            return None
        pct = lambda a, b: round((a / b - 1) * 100, 1)  # noqa: E731
        return {"omzet_pct": pct(o_nu, o_toen), "winkels_pct": pct(w_nu, w_toen),
                "per_winkel_pct": pct(p_nu, p_toen),
                "winkels_nu": w_nu, "winkels_toen": w_toen}

    # Laatste AFGESLOTEN periode tegen dezelfde periode vorig jaar.
    ref = ytd_ref if ytd_ref in tijdlijn_periodes else tijdlijn_periodes[-1]
    nu_i = tijdlijn_periodes.index(ref)
    vorig_label = (f"{period_year(ref) - 1}-W{period_number(ref):02d}"
                   if caps["periode"] == "week"
                   else f"{period_year(ref) - 1}-{period_number(ref):02d}")
    toen_i = tijdlijn_periodes.index(vorig_label) if vorig_label in tijdlijn_periodes else -1
    tijdlijn = {
        "periodes": tijdlijn_periodes,
        "venster": n_venster,
        "per_merk": per_merk_reeks,
        "totaal": totaal_reeks,
        "vergelijking": {"nu": ref, "vorig": vorig_label if toen_i >= 0 else None},
        "decompositie": {
            "totaal": decomponeer(totaal_reeks, nu_i, toen_i),
            "per_merk": [{"merk": r["merk"], **(decomponeer(r, nu_i, toen_i) or {})}
                         for r in per_merk_reeks
                         if decomponeer(r, nu_i, toen_i)],
        },
    }

    return {
        "available": True, "empty": False, "capabilities": caps,
        "resolution": res.as_dict(), "labels": labels,
        "periode_type": caps["periode"], "laatste_periode": latest,
        "laatste_periode_compleet": latest_compleet,
        "kpi": {
            "omzet": {"waarde": kpi["omzet"],
                      "breakdown": brand_breakdown(latest_rows, "omzet"),
                      "breakdowns": {d: dim_breakdown(latest_rows, "omzet", d)
                                     for d in dimensies}},
            "volume": {"waarde": kpi["volume"],
                       "breakdown": brand_breakdown(latest_rows, "volume"),
                       "breakdowns": {d: dim_breakdown(latest_rows, "volume", d)
                                      for d in dimensies}},
            "omzet_per_winkel": {"waarde": per_store, "winkels": n_stores,
                                 "schatting": not from_facts,
                                 "breakdown": store_breakdown(latest),
                                 "breakdowns": {d: store_breakdown(latest, d)
                                                for d in dimensies}},
        },
        "dimensies": dimensies,
        "ytd": {
            "jaar": y_now, "tot_periode": upto,
            # De comp-bedragen staan erbij: het Δ% is op deze basis gerekend
            # en hoort naast de volledige totalen narekenbaar te zijn.
            "basis": {"volledig": basis_volledig,
                      "vergelijkbaar": vergelijkbaar,
                      "niet_vergelijkbaar": niet_vergelijkbaar,
                      "omzet": {"nu": comp_now_agg["omzet"],
                                "vorig": comp_prior_agg["omzet"]},
                      "volume": {"nu": comp_now_agg["volume"],
                                 "vorig": comp_prior_agg["volume"]}},
            # Wat elk jaar feitelijk dekt. Zonder dit kan het scherm alleen
            # "€ 0" tonen waar het "dit jaar loopt niet over die weken" moet
            # zeggen — en dat leest als "niets verkocht".
            "dekking": dekking,
            "per_merk": ytd_per_merk,
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
        "tijdlijn": tijdlijn,
        "winkelanalyse": winkelanalyse(rows, caps, y_now),
        "filters": filters,
    }


# ---------------------------------------------------------------- articles

# "Recent" voor de delist-signalen: ongeveer een kwartaal.
RECENT_PERIODES = 13          # weken; bij een maandfeed 3 maanden

# Onder deze omzet per winkel per week ligt een artikel feitelijk niet meer
# in het schap: 530 winkels met EUR 50 omzet per week is EUR 0,09 per winkel
# — dat betekent dat het nog in een handvol winkels verkoopt, niet in 530.
#
# Gekalibreerd op de echte Etos-assortimentsverdeling (49 artikelen, laatste
# 13 weken, 530 winkels): gezonde lopers zitten op EUR 2 tot 8 per winkel per
# week, de mediaan op EUR 0,45, en onder EUR 0,10 zit de staart die ook op
# andere signalen dood oogt (o.a. een artikel met -96% jaar-op-jaar). Deze
# grens vlagt daar 10 van de 49, als vraag ("delisted?") en niet als oordeel.
MIN_OMZET_PER_WINKEL_PER_WEEK = 0.10


def _artikel_status(tot, ltot, recent_omzet, n_recent, n_stores, periode_type, jaar,
                    merk_heeft_vorig_jaar=True, merk_heeft_dit_jaar=True):
    """(status, reden, omzet per winkel per week) voor één artikel.

    nieuw     — dit jaar omzet, vorig jaar niet: nieuw in het schap.
    delisted  — vorig jaar wél omzet, dit jaar niets meer.
    delisted? — twijfel: dit jaar wel gestart maar recent stilgevallen, of
                nog wel omzet maar zo weinig dat het bij dit winkelbestand
                niet meer op distributie kan wijzen.

    De twee guards zijn dezelfde les als `winkelanalyse.met_historie`: zit
    het MERK zelf niet in een van beide jaren, dan is "geen omzet" daar een
    gat in de data en geen waarneming. Zonder guard kreeg elk artikel van
    een merk zonder geladen vorig jaar het label NIEUW (156 stuks op de
    echte Kruidvat-bestanden), en elk artikel van een merk waarvan de feed
    dit jaar nog niets leverde het label DELISTED.
    """
    if tot["omzet"] and not ltot["omzet"]:
        if not merk_heeft_vorig_jaar:
            return None, None, None
        return "nieuw", f"geen omzet in {jaar - 1}, dit jaar wel", None
    if ltot["omzet"] and not tot["omzet"]:
        if not merk_heeft_dit_jaar:
            return None, None, None
        return "delisted", f"wel omzet in {jaar - 1}, dit jaar niets", None

    weken = n_recent * (52 / 12) if periode_type == "maand" else n_recent
    per_winkel_week = (recent_omzet / n_stores / weken
                       if n_stores and weken else None)
    if tot["omzet"] and not recent_omzet:
        eenheid = "maanden" if periode_type == "maand" else "weken"
        return "delisted?", f"geen omzet in de laatste {n_recent} {eenheid}", per_winkel_week
    if per_winkel_week is not None and 0 < per_winkel_week < MIN_OMZET_PER_WINKEL_PER_WEEK:
        return ("delisted?",
                f"nog maar {fmt_eur(per_winkel_week)} per winkel per week "
                f"over {n_stores} winkels", per_winkel_week)
    return None, None, per_winkel_week


def fmt_eur(v: float) -> str:
    return f"€ {v:,.2f}".replace(",", "·").replace(".", ",").replace("·", ".")

def articles(conn, retailer_id: str, merk=None) -> dict:
    caps, base_labels = retailer_caps(conn, retailer_id)
    if caps is None:
        return {"available": False, "reason": "PARSER PROFIEL ONTBREEKT"}
    res = fallback.resolve(caps, artikel=True, week=True)
    if res.level_used.get("detail") != "artikel":
        return {"available": False, "reason": "GEGEVENS NIET BESCHIKBAAR",
                "resolution": res.as_dict(), "labels": base_labels + res.labels}
    # Eén query; het merkfilter is een Python-subset zodat de filterlijst en
    # de cijfers uit dezelfde rijen komen (zelfde patroon als dashboard).
    all_rows = load_facts(conn, retailer_id)
    rows = [r for r in all_rows if not merk or r["merk"] in merk]
    filters = {"merk": sorted({r["merk"] for r in all_rows if r["merk"]})}
    if not rows:
        return {"available": True, "artikelen": [], "filters": filters,
                "gefilterd": bool(all_rows),
                "labels": base_labels + res.labels, "resolution": res.as_dict()}
    periods = sorted({r["periode"] for r in rows}, key=sort_key)
    latest = periods[-1]
    # Dezelfde regel als het dashboard: YTD en de statusoordelen rekenen t/m
    # de laatste AFGESLOTEN periode. Een lopende week meetellen laat elk
    # artikel "dalen" en maakt de YoY-vergelijking oneerlijk.
    afgesloten = [p for p in periods if is_afgesloten(p)]
    ytd_ref = afgesloten[-1] if afgesloten else latest
    y_now, upto = period_year(ytd_ref), period_number(ytd_ref)

    # Alles wat over "de feed" gaat, gaat per MERK: merken komen in aparte
    # bestanden binnen en lopen onafhankelijk voor of achter. Eén gedeelde as
    # gaf artikelen van een achterlopend merk valse DELISTED?-labels en
    # YTD-delta's tot -100% (TWEEZERMAN liep 15 weken achter op de echte
    # Kruidvat-bestanden).
    merk_periodes: dict = defaultdict(set)
    for r in rows:
        merk_periodes[r["merk"]].add(r["periode"])
    n_terug = RECENT_PERIODES if caps["periode"] == "week" else 3
    merk_recent, merk_lytd, merk_dit_jaar, merk_venster = {}, {}, {}, {}
    for m, ps in merk_periodes.items():
        eigen_as = sorted(ps, key=sort_key)
        # Het "recente venster": ongeveer drie maanden, in de korrel van de
        # feed — gemeten op de as van het merk zelf.
        merk_recent[m] = set(eigen_as[-n_terug:])
        merk_lytd[m] = any(period_year(q) == y_now - 1 for q in ps)
        merk_dit_jaar[m] = any(period_year(q) == y_now for q in ps)
        # Vergelijkingsvenster: de periodenummers die BEIDE jaren hebben,
        # dezelfde doorsnede-regel als het dashboard.
        per_jaar = lambda j: {period_number(q) for q in ps
                              if period_year(q) == j and period_number(q) <= upto}
        merk_venster[m] = per_jaar(y_now) & per_jaar(y_now - 1)

    per_art: dict = {}
    for r in rows:
        if not r["artikel_ean"]:
            continue
        a = per_art.setdefault(r["artikel_ean"], {
            "ean": r["artikel_ean"], "naam": r["artikel_naam"], "merk": r["merk"],
            "ytd": defaultdict(lambda: {"volume": 0, "omzet": 0.0}),
            "lytd": defaultdict(lambda: {"volume": 0, "omzet": 0.0}),
            "laatste": {"volume": 0, "omzet": 0.0},
            "recent_omzet": 0.0, "rijen": []})
        a["rijen"].append(r)
        y, p = period_year(r["periode"]), period_number(r["periode"])
        bucket = a["ytd"] if y == y_now else a["lytd"] if y == y_now - 1 else None
        if bucket is not None and p <= upto:
            bucket[p]["volume"] += r["volume"]
            bucket[p]["omzet"] += r["omzet"]
        if r["periode"] in merk_recent.get(r["merk"], ()):
            a["recent_omzet"] += r["omzet"]
        if r["periode"] == latest:
            a["laatste"]["volume"] += r["volume"]
            a["laatste"]["omzet"] += r["omzet"]

    # Winkelaantal voor de "verdwijnt uit het schap"-toets: uit de feiten als
    # de retailer winkelniveau levert, anders het handmatige aantal.
    settings = manual_store_settings(conn, retailer_id)
    n_stores, _uit_feiten = store_count(conn, retailer_id, caps, rows, latest, settings)

    # Gaten in de aanlevering: een land of formule die eerder stopt, later
    # begint of een gat heeft, vertekent elk artikel dat daar verkocht wordt.
    alle_gaten = dekking_mod.gaten(rows, caps)

    out = []
    for a in per_art.values():
        tot = {k: sum(v[k] for v in a["ytd"].values()) for k in ("volume", "omzet")}
        ltot = {k: sum(v[k] for v in a["lytd"].values()) for k in ("volume", "omzet")}
        # De "verdwijnt uit het schap"-drempel deelt door de winkels van de
        # EIGEN scope van dit artikel; het retailer-brede totaal telt ook
        # landen en formules mee waar het artikel helemaal niet ligt.
        art_stores, _ = store_count(conn, retailer_id, caps, a["rijen"],
                                    latest, settings)
        status, reden, per_winkel_week = _artikel_status(
            tot, ltot, a["recent_omzet"], len(merk_recent.get(a["merk"], ())),
            art_stores or n_stores, caps["periode"], y_now,
            merk_heeft_vorig_jaar=merk_lytd.get(a["merk"], False),
            merk_heeft_dit_jaar=merk_dit_jaar.get(a["merk"], False))
        # Delta op de vergelijkbare basis van het merk (doorsnede van beide
        # jaren): een feed die korter of later loopt is geen omzetdaling.
        sel = merk_venster.get(a["merk"]) or None
        delta = None
        if sel:
            nu_v = sum(v["omzet"] for q, v in a["ytd"].items() if q in sel)
            vorig_v = sum(v["omzet"] for q, v in a["lytd"].items() if q in sel)
            if vorig_v:
                delta = round((nu_v - vorig_v) / vorig_v * 100, 1)
        out.append({
            "ean": a["ean"], "naam": a["naam"], "merk": a["merk"],
            "sparkline": {"ytd": {p: dict(v) for p, v in sorted(a["ytd"].items())},
                          "lytd": {p: dict(v) for p, v in sorted(a["lytd"].items())}},
            "laatste_periode": a["laatste"], "totaal_ytd": tot, "totaal_lytd": ltot,
            "status": status, "status_reden": reden,
            "dekking": dekking_mod.per_artikel(alle_gaten, a["rijen"], caps),
            "omzet_per_winkel_per_week": per_winkel_week,
            "ytd_delta_pct": delta})
    out.sort(key=lambda x: -x["totaal_ytd"]["omzet"])
    return {"available": True, "artikelen": out, "laatste_periode": latest,
            "filters": filters, "dekking": alle_gaten,
            # Het jaar hoort bij de data, niet bij de kalender van vandaag:
            # de grafieklegenda gebruikt dit in plaats van vaste jaartallen.
            "jaar": y_now,
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
        # Alleen afgesloten periodes: een halve week in de basislijn drukt de
        # mediaan, en een actie in een lopende week heeft nog geen uplift.
        baseline_revs = [agg["omzet"] for (s, p), agg in per_scope_period.items()
                         if s == scope and period_year(p) == jaar
                         and (merk, land, banner, p) not in confirmed
                         and is_afgesloten(p)]
        regel = {"merk": merk, "land": land, "banner": banner, "periode": periode,
                 "jaar": jaar, "omzet": promo_rev, "basisperiodes": len(baseline_revs)}
        if not is_afgesloten(periode):
            regel.update({"basislijn": None, "uplift_pct": None,
                          "reden": "periode loopt nog"})
        elif len(baseline_revs) < MIN_BASISPERIODES:
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
    settings = manual_store_settings(conn, retailer_id)
    n_stores, from_facts = store_count(conn, retailer_id, caps, rows, None, settings)
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
    alle_gaten = dekking_mod.gaten(rows, caps)

    out = []
    for ean, a in per_art.items():
        # Delen door het hele jaar terwijl een artikel pas in week 20 is
        # geïntroduceerd, maakt van een gezonde loper een delist-kandidaat.
        # Tel daarom vanaf de eerste periode mét verkoop.
        eerste = min(a["periodes"], key=sort_key) if a["periodes"] else None
        actief = len([p for p in geordend if sort_key(p) >= sort_key(eerste)]) if eerste else 0
        actieve_weken = (actief * 52 / 12) if caps["periode"] == "maand" else actief
        # En door de winkels van de EIGEN scope: uit de feiten als de feed
        # winkelniveau levert, anders het handmatige aantal van de eigen
        # merk/land/formule-combinatie. Het retailer-brede totaal is pas de
        # terugval als er voor deze scope niets is ingesteld — dat totaal
        # telt ook landen mee waar dit artikel niet ligt, en drukte op de
        # echte Kruidvat-data elke rotatie met ~30-45% (valse delists).
        art_stores, _ = store_count(conn, retailer_id, caps, a["rijen"], None, settings)
        noemer_winkels = art_stores or n_stores
        rotatie = (a["volume"] / actieve_weken / noemer_winkels
                   if actieve_weken and noemer_winkels else None)
        target = targets.get(a["merk"])
        score = round(rotatie / target * 100) if rotatie is not None and target else None
        if actief and actief < MIN_ACTIEVE_PERIODES:
            # Te vers om over te oordelen: één zwakke startweek is geen bewijs.
            advies = "Te kort geleden geïntroduceerd"
            score = None
        elif not actief:
            # Rijen zonder één verkochte periode dit jaar. "Geen target" zou
            # hier liegen: het target kan gewoon ingesteld staan.
            advies = "Geen verkoop dit jaar"
            score = None
        elif rotatie is None:
            advies = "Geen winkelaantal ingesteld"
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
                    "actieve_periodes": actief, "winkels": noemer_winkels,
                    "dekking": dekking_mod.per_artikel(alle_gaten, a["rijen"], caps)})
    out.sort(key=lambda x: (x["score"] is None, x["score"] if x["score"] is not None else 0))
    op_target = sum(1 for a in out if a["score"] is not None and a["score"] >= 100)
    onder = sum(1 for a in out if a["score"] is not None and 70 <= a["score"] < 100)
    delist = sum(1 for a in out if a["score"] is not None and a["score"] < 70)
    return {"available": True, "artikelen": out, "labels": labels,
            "resolution": res.as_dict(), "periode_type": caps["periode"],
            "dekking": alle_gaten,
            "stats": {"op_target": op_target, "onder_target": onder, "delist": delist}}
