"""Etos levert dezelfde Data Grid-widget met én zonder winkelkolommen.

De export "Omzet/volume per week per item per winkel" heeft twee kolommen
extra — Store en City — en dan is elke rij een artikel×winkel in plaats van
een artikel. Dat opent dezelfde winkelanalyse als bij ICI Paris XL.

De bestaande analyses draaien nog op de oude export, dus die moet
onveranderd blijven werken: deze tests pinnen beide vormen vast.
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


def art(upc, merk, weeks, winkel=None, stad=None):
    rij = {"upc": upc, "naam": f"ARTIKEL {upc}", "merk": merk,
           "merk_nr": 2278 if merk == "TWEEZERMAN" else 2912, "weeks": weeks}
    if winkel:
        rij["winkel"], rij["stad"] = winkel, stad or "Sneek"
    return rij


def met_winkels(client, artikelen, naam="Data_Grid_57018_winkels.xlsx"):
    import seed
    upload(client, naam, seed.make_etos_xlsx(artikelen, winkels=True))


# ------------------------------------------------------------------- parser

def test_winkelkolommen_worden_gelezen(client):
    met_winkels(client, [
        art("120781690", "TWEEZERMAN", {"202601": (29.99, 1)},
            "ETOS BEVERWIJK - 6311", "Beverwijk"),
        art("120781690", "TWEEZERMAN", {"202601": (59.98, 2)},
            "ETOS SNEEK - 6263", "Sneek")])
    import db
    with db.get_conn() as conn:
        rijen = [dict(r) for r in conn.execute(
            "SELECT winkel_id, winkel_naam, omzet FROM sellout_facts "
            "WHERE retailer_id='etos' ORDER BY winkel_id")]
    assert [r["winkel_id"] for r in rijen] == ["6263", "6311"]
    # De stad hoort bij de naam: twee filialen in dezelfde plaats zijn anders
    # niet uit elkaar te houden op het scherm.
    assert rijen[0]["winkel_naam"] == "ETOS SNEEK (Sneek)"


def test_zelfde_artikel_in_twee_winkels_is_geen_dubbeling(client):
    """De sleutel is artikel x winkel x week. Zonder de winkel erin zou elke
    tweede winkel als dubbeling gelden en de import afbreken."""
    met_winkels(client, [
        art("120781690", "TWEEZERMAN", {"202601": (10.0, 1)}, "ETOS A - 6001"),
        art("120781690", "TWEEZERMAN", {"202601": (20.0, 2)}, "ETOS B - 6002")])
    d = client.get("/api/etos/dashboard").json()
    assert d["kpi"]["omzet"]["waarde"] == pytest.approx(30.0)


def test_winkel_zonder_nummer_breekt_de_import_af(client):
    """Zonder nummer is een winkel niet te volgen over exports heen; stil
    doorgaan zou de winkeltelling laten zakken zonder dat iemand het merkt."""
    import seed
    from engine import etos_datagrid, parser
    inhoud = seed.make_etos_xlsx(
        [art("120781690", "TWEEZERMAN", {"202601": (10.0, 1)}, "ETOS ZONDER NUMMER")],
        winkels=True)
    with pytest.raises((ValueError, parser.ParseError), match="NAAM - nummer"):
        etos_datagrid.parse_workbook(inhoud)


def test_oude_export_zonder_winkelkolommen_blijft_werken(client):
    """De bestaande analyses draaien hierop; dat mag niet veranderen."""
    import seed
    upload(client, "Data_Grid_57018_widget.xlsx", seed.make_etos_xlsx(
        [art("120781690", "TWEEZERMAN", {"202601": (29.99, 1)})]))
    d = client.get("/api/etos/dashboard").json()
    assert d["kpi"]["omzet"]["waarde"] == pytest.approx(29.99)
    # Geen winkelniveau in de data: de app claimt het ook niet.
    assert d["capabilities"]["winkel"] is False


# ------------------------------------------------------------ winkelanalyse

def test_winkelniveau_opent_dezelfde_analyse_als_bij_ici(client):
    met_winkels(client, [
        art(f"12078000{i}", "TWEEZERMAN",
            {f"2026{w:02d}": (10.0, 1) for w in range(1, 13)},
            f"ETOS FILIAAL {i} - 60{i:02d}")
        for i in range(1, 6)])
    d = client.get("/api/etos/dashboard").json()
    assert d["capabilities"]["winkel"] is True
    # Winkelaantal uit de feiten, niet uit een handmatige schatting.
    assert d["kpi"]["omzet_per_winkel"]["winkels"] == 5
    assert d["kpi"]["omzet_per_winkel"]["schatting"] is False
    assert "SCHATTING" not in d["labels"]
    assert d["winkelanalyse"]["beschikbaar"] is True


# ------------------------------------------- automatisch ingevulde winkels

def test_winkelaantallen_komen_geteld_uit_de_import(client):
    """Levert de feed winkels, dan hoeft niemand ze in te vullen — en een
    afwijkend handmatig getal zou stilletjes winnen in de schermen die het
    gebruiken."""
    met_winkels(client, [
        art("120781690", "TWEEZERMAN", {"202601": (10.0, 1)}, "ETOS A - 6001"),
        art("120781691", "TWEEZERMAN", {"202601": (10.0, 1)}, "ETOS B - 6002"),
        art("120789245", "BJÖRN AXÉN", {"202601": (10.0, 1)}, "ETOS A - 6001")])
    g = {x["merk"]: x for x in client.get("/api/etos/instellingen").json()["feed_winkels"]}
    assert g["TWEEZERMAN"]["aantal_winkels"] == 2
    assert g["BJÖRN AXÉN"]["aantal_winkels"] == 1
    assert g["TWEEZERMAN"]["jaar"] == 2026


def test_winkel_zonder_omzet_telt_niet_mee(client):
    """Zelfde regel als in de analyses: een winkel die dat jaar niets
    verkocht drukt het gemiddelde omlaag zonder dat er iets veranderd is."""
    met_winkels(client, [
        art("120781690", "TWEEZERMAN", {"202601": (10.0, 1)}, "ETOS A - 6001"),
        art("120781691", "TWEEZERMAN", {"202601": (0.0, 0)}, "ETOS LEEG - 6099")])
    g = client.get("/api/etos/instellingen").json()["feed_winkels"]
    assert [x["aantal_winkels"] for x in g] == [1]


def test_zonder_winkelniveau_valt_er_niets_te_tellen(client):
    import seed
    upload(client, "Data_Grid_57018_widget.xlsx", seed.make_etos_xlsx(
        [art("120781690", "TWEEZERMAN", {"202601": (29.99, 1)})]))
    assert client.get("/api/etos/instellingen").json()["feed_winkels"] == []
