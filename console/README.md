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
- **Tests**: pytest voor de parser-engine en fallback-logica (het kritieke
  deel, 31 tests).

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
