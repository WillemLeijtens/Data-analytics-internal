"""Winkelaantallen per artikel, naast het bestaande merkniveau.

Niet elk artikel van een merk ligt in evenveel winkels: een basisitem in 800
filialen, een nieuwe kleur in 120. Eén getal voor het hele merk maakt van de
omzet per winkel van dat nieuwe item een fractie van wat het echt is.

Voor het MERKgemiddelde geldt een voorbehoud, en die keuze wordt hier
vastgepind: het merk krijgt het GROOTSTE artikelaantal, niet de som. Zie
engine/winkelniveau.py voor de redenering.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import winkelniveau  # noqa: E402
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


def _laad(client):
    """Twee artikelen van één merk, in dezelfde week."""
    import seed
    upload(client, "kv.xlsx", seed.make_dwh_xlsx([
        {"sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
         "brand": "TWEEZERMAN", "weeks": {"202632": (10, 800.0)}},
        {"sku": "31210002", "gtin": "4049469072774", "desc": "Mini",
         "brand": "TWEEZERMAN", "weeks": {"202632": (5, 200.0)}}]))


# ------------------------------------------------------------- de rekenregel

def test_merkniveau_blijft_het_ingestelde_getal():
    assert winkelniveau.effectief(
        {"niveau": "merk", "aantal_winkels": 500}, [{"aantal_winkels": 120}]) == 500


def test_artikelniveau_neemt_het_grootste_artikel():
    """Niet de som: elke winkel die beide artikelen voert zou dan dubbel
    tellen en het gemiddelde naar een fractie van de werkelijkheid duwen."""
    assert winkelniveau.effectief(
        {"niveau": "artikel", "aantal_winkels": 999},
        [{"aantal_winkels": 120}, {"aantal_winkels": 800}]) == 800


def test_artikelniveau_zonder_ingevulde_artikelen_geeft_niets():
    """Net als een leeg merkveld: dan valt de analyse terug op wat ze zonder
    instelling doet, in plaats van met een verzonnen getal te rekenen."""
    assert winkelniveau.effectief(
        {"niveau": "artikel", "aantal_winkels": 500},
        [{"aantal_winkels": None}, {}]) is None


def test_nul_en_negatief_tellen_niet_mee():
    assert winkelniveau.effectief(
        {"niveau": "artikel"}, [{"aantal_winkels": 0}, {"aantal_winkels": -3},
                                {"aantal_winkels": 60}]) == 60


# ----------------------------------------------------------------- endpoints

def test_artikelen_uit_de_feed_komen_mee(client):
    _laad(client)
    d = client.get("/api/kruidvat/instellingen").json()
    # Kruidvat levert het artikelnummer, niet de EAN — de feed bepaalt wat
    # er in de lijst staat, niet een aanname over identifiers.
    eans = {a["artikel_ean"] for a in d["feed_artikelen"]}
    assert eans == {"31210001", "31210002"}
    # Handmatig een artikel verzinnen kan niet: de lijst komt uit de feiten.
    assert all(a["merk"] == "TWEEZERMAN" for a in d["feed_artikelen"])


def test_artikelniveau_stuurt_het_dashboard(client):
    _laad(client)
    client.put("/api/kruidvat/instellingen", json={
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": 999, "niveau": "artikel"}],
        "artikel_winkels": [
            {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
             "artikel_ean": "31210001", "aantal_winkels": 800},
            {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
             "artikel_ean": "31210002", "aantal_winkels": 120}]})

    k = client.get("/api/kruidvat/dashboard").json()["kpi"]["omzet_per_winkel"]
    # 1000 omzet / 800 winkels — het merkveld (999) telt niet mee.
    assert k["waarde"] == pytest.approx(1000.0 / 800)


def test_terugschakelen_naar_merkniveau_gooit_niets_weg(client):
    _laad(client)
    payload = {
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": 500, "niveau": "artikel"}],
        "artikel_winkels": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "artikel_ean": "31210001", "aantal_winkels": 800}]}
    client.put("/api/kruidvat/instellingen", json=payload)

    terug = {**payload, "winkels_targets": [
        {**payload["winkels_targets"][0], "niveau": "merk"}]}
    client.put("/api/kruidvat/instellingen", json=terug)

    d = client.get("/api/kruidvat/instellingen").json()
    assert d["winkels_targets"][0]["niveau"] == "merk"
    assert d["winkels_targets"][0]["aantal_winkels"] == 500
    # De artikelinstelling staat er nog: opnieuw omschakelen kost geen werk.
    assert d["artikel_winkels"][0]["aantal_winkels"] == 800
    k = client.get("/api/kruidvat/dashboard").json()["kpi"]["omzet_per_winkel"]
    assert k["waarde"] == pytest.approx(1000.0 / 500)


def test_onbekend_niveau_wordt_geweigerd(client):
    _laad(client)
    r = client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "niveau": "winkel"}]})
    assert r.status_code == 422


def test_artikelaantal_moet_positief_zijn(client):
    _laad(client)
    r = client.put("/api/kruidvat/instellingen", json={"artikel_winkels": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
         "artikel_ean": "31210001", "aantal_winkels": 0}]})
    assert r.status_code == 422


def test_historie_legt_het_afgeleide_getal_vast(client):
    """De historie voedt het distributiesignaal. Op artikelniveau hoort daar
    het getal in waarmee gerekend wordt, niet het merkveld dat niet meetelt."""
    _laad(client)
    client.put("/api/kruidvat/instellingen", json={
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": 500, "niveau": "merk"}]})
    client.put("/api/kruidvat/instellingen", json={
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": 500, "niveau": "artikel"}],
        "artikel_winkels": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "artikel_ean": "31210001", "aantal_winkels": 420}]})

    h = client.get("/api/kruidvat/instellingen").json()["winkels_historie"]
    assert [r["aantal_winkels"] for r in h] == [500, 420]


def test_opslaan_zonder_wijziging_maakt_geen_nieuwe_meting(client):
    """Anders groeit de historie bij elke keer 'Alles opslaan' met een
    wijziging die er niet was, en toont het distributiesignaal ruis."""
    _laad(client)
    payload = {
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": 500, "niveau": "artikel"}],
        "artikel_winkels": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "artikel_ean": "31210001", "aantal_winkels": 420}]}
    client.put("/api/kruidvat/instellingen", json=payload)
    voor = client.get("/api/kruidvat/instellingen").json()["winkels_historie"]
    client.put("/api/kruidvat/instellingen", json=payload)
    na = client.get("/api/kruidvat/instellingen").json()["winkels_historie"]
    assert len(na) == len(voor)


# --------------------------------------------- waar artikelniveau voor dient

def test_rotatie_deelt_door_de_winkels_van_dat_artikel(client):
    """Dit is de eigenlijke winst: een nieuwe kleur in 120 filialen die door
    het merkaantal van 800 gedeeld wordt, ziet eruit als een delist-kandidaat
    terwijl hij in zijn eigen winkels prima loopt."""
    import seed
    upload(client, "kv.xlsx", seed.make_dwh_xlsx([
        {"sku": "31210001", "gtin": "4049469072773", "desc": "Basis",
         "brand": "TWEEZERMAN", "weeks": {"202632": (800, 8000.0)}},
        {"sku": "31210002", "gtin": "4049469072774", "desc": "Nieuwe kleur",
         "brand": "TWEEZERMAN", "weeks": {"202632": (120, 1200.0)}}]))
    client.put("/api/kruidvat/instellingen", json={
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": 800, "niveau": "artikel"}],
        "artikel_winkels": [
            {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
             "artikel_ean": "31210001", "aantal_winkels": 800},
            {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
             "artikel_ean": "31210002", "aantal_winkels": 120}],
        "rotatie_targets": [{"merk": "TWEEZERMAN", "stuks_per_winkel_per_week": 1}]})

    per_ean = {a["ean"]: a for a in
               client.get("/api/kruidvat/assortiment").json()["artikelen"]}
    # Beide artikelen draaien 1 stuk per winkel per week in hun eigen winkels.
    assert per_ean["31210001"]["rotatie"] == pytest.approx(1.0)
    assert per_ean["31210002"]["rotatie"] == pytest.approx(1.0)


def test_zonder_artikelinstelling_blijft_het_merkgetal_gelden(client):
    """Een artikel zonder eigen aantal valt terug op het merk; anders zou het
    omzetten naar artikelniveau elk nog niet ingevuld artikel breken.

    De volumes zijn groot genoeg gekozen om het verschil te zien: rotatie
    wordt op twee decimalen afgerond, dus 5/400 en 5/500 zijn allebei 0,01."""
    import seed
    upload(client, "kv.xlsx", seed.make_dwh_xlsx([
        {"sku": "31210001", "gtin": "4049469072773", "desc": "Basis",
         "brand": "TWEEZERMAN", "weeks": {"202632": (800, 8000.0)}},
        {"sku": "31210002", "gtin": "4049469072774", "desc": "Mini",
         "brand": "TWEEZERMAN", "weeks": {"202632": (400, 4000.0)}}]))
    client.put("/api/kruidvat/instellingen", json={
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": 500, "niveau": "artikel"}],
        "artikel_winkels": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "artikel_ean": "31210001", "aantal_winkels": 400}],
        "rotatie_targets": [{"merk": "TWEEZERMAN", "stuks_per_winkel_per_week": 1}]})

    per_ean = {a["ean"]: a for a in
               client.get("/api/kruidvat/assortiment").json()["artikelen"]}
    # 31210002 heeft geen eigen aantal: dan geldt het afgeleide merkgetal (400,
    # het grootste artikel), niet het niet-meetellende merkveld van 500.
    # 400 stuks door het afgeleide merkgetal (400, het grootste artikel),
    # niet door het merkveld van 500 dat niet meetelt.
    assert per_ean["31210002"]["rotatie"] == pytest.approx(1.0)
    assert per_ean["31210001"]["rotatie"] == pytest.approx(2.0)
