"""Projectcalculator: rekenmodel, opslag, logboek en validatie.

De kern: één project levert TWEE uitkomsten — de eenmalige vulling
(sell-in) en de terugkerende doorverkoop (rotatie x winkels, per week en
over de looptijd) — en kosten drukken op de kant waar ze horen.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import projecten  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for name in ("db", "seed", "main"):
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


PRODUCT = {"naam": "Nagellak rood", "kostprijs": 2.0, "verkoopprijs": 5.0,
           "aantal_winkels": 100, "stuks_per_winkel": 6,
           "rotatie_per_winkel_per_week": 0.5}


# ------------------------------------------------------------- rekenmodel

def test_eenmalig_en_terugkerend_gescheiden():
    """100 winkels x 6 stuks vulling = 600 stuks sell-in; daarna 0,5 per
    winkel per week = 50 stuks per week, 4 weken lang (1 t/m 28 september:
    28 dagen inclusief de einddag = exact 4,0 weken)."""
    uit = projecten.bereken(
        {"start_datum": "2026-09-01", "eind_datum": "2026-09-28"},
        [PRODUCT],
        [{"soort": "listing_fee", "label": "Listing fee", "bedrag": 500.0, "terugkerend": 0},
         {"soort": "marketing", "label": "Marketingbudget", "bedrag": 300.0, "terugkerend": 1}])
    assert uit["looptijd_weken"] == 4
    e = uit["eenmalig"]
    assert e["omzet"] == 3000.0                    # 600 x 5
    assert e["productmarge"] == pytest.approx(1800.0)   # 600 x (5-2)
    assert e["kosten"] == 500.0 and e["marge"] == pytest.approx(1300.0)
    assert e["marge_pct"] == pytest.approx(43.3, abs=0.05)
    t = uit["terugkerend"]
    assert t["per_week"] == {"omzet": 250.0, "marge": 150.0}
    assert t["omzet"] == 1000.0 and t["kosten"] == 300.0
    assert t["marge"] == pytest.approx(300.0)      # 4 x 150 - 300
    assert uit["totaal"]["omzet"] == 4000.0
    assert uit["totaal"]["marge"] == pytest.approx(1600.0)


def test_zonder_looptijd_geen_schijngetal():
    """Zonder datums is er wél een weekbeeld, maar geen looptijdtotaal —
    de terugkerende marge blijft None in plaats van nul te lijken."""
    uit = projecten.bereken({}, [PRODUCT], [])
    assert uit["looptijd_weken"] is None
    assert uit["terugkerend"]["per_week"]["omzet"] == 250.0
    assert uit["terugkerend"]["omzet"] is None
    assert uit["terugkerend"]["marge"] is None
    assert uit["totaal"]["marge"] == uit["eenmalig"]["marge"]


def test_lege_velden_rekenen_als_nul():
    uit = projecten.bereken({}, [{"naam": "Leeg product"}], [{"soort": "overig", "label": "X"}])
    assert uit["eenmalig"]["omzet"] == 0.0
    assert uit["eenmalig"]["marge"] == 0.0
    assert uit["eenmalig"]["marge_pct"] is None


def test_lege_kostprijs_met_ingevulde_verkoopprijs_waarschuwt():
    """Kostprijs leeg, verkoopprijs wel ingevuld: de marge rekent kostprijs
    als €0 en lijkt daardoor voller dan hij is. De rekenwijze blijft
    None-tolerant (crasht niet), maar dit moet een waarschuwing opleveren
    i.p.v. stil een te hoge marge te tonen."""
    uit = projecten.bereken({}, [{"naam": "Halfingevuld", "verkoopprijs": 10.0,
                                  "aantal_winkels": 1, "stuks_per_winkel": 1}], [])
    assert uit["producten"][0]["marge_per_stuk"] == 10.0  # rekent nog steeds door
    assert uit["producten"][0]["prijs_onvolledig"] is True
    assert uit["waarschuwingen"] and "Halfingevuld" in uit["waarschuwingen"][0]


def test_beide_prijzen_leeg_of_beide_ingevuld_waarschuwt_niet():
    """Beide leeg (nog niets ingevuld) of beide ingevuld (compleet) zijn
    geen halfvolle rijen en horen geen waarschuwing te geven."""
    uit = projecten.bereken({}, [
        {"naam": "Nog leeg"},
        {"naam": "Compleet", "kostprijs": 1.0, "verkoopprijs": 2.0},
    ], [])
    assert uit["waarschuwingen"] == []


def test_looptijd_is_fractioneel_met_einddag_inbegrepen():
    """Hele weken afronden gooide tot een halve week doorverkoop weg (74
    dagen werd 11 weken); de looptijd telt nu fractioneel, mét de einddag."""
    assert projecten.looptijd_weken("2026-09-01", "2026-09-03") == 0.4   # 3 dagen
    assert projecten.looptijd_weken("2026-09-01", "2026-09-01") == 0.1   # 1 dag
    assert projecten.looptijd_weken("2026-01-05", "2026-03-29") == 12.0  # 84 dagen
    assert projecten.looptijd_weken("2026-09-01", "2026-11-13") == 10.6  # 74 dagen


def test_looptijdkosten_zonder_looptijd_staan_expliciet_buiten_beeld():
    """Looptijdkosten kunnen zonder looptijd nergens op drukken; ze stil uit
    het totaal laten vallen laat het project completer lijken dan het is."""
    uit = projecten.bereken({}, [PRODUCT],
                            [{"soort": "marketing", "label": "M", "bedrag": 4000.0,
                              "terugkerend": 1}])
    assert uit["totaal"]["kosten_buiten_beeld"] == 4000.0
    # Mét looptijd tellen ze gewoon mee en is er niets buiten beeld.
    uit = projecten.bereken({"start_datum": "2026-09-01", "eind_datum": "2026-09-28"},
                            [PRODUCT],
                            [{"soort": "marketing", "label": "M", "bedrag": 4000.0,
                              "terugkerend": 1}])
    assert uit["totaal"]["kosten_buiten_beeld"] == 0.0


def test_bijdrage_leverancier_telt_op_bij_de_marge():
    """De bijdrage van de fabrikant verlaagt de nettokosten: hij telt óp bij
    de nettomarge van de kant waar zijn schakel op staat, en telt niet als
    omzet (het is een tegemoetkoming, geen verkoop)."""
    uit = projecten.bereken(
        {"start_datum": "2026-09-01", "eind_datum": "2026-09-28"},
        [PRODUCT],
        [{"soort": "listing_fee", "label": "Listing fee", "bedrag": 500.0, "terugkerend": 0},
         {"soort": "bijdrage_leverancier", "label": "Bijdrage leverancier",
          "bedrag": 800.0, "terugkerend": 0},
         {"soort": "marketing", "label": "Marketingbudget", "bedrag": 300.0, "terugkerend": 1},
         {"soort": "bijdrage_leverancier", "label": "Bijdrage leverancier",
          "bedrag": 100.0, "terugkerend": 1}])
    e = uit["eenmalig"]
    assert e["omzet"] == 3000.0                       # bijdrage is géén omzet
    assert e["bijdrage"] == 800.0
    assert e["marge"] == pytest.approx(1800.0 - 500.0 + 800.0)   # 2100
    assert e["marge_pct"] == pytest.approx(2100.0 / 3000.0 * 100, abs=0.05)
    t = uit["terugkerend"]
    assert t["bijdrage"] == 100.0
    assert t["marge"] == pytest.approx(4 * 150.0 - 300.0 + 100.0)  # 400
    assert uit["totaal"]["marge"] == pytest.approx(2100.0 + 400.0)


def test_bijdrage_zonder_looptijd_telt_in_buiten_beeld():
    """Een looptijd-bijdrage zonder looptijd staat net zo buiten beeld als
    looptijdkosten; het gemelde bedrag is het nettosaldo."""
    uit = projecten.bereken({}, [PRODUCT], [
        {"soort": "marketing", "label": "M", "bedrag": 4000.0, "terugkerend": 1},
        {"soort": "bijdrage_leverancier", "label": "B", "bedrag": 1500.0, "terugkerend": 1}])
    assert uit["totaal"]["kosten_buiten_beeld"] == 2500.0


# ------------------------------------------------------------- opslag + log

def test_aanmaken_opslaan_en_logboek(client):
    r = client.post("/api/projecten", json={"naam": "Actie week 40", "door": "Willem"})
    assert r.status_code == 200
    d = r.json()
    # Standaardkostenregels staan klaar, met de gebruikelijke schakelstand.
    assert [k["soort"] for k in d["kosten"]] == \
        ["listing_fee", "coop", "marketing", "display", "logistiek", "verpakking",
         "bijdrage_leverancier"]
    assert d["status"] == "concept"       # nieuwe projecten starten als concept
    assert d["log"][0]["actie"] == "aangemaakt" and d["log"][0]["door"] == "Willem"

    d["producten"] = [PRODUCT]
    d["kosten"][0]["bedrag"] = 500.0
    r = client.put(f"/api/projecten/{d['id']}",
                   json={**d, "start_datum": "2026-09-01", "eind_datum": "2026-09-28",
                         "door": "Sanne"})
    assert r.status_code == 200
    d2 = r.json()
    assert d2["gewijzigd_door"] == "Sanne"
    assert d2["log"][0]["actie"].startswith("gewijzigd")
    assert d2["berekening"]["eenmalig"]["marge"] == pytest.approx(1300.0)

    # Herladen geeft hetzelfde terug; de lijst toont de kerncijfers.
    lijst = client.get("/api/projecten").json()
    assert lijst[0]["naam"] == "Actie week 40"
    assert lijst[0]["eenmalig"]["marge"] == pytest.approx(1300.0)
    assert lijst[0]["looptijd_weken"] == 4


def test_status_markeren_als_definitief(client):
    """Een label, geen slot: definitief blijft gewoon bewerkbaar."""
    d = client.post("/api/projecten", json={"naam": "P"}).json()
    r = client.put(f"/api/projecten/{d['id']}", json={**d, "status": "definitief"})
    assert r.json()["status"] == "definitief"
    assert client.get(f"/api/projecten/{d['id']}").json()["status"] == "definitief"
    assert client.get("/api/projecten").json()[0]["status"] == "definitief"


def test_onbekende_status_wordt_geweigerd(client):
    d = client.post("/api/projecten", json={"naam": "P"}).json()
    r = client.put(f"/api/projecten/{d['id']}", json={**d, "status": "goedgekeurd"})
    assert r.status_code == 422


def test_snelle_autosaves_van_dezelfde_persoon_vullen_één_logregel_bij(client):
    """Automatisch opslaan mag niet één logregel per toetsaanslag geven:
    binnen 5 minuten door dezelfde persoon ververst hetzelfde logregel."""
    d = client.post("/api/projecten", json={"naam": "P", "door": "Willem"}).json()
    assert len(d["log"]) == 1                      # alleen 'aangemaakt'
    for i in range(3):
        d = client.put(f"/api/projecten/{d['id']}",
                       json={**d, "omschrijving": f"versie {i}", "door": "Willem"}).json()
    # 'aangemaakt' + één (ververste) 'gewijzigd'-regel — geen drie extra.
    assert len(d["log"]) == 2
    assert d["log"][0]["actie"].startswith("gewijzigd")

    # Een andere persoon start wél een nieuwe regel.
    d = client.put(f"/api/projecten/{d['id']}", json={**d, "door": "Sanne"}).json()
    assert len(d["log"]) == 3
    assert d["log"][0]["door"] == "Sanne"


def test_gatewayheader_wint_van_het_naamveld(client):
    r = client.post("/api/projecten", json={"naam": "P", "door": "Getypt"},
                    headers={"Remote-User": "willem@leijtensimport.com"})
    assert r.json()["log"][0]["door"] == "willem@leijtensimport.com"


def test_wie_ben_ik_meldt_het_portaal_als_er_een_header_staat(client):
    """Zodat het scherm het handmatige naamveld kan laten verdwijnen zodra
    het portaal een identiteit meestuurt."""
    r = client.get("/api/wie-ben-ik", headers={"Remote-User": "willem@leijtensimport.com"})
    assert r.json() == {"naam": "willem@leijtensimport.com", "bron": "portaal"}


def test_wie_ben_ik_valt_terug_op_handmatig_zonder_header(client):
    r = client.get("/api/wie-ben-ik")
    assert r.json() == {"naam": None, "bron": "handmatig"}


def test_validatie_wijst_onzin_af(client):
    p = client.post("/api/projecten", json={"naam": "P"}).json()
    fout = client.put(f"/api/projecten/{p['id']}", json={
        **p, "start_datum": "2026-09-10", "eind_datum": "2026-09-01"})
    assert fout.status_code == 422 and "einddatum" in fout.json()["detail"]
    fout = client.put(f"/api/projecten/{p['id']}", json={
        **p, "producten": [{"naam": "X", "kostprijs": -1}]})
    assert fout.status_code == 422
    # En bij een fout is er niets veranderd.
    assert client.get(f"/api/projecten/{p['id']}").json()["producten"] == []


def test_verwijderen_ruimt_alles_op(client):
    p = client.post("/api/projecten", json={"naam": "Weg ermee"}).json()
    assert client.delete(f"/api/projecten/{p['id']}").status_code == 200
    assert client.get(f"/api/projecten/{p['id']}").status_code == 404
    assert client.get("/api/projecten").json() == []
