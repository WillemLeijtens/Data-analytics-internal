"""Gaten in de aanlevering vinden en in gewone taal benoemen.

Aanleiding: van DEPEND kwam voor België vanaf week 3 niets meer binnen. De
artikel- en assortimentsanalyse telden die weken gewoon als nul mee, dus een
artikel dat in BE prima liep zag eruit als een artikel dat instortte — en de
rotatie per winkel zakte mee. Nergens stond dat er data ontbrak.

Een retailer levert per scope: een land, en bij Kruidvat ook per formule.
Stopt zo'n scope eerder dan de rest, begint hij later, of zit er een gat in,
dan is elk artikel dat daar verkocht wordt vertekend. Deze module vindt die
gaten; de analyses hangen ze aan de artikelen die het aangaat.

Bewust NIET aan alle artikelen: een artikel dat nooit in België verkocht is
heeft aan een BE-melding niets, en een waarschuwing die overal staat leest
niemand meer.
"""

from __future__ import annotations

from collections import defaultdict

from .periods import period_number, period_year, sort_key

# Landcodes uitschrijven; onbekende codes blijven staan zoals ze zijn. Beter
# een code tonen die de gebruiker herkent dan een verzonnen naam.
LANDEN = {
    "NL": "Nederland",
    "BE": "België",
    "LU": "Luxemburg",
    "DE": "Duitsland",
    "FR": "Frankrijk",
}


def _nr(periode: str) -> int:
    """Het periodenummer zoals de gebruiker het kent (week 3, maand 7)."""
    return period_number(periode)


def _land(code: str | None) -> str:
    if not code:
        return "onbekend land"
    return LANDEN.get(code.upper(), code)


def _opsomming(nummers: list[int]) -> str:
    """[6] -> '6';  [6, 7] -> '6 en 7';  [6, 7, 9] -> '6, 7 en 9'."""
    tekst = [str(n) for n in nummers]
    if len(tekst) == 1:
        return tekst[0]
    return f"{', '.join(tekst[:-1])} en {tekst[-1]}"


def scope_van(rij, caps: dict) -> tuple:
    """De eenheid waarin deze retailer aanlevert. Zonder formuleniveau is dat
    alleen het land — anders zou elke rij zijn eigen scope worden."""
    return (rij["land"], rij["banner"] if caps.get("banner") else None)


def _naam(scope: tuple, meerdere_formules: bool) -> str:
    land, banner = scope
    if banner and meerdere_formules:
        return f"{banner} in {_land(land)}"
    return _land(land)


def gaten(rows, caps: dict) -> list[dict]:
    """Wat er per scope ontbreekt, met de tekst die het scherm toont.

    Alleen binnen het laatste jaar in de data: dat is het venster waarover de
    analyses rekenen, en een feed die vorig jaar anders liep zegt niets over
    de cijfers van nu.
    """
    if not rows:
        return []
    pWoord = "maand" if caps.get("periode") == "maand" else "week"
    jaar = max(period_year(r["periode"]) for r in rows)
    dit_jaar = [r for r in rows if period_year(r["periode"]) == jaar]
    if not dit_jaar:
        return []

    # De periodeas van de retailer als geheel: alleen periodes die iemand
    # geleverd heeft. Een week die niemand levert is geen gat maar toekomst.
    as_periodes = sorted({r["periode"] for r in dit_jaar}, key=sort_key)
    per_scope: dict[tuple, set] = defaultdict(set)
    for r in dit_jaar:
        per_scope[scope_van(r, caps)].add(r["periode"])

    meerdere_formules = len({s[1] for s in per_scope if s[1]}) > 1
    # Eén scope kan per definitie niet achterlopen op zichzelf.
    if len(per_scope) < 2:
        return []

    nummer = {p: i for i, p in enumerate(as_periodes)}
    uit = []
    for scope, periodes in sorted(per_scope.items(), key=lambda kv: str(kv[0])):
        eigen = sorted(periodes, key=sort_key)
        eerste, laatste = nummer[eigen[0]], nummer[eigen[-1]]
        naam = _naam(scope, meerdere_formules)

        if laatste < len(as_periodes) - 1:
            volgende = as_periodes[laatste + 1]
            uit.append({
                "soort": "stopt", "land": scope[0], "banner": scope[1],
                "vanaf": volgende,
                "tekst": f"vanaf {pWoord} {_nr(volgende)} geen data voor {naam}",
            })
        if eerste > 0:
            uit.append({
                "soort": "begint_later", "land": scope[0], "banner": scope[1],
                "vanaf": eigen[0],
                "tekst": f"geen data voor {naam} vóór {pWoord} {_nr(eigen[0])}",
            })
        # Gaten binnen het eigen bereik: periodes die anderen wél hebben.
        ontbreekt = [p for p in as_periodes[eerste:laatste + 1] if p not in periodes]
        if ontbreekt:
            uit.append({
                "soort": "onderbroken", "land": scope[0], "banner": scope[1],
                "periodes": ontbreekt,
                "tekst": f"geen data voor {naam} in {pWoord} "
                         f"{_opsomming([_nr(p) for p in ontbreekt])}",
            })
    return uit


def per_artikel(alle_gaten: list[dict], rijen, caps: dict) -> list[dict]:
    """De gaten die dít artikel raken: alleen de scopes waarin het verkocht
    wordt. Zonder die beperking krijgt elk artikel elke melding."""
    if not alle_gaten:
        return []
    eigen = {scope_van(r, caps) for r in rijen}
    return [g for g in alle_gaten if (g["land"], g["banner"]) in eigen]
