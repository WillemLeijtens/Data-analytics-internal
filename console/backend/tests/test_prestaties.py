"""Twee dingen die het scherm traag of leeg maakten.

1. Het dashboard riep per periode opnieuw `store_count` aan, en die scant
   telkens álle rijen. Bij Kruidvat (ruim 130 weken × meerdere reeksen) waren
   dat honderden volledige scans per verzoek: 1086 ms voor één dashboard.
2. index.html werd zonder Cache-Control geserveerd. Een browser mag dan zelf
   een bewaartermijn verzinnen, en een oude index.html verwijst naar een
   bundle-naam die na een nieuwe build niet meer bestaat — 404 op het script,
   lege pagina. In incognito (lege cache) werkte het wél.
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


def _weken(aantal: int) -> bytes:
    import seed
    return seed.make_dwh_xlsx([{"sku": "31210001", "gtin": "4049469072773",
                                "desc": "Slant", "brand": "TWEEZERMAN",
                                "weeks": {f"2026{w:02d}": (10, 100.0)
                                          for w in range(1, aantal + 1)}}])


def test_store_count_wordt_niet_per_periode_herberekend(client, monkeypatch):
    # Zonder winkelniveau in de feed kijkt store_count niet naar de periode,
    # dus is het antwoord voor elke periode gelijk. Het aantal aanroepen mag
    # daarom niet meegroeien met het aantal periodes.
    upload(client, "kv.xlsx", _weken(30))
    client.put("/api/kruidvat/instellingen", json={"winkels_targets": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV",
         "aantal_winkels": 500, "target_per_winkel": None}]})

    from engine import analytics
    tellers = {"n": 0}
    echt = analytics.store_count

    def geteld(*a, **kw):
        tellers["n"] += 1
        return echt(*a, **kw)

    monkeypatch.setattr(analytics, "store_count", geteld)
    r = client.get("/api/kruidvat/dashboard")
    assert r.status_code == 200
    periodes = len(r.json()["tijdlijn"]["periodes"])
    assert periodes >= 20                      # er ís een lange reeks
    # Een handvol aanroepen (kpi, per merk, totaal) — niet één per periode.
    assert tellers["n"] < periodes, f"{tellers['n']} aanroepen bij {periodes} periodes"


def test_cachekoppen_per_soort_verzoek(client):
    # /api: nooit uit de cache — verkoopcijfers van gisteren tonen is erger
    # dan een verzoek extra.
    assert client.get("/api/overview").headers["cache-control"] == "no-store"
    assert client.get("/healthz").headers["cache-control"] == "no-store"


def test_kop_per_soort_pad(client):
    # De SPA wordt in de container vanuit backend/static geserveerd; in de
    # test bestaat die map niet, dus controleren we de regel per soort pad.
    for pad, verwacht in (("/assets/index-abc123.js", "public, max-age=31536000, immutable"),
                          ("/api/overview", "no-store"),
                          ("/kruidvat/dashboard", "no-cache, must-revalidate")):
        r = client.get(pad)
        assert r.headers["cache-control"] == verwacht, (pad, r.headers["cache-control"])


# ------------------------------------------------------- analysecache

def test_analysecache_serveert_nooit_verouderde_cijfers(client):
    """Auditbevinding M-2: de analyses kosten ~28 ms per 1000 feitregels en
    elke schermwissel rekende alles opnieuw. De cache haalt dat weg, maar mag
    NOOIT een verouderd cijfer teruggeven — dataintegriteit gaat voor
    snelheid.

    De eerste opzet keek naar de bestandstijd van de database; in WAL-modus
    raakt elke LEZENDE verbinding het -wal-bestand, dus die stempel veranderde
    bij elk verzoek en de cache raakte nooit (0% winst). De tweede opzet had
    een handmatige tabellijst en vergat meteen contract_documents. Nu komen de
    tabellen uit sqlite_master, zodat een vergeten tabel geen stille fout kan
    zijn."""
    import seed

    def laad(weeks):
        upload(client, f"DWH__Sales_Tweezerman_KVNL_{'-'.join(weeks)}.xlsx",
               seed.make_dwh_xlsx([{"sku": "31210001", "gtin": "4049469072773",
                                    "desc": "Slant", "brand": "TWEEZERMAN",
                                    "weeks": {w: (10, 100.0) for w in weeks}}]))

    laad(["202631"])
    eerst = client.get("/api/kruidvat/dashboard").json()["kpi"]["omzet"]["waarde"]
    # Tweede identieke verzoek: mag hetzelfde antwoord geven (cache of niet).
    assert client.get("/api/kruidvat/dashboard").json()["kpi"]["omzet"]["waarde"] == eerst

    # Nu verandert de data -> het antwoord MOET meebewegen.
    laad(["202631", "202632"])
    daarna = client.get("/api/kruidvat/dashboard").json()
    assert daarna["laatste_periode"] == "2026-W32"
    assert daarna["kpi"]["omzet"]["waarde"] == 100.0     # week 32 apart


def test_analysecache_ziet_een_gewijzigd_contract(client):
    """contract_documents voedt het contractsignaal op het Overzicht, maar
    zat niet in de eerste (handmatige) tabellijst van de cache — een geüpload
    contract ververste het Overzicht toen niet. Deze test dekt precies dat."""
    import db as db_mod

    voor = next(c for c in client.get("/api/overview").json()["retailers"]
                if c["id"] == "ici-paris-xl")["signalen"]["contract"]["signaal"]
    with db_mod.get_conn() as conn:
        conn.execute(
            "INSERT INTO contract_documents (retailer_id, naam, type, geldig_tot, signaal)"
            " VALUES ('ici-paris-xl','Testcontract','contract','2020-01-01','grey')")
    na = next(c for c in client.get("/api/overview").json()["retailers"]
              if c["id"] == "ici-paris-xl")["signalen"]["contract"]["signaal"]
    assert (voor, na) != (na, na) or voor != "grey", \
        "het Overzicht hoort een nieuw contract direct te zien"
    assert na == "red", f"verlopen contract hoort rood te zijn, kreeg {na}"
