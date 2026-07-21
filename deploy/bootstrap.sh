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

# Determine a resolvable hostname for TLS. Browsers/curl send no SNI for a
# bare IP, so Caddy can't serve a cert for one — we use a free sslip.io
# hostname (<ip-with-dashes>.sslip.io) that resolves to the droplet IP.
ip_to_sslip() { echo "$(echo "$1" | tr '.' '-').sslip.io"; }

CURRENT_SITE=$(grep '^SITE_ADDRESS=' .env | cut -d= -f2- || true)
if echo "$CURRENT_SITE" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    # Existing value is a bare IP from an earlier run — migrate it.
    NEW_SITE=$(ip_to_sslip "$CURRENT_SITE")
    sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=${NEW_SITE}|" .env
    echo "Migrated SITE_ADDRESS from bare IP to ${NEW_SITE}."
elif [ -z "$CURRENT_SITE" ]; then
    if [ -n "${SITE_ADDRESS:-}" ]; then
        NEW_SITE="${SITE_ADDRESS}"
    else
        DETECTED_IP=$(curl -s -4 --max-time 5 ifconfig.me || true)
        if [ -n "$DETECTED_IP" ]; then
            NEW_SITE=$(ip_to_sslip "$DETECTED_IP")
        else
            NEW_SITE=""
        fi
    fi
    if [ -n "$NEW_SITE" ]; then
        echo "SITE_ADDRESS=${NEW_SITE}" >> .env
        echo "Wrote SITE_ADDRESS=${NEW_SITE}."
    else
        echo "Could not determine SITE_ADDRESS — set it manually in .env, then re-run."
    fi
else
    echo "SITE_ADDRESS already set to a hostname (${CURRENT_SITE}), leaving as-is."
fi

echo "== 4/6: (TLS handled automatically by Caddy via Let's Encrypt) =="

echo "== 5/6: Build and start =="
docker compose up -d --build --force-recreate

echo "== 6/6: Status =="
echo "--- our containers ---"
docker compose ps
echo "--- all containers (checking nothing else was disturbed) ---"
docker ps -a
echo "--- listening ports ---"
ss -tlnp 2>/dev/null || sudo ss -tlnp

FINAL_SITE=$(grep '^SITE_ADDRESS=' .env | cut -d= -f2- || true)
echo ""
echo "Done. App should be reachable at: https://${FINAL_SITE:-<site-address>}"
echo "Caddy fetches a Let's Encrypt certificate on first request — the very"
echo "first load may take 10-30s while that happens. After that the padlock"
echo "should be green (trusted), no warning."
