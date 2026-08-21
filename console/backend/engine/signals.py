"""Signal radar (Overzicht): per retailer four signals — assortiment,
distributie, contract, data — plus the composite (worst wins).

green = op orde, orange = let op, red = actie nodig, grey = n.v.t.
"""

from __future__ import annotations

import datetime as dt

from . import analytics
from .periods import period_number, period_year
from .profile import active_profile, capabilities

ORDER = {"grey": 0, "green": 1, "orange": 2, "red": 3}


def _worst(signals: list[str]) -> str:
    real = [s for s in signals if s != "grey"]
    return max(real, key=lambda s: ORDER[s]) if real else "grey"


def contract_signal(conn, retailer_id: str, today: dt.date | None = None) -> tuple[str, str]:
    """Worst contract document; expiry recomputed live: expired or <7 days
    = red, <30 days = orange."""
    today = today or dt.date.today()
    docs = conn.execute(
        "SELECT naam, geldig_tot, signaal FROM contract_documents WHERE retailer_id=?",
        (retailer_id,)).fetchall()
    if not docs:
        return "grey", "Geen documenten gekoppeld"
    worst, note = "green", "Alles op orde"
    for d in docs:
        sig = d["signaal"]
        if d["geldig_tot"]:
            try:
                left = (dt.date.fromisoformat(d["geldig_tot"]) - today).days
            except ValueError:
                left = None
            if left is not None:
                if left < 7:
                    sig = "red"
                elif left < 30:
                    sig = "orange"
        if ORDER[sig] > ORDER[worst]:
            worst = sig
            if sig == "red":
                note = f"{d['naam']}: verlopen of verloopt deze week"
            elif sig == "orange":
                note = f"Verloopt {d['geldig_tot']}" if d["geldig_tot"] else d["naam"]
    return worst, note


def periods_behind(latest: str, ptype: str, today: dt.date | None = None) -> int:
    """How many periods the feed lags the last COMPLETED period. Counts
    across year boundaries, so a 2025-W52 feed in early January is current
    instead of falsely red."""
    today = today or dt.date.today()
    if ptype == "week":
        iso = today.isocalendar()
        current_idx = iso[0] * 53 + iso[1]
        latest_idx = period_year(latest) * 53 + period_number(latest)
    else:
        current_idx = today.year * 12 + today.month
        latest_idx = period_year(latest) * 12 + period_number(latest)
    return max(0, (current_idx - 1) - latest_idx)


def data_signal(conn, retailer_id: str) -> tuple[str, str]:
    """Feeds behind the expected cadence: newest period vs the last completed
    period. <=1 behind = green, <=4 = orange, more = red."""
    prof = active_profile(conn, retailer_id)
    statuses = ("ingelezen", "test") if prof and prof.status == "test" else ("ingelezen",)
    # Per merk-feed de nieuwste periode: één achterlopend merk hoort het
    # signaal te kleuren. Met alleen MAX(periode) over alles bleef een feed
    # die 15 weken achterliep groen zolang een ander merk actueel was
    # (TWEEZERMAN op de echte Kruidvat-bestanden). MAX(periode) per merk kan
    # lexicografisch: het periodeformaat ('2026-W07', '2026-07') heeft vaste
    # breedte en loopt gelijk met sort_key.
    rows = conn.execute(
        "SELECT f.merk, MAX(f.periode) AS periode, MAX(f.periode_type) AS periode_type "
        "FROM sellout_facts f "
        f"JOIN imports im ON im.id=f.import_id AND im.status IN ({','.join('?' * len(statuses))}) "
        "WHERE f.retailer_id=? GROUP BY f.merk", (*statuses, retailer_id)).fetchall()
    if not rows:
        return "grey", "Nog geen data"
    ptype = rows[0]["periode_type"]
    unit = "week" if ptype == "week" else "maand"
    per_feed = [(r["merk"], r["periode"], periods_behind(r["periode"], ptype))
                for r in rows]
    merk, _periode, behind = max(per_feed, key=lambda f: f[2])
    nieuwste = max(p for _, p, _b in per_feed)
    if behind <= 1:
        return "green", f"Actueel t/m {nieuwste}"
    wie = f"{merk or 'feed'} " if len(per_feed) > 1 else ""
    if behind <= 4:
        return "orange", f"{wie}{behind} {unit}(en) achter"
    return "red", f"{wie}{behind} {unit}(en) achter"


def assortment_signal(conn, retailer_id: str) -> tuple[str, str]:
    result = analytics.assortment(conn, retailer_id)
    if not result.get("available"):
        return "grey", "n.v.t."
    stats = result["stats"]
    n = len(result["artikelen"]) or 1
    if stats["delist"] and stats["delist"] / n >= 0.25:
        return "red", f"{stats['delist']} delist-kandidaten"
    if stats["delist"]:
        return "orange", f"{stats['delist']} mogelijke delist"
    if stats["onder_target"]:
        return "orange", f"{stats['onder_target']} artikelen onder target"
    return "green", "Alles op orde"


def distributie_signal(conn, retailer_id: str) -> tuple[str, str]:
    """Loopt het aantal winkels dat onze merken voert terug?

    Twee bronnen, afhankelijk van wat de retailer aanlevert:
      * winkelniveau in de feed (ICI) -> de winkelanalyse telt de winkels die
        dit jaar stilgevallen zijn, met de omzet die we daardoor mislopen;
      * geen winkelniveau (Kruidvat, Etos) -> de handmatig ingevulde
        winkelaantallen uit Instellingen, waarvan elke wijziging bewaard
        wordt. Zonder tweede meting valt er nog niets te zeggen (grijs).
    """
    prof = active_profile(conn, retailer_id)
    if not prof:
        return "grey", "n.v.t."
    caps = capabilities(prof.definition)

    if caps.get("winkel"):
        rows = analytics.load_facts(conn, retailer_id)
        if not rows:
            return "grey", "Nog geen data"
        jaar = max(period_year(r["periode"]) for r in rows)
        w = analytics.winkelanalyse(rows, caps, jaar)
        gestopt = len(w.get("gestopt", []))
        if not gestopt:
            return "green", "Geen winkels stilgevallen"
        gemist = w.get("gemiste_omzet") or 0
        tekst = f"{gestopt} winkel(s) gestopt · € {gemist:,.0f} gemist".replace(",", ".")
        # Eén stille winkel is opruimwerk; een reeks is een distributieprobleem.
        return ("red" if gestopt >= 5 else "orange"), tekst

    # Handmatige aantallen: vergelijk de laatste meting per scope met de
    # meting daarvóór. Alleen dalingen zijn een signaal.
    hist = conn.execute(
        "SELECT merk, land, banner, aantal_winkels, gemeten_op "
        "FROM winkelaantal_historie WHERE retailer_id=? "
        "ORDER BY merk, land, banner, gemeten_op", (retailer_id,)).fetchall()
    per_scope: dict[tuple, list] = {}
    for r in hist:
        per_scope.setdefault((r["merk"], r["land"], r["banner"]), []).append(r)
    dalingen = []
    for (merk, _land, _banner), rijen in per_scope.items():
        if len(rijen) < 2:
            continue
        nu, vorig = rijen[-1]["aantal_winkels"], rijen[-2]["aantal_winkels"]
        if nu < vorig:
            dalingen.append((merk, vorig, nu, rijen[-1]["gemeten_op"][:10]))
    if not per_scope:
        return "grey", "Geen winkelaantallen ingevuld"
    if not any(len(r) >= 2 for r in per_scope.values()):
        return "grey", "Nog maar één meting"
    if not dalingen:
        return "green", "Winkelbestand stabiel"
    dalingen.sort(key=lambda d: d[2] - d[1])
    merk, vorig, nu, sinds = dalingen[0]
    pct = (vorig - nu) / vorig * 100
    tekst = f"{merk}: {vorig} → {nu} winkels sinds {sinds}"
    if len(dalingen) > 1:
        tekst += f" (+{len(dalingen) - 1} ander(e))"
    return ("red" if pct >= 10 else "orange"), tekst


def retailer_signals(conn, retailer_id: str) -> dict:
    prof = active_profile(conn, retailer_id)
    if prof is None:
        return {"assortiment": {"signaal": "grey", "tekst": "n.v.t."},
                "distributie": {"signaal": "grey", "tekst": "n.v.t."},
                "contract": {"signaal": "grey", "tekst": "n.v.t."},
                "data": {"signaal": "grey", "tekst": "Nog geen profiel"},
                "composiet": "grey", "context": "Nog geen profiel"}
    a_sig, a_txt = assortment_signal(conn, retailer_id)
    v_sig, v_txt = distributie_signal(conn, retailer_id)
    c_sig, c_txt = contract_signal(conn, retailer_id)
    d_sig, d_txt = data_signal(conn, retailer_id)
    comp = _worst([a_sig, v_sig, c_sig, d_sig])
    context = {a_sig: a_txt, v_sig: v_txt, c_sig: c_txt, d_sig: d_txt}.get(
        comp, "Alles op orde") if comp != "green" else "Alles op orde"
    return {"assortiment": {"signaal": a_sig, "tekst": a_txt},
            "distributie": {"signaal": v_sig, "tekst": v_txt},
            "contract": {"signaal": c_sig, "tekst": c_txt},
            "data": {"signaal": d_sig, "tekst": d_txt},
            "composiet": comp, "context": context}


def overview(conn) -> dict:
    retailers = conn.execute("SELECT * FROM retailers ORDER BY aangesloten DESC, rowid").fetchall()
    cards = []
    for r in retailers:
        prof = active_profile(conn, r["id"])
        caps = capabilities(prof.definition) if prof else None
        cards.append({
            "id": r["id"], "naam": r["naam"], "aangesloten": bool(r["aangesloten"]),
            "profiel": {"versie": prof.version, "status": prof.status} if prof else None,
            "capabilities": caps,
            "signalen": retailer_signals(conn, r["id"]),
        })
    attention = sum(1 for c in cards if c["signalen"]["composiet"] in ("orange", "red"))
    return {"retailers": cards, "aandacht": attention}
