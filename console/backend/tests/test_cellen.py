"""De gedeelde identifier-conversie.

Deze module bestaat naar aanleiding van een auditbevinding: dezelfde
`str(int(cel))`-fout stond drie keer los in de codebase (Kruidvat, Etos,
ICI). Toen hij in één parser gecorrigeerd werd, bleven de andere twee
stilzwijgend identifiers verminken. Deze tests pinnen het gedrag op één
plek vast.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.cellen import als_identifier  # noqa: E402


def test_tekstcel_behoudt_leidende_nullen():
    """De kern van de bevinding: '012345678905' is een ánder artikel dan
    '12345678905'."""
    assert als_identifier("012345678905") == "012345678905"
    assert als_identifier("007") == "007"
    assert als_identifier("0042") == "0042"


def test_float_staart_wordt_verwijderd():
    """Een identifier die onderweg door een float is gegaan: de '.0' is een
    opslagartefact, geen onderdeel van de identifier."""
    assert als_identifier("4049469072773.0") == "4049469072773"
    assert als_identifier(4049469072773.0) == "4049469072773"
    assert als_identifier("007.00") == "007"


def test_echte_decimalen_worden_niet_afgekapt():
    """'1.5' is geen float-artefact maar andere inhoud; stil afkappen zou
    opnieuw data weggooien."""
    assert als_identifier("1.5") == "1.5"
    assert als_identifier(1.5) is None      # numeriek en niet-geheel: geen identifier


def test_numerieke_cel_zonder_kunstjes():
    """Een getalcel kan een leidende nul per definitie niet dragen, dus daar
    is int() ongevaarlijk."""
    assert als_identifier(31210001) == "31210001"
    assert als_identifier(42) == "42"


def test_onbruikbare_cellen_geven_none():
    for leeg in (None, "", "   ", True, False, float("nan"), float("inf")):
        assert als_identifier(leeg) is None, f"{leeg!r} hoort None te geven"


def test_spaties_worden_gestript_maar_inhoud_niet():
    assert als_identifier("  4049469072773  ") == "4049469072773"
    assert als_identifier("  0042  ") == "0042"
