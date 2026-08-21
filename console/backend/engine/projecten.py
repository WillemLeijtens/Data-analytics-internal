"""Rekenmodel van de projectcalculator.

Een project rekent een listing of actie vooraf door en levert TWEE
uitkomsten, omdat ze twee verschillende beslissingen voeden:

  * EENMALIG — de eerste vulling: elk deelnemend filiaal krijgt een
    startvoorraad (aantal_winkels x stuks_per_winkel). Dit is de sell-in
    die één keer gefactureerd wordt.
  * TERUGKEREND — de doorverkoop daarna: rotatie per winkel per week x
    aantal winkels, per week en opgeteld over de looptijd van het project.

Kosten hebben een schakel `terugkerend`: eenmalige kosten (listing fee, een
display) drukken op de eenmalige marge, looptijdkosten (marketingbudget,
co-op, logistiek) op de terugkerende. Verpakking loopt uitsluitend via de
kostenregel "Verpakkingskosten (totaal)" — geen apart veld per product: dat
gaf op regelniveau een marge die zonder duidelijke reden op nul uitkwam
zodra kostprijs plus verpakking de verkoopprijs opaten.

De "Bijdrage leverancier" is de omgekeerde regel: geld dat de fabrikant
bijlegt aan de actie. Hij staat tussen de kostenregels (zelfde schakel
eenmalig/looptijd) maar telt OP bij de nettomarge in plaats van eraf —
en telt bewust niet als omzet: het is een tegemoetkoming in de kosten.

Alles is None-tolerant: een half ingevuld project rekent met 0 voor wat er
nog niet staat, in plaats van te crashen of het scherm te blokkeren.
"""

from __future__ import annotations

import datetime as dt

# De vaste kostenregels waarmee elk nieuw project start. De gebruiker kan
# bedragen leeg laten, de schakel omzetten en vrije regels toevoegen.
STANDAARD_KOSTEN = [
    ("listing_fee", "Listing fee", 0),
    ("coop", "Co-op bijdrage", 1),
    ("marketing", "Marketingbudget", 1),
    ("display", "Displaykosten", 0),
    ("logistiek", "Logistieke kosten", 1),
    ("verpakking", "Verpakkingskosten (totaal)", 0),
    ("bijdrage_leverancier", "Bijdrage leverancier", 0),
]

KOSTEN_SOORTEN = {s for s, _, _ in STANDAARD_KOSTEN} | {"overig"}
BIJDRAGE = "bijdrage_leverancier"


def _n(v) -> float:
    """Leeg veld telt als nul; de calculator mag nooit crashen op een
    half ingevuld project."""
    return float(v) if v is not None else 0.0


def looptijd_weken(start: str | None, eind: str | None) -> float | None:
    """Weken tussen start- en einddatum, einddag inbegrepen, op één decimaal.

    Fractioneel, niet afgerond op hele weken: round(dagen/7) maakte van elf
    dagen één week en van 74 dagen elf weken — tot een halve week
    doorverkoop (±5% op een actie van tien weken) verdween of kwam erbij.
    84 dagen (start t/m einde) is exact 12,0 weken."""
    if not start or not eind:
        return None
    dagen = (dt.date.fromisoformat(eind) - dt.date.fromisoformat(start)).days + 1
    if dagen <= 0:
        return None
    return round(dagen / 7, 1)


def _product(p: dict) -> dict:
    winkels = _n(p.get("aantal_winkels"))
    kostprijs, verkoopprijs = p.get("kostprijs"), p.get("verkoopprijs")
    marge_per_stuk = _n(verkoopprijs) - _n(kostprijs)
    stuks_eenmalig = winkels * _n(p.get("stuks_per_winkel"))
    stuks_week = winkels * _n(p.get("rotatie_per_winkel_per_week"))
    return {
        **p,
        # Eén van de twee leeg (de ander wél ingevuld) rekent stilzwijgend
        # met 0 voor het ontbrekende veld — dat KAN de marge onterecht laten
        # lijken alsof kostprijs of verkoopprijs nul is. De rekenwijze blijft
        # bewust None-tolerant (zie moduledocstring), maar dit signaal laat
        # het scherm een waarschuwing tonen i.p.v. de marge stil te vertrouwen.
        "prijs_onvolledig": (kostprijs is None) != (verkoopprijs is None),
        "marge_per_stuk": round(marge_per_stuk, 4),
        # De brutomarge van het product zelf: hetzelfde percentage voor de
        # eenmalige vulling als voor de wekelijkse doorverkoop, want het is
        # per stuk. De projectkosten zitten er nog NIET in — die drukken op
        # de projectmarge verderop.
        "marge_pct": _pct(marge_per_stuk, _n(verkoopprijs)),
        "eenmalig_stuks": round(stuks_eenmalig, 2),
        "eenmalig_omzet": round(stuks_eenmalig * _n(verkoopprijs), 2),
        "eenmalig_marge": round(stuks_eenmalig * marge_per_stuk, 2),
        "week_stuks": round(stuks_week, 2),
        "week_omzet": round(stuks_week * _n(verkoopprijs), 2),
        "week_marge": round(stuks_week * marge_per_stuk, 2),
    }


def _pct(marge: float, omzet: float) -> float | None:
    return round(marge / omzet * 100, 1) if omzet else None


def _voldoet(pct: float | None, drempel: float | None) -> bool | None:
    """None als er niets te meten valt: geen drempel ingesteld, of nog geen
    marge om tegen te houden. Geen drempel is geen goedkeuring."""
    if drempel is None or pct is None:
        return None
    return pct >= drempel


def bereken(project: dict, producten: list[dict], kosten: list[dict],
            drempels: dict | None = None) -> dict:
    """De volledige doorrekening. Puur: geen database, geen klok.

    `drempels` is {"eenmalig": pct|None, "terugkerend": pct|None} — de
    bedrijfsnorm uit de instellingen. Zonder drempel wordt er niets gemeten
    en niets gemeld."""
    drempels = drempels or {}
    d_een = drempels.get("eenmalig")
    d_terug = drempels.get("terugkerend")
    # Een one-shot is één levering: er ís geen doorverkoop per week. De
    # ingevulde rotatie blijft in de database staan (omzetten naar doorlopend
    # brengt hem terug), maar telt nergens in mee — en de drempel voor
    # terugkerende omzet geldt hier niet, want er is geen terugkerende omzet.
    eenmalig_project = project.get("soort") == "eenmalig"
    if eenmalig_project:
        d_terug = None
    regels = [_product(p) for p in producten]
    for r in regels:
        if eenmalig_project:
            r["week_stuks"] = r["week_omzet"] = r["week_marge"] = 0.0

    # Haalt een product de drempel op zijn BRUTOmarge al niet, dan haalt het
    # project hem zeker niet: de kosten komen er nog af. Dat is precies het
    # moment om het te zeggen — bij het invullen, niet pas bij het totaal.
    for r in regels:
        onder = []
        if r["marge_pct"] is not None:
            if d_een is not None and r["marge_pct"] < d_een:
                onder.append({"soort": "eenmalig", "drempel_pct": d_een})
            if d_terug is not None and r["marge_pct"] < d_terug:
                onder.append({"soort": "terugkerend", "drempel_pct": d_terug})
        r["onder_drempel"] = onder
    weken = looptijd_weken(project.get("start_datum"), project.get("eind_datum"))

    def kosten_en_bijdrage(terugkerend: bool) -> tuple[float, float]:
        uit = bij = 0.0
        for k in kosten:
            # Bij een one-shot is er geen looptijdmarge om op te drukken. Alles
            # op de eenmalige marge zetten is de enige plek waar het nog eerlijk
            # meetelt; ze stil laten vallen zou het project winstgevender laten
            # lijken dan het is.
            regel_terugkerend = bool(k.get("terugkerend")) and not eenmalig_project
            if regel_terugkerend != terugkerend:
                continue
            if k.get("soort") == BIJDRAGE:
                bij += _n(k.get("bedrag"))
            else:
                uit += _n(k.get("bedrag"))
        return uit, bij

    kosten_eenmalig, bijdrage_eenmalig = kosten_en_bijdrage(False)
    kosten_looptijd, bijdrage_looptijd = kosten_en_bijdrage(True)

    een_omzet = sum(r["eenmalig_omzet"] for r in regels)
    een_productmarge = sum(r["eenmalig_marge"] for r in regels)
    week_omzet = sum(r["week_omzet"] for r in regels)
    week_marge = sum(r["week_marge"] for r in regels)

    # Zonder looptijd is er wél een weekbeeld maar geen looptijdtotaal; de
    # looptijdkosten kunnen dan nergens tegen afgezet worden en de
    # terugkerende marge blijft None in plaats van een schijngetal.
    terug_omzet = round(week_omzet * weken, 2) if weken and not eenmalig_project else None
    terug_productmarge = round(week_marge * weken, 2) \
        if weken and not eenmalig_project else None
    terug_marge = round(terug_productmarge - kosten_looptijd + bijdrage_looptijd, 2) \
        if terug_productmarge is not None else None

    een_marge = round(een_productmarge - kosten_eenmalig + bijdrage_eenmalig, 2)
    totaal_omzet = round(een_omzet + (terug_omzet or 0), 2)
    totaal_marge = round(een_marge + (terug_marge or 0), 2) \
        if terug_marge is not None else een_marge

    # Looptijd(kosten én bijdragen) zonder looptijd kunnen nergens op
    # drukken. Ze stil uit elk totaal laten vallen zou het project completer
    # laten lijken dan het is — het scherm meldt het nettobedrag expliciet
    # bij het Totaal.
    kosten_buiten_beeld = round(kosten_looptijd - bijdrage_looptijd, 2) \
        if (kosten_looptijd or bijdrage_looptijd) and not weken else 0.0

    waarschuwingen = [
        f"{r.get('naam') or 'Naamloos product'}: kostprijs of verkoopprijs is leeg — "
        "de marge rekent het ontbrekende veld als €0, wat de marge kunstmatig kan "
        "op- of neerwaarts vertekenen."
        for r in regels if r.get("prijs_onvolledig")
    ]

    return {
        "producten": regels,
        "soort": "eenmalig" if eenmalig_project else "doorlopend",
        "looptijd_weken": weken,
        "waarschuwingen": waarschuwingen,
        "eenmalig": {
            "omzet": round(een_omzet, 2),
            "productmarge": round(een_productmarge, 2),
            "kosten": round(kosten_eenmalig, 2),
            "bijdrage": round(bijdrage_eenmalig, 2),
            "marge": een_marge,
            "marge_pct": _pct(een_marge, een_omzet),
            "drempel_pct": d_een,
            "voldoet": _voldoet(_pct(een_marge, een_omzet), d_een),
        },
        "terugkerend": {
            "per_week": {"omzet": round(week_omzet, 2), "marge": round(week_marge, 2)},
            "omzet": terug_omzet,
            "productmarge": terug_productmarge,
            "kosten": round(kosten_looptijd, 2),
            "bijdrage": round(bijdrage_looptijd, 2),
            "marge": terug_marge,
            "marge_pct": _pct(terug_marge, terug_omzet)
            if terug_marge is not None and terug_omzet else None,
            "drempel_pct": d_terug,
            "voldoet": _voldoet(
                _pct(terug_marge, terug_omzet)
                if terug_marge is not None and terug_omzet else None, d_terug),
        },
        "totaal": {
            "omzet": totaal_omzet,
            "marge": totaal_marge,
            "marge_pct": _pct(totaal_marge, totaal_omzet),
            "kosten_buiten_beeld": kosten_buiten_beeld,
        },
    }


STATUSSEN = {"concept", "definitief"}
SOORTEN = {"eenmalig", "doorlopend"}


def valideer(project: dict, producten: list[dict], kosten: list[dict]) -> None:
    """Raise ValueError vóór er iets aan de database verandert."""
    if not str(project.get("naam") or "").strip():
        raise ValueError("projectnaam is verplicht")
    if project.get("status") not in STATUSSEN:
        raise ValueError(f"status moet concept of definitief zijn, niet {project.get('status')!r}")
    if project.get("soort", "doorlopend") not in SOORTEN:
        raise ValueError("soort moet eenmalig of doorlopend zijn, niet "
                         f"{project.get('soort')!r}")
    for veld in ("start_datum", "eind_datum"):
        w = project.get(veld)
        if w:
            try:
                dt.date.fromisoformat(w)
            except ValueError:
                raise ValueError(f"{veld} {w!r} is geen datum (YYYY-MM-DD)")
    s, e = project.get("start_datum"), project.get("eind_datum")
    if s and e and e < s:
        raise ValueError("einddatum ligt vóór de startdatum")
    for p in producten:
        if not str(p.get("naam") or "").strip():
            raise ValueError("elk product heeft een naam nodig")
        for veld in ("kostprijs", "verkoopprijs", "aantal_winkels",
                     "stuks_per_winkel", "rotatie_per_winkel_per_week"):
            w = p.get(veld)
            if w is not None and float(w) < 0:
                raise ValueError(f"{veld} kan niet negatief zijn ({p['naam']})")
    for k in kosten:
        if k.get("soort") not in KOSTEN_SOORTEN:
            raise ValueError(f"onbekende kostensoort {k.get('soort')!r}")
        if not str(k.get("label") or "").strip():
            raise ValueError("elke kostenregel heeft een omschrijving nodig")
        if k.get("bedrag") is not None and float(k["bedrag"]) < 0:
            raise ValueError(f"kostenbedrag kan niet negatief zijn ({k['label']})")


def log_wijziging(conn, project_id: int, door: str, actie: str) -> None:
    """Ververst de meest recente 'gewijzigd'-logregel van dezelfde persoon
    als die nog geen 5 minuten oud is (nieuwe tijd, nieuwe actietekst), anders
    komt er een nieuwe regel bij. Zonder dit zou automatisch opslaan (elke
    wijziging, gedebounced op het scherm) het logboek laten volstromen met
    tientallen regels per minuut terwijl iemand gewoon aan het typen is —
    het logboek moet "wie deed wanneer iets" blijven vertellen, niet "wie
    typte om welke seconde een letter"."""
    ver = conn.execute(
        "UPDATE project_log SET op=datetime('now'), actie=? "
        "WHERE id = (SELECT id FROM project_log WHERE project_id=? AND door=? "
        "AND actie LIKE 'gewijzigd%' AND op >= datetime('now','-5 minutes') "
        "ORDER BY op DESC, id DESC LIMIT 1)",
        (actie, project_id, door))
    if not ver.rowcount:
        conn.execute(
            "INSERT INTO project_log (project_id, door, actie) VALUES (?,?,?)",
            (project_id, door, actie))
