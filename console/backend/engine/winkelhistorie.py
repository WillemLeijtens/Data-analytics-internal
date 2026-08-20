"""Wanneer een gewijzigd winkelaantal een historieregel verdient.

Deze regel stond in de HTTP-laag (main.py, save_settings). Hij is puur
domein: hij bepaalt welke wijzigingen betekenis hebben voor het
distributiesignaal op het Overzicht, en dat heeft niets met verzoeken of
statuscodes te maken.
"""

from __future__ import annotations

import datetime as dt


def nieuwe_metingen(conn, retailer_id: str, winkels_targets: list[dict],
                    vandaag: dt.date | None = None) -> list[tuple]:
    """De historieregels die deze opslag oplevert.

    Alleen winkelaantallen die VERANDEREN worden vastgelegd: alleen zo is
    een dalende distributie later terug te zien. Ongewijzigde waarden voegen
    niets toe.

    Uitzondering: is er voor een scope nog geen enkele historie, dan wordt
    eerst de waarde vastgelegd zoals die nú in de database staat. Zonder die
    nulmeting levert de eerste wijziging maar één punt op en blijft het
    signaal grijs — precies op het moment dat je de daling wilt zien.

    Geeft rijen terug in de vorm (retailer_id, merk, land, banner, aantal,
    geldig_vanaf), klaar voor executemany().
    """
    vorige = {(r["merk"], r["land"], r["banner"]): r["aantal_winkels"]
              for r in conn.execute(
                  "SELECT merk, land, banner, aantal_winkels FROM retailer_settings "
                  "WHERE retailer_id=?", (retailer_id,))}
    met_historie = {(r["merk"], r["land"], r["banner"]) for r in conn.execute(
        "SELECT DISTINCT merk, land, banner FROM winkelaantal_historie "
        "WHERE retailer_id=?", (retailer_id,))}

    datum = (vandaag or dt.date.today()).isoformat()
    rijen: list[tuple] = []
    for s in winkels_targets:
        aantal = s.get("aantal_winkels")
        if not aantal:
            continue
        scope = (s["merk"], s["land"], s.get("banner"))
        oud = vorige.get(scope)
        if scope not in met_historie and oud:
            rijen.append((retailer_id, *scope, oud, datum))
        if oud != aantal:
            rijen.append((retailer_id, *scope, aantal, datum))
    return rijen
