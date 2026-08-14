"""File detection + parsing against a parser profile (PROMPT.md §3).

Detection: filename_glob first, sheet/required_headers as tiebreak. Zero or
multiple matches -> the import gets status 'profiel_nodig'. Only live/test
profiles take part in detection; concept profiles exist to be completed in
the Parser screen.

Parsing is transactional at the caller: this module either returns the full
list of canonical fact dicts or raises ParseError with row-level detail —
never a partial result.
"""

from __future__ import annotations

import csv
import fnmatch
import io
import re

from .periods import PeriodError, parse_period
from .profile import Profile, capabilities

EAN_RE = re.compile(r"\d{8}$|\d{13}$")


class ParseError(Exception):
    def __init__(self, message: str, row_errors: list[dict] | None = None):
        super().__init__(message)
        self.row_errors = row_errors or []


# ---------------------------------------------------------------- reading

def _read_csv(content: bytes, delimiter: str) -> list[list[str]]:
    text = content.decode("utf-8-sig")
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter or ";")]


def _read_xlsx(content: bytes, sheet: str | None) -> list[list]:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    if sheet and sheet in wb.sheetnames:
        ws = wb[sheet]
    elif sheet:
        raise ParseError(f"werkblad {sheet!r} niet gevonden (wel: {', '.join(wb.sheetnames)})")
    else:
        ws = wb[wb.sheetnames[0]]
    return [["" if c is None else c for c in row] for row in ws.iter_rows(values_only=True)]


def read_table(content: bytes, detection: dict) -> tuple[list[str], list[list]]:
    """Returns (headers, data_rows) using the profile's header_row (1-based)."""
    if detection.get("filetype") == "csv":
        rows = _read_csv(content, detection.get("csv_delimiter"))
    else:
        rows = _read_xlsx(content, detection.get("sheet"))
    header_row = int(detection.get("header_row") or 1)
    if len(rows) < header_row:
        raise ParseError(f"bestand heeft geen rij {header_row} (header-rij volgens profiel)")
    headers = [str(h).strip() for h in rows[header_row - 1]]
    data = [r for r in rows[header_row:] if any(str(c).strip() for c in r)]
    return headers, data


def probe_headers(content: bytes, detection: dict) -> list[str] | None:
    try:
        headers, _ = read_table(content, detection)
        return headers
    except Exception:  # noqa: BLE001 - a failed probe just means "no match"
        return None


# ---------------------------------------------------------------- detection

def sniff(filename: str, content: bytes) -> dict | None:
    """Best-effort look inside an UNRECOGNISED file, so the Parser screen can
    offer its real columns instead of an empty mapping table.

    Returns {filetype, sheet, header_row, csv_delimiter, columns, voorbeeld}
    or None when nothing table-like is found. Never raises: a file we cannot
    read simply yields no suggestion.
    """
    name = filename.lower()
    try:
        if name.endswith((".csv", ".txt", ".tsv")):
            return _sniff_csv(content)
        if name.endswith((".xlsx", ".xlsm")):
            return _sniff_xlsx(content)
        # Unknown extension: try both, spreadsheet first.
        return _sniff_xlsx(content) or _sniff_csv(content)
    except Exception:  # noqa: BLE001 - a failed sniff is not an error
        return None


def _score(cells: list) -> int:
    """How much a row looks like a header: non-empty, non-numeric labels."""
    score = 0
    for c in cells:
        s = str(c).strip()
        if not s or s.startswith("#"):
            continue
        try:
            float(s.replace(",", "."))
        except ValueError:
            score += 1
    return score


def _pick_header(rows: list[list], limit: int = 25) -> tuple[int, list[str]] | None:
    """Header = the highest-scoring row in the first `limit` rows; ties go to
    the earliest. Handles metadata blocks above the real header."""
    best = None
    for i, row in enumerate(rows[:limit]):
        s = _score(row)
        if s >= 2 and (best is None or s > best[0]):
            best = (s, i)
    if best is None:
        return None
    idx = best[1]
    headers = [str(c).strip() for c in rows[idx]]
    while headers and not headers[-1]:
        headers.pop()
    return idx, headers


def _sniff_csv(content: bytes) -> dict | None:
    text = content.decode("utf-8-sig", errors="replace")
    best = None
    for delim in (";", ",", "\t", "|"):
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim)]
        rows = [r for r in rows if not (r and str(r[0]).startswith("#"))]
        picked = _pick_header(rows)
        if picked and (best is None or len(picked[1]) > len(best[1][1])):
            best = (delim, picked, rows)
    if not best or len(best[1][1]) < 2:
        return None
    delim, (idx, headers), rows = best
    sample = rows[idx + 1] if len(rows) > idx + 1 else []
    return {"filetype": "csv", "sheet": None, "header_row": idx + 1,
            "csv_delimiter": delim, "columns": headers,
            "voorbeeld": [str(c) for c in sample[:len(headers)]]}


def _sniff_xlsx(content: bytes) -> dict | None:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    best = None
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            rows.append(["" if c is None else c for c in row])
            if i >= 30:
                break
        picked = _pick_header(rows)
        if picked and (best is None or len(picked[1]) > len(best[1][1])):
            best = (sheet, picked, rows)
    if not best or len(best[1][1]) < 2:
        return None
    sheet, (idx, headers), rows = best
    sample = rows[idx + 1] if len(rows) > idx + 1 else []
    return {"filetype": "xlsx", "sheet": sheet, "header_row": idx + 1,
            "csv_delimiter": None, "columns": headers,
            "voorbeeld": [str(c) for c in sample[:len(headers)]]}


def detect(filename: str, content: bytes, profiles: list[Profile]) -> Profile | None:
    """Pick the profile for a file. None => 'profiel_nodig'."""
    candidates = [p for p in profiles if p.status in ("live", "test")
                  and fnmatch.fnmatch(filename.lower(),
                                      p.definition["detection"]["filename_glob"].lower())]
    if len(candidates) > 1:
        # Tiebreak on sheet + required headers actually present.
        confirmed = [p for p in candidates if _headers_match(content, p)]
        candidates = confirmed if confirmed else candidates
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return None  # ambiguous — user must map/choose once
    # No filename match: try content-based match as a last resort.
    confirmed = [p for p in profiles if p.status in ("live", "test") and _headers_match(content, p)]
    return confirmed[0] if len(confirmed) == 1 else None


def _headers_match(content: bytes, profile: Profile) -> bool:
    det = profile.definition["detection"]
    headers = probe_headers(content, det)
    if headers is None:
        return False
    hset = {h.lower() for h in headers}
    return all(req.lower() in hset for req in det.get("required_headers", []))


# ---------------------------------------------------------------- numbers

def parse_number(value, decimal: str) -> float:
    """Parse with the profile's decimal sign; both '1.234,56' and '1234.56'."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("€", "").replace(" ", "")
    if not s:
        raise ValueError("leeg")
    if decimal == ",":
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    return float(s)


# ---------------------------------------------------------------- parsing

def parse_file(filename: str, content: bytes, profile: Profile) -> dict:
    """Parse + validate a whole file against a profile.

    Returns {'facts': [...], 'periode_type': .., 'periodes': [..]} or raises
    ParseError carrying row-level errors (PROMPT §3: never half imports).
    """
    d = profile.definition
    det = d["detection"]
    headers, data = read_table(content, det)
    hindex = {h.lower(): i for i, h in enumerate(headers)}

    missing_headers = [req for req in det.get("required_headers", [])
                       if req.lower() not in hindex]
    if missing_headers:
        raise ParseError("verplichte kolommen ontbreken: " + ", ".join(missing_headers))

    period_cfg = d["period"]
    period_col = period_cfg["source_column"].lower()
    if period_col not in hindex:
        raise ParseError(f"periodekolom {period_cfg['source_column']!r} niet gevonden")

    mapping = [(m["source"].lower(), m["target"], m.get("normalize"))
               for m in d.get("mapping", []) if m.get("target")]
    for source, target, _n in mapping:
        if source not in hindex:
            raise ParseError(f"gemapte kolom {source!r} niet gevonden in het bestand")

    caps = capabilities(d)
    decimal = det.get("decimal") or ","
    constants = d.get("constants", {})

    facts: list[dict] = []
    errors: list[dict] = []
    for rownum, row in enumerate(data, start=int(det.get("header_row") or 1) + 1):
        fact = {"land": None, "banner": None, "winkel_id": None, "winkel_naam": None,
                "merk": None, "artikel_ean": None, "artikel_naam": None}
        fact.update(constants)
        try:
            fact["periode"] = parse_period(row[hindex[period_col]], period_cfg["format"])
        except (PeriodError, IndexError) as e:
            errors.append({"rij": rownum, "veld": "periode", "fout": str(e)})
            continue
        row_ok = True
        for source, target, normalize in mapping:
            raw = row[hindex[source]] if hindex[source] < len(row) else ""
            try:
                if target in ("volume", "omzet"):
                    value = parse_number(raw, decimal)
                    if target == "volume":
                        value = int(round(value))
                else:
                    value = str(raw).strip()
                    if normalize == "upper":
                        value = value.upper()
                    if target == "artikel_ean" and value and not EAN_RE.fullmatch(value):
                        raise ValueError(f"EAN {value!r} is niet 8 of 13 cijfers")
            except (ValueError, TypeError) as e:
                errors.append({"rij": rownum, "veld": target, "fout": str(e)})
                row_ok = False
                break
            fact[target] = value
        if not row_ok:
            continue
        for req in ("volume", "omzet"):
            if fact.get(req) is None:
                errors.append({"rij": rownum, "veld": req, "fout": "verplicht veld leeg"})
                row_ok = False
        if caps["merk"] and not fact.get("merk"):
            errors.append({"rij": rownum, "veld": "merk", "fout": "verplicht veld leeg"})
            row_ok = False
        if row_ok:
            facts.append(fact)

    if errors:
        raise ParseError(f"{len(errors)} rij(en) met fouten", row_errors=errors)
    if not facts:
        raise ParseError("bestand bevat geen datarijen")

    return {
        "facts": facts,
        "periode_type": period_cfg["type"],
        "periodes": sorted({f["periode"] for f in facts}),
    }
