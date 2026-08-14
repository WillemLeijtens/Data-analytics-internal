"""Parser-profile model + capability derivation (PROMPT.md §3).

A profile's `definition` is JSON as in console/profiles/*.json. Capabilities
are ALWAYS derived from mapping + constants — never stored redundantly.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

CANONICAL_FIELDS = {
    "land", "banner", "winkel_id", "winkel_naam",
    "merk", "artikel_ean", "artikel_naam", "volume", "omzet",
}
REQUIRED_ALWAYS = {"volume", "omzet"}
PERIOD_FORMATS = {
    "week": {"yyyyww", "yyyy-Www"},
    "maand": {"mm-yyyy", "yyyy-mm", "yyyymm"},
}
NORMALIZERS = {None, "", "upper"}

# Ingebouwde parsers voor formaten die een kolom-mapping niet kán uitdrukken
# (zoals de echte Kruidvat DWH-export: metadatablok + weekkolommen naast
# elkaar). Een profiel met "builtin" gebruikt zo'n parser in plaats van de
# mapping; de capabilities liggen dan vast bij de parser.
BUILTIN_CAPS = {
    "kruidvat_dwh": {"periode": "week", "merk": True, "artikel": True,
                     "winkel": False, "banner": True, "land": True,
                     "volume": True},
    "ici_maandrapport": {"periode": "maand", "merk": True, "artikel": False,
                         "winkel": True, "banner": False, "land": True,
                         "volume": False},
}


@dataclass(frozen=True)
class Profile:
    id: int | None
    retailer_id: str
    version: int
    status: str          # concept | test | live
    definition: dict

    @classmethod
    def from_row(cls, row) -> "Profile":
        return cls(id=row["id"], retailer_id=row["retailer_id"], version=row["version"],
                   status=row["status"], definition=json.loads(row["definition"]))


def mapped_targets(definition: dict) -> set[str]:
    targets = {m["target"] for m in definition.get("mapping", []) if m.get("target")}
    targets |= set(definition.get("constants", {}).keys())
    return targets


def capabilities(definition: dict) -> dict:
    """Derive what a profile can deliver, purely from mapping + constants —
    or, for a builtin parser, from that parser's fixed capability set."""
    b = definition.get("builtin")
    if b in BUILTIN_CAPS:
        return dict(BUILTIN_CAPS[b])
    t = mapped_targets(definition)
    return {
        "periode": definition.get("period", {}).get("type", "week"),
        "merk": "merk" in t,
        "artikel": "artikel_ean" in t,
        "winkel": "winkel_id" in t,
        "banner": "banner" in t,
        "land": "land" in t,
        # Volume is verplicht bij mapping-profielen, dus daar altijd True;
        # de vlag bestaat voor ingebouwde parsers van feeds zonder volume.
        "volume": "volume" in t,
    }


def missing_required(definition: dict) -> set[str]:
    """Canonical fields that must be mapped for the profile to import at all:
    volume + omzet, plus the period source column."""
    if definition.get("builtin") in BUILTIN_CAPS:
        return set()
    missing = REQUIRED_ALWAYS - mapped_targets(definition)
    if not definition.get("period", {}).get("source_column"):
        missing.add("periode")
    return missing


def validate_definition(definition: dict, *, require_complete: bool = False) -> None:
    """Controleer profiel-JSON vóórdat het uitvoerbare configuratie wordt.

    Een concept mag bewust nog ongemapte velden hebben, maar de structuur
    eromheen moet veilig te inspecteren zijn. Test/live-profielen moeten
    compleet genoeg zijn om een bestand te kunnen importeren."""
    if not isinstance(definition, dict):
        raise ValueError("definitie moet een JSON-object zijn")
    builtin = definition.get("builtin")
    if builtin is not None and builtin not in BUILTIN_CAPS:
        raise ValueError(f"onbekende ingebouwde parser {builtin!r}")

    detection = definition.get("detection")
    if not isinstance(detection, dict):
        raise ValueError("detection ontbreekt of is geen object")
    if not isinstance(detection.get("filename_glob"), str) or not detection["filename_glob"].strip():
        raise ValueError("detection.filename_glob is verplicht")
    filetype = detection.get("filetype")
    if filetype not in ("csv", "xlsx"):
        raise ValueError("detection.filetype moet csv|xlsx zijn")
    try:
        if isinstance(detection.get("header_row"), bool) or int(detection.get("header_row")) < 1:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("detection.header_row moet een positief geheel getal zijn") from None
    required_headers = detection.get("required_headers")
    if not isinstance(required_headers, list) or any(
            not isinstance(h, str) or not h.strip() for h in required_headers):
        raise ValueError("detection.required_headers moet een lijst met kolomnamen zijn")
    folded_required = [h.strip().casefold() for h in required_headers]
    if len(folded_required) != len(set(folded_required)):
        raise ValueError("detection.required_headers bevat dubbele kolomnamen")
    if detection.get("decimal") not in (",", "."):
        raise ValueError("detection.decimal moet ',' of '.' zijn")
    if filetype == "csv" and not builtin:
        delimiter = detection.get("csv_delimiter")
        if not isinstance(delimiter, str) or len(delimiter) != 1:
            raise ValueError("detection.csv_delimiter moet precies één teken zijn")

    period = definition.get("period")
    if not isinstance(period, dict):
        raise ValueError("period ontbreekt of is geen object")
    period_type = period.get("type")
    if period_type not in PERIOD_FORMATS:
        raise ValueError("period.type moet week|maand zijn")
    if not builtin and period.get("format") not in PERIOD_FORMATS[period_type]:
        raise ValueError(f"period.format past niet bij period.type={period_type}")
    if not isinstance(period.get("source_column"), str):
        raise ValueError("period.source_column moet tekst zijn")

    mapping = definition.get("mapping")
    if not isinstance(mapping, list):
        raise ValueError("mapping moet een lijst zijn")
    source_names: set[str] = set()
    target_names: set[str] = set()
    for i, item in enumerate(mapping, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"mapping[{i}] moet een object zijn")
        source = item.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"mapping[{i}].source is verplicht")
        source_key = source.strip().casefold()
        if source_key in source_names:
            raise ValueError(f"bronkolom {source!r} is meer dan één keer gemapt")
        source_names.add(source_key)
        target = item.get("target")
        if target not in (None, ""):
            if target not in CANONICAL_FIELDS:
                raise ValueError(f"onbekend doelveld {target!r}")
            if target in target_names:
                raise ValueError(f"doelveld {target!r} is meer dan één keer gemapt")
            target_names.add(target)
        if item.get("normalize") not in NORMALIZERS:
            raise ValueError(f"onbekende normalisatie in mapping[{i}]")

    constants = definition.get("constants")
    if not isinstance(constants, dict):
        raise ValueError("constants moet een object zijn")
    bad_constants = set(constants) - CANONICAL_FIELDS
    if bad_constants:
        raise ValueError("onbekende constants: " + ", ".join(sorted(bad_constants)))
    overlap = target_names & set(constants)
    if overlap:
        raise ValueError("velden staan zowel in mapping als constants: " + ", ".join(sorted(overlap)))

    thresholds = definition.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise ValueError("thresholds moet een object zijn")
    promo_drop = thresholds.get("promo_price_drop", 0.05)
    if isinstance(promo_drop, bool) or not isinstance(promo_drop, (int, float)) \
            or not math.isfinite(float(promo_drop)) or not 0 <= float(promo_drop) <= 1:
        raise ValueError("thresholds.promo_price_drop moet tussen 0 en 1 liggen")

    if require_complete and not builtin:
        missing = missing_required(definition)
        if missing:
            raise ValueError("profiel mist verplichte velden: " + ", ".join(sorted(missing)))
        if not required_headers:
            raise ValueError("test/live-profiel vereist minimaal één required_header")


def get_profiles(conn, retailer_id: str | None = None, statuses=None) -> list[Profile]:
    sql = "SELECT * FROM parser_profiles"
    conds, params = [], []
    if retailer_id:
        conds.append("retailer_id = ?")
        params.append(retailer_id)
    if statuses:
        conds.append(f"status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY retailer_id, version DESC"
    return [Profile.from_row(r) for r in conn.execute(sql, params)]


def latest_profile(conn, retailer_id: str) -> Profile | None:
    rows = get_profiles(conn, retailer_id)
    return rows[0] if rows else None


def active_profile(conn, retailer_id: str) -> Profile | None:
    """Newest live profile, else newest test profile (facts flagged), else None."""
    for status in ("live", "test"):
        row = conn.execute(
            "SELECT * FROM parser_profiles WHERE retailer_id=? AND status=? ORDER BY version DESC LIMIT 1",
            (retailer_id, status)).fetchone()
        if row:
            return Profile.from_row(row)
    return None


def save_profile(conn, retailer_id: str, definition: dict, status: str) -> Profile:
    """Publishing = a NEW version; old versions stay readable."""
    validate_definition(definition, require_complete=status in ("test", "live"))
    cur = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM parser_profiles WHERE retailer_id=?",
        (retailer_id,)).fetchone()
    version = cur["v"] + 1
    definition = {**definition, "retailer_id": retailer_id, "version": version, "status": status}
    c = conn.execute(
        "INSERT INTO parser_profiles (retailer_id, version, status, definition, published_at) "
        "VALUES (?,?,?,?, CASE WHEN ?='live' THEN datetime('now') END)",
        (retailer_id, version, status, json.dumps(definition, ensure_ascii=False), status))
    return Profile(id=c.lastrowid, retailer_id=retailer_id, version=version,
                   status=status, definition=definition)
