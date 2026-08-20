"""Retailer profile registry — the single place that says what each
retailer's data looks like and what it can support.

Adding a retailer = one parser module in app/parsers/ + one profile entry
here. Everything else (import page, dashboard visuals, promotions, import
status, settings, auto-import) reads the profile and adapts:

  * period_type steers every time axis (weeks 1-53 vs months 1-12), the
    YTD comparison window and all period labels;
  * unit_type/has_items steer whether the per-unit analysis section shows
    items (SKU grain) or stores, or is hidden;
  * has_volume steers the volume tiles/charts and the automatic promo
    suggestion (unit price needs volume) — manual promo marking and the
    revenue-based uplift work without volume.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from parsers import kruidvat


@dataclass(frozen=True)
class RetailerProfile:
    id: str                # stable DB value, never rename once data exists
    display_name: str
    period_type: str       # "week" | "month"
    unit_type: str         # "sku" | "store"
    parser: Callable       # parse(path, filename) -> parsers.base.ParsedFile
    has_items: bool        # item attributes present -> item analysis, sparklines
    has_volume: bool       # sales volume present -> volume visuals + promo suggestion
    file_hint: str = ".xlsx"   # shown on the import page

    @property
    def period_word(self) -> str:
        return "week" if self.period_type == "week" else "maand"

    @property
    def period_max(self) -> int:
        return 53 if self.period_type == "week" else 12

    @property
    def unit_word(self) -> str:
        return "Item" if self.unit_type == "sku" else "Winkel"


RETAILERS: dict[str, RetailerProfile] = {
    "KRUIDVAT": RetailerProfile(
        id="KRUIDVAT",
        display_name="Kruidvat & Trekpleister",
        period_type="week",
        unit_type="sku",
        parser=kruidvat.parse_workbook,
        has_items=True,
        has_volume=True,
        file_hint="DWH sellout export (.xlsx)",
    ),
    # Etos / ICI Paris XL / Douglas: profile + parser land here as soon as a
    # real sample file is available — parsers built on assumptions about a
    # file layout have proven to go wrong.
}

DEFAULT_RETAILER = "KRUIDVAT"

_MONTHS_NL = ["jan", "feb", "mrt", "apr", "mei", "jun",
              "jul", "aug", "sep", "okt", "nov", "dec"]


def get_profile(retailer_id: str | None) -> RetailerProfile:
    return RETAILERS.get(retailer_id or "", RETAILERS[DEFAULT_RETAILER])


def fmt_period(period, period_type: str) -> str:
    """'202631' -> '2026-31' (week) or '202607' -> '2026-jul' (month)."""
    s = str(period)
    if len(s) != 6 or not s.isdigit():
        return s
    if period_type == "month":
        m = int(s[4:])
        if 1 <= m <= 12:
            return f"{s[:4]}-{_MONTHS_NL[m - 1]}"
    return f"{s[:4]}-{s[4:]}"
