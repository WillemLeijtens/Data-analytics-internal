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

# Dezelfde sleutel ZONDER winkel_id: dezelfde verkoop, alleen op een andere
# korrel geleverd. Zie _replace_redelivered_facts.
_GROVE_KEY = ("merk", "land", "banner", "artikel_ean")


def _grove_sleutel_sql(alias: str = "") -> str:
    p = f"{alias}." if alias else ""
    return ("||CHAR(31)||".join(f"COALESCE({p}{k},'')" for k in _GROVE_KEY)
            + f"||CHAR(31)||{p}periode")


def _sleutel(fact: dict) -> str:
    return "\x1f".join("" if fact.get(k) is None else str(fact.get(k)) for k in _FACT_KEY[:-1]) \
        + "\x1f" + str(fact["periode"])


def _grove_sleutel(fact: dict) -> str:
    return "\x1f".join("" if fact.get(k) is None else str(fact.get(k)) for k in _GROVE_KEY) \
        + "\x1f" + str(fact["periode"])


def _vervang_scope_maanden(conn, retailer_id: str, niveau: str, facts: list[dict]):
    """Vervanging voor een GESPLITSTE feed (Douglas, zie migratie 023).

    Zo'n rapport is per merk x land x formule x maand compleet: alle
    artikelen (of alle winkels) van die scope staan erin. Daarom vervalt de
    hele scope-maand op dit niveau, niet alleen de sleutels die het bestand
    opnieuw levert. Alleen op exacte sleutel vervangen zou bij een correctie
    een verdwenen winkel stil laten staan — en dan lopen de artikel- en de
    winkelverdeling van dezelfde maand uiteen, precies wat dit ontwerp niet
    mag laten gebeuren.

    Het andere niveau blijft onaangeroerd: de artikelregels van augustus
    zijn niet "dezelfde verkoop anders geteld" in de zin van de
    korrelwissel hieronder, ze zijn de andere helft van het ontwerp.
    Rijen zonder niveau (een retailer die van ongesplitst naar gesplitst
    overstapt) vervallen wél voor dezelfde scope-maand: die zouden anders
    naast beide slices blijven staan.
    """
    scopes = sorted({(f["merk"], f["land"], f["banner"], f["periode"]) for f in facts},
                    key=lambda t: tuple("" if v is None else str(v) for v in t))
    for merk, land, banner, periode in scopes:
        conn.execute(
            "DELETE FROM sellout_facts WHERE retailer_id = ? AND merk IS ? AND land IS ? "
            "AND banner IS ? AND periode = ? AND (niveau IS NULL OR niveau = ?)",
            (retailer_id, merk, land, banner, periode, niveau))


def _replace_redelivered_facts(conn, retailer_id: str, facts: list[dict],
                               niveau: str | None = None):
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
    indexopzoeking per regel.

    KORRELWISSEL. De sleutel bevat winkel_id, en dat is precies genoeg zolang
    een retailer op één korrel blijft leveren. Etos stapte over van de
    artikelniveau-export naar dezelfde widget mét Store-kolommen: dezelfde
    week, hetzelfde artikel, maar winkel_id NULL tegen winkel_id '6001'. Die
    sleutels botsen nooit, dus de oude regels bleven naast de nieuwe staan en
    elke week die in BEIDE bestanden zat telde dubbel. Gemeten op de echte
    Etos-data: week 32 stond op EUR 52.200 in plaats van EUR 26.100, waardoor
    het dashboard voor week 33 -56,2% meldde terwijl de werkelijke daling
    -12,4% was.

    Daarom vervalt óók de andere korrel van dezelfde verkoop: levert dit
    bestand een (merk, land, banner, artikel, periode) op winkelniveau, dan
    verdwijnt de artikelniveau-regel van diezelfde combinatie, en andersom.
    Dat kan nooit twee ECHTE regels raken — het is per definitie dezelfde
    verkoop, anders geteld. Regels die dit bestand niet levert (andere weken,
    andere merken) blijven staan, dus historie op de oude korrel blijft.

    Feiten mét een `niveau` (gesplitste feed) volgen een andere regel, zie
    _vervang_scope_maanden: daar is "artikel zonder winkel" tegen "winkel
    zonder artikel" geen korrelwissel maar het ontwerp zelf, en de
    korrelwissel-DELETE zou de artikelregels wegvegen zodra het
    winkelrapport binnenkomt."""
    if niveau:
        _vervang_scope_maanden(conn, retailer_id, niveau, facts)
        return
    conn.execute("DROP TABLE IF EXISTS temp._nieuwe_sleutels")
    conn.execute("DROP TABLE IF EXISTS temp._nieuwe_grof")
    conn.execute("CREATE TEMP TABLE _nieuwe_sleutels (sleutel TEXT PRIMARY KEY)")
    # Per grove sleutel: levert dit bestand hem op winkelniveau (1) of op
    # artikelniveau (0)? Beide kan, en dan vervalt er aan die kant niets.
    conn.execute("CREATE TEMP TABLE _nieuwe_grof "
                 "(sleutel TEXT PRIMARY KEY, met_winkel INT, zonder_winkel INT)")
    conn.executemany(
        "INSERT OR IGNORE INTO temp._nieuwe_sleutels (sleutel) VALUES (?)",
        [(s,) for s in sorted({_sleutel(f) for f in facts})])
    grof: dict[str, list[int]] = {}
    for f in facts:
        vlag = grof.setdefault(_grove_sleutel(f), [0, 0])
        vlag[0 if f.get("winkel_id") else 1] = 1
    conn.executemany(
        "INSERT OR IGNORE INTO temp._nieuwe_grof (sleutel, met_winkel, zonder_winkel) "
        "VALUES (?, ?, ?)", [(s, v[0], v[1]) for s, v in sorted(grof.items())])
    conn.execute(
        f"DELETE FROM sellout_facts WHERE retailer_id = ? AND ({_SLEUTEL_SQL}) "
        "IN (SELECT sleutel FROM temp._nieuwe_sleutels)", (retailer_id,))
    conn.execute(
        "DELETE FROM sellout_facts WHERE retailer_id = ? AND rowid IN ("
        "  SELECT f.rowid FROM sellout_facts f JOIN temp._nieuwe_grof g"
        f"    ON g.sleutel = ({_grove_sleutel_sql('f')})"
        "  WHERE f.retailer_id = ?"
        "    AND ((f.winkel_id IS NULL AND g.met_winkel = 1)"
        "      OR (f.winkel_id IS NOT NULL AND g.zonder_winkel = 1)))",
        (retailer_id, retailer_id))
    conn.execute("DROP TABLE temp._nieuwe_sleutels")
    conn.execute("DROP TABLE temp._nieuwe_grof")


def _gesplitste_feed_meldingen(conn, retailer_id: str, result: dict) -> list[str]:
    """Wat er bij een gesplitste feed te melden valt, vóór het inserten van de
    nieuwe regels (de vergelijking met de andere slice gebruikt dus wat er al
    STOND).

    * Ontbrekende maanden: staat er meer cumulatief dan deze maand terwijl
      er van dit jaar geen eerdere maand geladen is, dan bestaan er
      maandbestanden die nog niet geleverd zijn.
    * Achterlopende andere slice: het dashboard rekent op de winkelslice en
      stopt dus bij de laatste maand daarvan; de artikelanalyse gaat door.
      Dat hoort zichtbaar te zijn.
    """
    uit: list[str] = []
    niveau = result["niveau"]
    ander = "winkel" if niveau == "artikel" else "artikel"
    periodes = result["periodes"]
    laatste = periodes[-1] if periodes else None
    cum = result.get("cumulatief") or {}
    if laatste and cum.get("totaal", 0) > cum.get("maand", 0) + 1.0:
        jaar = laatste[:4]
        eerder = conn.execute(
            "SELECT 1 FROM sellout_facts WHERE retailer_id = ? AND niveau = ? "
            "AND periode < ? AND periode >= ? LIMIT 1",
            (retailer_id, niveau, laatste, f"{jaar}-01")).fetchone()
        if not eerder:
            uit.append(
                f"de eerdere maanden van {jaar} ontbreken: cumulatief EUR {cum['totaal']:,.0f} "
                f"tegen EUR {cum['maand']:,.0f} in {laatste} — vraag de eerdere "
                "maandbestanden op".replace(",", "."))
    if laatste:
        ander_max = conn.execute(
            "SELECT MAX(periode) FROM sellout_facts WHERE retailer_id = ? AND niveau = ?",
            (retailer_id, ander)).fetchone()[0]
        if ander_max is None:
            uit.append(f"het {ander}rapport is nog niet geladen; " + (
                "het dashboard rekent tot dan met handmatige winkelaantallen"
                if ander == "winkel" else
                "de artikelanalyse blijft tot dan leeg"))
        elif ander_max < laatste:
            uit.append(f"het {ander}rapport loopt achter: t/m {ander_max}, dit bestand "
                       f"is {laatste}")
    return uit


def _afstemming(conn, retailer_id: str, periodes: list[str]) -> list[str]:
    """Na het inserten: tellen beide slices per scope-maand nog op tot
    hetzelfde? Dit is de aanname waar het hele ontwerp op rust; een stil
    verschil zou betekenen dat het dashboard en de artikelanalyse elk een
    andere omzet tonen. Zelfde tolerantie als de ICI-reconciliatie."""
    if not periodes:
        return []
    marks = ",".join("?" * len(periodes))
    rijen = conn.execute(
        "SELECT merk, land, banner, periode, "
        "  SUM(CASE WHEN niveau='artikel' THEN omzet END) AS a, "
        "  SUM(CASE WHEN niveau='winkel' THEN omzet END) AS w "
        f"FROM sellout_facts WHERE retailer_id = ? AND periode IN ({marks}) "
        "AND niveau IS NOT NULL GROUP BY merk, land, banner, periode",
        (retailer_id, *periodes)).fetchall()
    scheef = []
    for r in rijen:
        if r["a"] is None or r["w"] is None:
            continue
        if abs(r["a"] - r["w"]) > max(1.0, 0.005 * abs(r["w"])):
            scheef.append(f"{r['merk']} {r['land']} {r['banner']} {r['periode']}: "
                          f"artikelen EUR {r['a']:,.0f} tegen winkels EUR {r['w']:,.0f}"
                          .replace(",", "."))
    if not scheef:
        return []
    return [f"artikel- en winkelrapport sluiten niet op elkaar aan voor "
            f"{len(scheef)} scope/maand-combinatie(s): {'; '.join(scheef[:3])}"
            + (" …" if len(scheef) > 3 else "")]


def run_import(conn, filename: str, content: bytes,
               retailer_id: str | None = None) -> dict:
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
    if retailer_id:
        # De gebruiker heeft gekozen tussen profielen die dit bestand allebei
        # herkennen (ICI NL en BE hebben dezelfde structuur). Alleen kiezen
        # uit de kandidaten: een willekeurige retailer meesturen mag een
        # bestand niet bij een parser krijgen die het niet aankan.
        profiles = [p for p in parser_mod.kandidaten(filename, content, profiles)
                    if p.retailer_id == retailer_id]
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
    _replace_redelivered_facts(conn, profile.retailer_id, result["facts"],
                               niveau=result.get("niveau"))
    status = "test" if profile.status == "test" else "ingelezen"
    periodes = result["periodes"]
    periode_txt = periodes[0] if len(periodes) == 1 else \
        f"{periodes[0]} t/m {periodes[-1]} ({len(periodes)})"
    warnings = list(result.get("warnings") or [])
    if result.get("niveau"):
        warnings += _gesplitste_feed_meldingen(conn, profile.retailer_id, result)
    cur = conn.execute(
        "INSERT INTO imports (retailer_id, profile_id, filename, file_hash, periode_type, "
        "periode, row_count, status, error_detail) VALUES (?,?,?,?,?,?,?,?,?)",
        (profile.retailer_id, profile.id, filename, h, result["periode_type"],
         periode_txt, len(result["facts"]), status,
         json.dumps({"warnings": warnings}, ensure_ascii=False) if warnings else None))
    import_id = cur.lastrowid
    # niveau: alleen een gesplitste feed (Douglas) levert dit; zie migratie
    # 023. Voor alle andere parsers blijft het NULL.
    niveau = result.get("niveau")
    conn.executemany(
        "INSERT INTO sellout_facts (retailer_id, import_id, periode_type, periode, land, "
        "banner, winkel_id, winkel_naam, merk, artikel_ean, artikel_naam, categorie, "
        "volume, omzet, niveau) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(profile.retailer_id, import_id, result["periode_type"], f["periode"], f["land"],
          f["banner"], f["winkel_id"], f["winkel_naam"], f["merk"], f["artikel_ean"],
          # categorie: alleen de Etos-parser levert dit vandaag; andere
          # profielen laten het veld gewoon leeg (.get, geen KeyError).
          f["artikel_naam"], f.get("categorie"), f["volume"], f["omzet"], niveau)
         for f in result["facts"]])
    if niveau:
        # Pas na het inserten te toetsen: beide slices moeten er staan.
        scheef = _afstemming(conn, profile.retailer_id,
                             sorted({f["periode"] for f in result["facts"]}))
        if scheef:
            warnings += scheef
            conn.execute("UPDATE imports SET error_detail = ? WHERE id = ?",
                         (json.dumps({"warnings": warnings}, ensure_ascii=False), import_id))
    return {"import_id": import_id, "status": status, "filename": filename,
            "retailer_id": profile.retailer_id, "profile_version": profile.version,
            "periode": periode_txt, "rows": len(result["facts"]),
            "detail": "; ".join(warnings) if warnings else None}
