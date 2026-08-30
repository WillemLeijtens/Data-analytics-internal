"""Period parsing & arithmetic.

Canonical period strings: '2026-W32' (week) and '2026-07' (month). Profiles
declare the source format; supported formats:

  yyyyww    202632        -> 2026-W32
  yyyy-Www  2026-W32      -> 2026-W32
  mm-yyyy   07-2026       -> 2026-07
  yyyy-mm   2026-07       -> 2026-07
"""

from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache


class PeriodError(ValueError):
    pass


def _check_week(year: int, week: int):
    if not 1 <= week <= 53:
        raise PeriodError(f"weeknummer {week} buiten 1-53")
    if week == 53:
        # Niet elk jaar heeft 53 ISO-weken; "202553" is dan een tikfout of
        # exportfout die anders stil als extra periode in de trend belandt.
        try:
            dt.date.fromisocalendar(year, 53, 1)
        except ValueError:
            raise PeriodError(f"week 53 bestaat niet: {year} heeft 52 weken")


def parse_period(value, fmt: str) -> str:
    s = str(value).strip()
    if fmt == "yyyyww":
        if not re.fullmatch(r"\d{6}", s):
            raise PeriodError(f"periode {s!r} past niet op formaat yyyyww")
        year, week = int(s[:4]), int(s[4:])
        _check_week(year, week)
        return f"{year}-W{week:02d}"
    if fmt == "yyyy-Www":
        m = re.fullmatch(r"(\d{4})-W(\d{1,2})", s, flags=re.IGNORECASE)
        if not m or not 1 <= int(m.group(2)) <= 53:
            raise PeriodError(f"periode {s!r} past niet op formaat yyyy-Www")
        _check_week(int(m.group(1)), int(m.group(2)))
        return f"{m.group(1)}-W{int(m.group(2)):02d}"
    if fmt == "mm-yyyy":
        m = re.fullmatch(r"(\d{1,2})-(\d{4})", s)
        if not m or not 1 <= int(m.group(1)) <= 12:
            raise PeriodError(f"periode {s!r} past niet op formaat mm-yyyy")
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    if fmt == "yyyymm":
        if not re.fullmatch(r"\d{6}", s):
            raise PeriodError(f"periode {s!r} past niet op formaat yyyymm")
        year, month = int(s[:4]), int(s[4:])
        if not 1 <= month <= 12:
            raise PeriodError(f"maandnummer {month} buiten 1-12")
        return f"{year}-{month:02d}"
    if fmt == "yyyy-mm":
        m = re.fullmatch(r"(\d{4})-(\d{1,2})", s)
        if not m or not 1 <= int(m.group(2)) <= 12:
            raise PeriodError(f"periode {s!r} past niet op formaat yyyy-mm")
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    raise PeriodError(f"onbekend periodeformaat {fmt!r}")


# Gememoiseerd: de analyses roepen deze functies honderdduizenden keren per
# dashboard aan (237k in het auditprofiel) over hooguit een paar honderd
# verschillende periodestrings. De cache mag onbegrensd zijn: het aantal
# onderscheiden periodes is klein en groeit met hooguit ~52 per jaar.

@lru_cache(maxsize=None)
def period_year(period: str) -> int:
    return int(period[:4])


@lru_cache(maxsize=None)
def period_number(period: str) -> int:
    """Week number 1-53 or month number 1-12."""
    tail = period.split("-", 1)[1]
    return int(tail.lstrip("Ww"))


@lru_cache(maxsize=None)
def period_type_of(period: str) -> str:
    return "week" if "W" in period.upper() else "maand"


@lru_cache(maxsize=None)
def sort_key(period: str) -> tuple[int, int]:
    return (period_year(period), period_number(period))


MAANDNAMEN = ["", "januari", "februari", "maart", "april", "mei", "juni",
              "juli", "augustus", "september", "oktober", "november", "december"]


@lru_cache(maxsize=None)
def kalendermaand(period: str) -> tuple[int, int]:
    """(jaar, maand) waar deze periode bij hoort.

    Een maandperiode wijst zichzelf aan. Een ISO-week ligt vaak in twee
    maanden; die telt hier bij de maand van zijn DONDERDAG. Dat is dezelfde
    regel als de ISO-jaartelling gebruikt en het is de maand waarin de
    meeste dagen van die week vallen — een week met vier dagen in juli en
    drie in augustus hoort bij juli.
    """
    jaar, nummer = period_year(period), period_number(period)
    if period_type_of(period) == "maand":
        return (jaar, nummer)
    try:
        donderdag = dt.date.fromisocalendar(jaar, nummer, 4)
    except ValueError:               # week 53 in een 52-weekjaar
        donderdag = dt.date.fromisocalendar(jaar, 52, 4)
    return (donderdag.year, donderdag.month)


def maand_label(maand: tuple[int, int]) -> str:
    return f"{MAANDNAMEN[maand[1]]} {maand[0]}"


def maandbereik(maanden: list[tuple[int, int]]) -> str | None:
    """Een leesbaar label voor een reeks maanden: "juli-augustus 2026".

    Het jaartal maar een keer zolang het bereik binnen een jaar valt; over de
    jaarwissel heen staat het er twee keer ("december 2025-januari 2026"),
    anders leest het als een bereik binnen het laatste jaar.
    """
    if not maanden:
        return None
    eerste, laatste = maanden[0], maanden[-1]
    if eerste == laatste:
        return maand_label(eerste)
    if eerste[0] == laatste[0]:
        return f"{MAANDNAMEN[eerste[1]]}-{MAANDNAMEN[laatste[1]]} {laatste[0]}"
    return f"{maand_label(eerste)}-{maand_label(laatste)}"


def _vandaag_nl() -> dt.date:
    # De retailers en gebruikers leven in Nederland; de serverklok staat op
    # UTC. Zonder tijdzone zou een week rond maandagnacht een paar uur te
    # vroeg of te laat "af" zijn.
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("Europe/Amsterdam")).date()


def vorige_periode(period: str) -> str:
    """De kalenderperiode direct vóór deze — voor week-op-week/maand-op-maand
    vergelijkingen (in tegenstelling tot dezelfde periode vorig jaar). Rondt
    de jaarwisseling correct af: week 1 wordt de laatste ISO-week van het
    voorgaande jaar (52 of 53), niet "week 0"."""
    jaar, nummer = period_year(period), period_number(period)
    if period_type_of(period) == "maand":
        return f"{jaar - 1}-12" if nummer == 1 else f"{jaar}-{nummer - 1:02d}"
    if nummer > 1:
        return f"{jaar}-W{nummer - 1:02d}"
    # 28 december valt door de ISO-definitie altijd in de laatste week van
    # het jaar — een robuuste manier om 52 vs. 53 weken te onderscheiden.
    vorig_jaar = jaar - 1
    laatste_week = dt.date(vorig_jaar, 12, 28).isocalendar()[1]
    return f"{vorig_jaar}-W{laatste_week:02d}"


def is_afgesloten(period: str, vandaag: dt.date | None = None) -> bool:
    """Is deze periode voorbij, of loopt hij nog?

    Een retailer die halverwege de maand levert, levert een halve maand. Die
    als volledige periode tonen zakt de trendlijn, verlaagt de KPI en maakt de
    YTD-vergelijking oneerlijk (halve maand tegen hele maand vorig jaar).
    Daarom weet elke analyse of de laatste periode al af is."""
    vandaag = vandaag or _vandaag_nl()
    jaar, nummer = period_year(period), period_number(period)
    if period_type_of(period) == "maand":
        return (jaar, nummer) < (vandaag.year, vandaag.month)
    try:
        # ISO-weken: de week is af zodra de zondag voorbij is.
        zondag = dt.date.fromisocalendar(jaar, nummer, 7)
    except ValueError:
        # Week 53 in een jaar dat er 52 heeft: bestaat niet, dus niet lopend.
        return True
    return vandaag > zondag
