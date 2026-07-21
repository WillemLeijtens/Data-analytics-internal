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

echo "== 3/5: Password + site address =="
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

if ! grep -q '^SITE_ADDRESS=' .env; then
    DETECTED_IP=$(curl -s -4 --max-time 5 ifconfig.me || true)
    if [ -n "${SITE_ADDRESS:-}" ]; then
        echo "SITE_ADDRESS=${SITE_ADDRESS}" >> .env
        echo "Wrote SITE_ADDRESS from env var (${SITE_ADDRESS})."
    elif [ -n "$DETECTED_IP" ]; then
        echo "SITE_ADDRESS=${DETECTED_IP}" >> .env
        echo "Wrote SITE_ADDRESS from detected public IP (${DETECTED_IP})."
    else
        echo "Could not auto-detect public IP — Caddy will fall back to the"
        echo "default baked into the Caddyfile. Set SITE_ADDRESS in .env"
        echo "manually if that's wrong for this droplet, then re-run."
    fi
else
    echo "SITE_ADDRESS already set in .env, leaving as-is."
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
