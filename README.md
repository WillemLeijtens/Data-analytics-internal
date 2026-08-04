# Data Analytics Internal

Internal analytics app for weekly retail sellout data (DWH exports), across
multiple brands, countries, and retail banners.

## Status

**Phase 1 (done):** manual upload of DWH `.xlsx` exports → parse → clean →
store in a normalized SQLite fact table → dashboard with
brand/country/banner filters, YoY/YTD comparisons, per-item sparklines,
promotion analysis, and "last received" / "last analyzed" timestamps.

**Phase 2 (built, needs one mailbox setup step):** automatic mail import — a
poller watches a mailbox for mails whose subject matches a filter, downloads
their `.xlsx` attachments, and runs them through the *same* ingestion
pipeline as a manual upload. Two interchangeable sources: a dedicated
forwarding mailbox over IMAP (recommended — no access to your own mailbox),
or your own mailbox over Microsoft Graph. See "Automatic mail import" below.

## Automatic mail import

The `poller` service (see `docker-compose.yml`) checks a mailbox every 15
minutes, downloads `.xlsx` attachments from mails whose subject matches a
filter, and runs them through the same pipeline as a manual upload. It is
**off by default** and does nothing until you switch it on in Settings. Each
mail+attachment is imported at most once (tracked in `email_imports`), so
restarts and overlapping polls are safe.

Pick one of two sources in **Settings → Automatische import van mail**:

| | A. Forwarding mailbox (IMAP) — *recommended* | B. Your own mailbox (Graph) |
|---|---|---|
| Access | Only a dedicated throwaway mailbox | Read access to your whole mailbox |
| Setup | Outlook rule + IMAP credentials in `.env` | Azure app registration + one-time sign-in |
| Credentials | Mailbox password/app password | OAuth refresh token |
| Provider | Must be **non-Microsoft** (see below) | Any Microsoft mailbox |

### Option A — forwarding mailbox (recommended)

Smallest blast radius: if the credentials leak, they only reach a mailbox
that contains nothing but forwarded reports.

1. Create a **dedicated mailbox** used for nothing else. It must **not** be a
   second mailbox in your own Microsoft 365 tenant — Microsoft disabled
   IMAP-with-password for Exchange Online, so that would need OAuth anyway.
   Use e.g. Gmail with an **App Password** (requires 2FA on that account), or
   a mailbox at your web host.
2. In Outlook, add a **rule**: mails with the report subject → *forward to*
   that mailbox.
3. Put the credentials in `.env` on the droplet and restart:
   ```
   IMAP_HOST=imap.gmail.com
   IMAP_USER=rapporten@example.com
   IMAP_PASSWORD=<app password>
   IMAP_FOLDER=INBOX
   ```
   ```bash
   docker compose up -d --build
   ```
4. In Settings: pick *Doorstuur-mailbox (IMAP)*, set the subject filter, tick
   *Automatische import aan*, save, and use *Nu controleren* to test.

The mailbox is opened **read-only** (`BODY.PEEK`): nothing is marked as read,
moved or deleted.

### Option B — your own mailbox via Microsoft Graph

Auth uses **delegated OAuth (device-code flow)**: you sign in once, then the
refresh token in `data/msal_cache.json` keeps it running unattended. There is
no password/app-password option — Microsoft retired basic auth (IMAP/POP)
for Exchange Online and Outlook.com. The requested scope is `Mail.Read`
only: the importer never modifies or deletes anything in the mailbox.

#### One-time setup

1. **Register an app** at [portal.azure.com](https://portal.azure.com) →
   *Microsoft Entra ID* → *App registrations* → *New registration*:
   - Name: anything (e.g. "Sellout auto-import").
   - Supported account types: whichever matches the mailbox (for a
     work/school account: "Accounts in this organizational directory only").
   - Redirect URI: leave empty.
2. On the new app's **Authentication** page, enable
   *Allow public client flows* → **Yes** (required for the device-code flow).
3. On **API permissions**, add *Microsoft Graph → Delegated → `Mail.Read`*,
   then *Grant admin consent* if your tenant requires it.
4. Copy the **Application (client) ID** (and the **Directory (tenant) ID**)
   into `.env` on the droplet:
   ```
   AZURE_CLIENT_ID=<application-client-id>
   AZURE_TENANT_ID=<directory-tenant-id>   # or: common
   ```
5. Restart: `docker compose up -d --build`.
6. In the app: **Settings → Automatische import uit Outlook** → *Stap 1 —
   start inloggen*, enter the shown code at
   [microsoft.com/devicelogin](https://microsoft.com/devicelogin), then
   *Stap 2 — voltooien*.
7. Set the **subject filter** (e.g. `DWH`), tick **Automatische import aan**,
   and save. Use *Nu controleren* to test immediately.

### Troubleshooting

- *"Inloggen bij de IMAP-mailbox is geweigerd"* — wrong user/password, or you
  used the account password where the provider requires an app password.
- *"Outlook sign-in has expired"* — the refresh token lapsed (poller down for
  a long time, or a conditional-access policy). Redo step 6 of option B.
- Poller logs: `docker compose logs -f poller`.
- A file that fails to parse is logged with status ❌ in Settings and is not
  retried (it won't fix itself); network/auth failures are retried on the
  next poll automatically.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

The SQLite database is created at `data/analytics.db` on first run. Set
`STREAMLIT_APP_PASSWORD` in the environment to require a password before the
app loads (recommended once any real data is in it); without it, the app
runs with no login and shows a warning.

## Deploying — current plan: a Droplet (interim), proper internal web app later

**Now:** run this on a single DigitalOcean Droplet (or any VM you already
have), reachable at `https://<droplet-ip>`. Storage lives on the droplet's
own disk, so history persists across restarts as long as you don't destroy
the droplet.

**Later:** once this is validated, move to a proper internal web app (real
domain, likely SSO instead of a shared password, possibly the Render setup
below or similar) — not built yet, revisit when Phase 1 usage proves out.

### Droplet setup

This repo ships `docker-compose.yml` + `Caddyfile` for this: Caddy
terminates TLS with a **self-signed certificate** (via `tls internal`) and
reverse-proxies to the Streamlit app. A bare IP address can't get a
publicly-trusted certificate (Let's Encrypt requires a domain name), so
your browser will show a one-time "not trusted" warning the first time you
visit — click through (or install Caddy's local CA cert) — the connection
is still encrypted, just not verified by a public authority. Swap in a
real domain + Let's Encrypt later by pointing DNS at the droplet and
replacing `tls internal` with your email/domain in the Caddyfile.

**One-shot setup:** `deploy/bootstrap.sh` does everything below in one
idempotent run — installs Docker if missing, clones/pulls the repo,
generates a password if you don't supply one, builds, starts, and prints
status (including a check that nothing else on the host was disturbed).
Safe to re-run any time (e.g. after a `git pull` to redeploy).

This repo is **private**, so `raw.githubusercontent.com` can't serve the
script directly (it 404s without auth) — clone first, then run it locally:

```bash
git clone https://github.com/WillemLeijtens/Data-analytics-internal.git /opt/Data-analytics-internal
# ^ if prompted for credentials: username = your GitHub username,
#   password = a GitHub Personal Access Token (Settings → Developer
#   settings → Personal access tokens), NOT your account password —
#   GitHub no longer accepts the latter for git operations.
cd /opt/Data-analytics-internal
git checkout claude/outlook-attachment-analytics-g14jvk
bash deploy/bootstrap.sh
```

Or, to set your own password instead of a generated one:
```bash
STREAMLIT_APP_PASSWORD=your-password-here bash deploy/bootstrap.sh
```

**Manual steps**, if you'd rather run them individually:
```bash
# 1. Install Docker + Compose plugin
curl -fsSL https://get.docker.com | sh

# 2. Clone this repo and switch to this branch
git clone https://github.com/WillemLeijtens/Data-analytics-internal.git /opt/Data-analytics-internal
cd /opt/Data-analytics-internal
git checkout claude/outlook-attachment-analytics-g14jvk

# 3. Set your app password (never commit this file)
cp .env.example .env
nano .env   # set STREAMLIT_APP_PASSWORD to a real password

# 4. Build and start (app + Caddy reverse proxy with TLS)
docker compose up -d --build
```
Then open `https://<droplet-ip>` (accept the self-signed cert warning
once). Only port 443 is bound — port 80 is deliberately left alone since
another app's nginx may already be using it on a shared droplet.

`docker-compose.yml` bind-mounts `./data` on the droplet's own disk into
the container, so `analytics.db` survives container restarts and
`docker compose up -d --build` redeploys (pushing new code + rerunning
this command does **not** wipe history). It's only lost if you delete the
droplet or the `data/` directory yourself — back it up periodically
(`scp` the `data/analytics.db` file off the droplet) since a single
droplet has no built-in redundancy.

To redeploy after a code change: `git pull && docker compose up -d --build`.

<details>
<summary>Alternative considered: Render.com (parked for now)</summary>

This repo also includes a `render.yaml` for Render, with a persistent disk
mounted at `/app/data` — useful if you'd rather not manage a VM yourself.
Plain Streamlit Community Cloud was ruled out regardless of host, since its
filesystem resets on every redeploy, wiping historical data. Revisit this
option for the "later" internal-web-app phase if you'd rather not run your
own server long-term.
</details>

## Project layout

- `app/ingestion.py` — parses a DWH export file: reads the metadata block
  (Country/Formula/Brand/Weeks/Date), picks the authoritative sheet (the one
  whose row count matches its own trailing "Total" row), forward-fills the
  merged year-week header, extracts item attributes and per-week
  sales volume/value, and reconciles computed weekly totals against the
  file's own Total row and Total column.
- `app/db.py` — SQLite schema and persistence: `items` (item attributes),
  `fact_sales` (brand/country/banner/sku/year_week grain, append-only
  history), `store_counts` (manually configured, per brand+country+banner,
  with optional per-week overrides), `kpi_definitions` (config-driven KPI
  formulas), `import_log`, `app_meta` (timestamps).
- `app/kpi.py` — safe arithmetic expression evaluator for KPI formulas
  (restricted to `+ - * / ()` over a fixed set of scope variables — no
  arbitrary code execution).
- `app/streamlit_app.py` — the UI: Import, Dashboard, Settings pages.

## Data model

One shared fact table across all brands, not separate databases per brand:

```
fact_sales(brand, country, banner, sku, year_week, sales_volume, sales_value)
```

`banner` is the retail chain/formula code (e.g. `KV` = Kruidvat, `TP` =
Trekpleister) — a dimension distinct from country, both read from each
file's own metadata block (not just the filename).

## Known source-file quirks handled

- Each file has 2 sheets; the second repeats every SKU once per GTIN/PLU
  variant. The first sheet (SKU-grain) is authoritative.
- The bottom "Total" row's SKU-number cell holds a row count, not a SKU —
  excluded from data, used only to validate weekly sums.
- A trailing "Total" column pair (grand total per SKU across all weeks) sits
  after the last real week — excluded from the per-week fact rows.
- Some item-attribute columns share a header label (e.g. two "Size"
  columns) — first occurrence is kept.
- One export can cover **several brands at once**. The metadata block then
  joins them with a semicolon (`Brand: ALESSANDRO;DEPEND GEL IQ`) and only
  the per-row "Brand" column says which brand a row belongs to, so the row's
  own value is authoritative — each brand lands on its own `fact_sales` rows
  and stays connected to its own history.

## Adding a new brand/source format

Ingestion reads brand/country/banner from the file's metadata block, so a
new brand generally needs no code change. If a new export has a
structurally different layout, extend `ingestion.py`'s sheet-selection or
column-detection logic rather than writing a brand-specific pipeline.
