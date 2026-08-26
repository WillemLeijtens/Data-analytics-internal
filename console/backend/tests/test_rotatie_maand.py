"""De rotatie in de assortimentsanalyse rekent over de HUIDIGE MAAND.

Over het hele jaar middelen verbergt precies waar het om gaat: een artikel
dat in het voorjaar goed liep en sinds de zomer stilstaat, houdt een net
jaargemiddelde en valt nergens op. Over de laatste maand valt hij meteen door
de mand.

Twee dingen worden hier vastgepind:

  * het aantal weken komt uit de DATA, niet uit de kalender — is er van
    augustus pas twee weken geleverd, dan wordt door twee gedeeld;
  * de noemer is het winkelaantal van het artikel zelf als dat is ingesteld,
    anders het merkaantal, en het scherm meldt welk van de twee het is.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.periods import kalendermaand, maand_label  # noqa: E402
from test_parser_flow import upload  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for name in ("db", "seed", "main"):
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def _upload(client, artikelen):
    import seed
    upload(client, "kv.xlsx", seed.make_dwh_xlsx(artikelen))


def _art(sku, gtin, weeks, brand="TWEEZERMAN"):
    return {"sku": sku, "gtin": gtin, "desc": f"Artikel {sku}",
            "brand": brand, "weeks": weeks}


def _instel(client, aantal=100, target=1.0, artikelen=None):
    client.put("/api/kruidvat/instellingen", json={
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": aantal,
                             "niveau": "artikel" if artikelen else "merk"}],
        "artikel_winkels": artikelen or [],
        "rotatie_targets": [{"merk": "TWEEZERMAN", "stuks_per_winkel_per_week": target}]})


def _per_ean(client):
    return {a["ean"]: a for a in
            client.get("/api/kruidvat/assortiment").json()["artikelen"]}


# ------------------------------------------------------------ de maandgrens

def test_week_hoort_bij_de_maand_van_zijn_donderdag():
    """Een ISO-week ligt vaak in twee maanden. De donderdag beslist — dat is
    dezelfde regel als de ISO-jaartelling en de maand met de meeste dagen."""
    # Week 5 van 2026 loopt van 26 januari t/m 1 februari: donderdag 29
    # januari, dus januari.
    assert kalendermaand("2026-W05") == (2026, 1)
    assert kalendermaand("2026-W06") == (2026, 2)
    assert kalendermaand("2026-08") == (2026, 8)
    assert maand_label((2026, 8)) == "augustus 2026"


# --------------------------------------------------------- de rekenregel zelf

def test_rotatie_rekent_alleen_over_de_laatste_maand(client):
    """Week 1 t/m 5 (januari) draaide 500 stuks per week, week 6 en 7
    (februari) nog 50. Het jaargemiddelde zou 371 zijn en ruim op target
    uitkomen; over februari is het 0,5 en dus onder target."""
    januari = {f"2026{w:02d}": (500, 5000.0) for w in range(1, 6)}
    februari = {f"2026{w:02d}": (50, 500.0) for w in range(6, 8)}
    _upload(client, [_art("31210001", "4049469072773", {**januari, **februari})])
    _instel(client, aantal=100, target=1.0)

    a = _per_ean(client)["31210001"]
    # 100 stuks over twee weken, 100 winkels -> 0,5 per winkel per week.
    assert a["rotatie"] == pytest.approx(0.5)
    assert a["maand_weken"] == 2
    assert a["maand_volume"] == 100
    assert a["score"] == 50
    assert a["advies"] == "Mogelijke delist"


def test_deelt_door_de_geleverde_weken_niet_door_de_kalendermaand(client):
    """Van februari is pas de helft geleverd. Door 4,33 weken delen zou de
    rotatie halveren en een gezond artikel als delist wegzetten."""
    _upload(client, [_art("31210001", "4049469072773",
                          {f"2026{w:02d}": (100, 1000.0) for w in range(1, 8)})])
    _instel(client, aantal=100, target=1.0)

    a = _per_ean(client)["31210001"]
    assert a["maand_weken"] == 2                 # week 6 en 7, niet 4,33
    assert a["rotatie"] == pytest.approx(1.0)
    assert a["advies"] == "Op target"


def test_de_maand_staat_in_het_antwoord(client):
    _upload(client, [_art("31210001", "4049469072773",
                          {f"2026{w:02d}": (100, 1000.0) for w in range(1, 8)})])
    maand = client.get("/api/kruidvat/assortiment").json()["maand"]
    assert maand["label"] == "februari 2026"
    assert maand["periodes"] == ["2026-W06", "2026-W07"]
    assert maand["weken"] == 2


def test_geen_verkoop_deze_maand_is_een_eigen_oordeel(client):
    """Nul stuks deze maand is de scherpste delist-aanwijzing die er is, maar
    "Mogelijke delist" verklaart niet waarom. Het oordeel telt wel gewoon mee
    in de delist-teller."""
    _upload(client, [
        _art("31210001", "4049469072773",
             {f"2026{w:02d}": (100, 1000.0) for w in range(1, 8)}),
        # Stopt na week 5: in februari geen enkele verkoop meer.
        _art("31210002", "4049469072774",
             {f"2026{w:02d}": (100, 1000.0) for w in range(1, 6)})])
    _instel(client, aantal=100, target=1.0)

    data = client.get("/api/kruidvat/assortiment").json()
    per = {a["ean"]: a for a in data["artikelen"]}
    assert per["31210002"]["rotatie"] == 0
    assert per["31210002"]["advies"] == "Geen verkoop deze maand"
    assert data["stats"]["delist"] == 1
    assert per["31210001"]["advies"] == "Op target"


def test_een_enkele_week_levert_nog_geen_oordeel(client):
    """Eén geleverde week in de nieuwe maand is voor een langzame loper geen
    bewijs; het cijfer is wel te zien, het oordeel wordt uitgesteld."""
    _upload(client, [_art("31210001", "4049469072773",
                          {f"2026{w:02d}": (100, 1000.0) for w in range(1, 7)})])
    _instel(client, aantal=100, target=1.0)

    a = _per_ean(client)["31210001"]
    assert a["maand_weken"] == 1
    assert a["rotatie"] == pytest.approx(1.0)
    assert a["score"] is None
    assert a["advies"] == "Nog te weinig weken deze maand"


def test_introductie_halverwege_de_maand_wordt_niet_verdund(client):
    """Een artikel dat in week 7 startte, mag niet door de hele maand gedeeld
    worden: dan telt de week waarin het nog niet in het schap lag mee als een
    week zonder verkoop."""
    _upload(client, [
        _art("31210001", "4049469072773",
             {f"2026{w:02d}": (100, 1000.0) for w in range(1, 9)}),
        _art("31210002", "4049469072774",
             {f"2026{w:02d}": (100, 1000.0) for w in range(7, 9)})])
    _instel(client, aantal=100, target=1.0)

    per = _per_ean(client)
    # Het oude artikel rekent over week 6 t/m 8, het nieuwe alleen over 7 en 8.
    assert per["31210001"]["maand_weken"] == 3
    assert per["31210002"]["maand_weken"] == 2
    assert per["31210002"]["rotatie"] == pytest.approx(1.0)


# ------------------------------------------------------- waar de noemer vandaan komt

def test_meldt_of_de_noemer_van_het_artikel_of_van_het_merk_komt(client):
    """De vraag die dit beantwoordt: "1142 winkels komt niet terug in de
    instellingen". Dat klopt als het merkgetal gebruikt is; het scherm hoort
    te zeggen welk van de twee het is."""
    _upload(client, [
        _art("31210001", "4049469072773",
             {f"2026{w:02d}": (100, 1000.0) for w in range(1, 8)}),
        _art("31210002", "4049469072774",
             {f"2026{w:02d}": (100, 1000.0) for w in range(1, 8)})])
    _instel(client, aantal=800, target=1.0, artikelen=[
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
         "artikel_ean": "31210001", "aantal_winkels": 120}])

    per = _per_ean(client)
    assert (per["31210001"]["winkels"], per["31210001"]["winkels_bron"]) == (120, "artikel")
    # Geen eigen aantal: dan het afgeleide merkgetal (het grootste artikel).
    assert per["31210002"]["winkels_bron"] == "merk"
