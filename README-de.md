# Debezium Server Versuchsaufbau

[English](README-en.md) | [Schweizerdeutsch](README-sg.md)

Die Details:

- [Operator Guide](docs/operator-guide-de.md)
- [Offline Installation auf Oracle Linux 8](docs/oracle-linux-8-offline-de.md)
- [Entwicklerleitfaden für Cyrille](docs/entwicklerleitfaden-de.md)

## Zweck

Ein reproduzierbarer Testaufbau für PostgreSQL → Debezium Server → Java-HTTP-Empfänger. Zeitkritische Zeilenänderungen werden erfasst; ein separater Bulk-Datenpfad bleibt draussen. Damit lassen sich Zustellung und Fehlerverhalten lokal untersuchen. Für Produktion ist der Aufbau nicht vorgesehen.

## Versionen

| Komponente | Version |
|---|---|
| PostgreSQL | 18.6-alpine |
| Debezium Server | 3.7.0.Final |
| Maven Build Image | 3.10.0-eclipse-temurin-25-alpine |
| Java Runtime Image | 25.0.4_7-jre-alpine |

## Voraussetzungen

Docker CE und Docker Compose laufen nativ in WSL. Docker Desktop wird nicht verwendet. Für Healthchecks und Verifikation wird Python 3.12 benötigt.

## Hostports

Alle drei veröffentlichten Hostports in `.env` setzen. Beispiel, falls die Standardports belegt sind:

```dotenv
PG_HOST_PORT=15432
RECEIVER_HOST_PORT=18080
DEBEZIUM_HOST_PORT=18081
```

`make health` und der Verifier verwenden die aufgelösten Compose-Portwerte, einschliesslich Umgebungs-Overrides. Intern bleiben PostgreSQL auf 5432 und HTTP auf 8080; für andere Hostports sind keine Änderungen am Connector oder Empfänger nötig. Nach einer Änderung in `.env` die Dienste mit dem folgenden Befehl neu erstellen. Datenbank und Offsets bleiben erhalten. Auf Offline-Hosts zusätzlich `--pull never` angeben.

```sh
docker compose up -d --wait --no-build postgres receiver debezium
```

## Schnellstart

```sh
make up
make health
make generate RUN_ID=r1
make verify
```

## Betrieb

Empfänger bauen: `make build` (direkt: `docker compose build receiver`).

Stack starten: `make up` (Startbefehl: `docker compose up -d --wait postgres receiver debezium`).

Health mit den konfigurierten Ports prüfen: `make health`.

Deterministische Änderungen erzeugen: `make generate RUN_ID=r1` (direkt: `RUN_ID=r1 docker compose run --rm generator`).

Datenbank mit `make psql` untersuchen (direkt: `docker compose exec postgres psql -U dbz -d appdb`). Zum Beispiel:

```sql
select * from timecritical.customers order by id;
select run_id, status from bulk.batch_jobs order by id;
```

Containerdiagnostik mit `make logs` verfolgen (direkt: `docker compose logs -f --tail=100`). Envelopes mit `make tail` verfolgen (direkt: `tail -f logs/events.jsonl`).

Alle Verifikationsprüfungen ausführen: `make verify` (direkt: `python3 verify/verify.py all`).

Kurzen Ausfall reproduzieren: `make outage-short` (direkt: `python3 verify/verify.py outage-short`).

Langen Ausfall reproduzieren: `make outage-long` (direkt: `python3 verify/verify.py outage-long`).

Debezium nach ausgeschöpftem Retry-Budget wiederherstellen: `make recover` (direkt: `docker compose restart debezium`).

Mit `make stop` stoppen und Daten sowie Offsets erhalten (direkt: `docker compose stop`). Auch `make restart` erhält sie (direkt: `docker compose restart`).

Mit `make reset` zurücksetzen (Compose-Befehl: `docker compose --profile tools down -v --remove-orphans`; anschliessend werden die benannten Host-Logdateien und der Inhalt von `runs/` ausser `.gitkeep` entfernt). Dabei werden Container, die Volumes `dbzproof_pg_data` und `dbzproof_debezium_data`, `logs/events.jsonl`, `logs/receipts.jsonl`, `logs/receiver.log` und der Inhalt von `runs/` ausser `.gitkeep` gelöscht.

## Schnittstellenvertrag

Der Empfänger bietet `POST /events` und `GET /health`; Debezium-Health ist über `GET /q/health` auf dem konfigurierten Hostport erreichbar (Standard 8081). Event-POSTs enthalten das vollständige Debezium-Envelope (`before`, `after`, `source`, `transaction`, `op` und Zeitstempel), keine aggregierte oder aus dem Envelope herausgelöste Zeile. JSON-Schema-Metadaten und Delete-Tombstones sind deaktiviert; Delete-Envelopes bleiben erhalten. `logs/receipts.jsonl` enthält als separate Begleitdatei den Receipt-Zeitstempel, Methode, Pfad, Status, Byteanzahl, normalisierte Header und eine Ereigniszusammenfassung; sie verändert `logs/events.jsonl` nicht.

## Retry Einstellungen

Der HTTP-Sink verwendet einen Timeout von 5000 ms, 10 Retries und ein Retry-Intervall von 3000 ms. Im beobachteten Versuch stoppte die eingebettete Engine nach 1 + 10 Versuchen (etwa 48 Sekunden bei abgelehnten Verbindungen und zwei Verbindungs-Timeouts) mit `Exceeded maximum number of attempts to publish event`. Der Container läuft weiter, `/q/health` liefert 503 `DOWN`, und Compose zeigt `unhealthy`; es gibt keinen automatischen Neustart (`restart: "no"`). Die Wiederherstellung erfolgt mit `make recover` (`docker compose restart debezium`). Danach setzt Debezium beim persistierten Offset fort und liefert den Rückstand aus (beobachtet: 14 Events, 0 Duplikate). Beim zehnsekündigen `outage-short` erfolgte die Wiederherstellung durch die eigenen Retries des Sinks nach 15,1 Sekunden, ohne dass die Engine stoppte.

## Verifikation

`verify/verify.py` prüft Empfänger- und Debezium-Health, Snapshot-Anzahlen beim ersten Start, das Matching der Generator-Envelopes und Replica Identity, Zeilenereignisse derselben Transaktion, den Ausschluss von Bulk-Zeilen, Retry-Recovery bei kurzem Ausfall, Fehlerzustand und explizite Recovery bei langem Ausfall sowie Persistenz und ausbleibenden erneuten Snapshot bei gewöhnlichem Neustart. Es protokolliert mehrfach zugestellte Quellpositionen und lokale Zustellzeitbeobachtungen.

## Einschränkungen

Der Aufbau prüft die Funktion unter lokalen Bedingungen. Für einen Produktionsbenchmark braucht es andere Lasten und Messungen. Die Zugangsdaten gehören zu einem lokalen Superuser. Bei der Wiederherstellung können Duplikate entstehen; Exactly-once ist nicht garantiert. Die gemessenen Zustellzeiten sind Beobachtungen. Ein SLA lässt sich daraus nicht zaubern.

## Beobachtungen beim ersten Lauf

Verwendet wurden PostgreSQL 18.6, Debezium Server 3.7.0.Final, die Java-25.0.4-Runtime und ein mit Maven 3.10.0 gebauter Empfänger. Der Snapshot lieferte 15 Envelopes: 3 Kunden, 4 Bestellungen und 8 Bestellpositionen. Die Werte von `source.snapshot` umfassten `first`, `true`, `last_in_data_collection`, `first_in_data_collection` und `last`.

Das Szenario lieferte Matches für 7/7 erwartete Events; vier T1-Envelopes teilten dieselbe `source.txId`. Durch `REPLICA IDENTITY FULL` war `before` bei `u`- und `d`-Events befüllt. Die Bulk-Zeilen waren in PostgreSQL vorhanden, ohne dass ein `bulk`-Envelope eintraf. Lokale Zustellzeitbeobachtung (kein Benchmark): Minimum 757 ms, Median 786 ms, Maximum 797 ms.

Die Fakten zur HTTP-Repräsentation sind in `debezium/README.md` dokumentiert.

Abschliessender Gesamtlauf vom 9. Oktober 2026 (`runs/verify-20261009T184304Z.json`): alle acht Abnahmekriterien PASS. Die CLI enthält sieben Einzelprüfungen; `scenario` kombiniert Zeilenmatching und Transaktionsprüfung. Langer Ausfall: Die Engine stoppte nach 10 Sendversuchen in 39,0 s, der Container lief mit Health DOWN weiter, und ein explizites `docker compose restart debezium` lieferte den Rückstand mit 0 Duplikaten aus. Gewöhnliches `docker compose restart`: Zeilen und Offsets blieben erhalten, die Snapshot-Anzahl blieb bei 15 (kein erneuter Snapshot), 0 Duplikate. Zustellzeit in diesem Lauf: Minimum 589 ms, Median 602 ms, Maximum 611 ms (lokale Beobachtung, kein Benchmark). Die Läufe garantieren konstruktionsbedingt kein Exactly-once; in diesen Läufen wurden lediglich keine Duplikate beobachtet.
