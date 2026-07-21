#!/bin/bash
# One-shot droplet bootstrap: installs Docker if missing, sets up the .env
# file if missing, builds and starts the app, then prints status. Safe to
# re-run — every step is idempotent and none of it touches other
# services already running on the host (e.g. nginx on :80, other apps).
set -euo pipefail

REPO_DIR="/opt/Data-analytics-internal"
BRANCH="claude/outlook-attachment-analytics-g14jvk"
REPO_URL="https://github.com/WillemLeijtens/Data-analytics-internal.git"

echo "== 1/5: Docker =="
if ! command -v docker >/dev/null 2>&1; then
    echo "Docker not found, installing..."
    curl -fsSL https://get.docker.com | sh
else
    echo "Docker already installed, skipping."
fi

echo "== 2/5: Repo =="
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "Cloning repo into $REPO_DIR..."
    git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"

echo "== 3/5: Password =="
if [ ! -f .env ]; then
    if [ -n "${STREAMLIT_APP_PASSWORD:-}" ]; then
        echo "STREAMLIT_APP_PASSWORD=${STREAMLIT_APP_PASSWORD}" > .env
        echo "Wrote .env from STREAMLIT_APP_PASSWORD env var."
    else
        GENERATED_PW=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)
        echo "STREAMLIT_APP_PASSWORD=${GENERATED_PW}" > .env
        echo ""
        echo "!!! No password provided, generated one for you: ${GENERATED_PW}"
        echo "!!! Save it now — it will not be shown again by this script."
        echo ""
    fi
else
    echo ".env already exists, leaving your existing password as-is."
fi

echo "== 4/5: Build and start =="
docker compose up -d --build

echo "== 5/5: Status =="
echo "--- our containers ---"
docker compose ps
echo "--- all containers (checking nothing else was disturbed) ---"
docker ps -a
echo "--- listening ports ---"
ss -tlnp 2>/dev/null || sudo ss -tlnp

echo ""
echo "Done. App should be reachable at: https://$(curl -s -4 ifconfig.me || echo '<droplet-ip>')"
echo "(browser will warn about the self-signed cert once — that's expected)"
