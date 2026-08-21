"""Het winkelaantal van een scope: ingesteld op merkniveau, of afgeleid uit
de artikelen.

Niet elk artikel van een merk ligt in evenveel winkels. Wie de omzet per
winkel van één artikel wil beoordelen, moet door het aantal winkels van dát
artikel delen — niet door het merkgetal.

Voor het MERKgemiddelde geldt een voorbehoud dat hier expliciet gemaakt
wordt, omdat het anders stilzwijgend in elke grafiek zou zitten:

    Het aantal winkels van een merk is de VERENIGING van de winkels per
    artikel. Uit losse aantallen is die vereniging niet te berekenen; je
    kent alleen de grenzen:

        max(artikelen)  <=  merk  <=  min(som(artikelen), totaal filialen)

    Deze module neemt de ondergrens: het grootste artikel. Dat is juist
    zodra het smallere assortiment in dezelfde winkels ligt als het brede —
    de normale situatie, want een filiaal dat de nieuwe kleur voert heeft
    vrijwel altijd ook het basisitem. Liggen artikelen in verschillende
    winkels, dan is het echte aantal hoger, en valt de omzet per winkel op
    merkniveau dus te HOOG uit.

    Optellen zou de andere kant op fout zijn: elke winkel die twee artikelen
    voert telt dan dubbel, en het gemiddelde zakt naar een fractie van de
    werkelijkheid. Van de twee grenzen is de ondergrens de veiligste keuze
    en de enige die klopt in het normale geval.

Retailers die winkelniveau in de feed leveren komen hier niet langs: daar
worden de winkels geteld in plaats van ingesteld (zie analytics.store_count).
"""

from __future__ import annotations

NIVEAUS = {"merk", "artikel"}


def sleutel(merk, land, banner) -> tuple:
    return (merk, land, banner)


def effectief(rij: dict, artikelen: list[dict]) -> int | None:
    """Het winkelaantal waarmee gerekend wordt voor deze merk-land-scope.

    Op merkniveau het ingestelde getal; op artikelniveau het grootste
    artikelaantal (zie de moduledocstring voor waarom het grootste en niet
    de som). Geen enkel artikel ingevuld = geen getal, net als een leeg
    merkveld: dan valt de analyse terug op wat ze zonder instelling doet.
    """
    if rij.get("niveau") != "artikel":
        return rij.get("aantal_winkels")
    aantallen = [a["aantal_winkels"] for a in artikelen
                 if a.get("aantal_winkels") and a["aantal_winkels"] > 0]
    return max(aantallen) if aantallen else None


def per_scope(artikel_rijen: list[dict]) -> dict[tuple, list[dict]]:
    """Artikelinstellingen gegroepeerd op (merk, land, banner)."""
    uit: dict[tuple, list[dict]] = {}
    for a in artikel_rijen:
        uit.setdefault(sleutel(a["merk"], a["land"], a["banner"]), []).append(a)
    return uit


def voor_artikel(settings: list[dict], artikelen: dict[tuple, list[dict]],
                 ean: str) -> list[dict]:
    """De scope-instellingen zoals ze voor dit ÉNE artikel gelden.

    Hier zit de eigenlijke winst van artikelniveau: de rotatie en de omzet
    per winkel van een artikel horen door het aantal winkels van dát artikel
    gedeeld te worden. Een nieuwe kleur in 120 filialen die door het
    merkaantal van 800 gedeeld wordt, ziet eruit als een delist-kandidaat
    terwijl hij in zijn eigen winkels prima loopt.

    Scopes op merkniveau blijven ongemoeid; scopes op artikelniveau waar dit
    artikel geen eigen aantal heeft, vallen terug op het afgeleide merkgetal
    (dat `manual_store_settings` al heeft ingevuld).
    """
    uit = []
    for s in settings:
        rij = dict(s)
        if s.get("niveau") == "artikel":
            eigen = [a for a in artikelen.get(sleutel(s["merk"], s["land"], s["banner"]), [])
                     if a["artikel_ean"] == ean and a.get("aantal_winkels")]
            if eigen:
                rij["aantal_winkels"] = eigen[0]["aantal_winkels"]
        uit.append(rij)
    return uit


def laad(conn, retailer_id: str) -> dict[tuple, list[dict]]:
    """De artikelinstellingen van deze retailer, gegroepeerd op scope."""
    return per_scope([dict(r) for r in conn.execute(
        "SELECT merk, land, banner, artikel_ean, aantal_winkels "
        "FROM artikel_winkelaantallen WHERE retailer_id=?", (retailer_id,))])
