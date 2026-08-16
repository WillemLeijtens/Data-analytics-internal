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


class PeriodError(ValueError):
    pass


def parse_period(value, fmt: str) -> str:
    s = str(value).strip()
    if fmt == "yyyyww":
        if not re.fullmatch(r"\d{6}", s):
            raise PeriodError(f"periode {s!r} past niet op formaat yyyyww")
        year, week = int(s[:4]), int(s[4:])
        if not 1 <= week <= 53:
            raise PeriodError(f"weeknummer {week} buiten 1-53")
        return f"{year}-W{week:02d}"
    if fmt == "yyyy-Www":
        m = re.fullmatch(r"(\d{4})-W(\d{1,2})", s, flags=re.IGNORECASE)
        if not m or not 1 <= int(m.group(2)) <= 53:
            raise PeriodError(f"periode {s!r} past niet op formaat yyyy-Www")
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


def period_year(period: str) -> int:
    return int(period[:4])


def period_number(period: str) -> int:
    """Week number 1-53 or month number 1-12."""
    tail = period.split("-", 1)[1]
    return int(tail.lstrip("Ww"))


def period_type_of(period: str) -> str:
    return "week" if "W" in period.upper() else "maand"


def sort_key(period: str) -> tuple[int, int]:
    return (period_year(period), period_number(period))


def in_ytd_window(period: str, upto_number: int) -> bool:
    """True when the period's week/month number falls in 1..upto_number —
    the YTD vs LYTD comparison window."""
    return period_number(period) <= upto_number


def is_afgesloten(period: str, vandaag: dt.date | None = None) -> bool:
    """Is deze periode voorbij, of loopt hij nog?

    Een retailer die halverwege de maand levert, levert een halve maand. Die
    als volledige periode tonen zakt de trendlijn, verlaagt de KPI en maakt de
    YTD-vergelijking oneerlijk (halve maand tegen hele maand vorig jaar).
    Daarom weet elke analyse of de laatste periode al af is."""
    vandaag = vandaag or dt.date.today()
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
