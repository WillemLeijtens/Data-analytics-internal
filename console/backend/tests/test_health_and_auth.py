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
    main = build_app(tmp_path, monkeypatch, CONSOLE_PASSWORD="geheim",
                     CONSOLE_ALLOW_OPEN="0")
    return TestClient(main.app)


@pytest.fixture()
def client_open(tmp_path, monkeypatch):
    main = build_app(tmp_path, monkeypatch, CONSOLE_ALLOW_OPEN="1",
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
    with pytest.raises(RuntimeError, match="alle interfaces"):
        build_app(tmp_path, monkeypatch, CONSOLE_ALLOW_OPEN="1",
                  CONSOLE_BIND="0.0.0.0")


def test_no_password_and_no_explicit_open_refuses(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="CONSOLE_PASSWORD"):
        build_app(tmp_path, monkeypatch, CONSOLE_ALLOW_OPEN="0")
