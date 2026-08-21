"""Wiskundige en statistische correctheid van de analyses.

Elke test hier legt een fout vast die de audit op de ECHTE bestanden vond,
zodat hij niet terug kan komen:

  * winkels als 'nieuw' melden terwijl vorig jaar simpelweg niet geladen is
  * gemiste omzet over een heel jaar tellen terwijl dit jaar tot juli loopt
  * een verkoopmixverschuiving aanzien voor een prijsafslag
  * uplift meten tegen een basislijn uit een ander omzetregime
  * een half ingelezen periode meetellen alsof hij compleet is
  * een net geintroduceerd artikel als delist-kandidaat bestempelen
"""

import datetime as dt
import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import analytics  # noqa: E402
from engine.periods import is_afgesloten  # noqa: E402
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


class Rij(dict):
    """sqlite3.Row-achtig: ontbrekende kolommen geven None in plaats van
    KeyError, net als een echte databaserij."""

    def __getitem__(self, k):
        return dict.get(self, k)


def feit(periode, winkel, merk, omzet, ean=None, volume=0):
    return Rij(periode=periode, winkel_id=winkel, winkel_naam=f"WINKEL {winkel}",
               merk=merk, omzet=omzet, volume=volume, artikel_ean=ean,
               land="NL", banner=None)


CAPS_WINKEL = {"winkel": True, "periode": "maand"}


# ------------------------------------------------- winkels zonder historie

def test_geen_nieuwe_winkels_zonder_vorig_jaar():
    """Zonder vorig jaar is 'vorig jaar geen omzet' geen waarneming maar een
    gat in de data. Op het echte ICI-bestand meldde de app zo 244 nieuwe
    winkels waar er 2 waren."""
    rows = [feit("2026-01", str(w), "DEPEND", 100.0) for w in range(1, 11)]
    w = analytics.winkelanalyse(rows, CAPS_WINKEL, 2026)
    assert w["toegevoegd"] == []
    assert w["historie_ontbreekt"] == ["DEPEND"]


def test_nieuwe_winkel_wel_gemeld_met_historie():
    rows = [feit("2025-01", "1", "DEPEND", 100.0), feit("2026-01", "1", "DEPEND", 110.0),
            feit("2026-01", "2", "DEPEND", 40.0)]      # winkel 2 is echt nieuw
    w = analytics.winkelanalyse(rows, CAPS_WINKEL, 2026)
    assert [a["winkel_id"] for a in w["toegevoegd"]] == ["2"]
    assert w["historie_ontbreekt"] == []


# ------------------------------------------------- gemiste omzet in venster

def test_gemiste_omzet_telt_alleen_het_stilstandvenster():
    """Winkel verkoopt in januari nog, daarna niets. Gemist is wat hij in
    februari+maart vorig jaar deed — niet zijn hele vorige jaar, want de
    maanden april t/m december moeten dit jaar nog komen."""
    rows = [
        feit("2025-01", "1", "DEPEND", 100.0), feit("2025-02", "1", "DEPEND", 200.0),
        feit("2025-03", "1", "DEPEND", 300.0), feit("2025-11", "1", "DEPEND", 999.0),
        feit("2026-01", "1", "DEPEND", 90.0),
        # tweede winkel houdt de maandreeks van 2026 op de been
        feit("2026-01", "2", "DEPEND", 10.0), feit("2026-02", "2", "DEPEND", 10.0),
        feit("2026-03", "2", "DEPEND", 10.0),
    ]
    w = analytics.winkelanalyse(rows, CAPS_WINKEL, 2026)
    g = next(x for x in w["gestopt"] if x["winkel_id"] == "1")
    assert g["gemist_zelfde_venster"] == pytest.approx(500.0)   # feb 200 + mrt 300
    assert g["omzet_vorig_jaar"] == pytest.approx(1599.0)       # inclusief november
    assert w["gemiste_omzet"] == pytest.approx(500.0)


# ------------------------------------------------- prijsindex vs mixeffect

def _key(r):
    return (r["merk"], r["land"], None)


def test_prijsindex_negeert_verkoopmix():
    """Twee artikelen met een ONVERANDERLIJKE prijs (€ 5 en € 25). In week 2
    verkoopt het goedkope artikel veel meer: de gemengde stukprijs keldert,
    maar er is niets afgeprijsd. De index moet vlak blijven."""
    rows = []
    for periode, (goedkoop, duur) in {"2026-W01": (10, 10), "2026-W02": (90, 10)}.items():
        rows.append(feit(periode, None, "X", 5.0 * goedkoop, ean="1111", volume=goedkoop))
        rows.append(feit(periode, None, "X", 25.0 * duur, ean="2222", volume=duur))

    gemengd = {p: sum(r["omzet"] for r in rows if r["periode"] == p)
                  / sum(r["volume"] for r in rows if r["periode"] == p)
               for p in ("2026-W01", "2026-W02")}
    assert gemengd["2026-W02"] < gemengd["2026-W01"] * 0.6   # "daling" van >40%

    index = analytics.prijsindex(rows, _key)[("X", "NL", None)]
    assert index["2026-W01"] == pytest.approx(index["2026-W02"]), \
        "vaste prijzen horen een vlakke index te geven"


def test_prijsindex_ziet_echte_afprijzing():
    rows = []
    for periode, prijs in {"2026-W01": 5.0, "2026-W02": 5.0, "2026-W03": 3.0}.items():
        rows.append(feit(periode, None, "X", prijs * 100, ean="1111", volume=100))
        rows.append(feit(periode, None, "X", 25.0 * 10, ean="2222", volume=10))
    index = analytics.prijsindex(rows, _key)[("X", "NL", None)]
    assert index["2026-W03"] < index["2026-W01"] * 0.95


def test_prijsindex_vergelijkt_binnen_hetzelfde_jaar():
    """Een prijspeil dat over de jaren stijgt mag oudere jaren niet
    structureel als 'afgeprijsd' bestempelen."""
    rows = []
    for jaar, prijs in ((2025, 10.0), (2026, 20.0)):
        for wk in (1, 2, 3):
            rows.append(feit(f"{jaar}-W{wk:02d}", None, "X", prijs * 50,
                             ean="1111", volume=50))
    index = analytics.prijsindex(rows, _key)[("X", "NL", None)]
    # Elk jaar heeft zijn eigen niveau; binnen het jaar is er geen daling.
    assert index["2025-W01"] == pytest.approx(10.0)
    assert index["2026-W01"] == pytest.approx(20.0)


# ------------------------------------------------- uplift-basislijn

def test_uplift_zonder_genoeg_basisperiodes(client):
    """Eén referentieweek is geen basislijn; dan liever geen percentage dan
    een percentage dat toeval meet."""
    import seed
    upload(client, "DWH__Sales_Tweezerman_KVNL_kort.xlsx", seed.make_dwh_xlsx([{
        "sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
        "brand": "TWEEZERMAN", "weeks": {"202601": (10, 100.0), "202602": (10, 100.0)}}]))
    client.put("/api/kruidvat/promoties", json={"bevestigd": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "periode": "2026-W02"}]})
    u = client.get("/api/kruidvat/promoties").json()["uplift"][0]
    assert u["uplift_pct"] is None and u["reden"] == "te weinig basisperiodes"
    assert u["basisperiodes"] == 1


def test_uplift_basislijn_blijft_binnen_hetzelfde_jaar(client):
    """Kruidvat draaide in 2024 EUR 33k per week en in 2025 EUR 47k. Een
    actie mag niet tegen het gemiddelde van beide regimes gemeten worden."""
    import seed

    def wk(jaar, weken, waarde):
        return {f"{jaar}{w:02d}": (10, waarde) for w in weken}

    weeks = {}
    weeks.update(wk(2025, range(1, 6), 1000.0))     # mager jaar
    weeks.update(wk(2026, range(1, 6), 5000.0))     # rijk jaar
    weeks["202606"] = (10, 10000.0)                 # de actie
    upload(client, "DWH__Sales_Tweezerman_KVNL_jaren.xlsx", seed.make_dwh_xlsx([{
        "sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
        "brand": "TWEEZERMAN", "weeks": weeks}]))
    client.put("/api/kruidvat/promoties", json={"bevestigd": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "periode": "2026-W06"}]})
    u = next(x for x in client.get("/api/kruidvat/promoties").json()["uplift"]
             if x["periode"] == "2026-W06")
    # Basislijn = mediaan van 2026 (5000), niet van 2025+2026 samen (3000).
    assert u["basislijn"] == pytest.approx(5000.0)
    assert u["uplift_pct"] == pytest.approx(100.0)


# ------------------------------------------------- vergelijkbare YoY-basis

def kv(brand, gtin, sku, weeks):
    """Eén Kruidvat-artikel met de opgegeven weken."""
    import seed
    return seed.make_dwh_xlsx([{"sku": sku, "gtin": gtin, "desc": brand,
                                "brand": brand, "weeks": weeks}])


def test_ytd_delta_alleen_op_vergelijkbare_merken(client):
    """Auditbevinding B1: 2025 bevatte één merk-feed en 2026 drie; het
    dashboard toonde "+42,1%" die vooral 'twee merken erbij' was. Het delta-
    percentage telt nu per merk alleen het venster met data in BEIDE jaren;
    de rest wordt gemeld in plaats van meegeteld."""
    # TWEEZERMAN: beide jaren, maar de 2026-feed stopt op week 10.
    upload(client, "DWH__Sales_Tweezerman_KVNL_a.xlsx",
           kv("TWEEZERMAN", "31210001", "31210001",
              {"202505": (10, 100.0), "202510": (10, 100.0), "202515": (10, 300.0),
               "202605": (10, 150.0), "202610": (10, 150.0)}))
    # ALESSANDRO: alleen 2026, t/m week 20.
    upload(client, "DWH__Sales_Alessandro_KVNL_b.xlsx",
           kv("ALESSANDRO", "31210003", "31210003",
              {"202605": (5, 500.0), "202620": (5, 500.0)}))

    y = client.get("/api/kruidvat/dashboard").json()["ytd"]
    # Absolute totalen tellen alles (feitelijk juist): 2026 = 150+150+500+500.
    assert y["omzet"]["nu"] == pytest.approx(1300.0)
    # Delta alleen TWEEZERMAN, en dan t/m diens eigen laatste week (10):
    # 2026 (300) vs 2025 wk<=10 (200) = +50% — niet +160% over alles.
    assert y["omzet"]["delta_pct"] == pytest.approx(50.0)
    assert y["basis"]["volledig"] is False
    # Het venster is nu een bereik: beide jaren beginnen bij week 5, en de
    # 2026-feed stopt op week 10.
    assert y["basis"]["vergelijkbaar"] == [
        {"merk": "TWEEZERMAN", "van_periode": 5, "tot_periode": 10, "ontbrekend": []}]
    assert y["basis"]["niet_vergelijkbaar"] == ["ALESSANDRO"]

    # De trend meldt dat de TWEEZERMAN-feed eerder stopt dan de rest.
    achter = client.get("/api/kruidvat/dashboard").json()["trend"]["feeds_achter"]
    assert achter == [{"merk": "TWEEZERMAN", "laatste_periode": "2026-W10"}]


def test_elk_percentage_is_na_te_rekenen_uit_zichtbare_bedragen(client):
    """Gemeld vanaf het scherm: "€ 4.419.442 tegen € 1.841.919, +29,2%" — die
    drie getallen rijmen niet. Het percentage stond op de vergelijkbare basis
    (terecht), de bedragen waren de volledige totalen (ook terecht), maar
    samen op één kaart leest dat als een rekenfout.

    Beide percentages horen er te staan MET de twee bedragen waaruit ze
    volgen. Deze test rekent ze allebei na."""
    upload(client, "DWH__Sales_Tweezerman_KVNL_a.xlsx",
           kv("TWEEZERMAN", "31210001", "31210001",
              {"202505": (10, 100.0), "202510": (10, 100.0), "202520": (10, 100.0),
               "202605": (10, 150.0), "202610": (10, 150.0)}))
    upload(client, "DWH__Sales_Alessandro_KVNL_b.xlsx",
           kv("ALESSANDRO", "31210003", "31210003",
              {"202605": (5, 500.0), "202620": (5, 500.0)}))

    o = client.get("/api/kruidvat/dashboard").json()["ytd"]["omzet"]
    # 1. Het percentage van de totalen volgt uit nu en vorig.
    assert o["nu"] == pytest.approx(1300.0) and o["vorig"] == pytest.approx(300.0)
    assert o["totaal_delta_pct"] == pytest.approx(
        (o["nu"] - o["vorig"]) / o["vorig"] * 100, abs=0.05)
    # 2. Het percentage op vergelijkbare basis volgt uit ZIJN bedragen.
    v = o["vergelijkbaar"]
    assert (v["nu"], v["vorig"]) == (pytest.approx(300.0), pytest.approx(200.0))
    assert o["delta_pct"] == pytest.approx(
        (v["nu"] - v["vorig"]) / v["vorig"] * 100, abs=0.05)
    # 3. En ze verschillen hier echt — dat is precies waarom beide er staan.
    assert o["totaal_delta_pct"] != pytest.approx(o["delta_pct"])


def test_zonder_basisverschil_zeggen_beide_percentages_hetzelfde(client):
    """Dekken beide jaren dezelfde periodes, dan is er niets uit te leggen en
    hoort het scherm niet met twee cijfers te komen."""
    upload(client, "DWH__Sales_Tweezerman_KVNL_gelijk.xlsx",
           kv("TWEEZERMAN", "31210001", "31210001",
              {"202505": (10, 100.0), "202605": (10, 150.0)}))
    o = client.get("/api/kruidvat/dashboard").json()["ytd"]["omzet"]
    assert o["delta_pct"] == pytest.approx(o["totaal_delta_pct"])
    assert o["vergelijkbaar"]["nu"] == pytest.approx(o["nu"])


def test_ytd_basis_volledig_bij_samenhangende_feed(client):
    """Eén samenhangende feed (zoals ICI): geen basisregel, gedrag als vanouds."""
    import seed
    upload(client, "Maandelijkse_resultaten_ICI_Paris_XL_2j.xlsx",
           seed.make_ici_xlsx({
               "TWEEZERMAN": {"6051": {"202506": 100.0, "202507": 110.0,
                                       "202606": 120.0, "202607": 130.0}},
               "DEPEND": {"6051": {"202506": 10.0, "202507": 11.0,
                                   "202606": 12.0, "202607": 13.0}}}))
    y = client.get("/api/ici-paris-xl/dashboard").json()["ytd"]
    assert y["basis"]["volledig"] is True
    assert y["basis"]["niet_vergelijkbaar"] == []
    assert y["omzet"]["delta_pct"] == pytest.approx(
        (120 + 130 + 12 + 13 - 100 - 110 - 10 - 11) / (100 + 110 + 10 + 11) * 100, abs=0.1)


def test_ytd_per_merk_op_regelniveau(client):
    """Per merk een eigen YTD-regel, elk binnen zijn EIGEN venster: een merk
    met een kortere feed mag geen schijnbare daling tonen, en een merk zonder
    vorig jaar krijgt geen percentage maar een reden."""
    import seed

    def kv(brand, gtin, sku, weeks):
        return seed.make_dwh_xlsx([{"sku": sku, "gtin": gtin, "desc": brand,
                                    "brand": brand, "weeks": weeks}])

    upload(client, "DWH__Sales_Tweezerman_KVNL_a.xlsx",
           kv("TWEEZERMAN", "31210001", "31210001",
              {"202505": (10, 100.0), "202510": (10, 100.0), "202515": (10, 300.0),
               "202605": (10, 150.0), "202610": (10, 150.0)}))
    upload(client, "DWH__Sales_Alessandro_KVNL_b.xlsx",
           kv("ALESSANDRO", "31210003", "31210003",
              {"202605": (5, 500.0), "202620": (5, 500.0)}))

    per = {m["merk"]: m for m in client.get("/api/kruidvat/dashboard").json()["ytd"]["per_merk"]}
    tw = per["TWEEZERMAN"]
    # Eigen venster t/m week 10: 2026 300 vs 2025 200 = +50%.
    assert tw["vergelijkbaar"] is True and tw["tot_periode"] == 10
    assert tw["omzet"]["nu"] == pytest.approx(300.0)
    assert tw["omzet"]["vorig"] == pytest.approx(200.0)
    assert tw["omzet"]["delta_pct"] == pytest.approx(50.0)
    assert tw["volume"]["delta_pct"] == pytest.approx(0.0)   # 20 vs 20 stuks
    al = per["ALESSANDRO"]
    assert al["vergelijkbaar"] is False and al["omzet"]["delta_pct"] is None
    assert al["reden"] == "geen 2025"
    # Aflopend op omzet: ALESSANDRO (1000) boven TWEEZERMAN (300).
    assert [m["merk"] for m in
            client.get("/api/kruidvat/dashboard").json()["ytd"]["per_merk"]][0] == "ALESSANDRO"


def test_artikelanalyse_merkfilter(client):
    """Merkfilter op de artikelanalyse, zoals op het dashboard."""
    import seed
    upload(client, "DWH__Sales_KVNL_mix.xlsx", seed.make_dwh_xlsx([
        {"sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
         "brand": "TWEEZERMAN", "weeks": {"202632": (10, 100.0)}},
        {"sku": "31210003", "gtin": "4064089040111", "desc": "Striplac",
         "brand": "ALESSANDRO", "weeks": {"202632": (5, 50.0)}}]))

    alles = client.get("/api/kruidvat/artikelen").json()
    assert len(alles["artikelen"]) == 2
    assert alles["filters"]["merk"] == ["ALESSANDRO", "TWEEZERMAN"]

    een = client.get("/api/kruidvat/artikelen?merk=TWEEZERMAN").json()
    assert [a["merk"] for a in een["artikelen"]] == ["TWEEZERMAN"]
    # De filterlijst blijft compleet, ook mét actief filter — anders kan de
    # gebruiker het filter niet meer omzetten.
    assert een["filters"]["merk"] == ["ALESSANDRO", "TWEEZERMAN"]

    leeg = client.get("/api/kruidvat/artikelen?merk=BESTAATNIET").json()
    assert leeg["artikelen"] == [] and leeg["gefilterd"] is True
    assert leeg["filters"]["merk"] == ["ALESSANDRO", "TWEEZERMAN"]


def test_artikelstatus_nieuw_delisted_en_twijfel(client):
    """Statusmarkering per artikel: nieuw, delisted, of 'delisted?' bij
    recente stilte of een omzet die niet past bij het winkelbestand."""
    import seed

    def art(sku, gtin, weeks):
        return {"sku": sku, "gtin": gtin, "desc": f"Artikel {sku}",
                "brand": "TWEEZERMAN", "weeks": weeks}

    vorig = {f"2025{w:02d}": (20, 400.0) for w in range(1, 33)}
    dit = {f"2026{w:02d}": (20, 400.0) for w in range(1, 33)}
    # loper: beide jaren; nieuw: alleen 2026; weg: alleen 2025;
    # stil: 2026 t/m week 10, daarna niets; schrale: hele jaar EUR 50/week.
    upload(client, "DWH__Sales_Tweezerman_KVNL_status.xlsx", seed.make_dwh_xlsx([
        art("31210001", "31210001", {**vorig, **dit}),
        art("31210002", "31210002", dit),
        art("31210003", "31210003", vorig),
        art("31210004", "31210004",
            {**{f"2025{w:02d}": (20, 400.0) for w in range(1, 33)},
             **{f"2026{w:02d}": (20, 400.0) for w in range(1, 11)}}),
        art("31210005", "31210005",
            {**{f"2025{w:02d}": (2, 50.0) for w in range(1, 33)},
             **{f"2026{w:02d}": (2, 50.0) for w in range(1, 33)}}),
    ]))
    # 530 winkels: EUR 400 per week is EUR 0,75 per winkel per week (gezond),
    # EUR 50 per week is EUR 0,09 — precies het geval uit de praktijk.
    client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "aantal_winkels": 530}]})

    per = {a["ean"]: a for a in client.get("/api/kruidvat/artikelen").json()["artikelen"]}
    assert per["31210001"]["status"] is None            # gewone loper
    assert per["31210002"]["status"] == "nieuw"
    assert "2025" in per["31210002"]["status_reden"]
    assert per["31210003"]["status"] == "delisted"
    assert per["31210004"]["status"] == "delisted?"
    assert "laatste 13 weken" in per["31210004"]["status_reden"]
    schraal = per["31210005"]
    assert schraal["status"] == "delisted?"
    assert "per winkel per week" in schraal["status_reden"]
    assert schraal["omzet_per_winkel_per_week"] == pytest.approx(50 / 530, abs=0.01)


def test_artikelstatus_zonder_winkelaantal_geen_valse_twijfel(client):
    """Zonder winkelaantal is 'te weinig per winkel' niet te berekenen; dan
    hoort er geen twijfelvlag te staan in plaats van een gegokte."""
    import seed
    upload(client, "DWH__Sales_Tweezerman_KVNL_zonder.xlsx", seed.make_dwh_xlsx([
        {"sku": "31210001", "gtin": "4049469072773", "desc": "S", "brand": "TWEEZERMAN",
         "weeks": {**{f"2025{w:02d}": (2, 50.0) for w in range(1, 33)},
                   **{f"2026{w:02d}": (2, 50.0) for w in range(1, 33)}}}]))
    a = client.get("/api/kruidvat/artikelen").json()["artikelen"][0]
    assert a["status"] is None and a["omzet_per_winkel_per_week"] is None


# ------------------------------------------------- instellingen-rijen

def test_instellingen_feed_combinaties_en_rij_toevoegen(client):
    """Auditbevinding B2: op een verse installatie waren de instellingen-
    tabellen leeg en onuitbreidbaar. De API levert nu de combinaties uit de
    feed, en een toegevoegde rij werkt direct door op het dashboard."""
    import seed
    upload(client, "DWH__Sales_Tweezerman_KVNL_32.xlsx",
           seed.make_dwh_xlsx(seed._kv_demo_rows(["202632"])))

    inst = client.get("/api/kruidvat/instellingen").json()
    combos = {(c["merk"], c["land"], c["banner"]) for c in inst["feed_combinaties"]}
    assert ("TWEEZERMAN", "NL", "KV") in combos
    assert inst["winkels_targets"] == []          # verse installatie: leeg

    r = client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
         "aantal_winkels": 900, "target_per_winkel": 45.0}]})
    assert r.status_code == 200
    k = client.get("/api/kruidvat/dashboard").json()["kpi"]["omzet_per_winkel"]
    assert k["winkels"] == 900 and k["schatting"] is True


# ------------------------------------------------- filter-lege staat (B4)

def test_filter_zonder_resultaat_houdt_filters_bedienbaar(client):
    """Auditbevinding B4: bij nul rijen ná filteren verdwenen de filterchips
    en zei het scherm "nog geen data geïmporteerd" — een doodlopende staat."""
    import seed
    upload(client, "DWH__Sales_Tweezerman_KVNL_32.xlsx",
           seed.make_dwh_xlsx(seed._kv_demo_rows(["202632"])))
    r = client.get("/api/kruidvat/dashboard?merk=BESTAATNIET").json()
    assert r["empty"] is True and r["gefilterd"] is True
    assert "TWEEZERMAN" in r["filters"]["merk"], "chips moeten bedienbaar blijven"
    # Écht lege retailer: geen 'gefilterd', wel de gewone lege staat.
    leeg = client.get("/api/douglas/dashboard").json()
    assert leeg.get("available") is False or leeg.get("gefilterd") in (False, None)


# ------------------------------------------------- target per winkel (B5)

def test_target_per_winkel_zichtbaar_in_breakdown(client):
    """Auditbevinding B5: het targetveld werd opgeslagen maar nergens
    gebruikt. Het staat nu per merk in de omzet-per-winkel-uitsplitsing."""
    import seed
    upload(client, "Maandelijkse_resultaten_ICI_Paris_XL_t.xlsx",
           seed.make_ici_xlsx({"TWEEZERMAN": {"6051": {"202607": 100.0},
                                              "6052": {"202607": 60.0}}}))
    client.put("/api/ici-paris-xl/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": None,
         "aantal_winkels": None, "target_per_winkel": 75.0}]})
    b = client.get("/api/ici-paris-xl/dashboard").json()["kpi"]["omzet_per_winkel"]["breakdown"]
    t = next(x for x in b if x["merk"] == "TWEEZERMAN")
    # 160 omzet / 2 winkels = 80 per winkel, target 75 zichtbaar ernaast.
    assert t["waarde"] == pytest.approx(80.0) and t["target"] == pytest.approx(75.0)


def test_artikelanalyse_geeft_jaar_mee(client):
    """Auditbevinding B6: de grafiek hardcodeerde 2025/2026."""
    import seed
    upload(client, "DWH__Sales_Tweezerman_KVNL_32.xlsx",
           seed.make_dwh_xlsx(seed._kv_demo_rows(["202632"])))
    assert client.get("/api/kruidvat/artikelen").json()["jaar"] == 2026


# ------------------------------------------------- distributiesignaal

def test_distributie_uit_handmatig_winkelaantal(client):
    """Kruidvat levert geen winkelniveau: de daling moet blijken uit de
    winkelaantallen die de gebruiker bijhoudt. Elke wijziging wordt bewaard."""
    import seed
    upload(client, "DWH__Sales_Tweezerman_KVNL_32.xlsx",
           seed.make_dwh_xlsx(seed._kv_demo_rows(["202632"])))

    def kaart():
        return next(c for c in client.get("/api/overview").json()["retailers"]
                    if c["id"] == "kruidvat")["signalen"]["distributie"]

    assert kaart()["signaal"] == "grey"          # nog niets ingevuld
    zet = lambda n: client.put("/api/kruidvat/instellingen", json={"winkels_targets": [  # noqa: E731
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "aantal_winkels": n}]})
    zet(912)
    assert kaart()["signaal"] == "grey"          # één meting zegt nog niets
    zet(880)                                     # -3,5%: let op
    s = kaart()
    assert s["signaal"] == "orange" and "912 → 880" in s["tekst"]
    zet(700)                                     # -20%: actie nodig
    assert kaart()["signaal"] == "red"
    zet(900)                                     # weer omhoog
    assert kaart()["signaal"] == "green"

    # De historie is opvraagbaar voor het instellingenscherm.
    hist = client.get("/api/kruidvat/instellingen").json()["winkels_historie"]
    assert [h["aantal_winkels"] for h in hist] == [912, 880, 700, 900]
    # Onveranderd opslaan voegt geen ruis toe aan de historie.
    zet(900)
    assert len(client.get("/api/kruidvat/instellingen").json()["winkels_historie"]) == 4


def test_bestaand_winkelaantal_krijgt_nulmeting(client):
    """Staat er al een winkelaantal in de database zonder historie (zoals op
    de bestaande installatie), dan wordt dát als nulmeting vastgelegd bij de
    eerste opslag. Anders levert de eerste wijziging één punt op en blijft
    het signaal grijs — precies wanneer je de daling wilt zien."""
    import db
    import seed
    upload(client, "DWH__Sales_Tweezerman_KVNL_32.xlsx",
           seed.make_dwh_xlsx(seed._kv_demo_rows(["202632"])))
    # Bootst de bestaande situatie na: een waarde zonder enige historie.
    with db.get_conn() as conn:
        conn.execute("INSERT INTO retailer_settings (retailer_id, merk, land, banner, "
                     "aantal_winkels) VALUES ('kruidvat','TWEEZERMAN','NL','KV',530)")
    client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "aantal_winkels": 470}]})

    hist = client.get("/api/kruidvat/instellingen").json()["winkels_historie"]
    assert [h["aantal_winkels"] for h in hist] == [530, 470]
    s = next(c for c in client.get("/api/overview").json()["retailers"]
             if c["id"] == "kruidvat")["signalen"]["distributie"]
    assert s["signaal"] == "red" and "530 → 470" in s["tekst"]


def test_distributie_uit_de_feiten_bij_winkelniveau(client):
    """ICI levert winkelniveau: dan komt het signaal uit de winkelanalyse
    (gestopte winkels + gemiste omzet), niet uit een handmatig getal."""
    import seed
    blocks = {"DEPEND": {}}
    # Zes winkels die vorig jaar en begin dit jaar verkochten en daarna stil
    # vallen, plus één die doorloopt.
    for w in range(1, 7):
        blocks["DEPEND"][str(7000 + w)] = {
            "202501": 100.0, "202502": 100.0, "202503": 100.0, "202601": 90.0}
    blocks["DEPEND"]["7099"] = {
        "202501": 100.0, "202502": 100.0, "202503": 100.0,
        "202601": 90.0, "202602": 90.0, "202603": 90.0}
    upload(client, "Maandelijkse resultaten ICI Paris XL (dist).xlsx", seed.make_ici_xlsx(blocks))

    s = next(c for c in client.get("/api/overview").json()["retailers"]
             if c["id"] == "ici-paris-xl")["signalen"]["distributie"]
    assert s["signaal"] == "red"                 # 6 gestopte winkels
    assert "6 winkel(s) gestopt" in s["tekst"] and "gemist" in s["tekst"]


# ------------------------------------------------- lopende periode

def test_is_afgesloten_week_en_maand():
    # Week 32 van 2026 loopt t/m zondag 9 augustus.
    assert is_afgesloten("2026-W32", dt.date(2026, 8, 10)) is True
    assert is_afgesloten("2026-W32", dt.date(2026, 8, 9)) is False
    assert is_afgesloten("2026-W32", dt.date(2026, 8, 5)) is False
    # Maand: pas af als de volgende maand begonnen is.
    assert is_afgesloten("2026-07", dt.date(2026, 8, 1)) is True
    assert is_afgesloten("2026-08", dt.date(2026, 8, 31)) is False
    # Jaargrens: week 1 van 2026 loopt t/m 4 januari.
    assert is_afgesloten("2025-W52", dt.date(2026, 1, 2)) is True
    # 2026 heeft 53 ISO-weken (1 januari is een donderdag); die laatste week
    # loopt door tot en met zondag 3 januari 2027.
    assert is_afgesloten("2026-W53", dt.date(2026, 12, 31)) is False
    assert is_afgesloten("2026-W53", dt.date(2027, 1, 4)) is True
    # 2025 heeft er 52: week 53 bestaat daar niet — geen crash, wel 'af'.
    assert is_afgesloten("2025-W53", dt.date(2025, 12, 31)) is True


def test_dashboard_markeert_lopende_periode(client, monkeypatch):
    import seed
    upload(client, "DWH__Sales_Tweezerman_KVNL_wk32.xlsx", seed.make_dwh_xlsx([{
        "sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
        "brand": "TWEEZERMAN", "weeks": {"202631": (10, 100.0), "202632": (4, 40.0)}}]))
    assert client.get("/api/kruidvat/dashboard").json()["laatste_periode_compleet"] is True

    # Alsof het nu midden in week 32 is: de week is dan nog niet af.
    monkeypatch.setattr(analytics, "is_afgesloten",
                        lambda p, vandaag=None: p != "2026-W32")
    # De analysecache kijkt naar de data en de datum. Deze test verandert
    # geen van beide maar het GEDRAG van is_afgesloten — iets wat in
    # productie alleen bij een herstart gebeurt. Cache leegmaken hoort hier
    # dus bij het nabootsen van de klok, niet bij het omzeilen van een bug.
    sys.modules["main"]._ANALYSE_CACHE.clear()
    dash = client.get("/api/kruidvat/dashboard").json()
    assert dash["laatste_periode"] == "2026-W32"
    assert dash["laatste_periode_compleet"] is False
    # De KPI toont de lopende week, maar de YTD rekent t/m week 31.
    assert dash["kpi"]["omzet"]["waarde"] == pytest.approx(40.0)
    assert dash["ytd"]["tot_periode"] == 31
    assert dash["ytd"]["omzet"]["nu"] == pytest.approx(100.0)


# ------------------------------------------------- P3-validaties

def test_week_53_in_52_weekjaar_wordt_geweigerd(client):
    """Auditbevinding B10: 202553 werd stil geaccepteerd terwijl 2025 maar
    52 ISO-weken heeft — een tikfout belandde zo als extra periode in de
    trend. 2026 hééft wel een week 53, die moet blijven werken."""
    import seed

    def kv(week):
        return seed.make_dwh_xlsx([{"sku": "31210001", "gtin": "4049469072773",
                                    "desc": "S", "brand": "TWEEZERMAN",
                                    "weeks": {week: (5, 50.0)}}])

    r = upload(client, "DWH__Sales_Tweezerman_KVNL_w53fout.xlsx", kv("202553"))
    assert r["status"] == "error" and "52 weken" in r["detail"]
    r = upload(client, "DWH__Sales_Tweezerman_KVNL_w53goed.xlsx", kv("202653"))
    assert r["status"] == "ingelezen"


def test_negatief_winkelaantal_is_422(client):
    """Auditbevinding B11: nul/negatief werd geaccepteerd en stil genegeerd."""
    r = client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "aantal_winkels": -5}]})
    assert r.status_code == 422
    r = client.put("/api/kruidvat/instellingen", json={"rotatie_targets": [
        {"merk": "TWEEZERMAN", "stuks_per_winkel_per_week": 0}]})
    assert r.status_code == 422


def test_promo_bevestiging_voor_onbekende_periode_is_422(client):
    """Auditbevinding B12: een bevestiging voor een periode die niet in de
    data zit werd onzichtbaar opgeslagen — en zou later, zodra die periode
    geladen wordt, ineens als actie meetellen."""
    import seed
    upload(client, "DWH__Sales_Tweezerman_KVNL_32.xlsx",
           seed.make_dwh_xlsx(seed._kv_demo_rows(["202632"])))
    r = client.put("/api/kruidvat/promoties", json={"bevestigd": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "periode": "2031-W01"}]})
    assert r.status_code == 422 and "2031-W01" in r.json()["detail"]
    # Een bestaande periode blijft gewoon werken.
    r = client.put("/api/kruidvat/promoties", json={"bevestigd": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "periode": "2026-W32"}]})
    assert r.status_code == 200


def test_onleesbaar_bestand_krijgt_eigen_melding(client):
    """Auditbevinding B14: een corrupt bestand kreeg dezelfde melding als een
    onbekend formaat ("deel het bestand voor een parser")."""
    r = upload(client, "kapot.xlsx", b"dit is geen spreadsheet")
    assert r["status"] == "profiel_nodig" and "niet als tabel gelezen" in r["detail"]
    ctrl = client.post("/api/import/controle", files=[
        ("files", ("kapot.xlsx", b"dit is geen spreadsheet"))]).json()["results"][0]
    assert "niet als tabel gelezen" in ctrl["detail"]
    # Een leesbaar maar onbekend formaat houdt de parser-uitleg.
    import io
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["Week", "Merk", "Omzet"]); ws.append(["2026-W32", "X", 1.0])
    buf = io.BytesIO(); wb.save(buf)
    r = upload(client, "onbekend_formaat.xlsx", buf.getvalue())
    assert "parser" in r["detail"]


# ------------------------------------------------- rotatie

def test_nieuw_artikel_is_geen_delist_kandidaat(client):
    """Een artikel dat pas in week 30 in het schap ligt, mag niet door het
    hele jaar gedeeld worden en geen delist-oordeel krijgen."""
    import seed
    upload(client, "DWH__Sales_Tweezerman_KVNL_mix.xlsx", seed.make_dwh_xlsx([
        {"sku": "31210001", "gtin": "4049469072773", "desc": "Loper",
         "brand": "TWEEZERMAN", "weeks": {f"2026{w:02d}": (100, 1000.0)
                                          for w in range(1, 31)}},
        {"sku": "31210009", "gtin": "4049469072780", "desc": "Nieuwkomer",
         "brand": "TWEEZERMAN", "weeks": {"202630": (100, 1000.0)}},
    ]))
    client.put("/api/kruidvat/instellingen", json={
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": 10, "target_per_winkel": 45.0}],
        "rotatie_targets": [{"merk": "TWEEZERMAN", "stuks_per_winkel_per_week": 10.0}]})
    per_ean = {a["ean"]: a for a in client.get("/api/kruidvat/assortiment").json()["artikelen"]}
    nieuw = per_ean["31210009"]
    assert nieuw["advies"] == "Te kort geleden geïntroduceerd"
    assert nieuw["score"] is None
    # De loper wordt gewoon beoordeeld: 100 stuks / 10 winkels = 10 per week.
    loper = per_ean["31210001"]
    assert loper["rotatie"] == pytest.approx(10.0)
    assert loper["advies"] == "Op target"


# ------------------------------------------------------- contract-uploads

def test_contract_upload_zonder_api_key_geeft_422(client, monkeypatch):
    """Zonder sleutel (noch database, noch omgeving) mag de upload nooit een
    halve of verzonnen analyse opslaan — een nette 422 in plaats van een
    crash."""
    from engine import contracts

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(contracts, "pdf_tekst", lambda content: "contracttekst")
    r = client.post("/api/ici-paris-xl/contract",
                    files={"file": ("contract.pdf", b"x", "application/pdf")})
    assert r.status_code == 422
    assert "sleutel" in r.text
    inst = client.get("/api/ici-paris-xl/instellingen").json()
    assert "sharepoint" not in inst
    assert inst["documenten"] == []


def test_contract_upload_vervangt_vorig_contract(client, monkeypatch):
    """Een nieuwe upload vervangt het vorige contract van die retailer: geen
    geschiedenis, en het signaal wordt live herberekend uit geldig_tot."""
    from engine import contracts

    antwoorden = iter([
        {"naam": "Jaarcontract 2026", "type": "contract", "geldig_tot": "2035-01-01",
         "conclusie": "Loopt nog.", "condities": [{"onderwerp": "Betaling", "afspraak": "30 dagen"}]},
        {"naam": "Jaarcontract 2027", "type": "contract", "geldig_tot": "2020-01-01",
         "conclusie": "Verlopen.", "condities": []},
    ])
    monkeypatch.setattr(contracts, "analyseer", lambda conn, tekst, vandaag=None: next(antwoorden))
    monkeypatch.setattr(contracts, "pdf_tekst", lambda content: "contracttekst")

    r1 = client.post("/api/ici-paris-xl/contract",
                     files={"file": ("c1.pdf", b"x", "application/pdf")}).json()
    assert r1["ok"] is True and r1["document"]["naam"] == "Jaarcontract 2026"
    inst = client.get("/api/ici-paris-xl/instellingen").json()
    assert len(inst["documenten"]) == 1
    assert inst["documenten"][0]["condities"] == [{"onderwerp": "Betaling", "afspraak": "30 dagen"}]
    kaart = next(c for c in client.get("/api/overview").json()["retailers"]
                 if c["id"] == "ici-paris-xl")
    assert kaart["signalen"]["contract"]["signaal"] == "green"

    r2 = client.post("/api/ici-paris-xl/contract",
                     files={"file": ("c2.pdf", b"x", "application/pdf")}).json()
    assert r2["document"]["naam"] == "Jaarcontract 2027"
    inst2 = client.get("/api/ici-paris-xl/instellingen").json()
    assert len(inst2["documenten"]) == 1
    assert inst2["documenten"][0]["naam"] == "Jaarcontract 2027"
    kaart2 = next(c for c in client.get("/api/overview").json()["retailers"]
                  if c["id"] == "ici-paris-xl")
    assert kaart2["signalen"]["contract"]["signaal"] == "red"


def test_contract_upload_bewaart_vorige_in_historie(client, monkeypatch):
    """Een vervangen contract wordt niet weggegooid: het blijft opvraagbaar
    in de historie, zodat een verkeerde extractie terug te draaien is."""
    from engine import contracts

    antwoorden = iter([
        {"naam": "Eerste contract", "type": "contract", "geldig_tot": "2035-01-01",
         "conclusie": "Loopt nog.", "condities": []},
        {"naam": "Tweede contract", "type": "contract", "geldig_tot": "2020-01-01",
         "conclusie": "Verlopen.", "condities": []},
    ])
    monkeypatch.setattr(contracts, "analyseer", lambda conn, tekst, vandaag=None: next(antwoorden))
    monkeypatch.setattr(contracts, "pdf_tekst", lambda content: "contracttekst")

    assert client.get("/api/ici-paris-xl/contract/historie").json()["historie"] == []
    client.post("/api/ici-paris-xl/contract",
               files={"file": ("c1.pdf", b"x", "application/pdf")})
    assert client.get("/api/ici-paris-xl/contract/historie").json()["historie"] == []

    client.post("/api/ici-paris-xl/contract",
               files={"file": ("c2.pdf", b"x", "application/pdf")})
    historie = client.get("/api/ici-paris-xl/contract/historie").json()["historie"]
    assert len(historie) == 1
    assert historie[0]["naam"] == "Eerste contract"
    # Het actuele contract is nu het tweede — de historie is puur archief.
    actueel = client.get("/api/ici-paris-xl/instellingen").json()["documenten"]
    assert actueel[0]["naam"] == "Tweede contract"


def test_analyseer_verwerpt_onwaarschijnlijke_datum(client, monkeypatch):
    """Een geëxtraheerde einddatum die >15 jaar van vandaag ligt is
    vrijwel zeker een verkeerd gelezen of gehallucineerde datum, geen
    echte contractlooptijd — hij mag het automatische signaal niet
    aansturen, maar blijft zichtbaar zodat een mens het kan controleren."""
    import json as _json

    import db as db_mod
    from engine import contracts

    class NepBlok:
        type = "text"
        text = _json.dumps({
            "naam": "Contract X", "type": "contract", "geldig_tot": "2099-01-01",
            "conclusie": "Loopt nog.", "condities": [],
        })

    class NepResponse:
        content = [NepBlok()]

    class NepMessages:
        @staticmethod
        def create(**kwargs):
            return NepResponse()

    class NepAnthropic:
        def __init__(self, api_key=None):
            self.messages = NepMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.setattr("anthropic.Anthropic", NepAnthropic)

    with db_mod.get_conn() as conn:
        gevonden = contracts.analyseer(conn, "contracttekst", vandaag=dt.date(2026, 8, 20))
    assert gevonden["geldig_tot"] is None
    assert "onwaarschijnlijk" in gevonden["conclusie"]
    assert "2099-01-01" in gevonden["conclusie"]  # ruwe waarde blijft zichtbaar


# ------------------------------------------------ Anthropic-sleutelbeheer

def test_haal_api_key_database_wint_van_omgeving(client, monkeypatch):
    from engine import contracts
    import db as db_mod

    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-sleutel")
    with db_mod.get_conn() as conn:
        assert contracts.haal_api_key(conn) == ("env-sleutel", "omgeving")
        conn.execute("UPDATE anthropic_config SET api_key=? WHERE id=1", ("db-sleutel",))
        assert contracts.haal_api_key(conn) == ("db-sleutel", "database")
        conn.execute("UPDATE anthropic_config SET api_key=? WHERE id=1", ("",))
        assert contracts.haal_api_key(conn) == ("env-sleutel", "omgeving")

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with db_mod.get_conn() as conn:
        assert contracts.haal_api_key(conn) == (None, "geen")


def test_anthropic_key_opslaan_en_testen(client, monkeypatch):
    from engine import contracts

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r0 = client.get("/api/systeem/anthropic").json()
    assert r0 == {"ingesteld": False, "gemaskeerd": None, "bron": "geen",
                  "bijgewerkt_op": None, "bijgewerkt_door": None,
                  "laatst_getest_op": None, "laatst_status": None, "laatst_melding": None}

    monkeypatch.setattr(contracts, "test_sleutel", lambda k: (True, "Werkt"))
    r1 = client.put("/api/systeem/anthropic", json={"api_key": "sk-ant-abcdefghijklmnop"}).json()
    assert r1["ingesteld"] is True
    assert r1["bron"] == "database"
    assert r1["gemaskeerd"] == "sk-ant-abc…mnop"
    assert "sk-ant-abcdefghijklmnop" not in json.dumps(r1)
    assert r1["laatst_status"] == "ok"

    monkeypatch.setattr(contracts, "test_sleutel", lambda k: (False, "Ongeldige sleutel (authenticatie mislukt)"))
    r2 = client.post("/api/systeem/anthropic/test").json()
    assert r2["ingesteld"] is True and r2["gemaskeerd"] == r1["gemaskeerd"]
    assert r2["laatst_status"] == "fout"
    assert "Ongeldige sleutel" in r2["laatst_melding"]

    r3 = client.put("/api/systeem/anthropic", json={"api_key": ""}).json()
    assert r3["ingesteld"] is False and r3["bron"] == "geen"


# --------------------------------------------------------------- YTD-overlap

def _kv_jaar(client, naam, jaar, weken, merk="ALESSANDRO", omzet=1000.0):
    import seed
    from test_parser_flow import upload as _up
    _up(client, naam, seed.make_dwh_xlsx(
        [{"sku": "6369354", "gtin": "4049469072773", "desc": "STRIPLAC",
          "brand": merk, "weeks": {f"{jaar}{w:02d}": (100, omzet) for w in weken}}],
        country3="BEL", formula="KV"))


def test_ytd_zonder_overlap_is_niet_vergelijkbaar(client):
    """2025 begint pas in week 40, 2026 loopt tot week 33 — die weken raken
    elkaar nergens. Vroeger heette dat 'vergelijkbaar' omdat het merk in beide
    jaren voorkwam, en toonde het scherm '€ 0' zonder enige melding."""
    _kv_jaar(client, "a.xlsx", 2025, range(40, 53))
    _kv_jaar(client, "b.xlsx", 2026, range(1, 34), omzet=1200.0)

    y = client.get("/api/kruidvat/dashboard").json()["ytd"]
    assert y["basis"]["volledig"] is False
    assert y["basis"]["vergelijkbaar"] == []
    assert y["basis"]["niet_vergelijkbaar"] == ["ALESSANDRO"]
    assert y["omzet"]["delta_pct"] is None
    # De dekking maakt zichtbaar waar de data wél zit.
    assert y["dekking"]["2025"] == {"van": 40, "tot": 52}
    assert y["dekking"]["2026"] == {"van": 1, "tot": 33}
    regel = y["per_merk"][0]
    assert regel["vergelijkbaar"] is False
    assert "week 40 t/m 52" in regel["reden"] and "geen gedeelde week" in regel["reden"]


def test_ytd_gedeeltelijke_overlap_knipt_beide_jaren_bij(client):
    """2025 vanaf week 26, 2026 t/m week 31: vergelijk week 26 t/m 31 in
    beide jaren. Vroeger werd 31 weken tegen 6 weken afgezet — op de echte
    Belgische data gaf dat +886,9%."""
    _kv_jaar(client, "a.xlsx", 2025, range(26, 53), omzet=1000.0)
    _kv_jaar(client, "b.xlsx", 2026, range(1, 32), omzet=1200.0)

    y = client.get("/api/kruidvat/dashboard").json()["ytd"]
    assert y["basis"]["vergelijkbaar"] == [
        {"merk": "ALESSANDRO", "van_periode": 26, "tot_periode": 31, "ontbrekend": []}]
    # Zes gedeelde weken: 6 x 1200 tegen 6 x 1000.
    assert y["omzet"]["delta_pct"] == pytest.approx(20.0)
    assert y["basis"]["volledig"] is False


def test_ytd_volledige_overlap_verandert_niet(client):
    """De gewone situatie moet zich gedragen als voorheen: venster 1..upto,
    basis volledig, en hetzelfde percentage."""
    _kv_jaar(client, "a.xlsx", 2025, range(1, 32), omzet=1000.0)
    _kv_jaar(client, "b.xlsx", 2026, range(1, 32), omzet=1200.0)

    y = client.get("/api/kruidvat/dashboard").json()["ytd"]
    assert y["basis"]["volledig"] is True
    assert y["basis"]["vergelijkbaar"] == [
        {"merk": "ALESSANDRO", "van_periode": 1, "tot_periode": 31, "ontbrekend": []}]
    assert y["omzet"]["delta_pct"] == pytest.approx(20.0)


def test_merk_zonder_vorig_jaar_blijft_niet_vergelijkbaar(client):
    _kv_jaar(client, "a.xlsx", 2025, range(1, 32), merk="ALESSANDRO")
    _kv_jaar(client, "b.xlsx", 2026, range(1, 32), merk="ALESSANDRO", omzet=1200.0)
    _kv_jaar(client, "c.xlsx", 2026, range(1, 32), merk="TWEEZERMAN", omzet=500.0)

    y = client.get("/api/kruidvat/dashboard").json()["ytd"]
    assert y["basis"]["niet_vergelijkbaar"] == ["TWEEZERMAN"]
    regel = next(r for r in y["per_merk"] if r["merk"] == "TWEEZERMAN")
    assert regel["reden"] == "geen 2025"


# ------------------------------------------------------- negatieve basis

def test_yoy_delta_bij_negatieve_basis_geeft_geen_percentage():
    """Auditbevinding L-2: `(nu - vorig) / vorig` draait van betekenis om bij
    een negatieve basis. Van -100 naar -50 is een VERBETERING, maar de formule
    geeft dan -50%. Geen percentage is eerlijker dan een omgekeerd leesbaar
    percentage. Nul was al correct afgevangen; negatief nu ook.

    Negatieve omzet is bereikbaar: de parsers accepteren correctierijen."""
    import importlib
    import sys as _sys

    _sys.modules.pop("db", None)
    _sys.modules.pop("main", None)
    mod = importlib.import_module("engine.analytics")

    # delta() is een closure in dashboard(); dezelfde regel hier nagerekend
    # zodat de conventie expliciet vastligt.
    def delta(now, prev):
        return round((now - prev) / prev * 100, 1) if prev and prev > 0 else None

    assert delta(120, 100) == 20.0
    assert delta(0, 100) == -100.0
    assert delta(100, 0) is None          # groei vanuit nul is ongedefinieerd
    assert delta(0, 0) is None
    assert delta(-50, -100) is None       # was -50,0 en las als achteruitgang
    assert delta(50, -100) is None
    assert "prev > 0" in inspect.getsource(mod.dashboard), \
        "dashboard.delta() hoort de negatieve basis af te vangen"
