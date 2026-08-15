# Retailer Console

Multi-retailer herbouw van de interne "Data analyse agent", naar het
high-fidelity ontwerp uit `design/` (By Leijtens design system). Eén canoniek
datamodel, N parser-profielen: een retailer toevoegen is één JSON-profiel
publiceren — er zit geen retailer-specifieke code in analyses of UI.

De bestaande Streamlit-app in `app/` blijft ongewijzigd draaien; deze console
staat er los naast tot de overstap gemaakt wordt.

## Starten

```bash
cd console
make seed   # voorbeelddata door de echte import-pipeline
make dev    # backend :8000 + frontend :5173
```

## Deployen op de droplet

De console draait als **één extra container** naast de bestaande
Streamlit-app (eigen image, eigen database in `console/data/`), met een eigen
hostnaam via Caddy. De bestaande app blijft ongewijzigd op de root staan.

Toegang loopt via het **portaal** (privé-adres + firewallregel voor de
gateway + forward-auth), net als bij de andere apps. De console wordt dus
**niet** op het publieke IP gepubliceerd en staat bewust niet in de Caddy
van deze repo.

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
docker compose up -d --build console      # bindt op 127.0.0.1:8010 -> :8000
curl -fsS localhost:8010/healthz
```

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

Een eigen hostnaam in plaats van een subpad (`/console`) is bewust: de SPA
verwijst naar absolute `/assets`- en `/api`-paden, die onder een prefix
zouden breken. `sslip.io` resolvet elk voorvoegsel, dus dit werkt zonder
DNS-registratie; Caddy haalt automatisch een certificaat op. Andere
hostnaam? Zet `CONSOLE_ADDRESS` in `.env`.

Bij de **eerste start** laadt de console alleen de parser-profielen voor de
retailers waarvan het aanleverformaat bekend is (Kruidvat DWH, ICI Paris XL
maandrapport). Verder is een verse installatie **leeg**: geen winkelaantallen,
targets, mailregels, SharePoint-koppeling of contractdocumenten. Dat is
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
      contracts.py   # ContractSource-interface + mock (SharePoint = TODO)
    main.py          # FastAPI-endpoints
    seed.py          # seeds in ECHT formaat door de echte pipeline
  frontend/          # tabs boven, donkere sidebar, 9 schermen
  profiles/          # de vier handoff-profielen (kruidvat/etos/ici/douglas)
  seed/              # stand-ins + contracts.json
  design/            # tokens, fonts, logo (referentie)
```

### Parser-profielen

Schema: zie `profiles/*.json` (PROMPT.md §3). Kernregels:

- **Capabilities worden afgeleid** uit mapping + constants, nergens opgeslagen.
- **Detectie**: filename-glob, met sheet/verplichte-headers als tiebreak.
  Nul of meerdere matches ⇒ status **PROFIEL NODIG**; de gebruiker mapt
  éénmalig kolommen in het Parser-scherm. Concept-profielen doen nooit mee.
- **Versionering**: publiceren = nieuwe versie; oude versies blijven leesbaar;
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
Instellingen (label `SCHATTING`).

### Winkelanalyse (retailers mét winkelniveau)

Op het dashboard: winkels die dit jaar stilgevallen zijn (wél eerder omzet,
daarna **twee of meer** maanden niets) met de omzet van vorig jaar als maat
voor de gemiste omzet, plus een actiepunt richting de category manager. Eén
lege maand is bij een langzaamlopend merk ruis; die winkels staan apart
onder "Let op" en tellen niet mee in de gemiste omzet. En
omgekeerd de nieuwe winkels: vorig jaar geen omzet, dit jaar wel. Per
winkel én merk, want een filiaal kan het ene merk laten vallen en het
andere houden.

## Nieuwe retailer toevoegen

1. Open **Parser** → "Nieuw profiel" (of upload een bestand: onbekend ⇒
   PROFIEL NODIG in de importlog).
2. Vul detectie (naam-patroon, sheet, header-rij), periodiciteit en de
   kolom-mapping in; `volume` en `omzet` zijn verplicht om te publiceren.
3. "Testen op bestand" tegen een echt voorbeeldbestand.
4. "Profiel publiceren" — alle schermen passen zich automatisch aan de
   afgeleide capabilities aan. Geen code nodig.

## Acceptatiecriteria (PROMPT.md §8)

1. ✅ Nieuwe retailer = één profiel — bewezen door `test_fifth_retailer_pure_profile`.
2. ✅ ICI toont merkniveau + maandniveau mét labels; Etos omzet/winkel = SCHATTING.
3. ✅ Seed herkent vier bestanden automatisch; Douglas ⇒ PROFIEL NODIG (assert in seed.py).
4. ✅ Atomair: `test_import_atomic_one_bad_row_zero_facts`.
5. ✅ Uplift stabiel na herimport van bevestigde actieperiode: `test_uplift_stable_after_reimport_of_confirmed_period`.
6. ✅ pytest dekt capability-afleiding, 4 terugvalregels, periodeformaten, komma/punt-decimalen, detectie incl. conflicten.
7. ✅ Visuele steekproef via Playwright-screenshots (radar, dashboard, parser, lege staat Douglas).

Bekende beperkingen: mailregels zijn CRUD-stubs (geen echte poller aan de
console gekoppeld); SharePoint is een mock (`contracts.py`); The Seasons-font
is de demo-versie (alleen basis-ASCII — koop de licentie voor productie).
