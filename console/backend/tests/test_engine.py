"""Engine tests — PROMPT.md acceptance 6 (+1, 4, 5).

Covers: capability derivation, all four fallback rules, period parsing
(yyyyww, yyyy-Www, mm-yyyy), decimals (comma AND point), profile detection
including conflicts, atomic imports, uplift baseline stability, and a
fictional fifth retailer working purely via a profile.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
from engine import analytics, importer
from engine import parser as parser_mod
from engine.fallback import resolve
from engine.periods import PeriodError, parse_period, period_number, period_year
from engine.profile import Profile, capabilities, missing_required

BASE = Path(__file__).resolve().parents[2]
# Profieldefinities uit het ontwerppakket: fictieve formaten, alleen nog
# in gebruik als testmateriaal voor de mapping-logica — ze worden bewust
# niet meer met de app meegeleverd.
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    c = db.connect()
    yield c
    c.commit()
    c.close()


def load_profile(name: str, status=None) -> Profile:
    d = json.loads((FIXTURES / name).read_text())
    return Profile(id=1, retailer_id=d["retailer_id"], version=d["version"],
                   status=status or d["status"], definition=d)


def insert_profile(conn, profile: Profile) -> Profile:
    cur = conn.execute(
        "INSERT INTO parser_profiles (retailer_id, version, status, definition) VALUES (?,?,?,?)",
        (profile.retailer_id, profile.version, profile.status,
         json.dumps(profile.definition)))
    return Profile(id=cur.lastrowid, retailer_id=profile.retailer_id,
                   version=profile.version, status=profile.status,
                   definition=profile.definition)


# ------------------------------------------------------------ capabilities

def test_capability_derivation_kruidvat():
    caps = capabilities(load_profile("kruidvat.json").definition)
    assert caps == {"periode": "week", "merk": True, "artikel": True,
                    "winkel": True, "banner": True, "land": True, "volume": True}


def test_capability_derivation_ici():
    caps = capabilities(load_profile("ici-paris-xl.json").definition)
    assert caps["periode"] == "maand" and caps["winkel"] and caps["merk"]
    assert not caps["artikel"] and not caps["banner"]


def test_capability_derivation_etos_constants_count():
    caps = capabilities(load_profile("etos.json").definition)
    assert caps["land"] is True          # via constants, not mapping
    assert caps["artikel"] and not caps["winkel"] and not caps["banner"]


def test_capability_derivation_douglas_unmapped():
    d = load_profile("douglas.concept.json").definition
    caps = capabilities(d)
    assert not any([caps["merk"], caps["artikel"], caps["winkel"], caps["banner"]])
    assert missing_required(d) == {"volume", "omzet"}


# ------------------------------------------------------------ fallback (4 regels)

def test_fallback_artikel_naar_merk():
    r = resolve({"artikel": False, "periode": "week"}, artikel=True)
    assert r.level_used["detail"] == "merk" and "OP MERKNIVEAU" in r.labels


def test_fallback_week_naar_maand():
    r = resolve({"periode": "maand"}, week=True)
    assert r.level_used["periode"] == "maand" and "OP MAANDNIVEAU" in r.labels


def test_fallback_winkel_naar_schatting():
    r = resolve({"winkel": False}, winkel=True)
    assert r.level_used["winkel"] == "handmatig" and "SCHATTING" in r.labels


def test_fallback_banner_naar_merk_land():
    r = resolve({"banner": False}, banner=True)
    assert r.level_used["scope"] == "merk+land"


def test_fallback_geen_terugval_geen_labels():
    r = resolve({"artikel": True, "periode": "week", "winkel": True, "banner": True},
                artikel=True, week=True, winkel=True, banner=True)
    assert r.labels == []


# ------------------------------------------------------------ periods

@pytest.mark.parametrize("value,fmt,expect", [
    ("202632", "yyyyww", "2026-W32"),
    (202601, "yyyyww", "2026-W01"),
    ("2026-W32", "yyyy-Www", "2026-W32"),
    ("2026-w5", "yyyy-Www", "2026-W05"),
    ("07-2026", "mm-yyyy", "2026-07"),
    ("12-2025", "mm-yyyy", "2025-12"),
])
def test_period_parsing(value, fmt, expect):
    assert parse_period(value, fmt) == expect


@pytest.mark.parametrize("value,fmt", [
    ("202699", "yyyyww"), ("13-2026", "mm-yyyy"), ("garbage", "yyyy-Www"),
])
def test_period_parsing_rejects(value, fmt):
    with pytest.raises(PeriodError):
        parse_period(value, fmt)


def test_period_helpers():
    assert period_year("2026-W32") == 2026 and period_number("2026-W32") == 32
    assert period_number("2026-07") == 7


# ------------------------------------------------------------ decimals

def test_decimal_comma_and_point():
    assert parser_mod.parse_number("7.180,00", ",") == 7180.0
    assert parser_mod.parse_number("15120.00", ".") == 15120.0
    assert parser_mod.parse_number("1,234.5", ".") == 1234.5
    assert parser_mod.parse_number(12, ",") == 12.0


# ------------------------------------------------------------ detection

def csv_bytes(header: str, *rows: str) -> bytes:
    return ("\n".join([header, *rows])).encode()


def test_detection_by_filename(conn):
    etos = load_profile("etos.json")
    assert parser_mod.detect("etos_sales_wk32.csv", b"", [etos]) is etos


def test_detection_concept_never_matches():
    douglas = load_profile("douglas.concept.json")
    assert parser_mod.detect("Douglas_Abverkauf_KW32.xlsx", b"", [douglas]) is None


def _other_retailer(profile: Profile, retailer_id: str) -> Profile:
    d = dict(profile.definition, retailer_id=retailer_id)
    return Profile(id=99, retailer_id=retailer_id, version=1,
                   status=profile.status, definition=d)


def test_detection_conflict_two_globs_headers_tiebreak():
    etos = load_profile("etos.json")
    clone = _other_retailer(load_profile("etos.json"), "etos2")
    clone.definition["detection"] = dict(clone.definition["detection"],
                                         required_headers=["Bestaat", "Niet"])
    content = csv_bytes("Year/Week;GTIN;Description;Supplier brand;Sales units;Sales value",
                        "2026-W32;4049469072773;X;Tweezerman;1;10.00")
    assert parser_mod.detect("etos_sales_wk32.csv", content, [etos, clone]) is etos


def test_detection_ambiguous_across_retailers_returns_none():
    a = load_profile("etos.json")
    b = _other_retailer(load_profile("etos.json"), "etos2")
    content = csv_bytes("Year/Week;GTIN;Description;Supplier brand;Sales units;Sales value",
                        "2026-W32;4049469072773;X;Tweezerman;1;10.00")
    assert parser_mod.detect("etos_sales_wk32.csv", content, [a, b]) is None


def test_detection_own_older_version_never_competes():
    """Re-publishing a profile must not make detection ambiguous: only the
    newest live version per retailer takes part."""
    v2 = load_profile("etos.json", status="live")
    v3 = Profile(id=2, retailer_id="etos", version=3, status="live",
                 definition=v2.definition)
    picked = parser_mod.detect("etos_sales_wk32.csv", b"", [v2, v3])
    assert picked is v3


# ------------------------------------------------------------ parsing + atomic import

ETOS_HEADER = "Year/Week;GTIN;Description;Supplier brand;Sales units;Sales value;Region;Supplier code"


def test_parse_etos_normalize_and_constants():
    etos = load_profile("etos.json")
    content = csv_bytes(ETOS_HEADER, "2026-W32;4049469072773;Slant;Tweezerman;864;15120.00;Noord;S1")
    out = parser_mod.parse_file("etos_sales_wk32.csv", content, etos)
    f = out["facts"][0]
    assert f["merk"] == "TWEEZERMAN"       # normalize upper
    assert f["land"] == "NL"               # constant
    assert f["periode"] == "2026-W32" and out["periode_type"] == "week"
    assert f["volume"] == 864 and f["omzet"] == 15120.0


def test_parse_rejects_bad_ean():
    etos = load_profile("etos.json")
    content = csv_bytes(ETOS_HEADER, "2026-W32;123ABC;Slant;Tweezerman;1;10.00;N;S1")
    with pytest.raises(parser_mod.ParseError) as e:
        parser_mod.parse_file("x.csv", content, etos)
    assert e.value.row_errors and e.value.row_errors[0]["veld"] == "artikel_ean"


def test_import_atomic_one_bad_row_zero_facts(conn):
    etos = insert_profile(conn, load_profile("etos.json", status="live"))
    content = csv_bytes(
        ETOS_HEADER,
        "2026-W32;4049469072773;Slant;Tweezerman;864;15120.00;N;S1",
        "2026-W32;4049469083120;Clipper;Tweezerman;NIET-EEN-GETAL;6656.00;N;S1")
    result = importer.run_import(conn, "etos_sales_wk32.csv", content)
    assert result["status"] == "error"
    assert conn.execute("SELECT COUNT(*) c FROM sellout_facts").fetchone()["c"] == 0
    row = conn.execute("SELECT error_detail FROM imports").fetchone()
    assert "rijen" in json.loads(row["error_detail"])
    assert etos.retailer_id == result["retailer_id"]


def test_import_reimport_same_file_replaces(conn):
    insert_profile(conn, load_profile("etos.json", status="live"))
    content = csv_bytes(ETOS_HEADER, "2026-W32;4049469072773;Slant;Tweezerman;864;15120.00;N;S1")
    importer.run_import(conn, "etos_sales_wk32.csv", content)
    importer.run_import(conn, "etos_sales_wk32.csv", content)
    assert conn.execute("SELECT COUNT(*) c FROM sellout_facts").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM imports").fetchone()["c"] == 1


def test_import_unknown_file_profiel_nodig(conn):
    result = importer.run_import(conn, "onbekend_rapport.xlsx", b"whatever")
    assert result["status"] == "profiel_nodig"
    row = conn.execute("SELECT * FROM imports").fetchone()
    assert row["retailer_id"] is None and row["status"] == "profiel_nodig"


# ------------------------------------------------------------ uplift stability (acceptance 5)

def _week_row(week, units, value):
    return f"2026-W{week:02d};4049469072773;Slant;Tweezerman;{units};{value};N;S1"


def test_uplift_stable_after_reimport_of_confirmed_period(conn):
    insert_profile(conn, load_profile("etos.json", status="live"))
    weeks = [_week_row(w, 100, "1000.00") for w in range(1, 6)]
    promo = _week_row(6, 300, "2400.00")   # unit price 8.00 vs 10.00 -> suggestion
    importer.run_import(conn, "etos_sales_wk01.csv", csv_bytes(ETOS_HEADER, *weeks, promo))
    conn.execute(
        "INSERT INTO promo_confirmations (retailer_id, merk, land, banner, periode) "
        "VALUES ('etos','TWEEZERMAN','NL',NULL,'2026-W06')")
    before = analytics.promotions(conn, "etos")["uplift"]
    assert len(before) == 1 and before[0]["uplift_pct"] == pytest.approx(140.0)

    # Re-import the confirmed period (same file => replace) — uplift unchanged.
    importer.run_import(conn, "etos_sales_wk01.csv", csv_bytes(ETOS_HEADER, *weeks, promo))
    after = analytics.promotions(conn, "etos")["uplift"]
    assert after == before


# ------------------------------------------------------------ fictional 5th retailer (acceptance 1)

FANTASIA = {
    "retailer_id": "fantasia", "version": 1, "status": "live",
    "detection": {"filename_glob": "fantasia_*.csv", "sheet": None, "header_row": 1,
                  "required_headers": ["P", "B", "V", "O"], "filetype": "csv",
                  "csv_delimiter": ";", "decimal": "."},
    "period": {"type": "maand", "source_column": "P", "format": "yyyy-mm"},
    "mapping": [{"source": "B", "target": "merk", "normalize": "upper"},
                {"source": "V", "target": "volume"}, {"source": "O", "target": "omzet"}],
    "constants": {"land": "DE"}, "thresholds": {"promo_price_drop": 0.05},
}


def test_fifth_retailer_pure_profile(conn):
    conn.execute("INSERT INTO retailers (id, naam, aangesloten) VALUES ('fantasia','Fantasia',1)")
    insert_profile(conn, Profile(id=None, retailer_id="fantasia", version=1,
                                 status="live", definition=FANTASIA))
    rows = [f"2026-{m:02d};Marke;{100 + m};{1000 + m * 10}.50" for m in range(1, 8)]
    result = importer.run_import(conn, "fantasia_2026.csv", csv_bytes("P;B;V;O", *rows))
    assert result["status"] == "ingelezen" and result["rows"] == 7

    dash = analytics.dashboard(conn, "fantasia")
    assert dash["available"] and not dash["empty"]
    assert dash["periode_type"] == "maand" and dash["laatste_periode"] == "2026-07"
    assert "OP MAANDNIVEAU" in dash["labels"] and "SCHATTING" in dash["labels"]

    art = analytics.articles(conn, "fantasia")
    assert not art["available"] and art["reason"] == "GEGEVENS NIET BESCHIKBAAR"
    assert "OP MERKNIVEAU" in art["labels"]

    promo = analytics.promotions(conn, "fantasia")
    assert promo["available"] and promo["resolution"]["level_used"]["scope"] == "merk+land"
