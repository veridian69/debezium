# Den Debezium-Versuchsaufbau offline auf Oracle Linux 8 bereitstellen

Sprache: [English](oracle-linux-8-offline-en.md) | [Schweizerdeutsch](oracle-linux-8-offline-sg.md)

So kommt Jons Versuchsaufbau auf den Offline-Host: auf einer Ubuntu-VM mit
Internetzugang auf dem Laptop bauen, ein Bundle übertragen und es auf
einem Oracle-Linux-8-Host mit bereits installiertem Docker CE und deaktiviertem
SELinux ausführen. Das Ziel benötigt weder Internetzugang noch Maven, ein JDK,
Git, einen PostgreSQL-Client oder eine Container-Registry.

Damit wird eine **neue Kopie des Versuchsaufbaus** mit einer eigenen,
vorbefüllten Datenbank und einem initialen Snapshot bereitgestellt. Die aktive
Datenbank des Laptops, der Replikations-Slot, das Offset-Volume und die
Ereignishistorie werden nicht migriert. Der Image-Export enthält
Anwendungs-Images, aber keine Docker-Volumes. Eine bestehende Installation
muss getrennt bleiben.

Datenfluss, Ereignisvertrag, Verifizierung und Wiederherstellung sind im
[Operator Guide](operator-guide-de.md) beschrieben. Alle Shell-Beispiele verwenden Bash.
Die Schritte der Reihe nach ausführen; die Rechner mit und ohne
Netzwerkzugang sind entsprechend gekennzeichnet.

## 1. Was über die Netzgrenze übertragen wird

| Bestandteil des Bundles | Zweck |
| --- | --- |
| `images.tar.gz` | PostgreSQL, Debezium Server und der gebaute Java-Empfänger |
| `project.tar.gz` | Compose-Dateien, `.env`, Init-SQL, Generator, Verifier, Quellcode und Dokumentation |
| `image-manifest.txt` | Image-IDs, Architektur und verfügbare Repository-Digests |
| `build-environment.txt` | Quellrevision und Docker-/Compose-Versionen des Build-Hosts |
| `SHA256SUMS` | Erkennt unvollständige oder beschädigte Übertragungen |
| Optional: Compose-Binärdatei/RPMs | Nur falls Voraussetzungen auf dem Ziel fehlen |

Es werden nur drei Laufzeit-Images benötigt:

```text
postgres:18.6-alpine
quay.io/debezium/server:3.7.0.Final
dbzproof/receiver:local
```

Der Generator verwendet das PostgreSQL-Image erneut: Bash und `psql` werden
aus diesem Image ausgeführt. Das Maven-Builder-Image und das Java-Basis-Image
des Empfängers werden während des Builds auf der verbundenen VM benötigt,
müssen aber nicht separat exportiert werden. Das fertige Empfänger-Image enthält
bereits Laufzeitumgebung und Abhängigkeiten.

Zum Export [`docker image save`](https://docs.docker.com/reference/cli/docker/image/save/)
und zum Import [`docker image load`](https://docs.docker.com/reference/cli/docker/image/load/) verwenden.
Diese Befehle erhalten Image-Layer und Tags. `docker export`/`docker import` arbeiten mit
Container-Dateisystemen und sind für diesen Zweck ungeeignet.

## 2. Zuerst das OL8-Ziel prüfen

Vor dem Vorbereiten des Bundles auf **Oracle Linux** folgende Informationen erfassen:

```bash
cat /etc/oracle-release
uname -m
id
docker version
docker compose version
docker compose up --help
docker compose run --help
df -h . /var/lib/docker
command -v python3.12 || true
command -v python3.11 || true
command -v python3 || true
command -v curl
command -v tar
command -v gzip
command -v sha256sum
```

Falls Docker ein anderes Datenverzeichnis verwendet, lässt es sich so ermitteln:

```bash
docker info --format '{{.DockerRootDir}}'
```

Die vollständige Version des Docker-**Servers** und die
Compose-Version notieren. „Docker CE irgendwas“ genügt für die Planung; ob die Befehle
funktionieren, hängt von den tatsächlichen Versionen ab. Das
Compose-Plugin verwenden (`docker compose`), nicht das alte Python-Programm `docker-compose`.
Prüfen, ob `up --help` die Optionen `--wait`, `--no-build` und
`--pull` enthält und ob `run --help` die Option `--pull` enthält.
Im Quellnachweis wurde Compose v5.6.0 verwendet. Das ist eine beobachtete
Quellversion und keine Behauptung, dass diese Version bereits mit OL8 getestet
wurde.

Das ausführende Konto benötigt Zugriff auf den Docker-Daemon. Falls die
Standortrichtlinien `sudo docker` vorschreiben, entweder ein freigegebenes Konto
mit Daemon-Zugriff verwenden oder den gesamten Verifier als autorisiertes
privilegiertes Konto ausführen: Der Verifier startet `docker` selbst
und fügt `sudo` nicht ein. Die Mitgliedschaft in der Docker-Gruppe gewährt
faktisch Kontrolle auf Root-Ebene. Diese Mitgliedschaft nicht leichtfertig ändern.

SELinux ist hier wie angegeben deaktiviert. Dieses
Verfahren erfordert weder eine Neuzuordnung von Labels noch Änderungen an
Sicherheitsrichtlinien. Die Ports sind an Loopback gebunden; die Host-Firewall
muss daher für den Fernzugriff auf diesen lokalen Versuchsaufbau nicht
geöffnet werden.

Ausreichend Platz für das komprimierte Bundle, die geladenen
Image-Layer, PostgreSQL-Daten, WAL und wachsende Logs einplanen. Die Grösse
des erstellten Bundles messen, statt sich auf eine Schätzung zu verlassen. Mehrere
GiB freier Speicher sind ein sinnvoller Ausgangswert, aber keine
Kapazitätsgarantie. Durch einen Slot zurückgehaltenes WAL kann bei einem
Ausfall deutlich mehr Platz belegen.

## 3. CPU-Architektur abgleichen

Auf der **Ubuntu-VM** ausführen:

```bash
uname -m
docker info --format '{{.Architecture}}'
```

| Ausgabe von `uname -m` auf dem Ziel | Container-Plattform |
| --- | --- |
| `x86_64` | `linux/amd64` |
| `aarch64` | `linux/arm64` |

Am einfachsten ist eine VM mit derselben Architektur wie OL8. Die folgenden
Anweisungen setzen das voraus. Üblicherweise laufen sowohl die Ubuntu-VM als
auch der OL8-Host auf x86; das trotzdem prüfen, statt es anzunehmen.

Bei unterschiedlichen Architekturen keine Standard-Images der VM exportieren.
Einen Builder mit passender Architektur verwenden oder Cross-Platform-Builds
und Emulation bewusst einrichten. Da das
Empfänger-Dockerfile Maven innerhalb des Build-Images ausführt, stellt `--platform`
allein keine Emulation bereit. Jedes fest versionierte Upstream-Image muss
ebenfalls für die Zielarchitektur verfügbar sein. Das vor dem Packen klären; `exec format error` auf dem Offline-Host zu entdecken, kommt reichlich spät.

## 4. Auf der verbundenen Ubuntu-VM vorbereiten und bauen

Das Projekt auf die **Ubuntu-VM** kopieren. Dabei `.env` und das
Ausführungsrecht von `generator/generate.sh` erhalten. Als Ziel eignet sich
beispielsweise `~/projects/debezium`. Die übliche Methode zur Quellübertragung verwenden; ein
gehostetes Repository ist für dieses Verfahren nicht erforderlich.

```bash
cd ~/projects/debezium
set -euo pipefail

test -f .env
test -f compose.yaml
test -f deploy/compose.offline.yaml
test -x generator/generate.sh
docker version
docker compose version
docker compose config --quiet

docker compose pull postgres debezium
docker compose build --pull receiver

docker image inspect \
  postgres:18.6-alpine \
  quay.io/debezium/server:3.7.0.Final \
  dbzproof/receiver:local \
  --format '{{.RepoTags}} {{.Os}}/{{.Architecture}} {{.Id}}'
```

Alle drei gemeldeten Architekturen mit dem Ziel abgleichen. Beim Build des
Empfängers werden dessen Unit-Tests mit Maven ausgeführt. Der Schritt
`dependency:go-offline` erfolgt nach bestem Bemühen. Allein das Kopieren dieses Caches
würde also keinen Offline-Build ermöglichen. Durch die Übertragung des
**fertigen Images** entfällt das gesamte Maven-Problem.

Die obigen Befehle starten oder setzen keine Datenbank zurück. Für eine Probe
des gesamten Ablaufs die Neuinstallationssequenz im Operator Guide auf einem
isolierten Docker-Daemon oder in einer isolierten VM durchlaufen. Dieses Projekt verwendet feste Container- und Volume-Namen. Zwei Kopien
auf demselben Daemon sind nicht allein dadurch isoliert, dass sie in
verschiedenen Verzeichnissen liegen oder unterschiedliche Compose-Projektnamen
verwenden (`-p`).

Falls sich die Image-Tags in `.env` ändern, auch die drei
expliziten Image-Referenzen in den Befehlen zum Packen und Prüfen aktualisieren. Das
Verfahren hält bewusst die für diesen Versuchsaufbau verwendeten,
festgelegten Versionen fest.

## 5. Ein vollständiges Transfer-Bundle erstellen

Weiterhin auf der **Ubuntu-VM**, im Projekt-Stammverzeichnis:

```bash
set -euo pipefail
DBZ_BUNDLE=$(mktemp -d /tmp/dbzproof-offline.XXXXXX)
printf 'Bundle directory: %s\n' "$DBZ_BUNDLE"

docker image save \
  postgres:18.6-alpine \
  quay.io/debezium/server:3.7.0.Final \
  dbzproof/receiver:local | gzip > "$DBZ_BUNDLE/images.tar.gz"

docker image inspect \
  postgres:18.6-alpine \
  quay.io/debezium/server:3.7.0.Final \
  dbzproof/receiver:local \
  --format '{{.RepoTags}} {{.Os}}/{{.Architecture}} id={{.Id}} digests={{json .RepoDigests}}' \
  > "$DBZ_BUNDLE/image-manifest.txt"

{
  date -u +%FT%TZ
  if test -d .git; then
    git rev-parse HEAD
    git status --short
  fi
  uname -m
  docker version
  docker compose version
} > "$DBZ_BUNDLE/build-environment.txt"

tar --exclude='receiver/target' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    -czf "$DBZ_BUNDLE/project.tar.gz" \
    .env compose.yaml Makefile README.md README-de.md README-en.md README-sg.md \
    postgres debezium receiver generator verify docs deploy

(
  cd "$DBZ_BUNDLE"
  sha256sum images.tar.gz project.tar.gz \
    image-manifest.txt build-environment.txt > SHA256SUMS
  ls -lh
)
```

`set -o pipefail` ist wichtig: Ein fehlgeschlagener Image-Export darf nicht durch einen
erfolgreichen gzip-Schritt wie ein gültiges Bundle aussehen. Diese
Shell geöffnet lassen oder den ausgegebenen Pfad notieren; `DBZ_BUNDLE` ist nur eine
Shell-Variable.

Das Projektarchiv enthält die aktuellen Dateien einschliesslich nicht
committeter Dokumentation. Es wird nicht stillschweigend ein älteres
`git archive HEAD` verwendet. Die aufgezeichnete Git-Revision allein definiert das Archiv
daher nicht; die Prüfsumme legt den tatsächlich übertragenen Inhalt fest.
Ausgeschlossen werden bewusst `.git`, Host-Ereignislogs, Ausführungsberichte,
lokale Datenbank-Volumes und Maven-Ausgaben des Hosts.

Das aktuelle `.env` enthält Demo-Zugangsdaten (`dbz`/`dbz`);
`debezium/application.properties` enthält dieselben Zugangsdaten. Beide Dateien vor der Übertragung
prüfen. Falls sie später echte Zugangsdaten enthalten, das Bundle entsprechend
behandeln: nicht per E-Mail versenden oder in einem gewöhnlichen freigegebenen
Verzeichnis ablegen.

SHA-256-Prüfsummen erkennen Beschädigungen, aber keinen böswilligen Austausch
von Archiv und Prüfsumme zugleich. Den freigegebenen Weg über
Wechselmedien oder Dateiübertragung verwenden.

## 6. Das Verzeichnis übertragen

**Alle Dateien aus dem ausgegebenen Bundle-Verzeichnis** nach OL8 übertragen,
zum Beispiel nach:

```text
/home/jon/dbzproof-transfer/
```

Ein eingehängtes USB-Laufwerk, einen kontrollierten Dateiablageort
oder eine interne Netzwerkkopie verwenden. „Kein Internet“ bedeutet nicht zwingend
„kein internes SSH“. Falls internes SSH verfügbar ist, geht das auf der
Ubuntu-VM beispielsweise so:

```bash
scp -r "$DBZ_BUNDLE" jon@ol8-host:/home/jon/dbzproof-transfer-bundle
```

Host und Konto ersetzen. Auf OL8 das tatsächliche Zielverzeichnis mit
`SHA256SUMS` verwenden, nicht dessen übergeordnetes Verzeichnis.
Keine der beiden Übertragungsmethoden muss von OL8 aus eine öffentliche
Registry kontaktieren.

## 7. Auf dem Offline-OL8 laden und konfigurieren

Auf **Oracle Linux** zuerst die Übertragung prüfen:

```bash
set -euo pipefail
cd /home/jon/dbzproof-transfer
sha256sum -c SHA256SUMS
gzip -t images.tar.gz
tar -tzf project.tar.gz
cat image-manifest.txt
```

Jede Prüfsumme muss mit `OK` bestätigt werden. Bei Verwendung des SSH-Beispiels den
Transferpfad anpassen. Vor dem Extrahieren die Archivliste prüfen.

Die Images laden und die Anwendung in ein **neues** Verzeichnis extrahieren:

```bash
docker image load --input images.tar.gz

mkdir -p "$HOME/apps"
DBZ_INSTALL="$HOME/apps/dbzproof"
test ! -e "$DBZ_INSTALL"
mkdir "$DBZ_INSTALL"
tar -xzf project.tar.gz -C "$DBZ_INSTALL"
cd "$DBZ_INSTALL"

mkdir -p logs runs
chmod 0755 generator/generate.sh
cp deploy/compose.offline.yaml compose.override.yaml

sed -i "s/^HOST_UID=.*/HOST_UID=$(id -u)/" .env
sed -i "s/^HOST_GID=.*/HOST_GID=$(id -g)/" .env
chmod 0600 .env
unset COMPOSE_FILE
```

Die Dateien mit dem Konto extrahieren, das den Versuchsaufbau betreiben wird. `logs/` und `runs/` müssen für die soeben erfasste UID/GID
beschreibbar sein. Die Installation nicht als Root einrichten und dann mittendrin das Konto
wechseln. Benannte Volumes verwaltet Docker; den Eigentümer von Docker-internen
Volume-Verzeichnissen nicht mit `chown` ändern.

Der mitgelieferte [Offline-Override](../deploy/compose.offline.yaml) setzt
`pull_policy: never` für **alle vier Dienste**, einschliesslich des Generators. Wird er als
`compose.override.yaml` kopiert, erkennen ihn normale Compose-Befehle und der Verifier
automatisch. Die Mounts, benannten Volumes, Netzwerke und Healthchecks der
Basisdatei bleiben erhalten. Die Build-Definition des Empfängers wird dadurch
nicht entfernt; der Start muss deshalb zusätzlich `--no-build` verwenden.

Die IDs der geladenen Images mit `image-manifest.txt` vergleichen:

```bash
docker image inspect \
  postgres:18.6-alpine \
  quay.io/debezium/server:3.7.0.Final \
  dbzproof/receiver:local \
  --format '{{.RepoTags}} {{.Os}}/{{.Architecture}} {{.Id}}'

docker compose --profile tools config --quiet
docker compose --profile tools config --images
docker compose --profile tools config
```

Der letzte Befehl gibt aufgelöste Zugangsdaten aus. Die Ausgabe lokal prüfen
und nicht in ein uneingeschränkt zugängliches Ticket kopieren. Bei jedem Dienst prüfen, dass
`pull_policy: never` gesetzt ist, die Host-Ports an Loopback gebunden sind und
`logs`/`runs` auf diese Installation verweisen. Die Einrichtung entfernt
`COMPOSE_FILE`, damit die automatische Erkennung des Overrides nicht umgangen
werden kann. In einer neuen Shell wiederholen, falls diese Variable normalerweise gesetzt
ist. Kein fremdes Override in diesem Verzeichnis liegen lassen.

## 8. Ohne Build oder Pull starten

Auf **Oracle Linux** im Stammverzeichnis der Installation ausführen:

```bash
docker compose up -d --wait --no-build --pull never postgres receiver debezium
docker compose ps
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8081/q/health
```

**`make up` nicht auf dem Offline-Host verwenden.** Dessen Ziel
`up` hängt von `build` ab. Dieses führt `docker compose build receiver` aus und
benötigt möglicherweise Upstream-Images und Maven-Downloads. Für `make build`
gilt dasselbe. Den expliziten Befehl oben verwenden, wenn
Container erstellt oder neu erstellt werden müssen.
[`docker compose up`](https://docs.docker.com/reference/cli/docker/compose/up/) beschreibt
`--no-build`, die Pull-Richtlinie und das Warten auf Healthchecks.

Beim ersten Start initialisiert PostgreSQL das benannte Volume, erstellt und
befüllt die Schemas und richtet die Publication ein. Debezium wartet, bis
PostgreSQL und der Empfänger gesund sind, und erstellt danach Snapshots der
drei erfassten Tabellen. Es sind 15 `r`-Umschläge in `logs/events.jsonl` zu erwarten
(3 Kunden, 4 Bestellungen, 8 Positionen).

Dies ist ein lokaler PostgreSQL-Versuchsaufbau, der **auf Oracle
Linux gehostet wird**. Es handelt sich nicht um eine Oracle-Database-
Connector-Bereitstellung. Oracle-Client-Bibliotheken kommen nicht zum Einsatz.

## 9. Die Installation verifizieren

### Empfohlen: Python 3.12 auf dem Host

Der Versuchsaufbau wurde mit Python 3.12 verifiziert und verwendet
ausschliesslich die Standardbibliothek. Ein `pip install`-Schritt ist nicht nötig.
Den Interpreter ausdrücklich prüfen:

```bash
python3.12 --version
python3.12 verify/verify.py all
```

Auf dieser frischen Installation zuerst den vollständigen Verifier ausführen,
erst danach die Datenbank manuell ändern oder Beispiele generieren. Er
schreibt Nachweise nach `runs/`, erzeugt Szenario-Zeilen, stoppt und startet
den Empfänger absichtlich neu und startet den gesamten Stack neu. Dies ist
eine Abnahmeprüfung und kein passiver Monitoring-Befehl.

Für eine kurze Health-Prüfung genügt:

```bash
python3.12 verify/verify.py health
```

`make verify` ruft `python3` auf. Nur verwenden, wenn dieses Programm
der geeignete Interpreter ist. Weder das System-Python von OL8 noch
`/usr/libexec/platform-python` ersetzen. Einen versionierten Python-Befehl verwenden. Oracle stellt
Python 3.12 auf OL8.10 und Python 3.11 ab OL8.8 bereit. Details stehen in
der [Oracle-Dokumentation zur Python-Installation](https://docs.oracle.com/en/operating-systems/oracle-linux/8/python/python-InstallingPython.html).
Die für dieses Projekt dokumentierte und zuvor getestete Wahl ist Version
3.12.

Falls Python 3.12 fehlt, sollte die Systemadministration es über das
OL8-Paket-Repository des Standorts oder einen freigegebenen Offline-RPM-Prozess
bereitstellen. RPMs in einer verbundenen OL8-Umgebung vorbereiten, die
hinsichtlich Zielarchitektur, Minor-Release und Repository-Konfiguration
übereinstimmt. Dafür **keine Ubuntu-deb-Pakete** herunterladen.

Auf einem OL8.10-Staging-System mit den passenden Repositories und bereits
konfiguriertem DNF-Download-Plugin kann die Administration die Pakete wie
folgt zusammenstellen:

```bash
mkdir -p python-rpms
dnf download --resolve --alldeps --destdir ./python-rpms python3.12
```

Dieses Verzeichnis übertragen und die Pakete auf dem Ziel bei deaktivierten
Repositories installieren:

```bash
sudo dnf --disablerepo='*' install ./python-rpms/*.rpm
```

Dies sind bedingte Hinweise und keine universelle RPM-Liste. Die Abhängigkeiten
für das tatsächliche Ziel auf Vollständigkeit prüfen, Herstellersignaturen
beibehalten und fehlende freigegebene Signaturschlüssel hinzufügen.
`--nogpgcheck` nicht hinzufügen. Bei einem
älteren OL8-Minor-Release kann zuerst ein freigegebenes Betriebssystem-Update
erforderlich sein.

### Ohne Python: manueller Smoke-Test

Der Stack kann ohne Python ausgeführt werden; nur die automatische
Verifizierung benötigt Python. Nach der Health-Prüfung den
Generator mit einer neuen Kennung ausführen:

```bash
RUN_ID=ol8-smoke-001 docker compose --profile tools run --rm --pull never generator
tail -n 20 logs/events.jsonl
cat runs/ol8-smoke-001/manifest.json
cat runs/ol8-smoke-001/expected.jsonl
docker compose exec -T postgres psql -U dbz -d appdb \
  -c "select run_id, status from bulk.batch_jobs order by id;"
```

Es sollten sieben erwartete erfasste Ereignisse erscheinen. Der Bulk-Marker
ist in der Datenbank vorhanden, ohne dass entsprechende `bulk`-Ereignisse
ausgegeben werden. Dieser Smoke-Test ersetzt nicht die automatisierten
Abnahmeprüfungen für Ausfälle und Neustarts. Jedes Mal eine
neue Ausführungskennung verwenden; Kennungen setzen einen Lauf weder zurück noch starten
sie ihn erneut.

## 10. Falls das Compose-Plugin fehlt

Docker Engine und Compose sind getrennte Komponenten. Eine vorhandene
Docker-CE-Installation belegt nicht, dass das Plugin installiert ist. Falls
`docker compose` bereits mit den erforderlichen Optionen funktioniert, diesen
Abschnitt überspringen.

Das am Standort freigegebene RPM `docker-compose-plugin` mit allen
Abhängigkeiten bevorzugen. Alternativ kann die Administration eine
offizielle Compose-Release-Binärdatei für die **Zielarchitektur** übertragen
und manuell installieren. Docker beschreibt Speicherorte und manuelle
Installation in der [Installationsanleitung für das Compose-Plugin](https://docs.docker.com/compose/install/linux/).

Auf dem verbundenen Rechner ein geprüftes Release und dessen
veröffentlichte Prüfsummen aus den [Docker-Compose-Releases](https://github.com/docker/compose/releases)
herunterladen. Für x86-OL8 `docker-compose-linux-x86_64` und für ARM-OL8
`docker-compose-linux-aarch64` wählen. Die Datei erst nach Prüfung der
Herstellerprüfsumme in das Transfer-Manifest aufnehmen. Kein undokumentiertes
„latest“ wählen.

Für eine übertragene x86-Binärdatei im aktuellen Verzeichnis kann die
Administration Folgendes ausführen:

```bash
sudo install -d -m 0755 /usr/local/lib/docker/cli-plugins
sudo install -m 0755 docker-compose-linux-x86_64 \
  /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
docker compose up --help
```

Für ARM den ARM-Dateinamen verwenden. Vor dem Einsatz die Kompatibilität
mit dem Docker-Daemon auf dem tatsächlichen OL8-Host prüfen. Die manuelle Installation der Binärdatei bietet keine
automatischen Updates; ihre Version im Bereitstellungsprotokoll festhalten.

## 11. Regelmässige Arbeiten auf OL8

| Aufgabe | Befehl im Installationsverzeichnis |
| --- | --- |
| Erstellen/neu erstellen und auf Healthchecks warten | `docker compose up -d --wait --no-build --pull never postgres receiver debezium` |
| Status anzeigen | `docker compose ps` |
| Diagnosemeldungen verfolgen | `docker compose logs -f --tail=100` |
| Ereignisse verfolgen | `tail -f logs/events.jsonl` |
| Anhalten und Zustand erhalten | `docker compose stop` |
| Vorhandene, angehaltene Container starten | `docker compose start` |
| Vorhandene Container neu starten | `docker compose restart` |
| Erschöpften Debezium-Engine-Prozess wiederherstellen | `docker compose restart debezium` |
| Weiteres Szenario erzeugen | `RUN_ID=ol8-run-002 docker compose --profile tools run --rm --pull never generator` |

`start` setzt vorhandene Container voraus. Nach `down` den
Befehl zum Erstellen/Neuerstellen verwenden. `restart` übernimmt geänderte
Compose-Umgebungseinstellungen nicht. Nach Änderungen dieser
Einstellungen den Befehl zum Erstellen/Neuerstellen verwenden.

Die erschöpfte Engine kann ihren Container **laufend, aber nicht gesund**
zurücklassen. Auf einem Offline-Host verhält sich das wie auf dem Laptop:
Zuerst den Empfänger wiederherstellen, danach Debezium ausdrücklich neu starten. Eine Restart-Policy, die auf den Container-Exit
reagiert, behebt diesen Fehlerfall nicht. Diese Bereitstellung richtet keinen
Autostart nach einem Reboot ein. Nach Wartungsarbeiten am Host den Zustand prüfen
und die benötigten Dienste bewusst starten.

Die benannten Volumes `dbzproof_pg_data` und `dbzproof_debezium_data` zusammen mit dem
Installationsprotokoll aufbewahren. `docker compose down` behält sie bei;
`docker compose down -v` und `make reset` löschen sie. Reset nicht verwenden, um einen
vorübergehenden Zustellausfall zu beheben.

## 12. Offline-Fehlerbehebung

| Symptom | Wahrscheinliche Ursache und nächster Schritt |
| --- | --- |
| Compose versucht Images abzurufen | Falsches Arbeitsverzeichnis, automatischer Override fehlt, `COMPOSE_FILE` umgeht ihn oder ein expliziter Befehl fordert einen Pull an. `docker compose --profile tools config` prüfen. |
| Der Empfänger-Build versucht Downloads | Es wurde `make up`, `make build` oder `--build` verwendet. Den expliziten Startbefehl mit `--no-build --pull never` verwenden. |
| Image bei deaktivierten Pulls nicht gefunden | Tag stimmt nicht oder Image fehlt im übertragenen Archiv. `.env`, `config --images` und `docker image ls` vergleichen; das Bundle auf der verbundenen VM korrigieren. |
| `exec format error` | Architektur stimmt nicht überein. Auf einer passenden Architektur neu bauen und exportieren; ein geladenes Image wird dadurch nicht konvertiert. |
| Unbekannte Option oder `pull_policy` wird abgelehnt | Compose ist zu alt oder es wird das falsche Programm verwendet. Über den freigegebenen Offline-Weg ein kompatibles Plugin bereitstellen. |
| Keine Schreibberechtigung für Logs/Runs | Falsche Host-UID/GID, Dateien wurden von einem anderen Konto extrahiert oder das Dateisystem ist schreibgeschützt. `id`, `.env` und `ls -ld logs runs` prüfen. SELinux ist in dieser Umgebung deaktiviert. |
| Port bereits belegt | Ein vorhandener Dienst verwendet Port 5432, 8080 oder 8081. `ss -ltn` prüfen; die URLs des Verifiers sind fest codiert und müssen vor einer Portänderung berücksichtigt werden. |
| PostgreSQL startet mit unerwartet alten Daten | Das feste benannte Volume existiert bereits. Anhalten und den Zustand untersuchen; ein neues Quellverzeichnis erzeugt keinen neuen Volume-Namen. |
| Snapshot-Verifier schlägt fehl | Kein frischer Seed-/Snapshot-Verlauf, Logs wurden entfernt, während Offsets erhalten blieben, oder der Start ist fehlgeschlagen. Vor einem destruktiven Reset den Operator Guide lesen. |
| Debezium läuft, ist aber nicht gesund | Den Zustand des Empfängers und die Debezium-Logs prüfen. Nach ausgeschöpften Wiederholungsversuchen muss Debezium ausdrücklich neu gestartet werden, sobald der Empfänger wiederhergestellt ist. |
| `/var/lib/docker` ist voll | Das vom PostgreSQL-Slot zurückgehaltene WAL sowie den Speicherverbrauch von Docker und Logs prüfen. Die Erfassung wiederherstellen; WAL-Dateien nicht manuell löschen. |

Nützliche Diagnosen, für die kein Internetzugang erforderlich ist:

```bash
docker compose ps -a
docker compose logs --tail=150 postgres receiver debezium
docker image ls
docker volume ls
docker system df
df -h
ls -ld logs runs
ss -ltn
```

`docker system prune --volumes` nicht als schnelle Fehlerbehebung ausführen. Dadurch können
Daten dieses Versuchsaufbaus oder anderer Installationen gelöscht
werden.

## 13. Updates und Protokollierung

Bei Änderungen am Empfänger: auf Ubuntu neu bauen, das neue Empfänger-Image
exportieren, seine Image-ID notieren, auf OL8 übertragen und laden, dann den
Empfänger mit `--no-build --pull never` neu erstellen. Da
`dbzproof/receiver:local` wiederverwendet wird, ist das Tag veränderlich. Image-IDs notieren,
damit Releases unterscheidbar bleiben, und das vorherige Image-Archiv
für ein Rollback aufbewahren.

Bei Änderungen der PostgreSQL- oder Debezium-Version ein separates,
geprüftes Bundle erstellen und vor der Bereitstellung testen. Ein
PostgreSQL-Major-Upgrade ist kein gewöhnlicher Image-Tausch mit dem
bestehenden Daten-Volume. Quellkonfiguration, Image-Versionen und persistenter
Zustand müssen zueinander passen; ein Image-Rollback macht Änderungen am
Datenbank- oder Zustandsformat allein nicht rückgängig.

Die Transfer-Prüfsummendatei, das Image-Manifest, die
Build-Umgebung, die tatsächliche OL8-Version und -Architektur, die
Docker-/Compose-Versionen sowie den abschliessenden Bericht `runs/verify-*.json`
mit den Bereitstellungsnotizen aufbewahren. Für diese Dokumentationsänderung wurde der
Compose-Override auf dem Entwicklungsrechner geprüft. Das Image-Bundle wurde
auf dem OL8-Host noch nicht erstellt oder bereitgestellt.
