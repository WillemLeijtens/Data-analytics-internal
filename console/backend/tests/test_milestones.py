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


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for name in ("db", "seed", "main"):
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def zet(client, jaar=2025, periode=12, tekst="introductie nieuw item", **extra):
    return client.post("/api/kruidvat/milestones", json={
        "jaar": jaar, "periode_nummer": periode, "tekst": tekst, **extra})


def test_mijlpaal_zetten_en_teruglezen(client):
    r = zet(client, door="Willem")
    assert r.status_code == 200
    gemaakt = r.json()
    assert (gemaakt["jaar"], gemaakt["periode_nummer"]) == (2025, 12)
    assert gemaakt["aangemaakt_door"] == "Willem"

    lijst = client.get("/api/kruidvat/milestones").json()
    assert [m["id"] for m in lijst] == [gemaakt["id"]]
    assert lijst[0]["tekst"] == "introductie nieuw item"


def test_lijst_staat_op_volgorde_van_de_x_as(client):
    for jaar, periode in ((2026, 3), (2025, 40), (2025, 2)):
        zet(client, jaar=jaar, periode=periode, tekst=f"{jaar}-{periode}")
    lijst = client.get("/api/kruidvat/milestones").json()
    assert [(m["jaar"], m["periode_nummer"]) for m in lijst] == [
        (2025, 2), (2025, 40), (2026, 3)]


def test_meerdere_mijlpalen_in_dezelfde_week_mogen(client):
    """Twee dingen in één week is geen fout: allebei tonen, niet overschrijven."""
    zet(client, tekst="nieuw item")
    zet(client, tekst="folderactie")
    lijst = client.get("/api/kruidvat/milestones").json()
    assert sorted(m["tekst"] for m in lijst) == ["folderactie", "nieuw item"]


def test_lege_tekst_wordt_geweigerd(client):
    """Een naamloze marker op de grafiek verklaart niets."""
    assert zet(client, tekst="   ").status_code == 422
    assert client.get("/api/kruidvat/milestones").json() == []


@pytest.mark.parametrize("periode", [0, 54, -1])
def test_periodenummer_buiten_de_as_wordt_geweigerd(client, periode):
    assert zet(client, periode=periode).status_code == 422


def test_lange_tekst_wordt_afgekapt(client):
    """Een label op een grafiek is kort; de rest zou de lijn onleesbaar maken."""
    m = zet(client, tekst="x" * 500).json()
    assert len(m["tekst"]) == 200


def test_verwijderen(client):
    m = zet(client).json()
    assert client.delete(f"/api/kruidvat/milestones/{m['id']}").status_code == 200
    assert client.get("/api/kruidvat/milestones").json() == []
    assert client.delete(f"/api/kruidvat/milestones/{m['id']}").status_code == 404


def test_mijlpaal_van_andere_retailer_is_niet_te_verwijderen(client):
    m = zet(client).json()
    assert client.delete(f"/api/etos/milestones/{m['id']}").status_code == 404
    assert len(client.get("/api/kruidvat/milestones").json()) == 1


def test_onbekende_retailer_geeft_404(client):
    assert client.get("/api/bestaatniet/milestones").status_code == 404
    assert client.post("/api/bestaatniet/milestones", json={
        "jaar": 2025, "periode_nummer": 12, "tekst": "x"}).status_code == 404
