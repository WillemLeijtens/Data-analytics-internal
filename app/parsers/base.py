"""Shared parser contract: every retailer parser produces a ParsedFile.

The fact grain is deliberately generic so one fact table serves every
retailer:

  * ``unit``   — what a fact row is about *within* a brand/country/banner
                 feed. For Kruidvat that's the SKU; for a retailer that
                 reports per store (e.g. ICI Paris) it's the store id; for
                 brand-level totals without any finer split it's ``"-"``.
  * ``period`` — ``YYYYWW`` (ISO week) or ``YYYYMM`` (month, 01-12); which
                 one is *not* stored per row but declared once by the
                 retailer's profile (see retailers.py), since a retailer
                 reports on exactly one cadence.

Every fact dict must carry: retailer, brand, country, banner, unit, period,
sales_volume (may be None when the retailer supplies no volume),
sales_value.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedFile:
    retailer: str
    brand: str
    country: str
    banner: str
    source_filename: str
    items: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
