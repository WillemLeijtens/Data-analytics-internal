#!/bin/sh
# Dagelijkse back-up van beide SQLite-databases.
#
# sqlite3 .backup in plaats van cp: een kopie met cp tijdens een schrijvende
# import levert een half bestand op (WAL-modus schrijft in een tweede bestand).
# .backup neemt een consistente momentopname, ook onder belasting.
#
# Draait als eigen container (service `backup` in docker-compose.yml) en
# controleert elk uur of de back-up van vandaag er al is. Zo hoeft er geen
# cron op de droplet te staan en overleeft het schema een herstart.
set -eu

BEWAARDAGEN="${BACKUP_KEEP_DAYS:-14}"
DOEL=/backups

maak_backup() {
    bron="$1"
    naam="$2"
    if [ ! -f "$bron" ]; then
        # LUID melden, niet stilzwijgend overslaan. Deze regel stond er eerst
        # als `|| return 0`, en daardoor bleef een verkeerd pad maandenlang
        # onopgemerkt: er kwam geen fout, er kwam alleen geen back-up.
        echo "[backup] WAARSCHUWING: $bron bestaat niet — GEEN back-up van $naam" >&2
        return 0
    fi
    stempel=$(date -u +%Y%m%d)
    uit="$DOEL/$naam-$stempel.db"
    [ -f "$uit" ] && return 0                     # vandaag al gedaan
    tmp="$uit.bezig"
    if sqlite3 "$bron" ".backup '$tmp'"; then
        # Controleer de kopie vóór hij de definitieve naam krijgt: een
        # onleesbare back-up die er wél staat is gevaarlijker dan geen.
        if [ "$(sqlite3 "$tmp" 'PRAGMA integrity_check;')" = "ok" ]; then
            mv "$tmp" "$uit"
            echo "[backup] $uit ($(du -h "$uit" | cut -f1))"
        else
            rm -f "$tmp"
            echo "[backup] MISLUKT: integriteitscontrole op $bron faalde" >&2
            return 1
        fi
    else
        rm -f "$tmp"
        echo "[backup] MISLUKT: kon $bron niet kopieren" >&2
        echo "[backup]   Staat de bronmap als ':ro' in docker-compose.yml? Een" >&2
        echo "[backup]   WAL-database heeft schrijfrechten nodig om te kunnen" >&2
        echo "[backup]   worden geopend, ook om alleen te lezen." >&2
        return 1
    fi
    # Opruimen: alles ouder dan BEWAARDAGEN weg.
    find "$DOEL" -name "$naam-*.db" -type f -mtime "+$BEWAARDAGEN" -delete
}

mkdir -p "$DOEL"
while true; do
    maak_backup /data/console/console.db console || true
    maak_backup /data/streamlit/analytics.db analytics || true
    sleep 3600
done
