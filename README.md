# Debezium Server Versuechsufbau

[Deutsch](README-de.md) | [English](README-en.md)

D Details:

- [Operator Guide](docs/operator-guide-sg.md)
- [Offline-Installation uf Oracle Linux 8](docs/oracle-linux-8-offline-sg.md)
- [Entwicklerleitfade für Cyrille](docs/entwicklerleitfaden-sg.md)

## Zweck

E reproduzierbare Testufbau für PostgreSQL → Debezium Server → Java-HTTP-Empfänger. Zitkritischi Zeileänderige wärde erfasst; e separate Bulk-Datepfad blybt dusse. Dermit löh sech d Zustellig und s Fählerverhalte lokal untersueche. Für Produktion isch dr Ufbau nid vorgseh.

## Versione

| Komponente | Version |
|---|---|
| PostgreSQL | 18.6-alpine |
| Debezium Server | 3.7.0.Final |
| Maven Build Image | 3.10.0-eclipse-temurin-25-alpine |
| Java Runtime Image | 25.0.4_7-jre-alpine |

## Vorussetzige

Docker CE und Docker Compose loufe nativ i WSL. Docker Desktop wird nid bruucht. Für Healthchecks und d Verifikation bruchts Python 3.12.

## Hostports

Aui drü veröffentlichte Hostports i `.env` setze. Zum Bispiel, we d Standardports scho belegt si:

```dotenv
PG_HOST_PORT=15432
RECEIVER_HOST_PORT=18080
DEBEZIUM_HOST_PORT=18081
```

`make health` und dr Verifier bruuche d ufglöste Compose-Portwärt, inklusiv Umgäbigs-Overrides. Intern blybe PostgreSQL uf 5432 und HTTP uf 8080; für anderi Hostports bruchts ke Änderig am Connector oder Empfänger. Nach ere Änderig i `.env` d Dienscht mit em folgende Befähl nöi erstelle. Datebank und Offsets blybe erhalte. Uf Offline-Hosts zuesätzlech `--pull never` aage.

```sh
docker compose up -d --wait --no-build postgres receiver debezium
```

## Schnällstart

```sh
make up
make health
make generate RUN_ID=r1
make verify
```

## Betrieb

Dr Empfänger boue: `make build` (direkt: `docker compose build receiver`).

Dr Stack starte: `make up` (Startbefehl: `docker compose up -d --wait postgres receiver debezium`).

Health mit de konfigurierten Ports prüefe: `make health`.

Deterministischi Änderige erzüge: `make generate RUN_ID=r1` (direkt: `RUN_ID=r1 docker compose run --rm generator`).

D Datebank mit `make psql` untersueche (direkt: `docker compose exec postgres psql -U dbz -d appdb`). Zum Bispiel:

```sql
select * from timecritical.customers order by id;
select run_id, status from bulk.batch_jobs order by id;
```

D Containerdiagnostik mit `make logs` verfolge (direkt: `docker compose logs -f --tail=100`). D Envelopes mit `make tail` verfolge (direkt: `tail -f logs/events.jsonl`).

Alli Verifikationsprüefige usfüehre: `make verify` (direkt: `python3 verify/verify.py all`).

E churze Usfall reproduziere: `make outage-short` (direkt: `python3 verify/verify.py outage-short`).

E lange Usfall reproduziere: `make outage-long` (direkt: `python3 verify/verify.py outage-long`).

Debezium wieder zum Loufe bringe, wenn s Retry-Budget ufgbruucht isch: `make recover` (direkt: `docker compose restart debezium`).

Mit `make stop` stoppe und d Date sowie d Offsets bhalte (direkt: `docker compose stop`). O `make restart` bhaltet si (direkt: `docker compose restart`).

Mit `make reset` zruggsetze (Compose-Befehl: `docker compose --profile tools down -v --remove-orphans`; dernah wärde d benannte Host-Logdateie und dr Inhalt vo `runs/` usser `.gitkeep` entfernt). Derby wärde d Container, d Volumes `dbzproof_pg_data` und `dbzproof_debezium_data`, `logs/events.jsonl`, `logs/receipts.jsonl`, `logs/receiver.log` und dr Inhalt vo `runs/` usser `.gitkeep` glöscht.

## Schnittstellevertrag

Dr Empfänger bietet `POST /events` und `GET /health`; Debezium-Health isch über `GET /q/health` uf em konfigurierten Hostport erreichbar (Standard 8081). Event-POSTs enthalte s vollständige Debezium-Envelope (`before`, `after`, `source`, `transaction`, `op` und Zitstämpfle), ke aggregierti oder us em Envelope useglösti Zeile. JSON-Schema-Metadate und Delete-Tombstones si deaktiviert; Delete-Envelopes blybe erhalte. `logs/receipts.jsonl` enthaltet als separati Begleitdatei dr Receipt-Zitstämpfel, d Methode, dr Pfad, dr Status, d Byteazahl, normalisierti Header und e Ereigniszusammefassig; si verändert `logs/events.jsonl` nid.

## Retry Istellige

Dr HTTP-Sink verwendet e Timeout vo 5000 ms, 10 Retries und es Retry-Intervall vo 3000 ms. Im beobachtete Versuech het d ibetteti Engine nach 1 + 10 Versueche gstoppt (öppe 48 Sekunde bi abglehnte Verbindige und zwöi Verbindigs-Timeouts), mit `Exceeded maximum number of attempts to publish event`. Dr Container louft wyter, `/q/health` liefert 503 `DOWN`, und Compose zeigt `unhealthy`; es git ke automatische Neustart (`restart: "no"`). D Wiederherstellig erfolgt mit `make recover` (`docker compose restart debezium`). Dernah setzt Debezium bim persistierte Offset fort und liefert dr Rückstand us (beobachtet: 14 Events, 0 Duplikat). Bim zähsekündige `outage-short` isch d Wiederherstellig dür d eigete Retries vom Sink nach 15,1 Sekunde erfolgt, ohni dass d Engine gstoppt het.

## Verifikation

`verify/verify.py` prüeft d Empfänger- und Debezium-Health, d Snapshot-Azahle bim erschte Start, s Matching vo de Generator-Envelopes und d Replica Identity, Zeileereignis us derselbe Transaktion, dr Usschluss vo Bulk-Zeile, Retry-Recovery bim churze Usfall, dr Fählerzustand und d expliziti Recovery bim lange Usfall sowie d Persistenz und dr usblybendi erneuti Snapshot bim normale Neustart. Es protokolliert mehrfach zugstellti Quellpositione und lokali Beobachtige vo dr Zustellzit.

## Ischränkige

Dr Ufbau prüeft d Funktion under lokale Bedingige. Für e Produktionsbenchmark bruchts anderi Laste und Mässige. D Zuegangsdate ghöre zu mene lokale Superuser. Bi dr Wiederherstellig chöi Duplikat entstah; Exactly-once isch nid garantiert. D gmässene Zustellzite si Beobachtige. Es SLA laht sech dadrus nid zouberä.

## Beobachtige bim erschte Louf

Bruucht worde si PostgreSQL 18.6, Debezium Server 3.7.0.Final, d Java-25.0.4-Runtime und e mit Maven 3.10.0 boute Empfänger. Dr Snapshot het 15 Envelopes glieferet: 3 Chunde, 4 Bstellige und 8 Bstellpositione. D Wärt vo `source.snapshot` hei `first`, `true`, `last_in_data_collection`, `first_in_data_collection` und `last` umfasst.

S Szenario het Matches für 7/7 erwarteti Events glieferet; vier T1-Envelopes hei dieselbi `source.txId` teilt. Dür `REPLICA IDENTITY FULL` isch `before` bi `u`- und `d`-Events befüllt gsi. D Bulk-Zeile si i PostgreSQL vorhande gsi, ohni dass es `bulk`-Envelope aacho isch. Lokali Beobachtig vo dr Zustellzit (ke Benchmark): Minimum 757 ms, Median 786 ms, Maximum 797 ms.

D Fakte zur HTTP-Repräsentation si i `debezium/README.md` dokumentiert.

Abschliessende Gsamtlouf vom 9. Oktober 2026 (`runs/verify-20261009T184304Z.json`): alli acht Abnahmekriterie PASS. D CLI enthaltet sibe Einzelprüefige; `scenario` kombiniert s Zeilematching und d Transaktionsprüefig. Lange Usfall: D Engine het nach 10 Sendversueche i 39,0 s gstoppt, dr Container isch mit Health DOWN wytergloffe, und es explizits `docker compose restart debezium` het dr Rückstand mit 0 Duplikat usglieferet. Normals `docker compose restart`: D Zeile und d Offsets si erhalte blibe, d Snapshot-Azahl isch bi 15 blibe (ke erneute Snapshot), 0 Duplikat. Zustellzit i däm Louf: Minimum 589 ms, Median 602 ms, Maximum 611 ms (lokali Beobachtig, ke Benchmark). D Löif garantiere konstruktionsbedingt ke Exactly-once; i dene Löif si eifach ke Duplikat beobachtet worde.
