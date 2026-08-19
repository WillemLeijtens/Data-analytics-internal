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

echo "== 3/6: Password + site address =="
touch .env

if ! grep -q '^STREAMLIT_APP_PASSWORD=' .env; then
    if [ -n "${STREAMLIT_APP_PASSWORD:-}" ]; then
        echo "STREAMLIT_APP_PASSWORD=${STREAMLIT_APP_PASSWORD}" >> .env
        echo "Wrote STREAMLIT_APP_PASSWORD from env var."
    else
        # head -c32 reads a fixed, finite amount so nothing downstream
        # closes the pipe early — piping straight into `head -c20` from
        # an unbounded /dev/urandom source causes a SIGPIPE that, under
        # `set -o pipefail`, aborts the whole script.
        GENERATED_PW=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-20)
        echo "STREAMLIT_APP_PASSWORD=${GENERATED_PW}" >> .env
        echo ""
        echo "!!! No password provided, generated one for you: ${GENERATED_PW}"
        echo "!!! Save it now — it will not be shown again by this script."
        echo ""
    fi
else
    echo "STREAMLIT_APP_PASSWORD already set in .env, leaving as-is."
fi

# Geen TLS-instellingen meer: de app en de console staan achter het portaal
# (prive-adres + firewallregel voor de gateway + forward-auth), dus er is geen
# publieke ingang op deze droplet die een certificaat nodig heeft.

echo "== 4/6: Toegang =="
echo "APP_BIND/CONSOLE_BIND bepalen waar de diensten luisteren; zonder"
echo "instelling is dat 127.0.0.1. Moet de gateway erbij, zet ze dan op het"
echo "prive-adres van deze droplet — nooit op 0.0.0.0."

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
echo "Klaar. De app en de console luisteren op hun eigen poort; het portaal"
echo "zet ze door en doet de authenticatie. Het echte adres per dienst:"
echo "  docker compose port app 8501"
echo "  docker compose port console 8000"
echo "Loopt er iets niet, draai dan: bash deploy/diagnose.sh"
