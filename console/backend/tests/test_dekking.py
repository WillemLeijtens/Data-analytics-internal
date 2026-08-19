"""Waarschuwen als een feed niet compleet is.

Van DEPEND kwam voor België vanaf week 3 niets meer binnen. De artikel- en
assortimentsanalyse telden die weken als nul mee: een artikel dat in BE prima
liep zag eruit als een artikel dat instortte. Deze tests pinnen vast dat zo'n
gat gemeld wordt, in gewone taal, en alleen bij de artikelen die het aangaat.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import dekking  # noqa: E402
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


def _kv(client, naam, land, weken, sku="111", merk="DEPEND"):
    import seed
    upload(client, naam, seed.make_dwh_xlsx(
        [{"sku": sku, "gtin": "404946907" + sku[-3:], "desc": f"ART {sku}",
          "brand": merk, "weeks": {f"2026{w:02d}": (10, 100.0) for w in weken}}],
        country3=land, formula="KV"))


def _teksten(rij):
    return [g["tekst"] for g in rij["dekking"]]


# ------------------------------------------------------------ de kernregel

def test_land_dat_stopt_wordt_gemeld_bij_de_juiste_artikelen(client):
    _kv(client, "nl.xlsx", "NLD", range(1, 11), sku="111")
    _kv(client, "be.xlsx", "BEL", range(1, 3), sku="111")   # stopt na week 2
    _kv(client, "nl2.xlsx", "NLD", range(1, 11), sku="222")  # alleen NL

    data = client.get("/api/kruidvat/artikelen").json()
    assert [g["tekst"] for g in data["dekking"]] == \
        ["vanaf week 3 geen data voor België"]

    per_ean = {a["ean"]: a for a in data["artikelen"]}
    assert _teksten(per_ean["404946907111"]) == ["vanaf week 3 geen data voor België"]
    # Dit artikel is nooit in BE verkocht; een BE-melding zegt er niets over.
    assert _teksten(per_ean["404946907222"]) == []


def test_land_dat_later_begint(client):
    _kv(client, "nl.xlsx", "NLD", range(1, 11), sku="111")
    _kv(client, "be.xlsx", "BEL", range(5, 11), sku="111")

    data = client.get("/api/kruidvat/artikelen").json()
    assert [g["tekst"] for g in data["dekking"]] == \
        ["geen data voor België vóór week 5"]


def test_gat_midden_in_de_reeks(client):
    _kv(client, "nl.xlsx", "NLD", range(1, 11), sku="111")
    _kv(client, "be.xlsx", "BEL", [1, 2, 3, 4, 5, 8, 9, 10], sku="111")

    data = client.get("/api/kruidvat/artikelen").json()
    assert [g["tekst"] for g in data["dekking"]] == \
        ["geen data voor België in week 6 en 7"]


def test_volledige_aanlevering_geeft_geen_waarschuwing(client):
    _kv(client, "nl.xlsx", "NLD", range(1, 11), sku="111")
    _kv(client, "be.xlsx", "BEL", range(1, 11), sku="111")

    data = client.get("/api/kruidvat/artikelen").json()
    assert data["dekking"] == []
    assert all(not a["dekking"] for a in data["artikelen"])


def test_een_enkele_scope_meldt_niets(client):
    """Met één land is er niets om tegen af te zetten: dat de feed in week 10
    ophoudt betekent dan gewoon dat de data tot week 10 loopt."""
    _kv(client, "nl.xlsx", "NLD", range(1, 11), sku="111")
    data = client.get("/api/kruidvat/artikelen").json()
    assert data["dekking"] == []


def test_assortiment_meldt_hetzelfde(client):
    _kv(client, "nl.xlsx", "NLD", range(1, 11), sku="111")
    _kv(client, "be.xlsx", "BEL", range(1, 3), sku="111")

    data = client.get("/api/kruidvat/assortiment").json()
    assert [g["tekst"] for g in data["dekking"]] == \
        ["vanaf week 3 geen data voor België"]
    assert _teksten(data["artikelen"][0]) == ["vanaf week 3 geen data voor België"]


# ------------------------------------------------------------- formulering

def test_maandfeed_zegt_maand():
    caps = {"periode": "maand", "banner": False}
    rows = [{"merk": "DEPEND", "land": "NL", "banner": None, "periode": f"2026-{m:02d}"} for m in range(1, 8)]
    rows += [{"merk": "DEPEND", "land": "BE", "banner": None, "periode": f"2026-{m:02d}"} for m in (1, 2)]
    assert [g["tekst"] for g in dekking.gaten(rows, caps)] == \
        ["vanaf maand 3 geen data voor België"]


def test_formule_wordt_genoemd_als_er_meer_zijn():
    caps = {"periode": "week", "banner": True}
    rows = [{"merk": "DEPEND", "land": "NL", "banner": "KV", "periode": f"2026-W{w:02d}"} for w in range(1, 6)]
    rows += [{"merk": "DEPEND", "land": "NL", "banner": "TP", "periode": f"2026-W{w:02d}"} for w in (1, 2)]
    assert [g["tekst"] for g in dekking.gaten(rows, caps)] == \
        ["vanaf week 3 geen data voor TP in Nederland"]


def test_onbekende_landcode_blijft_staan():
    caps = {"periode": "week", "banner": False}
    rows = [{"merk": "DEPEND", "land": "NL", "banner": None, "periode": f"2026-W{w:02d}"} for w in range(1, 6)]
    rows += [{"merk": "DEPEND", "land": "XX", "banner": None, "periode": "2026-W01"}]
    tekst = [g["tekst"] for g in dekking.gaten(rows, caps)]
    assert tekst == ["vanaf week 2 geen data voor XX"]


def test_alleen_het_laatste_jaar_telt():
    """Een land dat vorig jaar anders liep zegt niets over de cijfers van nu;
    de analyses rekenen over het laatste jaar."""
    caps = {"periode": "week", "banner": False}
    rows = [{"merk": "DEPEND", "land": "NL", "banner": None, "periode": f"2025-W{w:02d}"} for w in range(1, 6)]
    rows += [{"merk": "DEPEND", "land": "NL", "banner": None, "periode": f"2026-W{w:02d}"} for w in range(1, 6)]
    rows += [{"merk": "DEPEND", "land": "BE", "banner": None, "periode": f"2026-W{w:02d}"} for w in range(1, 6)]
    assert dekking.gaten(rows, caps) == []


# ------------------------------------------------------- merk-dimensie

def test_merkfeed_die_achterloopt_wordt_gemeld(client):
    """Merken komen in aparte bestanden met een eigen ritme binnen. Een
    merk-feed die weken achterloopt was onzichtbaar zolang een ander merk
    hetzelfde land vulde (TWEEZERMAN liep 15 weken achter op de echte
    Kruidvat-bestanden, zonder één melding)."""
    _kv(client, "al.xlsx", "NLD", range(1, 11), sku="111", merk="ALESSANDRO")
    _kv(client, "tw.xlsx", "NLD", range(1, 5), sku="222", merk="TWEEZERMAN")

    data = client.get("/api/kruidvat/artikelen").json()
    assert [g["tekst"] for g in data["dekking"]] == \
        ["vanaf week 5 geen data voor TWEEZERMAN in Nederland"]
    per_ean = {a["ean"]: a for a in data["artikelen"]}
    # Alleen het artikel van het achterlopende merk draagt de melding.
    assert _teksten(per_ean["404946907222"]) == \
        ["vanaf week 5 geen data voor TWEEZERMAN in Nederland"]
    assert _teksten(per_ean["404946907111"]) == []


def test_een_periode_achterstand_is_normale_cadans(client):
    """België levert structureel één week na Nederland. Dat elke week als
    rood gat melden went de gebruiker aan het negeren van de driehoek."""
    _kv(client, "nl.xlsx", "NLD", range(1, 11), sku="111")
    _kv(client, "be.xlsx", "BEL", range(1, 10), sku="111")   # één week achter

    data = client.get("/api/kruidvat/artikelen").json()
    assert data["dekking"] == []


def test_twee_periodes_achterstand_wordt_wel_gemeld(client):
    _kv(client, "nl.xlsx", "NLD", range(1, 11), sku="111")
    _kv(client, "be.xlsx", "BEL", range(1, 9), sku="111")    # twee weken achter

    data = client.get("/api/kruidvat/artikelen").json()
    assert [g["tekst"] for g in data["dekking"]] == \
        ["vanaf week 9 geen data voor België"]


# ------------------------------------------------------- per-feed versheid

def test_import_status_toont_achterstand_per_feed(client):
    """Eén merk dat weken achterloopt hoort op Import status rood te staan,
    ook als een ander merk actueel is."""
    _kv(client, "al.xlsx", "NLD", range(1, 11), sku="111", merk="ALESSANDRO")
    _kv(client, "tw.xlsx", "NLD", range(1, 5), sku="222", merk="TWEEZERMAN")

    feeds = {f["feed"]: f for r in client.get("/api/import-status").json()
             for f in r["feeds"]}
    # Absolute achterstand hangt van de kalender af; het verschíl niet.
    assert feeds["TWEEZERMAN"]["achter"] - feeds["ALESSANDRO"]["achter"] == 6
    assert feeds["TWEEZERMAN"]["achter"] > 4
    assert feeds["TWEEZERMAN"]["signaal"] == "red"
