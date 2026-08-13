"""Backwards-compatible shim: the Kruidvat parser moved to
app/parsers/kruidvat.py when the multi-retailer registry (retailers.py)
was introduced. Import from there (or pick a parser via a RetailerProfile)
in new code."""

from parsers.base import ParsedFile  # noqa: F401
from parsers.kruidvat import parse_workbook, parse_filename  # noqa: F401
