"""Conclusie per retailer: bevindingen deterministisch, tekst door Claude.

Dezelfde huisregel als bij de contractanalyse (zie contracts.py): het model
schrijft de zin, de cijfers blijven deterministisch. Concreet werkt dit in
twee lagen:

  1. `bevindingen()` haalt de opvallende feiten uit de vier bestaande analyses
     (dashboard, assortiment, winkelontwikkeling, promoties) en zet ze om in
     gestructureerde items met een ernst. Die laag rekent zelf niets nieuws
     uit — hij selecteert — werkt zonder API-sleutel en is gewoon te testen.
  2. `genereer()` stuurt ALLEEN die bevindingen naar Claude, dat er een
     samenvatting en adviezen omheen schrijft.

Zo kan het model geen cijfer verzinnen zonder dat het opvalt: alles wat het
noemt hoort in de bevindingen te staan, en `controleer_getallen()` toetst dat
na afloop. Wat er niet in staat wordt gemeld in plaats van stil geslikt —
dezelfde keuze als de onaannemelijke-datumrem bij contracten.

De bevindingen gaan mee de database in naast de tekst. Zonder die
momentopname staat er straks een conclusie zonder bewijs: de data verandert
bij elke import, en dan is niet meer na te gaan uit welk cijfer een zin volgde.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re

from . import analytics, signals
from .contracts import STANDAARD_MODEL, haal_api_key

# Zelfde drempel en zelfde reden als _data_versie in main.py: kleine tabellen
# worden IN PLAATS bijgewerkt, dus tellen en MAX(rowid) zien een gewijzigde
# drempel of target niet. Die gaan op inhoud mee.
_KLEIN = 200

# Een conclusie mag zijn eigen vingerafdruk niet beinvloeden: anders is de
# tekst meteen na het opslaan alweer "verouderd" en blijft het scherm zichzelf
# herschrijven — een API-call per keer kijken.
_NIET_IN_VINGERAFDRUK = {"retailer_conclusies"}

ONDERDELEN = ("omzet", "assortiment", "winkels", "promoties")


# ----------------------------------------------------------------- bevindingen

def _bev(uit: list, onderdeel: str, ernst: str, kop: str, tekst: str, **cijfers):
    uit.append({"onderdeel": onderdeel, "ernst": ernst, "kop": kop, "tekst": tekst,
                "cijfers": {k: v for k, v in cijfers.items() if v is not None}})


def _pct(v) -> str:
    return f"{v:+.1f}%".replace(".", ",") if v is not None else "onbekend"


def _eur(v) -> str:
    return f"€ {v:,.0f}".replace(",", ".")


def _omzet_bevindingen(uit: list, d: dict, pwoord: str):
    ytd, kpi = d.get("ytd") or {}, d.get("kpi") or {}
    o = ytd.get("omzet") or {}
    delta, totaal = o.get("delta_pct"), o.get("totaal_delta_pct")
    if delta is not None:
        ernst = "rood" if delta <= -10 else "oranje" if delta < 0 else "info"
        basis = (ytd.get("basis") or {})
        staart = ""
        if not basis.get("volledig"):
            niet = basis.get("niet_vergelijkbaar") or []
            staart = (f" Let op: {', '.join(niet)} telt niet mee in dit percentage "
                      "(geen vergelijkbare periodes vorig jaar).") if niet else \
                     " Let op: niet alle periodes zijn in beide jaren geleverd."
        _bev(uit, "omzet", ernst, f"Omzet YTD {_pct(delta)} tegen vorig jaar",
             f"Op vergelijkbare basis {_pct(delta)}: {_eur(o.get('nu') or 0)} tegen "
             f"{_eur(o.get('vorig') or 0)}.{staart}",
             delta_pct=delta, totaal_delta_pct=totaal,
             omzet_nu=o.get("nu"), omzet_vorig=o.get("vorig"))
    elif o.get("nu"):
        _bev(uit, "omzet", "info", "Geen vergelijking met vorig jaar",
             f"Omzet dit jaar {_eur(o['nu'])}; vorig jaar is niet geladen, dus er is "
             "geen groeicijfer.", omzet_nu=o.get("nu"))

    ko = kpi.get("omzet") or {}
    if ko.get("delta_pct") is not None:
        ernst = "oranje" if ko["delta_pct"] <= -20 else "info"
        _bev(uit, "omzet", ernst,
             f"Laatste {pwoord} {_pct(ko['delta_pct'])} tegen de {pwoord} ervoor",
             f"{_eur(ko.get('waarde') or 0)} in {d.get('laatste_periode')}, "
             f"tegen {ko.get('vorige_periode')}.",
             delta_pct=ko["delta_pct"], omzet=ko.get("waarde"))

    per_merk = [m for m in (ytd.get("per_merk") or [])
                if (m.get("omzet") or {}).get("delta_pct") is not None]
    if len(per_merk) > 1:
        gesorteerd = sorted(per_merk, key=lambda m: m["omzet"]["delta_pct"])
        slechtste, beste = gesorteerd[0], gesorteerd[-1]
        if slechtste["omzet"]["delta_pct"] < 0:
            _bev(uit, "omzet", "oranje" if slechtste["omzet"]["delta_pct"] > -20 else "rood",
                 f"{slechtste['merk']} daalt het hardst",
                 f"{slechtste['merk']} {_pct(slechtste['omzet']['delta_pct'])} YTD "
                 f"({_eur(slechtste['omzet'].get('nu') or 0)} tegen "
                 f"{_eur(slechtste['omzet'].get('vorig') or 0)}).",
                 merk=slechtste["merk"], delta_pct=slechtste["omzet"]["delta_pct"])
        if beste["omzet"]["delta_pct"] > 0 and beste is not slechtste:
            _bev(uit, "omzet", "info", f"{beste['merk']} groeit het hardst",
                 f"{beste['merk']} {_pct(beste['omzet']['delta_pct'])} YTD "
                 f"({_eur(beste['omzet'].get('nu') or 0)} tegen "
                 f"{_eur(beste['omzet'].get('vorig') or 0)}).",
                 merk=beste["merk"], delta_pct=beste["omzet"]["delta_pct"])

    if d.get("laatste_periode_compleet") is False:
        _bev(uit, "omzet", "info", f"De laatste {pwoord} loopt nog",
             f"{pwoord.capitalize()} {d.get('laatste_periode')} is nog niet af; dat cijfer "
             "is een tussenstand en hoort niet als daling gelezen te worden.")

    for f in (d.get("trend") or {}).get("feeds_achter") or []:
        _bev(uit, "omzet", "oranje", f"Feed van {f.get('merk')} loopt achter",
             f"{f.get('merk')} is geleverd t/m {f.get('laatste_periode')}, terwijl de rest "
             f"verder is. Een achterlopende feed leest als omzetdaling.",
             merk=f.get("merk"))

    for g in (d.get("dekkingsgaten") or [])[:4]:
        _bev(uit, "omzet", "oranje", "Gat in de aanlevering", g.get("tekst") or "",
             merk=g.get("merk"))


def _assortiment_bevindingen(uit: list, a: dict, art: dict):
    if a.get("available"):
        stats = a.get("stats") or {}
        n = len(a.get("artikelen") or []) or 1
        delist, onder = stats.get("delist") or 0, stats.get("onder_target") or 0
        if delist:
            _bev(uit, "assortiment", "rood" if delist / n >= 0.25 else "oranje",
                 f"{delist} mogelijke delist-kandidaten",
                 f"{delist} van de {n} artikelen haalt minder dan 70% van het "
                 f"rotatietarget.", aantal=delist, van=n)
        if onder:
            _bev(uit, "assortiment", "oranje", f"{onder} artikelen onder target",
                 f"{onder} van de {n} artikelen zit onder het rotatietarget maar boven "
                 f"de delist-grens.", aantal=onder, van=n)
        if not delist and not onder:
            _bev(uit, "assortiment", "info", "Assortiment op target",
                 f"Alle {n} artikelen halen hun rotatietarget.", van=n)
        for r in (a.get("artikelen") or [])[:3]:
            if (r.get("score") or 0) and r.get("score") < 70:
                _bev(uit, "assortiment", "info", f"Zwakste loper: {r.get('naam')}",
                     f"{r.get('naam')} ({r.get('merk')}): {r.get('advies')}, rotatie "
                     f"{r.get('rotatie')} tegen target {r.get('target')}.",
                     score=r.get("score"), rotatie=r.get("rotatie"), target=r.get("target"))

    if art.get("available"):
        tel: dict = {}
        for r in art.get("artikelen") or []:
            if r.get("status"):
                tel[r["status"]] = tel.get(r["status"], 0) + 1
        for status, ernst, kop in (("delisted", "rood", "uit het schap"),
                                   ("delisted?", "oranje", "mogelijk uit het schap"),
                                   ("nieuw", "info", "nieuw in het schap")):
            if tel.get(status):
                _bev(uit, "assortiment", ernst, f"{tel[status]} artikelen {kop}",
                     f"{tel[status]} artikelen hebben de status '{status}' in de "
                     f"artikelanalyse.", aantal=tel[status])


# Onder deze daling over twee maanden wordt een artikel gemeld. Distributie
# schommelt van week tot week (een winkel die net niets verkocht telt niet
# mee), dus een paar procent zegt niets; 15% over twee maanden is een echte
# terugloop in het aantal verkopende winkels.
DISTRIBUTIE_DREMPEL = 15.0

# En alleen artikelen die er iets toe doen: van 2 naar 0,7 winkels is -65%,
# maar het is geen distributieverhaal. Onder dit aantal winkels in de
# vergelijkingsperiode blijft een artikel buiten de melding.
DISTRIBUTIE_MINIMUM = 5


def _winkels(v) -> str:
    """Een winkelaantal is een gemiddelde over periodes en dus zelden rond.

    De decimaal blijft staan zodra het getal niet rond is: het percentage in
    dezelfde zin moet met deze twee getallen na te rekenen zijn, en "0
    winkels" naast "-66,7%" leest bovendien als een fout.
    """
    if v is None:
        return "onbekend"
    return f"{round(v, 1):g}".replace(".", ",")


def _distributie_bevindingen(uit: list, art: dict):
    """Distributie: het aantal winkels dat een artikel daadwerkelijk verkocht.

    Alleen voor retailers die winkelniveau leveren. Twee vragen: loopt de
    distributie over het jaar op of terug, en welke artikelen verliezen nu
    winkels? Dat tweede is het actiepunt — een artikel dat uit schappen
    verdwijnt ziet er in de omzet pas maanden later uit als een probleem.
    """
    if not art.get("available") or not art.get("distributie_beschikbaar"):
        return
    rijen = [r for r in (art.get("artikelen") or []) if r.get("distributie")]
    if not rijen:
        return

    # Portefeuillebreed: het gemiddelde over de artikelen die BEIDE jaren
    # hebben. Artikelen zonder vorig jaar zouden het gemiddelde anders naar
    # beneden trekken zonder dat er iets verloren is.
    beide = [r["distributie"]["ytd"] for r in rijen
             if r["distributie"]["ytd"]["nu"] is not None
             and r["distributie"]["ytd"]["vorig"]]
    if beide:
        nu = sum(y["nu"] for y in beide) / len(beide)
        vorig = sum(y["vorig"] for y in beide) / len(beide)
        pct = (nu - vorig) / vorig * 100
        _bev(uit, "assortiment", "rood" if pct <= -10 else "oranje" if pct < 0 else "info",
             f"Distributie {_pct(pct)} tegen vorig jaar",
             f"Gemiddeld verkocht een artikel dit jaar in {_winkels(nu)} winkels per "
             f"periode, tegen {_winkels(vorig)} vorig jaar — gemeten over {len(beide)} "
             f"artikelen die beide jaren geleverd zijn.",
             nu=round(nu, 1), vorig=round(vorig, 1), delta_pct=round(pct, 1),
             artikelen=len(beide))

    dalers = sorted(
        (r for r in rijen
         if (r["distributie"]["twee_maanden"]["delta_pct"] or 0) <= -DISTRIBUTIE_DREMPEL
         and (r["distributie"]["twee_maanden"]["vorig"] or 0) >= DISTRIBUTIE_MINIMUM),
        key=lambda r: r["distributie"]["twee_maanden"]["delta_pct"])
    if dalers:
        n = len(rijen)
        tm = dalers[0]["distributie"]["twee_maanden"]
        _bev(uit, "assortiment", "rood" if len(dalers) / n >= 0.25 else "oranje",
             f"{len(dalers)} artikelen verliezen winkels",
             f"{len(dalers)} van de {n} artikelen verkocht in {tm['label']} in minstens "
             f"{DISTRIBUTIE_DREMPEL:.0f}% minder winkels dan in {tm['vorig_label']}.",
             aantal=len(dalers), van=n)
        for r in dalers[:3]:
            t = r["distributie"]["twee_maanden"]
            _bev(uit, "assortiment", "info", f"Distributieverlies: {r.get('naam')}",
                 f"{r.get('naam')} ({r.get('merk')}) verkocht in {t['label']} gemiddeld in "
                 f"{_winkels(t['nu'])} winkels, tegen {_winkels(t['vorig'])} in "
                 f"{t['vorig_label']} ({_pct(t['delta_pct'])}).",
                 nu=t["nu"], vorig=t["vorig"], delta_pct=t["delta_pct"])


def _winkel_bevindingen(uit: list, d: dict, pwoord: str):
    w = d.get("winkelanalyse") or {}
    if w.get("beschikbaar"):
        gestopt = len(w.get("gestopt") or [])
        letop = len(w.get("signalen") or [])
        erbij = len(w.get("toegevoegd") or [])
        gemist = w.get("gemiste_omzet") or 0
        if gestopt:
            _bev(uit, "winkels", "rood" if gestopt >= 5 else "oranje",
                 f"{gestopt} winkels stilgevallen",
                 f"{gestopt} winkel/merk-combinaties verkopen niets meer, goed voor "
                 f"{_eur(gemist)} gemiste omzet. {w.get('actiepunt') or ''}".strip(),
                 aantal=gestopt, gemist=gemist)
        if letop:
            _bev(uit, "winkels", "oranje", f"{letop} winkels op 'let op'",
                 f"{letop} winkel/merk-combinaties zijn langer stil dan hun eigen ritme, "
                 "maar nog niet lang genoeg om gestopt te heten.", aantal=letop)
        if erbij:
            _bev(uit, "winkels", "info", f"{erbij} winkels erbij",
                 f"{erbij} winkel/merk-combinaties verkopen dit jaar voor het eerst.",
                 aantal=erbij)
        if not gestopt and not letop:
            _bev(uit, "winkels", "info", "Geen winkels stilgevallen",
                 "Elke winkel die eerder verkocht, verkoopt nog steeds.")

    kw = (d.get("kpi") or {}).get("omzet_per_winkel") or {}
    if kw.get("waarde") is not None:
        bron = " (winkelaantal handmatig ingesteld, geen telling uit de data)" \
            if kw.get("schatting") else ""
        _bev(uit, "winkels", "info", "Omzet per winkel",
             f"{_eur(kw['waarde'])} per winkel in de laatste {pwoord}, over "
             f"{kw.get('winkels')} winkels{bron}.",
             omzet_per_winkel=kw.get("waarde"), winkels=kw.get("winkels"))

    dec = ((d.get("tijdlijn") or {}).get("decompositie") or {}).get("totaal")
    verg = (d.get("tijdlijn") or {}).get("vergelijking") or {}
    if dec and verg.get("vorig"):
        # De enige plek in de app die "meer winkels of betere winkels" exact
        # splitst: omzet = winkels x omzet per winkel.
        winkels_pct, per_winkel_pct = dec.get("winkels_pct"), dec.get("per_winkel_pct")
        oorzaak = ("minder winkels" if (winkels_pct or 0) < (per_winkel_pct or 0)
                   else "minder omzet per winkel")
        _bev(uit, "winkels", "info", "Waar het verschil vandaan komt",
             f"{verg.get('nu')} tegen {verg.get('vorig')}: omzet {_pct(dec.get('omzet_pct'))} "
             f"= winkels {_pct(winkels_pct)} × omzet per winkel {_pct(per_winkel_pct)} "
             f"({dec.get('winkels_toen')} → {dec.get('winkels_nu')} winkels). "
             f"Het zwaarst weegt: {oorzaak}.",
             omzet_pct=dec.get("omzet_pct"), winkels_pct=winkels_pct,
             per_winkel_pct=per_winkel_pct, winkels_toen=dec.get("winkels_toen"),
             winkels_nu=dec.get("winkels_nu"))


def _promotie_bevindingen(uit: list, p: dict, pwoord: str):
    if not p.get("available"):
        return
    if p.get("methode") != "prijsindex":
        _bev(uit, "promoties", "info", "Acties niet automatisch te herkennen",
             "Deze retailer levert geen volume of geen artikelniveau, dus de app kan "
             "prijsdalingen niet meten. Acties moeten handmatig aangevinkt worden.")
        return

    suggesties = p.get("suggesties") or []
    zeker = [s for s in suggesties if (s.get("zekerheid") or 0) >= 4 and not s.get("bevestigd")]
    if zeker:
        weken = ", ".join(str(s.get("periode")) for s in zeker[:5])
        _bev(uit, "promoties", "oranje",
             f"{len(zeker)} waarschijnlijke acties nog niet bevestigd",
             f"{len(zeker)} periodes zien er sterk uit als een actie (zekerheid 4/5 of "
             f"hoger) maar zijn niet aangevinkt: {weken}. Zolang ze niet bevestigd zijn, "
             "tellen ze mee als gewone omzet in de vergelijkingen.",
             aantal=len(zeker))

    uplift = p.get("uplift") or []
    if uplift:
        gesorteerd = sorted(uplift, key=lambda u: u.get("uplift_pct") or 0)
        beste, slechtste = gesorteerd[-1], gesorteerd[0]
        _bev(uit, "promoties", "info", f"{len(uplift)} bevestigde acties gemeten",
             f"Beste: {beste.get('merk')} in {beste.get('periode')} "
             f"{_pct(beste.get('uplift_pct'))} tegen de basislijn "
             f"({_eur(beste.get('omzet') or 0)} tegen {_eur(beste.get('basislijn') or 0)}).",
             aantal=len(uplift), beste_uplift_pct=beste.get("uplift_pct"),
             beste_merk=beste.get("merk"))
        if (slechtste.get("uplift_pct") or 0) < 0 and slechtste is not beste:
            _bev(uit, "promoties", "oranje", "Een actie leverde minder op dan een normale week",
                 f"{slechtste.get('merk')} in {slechtste.get('periode')}: "
                 f"{_pct(slechtste.get('uplift_pct'))} tegen de basislijn.",
                 uplift_pct=slechtste.get("uplift_pct"), merk=slechtste.get("merk"))

    for b in (p.get("basis_per_merk") or [])[:4]:
        if b.get("gemiddelde"):
            _bev(uit, "promoties", "info", f"Normale {pwoord}omzet {b.get('merk')}",
                 f"{b.get('merk')} draait {_eur(b['gemiddelde'])} per {pwoord} buiten "
                 f"acties om ({b.get('periodes')} periodes, {b.get('jaar')}).",
                 gemiddelde=b.get("gemiddelde"), merk=b.get("merk"))

    onvolledig = p.get("onvolledige_periodes") or []
    if onvolledig:
        _bev(uit, "promoties", "oranje", "Actiedetectie mist data",
             f"{len(onvolledig)} periodes zijn niet volledig geleverd; daar is niet te "
             "zien of er een actie liep.", aantal=len(onvolledig))


def bevindingen(conn, retailer_id: str) -> dict:
    """Wat er over deze retailer te zeggen valt, uit de vier analyses.

    Puur selectie en formulering — geen nieuwe berekening, geen API-sleutel
    nodig. Bewust NIET uit de zware reeksen (sparkline, tijdlijn.per_merk,
    trend.series, gestopt[].reeks): daar zit het leeuwendeel van de bytes en
    niets wat een conclusie nodig heeft.
    """
    d = analytics.dashboard(conn, retailer_id)
    if not d.get("available"):
        return {"beschikbaar": False, "reden": d.get("reason") or "GEEN PROFIEL",
                "context": {}, "bevindingen": []}
    if d.get("empty"):
        return {"beschikbaar": False, "reden": "NOG GEEN DATA",
                "context": {}, "bevindingen": []}

    pwoord = "maand" if d.get("periode_type") == "maand" else "week"
    uit: list = []
    _omzet_bevindingen(uit, d, pwoord)
    art = analytics.articles(conn, retailer_id)
    _assortiment_bevindingen(uit, analytics.assortment(conn, retailer_id), art)
    _distributie_bevindingen(uit, art)
    _winkel_bevindingen(uit, d, pwoord)
    _promotie_bevindingen(uit, analytics.promotions(conn, retailer_id), pwoord)

    naam = conn.execute("SELECT naam FROM retailers WHERE id=?", (retailer_id,)).fetchone()
    return {
        "beschikbaar": True,
        "reden": None,
        "context": {
            "retailer": (naam["naam"] if naam else retailer_id),
            "periode_type": pwoord,
            "laatste_periode": d.get("laatste_periode"),
            "jaar": (d.get("ytd") or {}).get("jaar"),
            # De vier bestaande signalen, niet opnieuw afgeleid maar overgenomen.
            "signalen": signals.retailer_signals(conn, retailer_id),
        },
        "bevindingen": uit,
    }


# --------------------------------------------------------------- vingerafdruk

def _retailer_tabellen(conn) -> list[str]:
    """Tabellen met een retailer_id, uit de database gelezen.

    Zelfde reden als bij _data_versie in main.py: een handmatige lijst mist
    vroeg of laat een tabel, en dan blijft een conclusie stil actueel heten
    terwijl de cijfers eronder veranderd zijn.
    """
    namen = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    uit = []
    for naam in namen:
        if naam in _NIET_IN_VINGERAFDRUK:
            continue
        kolommen = {r[1] for r in conn.execute(f"PRAGMA table_info({naam})")}
        if "retailer_id" in kolommen:
            uit.append(naam)
    return uit


def vingerafdruk(conn, retailer_id: str) -> str:
    """De staat van de data van DEZE retailer, zonder datum erin.

    Bewust niet de analysecache-versie uit main.py: die bevat de datum van
    vandaag, en dan zou elke nacht elke conclusie herschreven worden — een
    API-call per retailer per dag zonder dat er iets veranderd is. En bewust
    per retailer: een import voor Kruidvat hoort de conclusie van Etos niet
    te verouderen.
    """
    delen: list = []
    for tabel in _retailer_tabellen(conn):
        aantal, hoogste = conn.execute(
            f"SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM {tabel} WHERE retailer_id=?",
            (retailer_id,)).fetchone()
        delen.append((tabel, aantal, hoogste))
        if aantal and aantal <= _KLEIN:
            rijen = conn.execute(f"SELECT * FROM {tabel} WHERE retailer_id=?",
                                 (retailer_id,)).fetchall()
            delen.append((tabel, tuple(tuple(r) for r in rijen)))
    return hashlib.sha256(repr(delen).encode()).hexdigest()[:16]


# ------------------------------------------------------------- getallencontrole

# Een getal met optioneel een euroteken ervoor of een procentteken erachter.
# Die twee tekens maken het verschil tussen "de 3 merken" (mag) en "3%" of
# "€ 3" (een bewering over een cijfer, die moet kloppen).
_GETAL_RE = re.compile(r"(€\s*)?(-?\d[\d.,]*\d|\d)\s*(%)?")


def _sleutels(waarde) -> set[str]:
    """Cijferreeksen waarmee een getal geschreven kan zijn.

    '€ 266.758' en '266758' horen te matchen, en -20,6 mag als '-21%'
    afgerond terugkomen — een tekst die netjes afrondt is geen verzinsel.
    """
    try:
        getal = float(waarde)
    except (TypeError, ValueError):
        return set()
    uit = set()
    for kandidaat in (getal, round(getal, 1), round(getal, 2), float(round(getal))):
        tekst = f"{abs(kandidaat):.2f}".rstrip("0").rstrip(".")
        uit.add(tekst.replace(".", ""))
    return uit


def _toegestaan(bev: dict) -> set[str]:
    toegestaan: set[str] = set()
    for item in bev.get("bevindingen") or []:
        for waarde in (item.get("cijfers") or {}).values():
            toegestaan |= _sleutels(waarde)
    # Ook alles wat in de teksten en de context zelf staat: periodenummers,
    # jaartallen en de getallen in de meldingen die de analyses al schreven.
    ruw = json.dumps([bev.get("context"), bev.get("bevindingen")], ensure_ascii=False)
    for _euro, getal, _pct_teken in _GETAL_RE.findall(ruw):
        toegestaan.add(re.sub(r"[^\d]", "", getal))
        toegestaan |= _sleutels(getal.replace(".", "").replace(",", "."))
    toegestaan.discard("")
    return toegestaan


def controleer_getallen(tekst: str, bev: dict) -> list[str]:
    """Getallen in de gegenereerde tekst die niet in de bevindingen staan.

    Melden, niet verbergen: hetzelfde als bij een onaannemelijke contractdatum.
    Korte getallen zonder euro- of procentteken ("de 3 merken", "4 weken")
    blijven buiten schot — die vlaggen zou de waarschuwing waardeloos maken.
    """
    toegestaan = _toegestaan(bev)
    onbekend: list[str] = []
    for euro, getal, procent in _GETAL_RE.findall(tekst or ""):
        cijfers = re.sub(r"[^\d]", "", getal)
        if not cijfers:
            continue
        beweert_iets = bool(euro or procent) or len(cijfers) > 2
        if not beweert_iets:
            continue
        varianten = {cijfers} | _sleutels(getal.replace(".", "").replace(",", "."))
        if varianten & toegestaan:
            continue
        geschreven = f"{'€ ' if euro else ''}{getal}{'%' if procent else ''}"
        if geschreven not in onbekend:
            onbekend.append(geschreven)
    return onbekend


# -------------------------------------------------------------------- genereren

_PROMPT = """Je bent analist voor een merkleverancier die zijn producten via \
drogisterij- en parfumerieketens verkoopt. Hieronder staan de BEVINDINGEN die \
de app zelf uit de verkoopdata van één retailer heeft berekend. Schrijf daar \
een conclusie en concrete adviezen bij.

Geef UITSLUITEND geldig JSON terug (geen uitleg, geen markdown-hekjes) met \
exact deze vorm:

{{
  "samenvatting": "3 tot 6 zinnen: hoe staat deze retailer ervoor en wat valt op",
  "advies": [
    {{"actie": "één concrete actie", "waarom": "op welke bevinding dit rust"}}
  ]
}}

Regels:
- Gebruik UITSLUITEND getallen die letterlijk in de bevindingen staan. Reken \
niets zelf uit en verzin niets; noem liever geen getal dan een geschat getal.
- Schrijf niets over onderdelen waarover geen bevindingen staan.
- Neem de kanttekeningen over data serieus. Staat er dat een periode nog loopt, \
dat een feed achterloopt of dat data ontbreekt, noem dat dan bij het cijfer in \
plaats van de daling als vaststaand feit te presenteren.
- Hoogstens 4 adviezen, belangrijkste eerst. Elk advies moet iets zijn wat een \
accountmanager kan doen (een gesprek met de category manager, herbevoorrading, \
een actie bevestigen, een prijsafspraak) — geen algemeenheden.
- Nederlands, zakelijk, kort. Geen aanhef en geen afsluiting.

Retailer: {retailer}
Periode-eenheid: {periode}
Meest recente periode: {laatste}

Bevindingen:
{bevindingen}"""


def _model() -> str:
    return os.environ.get("CONSOLE_CONCLUSIE_MODEL", "").strip() or STANDAARD_MODEL


def _schrijf(conn, retailer_id: str, bev: dict, api_key: str) -> dict:
    import anthropic

    context = bev.get("context") or {}
    kaal = [{k: v for k, v in item.items() if k != "cijfers"}
            | {"cijfers": item.get("cijfers") or {}}
            for item in bev.get("bevindingen") or []]
    prompt = _PROMPT.format(
        retailer=context.get("retailer") or retailer_id,
        periode=context.get("periode_type") or "week",
        laatste=context.get("laatste_periode") or "onbekend",
        bevindingen=json.dumps(kaal, ensure_ascii=False, indent=1))
    try:
        antwoord = anthropic.Anthropic(api_key=api_key).messages.create(
            model=_model(), max_tokens=1500,
            messages=[{"role": "user", "content": prompt}])
    except anthropic.APIError as e:
        raise ValueError(f"conclusie schrijven is mislukt: {e}") from e

    ruw = "".join(b.text for b in antwoord.content if b.type == "text").strip()
    ruw = ruw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(ruw)
    except json.JSONDecodeError as e:
        raise ValueError("de conclusie leverde geen bruikbaar antwoord op") from e

    samenvatting = str(data.get("samenvatting") or "").strip()
    if not samenvatting:
        raise ValueError("de conclusie leverde geen samenvatting op")
    advies = []
    for regel in (data.get("advies") or [])[:4]:
        if not isinstance(regel, dict):
            continue
        actie = str(regel.get("actie") or "").strip()
        if actie:
            advies.append({"actie": actie[:400],
                           "waarom": str(regel.get("waarom") or "").strip()[:400]})
    return {"samenvatting": samenvatting[:4000], "advies": advies}


def genereer(conn, retailer_id: str, door: str | None = None) -> dict:
    """Bevindingen ophalen, Claude laten schrijven, controleren en opslaan."""
    bev = bevindingen(conn, retailer_id)
    if not bev.get("beschikbaar"):
        raise ValueError("er is nog niets te concluderen voor deze retailer "
                         f"({(bev.get('reden') or 'geen data').lower()})")
    api_key, _bron = haal_api_key(conn)
    if not api_key:
        raise ValueError("de conclusie is niet geconfigureerd (geen Anthropic API-sleutel)")

    geschreven = _schrijf(conn, retailer_id, bev, api_key)
    onbekend = controleer_getallen(
        geschreven["samenvatting"] + " " +
        " ".join(f"{a['actie']} {a['waarom']}" for a in geschreven["advies"]), bev)
    waarschuwingen = ([f"Deze conclusie noemt getallen die niet in de bevindingen "
                       f"staan: {', '.join(onbekend)}. Controleer die zelf."]
                      if onbekend else [])

    nu = dt.datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM retailer_conclusies WHERE retailer_id=?", (retailer_id,))
    conn.execute(
        "INSERT INTO retailer_conclusies (retailer_id, samenvatting, advies, bevindingen, "
        "vingerafdruk, model, waarschuwingen, gegenereerd_op, gegenereerd_door) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (retailer_id, geschreven["samenvatting"],
         json.dumps(geschreven["advies"], ensure_ascii=False),
         json.dumps(bev, ensure_ascii=False), vingerafdruk(conn, retailer_id),
         _model(), json.dumps(waarschuwingen, ensure_ascii=False), nu, door))
    return lees(conn, retailer_id, bev)


def lees(conn, retailer_id: str, bev: dict | None = None) -> dict:
    """De opgeslagen conclusie plus verse bevindingen. Kost geen API-call."""
    bev = bev if bev is not None else bevindingen(conn, retailer_id)
    rij = conn.execute("SELECT * FROM retailer_conclusies WHERE retailer_id=?",
                       (retailer_id,)).fetchone()
    huidig = vingerafdruk(conn, retailer_id) if bev.get("beschikbaar") else None
    conclusie = None
    if rij:
        conclusie = {
            "samenvatting": rij["samenvatting"],
            "advies": json.loads(rij["advies"] or "[]"),
            "waarschuwingen": json.loads(rij["waarschuwingen"] or "[]"),
            "model": rij["model"],
            "gegenereerd_op": rij["gegenereerd_op"],
            "gegenereerd_door": rij["gegenereerd_door"],
        }
    return {
        "beschikbaar": bev.get("beschikbaar", False),
        "reden": bev.get("reden"),
        "context": bev.get("context") or {},
        "bevindingen": bev.get("bevindingen") or [],
        "conclusie": conclusie,
        # Verouderd zodra de data van deze retailer veranderd is sinds het
        # schrijven. Zonder opgeslagen tekst is er niets om te verouderen.
        "verouderd": bool(rij) and rij["vingerafdruk"] != huidig,
        "sleutel_ingesteld": bool(haal_api_key(conn)[0]),
    }
