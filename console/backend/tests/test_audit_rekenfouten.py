"""Rekenfouten die de audit op de ECHTE bestanden reproduceerde.

Elke test legt een gerepareerde fout vast:

  * een niet-geladen kwartaal telde als nul omzet in de YTD-vergelijking
    (-46,4% op de echte Etos-bestanden, zonder enige melding)
  * een merk zonder geladen vorig jaar maakte élk artikel "NIEUW" (156 op
    de echte Kruidvat-bestanden); een merk-feed die achterloopt maakte
    gezonde artikelen "DELISTED?" en gaf YTD-delta's tot -100%
  * de assortimentsrotatie deelde elk artikel door het retailer-brede
    winkelbestand (1300) in plaats van de eigen scope (900) — valse delists
  * de uplift-basislijn telde de lopende periode mee
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


def _dwh(rows, **kw) -> bytes:
    import seed
    return seed.make_dwh_xlsx(rows, **kw)


def _art(sku, gtin, brand, weeks):
    return {"sku": sku, "gtin": gtin, "desc": f"Artikel {sku}",
            "brand": brand, "weeks": weeks}


# ------------------------------------------------ YTD: doorsnede, geen range

def test_vergeten_kwartaal_telt_niet_als_omzetdaling(client):
    """2025 volledig geladen, van 2026 ontbreken week 5 t/m 8 (een vergeten
    bestand). Het bereik 1..12 zou die weken als nul meetellen en -33%
    melden; de doorsnede vergelijkt alleen de weken die er in beide jaren
    zíjn — en meldt wat er binnen het venster ontbreekt."""
    vorig = {f"2025{w:02d}": (10, 100.0) for w in range(1, 13)}
    dit = {f"2026{w:02d}": (10, 100.0) for w in list(range(1, 5)) + list(range(9, 13))}
    upload(client, "DWH__Sales_Tweezerman_KVNL_gat.xlsx",
           _dwh([_art("31210001", "4049469072773", "TWEEZERMAN", {**vorig, **dit})]))

    y = client.get("/api/kruidvat/dashboard").json()["ytd"]
    assert y["omzet"]["delta_pct"] == 0.0
    v = y["basis"]["vergelijkbaar"][0]
    assert v["ontbrekend"] == [5, 6, 7, 8]
    assert not y["basis"]["volledig"]
    # De comp-bedragen staan erbij zodat het Δ% narekenbaar is naast de
    # (afwijkende) volledige totalen.
    assert y["basis"]["omzet"] == {"nu": 800.0, "vorig": 800.0}
    assert y["omzet"]["nu"] == 800.0 and y["omzet"]["vorig"] == 1200.0
    # Ook de per-merk regel rekent op dezelfde doorsnede.
    regel = y["per_merk"][0]
    assert regel["omzet"]["delta_pct"] == 0.0
    assert regel["ontbrekend"] == [5, 6, 7, 8]


# ------------------------------------- artikelstatus: historie- en feed-guard

def test_merk_zonder_vorig_jaar_maakt_artikelen_niet_nieuw(client):
    """ALESSANDRO heeft geen 2025 in de database: dat is een gat in de data,
    geen introductie. TWEEZERMAN heeft wél beide jaren, dus dáár is een
    artikel zonder vorig jaar echt nieuw."""
    upload(client, "DWH__Sales_Tweezerman_KVNL_a.xlsx", _dwh([
        _art("31210001", "4049469072773", "TWEEZERMAN",
             {**{f"2025{w:02d}": (10, 100.0) for w in range(1, 9)},
              **{f"2026{w:02d}": (10, 100.0) for w in range(1, 9)}}),
        _art("31210002", "4049469072780", "TWEEZERMAN",
             {f"2026{w:02d}": (10, 100.0) for w in range(1, 9)}),
    ]))
    upload(client, "DWH__Sales_Alessandro_KVNL_a.xlsx", _dwh([
        _art("41210001", "4049469072797", "ALESSANDRO",
             {f"2026{w:02d}": (10, 100.0) for w in range(1, 9)}),
    ]))
    per = {a["ean"]: a for a in client.get("/api/kruidvat/artikelen").json()["artikelen"]}
    assert per["4049469072780"]["status"] == "nieuw"      # merk mét historie
    assert per["4049469072797"]["status"] is None         # merk zonder 2025
    assert per["4049469072797"]["ytd_delta_pct"] is None


def test_achterlopende_merkfeed_geeft_geen_valse_delisted(client):
    """TWEEZERMAN loopt t/m week 10 terwijl ALESSANDRO t/m week 30 loopt
    (aparte bestanden, echte situatie: 15 weken verschil). Een artikel dat
    binnen de eigen feed gewoon doorverkoopt is niet 'delisted?', en de
    YTD-delta vergelijkt alleen de weken die de feed in beide jaren dekt."""
    upload(client, "DWH__Sales_Alessandro_KVNL_b.xlsx", _dwh([
        _art("41210001", "4049469072797", "ALESSANDRO",
             {**{f"2025{w:02d}": (10, 100.0) for w in range(1, 31)},
              **{f"2026{w:02d}": (10, 100.0) for w in range(1, 31)}}),
    ]))
    upload(client, "DWH__Sales_Tweezerman_KVNL_b.xlsx", _dwh([
        _art("31210001", "4049469072773", "TWEEZERMAN",
             {**{f"2025{w:02d}": (10, 100.0) for w in range(1, 31)},
              **{f"2026{w:02d}": (10, 100.0) for w in range(1, 11)}}),
    ]))
    per = {a["ean"]: a for a in client.get("/api/kruidvat/artikelen").json()["artikelen"]}
    tw = per["4049469072773"]
    # Binnen de eigen feed verkoopt dit artikel elke week: geen twijfelvlag,
    # en geen -66% omdat 2025 verder doorloopt dan de feed van 2026.
    assert tw["status"] is None
    assert tw["ytd_delta_pct"] == 0.0
    # Een artikel dat binnen de geleverde weken stilvalt, blijft wél vlaggen.
    assert per["4049469072797"]["status"] is None


def test_stilgevallen_artikel_blijft_delisted_vraagteken(client):
    """De guard mag het echte signaal niet wegnemen: een artikel dat binnen
    de geleverde weken van zijn eigen merk stilvalt, houdt 'delisted?'."""
    upload(client, "DWH__Sales_Tweezerman_KVNL_c.xlsx", _dwh([
        _art("31210001", "4049469072773", "TWEEZERMAN",
             {**{f"2025{w:02d}": (20, 400.0) for w in range(1, 31)},
              **{f"2026{w:02d}": (20, 400.0) for w in range(1, 31)}}),
        _art("31210004", "4049469072803", "TWEEZERMAN",
             {**{f"2025{w:02d}": (20, 400.0) for w in range(1, 31)},
              **{f"2026{w:02d}": (20, 400.0) for w in range(1, 11)}}),
    ]))
    per = {a["ean"]: a for a in client.get("/api/kruidvat/artikelen").json()["artikelen"]}
    assert per["4049469072803"]["status"] == "delisted?"


# ------------------------------------------------ assortiment: eigen noemer

def test_rotatie_deelt_door_de_eigen_scope(client):
    """TWEEZERMAN ligt alleen in NL (900 winkels); DEPEND in NL én BE
    (900 + 400). Vóór de fix kreeg elk artikel de retailer-brede som 1300
    als noemer — rotatie ~30% te laag en valse delist-adviezen."""
    weken = {f"2026{w:02d}": (450, 900.0) for w in range(1, 11)}
    upload(client, "DWH__Sales_TweezermanDepend_KVNL.xlsx", _dwh([
        _art("31210001", "4049469072773", "TWEEZERMAN", weken),
        _art("51210001", "4049469072810", "DEPEND", weken),
    ]))
    upload(client, "DWH__Sales_Depend_KVBE.xlsx", _dwh([
        _art("51210001", "4049469072810", "DEPEND", weken),
    ], country3="BEL"))
    client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "aantal_winkels": 900},
        {"merk": "DEPEND", "land": "NL", "banner": "KV", "aantal_winkels": 900},
        {"merk": "DEPEND", "land": "BE", "banner": "KV", "aantal_winkels": 400}]})
    client.put("/api/kruidvat/instellingen", json={"rotatie_targets": [
        {"merk": "TWEEZERMAN", "stuks_per_winkel_per_week": 0.5},
        {"merk": "DEPEND", "stuks_per_winkel_per_week": 0.5}]})

    per = {a["ean"]: a for a in client.get("/api/kruidvat/assortiment").json()["artikelen"]}
    tw, dep = per["4049469072773"], per["4049469072810"]
    assert tw["winkels"] == 900
    assert dep["winkels"] == 1300                       # verkoopt écht in beide
    # 450 st/week over 900 winkels = 0,5 = precies op target.
    assert tw["rotatie"] == pytest.approx(0.5)
    assert tw["score"] == 100


# ------------------------------------------------ uplift: afgesloten periodes

def test_uplift_basislijn_zonder_lopende_periode(client, monkeypatch):
    """De lopende week hoort niet in de basislijn (halve omzet drukt de
    mediaan) en een bevestigde lopende week heeft nog geen uplift."""
    import datetime as dt

    from engine import periods

    # "Vandaag" = woensdag in 2026-W08: week 8 loopt nog, 1 t/m 7 zijn af.
    monkeypatch.setattr(periods, "_vandaag_nl",
                        lambda: dt.date.fromisocalendar(2026, 8, 3))
    weken = {f"2026{w:02d}": (10, 100.0) for w in range(1, 8)}
    weken["202605"] = (30, 300.0)                       # de actie
    weken["202608"] = (4, 40.0)                         # lopende (halve) week
    upload(client, "DWH__Sales_Tweezerman_KVNL_u.xlsx",
           _dwh([_art("31210001", "4049469072773", "TWEEZERMAN", weken)]))
    client.put("/api/kruidvat/promoties", json={"bevestigd": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "periode": "2026-W05"},
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "periode": "2026-W08"}]})

    per = {u["periode"]: u for u in client.get("/api/kruidvat/promoties").json()["uplift"]}
    # Basislijn = mediaan van de afgesloten niet-actieweken (allemaal 100):
    # zonder de fix drukte de halve week 8 (40) de basislijn omlaag.
    assert per["2026-W05"]["basislijn"] == 100.0
    assert per["2026-W05"]["uplift_pct"] == 200.0
    assert per["2026-W05"]["basisperiodes"] == 6
    assert per["2026-W08"]["uplift_pct"] is None
    assert per["2026-W08"]["reden"] == "periode loopt nog"
