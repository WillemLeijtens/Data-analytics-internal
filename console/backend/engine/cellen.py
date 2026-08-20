"""Celwaarden uit een werkblad omzetten naar wat ze semantisch zijn.

Deze module bestaat omdat dezelfde fout drie keer los is gemaakt: elke
parser had zijn eigen `str(int(cel))` voor SKU's, UPC's en winkelcodes, en
toen die in één parser gecorrigeerd werd, bleven de andere twee stilzwijgend
identifiers verminken. Eén plek dus.
"""

from __future__ import annotations

import math
import re

# "12345.0" — een identifier die onderweg door een float is gegaan. De ".0"
# is een artefact van de opslag, geen onderdeel van de identifier zelf.
_FLOAT_STAART = re.compile(r"\d+\.0+")


def als_identifier(raw) -> str | None:
    """Een celwaarde als identifier (SKU, UPC, EAN, winkelcode) — nooit als getal.

    Een TEKSTcel behoudt zijn leidende nullen; die zijn betekenisdragend
    ('012345678905' is een ander artikel dan '12345678905'). Een NUMERIEKE
    cel kan een leidende nul per definitie niet dragen, dus daar is int()
    ongevaarlijk — het dient er alleen toe om de ".0" van een float weg te
    halen.

    Geeft None terug als er geen bruikbare identifier in de cel staat; de
    aanroeper beslist zelf of dat een overgeslagen rij of een fout is.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        tekst = raw.strip()
        if not tekst:
            return None
        # Alleen een zuivere ".0"-staart weghalen. "1.5" blijft "1.5": dat is
        # geen identifier-die-door-een-float-ging maar gewoon andere inhoud,
        # en stilzwijgend afkappen zou opnieuw data weggooien.
        if _FLOAT_STAART.fullmatch(tekst):
            return tekst.split(".", 1)[0]
        return tekst
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        if not math.isfinite(raw) or raw != int(raw):
            return None
        return str(int(raw))
    tekst = str(raw).strip()
    return tekst or None
