"""Bestanden die geen parser aankan worden bewaard.

Waarom: de droplet is soms alleen via een webconsole in de browser
bereikbaar, en dan is er geen scp om een bestand naartoe te kopiëren. Een
bestand dat de parser afwijst zou dan onbereikbaar zijn voor het eenmalige
inleesgereedschap in tools/. Nu landt het in <data>/inbox en noemt het
scherm het pad.

Geslaagde imports worden NIET bewaard: die zitten al in de feiten, en een
tweede kopie op schijf is dan alleen maar een extra plek waar verkoopdata
rondslingert.
"""

from __future__ import annotations

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
    for naam in ("db", "seed", "main"):
        sys.modules.pop(naam, None)
    main = importlib.import_module("main")
    return TestClient(main.app), tmp_path / "inbox"


def _upload(c, naam, inhoud):
    r = c.post("/api/import", files=[("files", (naam, inhoud))])
    assert r.status_code == 200
    return r.json()["results"][0]


def test_onherkenbaar_bestand_wordt_bewaard(client):
    c, inbox = client
    uitkomst = _upload(c, "iets_onbekends.xlsx", b"geen geldig xlsx")
    assert uitkomst["status"] in ("profiel_nodig", "error")
    bewaard = Path(uitkomst["bewaard_als"])
    assert bewaard.parent == inbox
    assert bewaard.read_bytes() == b"geen geldig xlsx"
    # Het pad staat in de melding, want daar leest de gebruiker het af.
    assert str(bewaard) in uitkomst["detail"]


def test_geslaagde_import_wordt_niet_bewaard(client):
    c, inbox = client
    import seed
    uitkomst = _upload(c, "kv.xlsx", seed.make_dwh_xlsx(
        [{"sku": "31210001", "gtin": "4049469072773", "desc": "Slant",
          "brand": "TWEEZERMAN", "weeks": {"202632": (10, 100.0)}}]))
    assert uitkomst["status"] == "ingelezen"
    assert "bewaard_als" not in uitkomst
    assert not inbox.exists()


def test_bestandsnaam_kan_niet_uit_de_map_stappen(client):
    c, inbox = client
    uitkomst = _upload(c, "../../etc/passwd.xlsx", b"onzin")
    bewaard = Path(uitkomst["bewaard_als"])
    assert bewaard.parent == inbox, "de naam mag nooit een pad opleveren"
    assert ".." not in bewaard.name


def test_zelfde_bestand_nog_eens_overschrijft(client):
    c, inbox = client
    _upload(c, "zelfde.xlsx", b"eerste")
    tweede = _upload(c, "zelfde.xlsx", b"tweede versie")
    assert Path(tweede["bewaard_als"]).read_bytes() == b"tweede versie"
    assert len(list(inbox.iterdir())) == 1
