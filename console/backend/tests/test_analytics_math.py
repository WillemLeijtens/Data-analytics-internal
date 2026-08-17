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

def test_ytd_delta_alleen_op_vergelijkbare_merken(client):
    """Auditbevinding B1: 2025 bevatte één merk-feed en 2026 drie; het
    dashboard toonde "+42,1%" die vooral 'twee merken erbij' was. Het delta-
    percentage telt nu per merk alleen het venster met data in BEIDE jaren;
    de rest wordt gemeld in plaats van meegeteld."""
    import seed

    def kv(brand, gtin, sku, weeks):
        return seed.make_dwh_xlsx([{"sku": sku, "gtin": gtin, "desc": brand,
                                    "brand": brand, "weeks": weeks}])

    # TWEEZERMAN: beide jaren, maar de 2026-feed stopt op week 10.
    upload(client, "DWH__Sales_Tweezerman_KVNL_a.xlsx",
           kv("TWEEZERMAN", "4049469072773", "31210001",
              {"202505": (10, 100.0), "202510": (10, 100.0), "202515": (10, 300.0),
               "202605": (10, 150.0), "202610": (10, 150.0)}))
    # ALESSANDRO: alleen 2026, t/m week 20.
    upload(client, "DWH__Sales_Alessandro_KVNL_b.xlsx",
           kv("ALESSANDRO", "4064089040111", "31210003",
              {"202605": (5, 500.0), "202620": (5, 500.0)}))

    y = client.get("/api/kruidvat/dashboard").json()["ytd"]
    # Absolute totalen tellen alles (feitelijk juist): 2026 = 150+150+500+500.
    assert y["omzet"]["nu"] == pytest.approx(1300.0)
    # Delta alleen TWEEZERMAN, en dan t/m diens eigen laatste week (10):
    # 2026 (300) vs 2025 wk<=10 (200) = +50% — niet +160% over alles.
    assert y["omzet"]["delta_pct"] == pytest.approx(50.0)
    assert y["basis"]["volledig"] is False
    assert y["basis"]["vergelijkbaar"] == [{"merk": "TWEEZERMAN", "tot_periode": 10}]
    assert y["basis"]["niet_vergelijkbaar"] == ["ALESSANDRO"]

    # De trend meldt dat de TWEEZERMAN-feed eerder stopt dan de rest.
    achter = client.get("/api/kruidvat/dashboard").json()["trend"]["feeds_achter"]
    assert achter == [{"merk": "TWEEZERMAN", "laatste_periode": "2026-W10"}]


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
           kv("TWEEZERMAN", "4049469072773", "31210001",
              {"202505": (10, 100.0), "202510": (10, 100.0), "202515": (10, 300.0),
               "202605": (10, 150.0), "202610": (10, 150.0)}))
    upload(client, "DWH__Sales_Alessandro_KVNL_b.xlsx",
           kv("ALESSANDRO", "4064089040111", "31210003",
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
    nieuw = per_ean["4049469072780"]
    assert nieuw["advies"] == "Te kort geleden geïntroduceerd"
    assert nieuw["score"] is None
    # De loper wordt gewoon beoordeeld: 100 stuks / 10 winkels = 10 per week.
    loper = per_ean["4049469072773"]
    assert loper["rotatie"] == pytest.approx(10.0)
    assert loper["advies"] == "Op target"


# ------------------------------------------------- geen verzonnen contracten

def test_sharepoint_koppelen_verzint_geen_documenten(client):
    """De mock levert 'Distributieovereenkomst, verloopt 31-08-2026' en dat
    kleurt het Overzicht rood. Zonder CONSOLE_CONTRACTS=mock hoort een
    koppeling geen enkel document op te leveren."""
    r = client.post("/api/ici-paris-xl/sharepoint",
                    json={"map_url": "https://voorbeeld.sharepoint.com/contracten"}).json()
    assert r["ok"] is True and r["documenten"] == [] and r["bron"] == "niet gekoppeld"
    inst = client.get("/api/ici-paris-xl/instellingen").json()
    assert inst["documenten"] == []
    assert inst["sharepoint"]["map_url"].startswith("https://voorbeeld")

    kaart = next(c for c in client.get("/api/overview").json()["retailers"]
                 if c["id"] == "ici-paris-xl")
    assert kaart["signalen"]["contract"]["signaal"] == "grey"


def test_mock_contracten_alleen_met_expliciete_schakelaar(client, monkeypatch):
    monkeypatch.setenv("CONSOLE_CONTRACTS", "mock")
    r = client.post("/api/ici-paris-xl/sharepoint",
                    json={"map_url": "https://voorbeeld.sharepoint.com/contracten"}).json()
    assert r["bron"] == "mock" and len(r["documenten"]) == 2
