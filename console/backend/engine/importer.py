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

from . import parser as parser_mod
from .profile import Profile, get_profiles


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def run_import(conn, filename: str, content: bytes) -> dict:
    """Import one file inside the caller's transaction. Returns a summary dict
    mirroring an `imports` row."""
    h = file_hash(content)
    profiles = get_profiles(conn)
    profile = parser_mod.detect(filename, content, profiles)

    existing = conn.execute("SELECT id FROM imports WHERE file_hash=?", (h,)).fetchone()
    if existing:
        conn.execute("DELETE FROM sellout_facts WHERE import_id=?", (existing["id"],))
        conn.execute("DELETE FROM imports WHERE id=?", (existing["id"],))

    if profile is None:
        cur = conn.execute(
            "INSERT INTO imports (retailer_id, profile_id, filename, file_hash, status) "
            "VALUES (NULL, NULL, ?, ?, 'profiel_nodig')", (filename, h))
        return {"import_id": cur.lastrowid, "status": "profiel_nodig", "filename": filename,
                "retailer_id": None, "rows": 0,
                "detail": "geen (eenduidig) profiel herkend — kolommen mappen in de Parser"}

    try:
        result = parser_mod.parse_file(filename, content, profile)
    except parser_mod.ParseError as e:
        cur = conn.execute(
            "INSERT INTO imports (retailer_id, profile_id, filename, file_hash, status, error_detail) "
            "VALUES (?,?,?,?, 'error', ?)",
            (profile.retailer_id, profile.id, filename, h,
             json.dumps({"message": str(e), "rijen": e.row_errors}, ensure_ascii=False)))
        return {"import_id": cur.lastrowid, "status": "error", "filename": filename,
                "retailer_id": profile.retailer_id, "rows": 0, "detail": str(e)}

    status = "test" if profile.status == "test" else "ingelezen"
    periodes = result["periodes"]
    cur = conn.execute(
        "INSERT INTO imports (retailer_id, profile_id, filename, file_hash, periode_type, "
        "periode, row_count, status) VALUES (?,?,?,?,?,?,?,?)",
        (profile.retailer_id, profile.id, filename, h, result["periode_type"],
         ", ".join(periodes), len(result["facts"]), status))
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
            "periode": ", ".join(periodes), "rows": len(result["facts"]), "detail": None}


# Analyses must only see counted facts: live-profile imports.
COUNTED_FACTS = ("sellout_facts f JOIN imports im ON im.id = f.import_id "
                 "AND im.status = 'ingelezen'")
