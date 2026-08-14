"""Verwijdert demo-/voorbeelddata uit een bestaande console-database.

Veilig ontworpen: alleen rijen die EXACT overeenkomen met de bekende
demo-waarden worden verwijderd. Heb je een winkelaantal of target zelf
aangepast, dan blijft die rij staan. Geïmporteerde verkoopcijfers uit echte
bestanden worden nooit aangeraakt; demo-imports (herkenbaar aan hun
bestandsnaam) wel.

    python cleanup_demo.py            # toon wat er verwijderd zou worden
    python cleanup_demo.py --doen     # daadwerkelijk verwijderen
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
from seed import DEMO_SETTINGS, SEED

# Demowaarden die eerdere versies hebben aangemaakt maar die niet meer in
# DEMO_SETTINGS staan (Etos verloor zijn profiel, ICI kreeg een ander
# bijlage-patroon). Zonder deze lijst wordt het script blind voor precies de
# rijen die het zou moeten opruimen.
LEGACY_DEMO_SETTINGS = {
    "etos": {
        "winkels_targets": [("TWEEZERMAN", "NL", None, 530, 35.0),
                            ("ALESSANDRO", "NL", None, 530, 25.0)],
        "rotatie": [("TWEEZERMAN", 6.0), ("ALESSANDRO", 5.0)],
        "mail": [("Etos salesreport", "data@etos.nl", "etos_sales_wk*.csv")],
    },
    "ici-paris-xl": {
        "winkels_targets": [],
        "rotatie": [],
        "mail": [("ICI maandlevering", "reports@iciparisxl.be", "ICIP_*_MTH_*.xlsx")],
    },
}

DEMO_SHAREPOINT_PREFIX = "https://leijtens.sharepoint.com/sites/retail/"
DEMO_FILE_MARKERS = ("_demo.xlsx", "etos_sales_wk", "Douglas_Abverkauf_KW",
                     "ICIP_ALL_MTH_", "DWH_sellout_TWEEZERMAN_NL_wk",
                     "Maandelijkse_resultaten__Tweezerman__Depend_ICI_Paris_XL__20")


def _all_demo_settings() -> dict:
    """Huidige + historische demowaarden, samengevoegd per retailer."""
    merged: dict = {}
    for source in (DEMO_SETTINGS, LEGACY_DEMO_SETTINGS):
        for retailer, cfg in source.items():
            target = merged.setdefault(
                retailer, {"winkels_targets": [], "rotatie": [], "mail": []})
            for key in target:
                for row in cfg.get(key, []):
                    if row not in target[key]:
                        target[key].append(row)
    return merged


def _demo_rows():
    """(tabel, waar-clausule, params) per soort demo-rij."""
    out = []
    for retailer, cfg in _all_demo_settings().items():
        for merk, land, banner, winkels, target in cfg["winkels_targets"]:
            out.append((
                "retailer_settings",
                "retailer_id=? AND merk=? AND land=? AND banner IS ? AND "
                "aantal_winkels IS ? AND target_per_winkel IS ?",
                (retailer, merk, land, banner, winkels, target)))
        for merk, stuks in cfg["rotatie"]:
            out.append((
                "rotatie_targets",
                "retailer_id=? AND merk=? AND stuks_per_winkel_per_week=?",
                (retailer, merk, stuks)))
        for naam, afzender, glob in cfg["mail"]:
            out.append((
                "mail_rules",
                "retailer_id=? AND naam=? AND afzender IS ? AND bijlage_glob IS ?",
                (retailer, naam, afzender, glob)))
    return out


def main():
    ap = argparse.ArgumentParser(description="Demo-data uit de console verwijderen")
    ap.add_argument("--doen", action="store_true", help="daadwerkelijk verwijderen")
    args = ap.parse_args()

    verwijderd: dict[str, int] = {}

    def tel(tabel: str, n: int):
        if n:
            verwijderd[tabel] = verwijderd.get(tabel, 0) + n

    with db.get_conn() as conn:
        for tabel, waar, params in _demo_rows():
            n = conn.execute(f"SELECT COUNT(*) c FROM {tabel} WHERE {waar}",
                             params).fetchone()["c"]
            tel(tabel, n)
            if n and args.doen:
                conn.execute(f"DELETE FROM {tabel} WHERE {waar}", params)

        # SharePoint-koppeling + de daaruit afgeleide contractdocumenten.
        links = conn.execute(
            "SELECT retailer_id FROM sharepoint_links WHERE map_url LIKE ?",
            (DEMO_SHAREPOINT_PREFIX + "%",)).fetchall()
        demo_docs = {r["naam"] for docs in json.loads(
            (SEED / "contracts.json").read_text()).values() for r in docs}
        for row in links:
            r = row["retailer_id"]
            n = conn.execute(
                "SELECT COUNT(*) c FROM contract_documents WHERE retailer_id=?",
                (r,)).fetchone()["c"]
            tel("contract_documents", n)
            tel("sharepoint_links", 1)
            if args.doen:
                conn.execute("DELETE FROM contract_documents WHERE retailer_id=? AND naam IN "
                             f"({','.join('?' * len(demo_docs))})", (r, *demo_docs))
                conn.execute("DELETE FROM sharepoint_links WHERE retailer_id=?", (r,))

        # Demo-imports (en hun feiten) — echte bestanden blijven staan.
        for marker in DEMO_FILE_MARKERS:
            rows = conn.execute("SELECT id, filename FROM imports WHERE filename LIKE ?",
                                (f"%{marker}%",)).fetchall()
            for row in rows:
                n = conn.execute("SELECT COUNT(*) c FROM sellout_facts WHERE import_id=?",
                                 (row["id"],)).fetchone()["c"]
                tel("sellout_facts", n)
                tel("imports", 1)
                if args.doen:
                    conn.execute("DELETE FROM sellout_facts WHERE import_id=?", (row["id"],))
                    conn.execute("DELETE FROM imports WHERE id=?", (row["id"],))

        # Profielen uit het ontwerppakket (fictieve formaten, geen builtin).
        for row in conn.execute("SELECT id, retailer_id, version, definition FROM parser_profiles"):
            d = json.loads(row["definition"])
            if not d.get("builtin"):
                tel("parser_profiles", 1)
                if args.doen:
                    conn.execute("DELETE FROM parser_profiles WHERE id=?", (row["id"],))

    if not verwijderd:
        print("Geen demo-data gevonden — de database bevat alleen eigen gegevens.")
        return
    kop = "Verwijderd:" if args.doen else "Zou verwijderd worden (gebruik --doen):"
    print(kop)
    for tabel, n in sorted(verwijderd.items()):
        print(f"  {tabel}: {n}")
    if not args.doen:
        print("\nEigen aanpassingen blijven staan: alleen exact overeenkomende "
              "demo-waarden tellen mee.")


if __name__ == "__main__":
    main()
