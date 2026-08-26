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
from . import promoties as promo_mod
from . import winkelniveau
from .periods import (is_afgesloten, kalendermaand, maand_label, period_number,
                      period_type_of, period_year, sort_key, vorige_periode)
from .profile import active_profile, capabilities

LABEL_TEST = "PROFIEL IN TEST"


def retailer_caps(conn, retailer_id: str) -> tuple[dict | None, list[str]]:
    """(capabilities, base_labels) for a retailer, or (None, []) without profile.

    De profielvlag `winkel` zegt wat het FORMAAT aankan. Etos levert dezelfde
    widget met én zonder de kolommen Store/City, dus wordt hij hier getoetst
    aan de geladen feiten: claimt de app winkelniveau terwijl er geen enkel
    winkelnummer in de data staat, dan zou het instellingenscherm het
    handmatige winkelaantal blokkeren ("uit feed") zonder dat er iets te
    tellen valt. Zolang er nog helemaal geen feiten zijn blijft de vlag
    staan — dan is er niets dat hem tegenspreekt.
    """
    prof = active_profile(conn, retailer_id)
    if not prof:
        return None, []
    caps = capabilities(prof.definition)
    if caps.get("winkel"):
        heeft_feiten = conn.execute(
            "SELECT 1 FROM sellout_facts WHERE retailer_id=? LIMIT 1",
            (retailer_id,)).fetchone()
        met_winkel = conn.execute(
            "SELECT 1 FROM sellout_facts WHERE retailer_id=? AND winkel_id IS NOT NULL "
            "LIMIT 1", (retailer_id,)).fetchone()
        caps["winkel"] = bool(met_winkel) or not heeft_feiten
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
    """De handmatige instellingen, met het winkelaantal al opgelost.

    Staat een scope op artikelniveau, dan komt `aantal_winkels` uit de
    artikelen (het grootste; zie engine/winkelniveau.py voor waarom niet de
    som). De rest van de analyses hoeft daardoor niets van niveaus te weten
    en blijft met één getal per scope rekenen.

    Ook rijen zonder winkelaantal komen mee: die kunnen wél een target dragen
    (bij ICI komt het aantal uit de feed en is alleen het target invulbaar).
    """
    artikelen = winkelniveau.laad(conn, retailer_id)
    uit = []
    for r in conn.execute(
            "SELECT merk, land, banner, aantal_winkels, target_per_winkel, niveau "
            "FROM retailer_settings WHERE retailer_id=?", (retailer_id,)):
        rij = dict(r)
        sleutel = winkelniveau.sleutel(rij["merk"], rij["land"], rij["banner"])
        rij["aantal_winkels"] = winkelniveau.effectief(rij, artikelen.get(sleutel, []))
        uit.append(rij)
    return uit


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
    # De banner-vraag buiten de lus: deze setcomp loopt over álle rijen en is
    # met tienduizenden rijen de duurste regel van het dashboardprofiel.
    if caps.get("banner"):
        selected = {(r["merk"], r["land"], r["banner"]) for r in rows}
    else:
        selected = {(r["merk"], r["land"], None) for r in rows}
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
    if caps.get("banner"):
        selected = {(r["merk"], r["land"], r["banner"]) for r in rows}
    else:
        selected = {(r["merk"], r["land"], None) for r in rows}

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
#
# Let op: die redenering gaat over MAANDEN, terwijl de drempel in PERIODES
# telt. Bij een weekfeed (Etos) is twee lege weken niets — daar hoort een
# hogere drempel. Per retailer instelbaar in Instellingen -> Doelstellingen
# (tabel winkelsignaal_drempels); deze waarden gelden zolang niemand iets
# heeft ingesteld, zodat bestaande installaties niet ineens anders rekenen.
LETOP_VANAF = 1
GESTOPT_VANAF = 2

# Onder dit aantal niet-actieperiodes in hetzelfde jaar is een basislijn geen
# meting maar een toevalstreffer; dan tonen we geen uplift-percentage.
MIN_BASISPERIODES = 3

# Een artikel dat net in het schap ligt heeft nog geen rotatie die iets zegt;
# onder dit aantal periodes met verkoop geven we geen delist-oordeel.
MIN_ACTIEVE_PERIODES = 4

# De rotatie rekent over de huidige maand. Onder dit aantal weken data in die
# maand geven we geen delist-oordeel: één week is voor een langzame loper geen
# bewijs, maar het cijfer zelf is wel al te zien.
MIN_WEKEN_MAAND = 2


def signaal_drempels(conn, retailer_id: str) -> tuple[int, int]:
    """(let op vanaf, gestopt vanaf) in periodes, uit de instellingen."""
    r = conn.execute(
        "SELECT letop_vanaf, gestopt_vanaf FROM winkelsignaal_drempels WHERE retailer_id=?",
        (retailer_id,)).fetchone()
    return ((r["letop_vanaf"], r["gestopt_vanaf"]) if r
            else (LETOP_VANAF, GESTOPT_VANAF))


def winkelanalyse(rows, caps: dict, jaar: int,
                  drempels: tuple[int, int] | None = None) -> dict:
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
    letop_vanaf, gestopt_vanaf = drempels or (LETOP_VANAF, GESTOPT_VANAF)

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
        "toegevoegd": [], "gemiste_omzet": 0.0,
        "gestopt_vanaf": gestopt_vanaf, "letop_vanaf": letop_vanaf,
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

            # Het eigen verkoopritme: de mediane tussenpoos tussen periodes
            # mét omzet. Eén vaste drempel kent dit verschil niet: een winkel
            # die elke week verkoopt en er 3 stilvalt is alarmerender dan een
            # hakkelige verkoper die er 6 niets doet. De ingestelde drempels
            # blijven de VLOER; het ritme schaalt automatisch mee. Onder de
            # drie verkoopperiodes is er geen ritme om op te leunen en geldt
            # alleen de vloer.
            ritme = None
            if len(met_omzet) >= 3:
                tussenpozen = sorted(b - a for a, b in zip(met_omzet, met_omzet[1:]))
                ritme = tussenpozen[len(tussenpozen) // 2]
            stil = len(leeg)
            is_gestopt = stil >= gestopt_vanaf and (ritme is None or stil >= 3 * ritme)
            is_letop = stil >= letop_vanaf and (ritme is None or stil >= 2 * ritme)

            # Gemist: dezelfde periodes vorig jaar als die er zijn. Zonder
            # vorig jaar (Etos begon in 2026) bleef hier € 0 staan en was de
            # hele kolom — en de sortering erop — betekenisloos. Dan een
            # schatting op het eigen ritme: gemiddelde omzet per ACTIEVE
            # periode gedeeld door de tussenpoos = verwachte omzet per
            # kalenderperiode, maal de stilte.
            gemist = sum(v for m, v in w["vorig"].items() if vanaf <= m <= laatste)
            gemist_bron = "vorig_jaar"
            if not vorig_totaal and met_omzet:
                per_actieve = dit_jaar / len(met_omzet)
                gemist = per_actieve / (ritme or 1) * stil
                gemist_bron = "geschat"

            regel = {
                "winkel_id": w["winkel_id"], "winkel_naam": w["winkel_naam"],
                "merk": w["merk"], "laatste_maand": met_omzet[-1] if met_omzet else None,
                "maanden_zonder_omzet": stil,
                "ritme": ritme,
                "omzet_dit_jaar": dit_jaar,
                "gemist_zelfde_venster": round(gemist, 2),
                "gemist_bron": gemist_bron,
                # De weekreeks van dit jaar, alleen voor gemelde rijen: de
                # sparkline laat zien of het verval abrupt was of hakkelig.
                "reeks": {m: round(v, 2) for m, v in sorted(w["nu"].items())},
                "omzet_vorig_jaar": vorig_totaal}
            # Onder de "let op"-drempel valt de regel helemaal weg: bij een
            # weekfeed is één lege week ruis, en een lijst vol ruis leert je
            # het scherm te negeren.
            if is_gestopt:
                gestopt.append(regel)
            elif is_letop:
                signalen.append(regel)
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

def dashboard(conn, retailer_id: str, merk=None, land=None, banner=None,
             categorie=None) -> dict:
    caps, base_labels = retailer_caps(conn, retailer_id)
    if caps is None:
        return {"available": False, "reason": "PARSER PROFIEL ONTBREEKT"}
    res = fallback.resolve(caps, week=True, winkel=True, banner=True)
    labels = base_labels + res.labels

    # Eén query; het merk/land/banner/categorie-filter is een Python-subset
    # zodat de filterlijsten (uit all_rows) en de cijfers nooit uiteen
    # kunnen lopen.
    all_rows = load_facts(conn, retailer_id)
    rows = [r for r in all_rows
            if (not merk or r["merk"] in merk)
            and (not land or r["land"] in land)
            and (not banner or r["banner"] in banner)
            and (not categorie or r["categorie"] in categorie)]
    filters = {
        "merk": sorted({r["merk"] for r in all_rows if r["merk"]}),
        "land": sorted({r["land"] for r in all_rows if r["land"]}),
        "banner": sorted({r["banner"] for r in all_rows if r["banner"]}),
        # Alleen gevuld als de feed een categorie levert (vandaag: Etos met
        # de Class-kolom) — anders verschijnt er nergens een zinloze knop.
        "categorie": sorted({r["categorie"] for r in all_rows if r["categorie"]}),
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
        # `prev > 0`, niet `prev`: bij een negatieve basis (per saldo meer
        # retouren dan verkoop) draait het percentage van betekenis om —
        # van -100 naar -50 is een verbetering, maar (n-p)/p geeft dan -50%.
        # Geen percentage is eerlijker dan een omgekeerd leesbaar percentage.
        return round((now - prev) / prev * 100, 1) if prev and prev > 0 else None

    # Vorige periode (week-op-week of maand-op-maand) voor de KPI-kaarten
    # bovenaan het dashboard — losstaand van de YoY-vergelijking hieronder.
    # De kalenderperiode direct vóór de laatste, niet zomaar de vorige rij
    # met data: zonder data in die exacte periode (gat, of de feed begint
    # hier pas) blijft het percentage leeg in plaats van te vergelijken met
    # een willekeurige oudere periode die als "vorige week" zou uitlezen.
    vorige = vorige_periode(latest)
    vorige_rows = [r for r in rows if r["periode"] == vorige]
    if vorige_rows:
        vorige_kpi = agg(vorige_rows)
        vorige_n_stores, _ = store_count(conn, retailer_id, caps, rows, vorige, settings)
        vorige_per_store = (vorige_kpi["omzet"] / vorige_n_stores) if vorige_n_stores else None
    else:
        vorige_kpi = {"omzet": None, "volume": None}
        vorige_per_store = None

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
        winkels_ruw, per_winkel_ruw, omzet_ruw = [], [], []
        for i, p in enumerate(tijdlijn_periodes):
            aantal, herkomst = tellingen.get(p, (None, "aangenomen"))
            o = omzet_p.get(p, 0.0)
            omzet.append(round(o, 2))
            omzet_ruw.append(o)
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
                "winkels_ruw": winkels_ruw, "per_winkel_ruw": per_winkel_ruw,
                # Alleen voor decomponeer(): op centen afgeronde bedragen
                # laten de multiplicatieve identiteit niet meer opgaan.
                "omzet_ruw": omzet_ruw}

    per_merk_reeks = []
    for m in sorted({r["merk"] for r in rows}, key=lambda x: (x is None, x or "")):
        rs = [r for r in rows if r["merk"] == m]
        per_merk_reeks.append({"merk": m or "ONBEKEND", **reeks(rs)})
    totaal_reeks = reeks(rows)

    def decomponeer(serie: dict, nu_i: int, toen_i: int) -> dict | None:
        """omzet_t/omzet_0 = (winkels_t/winkels_0) x (perwinkel_t/perwinkel_0).

        Rekent op ONGERONDE bedragen. De weergavereeksen zijn op centen
        afgerond, en omzet/winkel daaruit overnemen brak de identiteit: bij
        een lage omzet per winkel (€ 0,30) liep het verschil op tot een hele
        procentpunt. Nu is omzet/winkel per definitie o/w, dus de drie
        percentages sluiten op elkaar aan op de afronding van de weergave na
        (elk hooguit 0,05 pp)."""
        if nu_i < 0 or toen_i < 0:
            return None
        o_nu, o_toen = serie["omzet_ruw"][nu_i], serie["omzet_ruw"][toen_i]
        w_nu, w_toen = serie["winkels_ruw"][nu_i], serie["winkels_ruw"][toen_i]
        if not (o_nu and o_toen and w_nu and w_toen):
            return None
        p_nu, p_toen = o_nu / w_nu, o_toen / w_toen
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
            "per_merk": [{"merk": r["merk"], **d}
                         for r, d in ((r, decomponeer(r, nu_i, toen_i))
                                      for r in per_merk_reeks) if d],
        },
    }

    return {
        "available": True, "empty": False, "capabilities": caps,
        "resolution": res.as_dict(), "labels": labels,
        "periode_type": caps["periode"], "laatste_periode": latest,
        "laatste_periode_compleet": latest_compleet,
        "kpi": {
            "omzet": {"waarde": kpi["omzet"],
                      "delta_pct": delta(kpi["omzet"], vorige_kpi["omzet"]),
                      "vorige_periode": vorige if vorige_rows else None,
                      "breakdown": brand_breakdown(latest_rows, "omzet"),
                      "breakdowns": {d: dim_breakdown(latest_rows, "omzet", d)
                                     for d in dimensies}},
            "volume": {"waarde": kpi["volume"],
                       "delta_pct": delta(kpi["volume"], vorige_kpi["volume"]),
                       "vorige_periode": vorige if vorige_rows else None,
                       "breakdown": brand_breakdown(latest_rows, "volume"),
                       "breakdowns": {d: dim_breakdown(latest_rows, "volume", d)
                                      for d in dimensies}},
            "omzet_per_winkel": {"waarde": per_store, "winkels": n_stores,
                                 "delta_pct": delta(per_store, vorige_per_store)
                                              if per_store is not None else None,
                                 "vorige_periode": vorige if vorige_rows else None,
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
            # Twee percentages, elk bij de twee getallen waaruit ze volgen.
            #
            # `delta_pct` is de groei op VERGELIJKBARE basis: per merk alleen
            # het venster dat beide jaren leveren. Dat is het cijfer waar een
            # beslissing op hoort te rusten — zonder die correctie las "twee
            # merk-feeds erbij" als groei en "een vergeten kwartaal" als
            # daling (beide gereproduceerd op echte bestanden).
            #
            # Maar het stond náást de volledige totalen, en die twee zijn niet
            # met elkaar te rijmen: "€ 4,4 mln tegen € 1,8 mln, +29%" leest als
            # een rekenfout. Daarom gaan de bedragen mee waarop het percentage
            # rust (`vergelijkbaar`), plus het percentage van de totalen zelf
            # (`totaal_delta_pct`) — zodat elk percentage op het scherm na te
            # rekenen is uit getallen die ernaast staan.
            "omzet": {"nu": ytd_now["omzet"], "vorig": ytd_prior["omzet"],
                      "delta_pct": delta(comp_now_agg["omzet"], comp_prior_agg["omzet"]),
                      "totaal_delta_pct": delta(ytd_now["omzet"], ytd_prior["omzet"]),
                      "vergelijkbaar": {"nu": comp_now_agg["omzet"],
                                        "vorig": comp_prior_agg["omzet"]}},
            "volume": {"nu": ytd_now["volume"], "vorig": ytd_prior["volume"],
                       "delta_pct": delta(comp_now_agg["volume"], comp_prior_agg["volume"]),
                       "totaal_delta_pct": delta(ytd_now["volume"], ytd_prior["volume"]),
                       "vergelijkbaar": {"nu": comp_now_agg["volume"],
                                         "vorig": comp_prior_agg["volume"]}},
            "omzet_per_winkel": {
                "nu": per_store_now, "vorig": per_store_prior,
                "delta_pct": delta(per_store_now, per_store_prior)
                if per_store_now is not None and per_store_prior is not None else None,
                "schatting": not (facts_now and facts_prior)},
        },
        "trend": trend,
        "tijdlijn": tijdlijn,
        "winkelanalyse": winkelanalyse(rows, caps, y_now,
                                       signaal_drempels(conn, retailer_id)),
        "filters": filters,
        # Bevestigde acties als markering op de trendgrafiek: een piek in de
        # lijn hoort zichzelf te verklaren op de plek waar je hem ziet, niet
        # pas op een ander scherm.
        "promoties": promo_markers(conn, retailer_id, rows, caps),
        # Wat er in de aanlevering ontbreekt ("vanaf week 4 geen data voor
        # België"). Stond alleen in de artikelanalyse, terwijl het dashboard
        # de plek is waar de totalen worden gelezen — en juist daar bepaalt
        # een stilgevallen feed of het cijfer nog iets betekent.
        # Let op: de sleutel "dekking" is hierboven al bezet (het YTD-venster
        # per jaar), vandaar deze naam.
        "dekkingsgaten": dekking_mod.gaten(rows, caps),
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


def _artikel_status(tot, ltot, ltot_jaar, recent_omzet, n_recent, n_stores, periode_type, jaar,
                    merk_heeft_vorig_jaar=True, merk_heeft_dit_jaar=True):
    """(status, reden, omzet per winkel per week) voor één artikel.

    nieuw     — dit jaar (YTD) omzet, HEEL vorig jaar niet: nieuw in het schap.
                Getoetst tegen het VOLLEDIGE vorige jaar (`ltot_jaar`), niet
                het YTD-venster (`ltot`): 2025 is een afgesloten jaar, dus een
                artikel dat toen pas vanaf week 40 startte hoort niet als
                NIEUW te gelden alleen omdat het venster t/m de huidige week
                nog geen 2025-omzet raakt — het bestond gewoon, alleen later.
    delisted  — vorig jaar (in hetzelfde venster) wél omzet, dit jaar niets
                meer. Hier telt wél het venster: het gaat om "verkocht dit
                jaar nog niet waar het toen al liep", niet om het hele jaar.
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
    if tot["omzet"] and not ltot_jaar["omzet"]:
        if not merk_heeft_vorig_jaar:
            return None, None, None
        return "nieuw", f"geen omzet in heel {jaar - 1}, dit jaar wel", None
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
    merk_eerste = {}
    for m, ps in merk_periodes.items():
        eigen_as = sorted(ps, key=sort_key)
        # De vroegste periode die dit merk überhaupt levert — de ondergrens
        # van wat over "sinds wanneer ligt dit artikel er" te zeggen valt.
        merk_eerste[m] = eigen_as[0]
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
            # Het HELE vorige jaar, niet het YTD-venster — voor de nieuw-toets
            # hieronder. 2025 is compleet: een artikel dat toen pas vanaf week
            # 40 startte hoort dit jaar niet als NIEUW te tellen alleen omdat
            # het venster t/m de huidige week nog geen 2025-omzet raakt.
            "lytd_jaar": {"volume": 0, "omzet": 0.0},
            "recent_omzet": 0.0, "rijen": []})
        a["rijen"].append(r)
        y, p = period_year(r["periode"]), period_number(r["periode"])
        bucket = a["ytd"] if y == y_now else a["lytd"] if y == y_now - 1 else None
        if bucket is not None and p <= upto:
            bucket[p]["volume"] += r["volume"]
            bucket[p]["omzet"] += r["omzet"]
        if y == y_now - 1:
            a["lytd_jaar"]["volume"] += r["volume"]
            a["lytd_jaar"]["omzet"] += r["omzet"]
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
        # ON COUNTER: de eerste periode waarin voor dit artikel omzet gemeten
        # is, in de korrel die de retailer levert (week bij Etos/Kruidvat,
        # maand bij ICI). Over ALLE geladen jaren, niet alleen dit jaar —
        # anders zou elk artikel elk jaar opnieuw "on counter" gaan.
        #
        # Regels zonder omzet tellen niet mee: een 0-regel betekent dat het
        # artikel die week gemeten is maar niets verkocht, en dat is niet het
        # moment dat het in het schap kwam.
        met_omzet = [r["periode"] for r in a["rijen"] if r["omzet"]]
        eerste = min(met_omzet, key=sort_key) if met_omzet else None
        # Valt die eerste meting samen met de start van de feed van dit merk,
        # dan is dit een ONDERGRENS: het artikel lag er mogelijk al eerder,
        # maar zo ver terug is er simpelweg geen data. Dat hoort erbij te
        # staan, anders leest een datagrens als een introductiedatum.
        begrensd = eerste is not None and eerste == merk_eerste.get(a["merk"])
        status, reden, per_winkel_week = _artikel_status(
            tot, ltot, a["lytd_jaar"], a["recent_omzet"], len(merk_recent.get(a["merk"], ())),
            art_stores or n_stores, caps["periode"], y_now,
            merk_heeft_vorig_jaar=merk_lytd.get(a["merk"], False),
            merk_heeft_dit_jaar=merk_dit_jaar.get(a["merk"], False))
        # Delta op de vergelijkbare basis van het merk (doorsnede van beide
        # jaren): een feed die korter of later loopt is geen omzetdaling.
        sel = merk_venster.get(a["merk"]) or None
        delta = None
        vergelijkbaar = None
        if sel:
            nu_v = sum(v["omzet"] for q, v in a["ytd"].items() if q in sel)
            vorig_v = sum(v["omzet"] for q, v in a["lytd"].items() if q in sel)
            # De bedragen gaan mee: het percentage is op dít venster gerekend,
            # niet op de totalen die in de tabel staan. Zonder die twee
            # getallen is het percentage niet na te rekenen — en dan lijkt het
            # fout terwijl het juist zorgvuldiger is.
            vergelijkbaar = {"nu": round(nu_v, 2), "vorig": round(vorig_v, 2)}
            if vorig_v:
                delta = round((nu_v - vorig_v) / vorig_v * 100, 1)
        out.append({
            "ean": a["ean"], "naam": a["naam"], "merk": a["merk"],
            "sparkline": {"ytd": {p: dict(v) for p, v in sorted(a["ytd"].items())},
                          "lytd": {p: dict(v) for p, v in sorted(a["lytd"].items())}},
            "laatste_periode": a["laatste"], "totaal_ytd": tot, "totaal_lytd": ltot,
            "on_counter": eerste, "on_counter_begrensd": begrensd,
            "status": status, "status_reden": reden,
            "dekking": dekking_mod.per_artikel(alle_gaten, a["rijen"], caps),
            "omzet_per_winkel_per_week": per_winkel_week,
            "ytd_delta_pct": delta, "ytd_vergelijkbaar": vergelijkbaar})
    out.sort(key=lambda x: -x["totaal_ytd"]["omzet"])
    return {"available": True, "artikelen": out, "laatste_periode": latest,
            "filters": filters, "dekking": alle_gaten,
            # Het jaar hoort bij de data, niet bij de kalender van vandaag:
            # de grafieklegenda gebruikt dit in plaats van vaste jaartallen.
            "jaar": y_now,
            "periode_type": caps["periode"], "labels": base_labels + res.labels,
            "resolution": res.as_dict()}


def promo_markers(conn, retailer_id: str, rows, caps: dict) -> list[dict]:
    """Bevestigde acties, klaar om op de trendgrafiek te zetten.

    De uplift komt uit `promotions()` zelf en wordt hier niet opnieuw
    uitgerekend: twee berekeningen van hetzelfde getal lopen vroeg of laat
    uiteen, en dan toont het dashboard een andere uplift dan de
    Promoties-pagina voor dezelfde week.

    Alleen de scopes die in deze (gefilterde) rijen voorkomen, zodat de
    markers het merkfilter van het dashboard volgen.
    """
    # Zonder bevestigde acties valt er niets te markeren. Die controle staat
    # vóór promotions(): die berekent de hele prijsindex over alle feiten en
    # verdubbelt anders de koude dashboardtijd voor een retailer waar nog
    # niets bevestigd is (gemeten: 0,9 s -> 1,6 s op 48k feiten).
    if not conn.execute(
            "SELECT 1 FROM promo_confirmations WHERE retailer_id=? LIMIT 1",
            (retailer_id,)).fetchone():
        return []

    zichtbaar = {_promo_scope_key(caps)(r) for r in rows}
    uit = []
    for u in promotions(conn, retailer_id).get("uplift", []):
        scope = (u["merk"], u["land"], u["banner"] if caps.get("banner") else None)
        if scope not in zichtbaar:
            continue
        uit.append({
            "merk": u["merk"], "land": u["land"], "banner": u["banner"],
            "jaar": u["jaar"], "periode_nummer": period_number(u["periode"]),
            "periode": u["periode"], "omzet": round(u["omzet"], 2),
            "basislijn": round(u["basislijn"], 2) if u.get("basislijn") else None,
            "uplift_pct": u.get("uplift_pct"),
            # Het aantal normale periodes achter de basislijn: de kaart op het
            # dashboard toont de bedragen mét deze context, anders is het
            # percentage daar niet na te rekenen.
            "basisperiodes": u.get("basisperiodes", 0),
            "reden": u.get("reden")})
    return sorted(uit, key=lambda m: (m["jaar"], m["periode_nummer"], m["merk"] or ""))


# ---------------------------------------------------------------- promotions

def _promo_scope_key(caps):
    return (lambda r: (r["merk"], r["land"], r["banner"])) if caps.get("banner") \
        else (lambda r: (r["merk"], r["land"], None))


def prijzen_per_artikel(rows, key) -> tuple[dict, dict]:
    """De stukprijs per artikel per periode, plus het jaargewicht per artikel.

    ({(scope, jaar, ean): {periode: prijs}}, {(scope, jaar, ean): jaarvolume})

    Losgetrokken uit `prijsindex` omdat de actiedetectie dezelfde cijfers per
    ARTIKEL nodig heeft: een actie op één artikel beweegt de gewogen index
    nauwelijks, maar is in de eigen prijsreeks van dat artikel goed te zien.
    Twee keer tellen zou twee waarheden opleveren.
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
    return prijzen, gewicht


def prijsindex(rows, key) -> dict[tuple, dict[str, float]]:
    """Prijsindex per scope per periode, als gewogen gemiddelde van
    prijsRELATIEVEN (prijs ÷ eigen jaarmediaan per artikel). ~1,0 = normaal.

    Twee mixeffecten moeten eruit, en dat vergt twee ingrepen:

    * De VERKOOPmix: de stukprijs van een scope (omzet ÷ volume) zakt al als
      het goedkope artikel een week wat meer verkoopt. Daarom per artikel de
      eigen prijs volgen, met vaste gewichten (het jaarvolume). Op de echte
      Kruidvat-data was 16 van 42 "acties" puur deze mixverschuiving.
    * De AANWEZIGHEIDSmix: een gewogen gemiddelde van prijsníveaus middelt
      alleen de artikelen die die week verkochten. Valt een duur artikel een
      week uit (geen verkoop — heel gewoon bij langzaamlopers), dan zakt zo'n
      index zonder dat er iets is afgeprijsd. Op de echte Etos-data schommelt
      de gewichtsdekking per week tussen 73% en 97% en verschoof dit ~20% van
      de vlaggen. Daarom relatieven: elk artikel draagt zijn eigen
      prijsverándering bij (≈1 in een normale week), en een ontbrekend
      artikel verschuift het niveau niet.

    Gewichten en basisprijzen (de mediaanprijs per artikel) zijn per JAAR,
    want een prijspeil dat over de jaren stijgt zou anders elk ouder jaar als
    'afgeprijsd' bestempelen.
    """
    prijzen, gewicht = prijzen_per_artikel(rows, key)

    index: dict[tuple, dict[str, float]] = defaultdict(dict)
    per_scope_jaar: dict[tuple, list] = defaultdict(list)
    for sleutel in prijzen:
        per_scope_jaar[(sleutel[0], sleutel[1])].append(sleutel)
    for (scope, _jaar), sleutels in per_scope_jaar.items():
        basis = {s: median(prijzen[s].values()) for s in sleutels}
        periodes = {p for s in sleutels for p in prijzen[s]}
        for periode in periodes:
            teller = noemer = 0.0
            for s in sleutels:
                prijs = prijzen[s].get(periode)
                if prijs is not None and gewicht[s] and basis[s]:
                    teller += (prijs / basis[s]) * gewicht[s]
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
    kwaliteit = promo_mod.periodekwaliteit(rows, key)
    suggestions = []
    if methode == "prijsindex":
        index = prijsindex(rows, key)
        prijzen, gewicht = prijzen_per_artikel(rows, key)
        for scope, per_periode in index.items():
            merk, land, banner = scope
            per_jaar = defaultdict(dict)
            for periode, waarde in per_periode.items():
                per_jaar[period_year(periode)][periode] = waarde
            for jaar, waarden in per_jaar.items():
                # De referentie negeert bevestigde acties en onvolledige
                # periodes: anders verklaart een actiejaar zijn eigen acties
                # weg (zie engine/promoties.py).
                negeer = {p for p in waarden
                          if (merk, land, banner, p) in confirmed
                          or kwaliteit.get((scope, p), "volledig") != "volledig"}
                # Twee passes. Niet-bevestigde actieweken zitten in pas 1 nog
                # in de referentie; bij een actierijk merk (PATCHOLOGY: 15 van
                # 33 weken) zakt de mediaan dan mee en blaast de MAD op, wat
                # de z-scores drukt. Pas 1 vlagt met de vervuilde referentie,
                # pas 2 rekent de definitieve cijfers met de gevlagde weken in
                # `negeer` — dezelfde regel die de uplift-basislijn al volgt.
                # Deterministisch: er is geen derde pas.
                ref1 = promo_mod.referentie(waarden, negeer)
                if ref1 and ref1[0]:
                    gevlagd = {p for p, w in waarden.items()
                               if (ref1[0] - w) / ref1[0] >= threshold}
                    negeer = negeer | gevlagd
                ref = promo_mod.referentie(waarden, negeer)
                if ref is None:
                    # Te veel weken gevlagd om nog een referentie over te
                    # houden: dan is de pas-1-referentie de beste die er is.
                    ref = ref1
                    negeer = {p for p in waarden
                              if (merk, land, banner, p) in confirmed
                              or kwaliteit.get((scope, p), "volledig") != "volledig"}
                vol_ref = promo_mod.referentie(
                    {p: per_scope_period[(scope, p)]["volume"] for p in waarden}, negeer)
                for periode, waarde in sorted(waarden.items(),
                                              key=lambda kv: sort_key(kv[0])):
                    is_confirmed = (merk, land, banner, periode) in confirmed
                    drop = z = None
                    stabiel_en_gedaald = False
                    if ref and ref[0]:
                        mid, spreiding, _n = ref
                        drop = (mid - waarde) / mid
                        z = ((mid - waarde) / spreiding) if spreiding else None
                        # Spreiding nul = de prijs stond het hele jaar vast.
                        # Geen z-score (delen door nul), maar een afwijking is
                        # dan juist het hardste bewijs.
                        stabiel_en_gedaald = spreiding == 0 and drop > 0
                    acties = promo_mod.artikelacties(
                        prijzen, gewicht, scope, jaar, periode, threshold, negeer)
                    verkocht = promo_mod._artikelen_met_verkoop(
                        prijzen, scope, jaar, periode, negeer)
                    bereik, telt_mee = promo_mod.bereik_van(acties, verkocht)
                    # Twee ingangen: de hele lijn zakt (index onder de drempel)
                    # of één artikel met gewicht is afgeprijsd. Dat tweede geval
                    # miste de index, want tien artikelen wegen één afprijzing weg.
                    breed = drop is not None and drop >= threshold
                    if not (breed or telt_mee or is_confirmed):
                        continue
                    respons = None
                    nu_vol = per_scope_period[(scope, periode)]["volume"]
                    if vol_ref and vol_ref[0]:
                        respons = (nu_vol - vol_ref[0]) / vol_ref[0]
                    kw = kwaliteit.get((scope, periode), "volledig")
                    score, delen = promo_mod.zekerheid(
                        z, respons, bereik, kw,
                        stabiel_en_gedaald=stabiel_en_gedaald,
                        n_referentie=ref[2] if ref else None)
                    suggestions.append({
                        "merk": merk, "land": land, "banner": banner, "periode": periode,
                        # Eén decimaal: bij hele procenten toonde een daling van
                        # 4,6% "-5%" terwijl de drempel 5% is — het getal sprak
                        # de regel tegen.
                        "suggestie": (f"afgeprijsd, -{drop * 100:.1f}%".replace(".", ",")
                                      if breed else
                                      (f"{sum(1 for a in acties if a['volumeaandeel_pct'] >= promo_mod.ARTIKEL_VOLUMEAANDEEL * 100)} artikel(en) afgeprijsd"
                                       if telt_mee else None)),
                        "bevestigd": is_confirmed,
                        "drop_pct": round(drop * 100, 1) if drop is not None else None,
                        "z": round(z, 1) if z is not None else None,
                        "volume_respons_pct": round(respons * 100, 1)
                        if respons is not None else None,
                        "bereik": bereik, "artikelen": acties[:8],
                        "artikelen_verkocht": verkocht,
                        "kwaliteit": kw,
                        "zekerheid": score, "zekerheid_delen": delen,
                        "referentieperiodes": ref[2] if ref else 0})
        suggestions.sort(key=lambda s: (s["merk"] or "", sort_key(s["periode"])))
    else:
        # Zonder volume bestaat er geen stukprijs en dus geen automatische
        # suggestie — maar handmatig actieperiodes markeren moet blijven
        # werken, dus elke periode per scope staat in de tabel.
        for scope, periode in sorted(per_scope_period, key=lambda k: (k[0], sort_key(k[1]))):
            merk, land, banner = scope
            # Dezelfde velden als de prijsindex-tak, met lege waarden: één
            # vorm voor de consument, ook al kan deze feed niets afleiden.
            suggestions.append({
                "merk": merk, "land": land, "banner": banner, "periode": periode,
                "suggestie": None, "bevestigd": (merk, land, banner, periode) in confirmed,
                "drop_pct": None, "z": None, "volume_respons_pct": None,
                "bereik": None, "artikelen": [], "artikelen_verkocht": 0,
                "kwaliteit": kwaliteit.get((scope, periode), "volledig"),
                "zekerheid": None, "zekerheid_delen": [], "referentieperiodes": 0})

    # Uplift per bevestigde actie: de actieperiode tegen de MEDIAAN van de
    # niet-actieperiodes uit HETZELFDE JAAR.
    #
    # Over alle jaren middelen vergelijkt door omzetniveaus heen: Kruidvat
    # draaide in 2024 € 33k per week en in 2025 € 47k, dus een actie werd
    # afgezet tegen een basislijn uit een ander regime. De mediaan in plaats
    # van het gemiddelde houdt één uitschieter (een andere, niet-bevestigde
    # actie) uit de basislijn. Bevestigde periodes blijven er sowieso buiten,
    # dus herimport van een bevestigde periode verschuift niets.
    # Wat NIET meetelt als normale periode: bevestigde acties, voorgestelde
    # acties, en periodes die niet volledig geleverd zijn. Eén definitie voor
    # zowel de basislijn van de uplift als het gemiddelde hieronder — anders
    # staan er twee versies van "een normale week" op dezelfde pagina.
    uitgesloten = {}
    for su in suggestions:
        # Alleen echte voorstellen tellen als actie. Zonder volume/artikelniveau
        # staat élke periode in de lijst (om handmatig te kunnen aanvinken);
        # die allemaal uitsluiten zou het gemiddelde leegmaken.
        if not su["bevestigd"] and not su["suggestie"]:
            continue
        sleutel = ((su["merk"], su["land"], su["banner"]), su["periode"])
        uitgesloten[sleutel] = "actie" if su["bevestigd"] else "voorstel"

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
                         and (s, p) not in uitgesloten
                         and kwaliteit.get((s, p), "volledig") == "volledig"]
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
            if not base:
                regel["reden"] = "basislijn is nul"
        uplift.append(regel)
    # Regels zonder uitspraak onderaan — niet gemengd tussen plus en min
    # alsof "geen oordeel" hetzelfde is als nul.
    uplift.sort(key=lambda u: (u["uplift_pct"] is None, -(u["uplift_pct"] or 0)))
    # Het basisniveau waartegen een actie afgezet hoort te worden: de
    # gemiddelde omzet per periode ZONDER acties en zonder onvolledige
    # periodes. Voorgestelde acties tellen ook niet mee — een niet-bevestigde
    # actieweek trekt het "normale" niveau anders omhoog.
    basis = promo_mod.gemiddelde_periodeomzet(per_scope_period, kwaliteit, uitgesloten)

    # Per merk het totaal: de opdracht vraagt om een gemiddelde per merk, maar
    # de detectie draait per merk x land x formule. Beide tonen, zodat de
    # merkregel aansluit op de scoperegels eronder.
    per_merk: dict[tuple, dict] = {}
    for b in basis:
        k = (b["merk"], b["jaar"])
        m = per_merk.setdefault(k, {"merk": b["merk"], "jaar": b["jaar"],
                                    "gemiddelde": 0.0, "periodes": 0, "scopes": 0})
        m["gemiddelde"] += b["gemiddelde"]
        m["periodes"] = max(m["periodes"], b["periodes"])
        m["scopes"] += 1
    for m in per_merk.values():
        m["gemiddelde"] = round(m["gemiddelde"], 2)

    onvolledig = sorted(
        ({"merk": s[0], "land": s[1], "banner": s[2], "periode": p, "reden": staat}
         for (s, p), staat in kwaliteit.items() if staat != "volledig"),
        key=lambda x: (x["merk"] or "", sort_key(x["periode"])))

    return {"available": True, "suggesties": suggestions, "uplift": uplift,
            "drempel": threshold, "periode_type": caps["periode"], "methode": methode,
            "basis": basis,
            "basis_per_merk": sorted(per_merk.values(),
                                     key=lambda m: (-m["jaar"], m["merk"] or "")),
            "onvolledige_periodes": onvolledig,
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
    # Winkelaantallen die per artikel zijn ingesteld: de rotatie hieronder
    # deelt dan door de winkels van dát artikel in plaats van door het merk.
    artikel_winkels = winkelniveau.laad(conn, retailer_id)
    n_stores, from_facts = store_count(conn, retailer_id, caps, rows, None, settings)
    if not from_facts and fallback.LABEL_SCHATTING not in labels:
        labels.append(fallback.LABEL_SCHATTING)
    periods = {r["periode"] for r in rows}
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

    # De rotatie kijkt naar de HUIDIGE MAAND, niet naar het hele jaar. Een
    # artikel dat in het voorjaar goed liep en sinds juni stilstaat, houdt
    # over het jaar gemiddeld een nette rotatie en valt dan nergens op; over
    # de laatste maand valt hij meteen door de mand. Het aantal weken komt
    # uit de DATA en niet uit de kalender: is er van augustus pas twee weken
    # geleverd, dan wordt door twee gedeeld en niet door 4,33.
    maand = kalendermaand(geordend[-1])
    maand_periodes = [p for p in geordend if kalendermaand(p) == maand]
    # De rotatietarget staat in stuks per winkel per WEEK. Een maandfeed
    # levert een hele maand in een periode; die staat voor 52/12 weken,
    # anders zou de rotatie ruim vier keer zo hoog lijken.
    weken_per_periode = 52 / 12 if caps["periode"] == "maand" else 1

    out = []
    for ean, a in per_art.items():
        eerste = min(a["periodes"], key=sort_key) if a["periodes"] else None
        actief = len([p for p in geordend if sort_key(p) >= sort_key(eerste)]) if eerste else 0
        # Delen door de hele maand terwijl een artikel er pas halverwege in
        # kwam, maakt van een gezonde loper een delist-kandidaat. Tel daarom
        # alleen de periodes van deze maand vanaf de eerste verkoop.
        venster = [p for p in maand_periodes
                   if eerste is None or sort_key(p) >= sort_key(eerste)]
        in_venster = set(venster)
        maand_volume = sum(r["volume"] for r in a["rijen"] if r["periode"] in in_venster)
        maand_weken = len(venster) * weken_per_periode
        # En door de winkels van de EIGEN scope: uit de feiten als de feed
        # winkelniveau levert, anders het handmatige aantal van de eigen
        # merk/land/formule-combinatie. Het retailer-brede totaal is pas de
        # terugval als er voor deze scope niets is ingesteld — dat totaal
        # telt ook landen mee waar dit artikel niet ligt, en drukte op de
        # echte Kruidvat-data elke rotatie met ~30-45% (valse delists).
        art_stores, art_uit_feiten = store_count(
            conn, retailer_id, caps, a["rijen"], None,
            winkelniveau.voor_artikel(settings, artikel_winkels, ean))
        noemer_winkels = art_stores or n_stores
        eigen = winkelniveau.eigen_aantal(settings, artikel_winkels, ean)
        # Welke van de twee scenario's dit artikel gebruikt, hoort zichtbaar
        # te zijn: anders is een winkelaantal in het scherm niet terug te
        # vinden in Instellingen omdat je op de verkeerde plek kijkt.
        if art_uit_feiten:
            bron = "feiten"
        elif not noemer_winkels:
            bron = None
        elif eigen is not None:
            bron = "artikel"
        elif art_stores:
            bron = "merk"
        else:
            bron = "retailer"
        rotatie = (maand_volume / maand_weken / noemer_winkels
                   if maand_weken and noemer_winkels else None)
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
        elif maand_weken < MIN_WEKEN_MAAND:
            # Eén week is voor een langzame loper geen bewijs: een artikel dat
            # om de week één stuk per winkel verkoopt, staat dan de halve
            # maand onterecht op nul. De rotatie is wél te zien.
            advies = "Nog te weinig weken deze maand"
            score = None
        elif score is None:
            advies = "Geen rotatie-target ingesteld"
        elif not maand_volume:
            # Duidelijker dan "Mogelijke delist": het artikel verkocht dit
            # jaar wél, maar deze maand geen enkel stuk.
            advies = "Geen verkoop deze maand"
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
                    "winkels_bron": bron, "maand_volume": maand_volume,
                    "maand_weken": round(maand_weken, 2),
                    "dekking": dekking_mod.per_artikel(alle_gaten, a["rijen"], caps)})
    out.sort(key=lambda x: (x["score"] is None, x["score"] if x["score"] is not None else 0))
    op_target = sum(1 for a in out if a["score"] is not None and a["score"] >= 100)
    onder = sum(1 for a in out if a["score"] is not None and 70 <= a["score"] < 100)
    delist = sum(1 for a in out if a["score"] is not None and a["score"] < 70)
    return {"available": True, "artikelen": out, "labels": labels,
            "resolution": res.as_dict(), "periode_type": caps["periode"],
            "dekking": alle_gaten,
            "maand": {"label": maand_label(maand), "periodes": maand_periodes,
                      "weken": round(len(maand_periodes) * weken_per_periode, 2)},
            "stats": {"op_target": op_target, "onder_target": onder, "delist": delist}}
