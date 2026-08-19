#!/bin/bash
# Waarom start de stack niet? — één read-only overzicht.
#
# Aanleiding: een deploy waarbij Caddy poort 443 niet kreeg ("port is already
# allocated") en `curl localhost:8010/healthz` niets teruggaf. Dat tweede was
# geen storing maar een verkeerd adres: de console publiceert op
# ${CONSOLE_BIND}:${CONSOLE_PORT}, en staat daar een privé-adres, dan luistert
# loopback terecht niet. Dit script kijkt daarom naar het ECHTE adres in
# plaats van naar een aangenomen localhost.
#
# Dit script leest alleen; het start, stopt en wijzigt niets. De conclusies
# staan onderaan, met per bevinding wat je eraan doet.
#
# Gebruik:  bash deploy/diagnose.sh     (vanuit de repomap; sudo mag, hoeft niet)

# Bewust GEEN `set -e`: een mislukte check is hier de uitkomst, niet een
# reden om te stoppen. Wel -u, zodat een typefout in een variabele opvalt.
set -u

BEVINDINGEN=()
meld() { BEVINDINGEN+=("$1"); }
kop() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

cd "$(dirname "$0")/.." || exit 1
REPO=$(pwd)
echo "Repo: $REPO"
echo "Host: $(hostname)  —  $(date '+%Y-%m-%d %H:%M:%S %Z')"

# ---------------------------------------------------------------- docker ---
if ! command -v docker >/dev/null 2>&1; then
    echo
    echo "Docker is hier niet geïnstalleerd — dit script hoort op de droplet"
    echo "te draaien, niet op een werkplek zonder Docker."
    exit 1
fi

# `docker compose` (plugin) of de losse `docker-compose`: beide komen voor.
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo
    echo "Geen 'docker compose' of 'docker-compose' gevonden."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo
    echo "De Docker-daemon antwoordt niet (of deze gebruiker mag er niet bij)."
    echo "Probeer het opnieuw met sudo, of: sudo systemctl status docker"
    exit 1
fi

# ------------------------------------------------------------- containers ---
kop "Containers"
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

# Health komt uit de HEALTHCHECK in console/Dockerfile: die praat met de app
# ín de container en is dus onafhankelijk van welk hostadres gepubliceerd is.
CONSOLE_CID=$("${COMPOSE[@]}" ps -q console 2>/dev/null | head -n1)
if [ -n "$CONSOLE_CID" ]; then
    STATUS=$(docker inspect --format '{{.State.Status}}' "$CONSOLE_CID" 2>/dev/null)
    HEALTH=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}geen healthcheck{{end}}' "$CONSOLE_CID" 2>/dev/null)
    RESTARTS=$(docker inspect --format '{{.RestartCount}}' "$CONSOLE_CID" 2>/dev/null)
    echo
    echo "console: status=$STATUS health=$HEALTH herstarts=$RESTARTS"
    case "$HEALTH" in
        healthy) meld "OK      console draait en is gezond." ;;
        starting) meld "WACHT   console is nog aan het opstarten; draai dit over ~30 s opnieuw." ;;
        *)  meld "PROBLEEM console is niet gezond ($STATUS/$HEALTH). Zie de log onderaan."
            echo
            echo "-- laatste 30 regels van de console-log --"
            "${COMPOSE[@]}" logs --tail=30 console 2>&1 | sed 's/^/   /'
            ;;
    esac
else
    meld "PROBLEEM er draait geen console-container in dit compose-project."
fi

# ------------------------------------------------------------- poorten 80/443 ---
kop "Wie heeft poort 80 en 443?"
if command -v ss >/dev/null 2>&1; then
    # -p toont het proces alleen als root; anders blijven de kolommen leeg en
    # lijkt het net of niemand luistert. Daarom expliciet melden.
    POORTEN=$(ss -tlnp '( sport = :80 or sport = :443 )' 2>/dev/null | tail -n +2)
    if [ -z "$POORTEN" ]; then
        echo "Niemand luistert op 80 of 443."
    else
        echo "$POORTEN"
        if [ "$(id -u)" -ne 0 ] && ! echo "$POORTEN" | grep -q 'users:'; then
            echo
            echo "(Procesnamen ontbreken omdat dit zonder root draait —"
            echo " herhaal met: sudo bash deploy/diagnose.sh)"
        fi
    fi
else
    echo "'ss' niet gevonden; sla deze check over."
    POORTEN=""
fi

# Welke containers claimen 443? Meer dan één betekent een conflict; nul terwijl
# er wél iets luistert wijst op een hostproces (nginx) of een verweesde
# docker-proxy na een halve herstart.
CLAIMERS=$(docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' | grep ':443->' )
# Onze eigen caddy, om "van ons" van "van een ander project" te onderscheiden.
ONZE_CADDY=$("${COMPOSE[@]}" ps --format '{{.Name}}' caddy 2>/dev/null | head -n1)
echo
if [ -n "$CLAIMERS" ]; then
    echo "Draaiende containers die 443 claimen:"
    echo "$CLAIMERS" | sed 's/^/   /'
    VREEMD=$(echo "$CLAIMERS" | cut -f1 | grep -vx "${ONZE_CADDY:-__geen__}")
    if [ -n "$VREEMD" ]; then
        # Dit is de klassieke val: twee checkouts, twee projectnamen, en
        # compose stopt de container van het andere project niet.
        meld "PROBLEEM 443 is bezet door een container buiten dit project: $(echo "$VREEMD" | paste -sd', ' -). Daarom start onze caddy niet. Lees eerst de sectie 'Compose-projecten' hieronder — de andere map heeft zijn eigen database."
    elif [ "$(echo "$CLAIMERS" | wc -l)" -gt 1 ]; then
        meld "PROBLEEM meer dan één draaiende container claimt 443 — zie de lijst hierboven."
    fi
else
    echo "Geen enkele container claimt 443."
    if echo "$POORTEN" | grep -q ':443'; then
        if echo "$POORTEN" | grep -q 'nginx'; then
            meld "PROBLEEM nginx op de host houdt 443 vast; Caddy kan er daarom niet bij. Dit raakt de andere app op deze droplet — overleg vóór je nginx verzet."
        elif echo "$POORTEN" | grep -q 'docker-proxy'; then
            meld "PROBLEEM een docker-proxy houdt 443 vast zonder container erachter (verweesd). Fix: docker compose down && docker compose up -d; helpt dat niet, dan sudo systemctl restart docker."
        else
            meld "PROBLEEM iets op de host houdt 443 vast, geen container. Zie de ss-uitvoer hierboven."
        fi
    fi
fi

# ------------------------------------------------- meerdere compose-projecten ---
# De val: deploy/bootstrap.sh checkt uit naar /opt/Data-analytics-internal,
# terwijl er ook een kopie in ~/analytics kan staan. Twee projectnamen ⇒
# compose stopt de container van de ánder niet, en ze vechten om 443.
kop "Compose-projecten op deze host"
PROJECTEN=$(docker ps -a --format '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}' \
    | grep -v '^\s*$' | sort -u)
if [ -z "$PROJECTEN" ]; then
    echo "Geen compose-containers gevonden."
else
    echo "$PROJECTEN" | sed 's/^/   /'
    AANTAL_P=$(echo "$PROJECTEN" | awk -F'\t' 'NF>1 && $1!="" {print $1}' | sort -u | wc -l)
    if [ "$AANTAL_P" -gt 1 ]; then
        echo
        echo "Meer dan één project. Databases per map (nieuwste = waarschijnlijk de echte):"
        GEVONDEN=0
        while IFS=$'\t' read -r _naam dir; do
            [ -n "${dir:-}" ] || continue
            for db in "$dir/console/data/console.db" "$dir/data/analytics.db"; do
                if [ -f "$db" ]; then
                    printf '   %s  %s\n' "$(date -r "$db" '+%Y-%m-%d %H:%M')" "$db"
                    GEVONDEN=1
                fi
            done
        done <<< "$PROJECTEN"
        [ "$GEVONDEN" -eq 0 ] && echo "   (geen databases leesbaar vanaf hier — kijk zelf in beide mappen)"
        meld "LET OP  er staan meerdere compose-projecten op deze host. Sluit de verkeerde NIET blind af: elke map heeft zijn eigen database. Vergelijk de datums hierboven eerst."
    fi
fi

# ----------------------------------------------------------- console-adres ---
kop "Console: het echte adres"
ADRES=$("${COMPOSE[@]}" port console 8000 2>/dev/null | head -n1)
if [ -z "$ADRES" ]; then
    echo "Compose meldt geen gepubliceerde poort voor console:8000."
else
    echo "Gepubliceerd op: $ADRES"
    BIND=$(grep -E '^CONSOLE_BIND=' .env 2>/dev/null | cut -d= -f2-)
    [ -n "${BIND:-}" ] && echo "CONSOLE_BIND in .env: $BIND"
    case "$ADRES" in
        127.0.0.1:*|localhost:*) : ;;
        *) meld "LET OP  de console luistert op $ADRES, niet op localhost. Gebruik dat adres in curl-commando's en in de gateway-registratie." ;;
    esac
    if command -v curl >/dev/null 2>&1; then
        echo
        # -sS in plaats van -s: geen voortgangsbalk, maar de FOUT wel tonen.
        # Kaal `curl -s` was precies wat de verwarring veroorzaakte — een
        # mislukte verbinding zag eruit als een leeg antwoord.
        if ANTWOORD=$(curl -fsS --connect-timeout 3 --max-time 5 "http://$ADRES/healthz" 2>&1); then
            echo "healthz: $ANTWOORD"
            meld "OK      healthz antwoordt op http://$ADRES/healthz"
        else
            echo "healthz mislukt: $ANTWOORD"
            meld "PROBLEEM healthz antwoordt niet op http://$ADRES/healthz — zie de console-log hierboven."
        fi
    else
        echo "(curl niet gevonden; sla de healthcheck over)"
    fi
fi

# ------------------------------------------------------------- herstart ----
if [ -f /var/run/reboot-required ]; then
    kop "Openstaande herstart"
    cat /var/run/reboot-required
    [ -f /var/run/reboot-required.pkgs ] && sed 's/^/   /' /var/run/reboot-required.pkgs
    meld "LET OP  deze host wacht op een herstart. Dat verklaart onder meer een verweesde docker-proxy op een poort. Plan hem op een rustig moment."
fi

# ------------------------------------------------------------- conclusie ---
kop "Conclusie"
if [ ${#BEVINDINGEN[@]} -eq 0 ]; then
    echo "Geen bijzonderheden gevonden."
else
    printf '%s\n' "${BEVINDINGEN[@]}"
fi
echo
echo "Dit script heeft niets gewijzigd."
