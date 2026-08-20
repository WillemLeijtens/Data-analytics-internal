"""Gaten in de aanlevering vinden en in gewone taal benoemen.

Aanleiding: van DEPEND kwam voor België vanaf week 3 niets meer binnen. De
artikel- en assortimentsanalyse telden die weken gewoon als nul mee, dus een
artikel dat in BE prima liep zag eruit als een artikel dat instortte — en de
rotatie per winkel zakte mee. Nergens stond dat er data ontbrak.

Een retailer levert per scope: een merk (feeds komen per merk of merkgroep
binnen, in eigen bestanden met een eigen ritme), een land, en bij Kruidvat
ook per formule. Stopt zo'n scope eerder dan de rest, begint hij later, of
zit er een gat in, dan is elk artikel dat daar verkocht wordt vertekend.
Deze module vindt die gaten; de analyses hangen ze aan de artikelen die het
aangaat. Zonder de merk-dimensie was een merk-feed die 15 weken achterliep
(TWEEZERMAN op de echte Kruidvat-bestanden) volstrekt onzichtbaar zolang een
ánder merk het land wel vulde.

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
    """De eenheid waarin deze retailer aanlevert: merk x land (x formule).
    Zonder formuleniveau blijft de formule buiten de sleutel — anders zou
    elke rij zijn eigen scope worden."""
    return (rij["merk"], rij["land"], rij["banner"] if caps.get("banner") else None)


def _naam(scope: tuple, meerdere_formules: bool, meerdere_merken: bool) -> str:
    """Alleen de dimensies noemen die onderscheiden: bij één merk is
    "TWEEZERMAN in Nederland" ruis, bij meerdere is het de kern."""
    merk, land, banner = scope
    plek = f"{banner} in {_land(land)}" if banner and meerdere_formules else _land(land)
    if merk and meerdere_merken:
        return f"{merk} in {plek}" if not (banner and meerdere_formules) \
            else f"{merk} ({plek})"
    return plek


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

    meerdere_formules = len({s[2] for s in per_scope if s[2]}) > 1
    meerdere_merken = len({s[0] for s in per_scope if s[0]}) > 1
    # Eén scope kan per definitie niet achterlopen op zichzelf.
    if len(per_scope) < 2:
        return []

    nummer = {p: i for i, p in enumerate(as_periodes)}
    uit = []
    for scope, periodes in sorted(per_scope.items(), key=lambda kv: str(kv[0])):
        eigen = sorted(periodes, key=sort_key)
        eerste, laatste = nummer[eigen[0]], nummer[eigen[-1]]
        naam = _naam(scope, meerdere_formules, meerdere_merken)

        # Eén periode achterlopen is normale levercadans (de Belgische feed
        # komt structureel een week na de Nederlandse); dat elke week als
        # rood gat melden went de gebruiker aan het negeren van de driehoek.
        # Vanaf twee periodes is het een gat.
        if laatste < len(as_periodes) - 2:
            volgende = as_periodes[laatste + 1]
            uit.append({
                "soort": "stopt", "merk": scope[0], "land": scope[1],
                "banner": scope[2],
                "vanaf": volgende,
                "tekst": f"vanaf {pWoord} {_nr(volgende)} geen data voor {naam}",
            })
        if eerste > 0:
            uit.append({
                "soort": "begint_later", "merk": scope[0], "land": scope[1],
                "banner": scope[2],
                "vanaf": eigen[0],
                "tekst": f"geen data voor {naam} vóór {pWoord} {_nr(eigen[0])}",
            })
        # Gaten binnen het eigen bereik: periodes die anderen wél hebben.
        ontbreekt = [p for p in as_periodes[eerste:laatste + 1] if p not in periodes]
        if ontbreekt:
            uit.append({
                "soort": "onderbroken", "merk": scope[0], "land": scope[1],
                "banner": scope[2],
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
    return [g for g in alle_gaten if (g["merk"], g["land"], g["banner"]) in eigen]
