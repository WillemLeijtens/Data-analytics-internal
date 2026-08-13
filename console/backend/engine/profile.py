"""Parser-profile model + capability derivation (PROMPT.md §3).

A profile's `definition` is JSON as in console/profiles/*.json. Capabilities
are ALWAYS derived from mapping + constants — never stored redundantly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CANONICAL_FIELDS = {
    "land", "banner", "winkel_id", "winkel_naam",
    "merk", "artikel_ean", "artikel_naam", "volume", "omzet",
}
REQUIRED_ALWAYS = {"volume", "omzet"}


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
    """Derive what a profile can deliver, purely from mapping + constants."""
    t = mapped_targets(definition)
    return {
        "periode": definition.get("period", {}).get("type", "week"),
        "merk": "merk" in t,
        "artikel": "artikel_ean" in t,
        "winkel": "winkel_id" in t,
        "banner": "banner" in t,
        "land": "land" in t,
    }


def missing_required(definition: dict) -> set[str]:
    """Canonical fields that must be mapped for the profile to import at all:
    volume + omzet, plus the period source column."""
    missing = REQUIRED_ALWAYS - mapped_targets(definition)
    if not definition.get("period", {}).get("source_column"):
        missing.add("periode")
    return missing


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
