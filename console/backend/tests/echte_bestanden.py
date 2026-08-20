"""Waar de échte retailerbestanden staan, en wat er moet gebeuren als ze er
niet zijn.

Auditbevinding H-3: de tests die correctheid verankeren aan echte
aanleverbestanden (exacte merktotalen over 4566 regels, de ICI-decompositie
tegen de auditcijfers) laadden hun fixture uit een sessiegebonden pad. Dat
pad bestaat niet in GitHub Actions, dus die tests sloegen daar stilzwijgend
over: CI meldde groen terwijl juist de zwaarste garanties niet draaiden.

De bestanden zélf horen niet in de repo — het is echte, commercieel
gevoelige verkoopdata van onze retailers. In plaats daarvan:

  * CONSOLE_FIXTURES_DIR  wijst naar de map waar ze staan (in CI: mount ze
                          uit een secret store of artifact, niet uit git).
  * CONSOLE_REAL_FIXTURES=1  maakt hun aanwezigheid VERPLICHT: ontbreken ze
                          dan, dan faalt de run luid in plaats van stil over
                          te slaan.

Zonder die variabelen gedragen de tests zich als voorheen (overslaan), zodat
een verse checkout zonder de bestanden gewoon werkt.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

STANDAARD_MAP = "/root/.claude/uploads/54377bab-ac94-5cbf-8750-c3a4d90899e0"

MAP = Path(os.environ.get("CONSOLE_FIXTURES_DIR") or STANDAARD_MAP)
VERPLICHT = os.environ.get("CONSOLE_REAL_FIXTURES", "").strip() == "1"


def vereist(*paden: Path):
    """Decorator: sla over als de bestanden ontbreken — tenzij ze verplicht
    zijn gesteld, dan is ontbreken een fout."""
    ontbreekt = [p.name for p in paden if not p.exists()]
    if not ontbreekt:
        return pytest.mark.skipif(False, reason="")
    if VERPLICHT:
        raise RuntimeError(
            "CONSOLE_REAL_FIXTURES=1, maar deze echte bestanden ontbreken in "
            f"{MAP}: {', '.join(ontbreekt)}. Zet CONSOLE_FIXTURES_DIR naar de "
            "map waar ze staan, of haal CONSOLE_REAL_FIXTURES weg.")
    return pytest.mark.skip(
        reason=f"echt sample-bestand niet aanwezig ({', '.join(ontbreekt)}); "
               "zet CONSOLE_FIXTURES_DIR, of CONSOLE_REAL_FIXTURES=1 om dit "
               "een fout te maken")
