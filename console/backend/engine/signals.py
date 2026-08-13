"""Signal radar (Overzicht): per retailer three signals — assortiment,
contract, data — plus the composite (worst wins).

green = op orde, orange = let op, red = actie nodig, grey = n.v.t.
"""

from __future__ import annotations

import datetime as dt

from . import analytics
from .periods import sort_key
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


def data_signal(conn, retailer_id: str) -> tuple[str, str]:
    """Feeds behind the expected cadence: newest period vs today. A weekly
    feed more than 2 periods behind = orange, more than 4 = red."""
    row = conn.execute(
        "SELECT f.periode, f.periode_type FROM sellout_facts f "
        "JOIN imports im ON im.id=f.import_id AND im.status IN ('ingelezen','test') "
        "WHERE f.retailer_id=? ", (retailer_id,)).fetchall()
    if not row:
        return "grey", "Nog geen data"
    latest = max((r["periode"] for r in row), key=sort_key)
    ptype = row[0]["periode_type"]
    today = dt.date.today()
    if ptype == "week":
        current = int(today.strftime("%V"))
        expected, unit = current - 1, "week"
        behind = expected - int(latest.split("-W")[1]) if latest.startswith(str(today.year)) else 5
    else:
        expected, unit = today.month - 1, "maand"
        behind = expected - int(latest[-2:]) if latest.startswith(str(today.year)) else 5
    if behind <= 1:
        return "green", f"Actueel t/m {latest}"
    if behind <= 4:
        return "orange", f"{behind} {unit}(en) achter"
    return "red", f"Feed {behind} {unit}(en) achter"


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


def retailer_signals(conn, retailer_id: str) -> dict:
    prof = active_profile(conn, retailer_id)
    if prof is None:
        return {"assortiment": {"signaal": "grey", "tekst": "n.v.t."},
                "contract": {"signaal": "grey", "tekst": "n.v.t."},
                "data": {"signaal": "grey", "tekst": "Nog geen profiel"},
                "composiet": "grey", "context": "Nog geen profiel"}
    a_sig, a_txt = assortment_signal(conn, retailer_id)
    c_sig, c_txt = contract_signal(conn, retailer_id)
    d_sig, d_txt = data_signal(conn, retailer_id)
    comp = _worst([a_sig, c_sig, d_sig])
    context = {a_sig: a_txt, c_sig: c_txt, d_sig: d_txt}.get(comp, "Alles op orde") \
        if comp != "green" else "Alles op orde"
    return {"assortiment": {"signaal": a_sig, "tekst": a_txt},
            "contract": {"signaal": c_sig, "tekst": c_txt},
            "data": {"signaal": d_sig, "tekst": d_txt},
            "composiet": comp, "context": context}


def overview(conn) -> dict:
    retailers = conn.execute("SELECT * FROM retailers ORDER BY rowid").fetchall()
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
