#!/bin/bash
# One-shot droplet bootstrap: installs Docker if missing, sets up the .env
# file if missing, builds and starts the app, then prints status. Safe to
# re-run — every step is idempotent and none of it touches other
# services already running on the host (e.g. nginx on :80, other apps).
set -euo pipefail

REPO_DIR="/opt/Data-analytics-internal"
BRANCH="claude/outlook-attachment-analytics-g14jvk"
REPO_URL="https://github.com/WillemLeijtens/Data-analytics-internal.git"

echo "== 1/6: Docker =="
if ! command -v docker >/dev/null 2>&1; then
    echo "Docker not found, installing..."
    curl -fsSL https://get.docker.com | sh
else
    echo "Docker already installed, skipping."
fi

echo "== 2/6: Repo =="
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "Cloning repo into $REPO_DIR..."
    git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"

echo "== 3/6: .env =="
touch .env
# De console draait standaard in gateway-modus (geen eigen inlog; het portaal
# authenticeert), dus er hoeft hier geen wachtwoord gegenereerd te worden.
# Wil je de contractanalyse gebruiken, zet dan ANTHROPIC_API_KEY in .env —
# of vul de sleutel na het starten in via Instellingen in de console zelf.
echo ".env staat klaar. Optioneel: ANTHROPIC_API_KEY voor contractanalyse."

# Geen TLS-instellingen: de console staat achter het portaal (prive-adres +
# firewallregel voor de gateway + forward-auth), dus er is geen publieke
# ingang op deze droplet die een certificaat nodig heeft.

echo "== 4/6: Toegang =="
echo "CONSOLE_BIND bepaalt waar de console luistert; zonder instelling is"
echo "dat 127.0.0.1. Moet de gateway erbij, zet hem dan op het prive-adres"
echo "van deze droplet — nooit op 0.0.0.0."

echo "== 5/6: Build and start =="
docker compose up -d --build --force-recreate

echo "== 6/6: Status =="
echo "--- our containers ---"
docker compose ps
echo "--- all containers (checking nothing else was disturbed) ---"
docker ps -a
echo "--- listening ports ---"
ss -tlnp 2>/dev/null || sudo ss -tlnp

echo ""
echo "Klaar. De console luistert op zijn eigen poort; het portaal zet hem"
echo "door en doet de authenticatie. Het echte adres:"
echo "  docker compose port console 8000"
echo "Loopt er iets niet, draai dan: bash deploy/diagnose.sh"
