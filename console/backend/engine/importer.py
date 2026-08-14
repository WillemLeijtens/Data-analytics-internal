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
    mirroring an `imports` row.

    A re-upload of a file whose facts are already loaded must never destroy
    those facts on a FAILED attempt (e.g. after a profile change): the old
    import is only replaced once the new parse has fully succeeded."""
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
        # Look inside the file anyway: the Parser screen prefills its mapping
        # table with these columns, so the user maps instead of typing.
        sniffed = parser_mod.sniff(filename, content)
        replace_existing()
        cur = conn.execute(
            "INSERT INTO imports (retailer_id, profile_id, filename, file_hash, status, "
            "error_detail) VALUES (NULL, NULL, ?, ?, 'profiel_nodig', ?)",
            (filename, h, json.dumps({"sniff": sniffed}, ensure_ascii=False)))
        return {"import_id": cur.lastrowid, "status": "profiel_nodig", "filename": filename,
                "retailer_id": None, "rows": 0, "sniff": sniffed,
                "detail": "geen (eenduidig) profiel herkend — kolommen mappen in de Parser"}

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

    replace_existing()
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


# Analyses must only see counted facts: live-profile imports.
COUNTED_FACTS = ("sellout_facts f JOIN imports im ON im.id = f.import_id "
                 "AND im.status = 'ingelezen'")
