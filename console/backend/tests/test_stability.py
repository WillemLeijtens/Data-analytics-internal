"""Stability guarantees: batch-imports, failed re-imports, path traversal,
malformed payloads, year boundaries and the rotation window."""

import datetime as dt
import importlib
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_parser_flow import (DG_HEADERS, dg_rows, douglas_definition,  # noqa: E402
                              make_xlsx, ship_profile, upload)
from engine.signals import periods_behind  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    # cleanup_demo hoort er ook bij: die module houdt een verwijzing naar
    # het db-module vast en zou anders naar de database van een vorige test
    # blijven wijzen.
    for name in ("db", "seed", "main", "cleanup_demo", "cleanup_duplicates"):
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def publish_douglas(client, break_period=False):
    f = make_xlsx(DG_HEADERS, dg_rows(2026, [32]))
    ship_profile("douglas", douglas_definition(break_period))
    return f


# ------------------------------------------------------- batch independence

def test_batch_keeps_good_files_when_one_crashes(client, monkeypatch):
    """A crash on file 2 must not roll back file 1 (each file = own txn)."""
    f = publish_douglas(client)
    upload(client, "Douglas_Abverkauf_KW32.xlsx", f)  # baseline loaded

    from engine import importer as imp
    real = imp.parser_mod.detect

    def exploding_detect(filename, content, profiles):
        if "KW31" in filename:
            raise RuntimeError("boem")
        return real(filename, content, profiles)

    monkeypatch.setattr(imp.parser_mod, "detect", exploding_detect)
    f30 = make_xlsx(DG_HEADERS, dg_rows(2026, [30]))
    f31 = make_xlsx(DG_HEADERS, dg_rows(2026, [31]))
    r = client.post("/api/import", files=[
        ("files", ("Douglas_Abverkauf_KW30.xlsx", f30)),
        ("files", ("Douglas_Abverkauf_KW31.xlsx", f31)),
    ]).json()["results"]
    assert [x["status"] for x in r] == ["ingelezen", "error"]

    # File 1's rows must actually BE there, crash on file 2 notwithstanding.
    # (JSON turns the year/period dict keys into strings.)
    dash = client.get("/api/douglas/dashboard").json()
    periodes = set(dash["trend"]["series"]["omzet"]["2026"].keys())
    assert {"30", "32"} <= periodes and "31" not in periodes


# ------------------------------------------------------- failed re-import

def test_failed_reimport_keeps_existing_facts(client):
    f = publish_douglas(client)
    assert upload(client, "Douglas_Abverkauf_KW32.xlsx", f)["status"] == "ingelezen"

    # A newer LIVE profile with a period column the file doesn't have:
    # re-uploading now fails to parse — the loaded facts must survive.
    publish_douglas(client, break_period=True)
    result = upload(client, "Douglas_Abverkauf_KW32.xlsx", f)
    assert result["status"] == "error"
    assert "blijft ongewijzigd" in result["detail"]

    imports = client.get("/api/imports").json()
    assert [i["status"] for i in imports] == ["ingelezen"]
    assert client.get("/api/douglas/dashboard").json()["available"]
    assert not client.get("/api/douglas/dashboard").json()["empty"]


def test_previously_loaded_file_survives_when_detection_turns_ambiguous(client):
    f = publish_douglas(client)
    assert upload(client, "Douglas_Abverkauf_KW32.xlsx", f)["status"] == "ingelezen"
    # A SECOND retailer ships a profile with the same glob and headers:
    # detection is now ambiguous -> the loaded import must stay untouched.
    ship_profile("etos", douglas_definition())
    result = upload(client, "Douglas_Abverkauf_KW32.xlsx", f)
    assert result["status"] == "ingelezen"
    assert "blijft staan" in result["detail"]
    assert [i["status"] for i in client.get("/api/imports").json()] == ["ingelezen"]


# ------------------------------------------------------- path traversal

@pytest.fixture()
def client_static(tmp_path, monkeypatch):
    static = BACKEND / "static"
    created = not static.exists()
    (static / "assets").mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<div id='root'>console</div>")
    (static / "assets" / "app.js").write_text("// js")
    try:
        monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
        monkeypatch.setenv("CONSOLE_AUTH", "gateway")
        monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
        for name in ("db", "seed", "main"):
            sys.modules.pop(name, None)
        main = importlib.import_module("main")
        yield TestClient(main.app)
    finally:
        if created:
            shutil.rmtree(static, ignore_errors=True)
        for name in ("db", "seed", "main"):
            sys.modules.pop(name, None)


def test_spa_serves_files_and_deep_links(client_static):
    assert "console" in client_static.get("/").text
    assert client_static.get("/assets/app.js").text == "// js"
    assert "console" in client_static.get("/kruidvat/dashboard").text


def test_spa_never_escapes_static_dir(client_static):
    r = client_static.get("/../main.py")
    assert "import" not in r.text or "console" in r.text
    r = client_static.get("/%2e%2e/%2e%2e/etc/passwd")
    assert "root:" not in r.text


# ------------------------------------------------------- malformed payloads

def test_malformed_settings_is_422_and_untouched(client):
    # Een verse installatie start met LEGE instellingen (geen verzonnen
    # winkelaantallen); vul er eerst iets echts in om te kunnen bewijzen dat
    # een foute payload dat niet aantast.
    client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
         "aantal_winkels": 900, "target_per_winkel": 45.0}]})
    before = client.get("/api/kruidvat/instellingen").json()["winkels_targets"]
    assert before
    r = client.put("/api/kruidvat/instellingen",
                   json={"winkels_targets": [{"land": "NL"}]})  # merk ontbreekt
    assert r.status_code == 422
    assert client.get("/api/kruidvat/instellingen").json()["winkels_targets"] == before


def test_malformed_promo_confirmation_is_422(client):
    r = client.put("/api/kruidvat/promoties", json={"bevestigd": [{"merk": "X"}]})
    assert r.status_code == 422


# ------------------------------------------------------- controleren op bestand

def test_test_endpoint_uses_shipped_profile(client):
    f = make_xlsx(DG_HEADERS, dg_rows(2026, [32]))
    # Zonder profiel: nette 404, geen crash.
    assert client.post("/api/parser/douglas/test",
                       files={"file": ("Douglas_Abverkauf_KW32.xlsx", f)}).status_code == 404
    ship_profile("douglas", douglas_definition())
    r = client.post("/api/parser/douglas/test",
                    files={"file": ("Douglas_Abverkauf_KW32.xlsx", f)}).json()
    assert r["ok"] and r["rijen"] == 2


# ------------------------------------------------------- year boundary

def test_periods_behind_january_week():
    # Early January: newest complete week is 2025-W52 -> feed is current.
    assert periods_behind("2025-W52", "week", dt.date(2026, 1, 2)) <= 1
    assert periods_behind("2025-W40", "week", dt.date(2026, 1, 2)) >= 5


def test_periods_behind_january_month():
    assert periods_behind("2025-12", "maand", dt.date(2026, 1, 15)) == 0
    assert periods_behind("2025-08", "maand", dt.date(2026, 1, 15)) == 4


# ------------------------------------------------------- rotation window

def test_rotation_uses_current_year_only(client):
    # Kruidvat is live in bootstrap (builtin DWH-parser); two years of data.
    import seed

    def one_item(year, weeks, vol):
        wkdata = {f"{year}{wk:02d}": (vol, vol * 13.0) for wk in weeks}
        return [{"sku": "31210001", "gtin": "4049469072773",
                 "desc": "Slant Tweezer", "brand": "TWEEZERMAN", "weeks": wkdata}]

    f_old = seed.make_dwh_xlsx(one_item(2025, range(1, 27), 10))
    # Vier weken: genoeg om voorbij de "te kort geleden geïntroduceerd"-drempel
    # te komen, zodat deze test over het JAARVENSTER blijft gaan.
    f_new = seed.make_dwh_xlsx(one_item(2026, [1, 2, 3, 4], 10))
    assert upload(client, "DWH__Sales_Tweezerman_KVNL_2025_demo.xlsx", f_old)["status"] == "ingelezen"
    assert upload(client, "DWH__Sales_Tweezerman_KVNL_02_demo.xlsx", f_new)["status"] == "ingelezen"

    client.put("/api/kruidvat/instellingen", json={
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": 1, "target_per_winkel": 45.0}],
        "rotatie_targets": [{"merk": "TWEEZERMAN", "stuks_per_winkel_per_week": 8.0}]})
    art = client.get("/api/kruidvat/assortiment").json()["artikelen"][0]
    # Current year: 40 stuks / 4 weken / 1 winkel = 10 — NOT diluted by 2025.
    assert art["rotatie"] == pytest.approx(10.0)
    assert art["score"] == 125


# ------------------------------------------------------- demo-opruiming

def test_cleanup_demo_keeps_real_imports_and_own_settings(client, tmp_path, monkeypatch):
    """cleanup_demo verwijdert alleen ongewijzigde demo-waarden: echte
    imports en zelf ingevulde instellingen blijven staan."""
    import seed as seed_mod
    import cleanup_demo

    seed_mod._load_demo_settings()                     # verzonnen instellingen
    upload(client, "DWH__Sales_Tweezerman_KVNL_demo.xlsx",
           seed_mod.make_dwh_xlsx(seed_mod._kv_demo_rows(["202601"])))   # demo-import
    echt = upload(client, "DWH__Sales_volume__sales_Tweezerman_KVNL_9999.xlsx",
                  seed_mod.make_dwh_xlsx(seed_mod._kv_demo_rows(["202602"])))
    assert echt["status"] == "ingelezen"
    # eigen instelling die NIET met de demo-waarde overeenkomt
    client.put("/api/kruidvat/instellingen", json={"rotatie_targets": [
        {"merk": "TWEEZERMAN", "stuks_per_winkel_per_week": 99.0}]})

    monkeypatch.setattr(sys, "argv", ["cleanup_demo.py", "--doen"])
    cleanup_demo.main()

    overgebleven = [i["filename"] for i in client.get("/api/imports").json()]
    assert overgebleven == ["DWH__Sales_volume__sales_Tweezerman_KVNL_9999.xlsx"]
    inst = client.get("/api/kruidvat/instellingen").json()
    assert [t["stuks_per_winkel_per_week"] for t in inst["rotatie_targets"]] == [99.0]
    assert inst["winkels_targets"] == []      # demo-winkelaantallen weg


# ------------------------------------------------------- audit-fixes

def test_profile_publishing_is_no_longer_exposed(client):
    """Zelf mappen is bewust uit de app: profielen komen uit het project.
    De oude endpoints horen weg te zijn, niet alleen verborgen in de UI."""
    r = client.post("/api/parser/douglas/profielen",
                    json={"definition": {"detection": {}}, "status": "live"})
    assert r.status_code in (404, 405)
    assert client.get("/api/parser/voorstel").status_code in (404, 405)


def test_gelijktijdige_upload_van_hetzelfde_nieuwe_bestand_dupliceert_niet(client):
    """REL-1: twee gelijktijdige uploads van hetzelfde, nog-nooit-geziene
    bestand zouden allebei de 'existing is None'-check kunnen passeren
    vóórdat een van beide commit. De UNIQUE-index op imports.file_hash
    (migrations/001_schema.sql) is de schema-level backstop daartegen: een
    tweede INSERT met dezelfde hash faalt hard i.p.v. stil te dupliceren.
    Dit simuleert de tweede, "verliezende" schrijver direct op de database."""
    import sqlite3

    import db as db_mod

    with db_mod.get_conn() as conn:
        conn.execute(
            "INSERT INTO imports (retailer_id, profile_id, filename, file_hash, status) "
            "VALUES (NULL, NULL, 'a.xlsx', 'zelfde-hash', 'profiel_nodig')")

    with db_mod.get_conn() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO imports (retailer_id, profile_id, filename, file_hash, status) "
                "VALUES (NULL, NULL, 'b.xlsx', 'zelfde-hash', 'profiel_nodig')")

    # De eerste rij staat nog gewoon: de mislukte tweede poging heeft niets
    # kapotgemaakt, alleen zichzelf niet toegevoegd.
    rows = client.get("/api/imports").json()
    assert sum(1 for r in rows if r["filename"] == "a.xlsx") == 1


def test_upload_limit_is_enforced_per_file(client, monkeypatch):
    main = sys.modules["main"]
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    monkeypatch.setattr(main, "MAX_UPLOAD_MB", 1)
    result = client.post("/api/import", files=[
        ("files", ("te-groot.csv", b"12345678901")),
    ]).json()["results"][0]
    assert result["status"] == "error" and "groter dan" in result["detail"]


def test_decompressiebom_wordt_geweigerd_voor_openpyxl_leest(client, monkeypatch):
    """Een klein, geldig .xlsx-bestand dat uitgepakt gigantisch wordt (een
    'zip bomb') mag nooit ongecontroleerd door openpyxl gedecomprimeerd
    worden — dat kan het geheugen van het proces opblazen."""
    import io
    import zipfile

    main = sys.modules["main"]
    monkeypatch.setattr(main, "MAX_UNCOMPRESSED_MB", 1)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 2 MB aan herhaalde tekst comprimeert tot een paar honderd bytes.
        zf.writestr("groot.xml", b"0" * (2 * 1024 * 1024))
    result = client.post("/api/import", files=[
        ("files", ("bom.xlsx", buf.getvalue())),
    ]).json()["results"][0]
    assert result["status"] == "error"
    assert "pakt uit tot meer dan" in result["detail"]


# ------------------------------------------------------- dubbele gegevens

def test_identical_file_twice_counts_once(client):
    """Het meest voorkomende dubbel-scenario: hetzelfde bestand nog een keer
    uploaden (per ongeluk, of onder een andere naam uit de mailbox). De hash
    op de inhoud vangt dat af: één importregel, één keer geteld."""
    import seed
    f = seed.make_dwh_xlsx([{"sku": "31210001", "gtin": "4049469072773",
                             "desc": "Slant", "brand": "TWEEZERMAN",
                             "weeks": {"202632": (10, 100.0)}}])
    assert upload(client, "DWH__Sales_Tweezerman_KVNL_wk32.xlsx", f)["status"] == "ingelezen"
    assert upload(client, "DWH__Sales_Tweezerman_KVNL_wk32.xlsx", f)["status"] == "ingelezen"
    # Zelfde inhoud, andere bestandsnaam — mailclients plakken er van alles voor.
    assert upload(client, "kopie van DWH__Sales_Tweezerman_KVNL_wk32 (1).xlsx",
                  f)["status"] == "ingelezen"

    assert len(client.get("/api/imports").json()) == 1
    assert client.get("/api/kruidvat/dashboard").json()["kpi"]["omzet"]["waarde"] == 100.0


def test_duplicate_keys_within_one_flat_file_sum(client):
    """Twee rijen met dezelfde sleutel BINNEN één plat bestand tellen op —
    exports splitsen een week soms over meerdere regels (bijv. promo en
    regulier). Dubbel tellen over bestanden heen kan niet: een herlevering
    vervangt eerst alle overlappende sleutels."""
    ship_profile("douglas", douglas_definition())
    rows = [["2026-W32", "DG-1", "TWEEZERMAN", 10, 100.0],
            ["2026-W32", "DG-1", "TWEEZERMAN", 5, 50.0]]
    f = make_xlsx(DG_HEADERS, rows)
    assert upload(client, "Douglas_Abverkauf_KW32.xlsx", f)["status"] == "ingelezen"
    assert client.get("/api/douglas/dashboard").json()["kpi"]["omzet"]["waarde"] == 150.0

    # Herlevering van dezelfde week in een ander bestand: vervangt, telt niet op.
    f2 = make_xlsx(DG_HEADERS, [["2026-W32", "DG-1", "TWEEZERMAN", 12, 120.0]])
    assert upload(client, "Douglas_Abverkauf_KW32_v2.xlsx", f2)["status"] == "ingelezen"
    assert client.get("/api/douglas/dashboard").json()["kpi"]["omzet"]["waarde"] == 120.0


def test_upload_path_in_filename_is_stripped(client):
    result = client.post("/api/import", files=[
        ("files", ("../../etc/passwd.xlsx", b"geen xlsx")),
    ]).json()["results"][0]
    assert result["filename"] == "passwd.xlsx"


def test_import_status_shows_latest_period_not_whole_history(client):
    import seed
    for wk in ("202631", "202632"):
        assert upload(client, f"DWH__Sales_volume_TWEEZERMAN_KVNL_wk{wk[-2:]}.xlsx",
                      seed.make_dwh_xlsx(seed._kv_demo_rows([wk])))["status"] == "ingelezen"
    retailer = client.get("/api/import-status?retailer_id=kruidvat").json()[0]
    feed = next(f for f in retailer["feeds"] if f["feed"] == "TWEEZERMAN")
    assert feed["periode"] == "2026-W32" and feed["rijen"] == 2


def test_cleanup_demo_also_removes_settings_from_older_versions(client, monkeypatch):
    """Gemeld vanaf de droplet: een console die door een oudere versie was
    aangemaakt hield Etos-demowaarden (530 winkels) over, omdat die retailer
    inmiddels uit DEMO_SETTINGS was gehaald en het opruimscript zijn zoeklijst
    daaruit afleidt."""
    import cleanup_demo
    import db as db_mod

    with db_mod.get_conn() as conn:
        conn.executemany(
            "INSERT INTO retailer_settings (retailer_id, merk, land, banner, "
            "aantal_winkels, target_per_winkel) VALUES ('etos',?,?,?,?,?)",
            [("TWEEZERMAN", "NL", None, 530, 35.0),
             ("ALESSANDRO", "NL", None, 530, 25.0)])
        conn.execute(
            "INSERT INTO mail_rules (retailer_id, naam, afzender, bijlage_glob) "
            "VALUES ('etos','Etos salesreport','data@etos.nl','etos_sales_wk*.csv')")
        # eigen waarde die MOET blijven staan
        conn.execute(
            "INSERT INTO retailer_settings (retailer_id, merk, land, banner, "
            "aantal_winkels) VALUES ('etos','OLIVIA GARDEN','NL',NULL,777)")

    monkeypatch.setattr(sys, "argv", ["cleanup_demo.py", "--doen"])
    cleanup_demo.main()

    with db_mod.get_conn() as conn:
        rest = conn.execute(
            "SELECT merk, aantal_winkels FROM retailer_settings").fetchall()
        assert [tuple(r) for r in rest] == [("OLIVIA GARDEN", 777)]
        assert conn.execute("SELECT COUNT(*) c FROM mail_rules").fetchone()["c"] == 0


def test_cleanup_duplicates_keeps_the_latest_correction(client, monkeypatch):
    """Databases van vóór de correctie-fix bevatten dubbele feitregels: een
    herlevering kwam ernaast te staan en werd opgeteld. Het opruimscript
    houdt per combinatie de regel uit de nieuwste import over."""
    import cleanup_duplicates
    import seed
    from engine import importer as imp

    def kv(omzet):
        return seed.make_dwh_xlsx([{"sku": "31210001", "gtin": "4049469072773",
                                    "desc": "Slant", "brand": "TWEEZERMAN",
                                    "weeks": {"202631": (12, omzet)}}])

    # Bootst de oude situatie na door de vervanging uit te schakelen.
    monkeypatch.setattr(imp, "_replace_redelivered_facts", lambda *a, **k: None)
    for omzet in (156.0, 999.0):
        upload(client, f"DWH__Sales_Tweezerman_KVNL_{omzet}.xlsx", kv(omzet))
    monkeypatch.undo()
    assert client.get("/api/kruidvat/dashboard").json()["kpi"]["omzet"]["waarde"] == 1155.0

    monkeypatch.setattr(sys, "argv", ["cleanup_duplicates.py", "--doen"])
    cleanup_duplicates.main()
    assert client.get("/api/kruidvat/dashboard").json()["kpi"]["omzet"]["waarde"] == 999.0

    # Idempotent: nog een keer draaien verandert niets meer.
    cleanup_duplicates.main()
    assert client.get("/api/kruidvat/dashboard").json()["kpi"]["omzet"]["waarde"] == 999.0
