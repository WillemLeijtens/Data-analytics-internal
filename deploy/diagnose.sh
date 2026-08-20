#!/bin/bash
# Waarom werkt de stack niet? — één read-only overzicht.
#
# Aanleiding: een deploy waarbij `curl localhost:8010/healthz` niets teruggaf.
# Dat was geen storing maar een verkeerd adres: de diensten publiceren op
# ${..._BIND}:${..._PORT}, en staat daar een privé-adres, dan luistert loopback
# terecht niet. Dit script kijkt daarom naar het ECHTE adres in plaats van
# naar een aangenomen localhost — en controleert meteen dat geen van onze
# diensten publiek luistert, want alles hoort achter het portaal te staan.
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
    # Alleen ANDERE checkouts van dít project zijn een probleem; de overige
    # apps op deze droplet (bolcom-agent, kadc, …) horen er gewoon te staan.
    # Herkenningspunt: een map met onze databases erin.
    echo
    echo "Checkouts van dit project (aan hun databases herkend):"
    DUBBEL=0
    while IFS=$'\t' read -r _naam dir; do
        [ -n "${dir:-}" ] || continue
        VAN_ONS=0
        for db in "$dir/console/data/console.db" "$dir/data/analytics.db"; do
            if [ -f "$db" ]; then
                printf '   %s  %s\n' "$(date -r "$db" '+%Y-%m-%d %H:%M')" "$db"
                VAN_ONS=1
            fi
        done
        [ "$VAN_ONS" -eq 1 ] && DUBBEL=$((DUBBEL + 1))
    done <<< "$PROJECTEN"
    if [ "$DUBBEL" -eq 0 ]; then
        echo "   (geen databases leesbaar vanaf hier)"
    elif [ "$DUBBEL" -gt 1 ]; then
        meld "LET OP  er staan $DUBBEL checkouts van dit project op deze host, elk met een eigen database. Sluit de verkeerde NIET blind af — vergelijk eerst de datums hierboven."
    fi
fi

# ------------------------------------------------------------- bindingen ---
# Alles loopt via het portaal, dus GEEN van onze diensten hoort op een
# publiek adres te luisteren. Een binding op 0.0.0.0 of op het publieke IP is
# daarom een bevinding, geen detail: dan staan de verkoopcijfers open.
kop "Waar luisteren onze diensten?"
for dienst in console app; do
    case "$dienst" in
        console) poort=8000; pad="/healthz" ;;
        app)     poort=8501; pad="/" ;;
    esac
    ADRES=$("${COMPOSE[@]}" port "$dienst" "$poort" 2>/dev/null | head -n1)
    if [ -z "$ADRES" ]; then
        echo "$dienst: geen gepubliceerde poort"
        continue
    fi
    HOST=${ADRES%:*}
    echo "$dienst: $ADRES"
    case "$HOST" in
        127.0.0.1|localhost|::1) : ;;
        10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*|169.254.*)
            # Prive-adres: precies de bedoeling, de gateway komt hier langs.
            : ;;
        0.0.0.0|::|\[::\])
            meld "PROBLEEM $dienst luistert op $ADRES — dat is elk adres van deze host, dus ook het publieke IP. Zet APP_BIND/CONSOLE_BIND op het prive-adres." ;;
        *)
            meld "PROBLEEM $dienst luistert op $ADRES; dat lijkt geen prive-adres. Alles hoort achter het portaal te staan." ;;
    esac
    if command -v curl >/dev/null 2>&1; then
        # Een paar pogingen: de Streamlit-app heeft na een herstart ~15 s
        # nodig om pandas en altair te laden. Direct na `up -d` meten geeft
        # anders een 000 die op een storing lijkt terwijl hij nog opstart.
        for poging in 1 2 3 4 5; do
            CODE=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 8 "http://$ADRES$pad" 2>/dev/null)
            [ "$CODE" != "000" ] && break
            [ "$poging" -lt 5 ] && sleep 4
        done
        echo "   http://$ADRES$pad -> $CODE"
        case "$CODE" in
            2*|3*) meld "OK      $dienst antwoordt op http://$ADRES$pad ($CODE)." ;;
            000)   meld "PROBLEEM $dienst antwoordt niet op http://$ADRES$pad (5 pogingen over ~20 s). Zie: docker compose logs $dienst" ;;
            *)     meld "LET OP  $dienst antwoordt met $CODE op http://$ADRES$pad." ;;
        esac
    fi
done

CONSOLE_ENV=$(grep -E '^CONSOLE_BIND=' .env 2>/dev/null | cut -d= -f2-)
APP_ENV=$(grep -E '^APP_BIND=' .env 2>/dev/null | cut -d= -f2-)
echo
echo ".env: CONSOLE_BIND=${CONSOLE_ENV:-<niet gezet, valt terug op 127.0.0.1>}"
echo ".env: APP_BIND=${APP_ENV:-<niet gezet, valt terug op 127.0.0.1>}"

# -------------------------------------------------------------- back-ups ---
# De back-up faalde dagenlang zonder dat iemand het zag: de fout stond alleen
# in de containerlog. Daarom hier expliciet kijken of er RECENTE bestanden
# staan, in plaats van of de service draait.
kop "Back-ups"
if [ ! -d backups ]; then
    echo "Geen map 'backups/' in deze checkout."
else
    for naam in console analytics; do
        NIEUWSTE=$(ls -1t "backups/$naam-"*.db 2>/dev/null | head -n1)
        if [ -z "$NIEUWSTE" ]; then
            echo "$naam: GEEN ENKELE back-up"
            meld "PROBLEEM er is geen enkele back-up van de $naam-database. Kijk in: docker compose logs backup"
        else
            OUD_UREN=$(( ( $(date +%s) - $(date -r "$NIEUWSTE" +%s) ) / 3600 ))
            printf '%s: %s (%s uur oud)\n' "$naam" "$NIEUWSTE" "$OUD_UREN"
            if [ "$OUD_UREN" -gt 48 ]; then
                meld "PROBLEEM de nieuwste back-up van $naam is $OUD_UREN uur oud. Kijk in: docker compose logs backup"
            fi
        fi
    done
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
