"""Conclusie per retailer: bevindingen deterministisch, tekst door Claude.

De bevindingenlaag is het echte product — die moet zonder API-sleutel werken
en exact te pinnen zijn. De Claude-laag wordt gemockt (zelfde patroon als de
contracttests), zodat CI geen sleutel nodig heeft.
"""

import importlib
import json
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
    for naam in ("db", "seed", "main"):
        sys.modules.pop(naam, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def _art(upc, merk, weeks, winkel=None):
    rij = {"upc": upc, "naam": f"ARTIKEL {upc}", "merk": merk,
           "merk_nr": 2278 if merk == "TWEEZERMAN" else 2912, "weeks": weeks}
    if winkel:
        rij["winkel"], rij["stad"] = winkel, "Sneek"
    return rij


def _laad(client, winkels=True, weken=range(1, 13), merk="TWEEZERMAN"):
    import seed
    artikelen = [
        _art(f"12078000{i}", merk, {f"2026{w:02d}": (10.0, 1) for w in weken},
             f"ETOS FILIAAL {i} - 60{i:02d}" if winkels else None)
        for i in range(1, 6)]
    upload(client, "Data_Grid_57018_winkels.xlsx",
           seed.make_etos_xlsx(artikelen, winkels=winkels))


# ------------------------------------------------------- bevindingen (gratis)

def test_bevindingen_zonder_sleutel(client):
    """De bevindingenlaag is het product: die hoort te werken zonder dat er
    ooit een API-call gedaan is."""
    _laad(client)
    d = client.get("/api/etos/conclusie").json()
    assert d["beschikbaar"] is True
    assert d["sleutel_ingesteld"] is False
    assert d["conclusie"] is None
    assert d["verouderd"] is False          # niets opgeslagen = niets verouderd
    assert d["bevindingen"], "zonder bevindingen valt er niets te concluderen"
    onderdelen = {b["onderdeel"] for b in d["bevindingen"]}
    assert onderdelen <= {"omzet", "assortiment", "winkels", "promoties"}
    for b in d["bevindingen"]:
        assert b["ernst"] in ("rood", "oranje", "info")
        assert b["kop"] and b["tekst"]
    # De vier bestaande signalen worden overgenomen, niet opnieuw afgeleid.
    assert set(d["context"]["signalen"]) >= {"assortiment", "distributie",
                                             "contract", "data", "composiet"}


def test_bevindingen_melden_stilgevallen_winkels(client):
    """Winkels die stilvallen horen als bevinding op te duiken, met hetzelfde
    aantal als de winkelanalyse zelf meldt."""
    import seed
    artikelen = [
        # Vier winkels verkopen door, één valt na week 2 stil.
        _art("120780001", "TWEEZERMAN", {f"2026{w:02d}": (10.0, 1) for w in range(1, 13)},
             "ETOS DOORLOPER - 6001"),
        _art("120780002", "TWEEZERMAN", {f"2026{w:02d}": (10.0, 1) for w in range(1, 3)},
             "ETOS STOPPER - 6002"),
    ]
    upload(client, "Data_Grid_57018_winkels.xlsx",
           seed.make_etos_xlsx(artikelen, winkels=True))
    d = client.get("/api/etos/conclusie").json()
    winkelbev = [b for b in d["bevindingen"] if b["onderdeel"] == "winkels"]
    assert winkelbev, "winkelontwikkeling hoort in de bevindingen te staan"
    gestopt = client.get("/api/etos/dashboard").json()["winkelanalyse"]["gestopt"]
    if gestopt:
        melding = next(b for b in winkelbev if "stilgevallen" in b["kop"])
        assert melding["cijfers"]["aantal"] == len(gestopt)


def test_zonder_data_valt_er_niets_te_concluderen(client):
    d = client.get("/api/etos/conclusie").json()
    assert d["beschikbaar"] is False
    assert d["bevindingen"] == []
    r = client.post("/api/etos/conclusie")
    assert r.status_code == 422 and "niets te concluderen" in r.json()["detail"]


def test_post_zonder_sleutel_is_422(client):
    _laad(client)
    r = client.post("/api/etos/conclusie")
    assert r.status_code == 422
    assert "Anthropic API-sleutel" in r.json()["detail"]


# ------------------------------------------------------------- vingerafdruk

def _vingerafdruk(retailer="etos"):
    import db
    from engine import conclusie
    with db.get_conn() as conn:
        return conclusie.vingerafdruk(conn, retailer)


def test_vingerafdruk_negeert_de_datum(client, monkeypatch):
    """DE val die dit ontwerp stuurt: de analysecache-versie bevat de datum
    van vandaag, dus die verandert elke nacht vanzelf. Hing 'verouderd'
    daaraan, dan zou de app elke dag elke conclusie herschrijven — een
    API-call per retailer per dag zonder dat er iets veranderd is."""
    import datetime as dt

    import db
    import main
    from engine import periods

    _laad(client)
    voor = _vingerafdruk()
    with db.get_conn() as conn:
        versie_voor = main._data_versie(conn)

    monkeypatch.setattr(periods, "_vandaag_nl", lambda: dt.date(2099, 1, 1))
    with db.get_conn() as conn:
        versie_na = main._data_versie(conn)

    assert versie_na != versie_voor, "opzet: de cacheversie hoort wél met de datum mee"
    assert _vingerafdruk() == voor, "de vingerafdruk mag niet met de datum meelopen"


def test_vingerafdruk_verandert_bij_nieuwe_data(client):
    import seed
    _laad(client)
    voor = _vingerafdruk()
    upload(client, "Data_Grid_57018_extra.xlsx", seed.make_etos_xlsx(
        [_art("120780009", "TWEEZERMAN", {f"2026{w:02d}": (10.0, 1) for w in range(1, 14)},
              "ETOS NIEUW - 6009")], winkels=True))
    assert _vingerafdruk() != voor


def test_vingerafdruk_van_andere_retailer_blijft_gelijk(client):
    """Een import voor Kruidvat hoort de conclusie van Etos niet te
    verouderen — anders betaal je voor herschrijvingen die nergens op slaan."""
    import seed
    _laad(client)
    voor = _vingerafdruk("etos")
    upload(client, "DWH__Sales_Tweezerman_KVNL_wk32.xlsx", seed.make_dwh_xlsx([{
        "sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
        "brand": "TWEEZERMAN", "weeks": {"202632": (4, 40.0)}}]))
    assert _vingerafdruk("etos") == voor


# ---------------------------------------------------------- getallencontrole

def _bev(*cijfers):
    return {"context": {}, "bevindingen": [
        {"onderdeel": "omzet", "ernst": "info", "kop": "k", "tekst": "t", "cijfers": c}
        for c in cijfers]}


def test_getallencontrole_vlagt_verzonnen_bedragen():
    from engine import conclusie
    bev = _bev({"omzet_nu": 266758.0, "delta_pct": -20.6})
    assert conclusie.controleer_getallen(
        "De omzet is € 266.758 en daalde -20,6%.", bev) == []
    # Netjes afgerond mag: dat is geen verzinsel.
    assert conclusie.controleer_getallen("De omzet daalde 21%.", bev) == []
    # Een bedrag dat nergens uit volgt hoort gemeld te worden.
    assert conclusie.controleer_getallen(
        "De omzet is € 412.900.", bev) == ["€ 412.900"]


def test_getallencontrole_vlagt_geen_gewone_tellingen():
    """'de 3 merken' mag; anders wordt de waarschuwing waardeloos."""
    from engine import conclusie
    bev = _bev({"aantal": 101})
    assert conclusie.controleer_getallen(
        "Bespreek de 3 merken en de 2 formules met de category manager.", bev) == []


# ------------------------------------------------------ genereren (gemockt)

class _NepBlok:
    type = "text"

    def __init__(self, text):
        self.text = text


class _NepAntwoord:
    def __init__(self, tekst):
        self.content = [_NepBlok(tekst)]


def _nep_anthropic(monkeypatch, antwoord: dict, gezien: dict | None = None):
    """Zelfde patroon als de contracttests: de SDK wordt vervangen, zodat CI
    geen sleutel nodig heeft."""
    class NepMessages:
        def create(self, **kwargs):
            if gezien is not None:
                gezien.update(kwargs)
            return _NepAntwoord(json.dumps(antwoord, ensure_ascii=False))

    class NepAnthropic:
        def __init__(self, api_key=None):
            self.messages = NepMessages()

    monkeypatch.setattr("anthropic.Anthropic", NepAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")


def test_genereren_slaat_op_en_leest_terug(client, monkeypatch):
    _laad(client)
    gezien: dict = {}
    _nep_anthropic(monkeypatch, {
        "samenvatting": "Etos draait stabiel; er zijn geen winkels stilgevallen.",
        "advies": [{"actie": "Bevestig de openstaande acties",
                    "waarom": "anders tellen ze mee als gewone omzet"}],
    }, gezien)

    r = client.post("/api/etos/conclusie")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["conclusie"]["samenvatting"].startswith("Etos draait stabiel")
    assert d["conclusie"]["advies"][0]["actie"] == "Bevestig de openstaande acties"
    assert d["conclusie"]["waarschuwingen"] == []
    assert d["verouderd"] is False

    # Het model krijgt ALLEEN de bevindingen — geen ruwe reeksen.
    prompt = gezien["messages"][0]["content"]
    assert "Bevindingen:" in prompt
    for verboden in ("sparkline", "winkels_ruw", "per_merk_reeks", "reeks"):
        assert verboden not in prompt, f"{verboden} hoort niet in de prompt"

    # Teruglezen kost geen API-call en levert dezelfde tekst.
    d2 = client.get("/api/etos/conclusie").json()
    assert d2["conclusie"]["samenvatting"] == d["conclusie"]["samenvatting"]
    assert d2["verouderd"] is False


def test_conclusie_veroudert_bij_nieuwe_data(client, monkeypatch):
    import seed
    _laad(client)
    _nep_anthropic(monkeypatch, {"samenvatting": "Stabiel.", "advies": []})
    client.post("/api/etos/conclusie")
    assert client.get("/api/etos/conclusie").json()["verouderd"] is False

    upload(client, "Data_Grid_57018_extra.xlsx", seed.make_etos_xlsx(
        [_art("120780009", "TWEEZERMAN", {f"2026{w:02d}": (10.0, 1) for w in range(1, 14)},
              "ETOS NIEUW - 6009")], winkels=True))
    d = client.get("/api/etos/conclusie").json()
    assert d["verouderd"] is True
    assert d["conclusie"]["samenvatting"] == "Stabiel.", "de oude tekst blijft leesbaar"


def test_verzonnen_getal_komt_als_waarschuwing_terug(client, monkeypatch):
    _laad(client)
    _nep_anthropic(monkeypatch, {
        "samenvatting": "De omzet bedroeg € 999.111 deze periode.", "advies": []})
    d = client.post("/api/etos/conclusie").json()
    assert d["conclusie"]["waarschuwingen"], "een verzonnen bedrag hoort gemeld te worden"
    assert "999.111" in d["conclusie"]["waarschuwingen"][0]


def test_onbruikbaar_antwoord_wordt_niet_opgeslagen(client, monkeypatch):
    _laad(client)

    class NepMessages:
        def create(self, **kwargs):
            return _NepAntwoord("dit is geen JSON")

    class NepAnthropic:
        def __init__(self, api_key=None):
            self.messages = NepMessages()

    monkeypatch.setattr("anthropic.Anthropic", NepAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    r = client.post("/api/etos/conclusie")
    assert r.status_code == 422 and "bruikbaar antwoord" in r.json()["detail"]
    assert client.get("/api/etos/conclusie").json()["conclusie"] is None


def test_opslaan_trekt_de_analysecache_niet_leeg(client, monkeypatch):
    """retailer_conclusies telt maar een paar rijen en zou dus op INHOUD
    meegaan in de globale dataversie. Elke opgeslagen conclusie zou dan de
    cache van álle analyses van álle retailers leegtrekken."""
    import db
    import main

    _laad(client)
    _nep_anthropic(monkeypatch, {"samenvatting": "Stabiel.", "advies": []})
    with db.get_conn() as conn:
        versie_voor = main._data_versie(conn)
    client.post("/api/etos/conclusie")
    with db.get_conn() as conn:
        assert main._data_versie(conn) == versie_voor
