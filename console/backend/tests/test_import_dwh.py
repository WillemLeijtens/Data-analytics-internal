"""The import path that actually matters in production: real Kruidvat
DWH-export files through the builtin parser."""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_parser_flow import upload  # noqa: E402

REAL_SAMPLE = Path(
    "/root/.claude/uploads/54377bab-ac94-5cbf-8750-c3a4d90899e0/"
    "aa516215-DWH__Sales_volume__sales_value_per_week_per_article_"
    "Alessendro_Depend_KVNL_5696_1175350483788269736.xlsx")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for name in ("db", "seed", "main"):
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def test_generated_dwh_file_imports(client):
    import seed
    content = seed.make_dwh_xlsx(seed._kv_demo_rows(["202631", "202632"]))
    r = upload(client, "DWH__Sales_volume__sales_Tweezerman_KVNL_32_demo.xlsx", content)
    assert r["status"] == "ingelezen"
    assert r["rows"] == 6           # 3 artikelen x 2 weken
    assert r["retailer_id"] == "kruidvat"

    dash = client.get("/api/kruidvat/dashboard").json()
    assert dash["laatste_periode"] == "2026-W32"
    merken = {b["merk"] for b in dash["kpi"]["omzet"]["breakdown"]}
    assert merken == {"TWEEZERMAN", "ALESSANDRO"}

    art = client.get("/api/kruidvat/artikelen").json()
    assert art["available"] and len(art["artikelen"]) == 3
    eans = {a["ean"] for a in art["artikelen"]}
    assert "4049469072773" in eans  # GTIN uit het bestand, niet het SKU-nummer

    status = client.get("/api/import-status?retailer_id=kruidvat").json()[0]
    assert status["feeds"], "import status moet de feed tonen"


def test_old_flat_handoff_format_is_no_longer_recognised(client):
    """Het fictieve platte formaat uit het ontwerppakket hoort nu op
    PROFIEL NODIG te stranden: het actieve kruidvat-profiel is de echte
    DWH-parser."""
    from test_parser_flow import make_xlsx
    flat = make_xlsx(["Weeknummer", "EAN", "Merk", "Aantal", "Omzet excl BTW"],
                     [["202632", "4049469072773", "TWEEZERMAN", 10, 130.0]],
                     sheet="Sellout", meta_rows=8)
    r = upload(client, "DWH_sellout_TWEEZERMAN_NL_wk32.xlsx", flat)
    assert r["status"] in ("profiel_nodig", "error")


def test_unknown_upload_stays_visible_on_retailer_tab(client):
    r = upload(client, "onbekend_rapport_zonder_match.xlsx", b"geen xlsx")
    assert r["status"] == "profiel_nodig"
    rows = client.get("/api/imports?retailer_id=kruidvat").json()
    assert any(x["status"] == "profiel_nodig" for x in rows), \
        "PROFIEL NODIG moet op de retailer-tab zichtbaar zijn"


@pytest.mark.skipif(not REAL_SAMPLE.exists(), reason="echt sample-bestand niet aanwezig")
def test_real_dwh_sample_full_counts(client):
    r = upload(client, REAL_SAMPLE.name[9:], REAL_SAMPLE.read_bytes())
    assert r["status"] == "ingelezen"
    assert r["rows"] == 4566
    dash = client.get("/api/kruidvat/dashboard").json()
    per_brand = {b["merk"]: b["waarde"] for b in dash["kpi"]["omzet"]["breakdown"]}
    assert set(per_brand) == {"ALESSANDRO", "DEPEND GEL IQ"}
    art = client.get("/api/kruidvat/artikelen").json()
    assert len(art["artikelen"]) == 156


@pytest.mark.skipif(not REAL_SAMPLE.exists(), reason="echt sample-bestand niet aanwezig")
def test_real_file_with_mangled_name_still_recognised(client):
    """Mailclients en downloads plakken voorvoegsels aan bestandsnamen; de
    inhoudsherkenning moet het bestand dan alsnog bij kruidvat brengen."""
    r = upload(client, "aa516215-hernoemd en (1) gek gemaakt.xlsx", REAL_SAMPLE.read_bytes())
    assert r["status"] == "ingelezen" and r["retailer_id"] == "kruidvat"


def test_dwh_total_mismatch_fails_closed(client):
    """Een niet-kloppend Total-getal mag niet stil worden ingelezen."""
    import io
    import seed
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(seed.make_dwh_xlsx(seed._kv_demo_rows(["202632"]))))
    ws = wb.active
    ws.cell(row=ws.max_row, column=5, value=999999)     # Total-rij verminken
    out = io.BytesIO()
    wb.save(out)

    r = upload(client, "DWH__Sales_volume_TWEEZERMAN_KVNL_kapot-totaal.xlsx", out.getvalue())
    assert r["status"] == "error" and "Total-rij" in r["detail"]
    assert client.get("/api/kruidvat/dashboard").json()["empty"] is True
