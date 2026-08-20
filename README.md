# Data Analytics Internal

Interne analyse van wekelijkse retail-selloutdata (DWH-exports), over meerdere
merken, landen en retailformules.

De applicatie is de **Retailer Console** in [`console/`](console/) — een
FastAPI-backend met een React/TypeScript-SPA. Alle inhoudelijke documentatie
(architectuur, parsers, datamodel, nieuwe retailer toevoegen, toegangscontrole)
staat in **[`console/README.md`](console/README.md)**.

> **Historie:** tot augustus 2026 draaide hier ook een oudere Streamlit-app
> (`app/`) met een eigen database (`data/analytics.db`) en een mailpoller. Die
> is verwijderd nu de console zijn taak volledig heeft overgenomen. De code is
> op te vragen uit de git-historie; zie "Wat er met de oude data gebeurt"
> hieronder als je die database nog nodig hebt.

## Wat er in deze repo staat

| Pad | Wat |
|---|---|
| `console/` | De applicatie: backend, frontend, parsers, tests, eigen README |
| `deploy/` | Droplet-scripts: `bootstrap.sh`, `diagnose.sh`, `backup.sh`, `restore.md` |
| `docker-compose.yml` | Twee services: `console` en `backup` |
| `.env.example` | Alle instelbare omgevingsvariabelen, met standaardwaarden |

## Draaien op de droplet

Alles loopt achter het interne **portaal**: de console luistert alleen op het
privé-adres van de droplet, het portaal doet TLS en authenticatie. Er staat
niets van deze repo op het publieke IP en er zit geen eigen reverse proxy meer
in.

```bash
cd /root/analytics          # of waar de checkout staat
git checkout main && git pull
docker compose up -d --build
```

Eerste keer op een verse droplet: `bash deploy/bootstrap.sh` (installeert
Docker, zet `.env` klaar, bouwt en start).

Loopt er iets niet: `bash deploy/diagnose.sh`. Dat script leest alleen — het
start, stopt of wijzigt niets — en meldt waar de console luistert, of hij
antwoordt op `/healthz`, of er meerdere checkouts van dit project op de host
draaien (elk met een eigen database), en of de back-ups actueel zijn.

## Back-ups

De `backup`-service maakt dagelijks een geverifieerde kopie van
`console/data/console.db` naar `backups/`, 14 dagen bewaard. Procedure en
herstelstappen: [`deploy/restore.md`](deploy/restore.md).

## Wat er met de oude Streamlit-data gebeurt

Het verwijderen van de app raakt **de database op de droplet niet**:
`data/analytics.db` staat op de serverdisk en is nooit in git meegegaan
(`.gitignore`). Wil je die historie behouden, archiveer het bestand dan zelf
(bijvoorbeeld naar SharePoint) vóór je de map opruimt. De `backup`-service
maakt er geen nieuwe kopieën meer van; bestaande `backups/analytics-*.db`
blijven staan tot je ze weghaalt.

De console heeft een eigen database (`console/data/console.db`) en een eigen
importpijplijn — bronbestanden opnieuw importeren via het Import-scherm levert
dezelfde cijfers op, want de parsers zijn deterministisch.

## CI

`.github/workflows/ci.yml` draait op elke pull request en push naar `main`:
de backend-testsuite (`pytest`), de frontend-tests (`vitest`) en een
productiebuild van de frontend (`tsc` + `vite build`).
