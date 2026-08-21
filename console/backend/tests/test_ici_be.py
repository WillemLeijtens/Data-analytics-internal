"""ICI Paris XL België als eigen retailer.

Het maandrapport van BE heeft exact dezelfde structuur als dat van NL — het
noemt zelf geen land. De retailer bepaalt dus welk land het is, en de twee
aanleveringen mogen elkaars cijfers nooit raken: eigen winkelbestand, eigen
tabblad.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_parser_flow import upload  # noqa: E402

NL_BESTAND = "Maandelijkse resultaten ICI Paris XL (7).xlsx"
BE_BESTAND = "SO_07.xlsx"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for naam in ("db", "seed", "main"):
        sys.modules.pop(naam, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def _rapport(winkels: dict, merk="DEPEND"):
    import seed
    return seed.make_ici_xlsx({merk: winkels})


BE_WINKELS = {"5007": {"202607": 100.0}, "5009": {"202607": 50.0}}
NL_WINKELS = {"1201": {"202607": 300.0}, "1202": {"202607": 200.0}}


# ------------------------------------------------------------------ routering

def test_be_bestand_landt_bij_de_be_retailer(client):
    r = client.post("/api/import/controle", files=[
        ("files", (BE_BESTAND, _rapport(BE_WINKELS)))]).json()["results"][0]
    assert r["herkend"] is True
    assert r["retailer_id"] == "ici-paris-be"


def test_nl_bestand_blijft_bij_nl(client):
    """De echte NL-bestandsnaam heeft SPATIES; de oude glob had
    onderstrepingstekens en matchte dus nooit op naam."""
    r = client.post("/api/import/controle", files=[
        ("files", (NL_BESTAND, _rapport(NL_WINKELS)))]).json()["results"][0]
    assert r["retailer_id"] == "ici-paris-xl"


def test_de_twee_aanleveringen_blijven_gescheiden(client):
    upload(client, NL_BESTAND, _rapport(NL_WINKELS))
    upload(client, BE_BESTAND, _rapport(BE_WINKELS))

    nl = client.get("/api/ici-paris-xl/dashboard").json()
    be = client.get("/api/ici-paris-be/dashboard").json()
    assert nl["kpi"]["omzet"]["waarde"] == pytest.approx(500.0)
    assert be["kpi"]["omzet"]["waarde"] == pytest.approx(150.0)
    # En het winkelbestand telt niet bij elkaar op.
    assert nl["kpi"]["omzet_per_winkel"]["winkels"] == 2
    assert be["kpi"]["omzet_per_winkel"]["winkels"] == 2


def test_be_data_krijgt_land_be(client):
    """Het rapport noemt geen land; dat komt uit het profiel van de retailer.
    Zonder dat zou BE-omzet als Nederlandse omzet in de analyses staan."""
    upload(client, BE_BESTAND, _rapport(BE_WINKELS))
    import db
    with db.get_conn() as conn:
        landen = {r[0] for r in conn.execute(
            "SELECT DISTINCT land FROM sellout_facts WHERE retailer_id='ici-paris-be'")}
    assert landen == {"BE"}


def test_be_verschijnt_als_eigen_tabblad(client):
    kaarten = {r["id"]: r for r in client.get("/api/overview").json()["retailers"]}
    assert kaarten["ici-paris-be"]["naam"] == "ICI Paris XL BE"
    assert kaarten["ici-paris-be"]["aangesloten"] is True
    # Naast NL, niet in plaats van.
    assert kaarten["ici-paris-xl"]["aangesloten"] is True


# ------------------------------------------- herkenning op winkelnummer

# ICI nummert per land in een eigen reeks: BE 5xxx, NL 6xxx en 7xxx, zonder
# één overlappend nummer (gecontroleerd op de echte bestanden van juli 2026:
# BE 5004-5308 over 135 winkels, NL 6051-7995 over 151). Een hernoemd bestand
# landt daardoor nog steeds bij het juiste land.

def test_hernoemd_be_bestand_landt_op_winkelnummer(client):
    r = client.post("/api/import/controle", files=[
        ("files", ("rapport.xlsx", _rapport(BE_WINKELS)))]).json()["results"][0]
    assert r["herkend"] is True
    assert r["retailer_id"] == "ici-paris-be"


def test_hernoemd_nl_bestand_landt_op_winkelnummer(client):
    r = client.post("/api/import/controle", files=[
        ("files", ("rapport.xlsx", _rapport({"7101": {"202607": 10.0}}))
         )]).json()["results"][0]
    assert r["retailer_id"] == "ici-paris-xl"


def test_een_winkel_buiten_de_reeks_maakt_het_geen_match(client):
    """Alles of niets: één winkel buiten de reeks betekent dat de aanname niet
    meer klopt, en dan is vragen beter dan een half kloppende gok."""
    gemengd = {"5007": {"202607": 10.0}, "7101": {"202607": 10.0}}
    r = client.post("/api/import/controle", files=[
        ("files", ("rapport.xlsx", _rapport(gemengd)))]).json()["results"][0]
    assert r["herkend"] is False
    assert {k["retailer_id"] for k in r["keuzes"]} == {"ici-paris-xl", "ici-paris-be"}


def test_onbekende_nummerreeks_vraagt_om_een_keuze(client):
    """Gaat ICI ooit hernummeren, of komt er een derde land bij, dan past geen
    enkele reeks. Dan blijven beide kandidaten staan en vraagt de app het —
    'geen parser herkent dit' zou naar het bouwen van een parser sturen die er
    al is."""
    r = client.post("/api/import/controle", files=[
        ("files", ("rapport.xlsx", _rapport({"9001": {"202607": 10.0}})))]).json()["results"][0]
    assert r["herkend"] is False
    assert {k["retailer_id"] for k in r["keuzes"]} == {"ici-paris-xl", "ici-paris-be"}
    assert "kies" in r["detail"].lower()


def test_de_keuze_bepaalt_waar_het_landt(client):
    inhoud = _rapport({"9001": {"202607": 10.0}})
    r = client.post("/api/import", files=[("files", ("rapport.xlsx", inhoud))],
                    data={"retailer_id": "ici-paris-be"}).json()["results"][0]
    assert r["status"] == "ingelezen"
    assert r["retailer_id"] == "ici-paris-be"


def test_zonder_keuze_wordt_er_niets_geraden(client):
    r = client.post("/api/import", files=[
        ("files", ("rapport.xlsx", _rapport({"9001": {"202607": 10.0}})))]).json()["results"][0]
    assert r["status"] == "profiel_nodig"
    assert r["rows"] == 0


def test_een_keuze_buiten_de_kandidaten_telt_niet(client):
    """Anders kan een verkeerd meegestuurde retailer een bestand door een
    parser duwen die het formaat niet aankan."""
    r = client.post("/api/import",
                    files=[("files", ("rapport.xlsx", _rapport({"9001": {"202607": 10.0}})))],
                    data={"retailer_id": "kruidvat"}).json()["results"][0]
    assert r["status"] == "profiel_nodig"
