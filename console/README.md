# Retailer Console

Multi-retailer herbouw van de interne "Data analyse agent", naar het
high-fidelity ontwerp uit `design/` (By Leijtens design system). Eén canoniek
datamodel, per retailer een parser die in dít project gebouwd wordt tegen een
écht aanleverbestand — er zit geen retailer-specifieke code in analyses of UI,
en er valt in de app niets te mappen of te publiceren.

Deze console is sinds de verwijdering van de oude Streamlit-app (`app/`) de
enige applicatie in deze repo.

## Starten

```bash
cd console
make seed   # voorbeelddata door de echte import-pipeline
make dev    # backend :8000 + frontend :5173
```

## Deployen op de droplet

De console draait als **één container** met een eigen image en een eigen
database in `console/data/`; daarnaast draait alleen nog de `backup`-service.

Toegang loopt via het **portaal** (privé-adres + firewallregel voor de
gateway + forward-auth), net als bij de andere apps. Niets van deze repo
wordt op het publieke IP gepubliceerd; er zit ook geen eigen reverse proxy
meer in — het portaal doet de TLS.

Kerngegevens voor de gateway-registratie:

| | |
|---|---|
| Interne poort | **8000** (uvicorn in de container; `CONSOLE_PORT` is alleen de host-kant) |
| Hostbinding | standaard `127.0.0.1`; zet `CONSOLE_BIND` op het privé-adres als de gateway erbij moet — nooit `0.0.0.0` |
| Healthcheck | `GET` én `HEAD` op `/healthz` en `/healthz/` — altijd zonder auth, ook als `CONSOLE_PASSWORD` gezet is; 200, of 503 als de database niet antwoordt |
| Protocol | gewone request/response; **geen** WebSockets of SSE |
| Padgevoelig | ja: de SPA gebruikt absolute `/assets`- en `/api`-paden, dus eigen host/root, geen subpad |
| Uploads | `POST /api/import` is multipart; backendlimiet standaard **200 MB per bestand** (`CONSOLE_MAX_UPLOAD_MB`) — zet de gatewaylimiet minimaal even hoog |

```bash
cd <repo>
git pull
docker compose up -d --build console      # bindt op ${CONSOLE_BIND}:8010 -> :8000
curl -fsS "http://$(docker compose port console 8000)/healthz"
```

`localhost:8010` werkt alleen bij de standaardbinding. Staat `CONSOLE_BIND`
op het privé-adres (nodig zodra de gateway erbij moet), dan luistert loopback
niet en weigert `curl localhost:8010` terecht — vandaar `docker compose port`,
dat het echte adres opvraagt. Onafhankelijk van welk adres dan ook: de
container heeft een `HEALTHCHECK`, dus `docker compose ps` toont `healthy`
zodra de app draait.

Start er iets niet, dan wijst `bash deploy/diagnose.sh` de oorzaak aan: welk
proces een poort vasthoudt, of er per ongeluk twee compose-projecten naast
elkaar staan (elk met een eigen database), en of de console gezond is. Het
script leest alleen en wijzigt niets.

## Thema en kleurpalet

Licht of donker kiest de gebruiker bij **Instellingen → Weergave**: systeem,
licht of donker. De keuze staat in `localStorage` onder `bl-theme` en geldt
dus per browser — hij blijft staan na uitloggen en na het sluiten van de
browser. Er is bewust geen serverkant: een voorkeur die pas na een
API-antwoord toegepast wordt, laat de pagina eerst in het verkeerde thema
opflitsen. In de stand *systeem* volgt de app `prefers-color-scheme` en
wisselt hij live mee als de computer omschakelt.

Het thema staat als `data-theme="light" | "dark"` op `<html>`. Dat gebeurt in
een klein script in `index.html`, vóór de eerste verf; `src/theme.ts` doet
daarna hetzelfde vanuit de app. Wijzig je het een, wijzig dan het ander mee.

**Alle kleuren staan in `src/ds/theme.css`** — dat is de enige plek waar het
palet beheerd wordt. De rest van de stylesheets en de componenten verwijzen
naar variabelen (`var(--t-card)`, `var(--cat3)`), ook in SVG-attributen, zodat
een grafiek vanzelf met het thema meekleurt. De oude merkaliassen uit
`colors_and_type.css` (`--fg-1`, `--bg-page`, …) wijzen door naar de
themavariabelen.

| groep | tokens | waarvoor |
|---|---|---|
| vlakken | `--t-bg` `--t-card` `--t-card2` `--t-border` | pagina, kaart, verzonken vlak, haarlijn |
| tekst | `--t-fg` `--t-fg2` `--t-meta` | primair, secundair, metadata |
| zijbalk | `--t-sidebar*` | die blijft donker in beide thema's |
| jaren | `--c-y1..3` | grafiekreeksen per jaar, per thema anders |
| categorieën | `--cat1..10` | merken en retailers, in beide thema's gelijk |
| signalen | `--pos` `--neg` `--warn` (+ `-text`) | vlakken/stippen, en de leesbare tekstvariant |
| accent | `--accent` | **alleen** de targetlijn en één haarlijn per pagina |

`--t-fg3`, `--pos`, `--neg` en `--warn` uit de handoff halen als kleine tekst
de 4,5:1-norm niet. Ze blijven daarom voor stippen, lijnen en vlakken (norm
3:1), en voor tekst staan er `--t-meta`, `--pos-text`, `--neg-text` en
`--warn-text` naast — dezelfde tint, een stap donkerder of lichter.

Kleur gewijzigd? Meet opnieuw:

```bash
cd console/frontend && node contrast.mjs
```

Dat leest `theme.css`, toetst tekst aan 4,5:1 en UI-elementen aan 3:1, en
meldt reekskleuren die perceptueel (OKLab) te dicht bij elkaar liggen om in
één grafiek uit elkaar te houden.

**Toegangscontrole: één schakelaar, `CONSOLE_AUTH`.** Instellingen kunnen
elkaar dus niet tegenspreken.

- **`gateway`** (standaard): de app doet zélf geen authenticatie — een
  geslaagde portal-login is voldoende en er komt nooit een browserprompt.
  Een achtergebleven `CONSOLE_PASSWORD` wordt genegeerd, met een melding in
  de log. Mag alleen bij een privé binding: **`gateway` samen met
  `CONSOLE_BIND=0.0.0.0` weigert te starten**, de enige combinatie die
  verkoopcijfers stilletjes publiek zou zetten.
- **`password`**: HTTP basic auth in de app zelf. Vereist
  `CONSOLE_PASSWORD`, en de gateway moet dan de `Authorization: Basic`-header
  injecteren — anders krijgt iedereen een prompt met een wachtwoord dat
  niemand kent.

`CONSOLE_ALLOW_OPEN=1` uit eerdere versies blijft werken en betekent
`gateway`; die stand wint nu van een gezet wachtwoord.

**Bewuste keuze: geen per-retailer autorisatie.** Beide standen hierboven
zijn all-or-nothing — wie de poort door is (portal-login of het gedeelde
wachtwoord) kan elke retailer zien én wijzigen, er is geen gebruikers- of
rollentabel. Dat is een expliciet geaccepteerd risico, passend bij een
klein, vertrouwd intern team waarvoor de app is gebouwd: iedereen mag
sowieso alle retailers zien. Het logboek (wie wijzigde wat) is dan ook een
werkafspraak, geen beveiligingsmaatregel. **Zodra de gebruikersgroep ooit
breder wordt dan dat ene vertrouwde team** — externe partijen, retailer-
eigen medewerkers, of iedereen die niet elke retailer mag zien — is echte
per-gebruiker/per-retailer toegangscontrole nodig vóór die uitbreiding,
niet erna.

Een eigen hostnaam in plaats van een subpad (`/console`) is bewust: de SPA
verwijst naar absolute `/assets`- en `/api`-paden, die onder een prefix
zouden breken. Registreer hem in het portaal dus op een eigen host, niet
onder `/console`.

Bij de **eerste start** laadt de console alleen de parser-profielen voor de
retailers waarvan het aanleverformaat bekend is (Kruidvat DWH, ICI Paris XL
maandrapport). Verder is een verse installatie **leeg**: geen winkelaantallen,
targets, mailregels of contractdocumenten. Dat is
bewust — een verzonnen winkelaantal of rotatietarget voedt echte
berekeningen (omzet per winkel, delist-advies) en levert dan geloofwaardige
maar onjuiste cijfers.

Demodata (verzonnen instellingen + drie jaar verkoopcijfers) is een
expliciete actie: `make seed`, of in de container
`docker compose exec console python seed.py`.

Staat er nog demodata in een bestaande installatie, dan haalt dit script hem
eruit — alleen rijen die exact met de demo-waarden overeenkomen, dus eigen
aanpassingen en echte imports blijven staan:

```bash
docker compose exec console python cleanup_demo.py          # toon wat er weg zou gaan
docker compose exec console python cleanup_demo.py --doen   # opruimen
```

**Dubbele feitregels.** Databases die zijn gevuld vóór de correctie-fix
kunnen dubbele cijfers bevatten: een herlevering van een al ingelezen
periode kwam er toen náást te staan en werd opgeteld. Dit script spoort ze
op en houdt per combinatie de regel uit de nieuwste import over:

```bash
docker compose exec console python cleanup_duplicates.py          # toon het verschil
docker compose exec console python cleanup_duplicates.py --doen   # opruimen
```

## Stack & motivatie

- **Backend**: FastAPI + SQLite via **plain `sqlite3`** (geen ORM). Bewuste
  afwijking van de SQLAlchemy-suggestie: de migraties draaien zo letterlijk
  (`schema.sql` uit de handoff wordt verbatim uitgevoerd als migratie 001),
  het queryprofiel is klein en leest als de SQL die de analyses nodig hebben,
  en het spiegelt de bewezen aanpak van de bestaande app (WAL, één bestand,
  nul extra dependencies). DuckDB kan later achter dezelfde querylaag als
  aggregaties zwaar worden.
- **Frontend**: React 18 + Vite + TypeScript, zonder UI-library; tokens en
  fonts 1:1 uit het design system (`frontend/src/ds/`).
- **Tests**: pytest voor parser-engine, imports, analyses, stabiliteit en
  toegangscontrole; GitHub Actions draait ze bij elke PR samen met een
  productiebuild van de frontend.

## Architectuur

```
console/
  backend/
    migrations/001_schema.sql   # canoniek model (uit de handoff, verbatim)
    engine/
      profile.py     # profielen + capability-AFLEIDING (nooit opgeslagen)
      parser.py      # detectie (glob + header-tiebreak) + parsing/validatie
      importer.py    # atomaire imports; herimport vervangt op file-hash
      periods.py     # yyyyww / yyyy-Www / mm-yyyy -> '2026-W32' / '2026-07'
      fallback.py    # de 4 terugvalregels, altijd met level_used + labels
      analytics.py   # dashboard, artikelen, promoties+uplift, assortiment
      signals.py     # signalenradar (assortiment / contract / data)
      contracts.py   # PDF-contractupload: tekst uitlezen + Claude-analyse
    main.py          # FastAPI-endpoints
    seed.py          # seeds in ECHT formaat door de echte pipeline
  frontend/          # tabs boven, donkere sidebar, 9 schermen
  profiles/          # de vier handoff-profielen (kruidvat/etos/ici/douglas)
  seed/              # stand-ins + contracts.json
  design/            # tokens, fonts, logo (referentie)
```

### Parser-profielen

Schema: zie `profiles/*.json` (PROMPT.md §3). Kernregels:

- **Profielen komen uit het project**, niet uit de app: ingebouwde parsers
  (`builtin`: kruidvat_dwh, ici_maandrapport, etos_datagrid) of een JSON in
  `profiles/`. De app heeft geen mapping-editor en geen publiceer-endpoint;
  het Parser-scherm is alleen-lezen plus "controleren op bestand".
- **Etos (Data Grid-widgetexport)**: artikel×week-matrix, land constant NL,
  geen winkel- of bannerniveau. Dit formaat heeft géén totalenrij; de parser
  verifieert daarom fail-closed alles wat het bestand zelf biedt: het
  merkental ("Brand (N)"), het weekbereik ("Fiscal YTD …-…") en per week de
  Ending-datum tegen de ISO-zondag — wijkt Etos ooit af van ISO-weken, dan
  stopt de import in plaats van weken verkeerd te labelen. Elke download is
  een groeiend YTD-bestand: overlappende weken worden vervangen op de
  natuurlijke sleutel, dus herimporteren telt nooit dubbel.
- **Bootstrap draait bij elke start** (idempotent): een nieuw meegeleverd
  profiel komt zo ook op een bestaande installatie aan.
- **Capabilities worden afgeleid** uit mapping + constants (of liggen bij een
  ingebouwde parser vast), nergens opgeslagen.
- **ICI Paris XL levert NL en BE apart** (`ici-paris-xl` en `ici-paris-be`):
  twee retailers, elk met een eigen winkelbestand en een eigen tabblad. Het
  rapport noemt zelf geen land, dus dat staat in `constants.land` van het
  profiel — zonder dat zou Belgische omzet als Nederlandse in de analyses
  belanden. Beide gebruiken dezelfde ingebouwde parser; ze worden onderscheiden
  op bestandsnaam (`*ici?paris*.xlsx` tegenover `SO_*.xlsx`) én, voor hernoemde
  bestanden, op **winkelnummer** (`detection.winkelreeks`). ICI nummert per
  land in een eigen reeks: BE 5xxx, NL 6xxx en 7xxx, zonder één overlappend
  nummer (gecontroleerd op de echte bestanden van juli 2026: BE 5004–5308 over
  135 winkels, NL 6051–7995 over 151). Dat is betrouwbaarder dan de plaatsnaam:
  stadsnamen komen in beide landen voor en dezelfde stad staat er soms met
  verschillende accenten in (LA LOUVIÈRE / LA LOUVIÉRE). Alle winkels moeten in
  de reeks passen; past er één niet, dan is niet-herkennen (en dus vragen)
  beter dan een half kloppende gok.
- **Detectie**: filename-glob, met sheet/verplichte-headers als tiebreak, en
  voor ingebouwde parsers structuurherkenning van de inhoud (hernoemen mag).
  Nul matches ⇒ status **PROFIEL NODIG**. Concept-profielen doen nooit mee.
  Bij **meerdere** matches raadt de app niet: de controlestap toont de
  kandidaten en de gebruiker kiest ("Importeren als ICI Paris XL BE"). Die
  keuze gaat als `retailer_id` mee met de import en wordt gecontroleerd tegen
  de kandidaten, zodat een bestand nooit door een parser gedrukt kan worden
  die het formaat niet aankan. Dit speelt bij een hernoemd ICI-rapport: NL en
  BE zijn qua structuur identiek en alleen de aanleveraar weet welk land het
  is.
- **Versionering**: nieuwe versie naast de oude; oude versies blijven leesbaar;
  elke import logt de gebruikte versie. Een profiel in `test` leest wél in,
  maar de feiten zijn gevlagd: zichtbaar in de schermen van die retailer
  (met label PROFIEL IN TEST), uitgesloten van cross-retailer-rapportage.
- **Atomair**: één kapotte rij ⇒ status `error` met rijniveau-detail en nul
  nieuwe feiten. Herimport van hetzelfde bestand vervangt (file-hash-dedupe).

### Terugvalregels (nooit stil)

| Gevraagd | Niet beschikbaar → | Label |
|---|---|---|
| artikel | merk | `OP MERKNIVEAU` |
| week | maand | `OP MAANDNIVEAU` |
| winkel_id | handmatig winkelaantal uit Instellingen | `SCHATTING` |
| banner | aggregatie per merk+land | — |

Elk analyse-resultaat bevat `{level_used, labels[]}`; de UI toont de
niveau-strip zodra `labels` niet leeg is.

### Aantal winkels

Levert de retailer winkelniveau, dan is het aantal winkels **het aantal
winkels dat in het lopende jaar omzet draaide voor dat merk** — per merk
apart, niet één gedeeld winkelbestand. Een winkellijst bevat ook filialen
die het merk niet voeren; die meetellen drukt de gemiddelde omzet per
winkel omlaag. Het jaartotaal is de maatstaf, niet de losse maand: een
winkel die in juli toevallig niets verkocht hoort nog steeds bij dat jaar.
Bij ICI Paris XL scheelt het per merk een factor — TWEEZERMAN ~145
winkels, DEPEND ~139, en per maand nog veel minder.

Zonder winkelniveau valt de teller terug op het handmatige aantal uit
Instellingen → Doelstellingen (label `SCHATTING`). Dat kan per merk-land(-
formule) op twee niveaus:

* **Merkniveau** — één getal voor de hele combinatie. Zoals het altijd was.
* **Artikelniveau** — een aantal per artikel uit de feed. Nodig zodra de
  artikelen van een merk niet in evenveel winkels liggen: een basisitem in
  800 filialen, een nieuwe kleur in 120. De rotatie en de omzet per winkel
  van een artikel delen dan door de winkels van dát artikel; een artikel
  zonder eigen getal valt terug op het merkgetal.

**Statistisch voorbehoud bij het merkgemiddelde.** Het aantal winkels van een
merk is de *vereniging* van de winkels per artikel. Uit losse aantallen is die
vereniging niet te berekenen — je kent alleen de grenzen:

    max(artikelen)  <=  merk  <=  min(som(artikelen), totaal filialen)

De app neemt de **ondergrens**: het grootste artikel. Dat is exact juist zodra
het smallere assortiment in dezelfde winkels ligt als het brede — de normale
situatie, want een filiaal dat de nieuwe kleur voert heeft vrijwel altijd ook
het basisitem. Liggen artikelen in verschillende winkels, dan is het echte
aantal hoger en valt de omzet per winkel op merkniveau te **hoog** uit.
Optellen zou de andere kant op fout zijn: elke winkel die twee artikelen voert
telt dan dubbel en het gemiddelde zakt naar een fractie van de werkelijkheid.
Van de twee grenzen is dit de veiligste, en de enige die klopt in het normale
geval. Het scherm meldt bij het merkgetal dat het een afgeleide is.

Wie het exact wil weten, heeft winkelniveau in de feed nodig — dan telt de app
de winkels en komt er geen aanname aan te pas.

Targets blijven op merk-landniveau: een target per artikel is een andere
afspraak dan er met de retailer gemaakt wordt.

### Lopende periode

Levert een retailer halverwege de maand, dan is die maand geen hele maand.
`is_afgesloten()` (in `periods.py`) bepaalt of de laatste periode al voorbij
is; het dashboard toont hem wél als KPI maar met het label **LOPEND**, en de
YTD-vergelijking rekent t/m de laatste **afgesloten** periode — anders zet je
een halve maand naast een hele maand vorig jaar.

### Omzet per winkel over tijd (dashboard)

Twee panelen op één tijdas: boven de gemiddelde omzet per winkel, eronder het
winkelbestand — één lijn per merk, zelfde kleur. Loopt de bovenste lijn op
terwijl de onderste zakt, dan komt de stijging van een kleiner winkelbestand
en niet van betere verkoop. Bewust geen tweede y-as in één grafiek: dan
bepaalt de schaalkeuze hoe sterk het verband lijkt.

Daaronder de decompositie, exact multiplicatief:
`omzet% = winkels% × omzet-per-winkel%`. Op de echte ICI-data (juli 2026 vs
juli 2025): TWEEZERMAN +32,6% = −0,7% × +33,5%; DEPEND +63,8% = +14,6% ×
+42,9%.

Het winkelaantal per periode komt uit de bron die beschikbaar is:

- **winkelniveau in de feed** (ICI): unieke winkels mét omzet in een
  voortschrijdend venster (3 maanden / 13 weken). Een losse maand is bij een
  langzaam merk ruis — DEPEND springt van 66 naar 102 winkels per maand
  terwijl het kwartaalcijfer rond 123–133 ligt. Voor de decompositie worden
  wél de ruwe periodecijfers gebruikt, zodat teller en noemer over dezelfde
  periode gaan en de drie percentages exact op elkaar aansluiten.
- **geen winkelniveau** (Kruidvat, Etos): een stapfunctie uit de handmatige
  metingen. Elk winkelaantal heeft een **`geldig_vanaf`**-datum (migratie
  004), dus 2025 wordt door het aantal van 2025 gedeeld en niet door dat van
  vandaag. Vóór de oudste meting rekent de app door met dat oudste getal,
  maar gemarkeerd als `aangenomen` (gestippeld in de grafiek).

Historische metingen leg je vast bij **Instellingen** → per rij "historie":
aantal + datum. Ook via `POST /api/{retailer}/winkelaantallen`.

### Distributiesignaal (Overzicht)

Ligt ons merk nog in evenveel winkels? Twee bronnen, per retailer wat er
beschikbaar is: levert de feed winkelniveau (ICI), dan telt de winkelanalyse
de winkels die dit jaar stilgevallen zijn met de omzet die we mislopen;
anders komt het uit de winkelaantallen in Instellingen — élke wijziging
daarvan wordt bewaard in `winkelaantal_historie`, zodat "530 → 470 sinds
17-08" zichtbaar wordt. Eén meting zegt nog niets (grijs); een daling van
10% of meer is rood. Het instellingenscherm toont de vorige waarde onder het
invoerveld.

### Winkelanalyse (retailers mét winkelniveau)

Op het dashboard: winkels die dit jaar stilgevallen zijn (wél eerder omzet,
daarna **twee of meer** maanden niets) met de omzet van vorig jaar als maat
voor de gemiste omzet, plus een actiepunt richting de category manager. Eén
lege maand is bij een langzaamlopend merk ruis; die winkels staan apart
onder "Let op" en tellen niet mee in de gemiste omzet. En
omgekeerd de nieuwe winkels: vorig jaar geen omzet, dit jaar wel. Per
winkel én merk, want een filiaal kan het ene merk laten vallen en het
andere houden.

"Gemist" is wat die winkel in **dezelfde maanden** van vorig jaar verkocht,
niet zijn hele vorige jaar: dat laatste telt maanden mee die dit jaar nog
moeten komen (op de echte ICI-data € 11.865 in plaats van € 6.160). Is vorig
jaar voor een merk niet geladen, dan blijft de lijst met nieuwe winkels leeg
met een melding — anders zou elke winkel "nieuw" heten (244 in plaats van 2).

### Promoties: prijsindex, geen gemiddelde stukprijs

De stukprijs van een heel merk (omzet ÷ volume) beweegt net zo hard mee met
de verkoopmix als met de prijs. Kruidvat-artikelen lopen van € 6,09 tot
€ 25,22: verkoopt het goedkope artikel een week wat meer, dan "daalt" de
gemiddelde prijs zonder afprijzing. Daarom volgt `prijsindex()` de prijs
**per artikel** en telt die met vaste gewichten (het jaarvolume) op, en
vergelijkt met de mediaan van **hetzelfde jaar** — een prijspeil dat over de
jaren stijgt zou anders elk ouder jaar als afgeprijsd bestempelen. Op de
echte feed: 42 gevlagde weken → 34, en wat overblijft is terug te voeren op
een echte prijsdaling per artikel.

Zonder artikelniveau (ICI) is er geen suggestie, alleen handmatig markeren:
`methode` in het antwoord zegt welke van de twee geldt.

De uplift meet tegen de **mediaan** van de niet-actieperiodes uit hetzelfde
jaar. Over jaren heen middelen vergelijkt door omzetregimes heen (Kruidvat
2024: € 33k/week, 2025: € 47k). Onder drie basisperiodes volgt geen
percentage maar "te weinig basisperiodes".

### Percentages: na te rekenen uit wat er staat

Eén regel door de hele app: **een percentage staat naast de twee getallen
waaruit het volgt.** Een cijfer dat je niet kunt controleren vertrouw je
terecht niet — en dat kostte de rest van het scherm zijn geloofwaardigheid.

Dat speelde op de YTD-kaarten. Het Δ% werd op de *vergelijkbare basis*
gerekend (per merk alleen het venster dat beide jaren leveren) terwijl de
bedragen de *volledige* totalen waren. Allebei juist, maar samen op één kaart
onmogelijk: "€ 4.419.442 tegen € 1.841.919, +29,2%" leest als een rekenfout.

Nu staan er twee percentages, elk bij zijn eigen bedragen:

* boven aan de kaart de kale verhouding tussen de twee totalen
  (`totaal_delta_pct`);
* eronder, alleen als hij afwijkt, de groei op vergelijkbare basis
  (`delta_pct`) mét de bedragen waarop die rust (`vergelijkbaar.nu` /
  `.vorig`).

De vergelijkbare basis zelf is ongewijzigd — die correctie is er niet voor
niets: zonder haar las "twee merk-feeds erbij" als groei en "een vergeten
kwartaal" als daling, beide gereproduceerd op echte bestanden. Wat verandert
is dat het scherm nu laat zien waar het cijfer vandaan komt in plaats van het
te poneren.

Dezelfde regel elders: de per-merktabel rekende al binnen het eigen venster van
elk merk (bedragen en Δ% horen daar bij elkaar); in de artikelanalyse en bij de
promotie-uplift staan de twee onderliggende bedragen nu in de hovertekst — de
actie-omzet tegen de basislijn, met het aantal periodes waarover die mediaan
gaat.

### Rotatie

Gedeeld door de periodes **sinds de eerste verkoop** van dat artikel en door
de winkels die dát artikel voerden — niet door het hele jaar en het hele
filiaalnet van het merk, want dan wordt een artikel dat in week 20 is
geïntroduceerd een delist-kandidaat. Onder vier actieve periodes volgt geen
oordeel maar "Te kort geleden geïntroduceerd".

### Contractdocumenten

Contracten worden per retailer als PDF geüpload (Instellingen → Contract).
Claude (Anthropic API) haalt er de looptijd, een conclusie (loopt nog /
verlopen) en de afgesproken condities (betalingen, COOP-investeringen e.d.)
uit. Een nieuwe upload vervangt het vorige contract — er is geen
geschiedenis. Het contractsignaal op het Overzicht blijft live herberekend
uit de gevonden einddatum (`signals.py`), niet door het model geraden.

De Anthropic API-sleutel wordt bij voorkeur direct in de app ingevuld
(Instellingen → "AI-contractanalyse", boven aan elk retailer-scherm, dus
retailer-onafhankelijk) — met een live statustest (groen/rood) bij opslaan
en op aanvraag. Een `ANTHROPIC_API_KEY` in de omgeving blijft werken als
terugval (bv. vlak na een verse deploy); de in-app-sleutel wint als beide
gezet zijn. Zonder geldige sleutel geeft een upload een nette 422 en blijft
de rest van de app gewoon werken.

### Dekkingsgaten (wat er in het laatste jaar ontbreekt)

`engine/dekking.py` meldt per scope (merk x land x formule) wat er binnen het
laatste jaar ontbreekt: een feed die stopt, later begint, of een gat heeft.
Die meldingen hangen als driehoekje bij de artikelen die het aangaat, in de
artikel- en assortimentsanalyse, én op het dashboard bij de **filterchip van
het merk** waar ze over gaan (`dekkingsgaten` in de dashboardrespons — de
sleutel `dekking` is daar al bezet door het YTD-venster per jaar). Het
dashboard is waar de totalen gelezen worden, en juist daar bepaalt een
stilgevallen feed of het cijfer nog iets betekent; aan het getal zelf is dat
niet te zien.

Bij het merk en niet in een losse melding bovenaan: dan zie je meteen wíé het
betreft, zonder een naam op te zoeken in een aparte tekst. Meldingen zonder
merk horen bij geen enkele chip; die blijven onder de trendgrafiek staan.

De melding onder de trendgrafiek ("X loopt t/m week Y — daarná telt de lijn
zonder dat merk") laat weg wat de kaart al noemt: twee formuleringen van
hetzelfde feit op één scherm lezen als twee problemen. Eén periode achterlopen
meldt de kaart bewust niet (normale levercadans, zie `dekking.py`), dus die
blijft onder de grafiek staan — de lijn zakt er wel degelijk van.

### Datagaten (meerjarige gaten in de aanlevering)

`engine/dekking.py` vindt gaten *binnen* het laatste jaar — het filtert daar
eerst op (`jaar = max(...)`). Een merk met doorverkoop in 2024, niets in 2025
en weer wel in 2026 valt daar structureel buiten. `engine/datagaten.py` kijkt
juist over de jaren heen: per scope (merk/land/formule) de jaren die tussen de
eerste en de laatste levering ontbreken, en alleen jaren waarin de retailer als
geheel wél leverde — anders is het geen gat maar een periode waarin de
samenwerking nog niet liep. Het begin en het einde van een reeks tellen dus
niet mee, en twee losse gaten zijn twee meldingen.

Of zo'n gat klopt (het merk lag dat jaar niet bij deze retailer) of niet (een
bestand is nooit ingelezen) is **niet uit de data af te leiden**: in beide
gevallen staat er niets. Daarom meldt de app het en vraagt om een oordeel
(Import status → Datagaten; het dashboard toont een melding zolang er iets
onbeoordeeld is). Het oordeel hangt aan de scope plus het jaarbereik, niet aan
een id van een bevinding — de detectie draait elke import opnieuw en zou anders
telkens een "nieuw" gat opleveren dat al beoordeeld was.

### Mijlpalen op de trendgrafiek

Klikken in de lijngrafiek op het dashboard zet een mijlpaal op de aangeklikte
week of maand ("introductie nieuw item", "folderactie"). De x-as is het
periodenummer met de jaren als losse lijnen, dus een mijlpaal hoort bij een
jaar én een periodenummer: week 12 van 2025 ligt op dezelfde x als week 12 van
2026, maar op een andere lijn — vandaar de jaarkeuze in het formulier en de
kleur van dat jaar op de marker. Ze staan standaard aan, zijn met een schuifje
uit te zetten en per jaar te filteren.

Een mijlpaal hoort bij één **merk**, en alleen bij een merk waarvan deze
retailer ook echt data heeft (de API weigert de rest): een markering op een
merk zonder lijn verklaart een piek die er niet is. Staat het merkfilter van
het dashboard aan, dan komen alleen de mijlpalen van die merken mee; zonder
filter alle. Mijlpalen van vóór de merkkolom hebben geen merk — die gelden
retailer-breed en horen dus bij elke selectie.

### One-shot of doorlopend

Een project is **one-shot** (één levering: kerstactie, eenmalige display) of
**doorlopend** (het product blijft in het schap en wordt bijbesteld). Bij een
one-shot verdwijnen alle velden over terugkerende omzet uit het scherm —
rotatie per winkel, de weekkolom, de kaart "Netto marge terugkerend" en de
keuze "drukt op" bij de kosten — want er is geen doorverkoop per week om ze
tegen af te zetten. Een getal dat nergens in meetelt leest als een fout in de
berekening in plaats van als een keuze.

Twee dingen die bewust níét stil gebeuren:

* Een ingevulde rotatie blijft in de database staan. Terugzetten naar
  doorlopend brengt de doorrekening ongewijzigd terug.
* Kostenregels die op "looptijd" stonden, drukken bij een one-shot op de
  eenmalige marge. Ze zouden anders uit elk totaal vallen en het project
  winstgevender laten lijken dan het is.

De drempel voor de terugkerende marge geldt niet voor een one-shot: er is geen
terugkerende omzet, dus er valt niets te toetsen. Standaard is `doorlopend`,
zodat bestaande projecten precies hetzelfde blijven uitkomen (migratie `016`).

### Drempelmarges (bedrijfsnormen)

Instellingen → Bedrijfsnormen: de minimale **eenmalige** en **terugkerende
nettomarge**, als percentage van de bijbehorende omzet, bedrijfsbreed (`bedrijfsinstellingen`, één rij,
zoals `anthropic_config`). Twee drempels omdat het twee beslissingen zijn: de
eenmalige vulling is een investering die je één keer doet (listing fee,
display) en mag krapper; de terugkerende omzet moet het jaar rond dragen.

Leeg = niet meten. Geen drempel is bewust géén goedkeuring: het oordeel blijft
dan leeg in plaats van "voldoet". De projectcalculator toetst er direct aan en
zet een rode driehoek met uitleg bij wat het niet haalt — op de resultaatkaart
(nettomarge, ná kosten) en al bij het product zelf zodra de **brutomarge** de
drempel niet haalt: dan haalt het project hem zeker niet, want de kosten komen
er nog af. Dat percentage staat achter het margebedrag in de kolommen
"Eenmalig" en "Per week": het is de brutomarge per stuk en dus in beide
kolommen gelijk, maar elke kolom wordt aan zijn eigen drempel gehouden — de
driehoek verschijnt dus in de kolom waar de norm niet gehaald wordt.

De calculator rekent twee keer: `engine/projecten.bereken()` bij het opslaan en
een spiegel in `screens/Projecten.tsx` tijdens het typen. Beide zijn getest met
dezelfde cijfers (`test_projecten.py` en `Projectmarge.test.ts`), zodat de twee
implementaties niet uit elkaar lopen.

### Back-up

Beide databases worden dagelijks gekopieerd door de `backup`-service in
`docker-compose.yml` (`sqlite3 .backup` + integriteitscontrole, 14 dagen
bewaard in `backups/`). Herstelprocedure: `deploy/restore.md`.

**Bewuste keuze: de Anthropic API-sleutel staat onversleuteld in de
database** (`anthropic_config.api_key`, zie "AI-contractanalyse" hierboven)
en komt dus ook onversleuteld in elke dagelijkse back-up terecht. Dat is
hetzelfde beveiligingsniveau als `CONSOLE_PASSWORD` nu al heeft (plaintext
env var) — geconsistent met de rest van deze app, niet apart verzwakt. Wie
toegang heeft tot `backups/` of het databasebestand, heeft ook de sleutel.
Beperk dus wie bij de droplet/back-upmap kan; overweeg sleutelrotatie als
die toegang ooit breder wordt dan het kleine team waarvoor deze app is
gebouwd (zie ook de sectie over autorisatie hierboven — dezelfde
overweging geldt hier).

## Nieuwe retailer toevoegen

1. Upload een bestand van de retailer: onbekend ⇒ **PROFIEL NODIG** in de
   importlog, mét de gesniffte kolommen als startinformatie.
2. Deel het échte aanleverbestand; de parser wordt in dit Claude
   Code-project gebouwd (ingebouwde parser voor gepivoteerde formaten, of
   een JSON-profiel in `profiles/` voor een plat bestand) en getest tegen
   dat bestand — reconciliatie met de totalen in het bestand incluis.
3. Na de update: bestand opnieuw uploaden ⇒ herkend en ingelezen; alle
   schermen passen zich automatisch aan de capabilities aan.

## Acceptatiecriteria (PROMPT.md §8)

1. ✅ Nieuwe retailer = één profiel — bewezen door `test_fifth_retailer_pure_profile`.
2. ✅ ICI toont merkniveau + maandniveau mét labels; Etos omzet/winkel = SCHATTING.
3. ✅ Seed herkent vier bestanden automatisch; Douglas ⇒ PROFIEL NODIG (assert in seed.py).
4. ✅ Atomair: `test_import_atomic_one_bad_row_zero_facts`.
5. ✅ Uplift stabiel na herimport van bevestigde actieperiode: `test_uplift_stable_after_reimport_of_confirmed_period`.
6. ✅ pytest dekt capability-afleiding, 4 terugvalregels, periodeformaten, komma/punt-decimalen, detectie incl. conflicten.
7. ✅ Visuele steekproef via Playwright-screenshots (radar, dashboard, parser, lege staat Douglas).

Bekende beperkingen: mailregels zijn CRUD-stubs (geen echte poller aan de
console gekoppeld); contractanalyse vereist `ANTHROPIC_API_KEY` (zonder
sleutel werkt de rest van de app, maar geeft een upload een nette 422); The
Seasons-font is de demo-versie (alleen basis-ASCII — koop de licentie voor
productie); `react-router-dom` heeft een moderate open-redirect-CVE die
alleen met een major-versiebump (v6 → v7) op te lossen is — bewust niet
blind doorgevoerd, de navigatie in deze app is toch al een vaste,
interne enum-set (retailer-id's + schermnamen), dus de praktische
exploiteerbaarheid is laag; `npm audit` volgen als dit ooit verandert.

**Tests op échte retailerbestanden.** Een deel van de suite verankert de
cijfers aan echte aanleverbestanden (exacte merktotalen over 4566 regels, de
ICI-decompositie tegen de auditcijfers). Die bestanden staan **niet** in de
repo — het is commercieel gevoelige verkoopdata. Zonder die bestanden slaan
die tests over; dat is precies waarom een groene CI-run ze eerst stilzwijgend
oversloeg. Om ze wél af te dwingen:

```bash
CONSOLE_FIXTURES_DIR=/pad/naar/de/bestanden \
CONSOLE_REAL_FIXTURES=1 python -m pytest -q tests
```

Ontbreekt er dan één, dan faalt de run luid in plaats van stil over te slaan.
Zie `tests/echte_bestanden.py`.

Frontend heeft sinds kort ook geautomatiseerde tests (Vitest +
Testing Library, `npm test` in `console/frontend`, draait mee in CI):
`src/api.ts` (foutafhandeling — het kanaal waar élke foutmelding in de app
doorheen loopt) en de `Uitleg`-popover. Dekking is nog beperkt tot deze
kern; de rest van de UI leunt op `tsc`/`vite build` + handmatige controle.
