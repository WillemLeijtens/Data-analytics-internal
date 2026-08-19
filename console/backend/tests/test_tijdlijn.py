"""Omzet per winkel over tijd: het winkelaantal van TÓEN, en een
decompositie die exact opgaat.

De oude per-winkel-reeks deelde de hele historie door het winkelaantal van
vandaag. Zakte dat van 530 naar 470, dan werd met terugwerkende kracht ook
2024 door 470 gedeeld — precies het effect dat zichtbaar moest worden
verdween. Deze tests pinnen het nieuwe gedrag vast.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_parser_flow import upload  # noqa: E402

U = Path("/root/.claude/uploads/54377bab-ac94-5cbf-8750-c3a4d90899e0")
REAL_ICI = U / "fc6fc987-Maandelijkse_resultaten__Tweezerman__Depend_ICI_Paris_XL__4.xlsx"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for name in ("db", "seed", "main"):
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def _kv(weken: dict) -> bytes:
    import seed
    return seed.make_dwh_xlsx([{"sku": "31210001", "gtin": "4049469072773",
                                "desc": "Slant", "brand": "TWEEZERMAN",
                                "weeks": weken}])


def test_winkelaantal_van_toen_bepaalt_de_deling(client):
    """De kern: metingen met datum maken de reeks historisch eerlijk."""
    upload(client, "DWH__Sales_Tweezerman_KVNL_hist.xlsx",
           _kv({"202601": (10, 1000.0), "202602": (10, 1000.0),
                "202620": (10, 1000.0), "202621": (10, 1000.0)}))
    for aantal, vanaf in ((500, "2026-01-01"), (250, "2026-05-18")):
        r = client.post("/api/kruidvat/winkelaantallen", json={
            "merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
            "aantal_winkels": aantal, "geldig_vanaf": vanaf})
        assert r.status_code == 200, r.text

    t = client.get("/api/kruidvat/dashboard").json()["tijdlijn"]
    serie = t["per_merk"][0]
    idx = {p: i for i, p in enumerate(t["periodes"])}
    # Zelfde omzet, ander winkelaantal -> het gemiddelde verdubbelt.
    assert serie["winkels"][idx["2026-W01"]] == 500
    assert serie["per_winkel"][idx["2026-W01"]] == pytest.approx(2.0)
    assert serie["winkels"][idx["2026-W21"]] == 250
    assert serie["per_winkel"][idx["2026-W21"]] == pytest.approx(4.0)
    # Week 20 valt vóór 18 mei (start van week 21) -> nog het oude aantal.
    assert serie["winkels"][idx["2026-W20"]] == 500


def test_periode_voor_de_eerste_meting_heet_aangenomen(client):
    upload(client, "DWH__Sales_Tweezerman_KVNL_aang.xlsx",
           _kv({"202501": (10, 500.0), "202601": (10, 1000.0)}))
    client.post("/api/kruidvat/winkelaantallen", json={
        "merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
        "aantal_winkels": 400, "geldig_vanaf": "2026-01-01"})
    t = client.get("/api/kruidvat/dashboard").json()["tijdlijn"]
    serie, idx = t["per_merk"][0], {p: i for i, p in enumerate(t["periodes"])}
    assert serie["bron"][idx["2025-W01"]] == "aangenomen"
    assert serie["bron"][idx["2026-W01"]] == "gemeten"
    # Vóór de meting wordt met het oudst bekende getal gerekend, niet met nul.
    assert serie["winkels"][idx["2025-W01"]] == 400


def test_decompositie_is_exact_multiplicatief(client):
    """omzet% = winkels% x per-winkel%, tot op de komma."""
    upload(client, "DWH__Sales_Tweezerman_KVNL_dec.xlsx",
           _kv({"202520": (10, 1000.0), "202620": (10, 1200.0)}))
    for aantal, vanaf in ((500, "2025-01-01"), (400, "2026-01-01")):
        client.post("/api/kruidvat/winkelaantallen", json={
            "merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
            "aantal_winkels": aantal, "geldig_vanaf": vanaf})
    d = client.get("/api/kruidvat/dashboard").json()["tijdlijn"]["decompositie"]["totaal"]
    # omzet +20%, winkels -20% -> per winkel +50%; (1,2 = 0,8 x 1,5)
    assert d["omzet_pct"] == pytest.approx(20.0, abs=0.1)
    assert d["winkels_pct"] == pytest.approx(-20.0, abs=0.1)
    assert d["per_winkel_pct"] == pytest.approx(50.0, abs=0.1)
    klopt = (1 + d["winkels_pct"] / 100) * (1 + d["per_winkel_pct"] / 100) - 1
    assert klopt * 100 == pytest.approx(d["omzet_pct"], abs=0.15)


def test_rollend_venster_houdt_het_gemiddelde_op_periodeniveau(client):
    """Bij winkelniveau wordt het winkelaantal over een venster geteld; de
    omzet moet dan over hetzelfde venster, anders zakt het gemiddelde met een
    factor drie (1 maand omzet gedeeld door 3 maanden winkels)."""
    import seed
    blocks = {"DEPEND": {str(7000 + w): {f"2026{m:02d}": 300.0 for m in range(1, 7)}
                         for w in range(1, 11)}}
    upload(client, "Maandelijkse_resultaten_ICI_venster.xlsx", seed.make_ici_xlsx(blocks))
    t = client.get("/api/ici-paris-xl/dashboard").json()["tijdlijn"]
    assert t["venster"] == 3
    serie = t["per_merk"][0]
    # 10 winkels x 300 = 3000 per maand, 10 winkels -> 300 per winkel per maand.
    assert serie["per_winkel"][-1] == pytest.approx(300.0)
    assert serie["winkels"][-1] == 10


@pytest.mark.skipif(not REAL_ICI.exists(), reason="echt sample-bestand niet aanwezig")
def test_echte_ici_decompositie_reproduceert_auditcijfers(client):
    upload(client, REAL_ICI.name[9:], REAL_ICI.read_bytes())
    t = client.get("/api/ici-paris-xl/dashboard").json()["tijdlijn"]
    assert t["vergelijking"] == {"nu": "2026-07", "vorig": "2025-07"}
    per = {d["merk"]: d for d in t["decompositie"]["per_merk"]}
    tw = per["TWEEZERMAN"]
    assert (tw["omzet_pct"], tw["winkels_pct"], tw["per_winkel_pct"]) == \
        pytest.approx((32.6, -0.7, 33.5), abs=0.2)
    dp = per["DEPEND"]
    assert (dp["omzet_pct"], dp["winkels_pct"], dp["per_winkel_pct"]) == \
        pytest.approx((63.8, 14.6, 42.9), abs=0.2)


def test_winkelaantal_endpoint_valideert(client):
    goed = {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
            "aantal_winkels": 500, "geldig_vanaf": "2026-01-01"}
    assert client.post("/api/kruidvat/winkelaantallen", json=goed).status_code == 200
    assert client.post("/api/kruidvat/winkelaantallen",
                       json={**goed, "aantal_winkels": 0}).status_code == 422
    assert client.post("/api/kruidvat/winkelaantallen",
                       json={**goed, "geldig_vanaf": "gisteren"}).status_code == 422
    assert client.post("/api/kruidvat/winkelaantallen",
                       json={**goed, "geldig_vanaf": "2099-01-01"}).status_code == 422
    assert client.post("/api/bestaatniet/winkelaantallen", json=goed).status_code == 404

    # Zelfde scope + datum overschrijft, stapelt niet.
    client.post("/api/kruidvat/winkelaantallen", json={**goed, "aantal_winkels": 480})
    hist = client.get("/api/kruidvat/instellingen").json()["winkels_historie"]
    op_die_datum = [h for h in hist if h["geldig_vanaf"] == "2026-01-01"]
    assert len(op_die_datum) == 1 and op_die_datum[0]["aantal_winkels"] == 480

    # En verwijderen kan.
    assert client.delete(f"/api/kruidvat/winkelaantallen/{op_die_datum[0]['id']}").status_code == 200
    assert client.get("/api/kruidvat/instellingen").json()["winkels_historie"] == []
