# Back-up en herstel

Beide databases worden dagelijks gekopieerd door de `backup`-service in
`docker-compose.yml`. Er is geen cron op de droplet nodig: de container kijkt
elk uur of de back-up van vandaag er al is en maakt hem anders alsnog.

| wat | waar in de container | back-upnaam |
|---|---|---|
| Retailer Console | `console/data/console.db` | `backups/console-JJJJMMDD.db` |
| Streamlit-app | `data/sellout.db` | `backups/sellout-JJJJMMDD.db` |

- **Bewaartermijn**: 14 dagen (`BACKUP_KEEP_DAYS` in `.env` om af te wijken).
- **Methode**: `sqlite3 .backup`, geen `cp`. Een `cp` tijdens een lopende
  import levert een half bestand op — de databases draaien in WAL-modus, dus
  een deel van de data staat op dat moment in een tweede bestand.
- **Controle**: elke kopie krijgt een `PRAGMA integrity_check` vóór hij zijn
  definitieve naam krijgt. Faalt die, dan wordt de kopie weggegooid en
  verschijnt er `[backup] MISLUKT` in `docker compose logs backup`. Een
  onleesbare back-up die er wél staat is gevaarlijker dan geen back-up.

## Controleren dat het werkt

```bash
docker compose logs --tail 20 backup     # [backup] /backups/console-JJJJMMDD.db (968K)
ls -la backups/
```

Staat er na een dag niets, dan draait de service niet — start hem met
`docker compose up -d backup`.

## Herstellen

```bash
cd /root/analytics
docker compose stop console                       # schrijvers eerst stil
cp console/data/console.db console/data/console.db.kapot   # bewaar het origineel
cp backups/console-JJJJMMDD.db console/data/console.db
docker compose start console
curl -fsS "http://$(docker compose port console 8000)/healthz"   # {"status":"ok",...}
```

Zelfde procedure voor de Streamlit-app met `app`/`poller` en
`data/sellout.db`.

Gooi `*.kapot` pas weg als het dashboard de verwachte cijfers laat zien: soms
zit er in het beschadigde bestand nog data die nieuwer is dan de laatste
back-up, en die kun je er dan met `sqlite3` alsnog uit vissen.

## Wat een back-up NIET dekt

De back-up staat op dezelfde droplet. Gaat de droplet zelf verloren, dan is
hij ook weg. Zolang er geen kopie buiten de droplet staat, is het herstelpad
in dat geval: nieuwe droplet, `git pull`, en de aanleverbestanden opnieuw
importeren vanuit de mailbox — de parsers zijn deterministisch, dus dat
levert dezelfde cijfers op, maar het kost handwerk. Een off-site kopie
(bijvoorbeeld `rclone` naar SharePoint) is de logische volgende stap.
