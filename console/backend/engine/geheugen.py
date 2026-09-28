"""De analysecache: één plek, gedeeld door de endpoints én de engine.

Waarom hier en niet in main.py. De cache stond eerst alleen om de endpoints
heen. De conclusie en het overzicht roepen dezelfde analyses rechtstreeks
aan, dus rekenden ze alles opnieuw uit — ook schermen die al klaarstonden.
Gemeten op Etos-schaal (90k feitregels): de conclusie haalde alle feiten
acht keer op en berekende promoties, assortiment en winkelanalyse elk twee
keer (5,5 s); het overzicht haalde ze achttien keer op (1,2 s). Nu gaan die
aanroepen door dezelfde cache, met dezelfde sleutels als de endpoints: wat
het dashboard al berekende, hergebruikt de conclusie.

INVALIDATIE is bewust op de DATA gebaseerd, niet op een teller die dit
proces zelf bijhoudt: seed.py, cleanup_demo.py, cleanup_duplicates.py en
tools/ schrijven buiten dit proces om. Een teller zou die missen en
stilzwijgend verouderde cijfers blijven tonen.

  * Een telling per tabel: COUNT(*) én MAX(rowid). Alleen MAX mist een
    verwijdering, alleen COUNT mist een even groot verwijder-en-invoegen.
  * Kleine tabellen (instellingen) op INHOUD: een UPDATE verandert geen van
    beide tellingen, en een drempel van 2 naar 6 zou anders onzichtbaar
    blijven.
  * De tabellen komen uit de database, niet uit een lijst hier: een
    vergeten tabel mag geen stille fout kunnen zijn.
  * De datum: `is_afgesloten()` hangt af van de klok, niet van de data.
  * Het databasepad: deze module leeft langer dan één database (tests
    maken er per test een nieuwe). Twee databases met toevallig gelijke
    tellingen mogen elkaars uitkomst nooit krijgen.

NIET op de bestandstijd van de database: in WAL-modus raakt élke lezende
verbinding het -wal-bestand, waardoor de stempel bij elk verzoek verandert.

Twee dingen die de oude cache niet deed:

  * SINGLE-FLIGHT. Het scherm vraagt overzicht, dashboard en datagaten
    tegelijk op. Koud rekenden drie threads elk alles uit, en door de GIL
    wachtte alles op elkaar. Nu wacht een tweede vrager op de lopende
    berekening van dezelfde sleutel.
  * LRU in plaats van alles wissen zodra er 64 sleutels zijn. Elke
    filtercombinatie is een eigen sleutel; wissen gooide dan ook het warme
    ongefilterde dashboard van alle retailers weg.

En de OPWARMER: na elke schrijfactie en na middernacht is de cache koud, en
betaalde de eerstvolgende gebruiker alles. Een achtergrondthread rekent de
ongefilterde schermen dan alvast uit.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

log = logging.getLogger("console")

# Boven dit aantal rijen wordt een tabel niet op inhoud gehashd.
KLEIN = 200

# Tabellen die GEEN invoer van een analyse zijn en dus helemaal buiten de
# dataversie blijven — niet op inhoud én niet op rijtelling.
#
#   * `anthropic_config`: de API-sleutel; de analyses hangen er niet van af.
#   * `retailer_conclusies`: een conclusie is juist een GEVOLG van de
#     analyses. Telde hij mee, dan zou elke opgeslagen conclusie de cache van
#     álle analyses van álle retailers leegtrekken (gepind in
#     test_conclusie.py).
BUITEN_DATAVERSIE = {"anthropic_config", "retailer_conclusies"}

MAX_SLEUTELS = 256

_CACHE: "OrderedDict[tuple, tuple[tuple, Any]]" = OrderedDict()
_LOCK = threading.Lock()


class _Vlucht:
    """Eén lopende berekening van (sleutel, versie)."""

    def __init__(self):
        self.klaar = threading.Event()
        self.uitkomst: Any = None
        self.gelukt = False
        self.thread = threading.get_ident()


_BEZIG: dict[tuple, _Vlucht] = {}


def data_versie(conn) -> tuple:
    """Een stempel die verandert zodra een invoer van een analyse verandert."""
    from .periods import _vandaag_nl

    pad = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    tabellen = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")
        if r[0] not in BUITEN_DATAVERSIE]
    if not tabellen:
        return (pad, _vandaag_nl().isoformat(), (), ())
    vraag = " UNION ALL ".join(
        f"SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM {t}" for t in tabellen)
    tellingen = tuple(tuple(r) for r in conn.execute(vraag))
    inhoud = []
    for naam, (aantal, _) in zip(tabellen, tellingen):
        if aantal > KLEIN:
            continue
        inhoud.append((naam, tuple(tuple(r) for r in conn.execute(f"SELECT * FROM {naam}"))))
    return (pad, _vandaag_nl().isoformat(), tellingen, tuple(inhoud))


def gecachet(sleutel: tuple, bereken: Callable[[], Any], conn,
             versie: tuple | None = None) -> Any:
    """De uitkomst van `bereken()` voor deze sleutel en de huidige data.

    Uitkomsten zijn GEDEELD tussen verzoeken: aanroepers lezen ze alleen,
    ze passen ze nooit aan.
    """
    if versie is None:
        versie = data_versie(conn)
    vlucht_sleutel = (sleutel, versie)
    with _LOCK:
        gevonden = _CACHE.get(sleutel)
        if gevonden is not None and gevonden[0] == versie:
            _CACHE.move_to_end(sleutel)
            return gevonden[1]
        vlucht = _BEZIG.get(vlucht_sleutel)
        # Dezelfde thread die op zijn eigen berekening zou wachten, loopt
        # vast. Geen enkele analyse vraagt zichzelf op, maar een fout in de
        # aanroepvolgorde mag geen hangend verzoek worden.
        eigen = vlucht is None or vlucht.thread == threading.get_ident()
        if vlucht is None:
            vlucht = _BEZIG[vlucht_sleutel] = _Vlucht()
    if not eigen:
        vlucht.klaar.wait()
        if vlucht.gelukt:
            return vlucht.uitkomst
        # Mislukt bij de ander: zelf proberen, dan komt de fout hier boven.
        return bereken()
    try:
        uitkomst = bereken()
        vlucht.uitkomst, vlucht.gelukt = uitkomst, True
    finally:
        with _LOCK:
            if _BEZIG.get(vlucht_sleutel) is vlucht:
                del _BEZIG[vlucht_sleutel]
            if vlucht.gelukt:
                _CACHE[sleutel] = (versie, vlucht.uitkomst)
                _CACHE.move_to_end(sleutel)
                while len(_CACHE) > MAX_SLEUTELS:
                    _CACHE.popitem(last=False)
        vlucht.klaar.set()
    return uitkomst


def leeg():
    with _LOCK:
        _CACHE.clear()


def aantal() -> int:
    return len(_CACHE)


# --------------------------------------------------------- gedeelde sleutels
#
# Eén definitie per analyse, zodat endpoint en engine nooit uiteenlopende
# sleutels bouwen (dan zou de conclusie het dashboard alsnog opnieuw doen).

def filterwaarden(conn, retailer_id: str):
    """De voorkomende (merk, land, banner, categorie)-combinaties van de
    dashboardrijen, gecachet (klein: tientallen tupels)."""
    from . import analytics

    def bereken():
        niveau = "winkel" if analytics.heeft_winkelslice(conn, retailer_id) else "artikel"
        return analytics.filter_waarden(conn, retailer_id, niveau)
    return gecachet(("filterwaarden", retailer_id), bereken, conn)


_DIMENSIES = ("merk", "land", "banner", "categorie")


def normaliseer_filters(conn, retailer_id: str, **filters) -> dict:
    """Maak gelijkwaardige filterkeuzes één cachesleutel.

    Het scherm stuurt de chips in klikvolgorde ("B,A" en "A,B" waren twee
    berekeningen), en een filter dat alle voorkomende waarden kiest, is
    geen filter: `land=NL` bij Etos (alleen NL) rekende het hele dashboard
    opnieuw uit terwijl het ongefilterde al warm stond. Alleen weglaten als
    er geen rijen ZONDER waarde in die kolom zijn — die vallen door een
    filter wél af.
    """
    actief = {k: v for k, v in filters.items() if v}
    if not actief:
        return {k: None for k in _DIMENSIES}
    combinaties = filterwaarden(conn, retailer_id)
    uit = {}
    for i, dim in enumerate(_DIMENSIES):
        v = filters.get(dim)
        if not v:
            uit[dim] = None
            continue
        gekozen = sorted(set(v.split(",")))
        aanwezig = {c[i] for c in combinaties}
        dekt_alles = None not in aanwezig and aanwezig <= set(gekozen)
        uit[dim] = None if dekt_alles and aanwezig else ",".join(gekozen)
    return uit


def dashboard(conn, retailer_id: str, merk=None, land=None, banner=None, categorie=None):
    """`merk` enz. zoals ze in de querystring staan ("A,B") of None."""
    from . import analytics
    f = normaliseer_filters(conn, retailer_id, merk=merk, land=land, banner=banner,
                            categorie=categorie)
    split = lambda v: v.split(",") if v else None  # noqa: E731
    return gecachet(
        ("dashboard", retailer_id, f["merk"], f["land"], f["banner"], f["categorie"]),
        lambda: analytics.dashboard(conn, retailer_id, split(f["merk"]), split(f["land"]),
                                    split(f["banner"]), split(f["categorie"])), conn)


def artikelen(conn, retailer_id: str, merk=None):
    from . import analytics
    return gecachet(("artikelen", retailer_id, merk),
                    lambda: analytics.articles(conn, retailer_id,
                                               merk.split(",") if merk else None), conn)


def promoties(conn, retailer_id: str):
    from . import analytics
    return gecachet(("promoties", retailer_id),
                    lambda: analytics.promotions(conn, retailer_id), conn)


def assortiment(conn, retailer_id: str):
    from . import analytics
    return gecachet(("assortiment", retailer_id),
                    lambda: analytics.assortment(conn, retailer_id), conn)


def datagaten(conn, retailer_id: str):
    from . import analytics
    from . import datagaten as datagaten_mod

    def bereken():
        caps, _ = analytics.retailer_caps(conn, retailer_id)
        if caps is None:
            return {"beschikbaar": False, "gaten": []}
        rows = analytics.load_facts(conn, retailer_id)
        return {"beschikbaar": True,
                "gaten": datagaten_mod.met_oordeel(conn, retailer_id, rows, caps)}
    return gecachet(("datagaten", retailer_id), bereken, conn)


def bevindingen(conn, retailer_id: str):
    from . import conclusie
    return gecachet(("conclusie-bevindingen", retailer_id),
                    lambda: conclusie.bevindingen(conn, retailer_id), conn)


def overzicht(conn):
    from . import signals
    return gecachet(("overview",), lambda: signals.overview(conn), conn)


# ------------------------------------------------------------------ opwarmen

_POR = threading.Event()
_OPWARMER: threading.Thread | None = None

# Hoe vaak de opwarmer zelf kijkt of de data veranderd is, ook zonder por:
# vangt middernacht (de datum zit in de versie) en schrijfacties van buiten
# dit proces (tools/, seed).
CONTROLE_SECONDEN = 300


def por():
    """Na een schrijfactie: warm de cache weer op."""
    _POR.set()


# Meer chips dan dit per retailer warmt de opwarmer niet op: elke chip is
# een volledige dashboardberekening, en een retailer met honderd merken zou
# de achtergrondthread minutenlang bezig houden.
MAX_CHIPS = 12


def chips(conn, retailer_id: str) -> list[tuple[str, str]]:
    """De losse filterchips die het scherm voor deze retailer toont, in de
    volgorde merk, land, formule — alleen dimensies met meer dan één
    waarde (één waarde is geen filter, zie normaliseer_filters)."""
    combinaties = filterwaarden(conn, retailer_id)
    uit = []
    for i, dim in enumerate(_DIMENSIES[:3]):
        waarden = sorted({c[i] for c in combinaties if c[i]})
        if len(waarden) > 1:
            uit.extend((dim, w) for w in waarden)
    return uit[:MAX_CHIPS]


def opwarmen(conn):
    """Reken de ongefilterde schermen van elke aangesloten retailer uit.

    Volgorde: wat een gebruiker het eerst ziet eerst — het overzicht (bij
    elke navigatie opgevraagd), dan per retailer het dashboard. De conclusie
    als laatste: die hergebruikt de rest.
    """
    from .profile import active_profile
    t = time.perf_counter()
    retailers = [r["id"] for r in conn.execute("SELECT id FROM retailers ORDER BY rowid")
                 if active_profile(conn, r["id"])]

    def stap(f, *args):
        try:
            f(conn, *args)
        except Exception:  # noqa: BLE001 - één kapotte retailer mag de rest niet tegenhouden
            log.exception("opwarmen %s %s mislukt", f.__name__, args)

    stap(overzicht)
    for rid in retailers:
        stap(dashboard, rid)
        stap(filterwaarden, rid)
    for f in (artikelen, promoties, assortiment, datagaten, bevindingen):
        for rid in retailers:
            stap(f, rid)
    # Als laatste de losse filterchips (één merk, één land, één formule):
    # de meest geklikte filters, en elk kost koud een seconde bij Etos.
    for rid in retailers:
        for dim, waarde in chips(conn, rid):
            stap(dashboard, rid, *[waarde if d == dim else None for d in _DIMENSIES])
    log.info("cache opgewarmd voor %d retailer(s) in %.1f s", len(retailers),
             time.perf_counter() - t)


def start_opwarmer(verbinding: Callable):
    """Start de achtergrondthread (één keer). `verbinding` is een
    contextmanager die een databaseverbinding geeft (db.get_conn)."""
    global _OPWARMER
    if os.environ.get("CONSOLE_OPWARMEN", "1").strip() == "0":
        return
    if _OPWARMER is not None and _OPWARMER.is_alive():
        return

    def lus():
        laatste = None
        _POR.set()                         # meteen bij het opstarten
        while True:
            _POR.wait(timeout=CONTROLE_SECONDEN)
            _POR.clear()
            try:
                with verbinding() as conn:
                    versie = data_versie(conn)
                    if versie == laatste:
                        continue
                    opwarmen(conn)
                    laatste = versie
            except Exception:  # noqa: BLE001 - de thread moet blijven lopen
                log.exception("opwarmer")
                time.sleep(5)

    _OPWARMER = threading.Thread(target=lus, name="cache-opwarmer", daemon=True)
    _OPWARMER.start()
