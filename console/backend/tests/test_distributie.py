"""Distributie per artikel: in hoeveel winkels het daadwerkelijk verkocht.

Het aantal verkopende winkels is het vroegste signaal dat een artikel uit het
schap loopt. In de omzet zie je dat pas maanden later, want de winkels die het
nog wél voeren blijven verkopen; het aantal winkels zakt meteen.

Wat hier vastligt:

  * "distributie" is een TELLING uit de feiten (winkels met omzet), geen
    schatting — dus alleen voor retailers die winkelniveau leveren;
  * de jaarvergelijking gebruikt hetzelfde vergelijkbare venster als de
    omzetdelta, anders is een feed die later begon al een "distributiesprong";
  * de tweemaandsvergelijking rekent met GEMIDDELDEN per periode, zodat een
    lopende maand het cijfer niet drukt;
  * een periode waarin het merk wel geleverd is maar dit artikel niets
    verkocht telt als 0 — dat is distributieverlies.
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
    for naam in ("db", "seed", "main"):
        sys.modules.pop(naam, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def _rij(upc, winkel, weeks):
    return {"upc": upc, "naam": f"ARTIKEL {upc}", "merk": "TWEEZERMAN",
            "merk_nr": 2278, "weeks": weeks,
            "winkel": f"ETOS PLAATS {winkel} - {winkel}", "stad": f"Plaats {winkel}"}


def _laad(client, rijen, naam="Data_Grid_57018_winkels.xlsx"):
    import seed
    upload(client, naam, seed.make_etos_xlsx(rijen, winkels=True))


def _per_ean(client):
    d = client.get("/api/etos/artikelen").json()
    return d, {a["ean"]: a for a in d["artikelen"]}


# ------------------------------------------------------- alleen waar het kan

def test_zonder_winkelniveau_geen_distributiekolom(client):
    """Kruidvat levert geen winkel-ID. Een geschat winkelaantal in deze kolom
    zou een telling suggereren die er niet is."""
    import seed
    upload(client, "kv.xlsx", seed.make_dwh_xlsx([
        {"sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
         "brand": "TWEEZERMAN", "weeks": {"202632": (10, 100.0)}}]))
    d = client.get("/api/kruidvat/artikelen").json()
    assert d["distributie_beschikbaar"] is False
    assert d["artikelen"][0]["distributie"] is None


def test_met_winkelniveau_wordt_er_geteld(client):
    """Drie winkels in week 1, twee in week 2 — geen gemiddelde, gewoon de
    winkels met omzet."""
    _laad(client, [
        _rij("120781690", 6001, {"202601": (30.0, 1), "202602": (30.0, 1)}),
        _rij("120781690", 6002, {"202601": (30.0, 1), "202602": (30.0, 1)}),
        _rij("120781690", 6003, {"202601": (30.0, 1)})])
    d, per = _per_ean(client)
    assert d["distributie_beschikbaar"] is True
    assert per["120781690"]["distributie"]["reeks"]["ytd"] == {"1": 3, "2": 2}
    assert per["120781690"]["distributie"]["laatste"] == 2


def test_een_winkel_zonder_omzet_telt_niet_mee(client):
    """De export levert ook 0-regels: gemeten, maar niets verkocht. Dat is
    geen distributie — en precies waarom de kolom telt wat verkocht is."""
    _laad(client, [
        _rij("120781690", 6001, {"202601": (30.0, 1)}),
        _rij("120781690", 6002, {"202601": (0.0, 0)})])
    _, per = _per_ean(client)
    assert per["120781690"]["distributie"]["reeks"]["ytd"] == {"1": 1}


# ------------------------------------------------------------ twee maanden

def _twee_maanden(client):
    """Mei-juni in 3 winkels, juli-augustus in 1: -66,7%."""
    weken_vroeg = {f"2026{w:02d}": (30.0, 1) for w in range(20, 27)}    # mei-juni
    weken_laat = {f"2026{w:02d}": (30.0, 1) for w in range(27, 35)}     # juli-aug
    _laad(client, [
        _rij("120781690", 6001, {**weken_vroeg, **weken_laat}),
        _rij("120781690", 6002, weken_vroeg),
        _rij("120781690", 6003, weken_vroeg)])


def test_twee_maanden_tegen_de_twee_daarvoor(client):
    _twee_maanden(client)
    _, per = _per_ean(client)
    tm = per["120781690"]["distributie"]["twee_maanden"]
    assert tm["nu"] == pytest.approx(1.0)
    assert tm["vorig"] == pytest.approx(3.0)
    assert tm["delta_pct"] == pytest.approx(-66.7)
    assert tm["label"] == "juli-augustus 2026"
    assert tm["vorig_label"] == "mei-juni 2026"


def test_de_tweemaandsvergelijking_is_een_gemiddelde_geen_som(client):
    """Van augustus zijn minder weken geleverd dan van juli. Een som zou de
    laatste maand laten "dalen" puur omdat hij nog loopt."""
    _twee_maanden(client)
    _, per = _per_ean(client)
    tm = per["120781690"]["distributie"]["twee_maanden"]
    # 8 weken in het recente blok, 7 in het vorige — het gemiddelde per week
    # is toch precies 1 tegen 3.
    assert (tm["periodes"], tm["vorige_periodes"]) == (8, 7)


# --------------------------------------------------------------- jaar op jaar

def test_ytd_vergelijkt_alleen_de_weken_die_beide_jaren_geleverd_zijn(client):
    """Vorig jaar begint de feed pas in week 3. De weken 1 en 2 van dit jaar
    zouden er anders als groei uitzien, terwijl er niets te vergelijken is."""
    _laad(client, [
        _rij("120781690", 6001, {"202601": (30.0, 1), "202602": (30.0, 1),
                                 "202603": (30.0, 1), "202604": (30.0, 1)}),
        _rij("120781690", 6002, {"202603": (30.0, 1), "202604": (30.0, 1)})],
        naam="dit_jaar.xlsx")
    _laad(client, [
        _rij("120781690", 6001, {"202503": (30.0, 1), "202504": (30.0, 1)})],
        naam="vorig_jaar.xlsx")
    _, per = _per_ean(client)
    y = per["120781690"]["distributie"]["ytd"]
    # Alleen week 3 en 4: dit jaar 2 winkels, vorig jaar 1.
    assert y["periodes"] == 2
    assert y["nu"] == pytest.approx(2.0)
    assert y["vorig"] == pytest.approx(1.0)
    assert y["delta_pct"] == pytest.approx(100.0)


def test_een_stille_week_telt_als_nul_winkels(client):
    """Het merk is die week wel geleverd, dit artikel verkocht niets. Die week
    overslaan zou het gemiddelde ophouden en distributieverlies verbergen."""
    _laad(client, [
        _rij("120781690", 6001, {"202601": (30.0, 1), "202602": (30.0, 1)}),
        # Tweede artikel houdt de feed van het merk in week 3 in de lucht.
        _rij("120781691", 6001, {"202601": (30.0, 1), "202602": (30.0, 1),
                                 "202603": (30.0, 1)})])
    _, per = _per_ean(client)
    reeks = per["120781690"]["distributie"]["reeks"]["ytd"]
    assert reeks == {"1": 1, "2": 1, "3": 0}


# ---------------------------------------------------------------- conclusie

def test_de_conclusie_meldt_distributieverlies(client):
    """Zes winkels naar twee is het soort verval dat in de omzet pas maanden
    later opvalt."""
    weken_vroeg = {f"2026{w:02d}": (30.0, 1) for w in range(20, 27)}
    weken_laat = {f"2026{w:02d}": (30.0, 1) for w in range(27, 35)}
    _laad(client, [_rij("120781690", 6000 + i, {**weken_vroeg, **weken_laat})
                   for i in range(2)]
                  + [_rij("120781690", 6000 + i, weken_vroeg) for i in range(2, 8)])
    koppen = [b["kop"] for b in client.get("/api/etos/conclusie").json()["bevindingen"]]
    assert any("verliezen winkels" in k for k in koppen)
    assert any(k.startswith("Distributieverlies:") for k in koppen)


def test_een_piepklein_artikel_haalt_de_conclusie_niet(client):
    """Van 2 naar 0 winkels is -100%, maar het is geen distributieverhaal."""
    weken_vroeg = {f"2026{w:02d}": (30.0, 1) for w in range(20, 27)}
    weken_laat = {f"2026{w:02d}": (30.0, 1) for w in range(27, 35)}
    _laad(client, [_rij("120781690", 6001, {**weken_vroeg, **weken_laat}),
                   _rij("120781690", 6002, weken_vroeg)])
    koppen = [b["kop"] for b in client.get("/api/etos/conclusie").json()["bevindingen"]]
    assert not any(k.startswith("Distributieverlies:") for k in koppen)
