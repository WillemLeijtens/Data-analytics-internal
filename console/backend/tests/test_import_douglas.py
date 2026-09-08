"""Douglas: twee maandrapporten die dezelfde omzet per artikel én per winkel
verdelen (zie engine/douglas_icube.py en migratie 023).

Wat hier vastligt:

  * beide rapporttypen worden herkend, op bestandsnaam én op inhoud;
  * beide laden → de dashboardomzet is het totaal van ÉÉN rapport, geen
    dubbeltelling; de artikelanalyse leest de artikelen, het dashboard de
    winkels;
  * de LY-kolom levert dezelfde maand vorig jaar als eigen regels;
  * een correctie vervangt de hele scope-maand, dus een verdwenen winkel
    verdwijnt écht;
  * de webshop telt mee in omzet maar niet in "per winkel";
  * zonder winkelrapport valt het dashboard terug op handmatige aantallen.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echte_bestanden import MAP, vereist  # noqa: E402
from engine import douglas_icube  # noqa: E402
from engine.periods import parse_period  # noqa: E402
from test_parser_flow import upload  # noqa: E402

# Via echte_bestanden, niet via Path.exists(): dat pad ligt onder /root en
# gooit in GitHub Actions een PermissionError die de hele collectie afbreekt.
ECHT_SKU = MAP / "7ae00ead-Doulgas_SO_Advanced_SKU_Sell_Out_Net_2026YTD08.xlsx"
ECHT_WINKEL = MAP / "d3529537-Douglas_SO_Advanced_Store_Sell_Out_Net_2026YTD08.xlsx"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for naam in ("db", "seed", "main"):
        sys.modules.pop(naam, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


SKU_NAAM = "Douglas_SO_Advanced_SKU_Sell_Out_Net_2026YTD08.xlsx"
WINKEL_NAAM = "Douglas_SO_Advanced_Store_Sell_Out_Net_2026YTD08.xlsx"


def _sku(ean, omzet, omzet_ly=None, cum=None, **kw):
    return {"ean": ean, "omzet": omzet, "omzet_ly": omzet_ly,
            "cum": cum if cum is not None else omzet, **kw}


def _winkel(nummer, omzet, omzet_ly=None, cum=None, **kw):
    return {"winkel": nummer, "omzet": omzet, "omzet_ly": omzet_ly,
            "cum": cum if cum is not None else omzet, **kw}


def _standaard(client):
    """Drie artikelen en drie winkels (waarvan één webshop) met hetzelfde
    totaal: 600 deze maand, 500 vorig jaar."""
    import seed
    upload(client, SKU_NAAM, seed.make_douglas_xlsx([
        _sku("8015150000001", 300.0, 250.0, lijn="GOCCE MAGICHE", naam="MAGIC DROPS"),
        _sku("8015150000002", 200.0, 150.0),
        _sku("8015150000003", 100.0, 100.0, kanaal="E-Commerce")]))
    upload(client, WINKEL_NAAM, seed.make_douglas_xlsx([
        _winkel(52, 350.0, 300.0, stad="Groningen"),
        _winkel(24, 150.0, 100.0, stad="Amsterdam"),
        _winkel(105, 100.0, 100.0, stad="Nijmegen", kanaal="E-Commerce")], soort="winkel"))


# --------------------------------------------------------------- herkenning

def test_beide_rapporten_worden_herkend_op_bestandsnaam(client):
    import seed
    r = upload(client, SKU_NAAM, seed.make_douglas_xlsx([_sku("8015150000001", 10.0)]))
    assert (r["status"], r["retailer_id"]) == ("ingelezen", "douglas")
    r = upload(client, WINKEL_NAAM, seed.make_douglas_xlsx([_winkel(52, 10.0)], soort="winkel"))
    assert (r["status"], r["retailer_id"]) == ("ingelezen", "douglas")


def test_herkenning_op_inhoud_bij_een_hernoemd_bestand(client):
    """Zoals bij Etos en ICI: een hernoemd bestand landt op structuur."""
    import seed
    r = upload(client, "export (3).xlsx", seed.make_douglas_xlsx([_sku("8015150000001", 10.0)]))
    assert (r["status"], r["retailer_id"]) == ("ingelezen", "douglas")


def test_de_oefenretailer_blijft_onherkend(client):
    """Het demo-Abverkauf-bestand lijkt nergens op; de Douglas-inhoudstoets
    mag hem niet opeisen."""
    from test_parser_flow import DG_HEADERS, dg_rows, make_xlsx
    r = upload(client, "Demo_Abverkauf_KW32.xlsx", make_xlsx(DG_HEADERS, dg_rows(2026, [32])))
    assert r["status"] == "profiel_nodig"


# --------------------------------------------------------------- parsen

def test_maandformaat_mmm_yy():
    assert parse_period("Aug-26", "mmm-yy") == "2026-08"
    assert parse_period("jan-25", "mmm-yy") == "2025-01"
    import datetime as dt
    assert parse_period(dt.date(2026, 8, 1), "mmm-yy") == "2026-08"
    with pytest.raises(ValueError):
        parse_period("Agu-26", "mmm-yy")


def test_parser_leest_land_kanaal_naam_en_ly_regels():
    import seed
    r = douglas_icube.parse_workbook(seed.make_douglas_xlsx([
        _sku("8015150000001", 100.0, 80.0, land="Belgium", kanaal="E-Commerce",
             lijn="GOCCE MAGICHE", naam="MAGIC DROPS", inhoud=30, eenheid="ML", kleur=None)]))
    assert r["niveau"] == "artikel" and r["periodes"] == ["2026-08"]
    nu, ly = r["facts"]
    assert (nu["land"], nu["banner"], nu["periode"], nu["omzet"]) == ("BE", "ONLINE", "2026-08", 100.0)
    assert nu["artikel_naam"] == "GOCCE MAGICHE MAGIC DROPS 30 ML"
    assert nu["categorie"] == "GOCCE MAGICHE"
    assert nu["artikel_ean"] == "8015150000001" and nu["volume"] == 0
    assert (ly["periode"], ly["omzet"]) == ("2025-08", 80.0)
    assert any("2025-08" in w for w in r["warnings"])


def test_lege_omzet_met_cumulatief_wordt_een_nulregel():
    """Het artikel deed dit jaar mee (cumulatief > 0) maar verkocht deze
    maand niets: gemeten, niets verkocht — geen ontbrekende regel."""
    import seed
    r = douglas_icube.parse_workbook(seed.make_douglas_xlsx([
        _sku("8015150000001", None, None, cum=450.0),
        _sku("8015150000002", None, 60.0, cum=None)]))      # alleen vorig jaar
    per = {(f["artikel_ean"], f["periode"]): f["omzet"] for f in r["facts"]}
    assert per[("8015150000001", "2026-08")] == 0.0
    assert ("8015150000002", "2026-08") not in per
    assert per[("8015150000002", "2025-08")] == 60.0


def test_winkelrapport_leest_nummer_en_adres():
    import seed
    r = douglas_icube.parse_workbook(seed.make_douglas_xlsx(
        [_winkel(52.0, 10.0, stad="Groningen", straat="Guldenstraat   ", nr="42-1")],
        soort="winkel"))
    f = r["facts"][0]
    assert r["niveau"] == "winkel"
    assert (f["winkel_id"], f["winkel_naam"]) == ("52", "Groningen, Guldenstraat 42-1")
    assert f["artikel_ean"] is None


@pytest.mark.parametrize("fout", [
    {"land": "Germany"}, {"kanaal": "Wholesale"}, {"ean": ""}])
def test_parser_faalt_gesloten(fout):
    import seed
    rij = _sku("8015150000001", 10.0)
    rij.update(fout)
    with pytest.raises(ValueError):
        douglas_icube.parse_workbook(seed.make_douglas_xlsx([rij]))


def test_dubbele_sleutel_in_het_bestand_breekt_af():
    import seed
    with pytest.raises(ValueError, match="dubbel"):
        douglas_icube.parse_workbook(seed.make_douglas_xlsx([
            _sku("8015150000001", 10.0), _sku("8015150000001", 20.0)]))


# ---------------------------------------------------------- geen dubbeltelling

def test_beide_rapporten_geladen_telt_de_omzet_een_keer(client):
    _standaard(client)
    d = client.get("/api/douglas/dashboard").json()
    assert d["kpi"]["omzet"]["waarde"] == pytest.approx(600.0)
    assert d["ytd"]["omzet"]["nu"] == pytest.approx(600.0)
    assert d["ytd"]["omzet"]["vorig"] == pytest.approx(500.0)
    assert d["niveaus"] == {"artikel": "2026-08", "winkel": "2026-08"}
    assert "SCHATTING" not in d["labels"]


def test_dashboard_op_winkels_artikelanalyse_op_artikelen(client):
    _standaard(client)
    d = client.get("/api/douglas/dashboard").json()
    a = client.get("/api/douglas/artikelen").json()
    assert d["kpi"]["omzet_per_winkel"]["winkels"] == 2          # webshop niet
    assert len(a["artikelen"]) == 3
    assert a["distributie_beschikbaar"] is False
    assert a["capabilities"]["volume"] is False


def test_webshop_telt_in_omzet_maar_niet_per_winkel(client):
    _standaard(client)
    d = client.get("/api/douglas/dashboard").json()
    k = d["kpi"]["omzet_per_winkel"]
    # 500 fysieke omzet over 2 fysieke winkels; de 100 van de webshop telt
    # niet mee — niet in de teller, niet in de noemer.
    assert k["waarde"] == pytest.approx(250.0)
    assert k["exclusief"] == ["ONLINE"]
    per_banner = {b["label"]: b for b in k["breakdowns"]["banner"]}
    assert per_banner["ONLINE"]["waarde"] is None
    assert per_banner["FYSIEK"]["winkels"] == 2
    omzet_banner = {b["label"]: b["waarde"] for b in d["kpi"]["omzet"]["breakdowns"]["banner"]}
    assert omzet_banner["ONLINE"] == pytest.approx(100.0)
    # En de winkelanalyse kent de webshop niet.
    ids = {w["winkel_id"] for lijst in ("gestopt", "signalen", "toegevoegd")
           for w in d["winkelanalyse"][lijst]}
    assert "105" not in ids


def test_decompositie_gaat_op_over_de_fysieke_winkels(client):
    _standaard(client)
    t = client.get("/api/douglas/dashboard").json()["tijdlijn"]
    assert t["periodes"] == ["2025-08", "2026-08"]
    # Kalendervenster: augustus 2026 mag augustus 2025 niet meenemen.
    assert t["totaal"]["winkels"] == [2, 2]
    dec = t["decompositie"]["totaal"]
    assert dec["winkels_nu"] == 2 and dec["winkels_toen"] == 2
    assert dec["omzet_pct"] == pytest.approx(25.0)      # 400 -> 500 fysiek


def test_afstemming_meldt_een_scheef_winkelrapport(client):
    import seed
    upload(client, SKU_NAAM, seed.make_douglas_xlsx([_sku("8015150000001", 300.0)]))
    r = upload(client, WINKEL_NAAM, seed.make_douglas_xlsx([_winkel(52, 200.0)], soort="winkel"))
    assert "sluiten niet op elkaar aan" in (r["detail"] or "")
    assert "EUR 300" in r["detail"] and "EUR 200" in r["detail"]


# ------------------------------------------------------- volgorde en herlevering

def test_alleen_het_artikelrapport_valt_terug_op_een_schatting(client):
    import seed
    r = upload(client, SKU_NAAM, seed.make_douglas_xlsx([_sku("8015150000001", 300.0)]))
    assert "winkelrapport is nog niet geladen" in r["detail"]
    d = client.get("/api/douglas/dashboard").json()
    assert d["kpi"]["omzet"]["waarde"] == pytest.approx(300.0)
    assert "SCHATTING" in d["labels"]
    assert d["niveaus"] is None
    # Het handmatige winkelaantal is dan wél in te vullen.
    assert client.get("/api/douglas/instellingen").json()["capabilities"]["winkel"] is False
    # Winkelrapport erbij: omslag naar geteld.
    upload(client, WINKEL_NAAM, seed.make_douglas_xlsx([_winkel(52, 300.0)], soort="winkel"))
    d = client.get("/api/douglas/dashboard").json()
    assert "SCHATTING" not in d["labels"]
    assert d["kpi"]["omzet_per_winkel"]["winkels"] == 1


def test_achterlopend_winkelrapport_wordt_gemeld(client):
    import seed
    _standaard(client)
    r = upload(client, SKU_NAAM.replace("08", "09"),
               seed.make_douglas_xlsx([_sku("8015150000001", 700.0)], maand="Sep-26"))
    assert "winkelrapport loopt achter" in r["detail"]
    d = client.get("/api/douglas/dashboard").json()
    assert d["laatste_periode"] == "2026-08"                  # dashboard op de winkelslice
    assert d["niveaus"] == {"artikel": "2026-09", "winkel": "2026-08"}
    assert "WINKELBESTAND T/M 2026-08" in d["labels"]
    assert client.get("/api/douglas/artikelen").json()["laatste_periode"] == "2026-09"


def test_herlevering_vervangt_de_hele_scope_maand(client):
    """Een correctie zonder winkel 24: die hoort te verdwijnen, niet stil te
    blijven staan naast de nieuwe regels."""
    import seed
    _standaard(client)
    upload(client, "Douglas_SO_Advanced_Store_Sell_Out_Net_2026YTD08_v2.xlsx",
           seed.make_douglas_xlsx([
               _winkel(52, 500.0, 300.0, stad="Groningen"),
               _winkel(105, 100.0, 100.0, stad="Nijmegen", kanaal="E-Commerce")], soort="winkel"))
    d = client.get("/api/douglas/dashboard").json()
    assert d["kpi"]["omzet"]["waarde"] == pytest.approx(600.0)
    assert d["kpi"]["omzet_per_winkel"]["winkels"] == 1
    # De artikelslice bleef staan.
    assert len(client.get("/api/douglas/artikelen").json()["artikelen"]) == 3


def test_een_echt_bestand_van_vorig_jaar_vervangt_de_ly_regels(client):
    import seed
    _standaard(client)
    upload(client, "Douglas_SO_Advanced_SKU_Sell_Out_Net_2025YTD08.xlsx",
           seed.make_douglas_xlsx([
               _sku("8015150000001", 260.0), _sku("8015150000002", 140.0),
               _sku("8015150000003", 100.0, kanaal="E-Commerce")], maand="Aug-25"))
    upload(client, "Douglas_SO_Advanced_Store_Sell_Out_Net_2025YTD08.xlsx",
           seed.make_douglas_xlsx([
               _winkel(52, 310.0, stad="Groningen"), _winkel(24, 90.0, stad="Amsterdam"),
               _winkel(105, 100.0, stad="Nijmegen", kanaal="E-Commerce")],
               soort="winkel", maand="Aug-25"))
    d = client.get("/api/douglas/dashboard").json()
    assert d["ytd"]["omzet"]["vorig"] == pytest.approx(500.0)     # niet 500 + 500


def test_zonder_volume_geen_assortiment_en_geen_prijsindex(client):
    _standaard(client)
    s = client.get("/api/douglas/assortiment").json()
    assert (s["available"], s["reason"]) == (False, "GEEN VOLUMEDATA")
    assert client.get("/api/douglas/promoties").json()["methode"] == "handmatig"


def test_geen_valse_nieuw_of_delisted_op_een_maand_historie(client):
    """Met alleen augustus 2025 geladen zegt "vorig jaar niets" alleen iets
    over augustus. Pas met een paar maanden historie valt er te oordelen."""
    import seed
    upload(client, SKU_NAAM, seed.make_douglas_xlsx([
        _sku("8015150000001", 100.0, 90.0),
        _sku("8015150000002", 50.0, None),              # zou "nieuw" lijken
        _sku("8015150000009", None, 40.0, cum=None)]))  # zou "delisted" lijken
    statussen = {a["ean"]: a["status"] for a in
                 client.get("/api/douglas/artikelen").json()["artikelen"]}
    assert statussen["8015150000002"] is None
    assert statussen["8015150000009"] is None


def test_distributiesignaal_zonder_winkelrapport_is_grijs(client):
    import seed
    upload(client, SKU_NAAM, seed.make_douglas_xlsx([_sku("8015150000001", 300.0)]))
    kaart = next(c for c in client.get("/api/overview").json()["retailers"] if c["id"] == "douglas")
    assert kaart["signalen"]["distributie"]["signaal"] == "grey"
    assert kaart["capabilities"]["winkel"] is False


# ---------------------------------------------------------------- echte bestanden

@vereist(ECHT_SKU, ECHT_WINKEL)
def test_echte_bestanden(client):
    r1 = upload(client, "Doulgas_SO_Advanced_SKU_Sell_Out_Net_2026YTD08.xlsx", ECHT_SKU.read_bytes())
    r2 = upload(client, "Douglas_SO_Advanced_Store_Sell_Out_Net_2026YTD08.xlsx", ECHT_WINKEL.read_bytes())
    assert r1["status"] == r2["status"] == "ingelezen"
    assert "eerdere maanden van 2026 ontbreken" in r1["detail"]
    d = client.get("/api/douglas/dashboard").json()
    assert d["kpi"]["omzet"]["waarde"] == pytest.approx(157146.91, abs=0.01)
    assert d["ytd"]["omzet"]["vorig"] == pytest.approx(172761.64, abs=0.01)
    assert d["kpi"]["omzet_per_winkel"]["winkels"] == 125          # 127 min de 2 webshops
    assert sorted(d["filters"]["land"]) == ["BE", "NL"]
    assert sorted(d["filters"]["banner"]) == ["FYSIEK", "ONLINE"]
    a = client.get("/api/douglas/artikelen").json()
    assert len({x["ean"] for x in a["artikelen"]}) == 576
    assert d["kpi"]["omzet"]["breakdowns"]["banner"][0]["label"] in ("FYSIEK", "ONLINE")
