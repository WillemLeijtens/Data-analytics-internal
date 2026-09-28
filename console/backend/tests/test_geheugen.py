"""De analysecache (engine/geheugen.py): gedeeld, single-flight, LRU, en een
opwarmer.

Waarom dit bestaat: op Etos-schaal (90k feitregels) kostte een koud
dashboard 2 s en een koude conclusie 5,5 s, waarvan de helft dubbel werk —
de conclusie rekende dashboard, artikelen, assortiment en promoties
opnieuw uit, ook als die al gecachet waren. Gelijktijdige koude verzoeken
rekenden elk alles zelf uit. Wat hier vastligt, is dat dat niet meer kan.
"""

import importlib
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import geheugen  # noqa: E402
from test_parser_flow import upload  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for naam in ("db", "seed", "main"):
        sys.modules.pop(naam, None)
    geheugen.leeg()
    main = importlib.import_module("main")
    return TestClient(main.app)


def _etos(client):
    import seed
    upload(client, "Data_Grid_57018_widget.xlsx", seed.make_etos_xlsx([
        {"upc": "120781690", "naam": "SLANT", "merk": "TWEEZERMAN", "merk_nr": 2278,
         "weeks": {f"2026{w:02d}": (30.0, 1) for w in range(1, 9)},
         "winkel": "ETOS SNEEK - 6263", "stad": "Sneek"}], winkels=True))


# ------------------------------------------------------------ de cache zelf

def test_single_flight_rekent_een_keer(client):
    """Twee threads vragen tegelijk dezelfde koude sleutel: één berekent,
    de ander wacht op die uitkomst."""
    import db
    telling = []
    gestart = threading.Event()

    def traag():
        telling.append(1)
        gestart.set()
        time.sleep(0.2)
        return {"x": 1}

    uit = []

    def vraag():
        with db.get_conn() as conn:
            uit.append(geheugen.gecachet(("proef",), traag, conn))

    a = threading.Thread(target=vraag)
    a.start()
    gestart.wait(2)
    b = threading.Thread(target=vraag)
    b.start()
    a.join(); b.join()
    assert len(telling) == 1
    assert uit == [{"x": 1}, {"x": 1}]


def test_een_fout_laat_geen_hangende_vlucht_achter(client):
    import db
    with db.get_conn() as conn:
        with pytest.raises(RuntimeError):
            geheugen.gecachet(("stuk",), lambda: (_ for _ in ()).throw(RuntimeError("x")), conn)
        # Daarna gewoon opnieuw te berekenen, niet vast op de mislukte vlucht.
        assert geheugen.gecachet(("stuk",), lambda: 42, conn) == 42


def test_lru_gooit_de_oudste_weg_niet_alles(client, monkeypatch):
    """De oude cache wiste álles zodra er 64 sleutels waren; elke
    filtercombinatie is een sleutel, dus dat gooide ook de warme
    ongefilterde dashboards weg."""
    import db
    monkeypatch.setattr(geheugen, "MAX_SLEUTELS", 3)
    with db.get_conn() as conn:
        for i in range(3):
            geheugen.gecachet(("s", i), lambda i=i: i, conn)
        geheugen.gecachet(("s", 0), lambda: "opnieuw", conn)     # 0 is nu recent
        geheugen.gecachet(("s", 3), lambda: 3, conn)             # gooit 1 weg
        assert geheugen.aantal() == 3
        assert geheugen.gecachet(("s", 0), lambda: "opnieuw", conn) == 0
        assert geheugen.gecachet(("s", 1), lambda: "vers", conn) == "vers"


def test_twee_databases_delen_nooit_een_uitkomst(tmp_path):
    """De cache leeft langer dan één database. Twee lege databases hebben
    dezelfde tellingen; zonder het pad in de versie zouden ze elkaars
    uitkomst krijgen."""
    import sqlite3
    a, b = sqlite3.connect(tmp_path / "a.db"), sqlite3.connect(tmp_path / "b.db")
    for c in (a, b):
        c.execute("CREATE TABLE t (x)")
    assert geheugen.data_versie(a) != geheugen.data_versie(b)


# ---------------------------------------------------- hergebruik, geen dubbel werk

def test_conclusie_hergebruikt_het_gecachete_dashboard(client, monkeypatch):
    from engine import analytics
    _etos(client)
    client.get("/api/etos/dashboard")
    client.get("/api/etos/artikelen")
    client.get("/api/etos/promoties")
    client.get("/api/etos/assortiment")
    aanroepen = []
    for naam in ("dashboard", "articles", "promotions", "assortment"):
        echt = getattr(analytics, naam)
        monkeypatch.setattr(analytics, naam,
                            lambda *a, _e=echt, _n=naam, **k: (aanroepen.append(_n), _e(*a, **k))[1])
    assert client.get("/api/etos/conclusie").status_code == 200
    assert aanroepen == []


def test_dashboard_rekent_promoties_niet_opnieuw_uit(client, monkeypatch):
    """promo_markers vroeg promotions() rechtstreeks op; nu via de cache,
    dus na het promotiescherm kost een koud dashboard geen prijsindex meer."""
    from engine import analytics
    _etos(client)
    client.put("/api/etos/promoties", json={"wijzigingen": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": None, "periode": "2026-W03",
         "bevestigd": True}]})
    client.get("/api/etos/promoties")
    aanroepen = []
    echt = analytics.promotions
    monkeypatch.setattr(analytics, "promotions",
                        lambda *a, **k: (aanroepen.append(1), echt(*a, **k))[1])
    client.get("/api/etos/dashboard")
    assert aanroepen == []


def test_een_wijziging_maakt_de_cache_meteen_vers(client):
    """Invalidatie blijft op de data gebaseerd: een instelling opslaan
    verandert de versie, en het volgende verzoek rekent opnieuw."""
    _etos(client)
    voor = client.get("/api/etos/instellingen").json()["winkelsignaal"]
    client.put("/api/etos/instellingen", json={"winkelsignaal": {"letop_vanaf": 3,
                                                                 "gestopt_vanaf": 6}})
    na = client.get("/api/etos/instellingen").json()["winkelsignaal"]
    assert voor != na == {"letop_vanaf": 3, "gestopt_vanaf": 6}


def test_distributiesignaal_gebruikt_de_ingestelde_drempels(client):
    """Het Overzicht rekende met de standaarddrempels, het dashboard met die
    uit Instellingen — ze konden elkaar tegenspreken."""
    import seed
    upload(client, "Data_Grid_57018_widget.xlsx", seed.make_etos_xlsx([
        {"upc": "120781690", "naam": "SLANT", "merk": "TWEEZERMAN", "merk_nr": 2278,
         "weeks": {f"2026{w:02d}": (30.0, 1) for w in range(1, 11)},
         "winkel": "ETOS SNEEK - 6263", "stad": "Sneek"},
        # Winkel 6264 stopt na week 6: vier lege weken.
        {"upc": "120781690", "naam": "SLANT", "merk": "TWEEZERMAN", "merk_nr": 2278,
         "weeks": {f"2026{w:02d}": (30.0, 1) for w in range(1, 7)},
         "winkel": "ETOS LEEK - 6264", "stad": "Leek"}], winkels=True))

    def signaal():
        kaart = next(c for c in client.get("/api/overview").json()["retailers"]
                     if c["id"] == "etos")
        return kaart["signalen"]["distributie"]["signaal"]

    client.put("/api/etos/instellingen", json={"winkelsignaal": {"letop_vanaf": 2,
                                                                 "gestopt_vanaf": 3}})
    assert signaal() == "orange"                     # gestopt na 4 lege weken
    client.put("/api/etos/instellingen", json={"winkelsignaal": {"letop_vanaf": 5,
                                                                 "gestopt_vanaf": 8}})
    assert signaal() == "green"                      # 4 lege weken is nu nog niets


# ------------------------------------------------------------------ opwarmen

def test_opwarmen_vult_de_schermen(client):
    import db
    _etos(client)
    geheugen.leeg()
    with db.get_conn() as conn:
        geheugen.opwarmen(conn)
        versie = geheugen.data_versie(conn)
    for sleutel in (("overview",), ("dashboard", "etos", None, None, None, None),
                    ("artikelen", "etos", None), ("promoties", "etos"),
                    ("assortiment", "etos"), ("datagaten", "etos"),
                    ("conclusie-bevindingen", "etos")):
        assert geheugen._CACHE[sleutel][0] == versie, sleutel


def test_een_schrijfactie_port_de_opwarmer(client, monkeypatch):
    geporred = []
    monkeypatch.setattr(geheugen, "por", lambda: geporred.append(1))
    _etos(client)                                         # POST /api/import
    assert geporred
    geporred.clear()
    client.get("/api/etos/dashboard")                     # lezen port niet
    client.put("/api/etos/instellingen", json={"bestaat_niet": 1})
    assert geporred == [1]


def test_opwarmer_is_uit_te_zetten(monkeypatch):
    monkeypatch.setenv("CONSOLE_OPWARMEN", "0")
    monkeypatch.setattr(geheugen, "_OPWARMER", None)
    geheugen.start_opwarmer(lambda: None)
    assert geheugen._OPWARMER is None


# ------------------------------------------------------------- import-status

def test_import_status_telt_alleen_de_laatste_periode(client):
    """Nu in SQL gegroepeerd in plaats van alle regels naar Python; de
    uitkomst moet gelijk blijven: per feed de laatste periode, en het aantal
    regels van dié periode — niet van de hele historie."""
    _etos(client)
    feed = client.get("/api/import-status?retailer_id=etos").json()[0]["feeds"][0]
    assert feed["periode"] == "2026-W08"
    assert feed["rijen"] == 1
    assert feed["ts"]


# ------------------------------------------------------------ filterchips

def _twee_merken(client):
    import seed
    upload(client, "Data_Grid_57018_widget.xlsx", seed.make_etos_xlsx([
        {"upc": "120781690", "naam": "SLANT", "merk": "TWEEZERMAN", "merk_nr": 2278,
         "weeks": {f"2026{w:02d}": (30.0, 1) for w in range(1, 9)},
         "winkel": "ETOS SNEEK - 6263", "stad": "Sneek"},
        {"upc": "120781691", "naam": "SCHAAR", "merk": "ZWILLING", "merk_nr": 2279,
         "weeks": {f"2026{w:02d}": (12.0, 1) for w in range(1, 9)},
         "winkel": "ETOS LEEK - 6264", "stad": "Leek"}], winkels=True))


def test_filter_dat_alles_kiest_hergebruikt_het_ongefilterde_dashboard(client, monkeypatch):
    """land=NL bij een retailer die alleen NL heeft, en beide merken in
    willekeurige volgorde, zijn geen nieuwe berekening."""
    from engine import analytics
    _twee_merken(client)
    heel = client.get("/api/etos/dashboard").json()
    aanroepen = []
    echt = analytics.dashboard
    monkeypatch.setattr(analytics, "dashboard",
                        lambda *a, **k: (aanroepen.append(a), echt(*a, **k))[1])
    assert client.get("/api/etos/dashboard?land=NL").json() == heel
    assert client.get("/api/etos/dashboard?merk=ZWILLING,TWEEZERMAN").json() == heel
    assert aanroepen == []
    # Volgorde van de chips maakt geen tweede sleutel.
    client.get("/api/etos/dashboard?merk=ZWILLING,TWEEZERMAN&land=XX")
    client.get("/api/etos/dashboard?land=XX&merk=TWEEZERMAN,ZWILLING")
    assert len(aanroepen) == 1


def test_gefilterd_laden_in_sql_geeft_dezelfde_cijfers(client):
    """Het gefilterde dashboard laadt nu alleen de gefilterde rijen; de
    filterlijsten moeten desondanks alle waarden blijven tonen, en de
    cijfers gelijk zijn aan een filter in Python over alle rijen."""
    import db
    from engine import analytics
    _twee_merken(client)
    with db.get_conn() as conn:
        gefilterd = analytics.dashboard(conn, "etos", merk=["ZWILLING"])
        echt = analytics.load_facts
        try:
            analytics.load_facts = lambda c, rid, *a, niveau="artikel", **k: [
                r for r in echt(c, rid, niveau=niveau)
                if not a or not a[0] or r["merk"] in a[0]]
            python = analytics.dashboard(conn, "etos", merk=["ZWILLING"])
        finally:
            analytics.load_facts = echt
        leeg = analytics.dashboard(conn, "etos", merk=["BESTAAT_NIET"])
    assert gefilterd == python
    assert gefilterd["filters"]["merk"] == ["TWEEZERMAN", "ZWILLING"]
    assert leeg["empty"] and leeg["gefilterd"]
    assert leeg["filters"]["merk"] == ["TWEEZERMAN", "ZWILLING"]


def test_opwarmen_warmt_ook_de_losse_merkchips(client):
    import db
    _twee_merken(client)
    geheugen.leeg()
    with db.get_conn() as conn:
        assert geheugen.chips(conn, "etos") == [("merk", "TWEEZERMAN"), ("merk", "ZWILLING")]
        geheugen.opwarmen(conn)
        versie = geheugen.data_versie(conn)
    for merk in ("TWEEZERMAN", "ZWILLING"):
        assert geheugen._CACHE[("dashboard", "etos", merk, None, None, None)][0] == versie
