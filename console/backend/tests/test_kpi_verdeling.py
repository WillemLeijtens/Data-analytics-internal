"""Uitsplitsing van de KPI-tegels over land en formule.

De tegels toonden alleen een verdeling per merk. Wie wil weten waar de omzet
van de afgelopen week vandaan komt — welk land, welke formule — kon dat niet
zien. Deze tests pinnen vast dat de verdelingen optellen tot het totaal, dat
er geen dimensie wordt aangeboden die de feed niet levert, en dat een
samengestelde bannerwaarde ("KV;TP") één categorie blijft.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def _dwh(weken: dict, *, land="NLD", formule="KV") -> bytes:
    import seed
    return seed.make_dwh_xlsx(
        [{"sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
          "brand": "TWEEZERMAN", "weeks": weken}],
        country3=land, formula=formule)


def _dash(client):
    r = client.get("/api/kruidvat/dashboard")
    assert r.status_code == 200
    return r.json()


def test_verdeling_per_land_en_formule_telt_op_tot_het_totaal(client):
    # Zelfde week, vier feiten: twee landen × twee formules. Elke uitsplitsing
    # verdeelt dezelfde omzet, dus alle drie moeten op hetzelfde totaal uitkomen.
    upload(client, "kv_nl.xlsx", _dwh({"202632": (10, 100.0)}, land="NLD", formule="KV"))
    upload(client, "tp_nl.xlsx", _dwh({"202632": (5, 50.0)}, land="NLD", formule="TP"))
    upload(client, "kv_be.xlsx", _dwh({"202632": (4, 40.0)}, land="BEL", formule="KV"))
    upload(client, "tp_be.xlsx", _dwh({"202632": (1, 10.0)}, land="BEL", formule="TP"))

    d = _dash(client)
    assert d["dimensies"] == ["merk", "land", "banner"]
    k = d["kpi"]
    for kpi, totaal in (("omzet", 200.0), ("volume", 20)):
        for dim in ("merk", "land", "banner"):
            verdeling = k[kpi]["breakdowns"][dim]
            assert sum(b["waarde"] for b in verdeling) == pytest.approx(totaal), (kpi, dim)

    per_land = {b["label"]: b["waarde"] for b in k["omzet"]["breakdowns"]["land"]}
    assert per_land == pytest.approx({"NL": 150.0, "BE": 50.0})
    per_formule = {b["label"]: b["waarde"] for b in k["omzet"]["breakdowns"]["banner"]}
    assert per_formule == pytest.approx({"KV": 140.0, "TP": 60.0})
    # Aflopend gesorteerd, zodat de grootste bijdrage bovenaan staat.
    assert [b["waarde"] for b in k["omzet"]["breakdowns"]["land"]] == [150.0, 50.0]


def test_merkverdeling_blijft_ongewijzigd(client):
    upload(client, "kv.xlsx", _dwh({"202632": (10, 100.0)}))
    k = _dash(client)["kpi"]
    # De oude sleutel blijft bestaan (bestaande consumenten), en `merk` staat
    # naast `label` zodat de merkkleuren blijven werken.
    oud = k["omzet"]["breakdown"]
    assert oud == k["omzet"]["breakdowns"]["merk"]
    assert oud[0]["merk"] == oud[0]["label"] == "TWEEZERMAN"


def test_samengestelde_formule_blijft_een_categorie(client):
    # "KV;TP" is in de bron één regel; die omzet is niet over formules te
    # splitsen, dus verzin geen verdeling maar toon hem als eigen categorie.
    upload(client, "kv_tp.xlsx", _dwh({"202632": (10, 100.0)}, formule="KV;TP"))
    upload(client, "kv.xlsx", _dwh({"202632": (4, 40.0)}, formule="KV"))
    k = _dash(client)["kpi"]
    labels = {b["label"] for b in k["omzet"]["breakdowns"]["banner"]}
    assert "KV;TP" in labels


def test_omzet_per_winkel_splitst_de_winkels_mee(client):
    upload(client, "kv_nl.xlsx", _dwh({"202632": (10, 100.0)}, land="NLD"))
    upload(client, "kv_be.xlsx", _dwh({"202632": (4, 40.0)}, land="BEL"))
    r = client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "aantal_winkels": 500,
         "target_per_winkel": None},
        {"merk": "TWEEZERMAN", "land": "BE", "banner": "KV", "aantal_winkels": 200,
         "target_per_winkel": None}]})
    assert r.status_code == 200
    per_land = {b["label"]: b for b in
                _dash(client)["kpi"]["omzet_per_winkel"]["breakdowns"]["land"]}
    # Elk land door zijn eigen winkelbestand, niet door het totaal van 700.
    assert per_land["NL"]["winkels"] == 500
    assert per_land["NL"]["waarde"] == pytest.approx(100.0 / 500)
    assert per_land["BE"]["winkels"] == 200
    assert per_land["BE"]["waarde"] == pytest.approx(40.0 / 200)
    # Targets staan per merk vastgelegd; over land zou optellen er een verzinnen.
    assert per_land["NL"]["target"] is None


def test_dimensie_blijft_staan_als_een_feed_achterloopt(client):
    # BE levert week 32 nog niet. De knop "Per land" moet blijven staan —
    # anders verschijnt en verdwijnt hij met het ritme van de feeds — maar de
    # verdeling van week 32 toont alleen wat er in die week is: NL.
    upload(client, "kv_nl31.xlsx", _dwh({"202631": (10, 100.0)}, land="NLD"))
    upload(client, "kv_be31.xlsx", _dwh({"202631": (4, 40.0)}, land="BEL"))
    upload(client, "kv_nl32.xlsx", _dwh({"202632": (10, 120.0)}, land="NLD"))

    d = _dash(client)
    assert d["laatste_periode"] == "2026-W32"
    assert "land" in d["dimensies"]
    per_land = d["kpi"]["omzet"]["breakdowns"]["land"]
    assert [b["label"] for b in per_land] == ["NL"]
    assert per_land[0]["waarde"] == pytest.approx(120.0)


def test_dimensie_met_een_waarde_wordt_niet_aangeboden(client):
    # Eén land, één formule: een "verdeling" zou één balk ter grootte van het
    # totaal zijn. Zo'n knop voegt niets toe, dus hij verschijnt niet.
    upload(client, "kv.xlsx", _dwh({"202632": (10, 100.0)}, land="NLD", formule="KV"))
    d = _dash(client)
    assert d["dimensies"] == ["merk"]
    assert set(d["kpi"]["omzet"]["breakdowns"]) == {"merk"}
