"""Spoort dubbele feitregels op en ruimt ze op.

Nodig voor databases die zijn gevuld vóór de correctie-fix: tot dan zette een
herlevering van een al ingelezen periode zijn regels ERNAAST in plaats van de
oude te vervangen, waardoor het dashboard ze bij elkaar optelde.

Een dubbele regel is een tweede rij met dezelfde natuurlijke sleutel
(retailer, merk, land, banner, winkel, artikel, periode). De rij uit de
NIEUWSTE import is de geldige — dat is de correctie — de oudere gaan weg.

    python cleanup_duplicates.py            # toon wat er mis is
    python cleanup_duplicates.py --doen     # opruimen
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db

KEY = ("retailer_id", "merk", "land", "banner", "winkel_id", "artikel_ean", "periode")
GROUP = ", ".join(f"COALESCE({c}, '')" for c in KEY)


def main():
    ap = argparse.ArgumentParser(description="Dubbele feitregels opruimen")
    ap.add_argument("--doen", action="store_true", help="daadwerkelijk verwijderen")
    args = ap.parse_args()

    with db.get_conn() as conn:
        groups = conn.execute(f"""
            SELECT {GROUP} AS sleutel, COUNT(*) AS n,
                   SUM(omzet) AS omzet_totaal, MAX(import_id) AS nieuwste
              FROM sellout_facts
             GROUP BY {GROUP}
            HAVING COUNT(*) > 1
        """).fetchall()

        if not groups:
            print("Geen dubbele feitregels gevonden — de cijfers kloppen.")
            return

        overtollig = sum(g["n"] - 1 for g in groups)
        print(f"{len(groups)} combinatie(s) met dubbele regels, "
              f"{overtollig} regel(s) te veel.")

        # Wat dit betekent voor de cijfers, per retailer en periode. De rij met
        # het hoogste id is de laatst geïmporteerde en dus de geldige.
        impact = conn.execute(f"""
            SELECT retailer_id, periode,
                   SUM(omzet) AS nu,
                   SUM(CASE WHEN id IN (SELECT MAX(id) FROM sellout_facts
                                         GROUP BY {GROUP})
                            THEN omzet ELSE 0 END) AS straks
              FROM sellout_facts
             GROUP BY retailer_id, periode
             ORDER BY retailer_id, periode
        """).fetchall()
        for row in impact:
            if abs(row["nu"] - row["straks"]) < 0.005:
                continue
            print(f"  {row['retailer_id']:14} {row['periode']:9} "
                  f"nu € {row['nu']:>12,.2f}  ->  € {row['straks']:>12,.2f}")

        if not args.doen:
            print("\nNiets gewijzigd. Draai met --doen om op te ruimen; de regel "
                  "uit de nieuwste import blijft staan.")
            return

        cur = conn.execute(f"""
            DELETE FROM sellout_facts
             WHERE id NOT IN (
                SELECT MAX(id) FROM sellout_facts GROUP BY {GROUP})
        """)
        print(f"\n{cur.rowcount} dubbele regel(s) verwijderd; per combinatie is de "
              "regel uit de nieuwste import bewaard.")


if __name__ == "__main__":
    main()
