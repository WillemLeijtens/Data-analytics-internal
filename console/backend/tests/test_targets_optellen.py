"""Winkeltargets uit Instellingen, opgeteld over de merken in beeld.

Een target is per merk afgesproken (€ per winkel per periode), maar één
filiaal voert die merken naast elkaar. De norm voor dat filiaal is dus de SOM
van de merknormen — en pas tegen die som is te zien of het target gehaald
wordt. De optelling volgt de filters: filter je op één merk, dan hoort daar
ook alleen dat target bij.

Wat hier vastligt:

  * de som staat bij de TOTAAL-reeks van de tijdlijn en op de KPI-kaart;
  * merken zónder ingesteld target worden apart gemeld, niet stil
    overgeslagen — een som over de helft van het assortiment ziet eruit als
    een harde lat en is het niet;
  * per merk blijft het eigen target erbij staan.
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


WEKEN = {f"2026{w:02d}": (100, 1000.0) for w in range(1, 9)}


def _laad(client):
    import seed
    upload(client, "kv.xlsx", seed.make_dwh_xlsx([
        {"sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
         "brand": "TWEEZERMAN", "weeks": WEKEN},
        {"sku": "51210001", "gtin": "4049469072810", "desc": "Nagellak",
         "brand": "DEPEND", "weeks": WEKEN}]))


def _targets(client, tweezerman=85.0, depend=45.0):
    rijen = [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
              "aantal_winkels": 500, "target_per_winkel": tweezerman}]
    if depend is not None:
        rijen.append({"merk": "DEPEND", "land": "NL", "banner": "KV",
                      "aantal_winkels": 500, "target_per_winkel": depend})
    client.put("/api/kruidvat/instellingen", json={"winkels_targets": rijen})


def _dash(client, query=""):
    return client.get(f"/api/kruidvat/dashboard{query}").json()


def test_totaal_telt_de_targets_van_de_merken_in_beeld_op(client):
    _laad(client)
    _targets(client)
    t = _dash(client)["tijdlijn"]["totaal"]
    assert t["target"] == pytest.approx(130.0)          # 85 + 45
    assert t["target_merken"] == [{"merk": "DEPEND", "target": 45.0},
                                  {"merk": "TWEEZERMAN", "target": 85.0}]
    assert t["target_zonder"] == []


def test_het_filter_bepaalt_welke_targets_meetellen(client):
    """Filter je op één merk, dan is de lat het target van dát merk. De
    optelsom van beide merken zou dan een norm opleggen voor omzet die je
    niet eens in beeld hebt."""
    _laad(client)
    _targets(client)
    assert _dash(client, "?merk=DEPEND")["tijdlijn"]["totaal"]["target"] == pytest.approx(45.0)


def test_merk_zonder_target_wordt_gemeld_niet_stil_overgeslagen(client):
    """Anders staat er een lat van € 85 onder een lijn die de omzet van twee
    merken bevat — die haal je moeiteloos, en dat zegt niets."""
    _laad(client)
    _targets(client, depend=None)
    t = _dash(client)["tijdlijn"]["totaal"]
    assert t["target"] == pytest.approx(85.0)
    assert t["target_zonder"] == ["DEPEND"]


def test_zonder_enig_target_staat_er_geen_lat(client):
    _laad(client)
    t = _dash(client)["tijdlijn"]["totaal"]
    assert t["target"] is None
    assert sorted(t["target_zonder"]) == ["DEPEND", "TWEEZERMAN"]


def test_per_merk_houdt_zijn_eigen_target(client):
    _laad(client)
    _targets(client)
    per = {r["merk"]: r for r in _dash(client)["tijdlijn"]["per_merk"]}
    assert per["TWEEZERMAN"]["target"] == pytest.approx(85.0)
    assert per["DEPEND"]["target"] == pytest.approx(45.0)


def test_de_kpi_kaart_krijgt_dezelfde_som(client):
    """De kaart telt de getoonde omzetten zelf op; het target komt van de
    backend, zodat er maar één plek is waar de som gemaakt wordt."""
    _laad(client)
    _targets(client)
    k = _dash(client)["kpi"]["omzet_per_winkel"]
    assert k["target_totaal"] == pytest.approx(130.0)
    assert k["target_zonder"] == []
    # De uitsplitsing per merk houdt zijn eigen target — daar telt het scherm
    # mee op, dus die twee moeten optellen tot het totaal.
    assert sum(b["target"] for b in k["breakdown"]) == pytest.approx(k["target_totaal"])


# ------------------------------------------------ per land en per formule

def _laad_be(client):
    """Dezelfde twee merken, in NL én BE — met een eigen target per land."""
    import seed
    arts = [{"sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
             "brand": "TWEEZERMAN", "weeks": WEKEN},
            {"sku": "51210001", "gtin": "4049469072810", "desc": "Nagellak",
             "brand": "DEPEND", "weeks": WEKEN}]
    upload(client, "kv_nl.xlsx", seed.make_dwh_xlsx(arts))
    upload(client, "kv_be.xlsx", seed.make_dwh_xlsx(arts, country3="BEL"))
    client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
         "aantal_winkels": 1205, "target_per_winkel": 50.0},
        {"merk": "DEPEND", "land": "NL", "banner": "KV",
         "aantal_winkels": 1205, "target_per_winkel": 34.0},
        {"merk": "TWEEZERMAN", "land": "BE", "banner": "KV",
         "aantal_winkels": 187, "target_per_winkel": 120.0},
        {"merk": "DEPEND", "land": "BE", "banner": "KV",
         "aantal_winkels": 187, "target_per_winkel": 70.0}]})


def test_de_landuitsplitsing_krijgt_de_targets_van_dat_land(client):
    """De landregel telt de omzet van de merken in dat land al bij elkaar op,
    dus hoort de lat waar dat tegen afgezet wordt daar net zo bij. En het is
    het target van DAT land: BE 120+70, niet het NL-getal."""
    _laad_be(client)
    per = {b["label"]: b for b in
           _dash(client)["kpi"]["omzet_per_winkel"]["breakdowns"]["land"]}
    assert per["BE"]["target"] == pytest.approx(190.0)
    assert per["NL"]["target"] == pytest.approx(84.0)
    assert per["BE"]["target_merken"] == [{"merk": "DEPEND", "target": 70.0},
                                          {"merk": "TWEEZERMAN", "target": 120.0}]


def test_een_merkregel_weegt_de_landtargets_naar_winkelaantal(client):
    """De merkregel deelt de omzet van beide landen door álle winkels, dus
    hoort de lat dat ook te doen: 1205 NL-winkels a € 50 en 187 BE-winkels a
    € 120 geeft € 59,40.

    Het hoogste getal nemen zou 87% van het winkelbestand langs de Belgische
    lat leggen; optellen zou hetzelfde filiaal twee keer een norm geven."""
    _laad_be(client)
    per = {b["label"]: b for b in
           _dash(client)["kpi"]["omzet_per_winkel"]["breakdown"]}
    assert per["TWEEZERMAN"]["target"] == pytest.approx((1205 * 50 + 187 * 120) / 1392, abs=0.01)
    assert per["DEPEND"]["target"] == pytest.approx((1205 * 34 + 187 * 70) / 1392, abs=0.01)


def test_zonder_winkelaantallen_valt_de_weging_terug_op_het_hoogste_getal(client):
    """Zonder noemer is er niets te wegen. Het hoogste getal is dan de
    veilige keuze: een te lage lat haal je moeiteloos en dat zegt niets."""
    _laad(client)
    client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
         "aantal_winkels": None, "target_per_winkel": 85.0}]})
    per = {b["label"]: b for b in
           _dash(client)["kpi"]["omzet_per_winkel"]["breakdown"]}
    assert per["TWEEZERMAN"]["target"] == pytest.approx(85.0)


def test_op_een_land_gefilterd_gelden_alleen_de_targets_van_dat_land(client):
    _laad_be(client)
    assert _dash(client, "?land=BE")["tijdlijn"]["totaal"]["target"] == pytest.approx(190.0)
    assert _dash(client, "?land=NL")["tijdlijn"]["totaal"]["target"] == pytest.approx(84.0)
