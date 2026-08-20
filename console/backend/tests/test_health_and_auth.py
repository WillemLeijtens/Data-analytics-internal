"""HTTP-level guarantees the platform depends on.

The health probe MUST stay reachable without credentials, in every spelling
a monitor might use — a 401 here shows up as a false "down" in uptime
monitoring. Everything else must stay behind auth when a password is set.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROBES = ["/healthz", "/healthz/", "/healthz?probe=1"]
METHODS = ["GET", "HEAD"]


def build_app(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for name in ("db", "seed", "main"):
        sys.modules.pop(name, None)
    return importlib.import_module("main")


@pytest.fixture()
def client_with_password(tmp_path, monkeypatch):
    main = build_app(tmp_path, monkeypatch, CONSOLE_AUTH="password",
                     CONSOLE_PASSWORD="geheim")
    return TestClient(main.app)


@pytest.fixture()
def client_open(tmp_path, monkeypatch):
    main = build_app(tmp_path, monkeypatch, CONSOLE_AUTH="gateway",
                     CONSOLE_BIND="127.0.0.1")
    return TestClient(main.app)


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("path", PROBES)
def test_health_open_even_with_password(client_with_password, method, path):
    assert client_with_password.request(method, path).status_code == 200


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("path", PROBES)
def test_health_open_without_password(client_open, method, path):
    assert client_open.request(method, path).status_code == 200


def test_health_reports_broken_database(client_with_password, tmp_path):
    (tmp_path / "console.db").write_bytes(b"dit is geen sqlite-bestand" * 40)
    assert client_with_password.get("/healthz").status_code == 503


@pytest.mark.parametrize("path", ["/api/overview", "/", "/kruidvat/dashboard"])
def test_everything_else_needs_credentials(client_with_password, path):
    assert client_with_password.get(path).status_code == 401


def test_correct_credentials_pass(client_with_password):
    r = client_with_password.get("/api/overview", auth=("console", "geheim"))
    assert r.status_code == 200


def test_open_mode_refuses_to_bind_all_interfaces(tmp_path, monkeypatch):
    """The one combination that would publish sales data unprotected."""
    with pytest.raises(RuntimeError, match="publiek"):
        build_app(tmp_path, monkeypatch, CONSOLE_AUTH="gateway",
                  CONSOLE_BIND="0.0.0.0")


def test_open_mode_refuses_specific_public_address(tmp_path, monkeypatch):
    """Alleen wildcards weigeren is niet genoeg: een publiek IP publiceert
    de console net zo goed onbeschermd."""
    with pytest.raises(RuntimeError, match="publiek"):
        build_app(tmp_path, monkeypatch, CONSOLE_AUTH="gateway",
                  CONSOLE_BIND="8.8.8.8")


def test_open_mode_accepts_private_address(tmp_path, monkeypatch):
    main = build_app(tmp_path, monkeypatch, CONSOLE_AUTH="gateway",
                     CONSOLE_BIND="10.110.0.5")
    assert TestClient(main.app).get("/healthz").status_code == 200


def test_no_mode_chosen_refuses(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="toegangsmodus"):
        build_app(tmp_path, monkeypatch)


def test_password_mode_without_password_refuses(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="vereist een gevulde"):
        build_app(tmp_path, monkeypatch, CONSOLE_AUTH="password")


def test_invalid_mode_refuses(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="ongeldig"):
        build_app(tmp_path, monkeypatch, CONSOLE_AUTH="misschien")


# --- regression: a stray password must never re-enable the browser prompt ---

@pytest.mark.parametrize("path", ["/api/overview", "/", "/kruidvat/dashboard",
                                  "/healthz"])
def test_gateway_mode_never_prompts_even_with_password_set(
        tmp_path, monkeypatch, path):
    """Reported from the portal: after a successful forward-auth login the
    browser still showed a Basic-Auth popup, because a leftover
    CONSOLE_PASSWORD in .env silently won over the gateway setting."""
    main = build_app(tmp_path, monkeypatch, CONSOLE_AUTH="gateway",
                     CONSOLE_BIND="127.0.0.1", CONSOLE_PASSWORD="restje")
    r = TestClient(main.app).get(path)
    assert r.status_code != 401
    assert "www-authenticate" not in {k.lower() for k in r.headers}


def test_legacy_allow_open_beats_leftover_password(tmp_path, monkeypatch):
    main = build_app(tmp_path, monkeypatch, CONSOLE_ALLOW_OPEN="1",
                     CONSOLE_PASSWORD="restje")
    assert TestClient(main.app).get("/api/overview").status_code == 200
