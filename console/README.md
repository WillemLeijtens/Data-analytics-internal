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
  geen bannerniveau. **Winkelniveau is optioneel**: dezelfde widget wordt met
  én zonder de kolommen Store/City geëxporteerd. Zit `Store` erin ("ETOS
  BEVERWIJK - 6311"), dan is elke rij een artikel×winkel en opent dezelfde
  winkelanalyse als bij ICI Paris XL; zonder die kolommen blijft het gedrag
  exact als voorheen. De dubbelcontrole gaat dan over artikel×winkel×week —
  zonder de winkel erin zou elke tweede winkel met hetzelfde artikel als
  dubbeling gelden. Een winkel zonder nummer breekt de import af: die is niet
  te volgen over exports heen, en stil doorgaan zou de winkeltelling laten
  zakken zonder dat iemand het merkt. Dit formaat heeft géén totalenrij; de parser
  verifieert daarom fail-closed alles wat het bestand zelf biedt: het
  merkental ("Brand (N)"), het weekbereik ("Fiscal YTD …-…") en per week de
  Ending-datum tegen de ISO-zondag — wijkt Etos ooit af van ISO-weken, dan
  stopt de import in plaats van weken verkeerd te labelen. Elke download is
  een groeiend YTD-bestand: overlappende weken worden vervangen op de
  natuurlijke sleutel, dus herimporteren telt nooit dubbel.
- **Etos: productcategorie via de Class-kolom.** Voegt iemand in de widget de
  kolom `Class` toe ("SHAMPOO - 3", "HAARSTYLING - 186", …), dan laat Etos
  daarbij de aparte `UPC ID`-kolom weg — blijkbaar verdringt de extra
  dimensie die kolom. Het EAN zit dan nog wel als suffix in `UPC Name`
  ("BJORN AXEN COOL BLONDE SH 250 - 120789317 (Sz: )"); de parser haalt het
  daar dan uit. Ontbreekt zowel `UPC ID` als een herkenbaar EAN-suffix, dan
  breekt de import fail-closed af — net als een winkelnaam zonder nummer.
  Een lege `Class`-cel bij een verder geldig product is GEEN fout (in
  tegenstelling tot een onherkenbare winkelnaam): de omzet blijft gewoon
  meetellen, alleen zonder categorie. Andere retailers/parsers laten dit
  veld gewoon `NULL`.

  `categorie` is BEWUST geen pagina-brede filter naast merk/land/formule: het
  aantal winkels is een telling van UNIEKE winkels, en twee losse
  categoriereeksen los bij elkaar optellen zou een winkel die dezelfde week
  beide categorieën verkocht dubbel tellen. Combineren moet dus vóór het
  tellen gebeuren, op de rijen. Daarom zit categorie alleen lokaal in de
  grafiek "Omzet per winkel over tijd" (`TijdlijnBlok`, Dashboard.tsx): een
  "Categorie"-stand naast Per merk/Totaal, met een eigen `MultiChips`-keuze
  die zelfgekozen categorieën samenvoegt tot één lijn (bijv. Shampoo +
  Conditioners → "Wash & Care") via een eigen fetch naar `/dashboard` met
  `categorie=...` — hetzelfde bestaande filter op `dashboard()`, alleen niet
  meer pagina-breed aangeroepen. De merk/land/formule-filters bovenaan
  blijven gewoon van toepassing op die fetch.
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

Levert de feed winkelniveau, dan **vult het instellingenscherm het aantal
zelf in**: geteld uit het importbestand, met de melding "automatisch
ingevuld" en het jaar erbij. Niet handmatig te overschrijven — een afwijkend
getal zou stilletjes winnen in de schermen die het gebruiken. De `winkel`-vlag
van een profiel zegt wat het FORMAAT aankan; `analytics.retailer_caps` toetst
hem aan de geladen feiten, zodat een installatie met alleen oude Etos-exports
niet plotseling "winkelniveau" claimt zonder winkels.

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

### Stille winkels: wanneer heet een winkel gestopt?

Per **winkel x merk**-combinatie, in `engine/analytics.winkelanalyse()`:

1. geen omzet in de laatste periode die de feed levert;
2. er wás eerder omzet — dit jaar of vorig jaar (anders is het geen stop maar
   een winkel die het merk nooit voerde);
3. het aantal periodes sinds de laatste periode mét omzet ligt op of boven de
   **gestopt**-drempel. Zit het daaronder maar op of boven de **let op**-
   drempel, dan verschijnt de regel onder "Let op"; daaronder wordt hij niet
   gemeld.

De gemiste omzet ernaast is wat diezelfde winkel in *dezelfde* periodes vorig
jaar wél verkocht — niet het hele vorige jaar, want dat telt periodes mee die
dit jaar nog moeten komen.

De drempels zijn de **ondergrens**; daarbovenop weegt het **eigen verkoopritme**
van elke winkel×merk mee: de mediane tussenpoos tussen periodes mét omzet (minimaal
drie verkoopperiodes, anders geldt alleen de vloer). Gestopt vergt stilte ≥ 3× dat
ritme, "let op" ≥ 2×. Eén vaste drempel kent dit verschil niet: een winkel die elke
week verkoopt en er drie stilvalt is alarmerender dan een hakkelige verkoper die er
zes niets doet — en een hogere drempel alleen verzwijgt de eerste terwijl hij blijft
ruisen bij de tweede. Op de echte Etos-weekdata: 363 → 102 "gestopte" regels op de
standaardvloer, puur door de ritmefilter.

**Gemist** blijft gebaseerd op dezelfde periodes vorig jaar; is dat jaar niet geladen
(Etos begon in 2026), dan een schatting op het eigen ritme (gemiddelde omzet per
actieve periode ÷ tussenpoos × stilte), op het scherm gemarkeerd met ±. Zonder die
schatting stond de kolom — en de sortering erop — overal op € 0. Elke gemelde rij
draagt zijn weekreeks mee; het scherm toont die als sparkline, zodat abrupt verval te
onderscheiden is van hakkelig verkopen. De tabellen tonen de eerste 25 rijen met een
toon-alles-knop.

Beide drempels zijn **per retailer instelbaar** (Instellingen →
Doelstellingen → Stille winkels; tabel `winkelsignaal_drempels`). Dat is nodig
omdat ze in PERIODES tellen terwijl de oorspronkelijke keuze (1 en 2) in
maanden geredeneerd was. Op de echte Etos-weekexport gaf die standaard 363
"gestopte" winkel/merk-regels; met 4 en 6 blijven er 77 over, met 8 en 13 nog
19. Zonder ingestelde rij blijft 1 en 2 gelden, zodat bestaande installaties
niet ineens andere aantallen tonen.

**Cache-let-op**: deze tabel wordt IN PLAATS bijgewerkt (één rij per retailer).
Tellen en `MAX(rowid)` veranderen daar niet van, dus de analysecache zou een
gewijzigde drempel niet zien. Daarom gaan kleine tabellen (< 200 rijen) op
inhoud mee in de cachesleutel; feitentabellen groeien alleen door inserts en
blijven op tellen. Kosten gemeten op 48k feiten: 2,5 ms per verzoek.

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

### Acties herkennen en beoordelen

`engine/promoties.py` + `analytics.promotions()`. Een actie is een periode waarin de
gemiddelde verkoopprijs onder het normale niveau lag. De index is een gewogen
gemiddelde van **prijsrelatieven** — per artikel de prijs gedeeld door de eigen
jaarmediaan, gewogen met het jaarvolume (≈ 1,0 in een normale week). Dat haalt twee
mixeffecten weg: de *verkoopmix* (het goedkope artikel verkoopt een week meer → de
stukprijs zakt zonder afprijzing) én de *aanwezigheidsmix* (een duur artikel verkoopt
een week niets → een gemiddelde van prijsniveaus zakt zonder afprijzing; op de echte
Etos-data schommelde de gewichtsdekking per week tussen 73% en 97% en verschoof dit
~20% van de vlaggen).

Drie regels bepalen de uitkomst:

1. **De referentie is de mediaan van de niet-bevestigde, volledig geleverde periodes,
   in twee passes.** Pas 1 vlagt tegen die mediaan; pas 2 rekent de definitieve cijfers
   (daling, z-score) met de gevlagde periodes buiten de referentie. Zonder die tweede
   pas zaten niet-bevestigde actieweken nog in de referentie: bij een actierijk merk
   (PATCHOLOGY: 15 van 33 weken) zakt de mediaan mee en blaast de MAD op, wat de
   z-scores drukt.
2. **De drempel wordt afgezet tegen de eigen spreiding.** Naast de vaste drempel uit het
   profiel (5%, ICI 3%) telt een robuuste z-score (MAD × 1,4826): hoeveel keer de
   normale schommeling van dít merk is deze afwijking? De gewone standaardafwijking zou
   juist opgeblazen worden door de uitschieters die we zoeken.
3. **Twee ingangen.** Zakt de hele lijn onder de drempel, dan is het assortimentsbreed.
   Is één artikel met noemenswaardig volume (≥ 20%) afgeprijsd terwijl de rest op prijs
   blijft, dan telt dat apart mee — die gevallen miste de gewogen index, want tien
   artikelen wegen één afprijzing weg.

**Zekerheid (1–5)** is een optelsom van vier waarneembare signalen: prijsdaling t.o.v.
de normale schommeling (max 2), volumereactie, bereik, en volledigheid van de data.
Onvolledige data plafonneert de score op 2. Randgevallen die expliciet geregeld zijn:
een prijs die het hele jaar exact vaststond heeft MAD 0 en dus geen z-score — een
afwijking is dan juist het hárdste bewijs en scoort vol; onder de zes
referentieperiodes is een MAD wankel en is het prijssignaal maximaal één punt waard;
en alleen-staartartikelen leveren géén bereikpunt op. Het is een **vuistregel, geen
kans**; het scherm toont per score welke signalen meetelden, zodat hij na te rekenen
is.

**Eén definitie van "een normale periode"**, gebruikt door zowel de basislijn van de
uplift als het gemiddelde: buiten de telling vallen bevestigde acties, voorgestelde
acties, en periodes die niet volledig geleverd zijn — die laatste zijn geen lage omzet
maar geen waarneming.

**Gemiddelde periodeomzet zonder acties** (Promoties-pagina, per merk × land × formule
plus een merktotaal): het niveau waartegen een actie afgezet hoort te worden. De
uitgesloten periodes staan er met reden bij.

**Uplift** van een bevestigde actie = `(omzet in de actieperiode − basislijn) /
basislijn`, met de basislijn als **mediaan** van de normale periodes van hetzelfde jaar
binnen dezelfde scope. Mediaan en niet gemiddelde, zodat één uitschieter de basislijn
niet optilt; alleen hetzelfde jaar, want een omzetregime van twee jaar terug is geen
referentie. Geen uitspraak bij een lopende periode of bij minder dan drie bruikbare
basisperiodes. De marker op het dashboard haalt zijn uplift uit dezelfde berekening —
twee keer hetzelfde getal uitrekenen loopt vroeg of laat uiteen.

Het merktotaal onder de basisregel is de **som van de scope-gemiddelden**; omdat elke
scope zijn eigen normale-weekverzameling heeft is dat een benadering (som van
gemiddelden ≠ gemiddelde van sommen als de weeksets verschillen) — goed genoeg als
richtgetal, en de scoperegels eronder zijn exact.

Feeds zonder volume of artikelniveau (ICI) kunnen geen stukprijs berekenen. Daar staat
elke periode in de lijst om handmatig aan te vinken; die tellen dan níét als voorstel en
blijven dus gewoon meedoen in het gemiddelde.

Vinkjes in de suggestietabel **slaan zichzelf op** (de PUT is een volledige
vervanging; opeenvolgende saves zijn geketend zodat snel klikken nooit een oudere staat
als laatste laat landen; mislukt een save, dan herstelt een verse load de vinkjes naar
de servertruth). De kaart **"Omzeteffect per promotie"** staat op het dashboard, onder
de trendgrafiek met de actiemarkers, en volgt daar het merkfilter.

Bevestigde acties verschijnen ook als **markering op de trendgrafiek van het dashboard**,
in een eigen kleur (`--promo`) en een eigen vorm (driehoek onder de as, tegenover de
ruit van een mijlpaal) — zodat de twee soorten ook zonder kleur te onderscheiden zijn.
Eigen schuifje, en filterbaar op merk en jaar.

### Rotatie

Stuks in de **huidige maand**, gedeeld door de **geleverde weken** van die
maand en door de winkels van dát artikel. Drie keuzes, elk met een reden:

* **Huidige maand, niet het jaar.** Een artikel dat in het voorjaar goed
  liep en sinds de zomer stilstaat, houdt over het jaar een net gemiddelde
  en valt nergens op. Over de laatste maand valt hij meteen door de mand.
  Welke maand dat is staat in de kolomkop; een ISO-week hoort bij de maand
  van zijn donderdag (`periods.kalendermaand`).
* **Geleverde weken, niet kalenderweken.** Is er van augustus pas twee weken
  binnen, dan wordt door twee gedeeld en niet door 4,33 — anders halveert de
  rotatie van elk artikel zodra een maand begint. Een maandfeed levert één
  periode voor 52/12 weken. Een artikel dat halverwege de maand startte telt
  vanaf zijn eerste week.
* **De winkels van dát artikel.** Twee scenario's, en per regel staat welke
  gebruikt is (`winkels_bron`): een aantal per artikel (Instellingen →
  winkelaantallen per artikel), anders het merkaantal — dan gaan alle
  artikelen van dat merk van hetzelfde winkelbestand uit. Levert de feed
  winkelniveau, dan worden de winkels met omzet geteld in plaats van
  ingesteld. Zonder die vermelding is een winkelaantal uit het scherm niet
  terug te vinden in Instellingen, omdat je op de verkeerde plek kijkt.

Twee remmen op valse delists: onder vier actieve periodes volgt geen oordeel
maar "Te kort geleden geïntroduceerd", en met minder dan twee geleverde weken
in de maand "Nog te weinig weken deze maand" — het cijfer is dan wel te zien.
Nul stuks in de maand heet "Geen verkoop deze maand" en telt gewoon als
delist-kandidaat.

Een wijziging in Instellingen werkt direct door: `retailer_settings` en
`artikel_winkelaantallen` zijn kleine tabellen en gaan op inhoud mee in de
dataversie van de analysecache (`main._data_versie`), dus de analyse wordt
opnieuw gerekend zodra er iets verandert.

### Bevestigen van acties

Een vinkje in de tabel Actiesuggesties slaat zichzelf op. Twee dingen daarin
zijn met opzet zo:

* **Per klik gaat er één wijziging naar de server** (`{"wijzigingen":
  [{merk, land, banner, periode, bevestigd}]}`), niet de hele lijst. Het
  scherm stuurde eerst de complete stand terug, afgeleid uit zijn eigen
  vinkjes. Na elke opslag volgt een verse herlaad (bevestigen verandert de
  uplift, de basisregel en de markers op het dashboard), en die herlaad zette
  de vinkjes terug naar de serverstand van dát moment — zonder de kliks die
  nog in de wachtrij stonden. Het vinkje van zo'n klik klapte dan om, en de
  klik daarna stuurde die achterhaalde stand terug als waarheid. Zo
  verdwenen bevestigingen die niemand had aangeraakt. Met één wijziging per
  klik kan dat niet meer, ook niet met een scherm dat achterloopt. De
  volledige-vervangingsvorm (`{"bevestigd": [...]}`) blijft bestaan voor
  "alles wissen" en voor scripts.
* **Zolang er kliks onderweg zijn, neemt een herlaad de vinkjes niet over.**
  De laatste opslag in de keten doet altijd nog een herlaad, dus de stand
  komt hoe dan ook goed — maar tussentijds wint de gebruiker.

De identiteit van een suggestie komt van de server (`analytics.promo_sleutel`,
JSON over merk/land/formule/periode). Het scherm bouwde die sleutel eerst zelf
als `merk|land|banner|periode` met een lege string voor een ontbrekende
formule; dat is niet injectief, en dan delen twee rijen hetzelfde vinkje.

### Distributie per artikel

Het aantal winkels dat een artikel in een periode **daadwerkelijk verkocht**
heeft. Drie kolommen in de artikelanalyse, en alleen bij retailers die
winkelniveau leveren (`caps["winkel"]`, vandaag Etos) — zonder winkel-ID valt
er niets te tellen en blijven de kolommen wég in plaats van leeg.

* **Distributie** — sparkline van het verloop per periode, dit jaar tegen
  vorig jaar, met het laatste aantal eronder.
* **Distributie YTD vs LYTD** — het gemiddelde aantal verkopende winkels per
  periode, op hetzelfde **vergelijkbare venster** als de omzetdelta (de
  doorsnede van de periodes die beide jaren geleverd zijn voor dat merk). Een
  feed die vorig jaar later begon is geen distributiesprong.
* **Distributie 2 mnd** — de laatste twee kalendermaanden tegen de twee
  daarvoor. Dichter op de actualiteit dan de jaarvergelijking en lang genoeg
  om weekruis te dempen. Een lopende maand mag meedoen omdat dit een
  **gemiddelde per periode** is en geen som: een halve maand drukt het cijfer
  dus niet.

Twee dingen die de definitie scherp houden:

* **Verkocht, niet op het schap.** Een winkel die het artikel wel voert maar
  die week niets verkocht telt niet mee; dat onderscheid staat niet in
  sellout-data, en schapaanwezigheid afleiden zou een getal opleveren dat
  nergens op rust. Bij langzame lopers ligt de echte schapdistributie dus
  hoger. De vergelijking door de tijd blijft wel zuiver — beide kanten meten
  hetzelfde. Dat staat ook in de uitleg bij de kolom.
* **De noemer is het aantal geleverde periodes**, niet het aantal
  kalenderweken. Een periode waarin het merk wél geleverd is maar dit artikel
  niets verkocht telt als 0: dat ís distributieverlies en hoort mee te wegen.

In de conclusie komt dit terug als bevinding: de portefeuillebrede
jaarvergelijking, en de artikelen die over twee maanden minstens 15% van hun
winkels verloren (`conclusie.DISTRIBUTIE_DREMPEL`). Artikelen met minder dan
vijf winkels in de vergelijkingsperiode blijven buiten die melding — van 2 naar
0,7 winkels is -65%, maar het is geen distributieverhaal.

### Winkeltargets

Per merk-land(-formule) is in Instellingen → Doelstellingen een **target per
winkel per periode** in te stellen (`retailer_settings.target_per_winkel`, €).
Dat target komt op twee plekken terug:

* **Kaart "Omzet per winkel"** — achter elke regel van de uitsplitsing, groen
  boven en rood onder de norm. Dat geldt op élke uitsplitsing: zet je hem op
  "Per land", dan telt de landregel de omzet van de merken in dat land al bij
  elkaar op, dus staat de bijbehorende lat daar net zo bij (BE € 120 + € 70 =
  € 190). De opbouw van zo'n regel staat in de hover. Op de merkuitsplitsing
  staat er een schuifje **"Tel op"** boven (standaard aan): één regel met de
  som van de merkregels tegen de som van de merktargets. Eén filiaal voert die
  merken naast elkaar, dus de norm voor dat filiaal is de som van de
  merknormen — pas daartegen is te zien of het target gehaald wordt. Over
  landen heen wordt niet opgeteld: die per-winkel-getallen gaan over
  verschillende winkelbestanden.
* **Grafiek "Omzet per winkel over tijd"** — als streepjeslijn over het
  bovenste paneel, met het bedrag in de tooltip van elke periode (groen/rood).
  De lijn verschijnt alleen als er **één reeks** in beeld is: op Totaal, op
  Categorie, of wanneer er op één merk gefilterd is. Acht streepjeslijnen naast
  acht merklijnen zijn niet meer aan elkaar te koppelen. Ligt de lat boven de
  hoogste gemeten waarde, dan rekt de schaal mee — "niet gehaald" is juist wat
  je dan wilt zien.

**Twee rekenregels**, elk met een reden:

* **Binnen één merk het naar winkels gewogen gemiddelde** van de targets van
  de scopes in beeld. Ligt TWEEZERMAN in 1205 NL-winkels met een target van
  € 50 en in 187 BE-winkels met € 120, dan is de lat op de merkregel € 59,40 —
  want die regel deelt de omzet van beide landen door alle 1392 winkels. Het
  hoogste getal nemen zou 87% van het winkelbestand langs de Belgische lat
  leggen; optellen zou hetzelfde filiaal twee keer een norm geven. Zonder
  bekende winkelaantallen valt het terug op het hoogste getal.
* **Over de merken heen optellen**, om de reden hierboven.

Twee dingen staan er bewust bij:

* **De optelling volgt de filters.** Filter je op één merk, dan is de lat het
  target van dát merk; de som van beide merken zou een norm opleggen voor
  omzet die niet eens in beeld is.
* **Merken zonder ingesteld target worden gemeld**, niet stil overgeslagen.
  Een som over de helft van het assortiment ziet eruit als een harde lat en is
  het niet — die haal je moeiteloos, en dat zegt niets.

Het grote getal op de kaart blijft de omzet van álle merken gedeeld door het
hele winkelbestand. Dat ligt iets **onder** de optelsom zodra een merk in
minder winkels ligt dan het grootste merk: die omzet wordt dan over meer
winkels uitgesmeerd. Allebei kloppen, dus ze staan naast elkaar en niet in
plaats van elkaar.

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

## Conclusie per retailer

Het scherm **Conclusie** (Analyses) vat per retailer samen wat de cijfers
zeggen over omzet, assortiment, winkelontwikkeling en promoties, met concrete
adviezen. Dat gebeurt in twee lagen, om dezelfde reden als bij de
contractanalyse: **het model schrijft de zin, de cijfers blijven
deterministisch**.

1. `engine/conclusie.bevindingen()` haalt de opvallende feiten uit de vier
   bestaande analyses en zet ze om in items met een ernst (rood/oranje/info).
   Die laag rekent zelf niets nieuws uit — hij selecteert — en werkt **zonder
   API-sleutel**. Zonder sleutel toont het scherm alleen de bevindingen, en
   dat is op zichzelf al bruikbaar.
2. Claude krijgt **alléén die bevindingen** (enkele KB's, nooit de ruwe
   reeksen) en schrijft er een samenvatting en hoogstens vier adviezen bij.

Wat de tekst noemt hoort dus in de bevindingen te staan, en die staan eronder
op het scherm — elke zin is terug te leiden tot een cijfer.
`controleer_getallen()` toetst dat na afloop: een getal in de tekst dat
nergens uit volgt, komt als waarschuwing boven de conclusie te staan in plaats
van stil te worden geslikt (net als een onaannemelijke contractdatum). De
`bevindingen` gaan als JSON-momentopname mee de database in, zodat een
conclusie narekenbaar blijft óók nadat de data veranderd is.

**Verversen kost een API-call, dus dat gebeurt alleen als het nodig is.**
`vingerafdruk()` legt de staat van de data van déze retailer vast, zónder
datum erin. Wijkt de huidige vingerafdruk af van die bij het schrijven, dan is
de tekst verouderd en werkt het scherm hem bij zodra je hem opent. Bewust niet
opgehangen aan de analysecache-versie uit `main.py`: die bevat de datum van
vandaag, en dan zou élke nacht elke conclusie van elke retailer herschreven
worden zonder dat er iets veranderd is. En bewust per retailer: een import
voor Kruidvat veroudert de conclusie van Etos niet.

`retailer_conclusies` staat in `_BUITEN_DATAVERSIE` (`main.py`). Een conclusie
is een *gevolg* van de analyses; telde de tabel mee in de dataversie, dan zou
elke opgeslagen conclusie de cache van álle analyses van álle retailers
leegtrekken.

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
