"""Meerjarige gaten: een jaar dat helemaal ontbreekt tussen twee leveringen.

engine/dekking.py kijkt alleen binnen het LAATSTE jaar (het filtert daar
eerst op). Een merk met doorverkoop in 2024, niets in 2025 en weer wel in
2026 valt daar structureel buiten — precies het geval waarvoor deze module
bestaat.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import datagaten, dekking  # noqa: E402
from test_parser_flow import upload  # noqa: E402

CAPS = {"periode": "week", "merk": True, "banner": False}


class Rij(dict):
    def __getitem__(self, k):
        return dict.get(self, k)


def feit(jaar, week, merk, land="NL"):
    return Rij(periode=f"{jaar}-W{week:02d}", merk=merk, land=land, banner=None)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for name in ("db", "seed", "main"):
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


# ------------------------------------------------------------ detectie

def test_ontbrekend_middenjaar_wordt_gevonden():
    """Het geval uit de vraag: 2024 wel, 2025 niet, 2026 weer wel."""
    rows = ([feit(2024, w, "TWEEZERMAN") for w in (10, 20)]
            + [feit(2026, w, "TWEEZERMAN") for w in (10, 20)]
            # Een tweede merk houdt 2025 op de retailer-as: het jaar bestaat.
            + [feit(2025, w, "ALESSANDRO") for w in (10, 20)]
            + [feit(2024, 10, "ALESSANDRO"), feit(2026, 10, "ALESSANDRO")])
    gaten = datagaten.vind(rows, CAPS)
    tweezer = [g for g in gaten if g["merk"] == "TWEEZERMAN"]
    assert len(tweezer) == 1
    assert (tweezer[0]["van_jaar"], tweezer[0]["tot_jaar"]) == (2025, 2025)
    assert "2025" in tweezer[0]["tekst"]
    # ALESSANDRO leverde elk jaar: geen gat.
    assert [g for g in gaten if g["merk"] == "ALESSANDRO"] == []


def test_dekking_ziet_dit_gat_niet():
    """Vastleggen waaróm deze module bestaat: dekking.py filtert eerst op het
    laatste jaar en kan een heel ontbrekend jaar dus niet zien."""
    rows = ([feit(2024, 10, "TWEEZERMAN"), feit(2026, 10, "TWEEZERMAN")]
            + [feit(2025, 10, "ALESSANDRO"), feit(2026, 10, "ALESSANDRO")])
    meerjarig = [g for g in datagaten.vind(rows, CAPS) if g["merk"] == "TWEEZERMAN"]
    assert meerjarig, "de nieuwe module hoort dit gat wél te vinden"
    binnen_jaar = [g for g in dekking.gaten(rows, CAPS) if g.get("merk") == "TWEEZERMAN"]
    assert not any(g["soort"] == "onderbroken" for g in binnen_jaar)


def test_begin_en_einde_zijn_geen_gat():
    """Vóór de eerste levering bestaat het merk nog niet, ná de laatste is het
    gestopt. Dat is een begin en een einde, geen gat — en de analyse vertelt
    dat zelf al."""
    rows = ([feit(2024, 10, "OUD"), feit(2025, 10, "OUD")]        # stopt na 2025
            + [feit(2025, 10, "NIEUW"), feit(2026, 10, "NIEUW")]  # begint in 2025
            + [feit(2024, 10, "VAST"), feit(2025, 10, "VAST"), feit(2026, 10, "VAST")])
    assert datagaten.vind(rows, CAPS) == []


def test_twee_losse_gaten_zijn_twee_meldingen():
    rows = ([feit(j, 10, "SPRING") for j in (2021, 2023, 2025)]
            + [feit(j, 10, "VAST") for j in (2021, 2022, 2023, 2024, 2025)])
    gaten = [g for g in datagaten.vind(rows, CAPS) if g["merk"] == "SPRING"]
    assert [(g["van_jaar"], g["tot_jaar"]) for g in gaten] == [(2022, 2022), (2024, 2024)]


def test_aaneengesloten_gat_is_een_melding():
    rows = ([feit(j, 10, "WEG") for j in (2021, 2025)]
            + [feit(j, 10, "VAST") for j in (2021, 2022, 2023, 2024, 2025)])
    gaten = [g for g in datagaten.vind(rows, CAPS) if g["merk"] == "WEG"]
    assert len(gaten) == 1
    assert (gaten[0]["van_jaar"], gaten[0]["tot_jaar"]) == (2022, 2024)


def test_jaar_dat_niemand_leverde_is_geen_gat():
    """Als de hele retailer dat jaar niets leverde, liep de samenwerking daar
    niet — dat is geen gat in dít merk."""
    rows = [feit(2024, 10, "A"), feit(2026, 10, "A"),
            feit(2024, 10, "B"), feit(2026, 10, "B")]
    assert datagaten.vind(rows, CAPS) == []


# ------------------------------------------------------------ oordeel

def _laad_gat(client):
    """Kruidvat met 2025 ontbrekend voor TWEEZERMAN."""
    import seed

    def kv(merk, sku, gtin, jaar, weken):
        return seed.make_dwh_xlsx([{
            "sku": sku, "gtin": gtin, "desc": merk, "brand": merk,
            "weeks": {f"{jaar}{w:02d}": (10, 100.0) for w in weken}}])

    for jaar in (2024, 2026):
        upload(client, f"DWH__Sales_TWEEZERMAN_KVNL_{jaar}.xlsx",
               kv("TWEEZERMAN", "31210001", "4049469072773", jaar, [10, 20]))
    for jaar in (2024, 2025, 2026):
        upload(client, f"DWH__Sales_ALESSANDRO_KVNL_{jaar}.xlsx",
               kv("ALESSANDRO", "31210002", "4049469072774", jaar, [10, 20]))


def _oordeel(gat, **extra):
    """Het scherm stuurt de scope terug die het kreeg — inclusief banner. Dat
    hier ook doen, anders beoordeel je een gat dat niet bestaat."""
    body = {k: gat[k] for k in ("merk", "land", "banner", "van_jaar", "tot_jaar")}
    body.update(extra)
    return body


def test_endpoint_meldt_gat_en_bewaart_oordeel(client):
    _laad_gat(client)
    r = client.get("/api/kruidvat/datagaten").json()
    assert r["beschikbaar"]
    gat = next(g for g in r["gaten"] if g["merk"] == "TWEEZERMAN")
    assert (gat["van_jaar"], gat["tot_jaar"]) == (2025, 2025)
    assert gat["oordeel"] is None, "een vers gat is nog niet beoordeeld"

    ok = client.put("/api/kruidvat/datagaten", json=_oordeel(
        gat, oordeel="klopt", toelichting="merk lag dat jaar niet bij Kruidvat",
        door="Willem"))
    assert ok.status_code == 200

    na = client.get("/api/kruidvat/datagaten").json()
    gat2 = next(g for g in na["gaten"] if g["merk"] == "TWEEZERMAN")
    assert gat2["oordeel"] == "klopt"
    assert gat2["toelichting"] == "merk lag dat jaar niet bij Kruidvat"
    assert gat2["beoordeeld_door"] == "Willem"


def test_oordeel_kan_herzien_worden(client):
    _laad_gat(client)
    gat = next(g for g in client.get("/api/kruidvat/datagaten").json()["gaten"]
               if g["merk"] == "TWEEZERMAN")
    for oordeel in ("klopt", "klopt_niet"):
        client.put("/api/kruidvat/datagaten", json=_oordeel(gat, oordeel=oordeel))
    gaten = client.get("/api/kruidvat/datagaten").json()["gaten"]
    tweezer = [g for g in gaten if g["merk"] == "TWEEZERMAN"]
    assert len(tweezer) == 1, "herzien mag geen tweede oordeel opleveren"
    assert tweezer[0]["oordeel"] == "klopt_niet"


def test_onbekend_oordeel_wordt_geweigerd(client):
    _laad_gat(client)
    gat = next(g for g in client.get("/api/kruidvat/datagaten").json()["gaten"]
               if g["merk"] == "TWEEZERMAN")
    r = client.put("/api/kruidvat/datagaten", json=_oordeel(gat, oordeel="misschien"))
    assert r.status_code == 422
