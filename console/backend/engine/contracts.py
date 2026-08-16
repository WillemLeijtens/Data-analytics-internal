"""ContractSource: interface for the SharePoint folder that holds contract
documents. Only the mock is implemented — the real Microsoft Graph
implementation is a TODO; it must return the same document dicts.

De mock levert VERZONNEN documenten ("Distributieovereenkomst, verloopt
31-08-2026") en die kleuren het contractsignaal op het Overzicht. Zolang de
Graph-koppeling er niet is, mag dat nooit in een echte omgeving belanden:
de mock doet alleen mee als CONSOLE_CONTRACTS=mock expliciet gezet is
(seed en tests). Standaard levert een gekoppelde map niets — een leeg
scherm is eerlijk, een verzonnen contract niet.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol


class ContractSource(Protocol):
    def list_documents(self, retailer_id: str) -> list[dict]:
        """[{naam, type, geldig_tot, signaal}] for the linked folder."""
        ...


class MockContractSource:
    """Reads console/seed/contracts.json — stands in for the Graph API."""

    def __init__(self, path: Path | None = None):
        self.path = path or Path(__file__).resolve().parents[2] / "seed" / "contracts.json"

    def list_documents(self, retailer_id: str) -> list[dict]:
        data = json.loads(self.path.read_text())
        return data.get(retailer_id, [])


class GeenContractBron:
    """Er is nog geen koppeling met SharePoint. Levert niets — en verzint
    dus ook niets."""

    def list_documents(self, retailer_id: str) -> list[dict]:
        return []


# TODO: GraphContractSource(site, drive, folder) via Microsoft Graph API.
def get_source() -> ContractSource:
    if os.environ.get("CONSOLE_CONTRACTS", "").strip().lower() == "mock":
        return MockContractSource()
    return GeenContractBron()


def bron_naam() -> str:
    return "mock" if isinstance(get_source(), MockContractSource) else "niet gekoppeld"


def sync_documents(conn, retailer_id: str, source: ContractSource | None = None):
    docs = (source or get_source()).list_documents(retailer_id)
    conn.execute("DELETE FROM contract_documents WHERE retailer_id=?", (retailer_id,))
    conn.executemany(
        "INSERT INTO contract_documents (retailer_id, naam, type, geldig_tot, signaal) "
        "VALUES (?,?,?,?,?)",
        [(retailer_id, d["naam"], d.get("type"), d.get("geldig_tot"),
          d.get("signaal", "grey")) for d in docs])
    return docs
