# Operator Guide: PostgreSQL → Debezium Server → HTTP-Empfänger

[Deutsch](operator-guide-de.md) | [English](operator-guide-en.md)

Dä Operator Guide erklärt, wie dr Versuechsufbau louft, was er prüeft und wo sini Gränze ligge.
Aui Befähl im Stammverzeichnis vom Repository usfüehre; d Pfade unte si relativ derzue.
Für Oracle Linux 8 mit Docker CE und ohni Internetzuegang beschreibt dr folgende Leitfade
d Vorbereitig, dr Image-Transfer, d Installation und d hostspezifische Prüefige: [Leitfade für d Offline-Bereitstellig](oracle-linux-8-offline-sg.md).
D Vorbereitig passiert uf dr Ubuntu-VM uf em Laptop, wo mit em Internet verbunde isch;
uf em OL8-Ziel isch SELinux nid aktiviert. Dä Leitfade beschreibt
ds Verhalte vo dr Awändig unabhängig vo dr Host-Distribution.

## Was dr Versuechsufbau belegt

Es externs Schreibsystem änderet relationali Zeile in PostgreSQL. Debezium erfasst dr
zytkritisch Datestrang und schickt einzeln Änderigs-Envelope a ne Java-HTTP-
Empfänger. Dr Empfänger dient als Ersatz für e REST-Dienst vom Integration Broker;
er protokolliert Zustellige, statt PeopleCode uszfüehre oder Gschäftsobjekt z verarbeite.
Dr separati `bulk`-Datestrang blybt in PostgreSQL und isch für e hypothetischi
zytgstüürti Verarbeitig vorgseh. Oracle, Datebank-Links, App Engine und PeopleSoft
ghöre nid zu däm Stack.

Es git weder Kafka no e Warteschlangedienst oder e Ebene, wo Gschäftsobjekt aggregiert.
Wenn e Chund, e Bstellig und zwöi Bstellpositione i einere Transaktion iigfüegt werde,
entstöh vier Zeileereignis. Die werde nid zu einere einzelne Bstellnachricht
zämegfasst. Das bestimmt, wie viu nachglagereti
Transaktionsverarbeitig e echti Integration bruucht.

Dr Versuechsufbau prüeft d initiali Erfassig, d Filterig, d Vorher-/Nachher-Wärt, ds begränzte
HTTP-Retry-Verhalte und dr Erhalt vom Zuestand nach em Neustart. Er belegt weder
Durchsatz no produktionsnahi Latenz, Exactly-once-Zuestellig oder Verfüegbarkeit im Produktivbetrieb.

## Komponente und Adresse

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
| Komponente | Adräss im Container | Standardadräss uf em Host |
|---|---|---|
| PostgreSQL | `postgres:5432` | `127.0.0.1:5432` |
| Empfänger | `receiver:8080/events` | `http://127.0.0.1:8080/events` |
| Health-Endpunkt vom Empfänger | `receiver:8080/health` | `http://127.0.0.1:8080/health` |
| Debezium-Health-Endpunkt | Port 8080 in Debezium | `http://127.0.0.1:8081/q/health` |

Dr Name vom Compose-Projekt isch `dbzproof`. D Dienscht heisse `postgres`, `receiver`,
`debezium` und `generator`; dr Generator verwendet ds Profil `tools` und wird bim normale
Start nid usgfüehrt. D veröffentlichte Ports si usschliesslech a Loopback bunde.
Innerhalb vo Compose d Dienstname verwände, nid d Loopback-Adresse vom Host.

D iigcheckti `.env` legt PostgreSQL `18.6-alpine`, Debezium Server
`3.7.0.Final`, Maven `3.10.0-eclipse-temurin-25-alpine` und d Temurin-JRE vom Empfänger
`25.0.4_7-jre-alpine` fescht. Ds Image vom Empfänger wird im Container bout;
Java und Maven uf em Host si nid nötig. Debezium verwendet d Laufzyt vo sine
eigene Images. Bim Vorbereite vo mene Bereitstelligspaket d Versionsagabe
us `.env` übernäh.

## Voraussetzige und gchoppleti Konfiguration

Für d dokumentierti Verifizierungsumgäbig bruucht dr Host Docker CE, ds Docker-Compose-
Plugin, Bash, Make, curl und Python 3.12. Dr Verifier verwendet usschliesslech d
Python-Standardbibliothek; e pip-Umgäbig und jq si nid nötig. Usserdäm rüeft
er Docker Compose und `tail` uf. Dr Generator verwendet psql us em PostgreSQL-Image;
psql uf em Host isch optional.

D Zuegangsdate si `dbz` / `dbz`, d Datebank heisst `appdb`. Das si
Superuser-Zuegangsdate für d Demonstration; dr Netzwerkverkehr zum Empfänger verwendet
unverschlüsslets HTTP ohni Authentifizierig. Die Dienscht nid dür e beiläufigi Änderig
vo de Loopback-Bindings nach usse öffne.

Aui veröffentlichte Hostports chöme us `.env`: `PG_HOST_PORT`, `RECEIVER_HOST_PORT` und `DEBEZIUM_HOST_PORT`. `make health` und aui Health-Abfrage vom Verifier bruuche d ufglösti Compose-Konfiguration, inklusiv Umgäbigs-Overrides. D Adresstabelle obe zeigt d Standardwärt. Interni Dienschtports blybe unveränderet.

Es Bispiel mit freie Hostports:

```dotenv
PG_HOST_PORT=15432
RECEIVER_HOST_PORT=18080
DEBEZIUM_HOST_PORT=18081
```

Nach ere Änderig i `.env` d Dienscht nöi erstelle; `restart` übernimmt ke nöii Portzueordnige:

```sh
docker compose up -d --wait --no-build postgres receiver debezium
```

Datebank und Offsets blybe erhalte. Uf em Offline-Host zuesätzlech `--pull never` bruuche.

D Zuegangsdate blybe koppelt: `compose.yaml` liist si us `.env`; `debezium/application.properties`, dr psql-Wrapper vom Verifier sowie `psql` und `seed` im Makefile enthalte wyterhi feschti Wärt für `dbz` / `appdb`. Bi andere Zuegangsdate die Stelle zäme ändere. Bestohendi PostgreSQL-Volumes bhalte Benutzer und Datebank; Änderige a `POSTGRES_*` initialisiere oder migriere si nid.

Empfänger und Generator loufe mit `HOST_UID:HOST_GID` us `.env` (Standardwärt
1000:1000). Uf em Zielsystem `id -u` und `id -g` prüefe und d Wärt vor
em Start passend setze. D Host-Verzeichnis `logs/` und `runs/` müesse für die Identität
beschrybbar si. D Berechtigunge vom Image-Verzeichnis setze d Berechtigunge vo mene
Bind-Mount nid usser Chraft.

## Erfassigsmechanik vo PostgreSQL

PostgreSQL startet mit `wal_level=logical`, `max_wal_senders=10` und
`max_replication_slots=10`. WAL protokolliert Datebankänderige; `pgoutput` stellt dr
logisch Replikationsstrom bereit, wo Debezium konsumiert.
Dr benannt logisch Slot `dbz_slot` haltet d Position im Strom fescht und bewahrt ds WAL uf,
wo si Verbraucher bruucht. D benannti Publication `dbz_publication` wählt d
Tabelle us. E Publication isch e Uswahlregel und ke Zuestellwarteschlange.

Ds initiale SQL legt die folgende Tabelle für d Erfassig aa:

| Tabelle | Beziehig | Seed-Zeile |
|---|---|---:|
| `timecritical.customers` | Chundeidentität und Kontaktfälder | 3 |
| `timecritical.orders` | Frömdschlüssel zum Chund | 4 |
| `timecritical.order_items` | Frömdschlüssel zur Bstellig | 8 |

Aui Tabelle hei dr identity-generiert bigint-Primärschlüssel `id`. Gäldbeträg
werde als ganzzahligi Cent-Beträg gspeicheret. O d separate Tabelle
`bulk.batch_jobs` und `bulk.pending_records` enthalte Seed-Zeile, werde aber nid
erfasst. D zwöiti Tabelle verweist uf d erschti.

`postgres/init/30-replication.sql` erstellt d Publication genau für die drei
zytkritische Tabelle. Dr Connector legt i `debezium/application.properties` usserdäm
e Schema-Allowlist und e expliziti Tabelle-Allowlist fescht. Beidi Ebene sötte
übereinstimme. E nöii Tabelle wird nid allei dadür erfasst, dass sie im Schema
vorhande isch. D automatischi Erstellig vo dr Publication steit uf `filtered`, damit
Debezium bi Bedarf e gfiltereti Publication cha erstelle; bim normale erschte Start
wird d Publication verwendet, wo mit SQL erstellt worde isch.

Für aui drei erfasste Tabelle isch `REPLICA IDENTITY FULL` gsetzt. So stöh bi
Updates und Deletes d alte Zeilewärt zur Verfüegig, sodass dr Verifier gändereti
Wärt i `before` cha prüefe. E Primärschlüssel identifiziert zwar e Zeile, liefert
aber nid ds vollständige alte Zeileabbild, wo dä Versuechsufbau bruucht. FULL erhöht dr
Replikationsufwand und ds Datevolume; die Chöschte für echti Tabelle beurteile.

Init-Scripts werde nume usgfüehrt, wenn PostgreSQL es läärs Date-Volume initialisiert.
E Neustart vo nere bestohende Datebank übernimmt ke Änderige am Schema oder
am Replikations-SQL. Für bhalteni Date gezielts Migrations-SQL verwände;
e reini Reproduktionsumgäbig cha komplett zrügggsetzt werde.

## Initiale Snapshot und Streaming

`snapshot.mode=initial` bedeutet: E Connector ohni gspeicherete Zuestand liist zersch
d bereits vorhande erfasste Zeile und verarbeitet dernah WAL-Änderige wyter.
Ds Seed-SQL wird vor em Start vo Debezium usgfüehrt. E suubere erschte Start liefert
drum 15 `op=r`-Envelope. D erwartete Azahle stöh i `postgres/expected_snapshot.json`.

Snapshot-Markierige si nid uf d Zeichefolg `true` beschränkt. Dr Verifier
akzeptiert i `source.snapshot` d Wärt `true`, `first`, `last`,
`first_in_data_collection` und `last_in_data_collection`. Streaming-Ereignis enthalte
normalerwys d Zeichefolg `false`. D tatsächleche Date prüefe, statt die
Zeichefolge anhand vo ihrem Wahrheitswärt i Booleans umzuwandle.

Offsets werde under `/debezium/data/offsets.dat` im benannte Volume
`dbzproof_debezium_data` gspeicheret. Ds konfigurierte Intervall zum Schrybe vo de Offsets
beträgt 0. Bi mene normale Neustart blybt dä Zuestand erhalte; dr Connector sött
ohni nöie Snapshot wyterfahre. Dr Verifier prüeft das Verhalte; e Offset-
Iistellig allei isch ke Nachwys. Wenn Offsets glöscht werde, während e befüllti
Datebank erhalte blybt, cha e nöie Snapshot vo aune aktuell erfasste Zeile entstoh
anstelle vo dr ursprüngleche Seed-Fixture mit 15 Zeile.

## Es Envelope läse

D JSON-Schema-Metadate für Schlüssel und Wärt si deaktiviert. Es Ereignis isch sälber
ds Envelope und het ke üssere `schema`/`payload`-Wrapper. HTTP-Batching isch deaktiviert.
Dr Empfänger entfernt überflüssigi JSON-Leerzeiche und schrybt ds JSON i eini Zeile,
bhaltet derbi aber Fälder und Wärt bi; er entfernt ke Metadate, packt Zeile nid us
und setzt ke Gschäftsobjekt zäme.

| Fäld | Bedeutig i däm Versuechsufbau |
|---|---|
| `op` | `r` Snapshot-Läsevorgang, `c` Aalege, `u` Aktualisiere, `d` Lösche |
| `before` | alti Zeile bi Update/Delete; bi Create/Snapshot null |
| `after` | nöii bzw. aktuelli Zeile; bi Delete null |
| `source.schema`, `source.table` | Ursprungsrelation |
| `source.lsn` | PostgreSQL-Quellposition für d Duplikatmäldig |
| `source.txId` | PostgreSQL-Transaktions-ID; bi de vier T1-Insert-Operatione gemeinsam |
| `source.snapshot` | Snapshot-Markierungszeichefolg |
| `source.ts_ms` | Quellzytstämpfel für lokali Zytmässige |
| `ts_ms`, `ts_us`, `ts_ns` | verfüegbari Verarbeitigszytstämpfel vom Connector |
| `transaction` | nullable Transaktionsmetadate; cha hie null si |

`source.txId` und ds oberste Fäld `transaction` si unterschiedlechi Fälder. Ds Szenario
verwendet ds erschte, um d gemeinsami Transaktionszueghörigkeit z zeige. Es setzt weder
nid-null Transaktionsmetadate uf dr oberste Ebene vorus no belegt es e atomari
HTTP-Zuestellig pro Transaktion. Dr Empfänger gseht einzeln Requests und darf nid
anäh, dass aui zueghörige Ereignis mitenand aachöme.

D chürzte Bispil zeige nume d Struktur; IDs, Zytstämpfel und Quellpositione
variiere. Tatsächlechi Envelope enthalte wyteri Quell- und Zeilefälder.


```json
{"before":null,"after":{"id":1,"external_ref":"cust-seed-1","name":"Ada Lovelace","email":"ada@example.test"},"source":{"schema":"timecritical","table":"customers","snapshot":"first","lsn":1234},"op":"r","transaction":null}
{"before":null,"after":{"id":4,"external_ref":"cust-demo","email":"demo@example.test"},"source":{"schema":"timecritical","table":"customers","snapshot":"false","txId":800,"lsn":2000},"op":"c","transaction":null}
{"before":{"id":4,"email":"demo@example.test"},"after":{"id":4,"email":"demo-updated@example.test"},"source":{"schema":"timecritical","table":"customers","snapshot":"false","txId":801,"lsn":2100},"op":"u","transaction":null}
{"before":{"id":10,"sku":"SKU-demo-B"},"after":null,"source":{"schema":"timecritical","table":"order_items","snapshot":"false","txId":803,"lsn":2300},"op":"d","transaction":null}
```
D beobachteti HTTP-Darstellig enthält ke separate Record-Key- oder Topic-Header.
E Zeile über `source.schema`, `source.table` und `after.id` oder bi
mene Delete über `before.id` identifiziere. Ds Topic-Präfix `plumbing` bedeutet nid, dass dr Topic-
Name als Ziel-Header übertrage wird. Receipt-Header enthalte HTTP-Kontext; d beobachtete
Wärt `x-debezium-__debezium.context.*` si base64-kodierts JSON und ke Zeileschlüssel.
Dr Verifier protokolliert vorhandeni Header, verlangt sie aber nid.

Delete-Tombstones si mit `tombstones.on.delete=false` deaktiviert; Delete-
**Envelope** blybe aktiviert. Dr Empfänger akzeptiert lääri oder JSON-null-Bodies mit
HTTP 204 und emene Tombstone-Receipt, ohni e Zeile zur Ereignisdatei dezuezfüege.

## Dauerhaftigkeit vom Empfänger und sini drei Logs

Bi gültigem, nid-null JSON hängt dr Empfänger mit emene FileChannel und `force(true)`
e vollständigi JSONL-Zeile aa, versuecht dernah es Receipt z schrybe und antwortet mit
HTTP 200. Wenn ds Aahänge vo mene Ereignis fählschlaht, isch d Antwort HTTP 500;
ungültigs JSON füehrt zu HTTP 400. Schreibzuegriff si gschperrt, damit paralleli
Aahäng nid ineinander verschachtlet werde. D JSON-Prüefig validiert ke fachlechs
Schema: Dr Endpunkt dient nume als Protokollierungs-Ersatz.

Ds Aahänge vom Ereignis bildet d Bestätigungsgränze. Ds Schrybe vo mene Receipt
passiert nach beschtem Bemühe: E Fähler derbi wird protokolliert und änderet e erfolgrichi
Ereigniszuestellig nid i e Fählermäldig. E Absturz oder e verloreni Antwort nach
em dauerhafte Schrybe cha drum e Wiederholig und e wyteri Ereigniszeile
uslöse. E Duplikatunterdrückig git es nid.

| Host-Pfad | Inhalt | Zwäck |
|---|---|---|
| `logs/events.jsonl` | kompakti vollständigi Envelope | primäre Zuestellnachwys |
| `logs/receipts.jsonl` | Aaforderigszyt, Status, Bytes, Header i Chlybuechstabe, Zämefassig | HTTP-/Zytdiagnose |
| `logs/receiver.log` | Diagnosemäldige vom Empfänger | Schreibfähler und Request-Fähler |
| `runs/<RUN_ID>/expected.jsonl` | die sibe vom Generator erwartete Änderige | unabhängigi Erwartige für dr Abglich |
| `runs/<RUN_ID>/manifest.json` | Szenario-ID, Zyte und Azahle | Zueordnig vo mene Durchlouf |
| `runs/verify-*.json` | Resultat und Beobachtige vom Verifier | Abnahmenachwys ufbewahre |

Dr Receipt-`seq`-Wärt ligt nume im Arbeitsspeicher und fangt nach jedem Neustart vom
Empfänger wieder vo vorne aa. Dr Wärt isch ke global eindeutigi Ereignis-ID. Für d
Zytmässig werde aktuell d gordnete Event-Receipts mit de Zeile vo dr Ereignisdatei
abgliche. Fählendi Receipts chöi dä Abglich beeinträchtige; erfolgrichi
Zuestellig und Latenznachwys si separati Ussage. Dr Health-Check vom Empfänger
prüeft, öb ds übergordnete Verzeichnis vo dr Ereignisdatei beschrybbar isch. Er macht ke
dauerhafte Testschreibvorgang und garantiert ke freie Speicherplatz.

## Befähl für dr Alltag


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
`make up` bout immer zersch dr Empfänger. Dä Befähl uf em Vorbereitigshost
mit Internetzuegang verwände. Uf em Offline-Ziel mit de übertragene Images
ohni Build und Pull starte, wie im Offline-Leitfade beschribe,
o nach emene vollständige Reset vo dr Testumgäbig. `make seed` wändet ds idempotente
Seed-SQL wieder aa; es stellt ke suubere Snapshot-Zuestand her. `ON CONFLICT DO NOTHING`
verhinderet doppleti Seed-Iiträg, setzt gändereti Fälder vo vorhandene Zeile aber nid uf
ihri ursprüngleche Wärt zrügg.

Für jede Generatorlouf isch e nöii ID nötig: Buechstabe, Ziffere, Pünkt,
Understriche und Bindestriche; ds erschte Zeiche muess e Buechstabe oder e Ziffer si.
Bereits vorhandeni Run-Verzeichnis werde abgwise. E ID isch optional, wenn e
UTC-Zytstämpfel-ID passt: `make generate`. Dr Generator committet vier Inserts i T1,
dernah es Chunde-Update i T2, es Bstelligs-Update i T3 und ds Lösche vo nere
Bstellposition i T4: insgesamt sibe erwarteti erfassti Ereignis. Zuesätzlech füegt er
e Bulk-Job und zwöi usstehendi Datesätz ii und aktualisiert e usstehende
Datesatz. D ufgzeichnete erwartete Zeile verwände d tatsächlich generierte
Primärschlüssel.

## Sicheri Abnahmefolg

Dr vollständigi Verifier isch e aktive Test-Harness: Er schrybt Datebankzeile,
stoppt dr Empfänger, laht ds Retry-Limit vom Sink usschöpfe und startet Dienscht nöi.
Nume uf däm isolierte Versuechsufbau usfüehre. E gemeinsam gnutzte Dienst,
wo ohni Unterbruch verfüegbar muess si, isch derfür ungeeignet. Ke zwöi Verifier
oder e Verifier und es manuells Szenario glychzytig usfüehre; Run-IDs verwände
Zytstämpfel mit ere Uflösig vo einere Sekunde, und d gemeinsame Logs werde global
usgwärtet.

Die folgendi Abfolg gilt für dr Vorbereitigshost mit Internetzuegang. Uf em
Offline-Ziel `make up` dür dr Startbefähl vom Offline-Leitfade ohni Build und Pull ersetze.
Für e reproduzierbari Abnahme vom erschte Start zersch aui benötigte Logs
und Berichte sichere, dernah dr flüchtig Zuestand vo däm Projekt ausdrücklich verwärfe:

```sh
make reset                         # DESTRUCTIVE: see exact scope below
make up
make verify
```
`make reset` fahrt Compose mit Volumes abe und entfernt
`dbzproof_pg_data`, `dbzproof_debezium_data`, `logs/events.jsonl`,
`logs/receipts.jsonl`, `logs/receiver.log` sowie dr Inhalt vo `runs/` usser
`.gitkeep`. Das isch ke gewöhnleche Neustart. Ke globals Docker-Prune verwände.

Für d Verifizierig vo mene frische Snapshot müesse sowohl ds Datebank-/Offset-Paar als
o d Logs frisch si. Alti Logs chöi derzue füehre, dass alti Snapshot-Zeile
mitzellt werde; nume d Logs z lösche, während d Offsets erhalte blybe, entfernt
Beleg, löst aber ke nöie Snapshot us. Wenn nume eis Volume nöi initialisiert wird, entsteit
e andere Test und d Kontinuität cha verlore gah. D vollständigi Prüefig erwartet
genau 3/4/8 Seed-Snapshot-Zeile. E erneute Snapshot vo nere befüllte Szenario-Datebank
erfüllt die Fixture nid.

## Sibe CLI-Prüefige, acht historischi Kriterie

Ds ursprüngleche Ziel nennt acht Abnahmekriterie. D Implementierig stellt sibe
einzelni Prüefige sowie `all` bereit: `scenario` kombiniert dr Abglich vo de
Zeile-Envelope mit em Kriterium vo gemeinsame Transaktione. E achte einzelne
Befähl git es nid. D historischi Formulierig «eight checks» bezieht sich uf d
Kriterie und nid uf CLI-Unterbefähl.

| CLI-Prüefig | Tatsächlechi Funktion |
|---|---|
| `health` | beidi Health-Endpunkt per GET abfrage; d letschti Zeile vo dr Host-Ereignisdatei iiläse |
| `snapshot` | uf Seed-Envelope mit `r` warte; exakti Azahle 3/4/8 und Markierige prüefe |
| `scenario` | e nöie Durchlouf erzeuge; sibe Zeile, Vorher-Bilder und vier gemeinsami T1-txIds abgliche |
| `bulk` | Bulk-Zeile vom Durchlouf prüefe; Bulk aktualisiere, uf e erfassti Markierig warte und Bulk-Envelope zrüggwyse |
| `outage-short` | Empfänger 10 Sekunde stoppe; Szenario erzeuge; Empfänger starte; Zuestellig bi laufendem Debezium abwarte |
| `outage-long` | Empfänger bis zum Engine-Fähler stoppe; Empfänger wiederherstelle; Debezium ausdrücklich nöi starte; Rückstand la abarbeite |
| `restart` | vor und nach em Neustart e Durchlouf erzeuge; erhalteni Zeile und unveränderti Snapshot-Azahl prüefe |


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
`scenario --run-id` **erzeugt** dr agäbeni Durchlouf; dr Befähl liist nid nume
e vorhandene manuelle Durchlouf ii. `bulk --run-id` liist d Erwartige vo mene
vorhandene Durchlouf und ergänzt eigeti Diagnose-Updates. `all` erstellt e
Szenario-ID und übergit sie a `bulk`. Jede Ufruef schrybt e Bericht mit Zytstämpfel
im JSON-Format und endet bi Erfolg mit 0, bi mene Fähler mit 1. Vor em nächste Versuech vo nere fählgschlagene Prüefig
dr benannt Bericht läse.

Dr Abglich verwendet erwarteti Schlüssel und Teilmängine vo de Vorher-/Nachher-Wärt us em
Generator; d Erwartige werde nid anhand vo dr beobachtete Zuestellig rekonstruiert.
Duplikatbericht verwände Quell-LSN, Schema, Tabelle, Operation und Zeile-ID. Sie si
Beobachtige und ke Dienst zur Duplikatunterdrückig bi dr Zuestellig. Einigi Prüefige
mälde Duplikat, ohni fählzschlah; `scenario` verlangt zuesätzlech genau vier passendi
T1-Ereignis. Es PASS isch ke Garantie für Exactly-once-Zuestellig.

## Verhalte bi Usfäll und ausdrücklechi Wiederherstellig

Ds HTTP-Sink-Timeout beträgt 5000 ms, d Azahl vo Wiederholige 10 und ds Intervall
zwüsche de Wiederholige 3000 ms. Ds Retry-Budget isch begränzt. Verbindigsablehnige und
Timeouts bruuche unterschiedlech viu Zyt; us dene Iistellige ergit sich drum
ke einheitlechi garantierte Usfallduur. Als Nachwys diene d Laufzyt, d Azahl vo de
Sändeversuech und d Logs vom Verifier.

Im feschtgleite, beobachtete Stack beendet ds Usschöpfe vo de Wiederholige d
iibetteti Engine, während dr Container wyterlouft. `/q/health` liefert HTTP 503/DOWN,
und Compose markiert dr Container nach ere gwüsse Zyt als fählerhaft. Es isch ke
Restart-Policy konfiguriert. E laufende Container allei belegt drum nid, dass d
Erfassig funktioniert.

Dr Empfänger wiederherstelle und Debezium nöi starte, damit d Engine wieder
öffnet wird:

```sh
docker compose start receiver
curl -fs "http://$(docker compose port receiver 8080)/health"
make recover                       # docker compose restart debezium
make health
make ps
docker compose logs --tail=100 debezium
```
`docker compose start debezium` startet ke bereits laufende, fählerhafte Container
nöi. E churze Usfall cha sich dür d Sink-Wiederholige erhole; nach em obe
beschribene Usschöpfe vom Retry-Budget isch e ausdrückleche Neustart nötig.
Zu de bisherige Beobachtige ghöre Engine-Fählermäldige mit
`Exceeded maximum number of attempts` und `Engine has failed`. D Azahl vo de Versuech und
d Wiederherstelligszyt hänge vom jeweilige Durchlouf ab.

## Logs ohni jq untersueche

Ds letschte Envelope mit dr Python-Standardbibliothek formatiert usgä:


```sh
tail -n 1 logs/events.jsonl | python3 -m json.tool
```
Operatione und Tabelle zelle und ds letschte Event-Receipt usgä:


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
Die Befähl bi ruhende Logs usfüehre oder nach emene
glychzytige Schreibvorgang a dr letschte Zeile wiederhole; dr Verifier sälber toleriert e
unvollständigi letschti JSONL-Zeile. Während dr Abnahme ke Test-JSON per POST schicke
a `/events`: Jedes gültige JSON-Objekt wird zu nere Zuestellzeile und cha d Aanahme
vom Verifier ungültig mache.

## Fählerbehebig und zrüggbhaltets WAL

| Symptom | Erschti Prüefige und Bedeutig |
|---|---|
| Port scho belegt | Host-Listener prüefe; d obe beschribene zämeghörige Port-Literale ändere |
| Empfänger fählerhaft oder HTTP 500 | UID/GID, Berechtigunge vom Bind-Verzeichnis, freie Speicher und `logs/receiver.log` prüefe |
| Debezium louft, isch aber fählerhaft | Debezium-Logs und `/q/health` prüefe; nach usgschöpftem Sink-Retry `make recover` usfüehre |
| Ereignis im Szenario fähle | Abwychige im Bericht, Schreibvorgäng vom Empfänger, Connector-Health und Capture-Allowlists prüefe |
| Bi Update/Delete fähle alti Fälder | Replica Identity i dr tatsächlich bhaltene Datebank prüefe |
| Unerwarteti Snapshot-Azahl | Volumes, alti Logs und separat entfernti Offsets prüefe |
| Generator wyst ID zrügg | e nöii gültigi ID verwände; bisherigi Run-Beleg ufbewahre, statt sie z überschrybe |
| Seed-/Schema-Änderig schynt ignoriert | Init-Scripts loufe nume bi mene lääre PostgreSQL-Date-Volume |

D Mitgliedschaft vo dr Publication, d Replica Identity und dr Fortschritt vom
Slot prüefe:

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
Replica Identity `f` bedeutet FULL. Solang dr Verbraucher usgfalle oder blockiert isch,
cha dr Slot WAL zrüggbhalte und dr PostgreSQL-Speicher fülle. Ds
zrüggbhaltene WAL und dr Speicherplatz überwache; dä Versuechsufbau konfiguriert weder e operativi
Gränze für d WAL-Ufbewahrig no Warnmäldige derzue. Dr Slot oder d
Offsets nid als routinemässigi Wiederherstelligsmassnahm lösche: Dadür cha benötigte
Änderigsverlouf verlore gah und e erneute Snapshot erzwunge werde. Zersch
d Zuestellig wiederherstelle und dernah dr Slot-Fortschritt sowie
dr Abbau vom Rückstand prüefe. Bi vollem Speicher isch e plante Datebank-Wiederherstelligsplan
nötig; wiederholti blindi Neustarts länge nid.

## Uswirkige uf dr Produktivbetrieb

Dä Empfänger bietet weder Authentifizierig no e Begränzig vo dr Request-Grössi,
fachlechi Validierig, Log-Rotation oder Duplikatunterdrückig. Zuesätzlech liist er jede
Request-Body vollständig i dr Arbeitsspeicher. D Append-Datei isch e Nachwys und ke
Warteschlange zur Verarbeitig vo Gschäftsdate. Vor so nere Verwendig d Ufbewahrig, Backups und
d Bestätigungssemantik vo nachglagerete Systeme plane.
Benannti Volumes und Bind-Mounts si persistente Speicher, aber ke Backups.

Für dr Produktivbetrieb bruucht es begränzti Datebankberechtigunge, abgsicherete und
authentifizierte Transport, Zuegangsdateverwaltig, Überwachig vo WAL und Slots,
Speicherkapazität und Log-Ufbewahrig. Es bruucht o e dürdachti Strategie für
d Duplikatbehandlig, Transaktione, Schemaänderige und Usfäll, wo länger duure als ds
begränzte Sink-Retry-Budget.
Lokali Zuestellzyte verwände Quellzytstämpfel und Receipt-Zytstämpfel nach beschtem Bemühe;
sie hänge vo de Uhre und dr Zueordnig vo de Receipts ab. Das si Beobachtige und ke
SLA. Erfolgrichi Durchlöuf vom Versuechsufbau liefere Aahaltspünkt für dä Entwurf, ersetze
ihne aber nid.
