"""Meerjarige gaten in de aanlevering: een jaar dat helemaal ontbreekt.

`dekking.py` vindt gaten BINNEN het laatste jaar — het filtert daar eerst op
(`jaar = max(...)`). Een merk dat in 2024 doorverkoop had, in 2025 niets, en
in 2026 weer wel, valt daar per definitie buiten. Juist dat gat is
interessant, want er zijn twee heel verschillende verklaringen:

  * het klopt      — het merk lag dat jaar niet bij deze retailer;
  * het klopt niet — er is een bestand nooit ingelezen.

Het verschil is niet uit de data af te leiden: in beide gevallen staat er
niets. Alleen een mens weet het. Daarom meldt deze module het gat en vraagt
hij om een oordeel, in plaats van zelf een conclusie te verzinnen.

Een onbeoordeeld gat is een waarschuwing bij elke analyse die dat merk raakt:
zonder oordeel weet niemand of de YoY-vergelijking over dat jaar iets
betekent.
"""

from __future__ import annotations

from collections import defaultdict

from .dekking import _land, scope_van
from .periods import period_year


def _naam(merk: str | None, land: str | None, banner: str | None) -> str:
    delen = [d for d in (merk, banner) if d]
    plek = _land(land) if land else None
    if plek:
        delen.append(f"in {plek}")
    return " ".join(delen) if delen else "deze aanlevering"


def _reeksen(ontbrekend: list[int]) -> list[tuple[int, int]]:
    """Aaneengesloten reeksen: [2025] -> [(2025,2025)]; [2020,2021,2023] ->
    [(2020,2021),(2023,2023)]. Twee losse gaten zijn twee vragen, geen één."""
    reeksen: list[tuple[int, int]] = []
    for jaar in sorted(ontbrekend):
        if reeksen and jaar == reeksen[-1][1] + 1:
            reeksen[-1] = (reeksen[-1][0], jaar)
        else:
            reeksen.append((jaar, jaar))
    return reeksen


def vind(rows, caps: dict) -> list[dict]:
    """Per scope de jaren die tussen de eerste en laatste levering ontbreken.

    Alleen jaren die de RETAILER als geheel wél geleverd heeft tellen mee:
    een jaar waarin niemand iets leverde is geen gat in deze scope maar een
    jaar waarin de samenwerking nog niet liep (of nog moet komen).
    """
    if not rows:
        return []
    jaren_retailer = {period_year(r["periode"]) for r in rows}
    per_scope: dict[tuple, set] = defaultdict(set)
    for r in rows:
        per_scope[scope_van(r, caps)].add(period_year(r["periode"]))

    uit = []
    for scope, jaren in sorted(per_scope.items(), key=lambda kv: str(kv[0])):
        eerste, laatste = min(jaren), max(jaren)
        # Alleen ingesloten jaren: vóór de eerste levering is het merk er nog
        # niet, ná de laatste is het gestopt — dat is geen gat maar een begin
        # of een einde, en dat vertelt de analyse zelf al.
        ontbrekend = [j for j in sorted(jaren_retailer)
                      if eerste < j < laatste and j not in jaren]
        merk, land, banner = scope
        for van, tot in _reeksen(ontbrekend):
            periode = str(van) if van == tot else f"{van} t/m {tot}"
            uit.append({
                "merk": merk, "land": land, "banner": banner,
                "van_jaar": van, "tot_jaar": tot,
                "jaren_met_data": sorted(jaren),
                "tekst": f"geen data voor {_naam(merk, land, banner)} in {periode}, "
                         f"terwijl er vóór én ná dat jaar wél data is",
            })
    return uit


def met_oordeel(conn, retailer_id: str, rows, caps: dict) -> list[dict]:
    """De gevonden gaten, elk met het eerder gegeven oordeel (of None)."""
    gaten = vind(rows, caps)
    if not gaten:
        return []
    oordelen = {
        (r["merk"], r["land"], r["banner"], r["van_jaar"], r["tot_jaar"]): dict(r)
        for r in conn.execute(
            "SELECT * FROM datagat_oordelen WHERE retailer_id=?", (retailer_id,))}
    for g in gaten:
        eerder = oordelen.get((g["merk"], g["land"], g["banner"],
                               g["van_jaar"], g["tot_jaar"]))
        g["oordeel"] = eerder["oordeel"] if eerder else None
        g["toelichting"] = eerder["toelichting"] if eerder else None
        g["beoordeeld_door"] = eerder["door"] if eerder else None
        g["beoordeeld_op"] = eerder["op"] if eerder else None
    return gaten


def bewaar_oordeel(conn, retailer_id: str, merk, land, banner,
                   van_jaar: int, tot_jaar: int, oordeel: str,
                   toelichting: str | None, door: str | None) -> None:
    if oordeel not in ("klopt", "klopt_niet"):
        raise ValueError(f"oordeel moet 'klopt' of 'klopt_niet' zijn, niet {oordeel!r}")
    conn.execute(
        "DELETE FROM datagat_oordelen WHERE retailer_id=? AND COALESCE(merk,'')=? "
        "AND COALESCE(land,'')=? AND COALESCE(banner,'')=? AND van_jaar=? AND tot_jaar=?",
        (retailer_id, merk or "", land or "", banner or "", van_jaar, tot_jaar))
    conn.execute(
        "INSERT INTO datagat_oordelen (retailer_id, merk, land, banner, van_jaar, "
        "tot_jaar, oordeel, toelichting, door) VALUES (?,?,?,?,?,?,?,?,?)",
        (retailer_id, merk, land, banner, van_jaar, tot_jaar, oordeel,
         (toelichting or "").strip() or None, door))
