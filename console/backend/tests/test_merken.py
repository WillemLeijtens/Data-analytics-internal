"""Merknamen gelijktrekken over feeds heen.

Kruidvat levert "DEPEND GEL IQ" (de productlijn), ICI levert "DEPEND" (het
merk), en in sommige Kruidvat-bestanden staan ze door elkaar. In de app waren
dat twee merken: twee filterchips, twee regels in de YTD-tabel, twee kleuren,
en geen vergelijking tussen retailers.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import merken  # noqa: E402
from test_parser_flow import upload  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for naam in ("db", "seed", "main"):
        sys.modules.pop(naam, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


@pytest.mark.parametrize("bron", [
    "DEPEND GEL IQ", "Depend Gel IQ", "  depend   gel   iq  ",
    "DEPEND GELIQ", "DEPEND GEL-IQ", "DEPEND", "depend",
])
def test_varianten_worden_een_merk(bron):
    assert merken.normaliseer(bron) == "DEPEND"


def test_onbekend_merk_blijft_bestaan():
    # Een merk mag niet verdwijnen omdat het niet in de lijst staat; alleen
    # spaties en hoofdletters worden gladgestreken.
    assert merken.normaliseer("  olivia   garden ") == "OLIVIA GARDEN"
    assert merken.normaliseer("BJÖRN AXÉN") == "BJÖRN AXÉN"
    assert merken.normaliseer(None) is None
    assert merken.normaliseer("   ") is None


def _kv(client, naam, merk, weken):
    import seed
    upload(client, naam, seed.make_dwh_xlsx(
        [{"sku": "6370075", "gtin": "4049469072773", "desc": "GEL IQ",
          "brand": merk, "weeks": weken}]))


def test_twee_schrijfwijzen_landen_op_een_merk(client):
    _kv(client, "a.xlsx", "DEPEND GEL IQ", {"202630": (10, 100.0)})
    _kv(client, "b.xlsx", "DEPEND", {"202631": (10, 150.0)})

    d = client.get("/api/kruidvat/dashboard").json()
    assert d["filters"]["merk"] == ["DEPEND"], "één chip, niet twee"

    import db
    with db.get_conn() as conn:
        merknamen = [r[0] for r in conn.execute(
            "SELECT DISTINCT merk FROM sellout_facts WHERE retailer_id='kruidvat'")]
    assert merknamen == ["DEPEND"]


def test_omzet_wordt_opgeteld_en_niet_overschreven(client):
    """Verschillende weken van hetzelfde merk mogen elkaar niet vervangen:
    de natuurlijke sleutel bevat het merk, dus normaliseren moet vóór het
    bepalen van wat vervangen wordt — anders verdwijnt de ene week."""
    _kv(client, "a.xlsx", "DEPEND GEL IQ", {"202630": (10, 100.0)})
    _kv(client, "b.xlsx", "DEPEND", {"202631": (10, 150.0)})

    import db
    with db.get_conn() as conn:
        totaal = conn.execute(
            "SELECT ROUND(SUM(omzet),2) FROM sellout_facts").fetchone()[0]
    assert totaal == pytest.approx(250.0)


def test_zelfde_week_onder_beide_namen_telt_niet_dubbel(client):
    """Levert een bestand dezelfde week onder de andere schrijfwijze, dan is
    dat een herlevering van dezelfde regel — geen tweede regel."""
    _kv(client, "a.xlsx", "DEPEND GEL IQ", {"202630": (10, 100.0)})
    _kv(client, "b.xlsx", "DEPEND", {"202630": (12, 120.0)})

    import db
    with db.get_conn() as conn:
        rijen = conn.execute(
            "SELECT COUNT(*), ROUND(SUM(omzet),2) FROM sellout_facts "
            "WHERE periode='2026-W30'").fetchone()
    assert tuple(rijen) == (1, 120.0), "de nieuwste levering vervangt de oude"


def test_migratie_voegt_bestaande_rijen_samen(client, tmp_path):
    """Rijen die er al stonden vóór de normalisatie. De migratie draait bij
    het opstarten; hier zetten we de oude toestand terug en draaien hem
    opnieuw, zodat het samenvoegen zelf getest wordt en niet alleen de
    parserkant."""
    _kv(client, "a.xlsx", "DEPEND", {"202630": (10, 100.0)})
    _kv(client, "b.xlsx", "DEPEND", {"202631": (10, 150.0)})

    import db
    # Terug naar de oude wereld: week 31 heet weer DEPEND GEL IQ.
    with db.get_conn() as conn:
        conn.execute("UPDATE sellout_facts SET merk='DEPEND GEL IQ' "
                     "WHERE periode='2026-W31'")
        conn.execute("DELETE FROM schema_migrations WHERE name LIKE '005%'")
    db.init_db()

    with db.get_conn() as conn:
        namen = [r[0] for r in conn.execute("SELECT DISTINCT merk FROM sellout_facts")]
        totaal = conn.execute("SELECT ROUND(SUM(omzet),2) FROM sellout_facts").fetchone()[0]
    assert namen == ["DEPEND"]
    assert totaal == pytest.approx(250.0), "omzet mag niet verdwijnen bij het hernoemen"


def test_migratie_telt_botsende_rijen_op(client):
    """Staat dezelfde week onder beide namen in de database, dan is het
    hetzelfde merk in dezelfde week: die omzet hoort opgeteld, niet half
    weggegooid."""
    _kv(client, "a.xlsx", "DEPEND", {"202630": (10, 100.0)})

    import db
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO sellout_facts (retailer_id, import_id, periode_type, periode, "
            "land, banner, merk, artikel_ean, volume, omzet) "
            "SELECT retailer_id, import_id, periode_type, periode, land, banner, "
            "'DEPEND GEL IQ', artikel_ean, volume, 40.0 FROM sellout_facts LIMIT 1")
        conn.execute("DELETE FROM schema_migrations WHERE name LIKE '005%'")
    db.init_db()

    with db.get_conn() as conn:
        rij = conn.execute(
            "SELECT COUNT(*), ROUND(SUM(omzet),2) FROM sellout_facts").fetchone()
    assert tuple(rij) == (1, 140.0)
