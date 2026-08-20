"""Toegangsmodus van de Streamlit-app.

Apart bestand zodat de regel te testen is zonder Streamlit te starten:
streamlit_app.py bouwt bij import meteen de hele pagina op.
"""

from __future__ import annotations

import os
from ipaddress import ip_address


def _is_private_bind(value: str) -> bool:
    """Gateway-modus mag alleen op loopback/prive/link-local binden. Een
    lijst met wildcards afwijzen is niet genoeg: een publiek IP invullen zou
    de app net zo goed onbeschermd publiceren. Zelfde regel als in
    console/backend/main.py, zodat de twee apps niet uit elkaar lopen."""
    try:
        address = ip_address(value.strip().strip("[]").split("%", 1)[0])
    except ValueError:
        return value.strip().lower() == "localhost"
    return (address.is_loopback or address.is_private or address.is_link_local) \
        and not address.is_unspecified


class ConfiguratieFout(RuntimeError):
    """Een toegangsinstelling die de app publiek zou zetten."""


def resolve_auth(env: dict | None = None) -> str:
    """'gateway' of 'password' — welke laag bewaakt deze app?

    - gateway:  geen eigen inlog, het portaal authenticeert. Alleen bij een
                prive binding; anders een harde fout, want dat is de enige
                combinatie die verkoopcijfers stil publiek zou zetten.
    - password: het gedeelde wachtwoord in de app zelf (standaard).
    """
    env = os.environ if env is None else env
    modus = (env.get("APP_AUTH") or "password").strip().lower()
    if modus not in ("gateway", "password"):
        raise ConfiguratieFout(
            f"APP_AUTH={modus!r} is ongeldig; kies 'gateway' of 'password'."
        )
    if modus == "gateway":
        bind = env.get("APP_BIND", "127.0.0.1")
        if not _is_private_bind(bind):
            raise ConfiguratieFout(
                f"APP_AUTH=gateway samen met APP_BIND={bind!r} zou de app "
                "zonder toegangscontrole publiek kunnen publiceren. Bind op "
                "127.0.0.1 of het prive-adres, of kies APP_AUTH=password."
            )
    return modus
