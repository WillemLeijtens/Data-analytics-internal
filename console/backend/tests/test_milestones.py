"""Mijlpalen op de trendgrafiek.

De x-as is het periodenummer met de jaren als losse lijnen. Een mijlpaal
hoort dus bij een jaar én een periodenummer — week 12 van 2025 ligt op
dezelfde x als week 12 van 2026, maar op een andere lijn.
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


def laad(client):
    """Een mijlpaal hoort bij een merk waar data van is, dus die moet er eerst
    zijn."""
    import seed

    for merk, sku, gtin in (("TWEEZERMAN", "31210001", "4049469072773"),
                            ("ALESSANDRO", "31210002", "4049469072774")):
        upload(client, f"DWH__Sales_{merk}_KVNL.xlsx", seed.make_dwh_xlsx([{
            "sku": sku, "gtin": gtin, "desc": merk, "brand": merk,
            "weeks": {"202510": (10, 100.0)}}]))


def zet(client, jaar=2025, periode=12, tekst="introductie nieuw item",
        merk="TWEEZERMAN", **extra):
    return client.post("/api/kruidvat/milestones", json={
        "jaar": jaar, "periode_nummer": periode, "tekst": tekst,
        "merk": merk, **extra})


def test_mijlpaal_zetten_en_teruglezen(client):
    laad(client)
    r = zet(client, door="Willem")
    assert r.status_code == 200
    gemaakt = r.json()
    assert (gemaakt["jaar"], gemaakt["periode_nummer"]) == (2025, 12)
    assert gemaakt["aangemaakt_door"] == "Willem"
    assert gemaakt["merk"] == "TWEEZERMAN"

    lijst = client.get("/api/kruidvat/milestones").json()
    assert [m["id"] for m in lijst] == [gemaakt["id"]]
    assert lijst[0]["tekst"] == "introductie nieuw item"


def test_lijst_staat_op_volgorde_van_de_x_as(client):
    laad(client)
    for jaar, periode in ((2026, 3), (2025, 40), (2025, 2)):
        zet(client, jaar=jaar, periode=periode, tekst=f"{jaar}-{periode}")
    lijst = client.get("/api/kruidvat/milestones").json()
    assert [(m["jaar"], m["periode_nummer"]) for m in lijst] == [
        (2025, 2), (2025, 40), (2026, 3)]


def test_meerdere_mijlpalen_in_dezelfde_week_mogen(client):
    """Twee dingen in één week is geen fout: allebei tonen, niet overschrijven."""
    laad(client)
    zet(client, tekst="nieuw item")
    zet(client, tekst="folderactie")
    lijst = client.get("/api/kruidvat/milestones").json()
    assert sorted(m["tekst"] for m in lijst) == ["folderactie", "nieuw item"]


def test_lege_tekst_wordt_geweigerd(client):
    """Een naamloze marker op de grafiek verklaart niets."""
    laad(client)
    assert zet(client, tekst="   ").status_code == 422
    assert client.get("/api/kruidvat/milestones").json() == []


@pytest.mark.parametrize("periode", [0, 54, -1])
def test_periodenummer_buiten_de_as_wordt_geweigerd(client, periode):
    laad(client)
    assert zet(client, periode=periode).status_code == 422


def test_lange_tekst_wordt_afgekapt(client):
    """Een label op een grafiek is kort; de rest zou de lijn onleesbaar maken."""
    laad(client)
    m = zet(client, tekst="x" * 500).json()
    assert len(m["tekst"]) == 200


def test_verwijderen(client):
    laad(client)
    m = zet(client).json()
    assert client.delete(f"/api/kruidvat/milestones/{m['id']}").status_code == 200
    assert client.get("/api/kruidvat/milestones").json() == []
    assert client.delete(f"/api/kruidvat/milestones/{m['id']}").status_code == 404


def test_mijlpaal_van_andere_retailer_is_niet_te_verwijderen(client):
    laad(client)
    m = zet(client).json()
    assert client.delete(f"/api/etos/milestones/{m['id']}").status_code == 404
    assert len(client.get("/api/kruidvat/milestones").json()) == 1


def test_onbekende_retailer_geeft_404(client):
    assert client.get("/api/bestaatniet/milestones").status_code == 404
    assert client.post("/api/bestaatniet/milestones", json={
        "jaar": 2025, "periode_nummer": 12, "tekst": "x",
        "merk": "TWEEZERMAN"}).status_code == 404


# ------------------------------------------------------------ merk

def test_merk_moet_data_hebben(client):
    """Een mijlpaal op een merk zonder lijn hoort nergens bij en verdwijnt
    zodra iemand op merk filtert."""
    laad(client)
    r = zet(client, merk="BESTAATNIET")
    assert r.status_code == 422
    assert "BESTAATNIET" in r.json()["detail"]
    # De geldige keuzes staan in de melding, anders is het raden.
    assert "TWEEZERMAN" in r.json()["detail"]


def test_merk_is_verplicht(client):
    laad(client)
    assert client.post("/api/kruidvat/milestones", json={
        "jaar": 2025, "periode_nummer": 12, "tekst": "x"}).status_code == 422
    assert zet(client, merk="  ").status_code == 422


def test_merkfilter_toont_alleen_dat_merk(client):
    laad(client)
    zet(client, merk="TWEEZERMAN", tekst="nieuw item")
    zet(client, merk="ALESSANDRO", tekst="folderactie")

    alles = client.get("/api/kruidvat/milestones").json()
    assert sorted(m["tekst"] for m in alles) == ["folderactie", "nieuw item"]

    een = client.get("/api/kruidvat/milestones?merk=ALESSANDRO").json()
    assert [m["tekst"] for m in een] == ["folderactie"]

    twee = client.get("/api/kruidvat/milestones?merk=ALESSANDRO,TWEEZERMAN").json()
    assert len(twee) == 2


def test_mijlpaal_zonder_merk_hoort_bij_elke_selectie(client):
    """Mijlpalen van vóór de merkkolom gelden retailer-breed. Ze wegfilteren
    zou ze onzichtbaar maken zodra iemand één merk aanvinkt."""
    laad(client)
    zet(client, merk="TWEEZERMAN", tekst="nieuw item")
    import db
    with db.get_conn() as conn:
        conn.execute("INSERT INTO milestones (retailer_id, jaar, periode_nummer, "
                     "tekst) VALUES ('kruidvat', 2025, 5, 'oude mijlpaal')")

    gefilterd = client.get("/api/kruidvat/milestones?merk=ALESSANDRO").json()
    assert [m["tekst"] for m in gefilterd] == ["oude mijlpaal"]
