# Operator Guide: PostgreSQL → Debezium Server → HTTP-Empfänger

[English version](operator-guide-en.md) | [Schweizerdeutsch](operator-guide-sg.md)

Dieser Operator Guide erklärt, wie der Versuchsaufbau läuft, was er prüft und wo seine Grenzen liegen.
Alle Befehle im Stammverzeichnis des Repositorys ausführen; die Pfade unten sind relativ dazu.
Für Oracle Linux 8 mit Docker CE und ohne Internetzugang beschreibt der folgende Leitfaden
die Vorbereitung, den Image-Transfer, die Installation und die hostspezifischen Prüfungen: [Leitfaden zur Offline-Bereitstellung](oracle-linux-8-offline-de.md).
Die Vorbereitung erfolgt auf der mit dem Internet verbundenen Ubuntu-VM auf dem Laptop;
auf dem OL8-Ziel ist SELinux nicht aktiviert. Dieser Leitfaden beschreibt
das Anwendungsverhalten unabhängig von der Host-Distribution.

## Was der Versuchsaufbau belegt

Ein externes Schreibsystem ändert relationale Zeilen in PostgreSQL. Debezium erfasst den
zeitkritischen Datenstrang und sendet einzelne Änderungs-Envelope an einen Java-HTTP-
Empfänger. Der Empfänger dient als Ersatz für einen REST-Dienst des Integration Broker;
er protokolliert Zustellungen, statt PeopleCode auszuführen oder Geschäftsobjekte zu verarbeiten.
Der separate `bulk`-Datenstrang verbleibt in PostgreSQL und ist für eine hypothetische
zeitgesteuerte Verarbeitung vorgesehen. Oracle, Datenbank-Links, App Engine und PeopleSoft
gehören nicht zu diesem Stack.

Es gibt weder Kafka noch einen Warteschlangendienst oder eine Ebene zur Aggregation von
Geschäftsobjekten. Werden ein Kunde, eine Bestellung und zwei Bestellpositionen in einer
Transaktion eingefügt, entstehen vier Zeilenereignisse. Sie werden nicht zu einer einzelnen
Bestellnachricht zusammengefasst. Das bestimmt, wie viel nachgelagerte
Transaktionsverarbeitung eine echte Integration braucht.

Der Versuchsaufbau prüft die initiale Erfassung, Filterung, Vorher-/Nachher-Werte, das begrenzte
HTTP-Wiederholungsverhalten und den Erhalt des Zustands nach einem Neustart. Er belegt weder
Durchsatz noch produktionsnahe Latenz, Exactly-once-Zustellung oder Verfügbarkeit im Produktivbetrieb.

## Komponenten und Adressen

```text
generator (manual psql scenario)
  └─ PostgreSQL: WAL + pgoutput + dbz_slot + dbz_publication
       └─ Debezium Server: initial snapshot, then streaming
            └─ HTTP POST /events, one envelope per request
                 └─ Java receiver: logs/events.jsonl
                                      logs/receipts.jsonl
                                      logs/receiver.log
host verifier ── reads logs/runs, queries PostgreSQL, controls Compose
```
| Komponente | Adresse innerhalb des Containers | Standardadresse auf dem Host |
|---|---|---|
| PostgreSQL | `postgres:5432` | `127.0.0.1:5432` |
| Empfänger | `receiver:8080/events` | `http://127.0.0.1:8080/events` |
| Health-Endpunkt des Empfängers | `receiver:8080/health` | `http://127.0.0.1:8080/health` |
| Debezium-Health-Endpunkt | Port 8080 in Debezium | `http://127.0.0.1:8081/q/health` |

Der Name des Compose-Projekts lautet `dbzproof`. Die Dienste heissen `postgres`, `receiver`,
`debezium` und `generator`; der Generator verwendet das Profil `tools` und wird beim normalen
Start nicht ausgeführt. Veröffentlichte Ports sind ausschliesslich an Loopback gebunden.
Innerhalb von Compose die Dienstnamen verwenden, nicht die Loopback-Adressen des Hosts.

Die eingecheckte `.env` legt PostgreSQL `18.6-alpine`, Debezium Server
`3.7.0.Final`, Maven `3.10.0-eclipse-temurin-25-alpine` und die Temurin-JRE des Empfängers
`25.0.4_7-jre-alpine` fest. Das Image des Empfängers wird im Container gebaut;
Java und Maven auf dem Host sind nicht erforderlich. Debezium verwendet die Laufzeit seiner
eigenen Images. Beim Vorbereiten eines Bereitstellungspakets die Versionsangaben
aus `.env` übernehmen.

## Voraussetzungen und gekoppelte Konfiguration

Für die dokumentierte Verifizierungsumgebung benötigt der Host Docker CE, das Docker-Compose-
Plugin, Bash, Make, curl und Python 3.12. Der Verifier verwendet ausschliesslich die
Python-Standardbibliothek; eine pip-Umgebung und jq sind nicht erforderlich. Ausserdem ruft
er Docker Compose und `tail` auf. Der Generator verwendet psql aus dem PostgreSQL-Image;
psql auf dem Host ist optional.

Die Zugangsdaten lauten `dbz` / `dbz`, die Datenbank heisst `appdb`. Es handelt sich um
Superuser-Zugangsdaten für die Demonstration; der Netzwerkverkehr zum Empfänger verwendet
unverschlüsseltes HTTP ohne Authentifizierung. Diese Dienste nicht durch eine beiläufige Änderung
der Loopback-Bindings nach aussen öffnen.

`.env` konfiguriert **nicht** alle Stellen, an denen Ports und Zugangsdaten verwendet werden:

- `compose.yaml` liest die Host-Ports und PostgreSQL-Zugangsdaten aus `.env`.
- `debezium/application.properties` enthält die Literale `dbz`, `dbz`, `appdb`.
- `verify/verify.py` enthält fest eingetragene Host-URLs auf den Ports 8080 und 8081 sowie
  in seinem psql-Wrapper die fest eingetragenen Datenbank-Benutzernamen und -Datenbanknamen `dbz` und `appdb`.
- Die Health-URLs, `psql` und `seed` im `Makefile` enthalten diese Literale ebenfalls.

Bei Änderungen an Ports oder Zugangsdaten diese Stellen gemeinsam anpassen. Bestehende
PostgreSQL-Volumes behalten ihre ursprünglichen Benutzer und Datenbanken; Änderungen an
`POSTGRES_*`-Umgebungsvariablen initialisieren sie nicht neu. Die Datenbankänderung ausdrücklich planen;
eine Anpassung der Umgebung übernimmt keine Migration.

Empfänger und Generator laufen mit `HOST_UID:HOST_GID` aus `.env` (Standardwert
1000:1000). Auf dem Zielsystem `id -u` und `id -g` prüfen und die Werte vor
dem Start passend setzen. Die Host-Verzeichnisse `logs/` und `runs/` müssen für diese Identität
beschreibbar sein. Berechtigungen des Image-Verzeichnisses setzen die Berechtigungen eines
Bind-Mounts nicht ausser Kraft.

## Erfassungsmechanik von PostgreSQL

PostgreSQL startet mit `wal_level=logical`, `max_wal_senders=10` und
`max_replication_slots=10`. WAL protokolliert Datenbankänderungen; `pgoutput` stellt den
von Debezium konsumierten logischen Replikationsstrom bereit.
Der benannte logische Slot `dbz_slot` hält die Position im Strom fest und bewahrt das von
seinem Verbraucher benötigte WAL auf. Die benannte Publication `dbz_publication` wählt die
Tabellen aus. Eine Publication ist eine Auswahlregel und keine Zustellwarteschlange.

Das initiale SQL legt die folgenden Tabellen für die Erfassung an:

| Tabelle | Beziehung | Seed-Zeilen |
|---|---|---:|
| `timecritical.customers` | Kundenidentität und Kontaktfelder | 3 |
| `timecritical.orders` | Fremdschlüssel zum Kunden | 4 |
| `timecritical.order_items` | Fremdschlüssel zur Bestellung | 8 |

Alle Tabellen besitzen den identity-generierten bigint-Primärschlüssel `id`. Geldbeträge
werden als ganzzahlige Cent-Beträge gespeichert. Auch die separaten Tabellen
`bulk.batch_jobs` und `bulk.pending_records` enthalten Seed-Zeilen, werden aber nicht
erfasst. Die zweite Tabelle verweist auf die erste.

`postgres/init/30-replication.sql` erstellt die Publication genau für die drei
zeitkritischen Tabellen. Der Connector legt in `debezium/application.properties` ausserdem
eine Schema-Allowlist und eine explizite Tabellen-Allowlist fest. Beide Ebenen sollten
übereinstimmen. Eine neue Tabelle wird nicht allein dadurch erfasst, dass sie im Schema
vorhanden ist. Die automatische Erstellung der Publication steht auf `filtered`, damit
Debezium bei Bedarf eine gefilterte Publication erstellen kann; beim normalen ersten Start
wird die mit SQL erstellte Publication verwendet.

Für alle drei erfassten Tabellen ist `REPLICA IDENTITY FULL` gesetzt. Dadurch stehen bei
Updates und Deletes die alten Zeilenwerte zur Verfügung, sodass der Verifier geänderte
Werte in `before` prüfen kann. Ein Primärschlüssel identifiziert zwar eine Zeile, liefert
aber nicht das vollständige alte Zeilenabbild, das dieser Versuchsaufbau benötigt. FULL erhöht den
Replikationsaufwand und das Datenvolumen; diese Kosten für echte Tabellen bewerten.

Init-Skripte werden nur ausgeführt, wenn PostgreSQL ein leeres Daten-Volume initialisiert.
Ein Neustart einer bestehenden Datenbank übernimmt keine Änderungen am Schema oder
an Replikations-SQL. Für beibehaltene Daten gezielte Migrations-SQL verwenden;
eine reine Reproduktionsumgebung kann vollständig zurückgesetzt werden.

## Initialer Snapshot und Streaming

`snapshot.mode=initial` bedeutet: Ein Connector ohne gespeicherten Zustand liest zuerst
die bereits vorhandenen erfassten Zeilen und verarbeitet anschliessend WAL-Änderungen weiter.
Das Seed-SQL wird vor dem Start von Debezium ausgeführt. Ein sauberer erster Start liefert
daher 15 `op=r`-Envelope. Die erwarteten Anzahlen stehen in `postgres/expected_snapshot.json`.

Snapshot-Markierungen sind nicht auf die Zeichenfolge `true` beschränkt. Der Verifier
akzeptiert in `source.snapshot` die Werte `true`, `first`, `last`,
`first_in_data_collection` und `last_in_data_collection`. Streaming-Ereignisse enthalten
normalerweise die Zeichenfolge `false`. Die tatsächlichen Daten prüfen, statt diese
Zeichenfolgen anhand ihres Wahrheitswerts in Booleans umzuwandeln.

Offsets werden unter `/debezium/data/offsets.dat` im benannten Volume
`dbzproof_debezium_data` gespeichert. Das konfigurierte Intervall zum Schreiben der Offsets
beträgt 0. Bei einem normalen Neustart bleibt dieser Zustand erhalten; der Connector sollte
ohne neuen Snapshot fortfahren. Der Verifier prüft dieses Verhalten; eine Offset-
Einstellung allein ist kein Nachweis. Werden Offsets gelöscht, während eine befüllte
Datenbank erhalten bleibt, kann ein neuer Snapshot aller aktuell erfassten Zeilen entstehen
anstelle der ursprünglichen Seed-Fixture mit 15 Zeilen.

## Ein Envelope lesen

Die JSON-Schema-Metadaten für Schlüssel und Werte sind deaktiviert. Ein Ereignis ist selbst
das Envelope und hat keinen äusseren `schema`/`payload`-Wrapper. HTTP-Batching ist deaktiviert.
Der Empfänger entfernt überflüssige JSON-Leerzeichen und schreibt das JSON in eine Zeile,
behält dabei aber Felder und Werte bei; er entfernt keine Metadaten, packt Zeilen nicht aus
und setzt keine Geschäftsobjekte zusammen.

| Feld | Bedeutung in diesem Versuchsaufbau |
|---|---|
| `op` | `r` Snapshot-Lesevorgang, `c` Anlegen, `u` Aktualisieren, `d` Löschen |
| `before` | alte Zeile bei Update/Delete; bei Create/Snapshot null |
| `after` | neue bzw. aktuelle Zeile; bei Delete null |
| `source.schema`, `source.table` | Ursprungsrelation |
| `source.lsn` | PostgreSQL-Quellposition für die Duplikatmeldung |
| `source.txId` | PostgreSQL-Transaktions-ID; bei den vier T1-Insert-Operationen gemeinsam |
| `source.snapshot` | Snapshot-Markierungszeichenfolge |
| `source.ts_ms` | Quellzeitstempel für lokale Zeitmessungen |
| `ts_ms`, `ts_us`, `ts_ns` | verfügbare Verarbeitungszeitstempel des Connectors |
| `transaction` | nullable Transaktionsmetadaten; kann hier null sein |

`source.txId` und das oberste Feld `transaction` sind unterschiedliche Felder. Das Szenario
verwendet das erste, um die gemeinsame Transaktionszugehörigkeit zu zeigen. Es setzt weder
nicht-null Transaktionsmetadaten auf oberster Ebene voraus noch belegt es eine atomare
HTTP-Zustellung pro Transaktion. Der Empfänger sieht einzelne Requests und darf nicht
annehmen, dass alle zugehörigen Ereignisse gemeinsam eintreffen.

Die gekürzten Beispiele zeigen nur die Struktur; IDs, Zeitstempel und Quellpositionen
variieren. Tatsächliche Envelope enthalten weitere Quell- und Zeilenfelder.


```json
{"before":null,"after":{"id":1,"external_ref":"cust-seed-1","name":"Ada Lovelace","email":"ada@example.test"},"source":{"schema":"timecritical","table":"customers","snapshot":"first","lsn":1234},"op":"r","transaction":null}
{"before":null,"after":{"id":4,"external_ref":"cust-demo","email":"demo@example.test"},"source":{"schema":"timecritical","table":"customers","snapshot":"false","txId":800,"lsn":2000},"op":"c","transaction":null}
{"before":{"id":4,"email":"demo@example.test"},"after":{"id":4,"email":"demo-updated@example.test"},"source":{"schema":"timecritical","table":"customers","snapshot":"false","txId":801,"lsn":2100},"op":"u","transaction":null}
{"before":{"id":10,"sku":"SKU-demo-B"},"after":null,"source":{"schema":"timecritical","table":"order_items","snapshot":"false","txId":803,"lsn":2300},"op":"d","transaction":null}
```
Die beobachtete HTTP-Darstellung enthält keinen separaten Record-Key- oder Topic-Header.
Eine Zeile über `source.schema`, `source.table` und `after.id` oder bei
einem Delete über `before.id` identifizieren. Das Topic-Präfix `plumbing` bedeutet nicht, dass der Topic-
Name als Ziel-Header übertragen wird. Receipt-Header enthalten HTTP-Kontext; die beobachteten
Werte `x-debezium-__debezium.context.*` sind base64-kodiertes JSON und keine Zeilenschlüssel.
Der Verifier protokolliert vorhandene Header, verlangt sie aber nicht.

Delete-Tombstones sind mit `tombstones.on.delete=false` deaktiviert; Delete-
**Envelope** bleiben aktiviert. Der Empfänger akzeptiert leere oder JSON-null-Bodies mit
HTTP 204 und einem Tombstone-Receipt, ohne eine Zeile zur Ereignisdatei hinzuzufügen.

## Dauerhaftigkeit des Empfängers und seine drei Logs

Bei gültigem, nicht-null JSON hängt der Empfänger mit einem FileChannel und `force(true)`
eine vollständige JSONL-Zeile an, versucht danach ein Receipt zu schreiben und antwortet mit
HTTP 200. Schlägt das Anhängen eines Ereignisses fehl, lautet die Antwort HTTP 500;
ungültiges JSON führt zu HTTP 400. Schreibzugriffe sind gesperrt, damit parallele
Anhänge sich nicht ineinander verschachteln. Die JSON-Prüfung validiert kein fachliches
Schema: Der Endpunkt dient lediglich als Protokollierungs-Ersatz.

Das Anhängen des Ereignisses bildet die Bestätigungsgrenze. Das Schreiben eines Receipts
erfolgt nach bestem Bemühen: Ein Fehler dabei wird protokolliert und ändert eine erfolgreiche
Ereigniszustellung nicht in eine Fehlermeldung. Ein Absturz oder eine verlorene Antwort nach
dem dauerhaften Schreiben kann deshalb eine Wiederholung und eine weitere Ereigniszeile
auslösen. Eine Duplikatunterdrückung gibt es nicht.

| Host-Pfad | Inhalt | Zweck |
|---|---|---|
| `logs/events.jsonl` | kompakte vollständige Envelope | primärer Zustellnachweis |
| `logs/receipts.jsonl` | Anforderungszeit, Status, Bytes, Header in Kleinbuchstaben, Zusammenfassung | HTTP-/Zeitdiagnose |
| `logs/receiver.log` | Diagnosemeldungen des Empfängers | Schreibfehler und Request-Fehler |
| `runs/<RUN_ID>/expected.jsonl` | die sieben vom Generator erwarteten Änderungen | unabhängige Erwartungen für den Abgleich |
| `runs/<RUN_ID>/manifest.json` | Szenario-ID, Zeiten und Anzahlen | Zuordnung eines Durchlaufs |
| `runs/verify-*.json` | Ergebnisse und Beobachtungen des Verifiers | Abnahmenachweis aufbewahren |

Der Receipt-`seq`-Wert liegt nur im Arbeitsspeicher und beginnt nach jedem Neustart des
Empfängers erneut. Der Wert ist keine global eindeutige Ereignis-ID. Für die
Zeitmessung werden derzeit die geordneten Event-Receipts mit den Zeilen der Ereignisdatei
abgeglichen. Fehlende Receipts können diesen Abgleich beeinträchtigen; erfolgreiche
Zustellung und Latenznachweis sind getrennte Aussagen. Der Health-Check des Empfängers
prüft, ob das übergeordnete Verzeichnis der Ereignisdatei beschreibbar ist. Er führt keinen
dauerhaften Testschreibvorgang aus und garantiert keinen freien Speicherplatz.

## Alltägliche Befehle


```sh
make build                         # build the Java receiver image
make up                            # build, start three services, wait for health
make ps
make health
make logs                          # follow container diagnostics; Ctrl-C stops following
make tail                          # follow delivered envelopes; Ctrl-C stops following
make psql                          # interactive database session
make generate RUN_ID=manual-001     # commit one identifiable scenario
make stop                          # retain containers, data, offsets and host logs
make start                         # start existing stopped containers
make restart                       # restart all services; preserve state
make down                          # remove containers/network; retain volumes and host files
make up                            # recreate services using retained state
```
`make up` baut immer zuerst den Empfänger. Diesen Befehl auf dem Vorbereitungshost
mit Internetzugang verwenden. Auf dem Offline-Ziel mit den übertragenen Images
ohne Build und Pull starten, wie im Offline-Leitfaden beschrieben,
auch nach einem vollständigen Reset der Testumgebung. `make seed` wendet das idempotente
Seed-SQL erneut an; es setzt keinen sauberen Snapshot-Zustand her. `ON CONFLICT DO NOTHING`
verhindert doppelte Seed-Einträge, setzt geänderte Felder vorhandener Zeilen aber nicht auf
ihre ursprünglichen Werte zurück.

Für jeden Generatorlauf ist eine neue ID erforderlich: Buchstaben, Ziffern, Punkte,
Unterstriche und Bindestriche; das erste Zeichen muss ein Buchstabe oder eine Ziffer sein.
Bereits vorhandene Run-Verzeichnisse werden abgewiesen. Eine ID ist optional, wenn eine
UTC-Zeitstempel-ID passt: `make generate`. Der Generator committet vier Inserts in T1,
danach ein Kunden-Update in T2, ein Bestellungs-Update in T3 und ein Löschen einer
Bestellposition in T4: insgesamt sieben erwartete erfasste Ereignisse. Zusätzlich fügt er
einen Bulk-Job und zwei ausstehende Datensätze ein und aktualisiert einen ausstehenden
Datensatz. Die aufgezeichneten erwarteten Zeilen verwenden die tatsächlich generierten
Primärschlüssel.

## Sichere Abnahmefolge

Der vollständige Verifier ist ein aktiver Test-Harness: Er schreibt Datenbankzeilen,
stoppt den Empfänger, lässt das Retry-Limit des Sinks ausschöpfen und startet Dienste neu.
Nur auf diesem isolierten Versuchsaufbau ausführen. Ein gemeinsam genutzter Dienst,
der ohne Unterbrechung verfügbar sein muss, ist dafür ungeeignet. Keine zwei Verifier
oder einen Verifier und ein manuelles Szenario gleichzeitig ausführen; Run-IDs verwenden
Zeitstempel mit einer Auflösung von einer Sekunde, und die gemeinsamen Logs werden global
ausgewertet.

Die folgende Abfolge gilt für den Vorbereitungshost mit Internetzugang. Auf dem
Offline-Ziel `make up` durch den Startbefehl des Offline-Leitfadens ohne Build und Pull ersetzen.
Für eine reproduzierbare Abnahme des ersten Starts zunächst alle benötigten Logs
und Berichte sichern, danach den flüchtigen Zustand dieses Projekts ausdrücklich verwerfen:

```sh
make reset                         # DESTRUCTIVE: see exact scope below
make up
make verify
```
`make reset` führt Compose mit Volumes herunter und entfernt
`dbzproof_pg_data`, `dbzproof_debezium_data`, `logs/events.jsonl`,
`logs/receipts.jsonl`, `logs/receiver.log` sowie den Inhalt von `runs/` ausser
`.gitkeep`. Das ist kein gewöhnlicher Neustart. Kein globales Docker-Prune verwenden.

Für die Verifizierung eines frischen Snapshots müssen sowohl das Datenbank-/Offset-Paar als
auch die Logs frisch sein. Alte Logs können dazu führen, dass alte Snapshot-Zeilen
mitgezählt werden; nur die Logs zu löschen, während die Offsets erhalten bleiben, entfernt
Belege, löst aber keinen neuen Snapshot aus. Wird nur ein Volume neu initialisiert, entsteht
ein anderer Test und die Kontinuität kann verloren gehen. Die vollständige Prüfung erwartet
genau 3/4/8 Seed-Snapshot-Zeilen. Ein erneuter Snapshot einer befüllten Szenario-Datenbank
erfüllt diese Fixture nicht.

## Sieben CLI-Prüfungen, acht historische Kriterien

Das ursprüngliche Ziel nennt acht Abnahmekriterien. Die Implementierung stellt sieben
einzelne Prüfungen sowie `all` bereit: `scenario` kombiniert den Abgleich der
Zeilen-Envelope mit dem Kriterium gemeinsamer Transaktionen. Einen achten einzelnen
Befehl gibt es nicht. Die historische Formulierung „eight checks“ bezieht sich auf die
Kriterien und nicht auf CLI-Unterbefehle.

| CLI-Prüfung | Tatsächliche Funktion |
|---|---|
| `health` | beide Health-Endpunkte per GET abfragen; die letzte Zeile der Host-Ereignisdatei einlesen |
| `snapshot` | auf Seed-Envelope mit `r` warten; exakte Anzahlen 3/4/8 und Markierungen prüfen |
| `scenario` | einen neuen Durchlauf erzeugen; sieben Zeilen, Vorher-Bilder und vier gemeinsame T1-txIds abgleichen |
| `bulk` | Bulk-Zeilen des Durchlaufs prüfen; Bulk aktualisieren, auf eine erfasste Markierung warten und Bulk-Envelope zurückweisen |
| `outage-short` | Empfänger 10 Sekunden stoppen; Szenario erzeugen; Empfänger starten; Zustellung bei laufendem Debezium abwarten |
| `outage-long` | Empfänger bis zum Engine-Fehler stoppen; Empfänger wiederherstellen; Debezium ausdrücklich neu starten; Rückstand abarbeiten lassen |
| `restart` | vor und nach dem Neustart einen Durchlauf erzeugen; erhaltene Zeilen und unveränderte Snapshot-Anzahl prüfen |


```sh
python3 verify/verify.py --help
python3 verify/verify.py health
python3 verify/verify.py snapshot
python3 verify/verify.py scenario --run-id=isolated-001
python3 verify/verify.py bulk --run-id=isolated-001
python3 verify/verify.py outage-short
python3 verify/verify.py outage-long
python3 verify/verify.py restart
python3 verify/verify.py all
```
`scenario --run-id` **erzeugt** den angegebenen Durchlauf; der Befehl liest nicht bloss
einen vorhandenen manuellen Durchlauf ein. `bulk --run-id` liest die Erwartungen eines
vorhandenen Durchlaufs und ergänzt eigene Diagnose-Updates. `all` erstellt eine
Szenario-ID und übergibt sie an `bulk`. Jeder Aufruf schreibt einen Bericht mit Zeitstempel
im JSON-Format und endet bei Erfolg mit 0, bei einem Fehler mit 1. Vor dem nächsten Versuch einer fehlgeschlagenen Prüfung
den benannten Bericht lesen.

Der Abgleich verwendet erwartete Schlüssel und Teilmengen der Vorher-/Nachher-Werte aus dem
Generator; die Erwartungen werden nicht anhand der beobachteten Zustellung rekonstruiert.
Duplikatberichte verwenden Quell-LSN, Schema, Tabelle, Operation und Zeilen-ID. Sie sind
Beobachtungen und kein Dienst zur Duplikatunterdrückung bei der Zustellung. Einige Prüfungen
melden Duplikate, ohne fehlzuschlagen; `scenario` verlangt zusätzlich genau vier passende
T1-Ereignisse. Ein PASS ist keine Garantie für Exactly-once-Zustellung.

## Verhalten bei Ausfällen und ausdrückliche Wiederherstellung

Das HTTP-Sink-Timeout beträgt 5000 ms, die Anzahl der Wiederholungen 10 und das Intervall
zwischen Wiederholungen 3000 ms. Das Retry-Budget ist begrenzt. Verbindungsablehnungen und
Timeouts verbrauchen unterschiedlich viel Zeit; aus diesen Einstellungen ergibt sich daher
keine einheitliche garantierte Ausfalldauer. Als Nachweis dienen die Laufzeit, die Anzahl der
Sendeversuche und die Logs des Verifiers.

Im festgelegten, beobachteten Stack beendet das Ausschöpfen der Wiederholungen die
eingebettete Engine, während der Container weiterläuft. `/q/health` liefert HTTP 503/DOWN,
und Compose markiert den Container nach einiger Zeit als fehlerhaft. Es ist keine
Restart-Policy konfiguriert. Ein laufender Container allein belegt deshalb nicht, dass die
Erfassung funktioniert.

Den Empfänger wiederherstellen und Debezium neu starten, damit die Engine erneut
geöffnet wird:

```sh
docker compose start receiver
curl -fs http://127.0.0.1:8080/health
make recover                       # docker compose restart debezium
make health
make ps
docker compose logs --tail=100 debezium
```
`docker compose start debezium` startet keinen bereits laufenden, fehlerhaften Container
neu. Ein kurzer Ausfall kann sich durch die Sink-Wiederholungen erholen; nach dem oben
beschriebenen Ausschöpfen des Retry-Budgets ist ein ausdrücklicher Neustart erforderlich.
Zu den bisherigen Beobachtungen gehören Engine-Fehlermeldungen mit
`Exceeded maximum number of attempts` und `Engine has failed`. Anzahl der Versuche und
Wiederherstellungszeit hängen vom jeweiligen Durchlauf ab.

## Logs ohne jq untersuchen

Das letzte Envelope mit der Python-Standardbibliothek formatiert ausgeben:


```sh
tail -n 1 logs/events.jsonl | python3 -m json.tool
```
Operationen und Tabellen zählen und das letzte Event-Receipt ausgeben:


```sh
python3 - <<'PYCODE'
import collections, json
from pathlib import Path
counts = collections.Counter()
for line in Path('logs/events.jsonl').read_text().splitlines():
    if not line.strip():
        continue
    event = json.loads(line)
    source = event.get('source') or {}
    counts[(source.get('schema'), source.get('table'), event.get('op'))] += 1
for key, count in sorted(counts.items()):
    print(*key, count)
receipts = Path('logs/receipts.jsonl')
if receipts.exists():
    events = [json.loads(line) for line in receipts.read_text().splitlines() if line.strip()]
    events = [r for r in events if r.get('kind') == 'event']
    if events:
        print(json.dumps(events[-1], indent=2))
PYCODE
```
Diese Befehle bei ruhenden Logs ausführen oder nach einem
gleichzeitigen Schreibvorgang an der letzten Zeile wiederholen; der Verifier selbst toleriert eine
unvollständige letzte JSONL-Zeile. Während der Abnahme keine Test-JSON per POST senden
an `/events`: Jedes gültige JSON-Objekt wird zu einer Zustellzeile und kann die Annahmen
des Verifiers ungültig machen.

## Fehlerbehebung und zurückgehaltenes WAL

| Symptom | Erste Prüfungen und Bedeutung |
|---|---|
| Port bereits belegt | Host-Listener prüfen; die oben beschriebenen zusammengehörigen Port-Literale ändern |
| Empfänger fehlerhaft oder HTTP 500 | UID/GID, Berechtigungen des Bind-Verzeichnisses, freien Speicher und `logs/receiver.log` prüfen |
| Debezium läuft, ist aber fehlerhaft | Debezium-Logs und `/q/health` prüfen; nach erschöpftem Sink-Retry `make recover` ausführen |
| Ereignisse im Szenario fehlen | Abweichungen im Bericht, Schreibvorgänge des Empfängers, Connector-Health und Capture-Allowlists prüfen |
| Bei Update/Delete fehlen alte Felder | Replica Identity in der tatsächlich beibehaltenen Datenbank prüfen |
| Unerwartete Snapshot-Anzahl | Volumes, alte Logs und separat entfernte Offsets prüfen |
| Generator weist ID zurück | eine neue gültige ID verwenden; bisherige Run-Belege aufbewahren, statt sie zu überschreiben |
| Seed-/Schema-Änderung scheint ignoriert | Init-Skripte laufen nur bei einem leeren PostgreSQL-Daten-Volume |

Die Mitgliedschaft der Publication, die Replica Identity und den Fortschritt des
Slots prüfen:

```sh
docker compose exec -T postgres psql -U dbz -d appdb <<'SQL'
SELECT schemaname, tablename FROM pg_publication_tables
WHERE pubname = 'dbz_publication' ORDER BY schemaname, tablename;
SELECT n.nspname, c.relname, c.relreplident
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='timecritical' AND c.relkind='r' ORDER BY c.relname;
SELECT slot_name, plugin, active, restart_lsn, confirmed_flush_lsn,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
FROM pg_replication_slots;
SQL
```
Replica Identity `f` bedeutet FULL. Solange der Verbraucher ausgefallen oder blockiert ist,
kann der Slot WAL zurückhalten und den PostgreSQL-Speicher füllen. Das
zurückgehaltene WAL und den Speicherplatz überwachen; dieser Versuchsaufbau konfiguriert weder eine operative
Grenze für die WAL-Aufbewahrung noch Warnmeldungen dazu. Den Slot oder die
Offsets nicht als routinemässige Wiederherstellungsmassnahme löschen: Dadurch kann benötigter
Änderungsverlauf verloren gehen und ein erneuter Snapshot erzwungen werden. Zuerst
die Zustellung wiederherstellen und anschliessend den Slot-Fortschritt sowie
den Abbau des Rückstands prüfen. Bei vollem Speicher ist ein geplanter Datenbank-Wiederherstellungsplan
erforderlich; wiederholte blinde Neustarts reichen nicht aus.

## Auswirkungen auf den Produktivbetrieb

Dieser Empfänger bietet weder Authentifizierung noch eine Begrenzung der Request-Grösse,
fachliche Validierung, Log-Rotation oder Duplikatunterdrückung. Zudem liest er jeden
Request-Body vollständig in den Arbeitsspeicher. Die Append-Datei ist ein Nachweis und keine
Warteschlange zur Verarbeitung von Geschäftsdaten. Vor einer solchen Verwendung Aufbewahrung, Backups und
Bestätigungssemantik nachgelagerter Systeme planen.
Benannte Volumes und Bind-Mounts sind persistenter Speicher, aber keine Backups.

Für den Produktivbetrieb braucht es begrenzte Datenbankberechtigungen, abgesicherten und
authentifizierten Transport, Zugangsdatenverwaltung, Überwachung von WAL und Slots,
Speicherkapazität und Log-Aufbewahrung. Ebenso ist eine durchdachte Strategie für
Duplikatbehandlung, Transaktionen, Schemaänderungen und Ausfälle nötig, die länger als das
begrenzte Sink-Retry-Budget dauern.
Lokale Zustellzeiten verwenden Quellzeitstempel und Receipt-Zeitstempel nach bestem Bemühen;
sie hängen von den Uhren und der Zuordnung der Receipts ab. Es sind Beobachtungen und kein
SLA. Erfolgreiche Durchläufe des Versuchsaufbaus liefern Anhaltspunkte für diesen Entwurf, ersetzen
ihn aber nicht.
