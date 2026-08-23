"""Actieweken herkennen, beoordelen en afzetten tegen een basisniveau.

Wat er te herkennen valt: een week waarin de gemiddelde verkoopprijs onder het
normale niveau lag. Dat kan over het hele assortiment (de hele lijn in de
folder) of op één artikel (één item afgeprijsd). Die twee zien er in de data
heel verschillend uit, en de tweede werd tot nu gemist: de prijsindex weegt
alle artikelen mee, dus één afgeprijsd item van de tien beweegt hem nauwelijks.

Drie keuzes die de uitkomst bepalen, en waarom:

1. **De referentie is de mediaan van de NIET-bevestigde periodes.** Eerder was
   het de mediaan van álle periodes van dat jaar — inclusief de acties zelf. In
   een jaar met veel acties zakt die mediaan mee en verdwijnen juist de echte
   acties uit beeld. De upliftberekening sloot bevestigde periodes al uit; de
   detectie niet.

2. **De drempel wordt afgezet tegen de eigen spreiding.** 5% korting is bij een
   merk met stabiele prijzen zeker een actie en bij een merk met grillige
   prijzen niets. Naast de vaste drempel uit het profiel telt daarom een
   robuuste z-score (MAD x 1,4826): hoeveel keer de normale schommeling is deze
   afwijking? Dat maakt de zekerheidsscore meetbaar in plaats van verzonnen.

3. **Onvolledige periodes doen niet mee.** Een lopende (halve) week en een week
   die deze scope niet geleverd heeft zijn geen lage prijs en geen lage omzet —
   ze zijn geen waarneming. Ze tellen niet in de referentie, niet in het
   gemiddelde, en plafonneren de zekerheid.

De zekerheidsscore is een HEURISTIEK, geen kans. Hij vat vier waarneembare
signalen samen; het scherm toont welke daarvan meetelden, zodat je de score
kunt narekenen in plaats van geloven.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from .periods import is_afgesloten, period_year, sort_key

# Onder dit aantal bruikbare periodes is een mediaan geen referentie maar een
# toevalstreffer; dan doet de app geen uitspraak.
MIN_REFERENTIE = 4

# Vanaf welk deel van de verkochte artikelen we van een assortimentsbrede
# actie spreken in plaats van losse artikelen.
BREED_VANAF = 0.5

# Een artikelactie telt alleen mee als dat artikel er commercieel toe doet:
# één afgeprijsd staartartikel is geen actie om op te sturen.
ARTIKEL_VOLUMEAANDEEL = 0.20

# Volume dat meer dan dit boven de mediaan ligt, geldt als reactie op de actie.
VOLUME_RESPONS = 0.25

_MAD_NAAR_SIGMA = 1.4826


def _spreiding(waarden: list[float], mid: float) -> float:
    """Robuuste standaardafwijking via de MAD.

    Niet de gewone standaardafwijking: die wordt juist opgeblazen door de
    uitschieters die we willen vinden, waardoor een jaar met veel acties zijn
    eigen acties normaal verklaart.
    """
    if len(waarden) < 2:
        return 0.0
    return median([abs(w - mid) for w in waarden]) * _MAD_NAAR_SIGMA


def referentie(per_periode: dict[str, float], negeer: set[str]) -> tuple | None:
    """(normaal niveau, robuuste spreiding, aantal gebruikte periodes).

    `negeer` zijn de periodes die niet meetellen: bevestigde acties en
    onvolledige aanleveringen. None als er te weinig overblijft.
    """
    bruikbaar = [v for p, v in per_periode.items() if p not in negeer]
    if len(bruikbaar) < MIN_REFERENTIE:
        return None
    mid = median(bruikbaar)
    return mid, _spreiding(bruikbaar, mid), len(bruikbaar)


def periodekwaliteit(rows, key, vandaag=None) -> dict[tuple, str]:
    """{(scope, periode): 'volledig' | 'loopt_nog' | 'niet_geleverd'}.

    Een scope die niets levert in een periode waarin de retailer als geheel
    wél leverde, is niet "geen verkoop" maar "geen data" — zelfde redenering
    als engine/dekking.py. Zonder dat onderscheid drukt een niet-geleverde
    week het gemiddelde en lijkt hij bovendien op een actie zonder omzet.
    """
    per_jaar_periodes: dict[int, set] = defaultdict(set)
    geleverd: set[tuple] = set()
    scopes: set = set()
    for r in rows:
        p = r["periode"]
        per_jaar_periodes[period_year(p)].add(p)
        scopes.add(key(r))
        geleverd.add((key(r), p))

    uit: dict[tuple, str] = {}
    for jaar, periodes in per_jaar_periodes.items():
        for p in periodes:
            loopt = not is_afgesloten(p, vandaag)
            for scope in scopes:
                if (scope, p) in geleverd:
                    uit[(scope, p)] = "loopt_nog" if loopt else "volledig"
                else:
                    uit[(scope, p)] = "niet_geleverd"
    return uit


def artikelacties(prijzen: dict, gewicht: dict, scope, jaar: int,
                  periode: str, drempel: float, negeer: set[str]) -> list[dict]:
    """Welke artikelen in deze periode onder hun eigen normale prijs lagen.

    Per artikel de eigen prijsreeks, met dezelfde referentieregel als de scope:
    de mediaan van de periodes die niet als actie of onvolledig gelden.
    """
    uit = []
    totaal_gewicht = sum(g for (s, j, _e), g in gewicht.items() if s == scope and j == jaar)
    for (s, j, ean), reeks in prijzen.items():
        if s != scope or j != jaar or periode not in reeks:
            continue
        ref = referentie(reeks, negeer)
        if ref is None:
            continue
        mid, _spr, _n = ref
        if not mid:
            continue
        daling = (mid - reeks[periode]) / mid
        if daling < drempel:
            continue
        aandeel = (gewicht[(s, j, ean)] / totaal_gewicht) if totaal_gewicht else 0.0
        uit.append({"artikel_ean": ean, "daling_pct": round(daling * 100, 1),
                    "normale_prijs": round(mid, 2),
                    "actieprijs": round(reeks[periode], 2),
                    "volumeaandeel_pct": round(aandeel * 100, 1)})
    return sorted(uit, key=lambda a: -a["daling_pct"])


def _artikelen_met_verkoop(prijzen: dict, scope, jaar: int, periode: str) -> int:
    return sum(1 for (s, j, _e), reeks in prijzen.items()
               if s == scope and j == jaar and periode in reeks)


def bereik_van(acties: list[dict], verkocht: int) -> tuple[str | None, bool]:
    """('assortiment' | 'artikel' | None, telt_als_actie).

    Eén afgeprijsd staartartikel is geen actie om op te sturen; pas met een
    noemenswaardig volumeaandeel telt hij mee.
    """
    if not acties or not verkocht:
        return None, False
    if len(acties) / verkocht >= BREED_VANAF:
        return "assortiment", True
    zwaar = any(a["volumeaandeel_pct"] >= ARTIKEL_VOLUMEAANDEEL * 100 for a in acties)
    return "artikel", zwaar


def zekerheid(z: float | None, volume_respons: float | None,
              bereik: str | None, kwaliteit: str) -> tuple[int, list[dict]]:
    """(score 1-5, welke signalen meetelden).

    Geen kans maar een optelsom van vier waarneembare dingen. De onderdelen
    gaan mee terug zodat het scherm kan laten zien waaróp de score rust — een
    cijfer dat je niet kunt narekenen vertrouw je terecht niet.
    """
    delen = []

    def voeg_toe(naam: str, punten: int, tekst: str):
        delen.append({"naam": naam, "punten": punten, "tekst": tekst})

    if z is None:
        voeg_toe("prijsdaling", 0, "te weinig vergelijkbare periodes voor een referentie")
    elif z >= 3:
        voeg_toe("prijsdaling", 2, f"{z:.1f}x de normale prijsschommeling")
    elif z >= 2:
        voeg_toe("prijsdaling", 1, f"{z:.1f}x de normale prijsschommeling")
    else:
        voeg_toe("prijsdaling", 0,
                 f"{z:.1f}x de normale schommeling — binnen de ruis van dit merk")

    if volume_respons is None:
        voeg_toe("volume", 0, "geen volume om mee te vergelijken")
    elif volume_respons >= VOLUME_RESPONS:
        voeg_toe("volume", 1, f"+{round(volume_respons * 100)}% volume tegenover normaal")
    else:
        voeg_toe("volume", 0, "volume reageerde niet noemenswaardig")

    if bereik == "assortiment":
        voeg_toe("bereik", 1, "het hele assortiment lag onder de normale prijs")
    elif bereik == "artikel":
        voeg_toe("bereik", 1, "een artikel met noemenswaardig volume was afgeprijsd")
    else:
        voeg_toe("bereik", 0, "geen enkel artikel viel apart op")

    if kwaliteit == "volledig":
        voeg_toe("data", 1, "de periode is compleet geleverd en afgesloten")
    else:
        voeg_toe("data", 0,
                 "de periode loopt nog" if kwaliteit == "loopt_nog"
                 else "deze scope leverde deze periode niets")

    score = sum(d["punten"] for d in delen)
    if kwaliteit != "volledig":
        # Op onvolledige data kan de app niet zeker zijn, hoe hard het
        # prijssignaal ook lijkt.
        score = min(score, 2)
    return max(1, min(5, score)), delen


def gemiddelde_periodeomzet(per_scope_periode: dict, kwaliteit: dict,
                            uitgesloten: dict[tuple, str]) -> list[dict]:
    """Gemiddelde omzet per periode per scope, over de periodes die overblijven.

    Uitgesloten: bevestigde acties, voorgestelde acties en onvolledige
    periodes. Zonder die drie meet je niet het normale niveau maar een mengsel
    van actieweken en niet-geleverde weken — en juist dat normale niveau is
    waar een actie tegen afgezet hoort te worden.
    """
    per_scope_jaar: dict[tuple, list] = defaultdict(list)
    weg: dict[tuple, list] = defaultdict(list)
    for (scope, periode), agg in per_scope_periode.items():
        jaar = period_year(periode)
        reden = uitgesloten.get((scope, periode))
        if reden is None and kwaliteit.get((scope, periode), "volledig") != "volledig":
            reden = kwaliteit[(scope, periode)]
        if reden:
            weg[(scope, jaar)].append({"periode": periode, "reden": reden})
            continue
        per_scope_jaar[(scope, jaar)].append(agg["omzet"])

    uit = []
    for (scope, jaar), omzetten in per_scope_jaar.items():
        merk, land, banner = scope
        uit.append({
            "merk": merk, "land": land, "banner": banner, "jaar": jaar,
            "gemiddelde": round(sum(omzetten) / len(omzetten), 2),
            "mediaan": round(median(omzetten), 2),
            "periodes": len(omzetten),
            "uitgesloten": sorted(weg.get((scope, jaar), []),
                                  key=lambda x: sort_key(x["periode"])),
        })
    return sorted(uit, key=lambda x: (-x["jaar"], x["merk"] or "", x["land"] or ""))
