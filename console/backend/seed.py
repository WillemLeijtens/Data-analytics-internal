"""`make seed`: build the seed files in their REAL delivery format from the
CSV stand-ins in console/seed/, then push them through the actual import
pipeline (no direct inserts — this proves the parsers work, PROMPT §7).

Also loads the four handoff profiles verbatim, default settings and the
mock SharePoint contract documents.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
from engine import contracts, importer

BASE = Path(__file__).resolve().parents[1]          # console/
PROFILES = BASE / "profiles"
SEED = BASE / "seed"


def _read_standin(path: Path) -> tuple[list[str], list[list[str]]]:
    rows = [r for r in csv.reader(path.open(), delimiter=";")
            if r and not r[0].startswith("#")]
    return rows[0], rows[1:]


def _to_xlsx(headers, data, sheet: str, header_row: int, numeric_cols: dict) -> bytes:
    """numeric_cols: {header: 'int'|'float'} — floats came in as '7.180,00'."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for i in range(1, header_row):
        ws.cell(row=i, column=1,
                value=f"metadataregel {i}" if header_row > 2 else "")
    for c, h in enumerate(headers, start=1):
        ws.cell(row=header_row, column=c, value=h)
    for r, row in enumerate(data, start=header_row + 1):
        for c, (h, val) in enumerate(zip(headers, row), start=1):
            kind = numeric_cols.get(h)
            if kind == "int":
                val = int(val)
            elif kind == "float":
                val = float(val.replace(".", "").replace(",", "."))
            ws.cell(row=r, column=c, value=val)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_seed_files() -> list[tuple[str, bytes]]:
    files = []

    h, d = _read_standin(SEED / "kruidvat_DWH_sellout_TWEEZERMAN_NL_wk32.csv")
    files.append(("DWH_sellout_TWEEZERMAN_NL_wk32.xlsx",
                  _to_xlsx(h, d, "Sellout", 9,
                           {"Aantal": "int", "Omzet excl BTW": "float"})))

    h, d = _read_standin(SEED / "ici_ICIP_ALL_MTH_07_2026.csv")
    files.append(("ICIP_ALL_MTH_07_2026.xlsx",
                  _to_xlsx(h, d, "Data by store", 3,
                           {"Units": "int", "Net sales": "float"})))

    files.append(("etos_sales_wk32.csv", (SEED / "etos_sales_wk32.csv").read_bytes()))

    h, d = _read_standin(SEED / "douglas_Abverkauf_KW32.csv")
    files.append(("Douglas_Abverkauf_KW32.xlsx",
                  _to_xlsx(h, d, "Sheet1", 1,
                           {"Absatz": "int", "Umsatz": "float"})))
    return files


DEFAULT_SETTINGS = {
    "kruidvat": {
        "winkels_targets": [
            ("TWEEZERMAN", "NL", "KV", 912, 45.0),
            ("TWEEZERMAN", "NL", "TP", 410, 30.0),
            ("TWEEZERMAN", "BE", "KV", 214, 40.0),
        ],
        "rotatie": [("TWEEZERMAN", 8.0), ("ALESSANDRO", 6.0)],
        "mail": [("DWH weeklevering", "rapportage@kruidvat.nl", "DWH_sellout_*.xlsx")],
    },
    "etos": {
        "winkels_targets": [("TWEEZERMAN", "NL", None, 530, 35.0),
                            ("ALESSANDRO", "NL", None, 530, 25.0)],
        "rotatie": [("TWEEZERMAN", 6.0), ("ALESSANDRO", 5.0)],
        "mail": [("Etos salesreport", "data@etos.nl", "etos_sales_wk*.csv")],
    },
    "ici-paris-xl": {
        # aantal_winkels NULL: comes from the facts (readonly in the UI)
        "winkels_targets": [("TWEEZERMAN", "NL", None, None, 1500.0),
                            ("TWEEZERMAN", "BE", None, None, 1500.0),
                            ("ALESSANDRO", "NL", None, None, 900.0),
                            ("ALESSANDRO", "BE", None, None, 900.0)],
        "rotatie": [],
        "mail": [("ICI maandlevering", "reports@iciparisxl.be", "ICIP_*_MTH_*.xlsx")],
    },
}


def seed():
    db.init_db()
    with db.get_conn() as conn:
        # Profiles verbatim from the handoff (version/status as delivered).
        for path in sorted(PROFILES.glob("*.json")):
            d = json.loads(path.read_text())
            conn.execute(
                "INSERT OR IGNORE INTO parser_profiles (retailer_id, version, status, definition, "
                "published_at) VALUES (?,?,?,?, CASE WHEN ?='live' THEN datetime('now') END)",
                (d["retailer_id"], d["version"], d["status"],
                 json.dumps(d, ensure_ascii=False), d["status"]))

        for retailer, cfg in DEFAULT_SETTINGS.items():
            conn.executemany(
                "INSERT OR IGNORE INTO retailer_settings (retailer_id, merk, land, banner, "
                "aantal_winkels, target_per_winkel) VALUES (?,?,?,?,?,?)",
                [(retailer, *row) for row in cfg["winkels_targets"]])
            conn.executemany(
                "INSERT OR REPLACE INTO rotatie_targets (retailer_id, merk, stuks_per_winkel_per_week) "
                "VALUES (?,?,?)", [(retailer, *row) for row in cfg["rotatie"]])
            for naam, afzender, glob in cfg["mail"]:
                if not conn.execute("SELECT 1 FROM mail_rules WHERE retailer_id=? AND naam=?",
                                    (retailer, naam)).fetchone():
                    conn.execute(
                        "INSERT INTO mail_rules (retailer_id, naam, afzender, bijlage_glob) "
                        "VALUES (?,?,?,?)", (retailer, naam, afzender, glob))

        # SharePoint: link + interpret documents for retailers present in contracts.json.
        doclist = json.loads((SEED / "contracts.json").read_text())
        for retailer in doclist:
            conn.execute(
                "INSERT INTO sharepoint_links (retailer_id, map_url) VALUES (?,?) "
                "ON CONFLICT(retailer_id) DO UPDATE SET map_url=excluded.map_url",
                (retailer, f"https://leijtens.sharepoint.com/sites/retail/{retailer}/contracten"))
            contracts.sync_documents(conn, retailer)

        results = [importer.run_import(conn, name, content)
                   for name, content in build_seed_files()]

    for r in results:
        print(f"[seed] {r['filename']}: {r['status']} "
              f"({r['rows']} rijen, retailer={r['retailer_id']})")
    statuses = {r["filename"]: r["status"] for r in results}
    assert statuses["DWH_sellout_TWEEZERMAN_NL_wk32.xlsx"] == "ingelezen", statuses
    assert statuses["ICIP_ALL_MTH_07_2026.xlsx"] == "ingelezen", statuses
    assert statuses["etos_sales_wk32.csv"] == "test", statuses
    assert statuses["Douglas_Abverkauf_KW32.xlsx"] == "profiel_nodig", statuses
    print("[seed] klaar — alle verwachte statussen kloppen")


if __name__ == "__main__":
    seed()
