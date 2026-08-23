"""Actiedetectie: referentie, artikelniveau, zekerheid en basisniveau.

De oude detectie vergeleek elke week met de mediaan van álle weken van dat
jaar — inclusief de actieweken zelf — en keek alleen naar de gewogen
prijsindex van het hele merk. Twee gevolgen: in een actierijk jaar verdwenen
juist de acties, en een actie op één artikel was onzichtbaar.
"""

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import promoties  # noqa: E402
from test_parser_flow import upload  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLE_DB", str(tmp_path / "console.db"))
    monkeypatch.setenv("CONSOLE_AUTH", "gateway")
    monkeypatch.setenv("CONSOLE_BIND", "127.0.0.1")
    for naam in ("db", "seed", "main"):
        sys.modules.pop(naam, None)
    main = importlib.import_module("main")
    return TestClient(main.app)


def laad(client, artikelen, naam="DWH__Sales_promo.xlsx"):
    import seed
    upload(client, naam, seed.make_dwh_xlsx(artikelen))


def art(sku, weken, merk="TWEEZERMAN"):
    return {"sku": sku, "gtin": sku, "desc": f"ART {sku}", "brand": merk,
            "weeks": weken}


def normaal(prijs, volume, weken, uitzondering=None):
    """{week: (volume, omzet)} tegen een vaste prijs, met eventueel een
    afwijkende prijs in bepaalde weken."""
    uit = {}
    for w in weken:
        p, v = (uitzondering or {}).get(w, (prijs, volume))
        uit[f"2026{w:02d}"] = (v, round(p * v, 2))
    return uit


# ------------------------------------------------------------- de referentie

def test_referentie_negeert_bevestigde_acties():
    """Anders verklaart een actierijk jaar zijn eigen acties weg: de mediaan
    zakt mee en de echte acties vallen binnen de 'normale' spreiding."""
    reeks = {f"2026-W{w:02d}": (8.0 if w % 2 else 10.0) for w in range(1, 13)}
    acties = {p for p, v in reeks.items() if v == 8.0}

    zonder = promoties.referentie(reeks, set())
    met = promoties.referentie(reeks, acties)
    assert zonder[0] == pytest.approx(9.0)      # mediaan van alles: vervuild
    assert met[0] == pytest.approx(10.0)        # alleen de normale weken
    assert met[2] == 6


def test_referentie_zwijgt_bij_te_weinig_periodes():
    """Drie waarnemingen zijn geen referentie maar een toevalstreffer."""
    assert promoties.referentie({"2026-W01": 10.0, "2026-W02": 10.0}, set()) is None


def test_spreiding_is_robuust_tegen_uitschieters():
    """De gewone standaardafwijking wordt juist opgeblazen door de acties die
    we willen vinden — dan verklaart het merk zijn eigen uitschieters."""
    stabiel = [10.0] * 10 + [4.0]
    mid = 10.0
    assert promoties._spreiding(stabiel, mid) == pytest.approx(0.0)


# --------------------------------------------------------------- artikelniveau

def test_actie_op_een_artikel_wordt_nu_gezien(client):
    """Vier artikelen, één week waarin er één fors is afgeprijsd. De gewogen
    index beweegt nauwelijks; vroeger bleef dit onzichtbaar."""
    weken = range(1, 15)
    laad(client, [
        art("31210001", normaal(20.0, 100, weken,
                                {5: (10.0, 300)})),          # -50% in week 5
        art("31210002", normaal(20.0, 100, weken)),
        art("31210003", normaal(20.0, 100, weken)),
        art("31210004", normaal(20.0, 100, weken)),
    ])
    s = {x["periode"]: x for x in client.get("/api/kruidvat/promoties").json()["suggesties"]}
    assert "2026-W05" in s
    gevonden = s["2026-W05"]
    assert gevonden["bereik"] == "artikel"
    assert gevonden["artikelen"][0]["artikel_ean"] == "31210001"
    assert gevonden["artikelen"][0]["daling_pct"] == pytest.approx(50.0, abs=0.1)


def test_afgeprijsd_staartartikel_is_geen_actie(client):
    """Eén afgeprijsd artikel dat nauwelijks verkoopt is geen actie om op te
    sturen — anders staat de lijst vol regels waar niets achter zit."""
    weken = range(1, 15)
    laad(client, [
        art("31210001", normaal(20.0, 1000, weken)),
        art("31210002", normaal(20.0, 1000, weken)),
        art("31210003", normaal(20.0, 1000, weken)),
        art("31210009", normaal(20.0, 2, weken, {5: (5.0, 2)})),   # 0,07% volume
    ])
    s = {x["periode"] for x in client.get("/api/kruidvat/promoties").json()["suggesties"]}
    assert "2026-W05" not in s


def test_hele_assortiment_afgeprijsd_heet_assortiment(client):
    weken = range(1, 15)
    laad(client, [
        art("31210001", normaal(20.0, 100, weken, {5: (15.0, 140)})),
        art("31210002", normaal(20.0, 100, weken, {5: (15.0, 140)})),
        art("31210003", normaal(20.0, 100, weken, {5: (15.0, 140)})),
    ])
    s = {x["periode"]: x for x in client.get("/api/kruidvat/promoties").json()["suggesties"]}
    assert s["2026-W05"]["bereik"] == "assortiment"
    assert "afgeprijsd" in s["2026-W05"]["suggestie"]


def test_percentage_spreekt_de_drempel_niet_tegen(client):
    """Op hele procenten toonde een daling van 4,6% "-5%" terwijl de drempel
    5% is; het getal sprak de regel tegen."""
    weken = range(1, 15)
    laad(client, [art("31210001", normaal(20.0, 100, weken, {5: (18.6, 100)}))])
    s = {x["periode"]: x for x in client.get("/api/kruidvat/promoties").json()["suggesties"]}
    if "2026-W05" in s and s["2026-W05"]["suggestie"]:
        getal = s["2026-W05"]["suggestie"].split("-")[1].rstrip("%").replace(",", ".")
        assert float(getal) == pytest.approx(s["2026-W05"]["drop_pct"], abs=0.05)


# -------------------------------------------------------------- de zekerheid

def test_zekerheid_telt_vier_signalen_op():
    score, delen = promoties.zekerheid(z=6.0, volume_respons=0.8,
                                       bereik="assortiment", kwaliteit="volledig")
    assert score == 5
    assert [d["punten"] for d in delen] == [2, 1, 1, 1]


def test_zwak_prijssignaal_binnen_de_ruis_scoort_laag():
    score, delen = promoties.zekerheid(z=1.2, volume_respons=0.0,
                                       bereik=None, kwaliteit="volledig")
    assert score == 1
    assert "ruis" in delen[0]["tekst"]


def test_onvolledige_data_plafonneert_de_zekerheid():
    """Hoe hard het prijssignaal ook lijkt: op een halve week kan de app niet
    zeker zijn."""
    score, _ = promoties.zekerheid(z=9.0, volume_respons=2.0,
                                   bereik="assortiment", kwaliteit="loopt_nog")
    assert score == 2


# ------------------------------------------------------------ basisniveau

def test_gemiddelde_weekomzet_laat_actieweken_weg(client):
    weken = range(1, 15)
    laad(client, [
        art("31210001", normaal(20.0, 100, weken, {5: (10.0, 400)})),
        art("31210002", normaal(20.0, 100, weken, {5: (10.0, 400)})),
    ])
    d = client.get("/api/kruidvat/promoties").json()
    b = next(x for x in d["basis"] if x["merk"] == "TWEEZERMAN")
    # Week 5 is voorgesteld als actie en telt dus niet mee in het gemiddelde.
    assert [u["periode"] for u in b["uitgesloten"]] == ["2026-W05"]
    assert b["uitgesloten"][0]["reden"] == "voorstel"
    assert b["periodes"] == 13
    # 13 normale weken van 2 x 100 x € 20.
    assert b["gemiddelde"] == pytest.approx(4000.0)


def test_niet_geleverde_periode_drukt_het_gemiddelde_niet(client):
    """Een week die deze scope niet leverde is geen lage omzet maar geen
    waarneming."""
    weken = [w for w in range(1, 15) if w != 7]
    laad(client, [art("31210001", normaal(20.0, 100, weken))], "DWH__Sales_a.xlsx")
    # Een tweede merk levert week 7 wél: de week bestaat op de retailer-as.
    laad(client, [art("31210007", normaal(20.0, 100, range(1, 15)), merk="ALESSANDRO")],
         "DWH__Sales_b.xlsx")

    d = client.get("/api/kruidvat/promoties").json()
    b = next(x for x in d["basis"] if x["merk"] == "TWEEZERMAN")
    assert b["gemiddelde"] == pytest.approx(2000.0)      # niet verlaagd door week 7
    assert any(o["reden"] == "niet_geleverd" and o["periode"] == "2026-W07"
               for o in d["onvolledige_periodes"] + b["uitgesloten"])


def test_basis_per_merk_vat_de_scopes_samen(client):
    laad(client, [art("31210001", normaal(20.0, 100, range(1, 15)))])
    d = client.get("/api/kruidvat/promoties").json()
    m = next(x for x in d["basis_per_merk"] if x["merk"] == "TWEEZERMAN")
    assert m["gemiddelde"] == pytest.approx(2000.0)
    assert m["scopes"] == 1


# ------------------------------------------------------- markers op dashboard

def test_bevestigde_actie_wordt_een_marker_op_het_dashboard(client):
    weken = range(1, 15)
    laad(client, [art("31210001", normaal(20.0, 100, weken, {5: (10.0, 400)}))])
    client.put("/api/kruidvat/promoties", json={"bevestigd": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "periode": "2026-W05"}]})

    markers = client.get("/api/kruidvat/dashboard").json()["promoties"]
    assert len(markers) == 1
    m = markers[0]
    assert (m["jaar"], m["periode_nummer"], m["merk"]) == (2026, 5, "TWEEZERMAN")
    # De uplift volgt uit de twee bedragen die de marker meedraagt.
    assert m["uplift_pct"] == pytest.approx(
        (m["omzet"] - m["basislijn"]) / m["basislijn"] * 100, abs=0.05)


def test_dashboard_en_promotiepagina_tonen_dezelfde_uplift(client):
    """Twee berekeningen van hetzelfde getal lopen vroeg of laat uiteen. De
    marker haalt zijn uplift daarom uit dezelfde bron als de pagina."""
    weken = range(1, 15)
    laad(client, [
        art("31210001", normaal(20.0, 100, weken, {5: (10.0, 400), 9: (12.0, 300)})),
    ])
    d = client.get("/api/kruidvat/promoties").json()
    # Week 5 bevestigen, week 9 blijft een voorstel.
    client.put("/api/kruidvat/promoties", json={"bevestigd": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "periode": "2026-W05"}]})

    pagina = next(u for u in client.get("/api/kruidvat/promoties").json()["uplift"]
                  if u["periode"] == "2026-W05")
    marker = next(m for m in client.get("/api/kruidvat/dashboard").json()["promoties"]
                  if m["periode"] == "2026-W05")
    assert marker["uplift_pct"] == pagina["uplift_pct"]
    assert marker["basislijn"] == pytest.approx(pagina["basislijn"])
    assert marker["omzet"] == pytest.approx(pagina["omzet"])


def test_basislijn_laat_voorgestelde_acties_ook_weg(client):
    """Eén definitie van 'een normale week'. De basislijn telde voorgestelde
    acties nog wel mee, terwijl het gemiddelde ze uitsloot — dan staan er twee
    versies van hetzelfde begrip op één pagina."""
    weken = range(1, 15)
    laad(client, [
        art("31210001", normaal(20.0, 100, weken, {5: (10.0, 400), 9: (10.0, 400)})),
    ])
    client.put("/api/kruidvat/promoties", json={"bevestigd": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": "KV", "periode": "2026-W05"}]})

    d = client.get("/api/kruidvat/promoties").json()
    u = next(x for x in d["uplift"] if x["periode"] == "2026-W05")
    b = next(x for x in d["basis"] if x["merk"] == "TWEEZERMAN")
    # Week 9 is een voorstel en zit dus in geen van beide.
    assert u["basisperiodes"] == b["periodes"] == 12
    assert u["basislijn"] == pytest.approx(b["mediaan"])
    # De normale week is 100 x € 20; de actieweek deed € 4.000.
    assert u["basislijn"] == pytest.approx(2000.0)
    assert u["uplift_pct"] == pytest.approx(100.0)


def test_zonder_bevestiging_geen_markers(client):
    laad(client, [art("31210001", normaal(20.0, 100, range(1, 15), {5: (10.0, 400)}))])
    assert client.get("/api/kruidvat/dashboard").json()["promoties"] == []


# ------------------------------------------- feeds zonder volume (ICI)

def test_zonder_volume_blijft_elke_periode_aanvinkbaar(client):
    """ICI levert geen volume, dus er bestaat geen stukprijs en geen
    automatische suggestie. Elke periode staat in de lijst om handmatig aan te
    vinken — maar dat maakt ze nog geen voorstel."""
    import seed
    upload(client, "Maandelijkse resultaten ICI Paris XL (basis).xlsx",
           seed.make_ici_xlsx({"TWEEZERMAN": {"6051": {
               f"2026{m:02d}": 100.0 * m for m in range(1, 8)}}}))

    d = client.get("/api/ici-paris-xl/promoties").json()
    assert d["methode"] == "handmatig"
    assert len(d["suggesties"]) == 7
    assert all(s["suggestie"] is None for s in d["suggesties"])
    # Dezelfde velden als de andere tak, zodat het scherm één vorm ziet.
    assert all("bereik" in s and "zekerheid" in s for s in d["suggesties"])

    # En het gemiddelde gebruikt gewoon alle zeven maanden: als elke periode
    # als "voorstel" zou tellen, bleef er niets over om over te middelen.
    b = next(x for x in d["basis"] if x["merk"] == "TWEEZERMAN")
    assert b["periodes"] == 7
    assert b["gemiddelde"] == pytest.approx(sum(100.0 * m for m in range(1, 8)) / 7)


def test_handmatig_bevestigde_periode_valt_wel_buiten_het_gemiddelde(client):
    import seed
    upload(client, "Maandelijkse resultaten ICI Paris XL (bev).xlsx",
           seed.make_ici_xlsx({"TWEEZERMAN": {"6051": {
               f"2026{m:02d}": 100.0 for m in range(1, 8)} | {"202604": 900.0}}}))
    client.put("/api/ici-paris-xl/promoties", json={"bevestigd": [
        {"merk": "TWEEZERMAN", "land": "NL", "banner": None, "periode": "2026-04"}]})

    b = next(x for x in client.get("/api/ici-paris-xl/promoties").json()["basis"]
             if x["merk"] == "TWEEZERMAN")
    assert b["periodes"] == 6
    assert b["gemiddelde"] == pytest.approx(100.0)
    assert b["uitgesloten"] == [{"periode": "2026-04", "reden": "actie"}]


# --------------------------------------- bevindingen wiskundige review

def test_vaste_prijs_die_zakt_is_het_hardste_bewijs():
    """F2: bij een prijs die het hele jaar exact vaststond is de MAD nul en
    bestaat er geen z-score. Dat is geen 'te weinig data' maar juist het
    sterkste prijssignaal — en zo hoort het ook te scoren."""
    score, delen = promoties.zekerheid(
        z=None, volume_respons=0.5, bereik="assortiment", kwaliteit="volledig",
        stabiel_en_gedaald=True, n_referentie=20)
    assert delen[0]["punten"] == 2
    assert "nooit beweegt" in delen[0]["tekst"]
    assert score == 5


def test_wankele_referentie_drukt_het_prijssignaal():
    """F6: een MAD op vier waarnemingen is wankel; onder de zes
    referentieperiodes is het prijssignaal maximaal een punt waard."""
    vol, _ = promoties.zekerheid(z=8.0, volume_respons=None, bereik=None,
                                 kwaliteit="volledig", n_referentie=20)
    wankel, delen = promoties.zekerheid(z=8.0, volume_respons=None, bereik=None,
                                        kwaliteit="volledig", n_referentie=4)
    assert vol - wankel == 1
    assert "4 referentieperiodes" in delen[0]["tekst"]


def test_staartartikelen_krijgen_geen_bereikpunt():
    """F4: 'artikel'-bereik met alleen staartartikelen kreeg een punt met de
    tekst "noemenswaardig volume" — terwijl dat er juist niet was."""
    _, delen = promoties.zekerheid(z=3.5, volume_respons=None, bereik="staart",
                                   kwaliteit="volledig", n_referentie=20)
    bereik_deel = next(d for d in delen if d["naam"] == "bereik")
    assert bereik_deel["punten"] == 0
    assert "zonder noemenswaardig volume" in bereik_deel["tekst"]


def test_periodekwaliteit_begin_en_einde_zijn_geen_gat():
    """F3: een merk dat in week 20 instapt kreeg week 1-19 als 'niet
    geleverd', en een scope die alleen in 2026 bestaat heel 2025. Vóór de
    eerste en ná de laatste levering is geen gat (zelfde regel als
    engine/datagaten.py); alleen binnenliggende gaten tellen."""
    def rij(periode, merk):
        return {"periode": periode, "merk": merk, "land": "NL", "banner": None}
    key = lambda r: (r["merk"], r["land"], r["banner"])  # noqa: E731
    rows = ([rij(f"2026-W{w:02d}", "VAST") for w in range(1, 11)]
            # LAAT begint in week 5 en slaat week 7 over.
            + [rij(f"2026-W{w:02d}", "LAAT") for w in (5, 6, 8, 9, 10)]
            # ALLEEN25 bestaat alleen in 2025.
            + [rij(f"2025-W{w:02d}", "ALLEEN25") for w in (1, 2, 3)])
    kw = promoties.periodekwaliteit(rows, key, vandaag=__import__("datetime").date(2027, 6, 1))

    laat = ("LAAT", "NL", None)
    assert kw[(laat, "2026-W07")] == "niet_geleverd"          # binnenliggend gat
    assert (laat, "2026-W01") not in kw                       # vóór de start: geen gat
    a25 = ("ALLEEN25", "NL", None)
    assert not any(s == a25 and p.startswith("2026") for (s, p) in kw), \
        "een scope zonder leveringen in een jaar hoort dat jaar niet te bestaan"


def test_referentie_wordt_niet_vervuild_door_eigen_voorstellen(client):
    """F5: niet-bevestigde actieweken zaten in de detectiereferentie. Bij een
    actierijk merk zakt de mediaan mee en blaast de MAD op, wat de z-scores
    drukt. De twee-pass rekent de definitieve cijfers zonder de gevlagde
    weken: op dit patroon (om de week -20%) hoort de normale prijs € 20 te
    zijn en elke actieweek een strakke z te krijgen."""
    weken = range(1, 21)
    laad(client, [art("31210001", normaal(
        20.0, 100, weken, {w: (16.0, 200) for w in range(2, 21, 2)}))])
    d = client.get("/api/kruidvat/promoties").json()
    actie = [s for s in d["suggesties"] if s["suggestie"]]
    assert len(actie) == 10
    # De referentie is de mediaan van de 10 normale weken (prijsrelatief 1,0);
    # elke actieweek ligt daar exact 20% onder.
    assert all(s["drop_pct"] == pytest.approx(20.0, abs=0.1) for s in actie)
    # En de referentie telt alleen de normale weken.
    assert actie[0]["referentieperiodes"] == 10


def test_index_zakt_niet_als_duur_artikel_ontbreekt_eind_tot_eind(client):
    """F1, end-to-end: het dure artikel verkoopt één week niets; met een
    niveau-index leek dat -67% actie, met relatieven is er geen suggestie."""
    weken = range(1, 11)
    laad(client, [
        art("31210001", normaal(5.0, 100, weken)),
        art("31210002", {f"2026{w:02d}": (100, 2500.0) for w in weken if w != 5}),
    ])
    d = client.get("/api/kruidvat/promoties").json()
    assert [s for s in d["suggesties"] if s["periode"] == "2026-W05"] == []
