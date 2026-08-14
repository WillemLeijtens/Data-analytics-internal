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

from test_parser_flow import DG_HEADERS, dg_rows, make_xlsx, upload  # noqa: E402
from engine.signals import periods_behind  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for name in ("db", "seed", "main"):
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def douglas_definition(break_period=False) -> dict:
    return {
        "detection": {"filename_glob": "Douglas_Abverkauf_KW*.xlsx", "sheet": "Sheet1",
                      "header_row": 1, "required_headers": DG_HEADERS[:3],
                      "filetype": "xlsx", "csv_delimiter": None, "decimal": ","},
        "period": {"type": "week",
                   "source_column": "BestaatNiet" if break_period else "Kalenderwoche",
                   "format": "yyyy-Www"},
        "mapping": [{"source": "Marke", "target": "merk"},
                    {"source": "Absatz", "target": "volume"},
                    {"source": "Umsatz", "target": "omzet"}],
        "constants": {"land": "DE"},
        "thresholds": {"promo_price_drop": 0.05},
    }


def publish_douglas(client, break_period=False):
    f = make_xlsx(DG_HEADERS, dg_rows(2026, [32]))
    r = client.post("/api/parser/douglas/profielen",
                    json={"definition": douglas_definition(break_period), "status": "live"})
    assert r.status_code == 200
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
    # A SECOND retailer publishes a profile with the same glob and headers:
    # detection is now ambiguous -> the loaded import must stay untouched.
    r = client.post("/api/parser/etos/profielen",
                    json={"definition": douglas_definition(), "status": "live"})
    assert r.status_code == 200
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
    before = client.get("/api/kruidvat/instellingen").json()["winkels_targets"]
    assert before  # bootstrap defaults present
    r = client.put("/api/kruidvat/instellingen",
                   json={"winkels_targets": [{"land": "NL"}]})  # merk ontbreekt
    assert r.status_code == 422
    assert client.get("/api/kruidvat/instellingen").json()["winkels_targets"] == before


def test_malformed_promo_confirmation_is_422(client):
    r = client.put("/api/kruidvat/promoties", json={"bevestigd": [{"merk": "X"}]})
    assert r.status_code == 422


# ------------------------------------------------------- test-on-file draft

def test_test_endpoint_uses_supplied_draft(client):
    f = make_xlsx(DG_HEADERS, dg_rows(2026, [32]))
    upload(client, "Douglas_Abverkauf_KW32.xlsx", f)
    d = client.get("/api/parser/voorstel").json()["definition"]
    d["period"] = {"type": "week", "source_column": "Kalenderwoche", "format": "yyyy-Www"}
    for m in d["mapping"]:
        m["target"] = {"Marke": "merk", "Absatz": "volume", "Umsatz": "omzet"}.get(m["source"])
    import json as _json
    r = client.post("/api/parser/douglas/test",
                    files={"file": ("Douglas_Abverkauf_KW32.xlsx", f)},
                    data={"definition": _json.dumps(d)}).json()
    assert r["ok"] and r["rijen"] == 2
    # Without the draft: the saved profile is the handoff CONCEPT (unmapped)
    r = client.post("/api/parser/douglas/test",
                    files={"file": ("Douglas_Abverkauf_KW32.xlsx", f)}).json()
    assert not r["ok"]


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
    f_new = seed.make_dwh_xlsx(one_item(2026, [1, 2], 10))
    assert upload(client, "DWH__Sales_Tweezerman_KVNL_2025_demo.xlsx", f_old)["status"] == "ingelezen"
    assert upload(client, "DWH__Sales_Tweezerman_KVNL_02_demo.xlsx", f_new)["status"] == "ingelezen"

    client.put("/api/kruidvat/instellingen", json={
        "winkels_targets": [{"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
                             "aantal_winkels": 1, "target_per_winkel": 45.0}],
        "rotatie_targets": [{"merk": "TWEEZERMAN", "stuks_per_winkel_per_week": 8.0}]})
    art = client.get("/api/kruidvat/assortiment").json()["artikelen"][0]
    # Current year: 20 stuks / 2 weken / 1 winkel = 10 — NOT diluted by 2025.
    assert art["rotatie"] == pytest.approx(10.0)
    assert art["score"] == 125
