"""De toegangsmodus van de Streamlit-app.

Deze regel bepaalt of er een inlogscherm vóór de verkoopcijfers staat. De
gevaarlijke combinatie is `gateway` (geen eigen inlog) samen met een publieke
binding: dan is de app voor iedereen open. Die moet hard weigeren, niet
waarschuwen.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def load_auth():
    path = Path(__file__).resolve().parents[1] / "app" / "auth.py"
    spec = importlib.util.spec_from_file_location("legacy_app_auth", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


auth = load_auth()


def test_standaard_is_wachtwoord():
    # Geen APP_AUTH gezet: het bestaande gedrag blijft, zodat een bestaande
    # .env niet stilzwijgend van beveiliging verandert.
    assert auth.resolve_auth({}) == "password"
    assert auth.resolve_auth({"APP_AUTH": ""}) == "password"


@pytest.mark.parametrize("bind", ["127.0.0.1", "localhost", "10.110.0.5",
                                  "192.168.1.9", "172.16.0.4", "169.254.1.1"])
def test_gateway_mag_bij_een_prive_binding(bind):
    assert auth.resolve_auth({"APP_AUTH": "gateway", "APP_BIND": bind}) == "gateway"


@pytest.mark.parametrize("bind", ["0.0.0.0", "188.166.88.105", "::", "8.8.8.8"])
def test_gateway_weigert_een_publieke_binding(bind):
    # Dit is de enige combinatie die de verkoopcijfers stil publiek zet.
    with pytest.raises(auth.ConfiguratieFout) as e:
        auth.resolve_auth({"APP_AUTH": "gateway", "APP_BIND": bind})
    assert "APP_AUTH=gateway" in str(e.value)


def test_gateway_zonder_bind_valt_terug_op_loopback():
    assert auth.resolve_auth({"APP_AUTH": "gateway"}) == "gateway"


def test_onbekende_modus_is_een_fout():
    # Een typefout mag niet stilletjes op 'password' of 'gateway' uitkomen.
    with pytest.raises(auth.ConfiguratieFout):
        auth.resolve_auth({"APP_AUTH": "geen"})


def test_hoofdletters_en_spaties_tellen_niet_mee():
    assert auth.resolve_auth({"APP_AUTH": " GATEWAY ",
                              "APP_BIND": " 127.0.0.1 "}) == "gateway"
