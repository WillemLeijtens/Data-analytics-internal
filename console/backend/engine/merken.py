"""Merknamen gelijktrekken over alle feeds heen.

Elke retailer schrijft een merk op zijn eigen manier. Kruidvat levert
"DEPEND GEL IQ" (de productlijn), ICI levert "DEPEND" (het merk), en in
sommige Kruidvat-bestanden staan ze zelfs door elkaar. Zonder deze laag zijn
dat twee merken in de app: twee filterchips, twee regels in de YTD-tabel, twee
kleuren, en geen enkele vergelijking tussen retailers.

Waarom hier en niet in elke parser apart: dit hoort NOOIT gesplitst in de
database te belanden, ook niet via een profiel-parser die later gebouwd wordt.
`engine/importer.run_import` is de enige plek waar alle feiten binnenkomen, dus
daar wordt genormaliseerd — één poort, geen sluiproutes.

Een alias toevoegen is één regel in ALIASSEN. Bestaat er al data onder de oude
naam, draai dan ook de bijbehorende migratie (zie migrations/005) of laat de
bestanden opnieuw inlezen.
"""

from __future__ import annotations

import re

# Schrijfwijze zoals hij in de app hoort te staan, per variant die in de
# aanleveringen voorkomt. Sleutels zijn genormaliseerd (hoofdletters, enkele
# spaties), dus "Depend Gel IQ" en "DEPEND  GEL  IQ" komen allebei uit.
#
# DEPEND is het merk; GEL IQ is er een productlijn binnen. ICI schrijft het al
# zo, dus deze keuze maakt de twee retailers meteen vergelijkbaar.
ALIASSEN = {
    "DEPEND GEL IQ": "DEPEND",
    "DEPEND GELIQ": "DEPEND",
    "DEPEND GEL-IQ": "DEPEND",
}

_SPATIES = re.compile(r"\s+")


def normaliseer(naam: str | None) -> str | None:
    """De schrijfwijze waaronder dit merk in de app thuishoort.

    Onbekende merken gaan er ongewijzigd doorheen, op nette spaties en
    hoofdletters na — een merk mag niet stilletjes verdwijnen omdat het niet
    in de lijst staat."""
    if naam is None:
        return None
    schoon = _SPATIES.sub(" ", str(naam).strip()).upper()
    if not schoon:
        return None
    return ALIASSEN.get(schoon, schoon)
