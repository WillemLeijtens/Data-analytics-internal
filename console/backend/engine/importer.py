"""Import pipeline: detect profile -> parse -> atomically store facts.

Rules (PROMPT.md §3, acceptance 3-5):
  * unknown / ambiguous file  -> import row with status 'profiel_nodig', no facts
  * parse/validation error    -> status 'error' + row detail, ZERO new facts
  * profile status 'test'     -> facts stored but import flagged 'test';
                                 analyses exclude them
  * re-import of an identical file (same hash) replaces the previous import's
    facts in the same transaction — never duplicates
"""

from __future__ import annotations

import hashlib
import json

from . import merken
from . import parser as parser_mod
from .profile import Profile, get_profiles


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


_FACT_KEY = ("merk", "land", "banner", "winkel_id", "artikel_ean", "periode")

# De natuurlijke sleutel als één tekstwaarde. CHAR(31) (unit separator) komt
# in geen enkel veld voor, dus twee verschillende sleutels kunnen niet op
# dezelfde tekst uitkomen.
_SLEUTEL_SQL = ("COALESCE(merk,'')||CHAR(31)||COALESCE(land,'')||CHAR(31)"
                "||COALESCE(banner,'')||CHAR(31)||COALESCE(winkel_id,'')||CHAR(31)"
                "||COALESCE(artikel_ean,'')||CHAR(31)||periode")


def _sleutel(fact: dict) -> str:
    return "\x1f".join("" if fact.get(k) is None else str(fact.get(k)) for k in _FACT_KEY[:-1]) \
        + "\x1f" + str(fact["periode"])


def _replace_redelivered_facts(conn, retailer_id: str, facts: list[dict]):
    """Verwijder bestaande feiten die dit bestand opnieuw levert.

    Een retailer stuurt regelmatig een correctie of een bestand dat een
    eerdere periode overlapt. Zonder deze stap zouden die regels ernaast
    komen te staan en telt het dashboard ze bij elkaar op — de correctie
    verdubbelt dan de omzet in plaats van hem te vervangen. Alleen exact de
    combinaties uit het nieuwe bestand worden vervangen; andere merken,
    winkels en periodes blijven onaangeroerd, dus de historie blijft staan.

    De sleutel gaat als één tekstkolom mét index de temp-tabel in: met zes
    losse COALESCE-vergelijkingen scant SQLite de sleuteltabel opnieuw voor
    élke feitregel (EXPLAIN QUERY PLAN: 'SCAN k'), wat bij een ICI-import
    van 4355 regels neerkomt op miljoenen vergelijkingen. Nu is het één
    indexopzoeking per regel."""
    conn.execute("DROP TABLE IF EXISTS temp._nieuwe_sleutels")
    conn.execute("CREATE TEMP TABLE _nieuwe_sleutels (sleutel TEXT PRIMARY KEY)")
    conn.executemany(
        "INSERT OR IGNORE INTO temp._nieuwe_sleutels (sleutel) VALUES (?)",
        [(s,) for s in sorted({_sleutel(f) for f in facts})])
    conn.execute(
        f"DELETE FROM sellout_facts WHERE retailer_id = ? AND ({_SLEUTEL_SQL}) "
        "IN (SELECT sleutel FROM temp._nieuwe_sleutels)", (retailer_id,))
    conn.execute("DROP TABLE temp._nieuwe_sleutels")


def run_import(conn, filename: str, content: bytes) -> dict:
    """Import one file inside the caller's transaction. Returns a summary dict
    mirroring an `imports` row.

    A re-upload of a file whose facts are already loaded must never destroy
    those facts on a FAILED attempt (e.g. after a profile change): the old
    import is only replaced once the new parse has fully succeeded.

    Concurrency note: two simultaneous uploads of the SAME, never-before-seen
    file could both pass the `existing is None` check before either commits.
    That's not a silent-duplicate-data risk — `imports.file_hash` has a
    UNIQUE index (migrations/001_schema.sql), so SQLite's own writer
    serialization means the second INSERT raises an IntegrityError rather
    than creating a duplicate row. main.py's do_import() catches that as any
    other unexpected exception (safe generic message to the client, full
    detail logged) — the caller just needs to retry the "failed" upload,
    which then sees the now-committed row and behaves like any other
    re-upload of an already-loaded file. No additional locking needed."""
    h = file_hash(content)
    profiles = get_profiles(conn)
    profile = parser_mod.detect(filename, content, profiles)

    existing = conn.execute(
        "SELECT id, status, row_count FROM imports WHERE file_hash=?", (h,)).fetchone()
    existing_loaded = existing is not None and existing["status"] in ("ingelezen", "test")

    def replace_existing():
        if existing:
            conn.execute("DELETE FROM sellout_facts WHERE import_id=?", (existing["id"],))
            conn.execute("DELETE FROM imports WHERE id=?", (existing["id"],))

    if profile is None:
        if existing_loaded:
            return {"import_id": existing["id"], "status": existing["status"],
                    "filename": filename, "retailer_id": None,
                    "rows": existing["row_count"] or 0,
                    "detail": "bestand is al eerder ingelezen; de huidige profielen "
                              "herkennen het niet meer — bestaande data blijft staan"}
        # Look inside the file anyway: the sniffed columns are the starting
        # information for building this retailer's parser in the project.
        sniffed = parser_mod.sniff(filename, content)
        replace_existing()
        # Vindt ook de sniff geen tabel, dan is het bestand hoogstwaarschijnlijk
        # corrupt of geen spreadsheet — "deel het voor een parser" zou dan de
        # verkeerde kant op sturen.
        detail = ("geen parser herkent dit bestand — deel het bestand, "
                  "dan wordt de parser in het project gebouwd") if sniffed else \
                 ("bestand kon niet als tabel gelezen worden — is het een "
                  "geldig XLSX- of CSV-bestand?")
        cur = conn.execute(
            "INSERT INTO imports (retailer_id, profile_id, filename, file_hash, status, "
            "error_detail) VALUES (NULL, NULL, ?, ?, 'profiel_nodig', ?)",
            (filename, h, json.dumps({"sniff": sniffed}, ensure_ascii=False)))
        return {"import_id": cur.lastrowid, "status": "profiel_nodig", "filename": filename,
                "retailer_id": None, "rows": 0, "sniff": sniffed, "detail": detail}

    try:
        result = parser_mod.parse_file(filename, content, profile)
    except parser_mod.ParseError as e:
        if existing_loaded:
            # Not recorded: the successful import keeps the hash slot, and its
            # facts stay untouched.
            return {"import_id": existing["id"], "status": "error", "filename": filename,
                    "retailer_id": profile.retailer_id, "rows": 0,
                    "detail": f"{e} — de eerder ingelezen versie van dit bestand "
                              "blijft ongewijzigd staan"}
        replace_existing()
        cur = conn.execute(
            "INSERT INTO imports (retailer_id, profile_id, filename, file_hash, status, error_detail) "
            "VALUES (?,?,?,?, 'error', ?)",
            (profile.retailer_id, profile.id, filename, h,
             json.dumps({"message": str(e), "rijen": e.row_errors}, ensure_ascii=False)))
        return {"import_id": cur.lastrowid, "status": "error", "filename": filename,
                "retailer_id": profile.retailer_id, "rows": 0, "detail": str(e)}

    # Merknamen gelijktrekken VOORDAT er iets wordt vervangen of geschreven:
    # de natuurlijke sleutel bevat het merk, dus normaliseren na het bepalen
    # van wat vervangen moet worden zou de verkeerde rijen laten staan. Zie
    # engine/merken.py — dit is de enige poort waar alle feeds langskomen.
    for f in result["facts"]:
        f["merk"] = merken.normaliseer(f.get("merk"))

    replace_existing()
    _replace_redelivered_facts(conn, profile.retailer_id, result["facts"])
    status = "test" if profile.status == "test" else "ingelezen"
    periodes = result["periodes"]
    periode_txt = periodes[0] if len(periodes) == 1 else \
        f"{periodes[0]} t/m {periodes[-1]} ({len(periodes)})"
    warnings = result.get("warnings") or []
    cur = conn.execute(
        "INSERT INTO imports (retailer_id, profile_id, filename, file_hash, periode_type, "
        "periode, row_count, status, error_detail) VALUES (?,?,?,?,?,?,?,?,?)",
        (profile.retailer_id, profile.id, filename, h, result["periode_type"],
         periode_txt, len(result["facts"]), status,
         json.dumps({"warnings": warnings}, ensure_ascii=False) if warnings else None))
    import_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO sellout_facts (retailer_id, import_id, periode_type, periode, land, "
        "banner, winkel_id, winkel_naam, merk, artikel_ean, artikel_naam, volume, omzet) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(profile.retailer_id, import_id, result["periode_type"], f["periode"], f["land"],
          f["banner"], f["winkel_id"], f["winkel_naam"], f["merk"], f["artikel_ean"],
          f["artikel_naam"], f["volume"], f["omzet"]) for f in result["facts"]])
    return {"import_id": import_id, "status": status, "filename": filename,
            "retailer_id": profile.retailer_id, "profile_version": profile.version,
            "periode": periode_txt, "rows": len(result["facts"]),
            "detail": "; ".join(warnings) if warnings else None}
