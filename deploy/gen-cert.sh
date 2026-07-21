#!/bin/bash
# Generate a self-signed TLS certificate whose SAN covers the site's IP
# address (and localhost), so browsers get a proper — if untrusted —
# certificate instead of a failed handshake. Idempotent: only regenerates
# if the cert is missing or the IP changed.
set -euo pipefail

CERT_DIR="$(dirname "$0")/../certs"
mkdir -p "$CERT_DIR"
CERT_DIR="$(cd "$CERT_DIR" && pwd)"

IP="${1:-${SITE_ADDRESS:-}}"
if [ -z "$IP" ]; then
    IP=$(curl -s -4 --max-time 5 ifconfig.me || true)
fi
if [ -z "$IP" ]; then
    echo "gen-cert: could not determine IP/site address; pass it as arg 1 or set SITE_ADDRESS" >&2
    exit 1
fi

CRT="$CERT_DIR/site.crt"
KEY="$CERT_DIR/site.key"

# Skip if an existing cert already covers this IP.
if [ -f "$CRT" ] && openssl x509 -in "$CRT" -noout -text 2>/dev/null | grep -qF "IP Address:$IP"; then
    echo "gen-cert: existing certificate already covers $IP, skipping."
    exit 0
fi

echo "gen-cert: generating self-signed certificate for $IP ..."
openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout "$KEY" -out "$CRT" \
    -subj "/CN=$IP" \
    -addext "subjectAltName=IP:$IP,DNS:localhost,IP:127.0.0.1"

chmod 644 "$CRT"
chmod 600 "$KEY"
echo "gen-cert: wrote $CRT and $KEY"
