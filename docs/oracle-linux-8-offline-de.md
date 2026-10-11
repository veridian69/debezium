# Die Debezium-Demonstration offline auf Oracle Linux 8 bereitstellen

Sprache: [English](oracle-linux-8-offline-en.md)

Dieses Bereitstellungsszenario entspricht Jons Aufbau: Erstellen auf einer
Ubuntu-VM mit Internetzugang auf dem Laptop, ein Bundle übertragen und es auf
einem Oracle-Linux-8-Host mit bereits installiertem Docker CE und deaktiviertem
SELinux ausführen. Das Ziel benötigt weder Internetzugang noch Maven, ein JDK,
Git, einen PostgreSQL-Client oder eine Container-Registry.

Damit wird eine **neue Kopie der Demonstrationsumgebung** mit einer eigenen,
vorbefüllten Datenbank und einem initialen Snapshot bereitgestellt. Die aktive
Datenbank des Laptops, der Replikations-Slot, das Offset-Volume und die
Ereignishistorie werden nicht migriert. Der Image-Export enthält
Anwendungs-Images, aber keine Docker-Volumes. Eine bestehende Installation
muss getrennt bleiben.

Weitere Informationen zum Datenfluss, Ereignisvertrag, zu den
Verifizierungsdetails und zum Wiederherstellungsverhalten stehen im
[Betreiberhandbuch](operator-guide.md). Alle Shell-Beispiele verwenden Bash.
Führen Sie die Schritte der Reihe nach aus; die Rechner mit und ohne
Netzwerkzugang sind entsprechend gekennzeichnet.

## 1. Was über die Netzgrenze übertragen wird

| Bestandteil des Bundles | Zweck |
| --- | --- |
| `images.tar.gz` | PostgreSQL, Debezium Server und der gebaute Java-Receiver |
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
des Receivers werden während des Builds auf der verbundenen VM benötigt,
müssen aber nicht separat exportiert werden. Das fertige Receiver-Image enthält
bereits Laufzeitumgebung und Abhängigkeiten.

Verwenden Sie [`docker image save`](https://docs.docker.com/reference/cli/docker/image/save/)
und [`docker image load`](https://docs.docker.com/reference/cli/docker/image/load/).
Diese Befehle erhalten Image-Layer und Tags. `docker export`/`docker import` arbeiten mit
Container-Dateisystemen und sind für diesen Zweck ungeeignet.

## 2. Zuerst das OL8-Ziel prüfen

Erfassen Sie auf **Oracle Linux** die folgenden Informationen, bevor Sie das
Bundle vorbereiten:

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

Falls Docker ein anderes Datenverzeichnis verwendet, ermitteln Sie es mit:

```bash
docker info --format '{{.DockerRootDir}}'
```

Notieren Sie die vollständige Version des Docker-**Servers** und die
Compose-Version. „Docker CE irgendwas“ genügt für die Planung; ob die Befehle
funktionieren, hängt von den tatsächlichen Versionen ab. Verwenden Sie das
Compose-Plugin (`docker compose`), nicht das alte Python-Programm `docker-compose`.
Prüfen Sie, ob `up --help` die Optionen `--wait`, `--no-build` und
`--pull` enthält und ob `run --help` die Option `--pull` enthält.
Im Quellnachweis wurde Compose v5.6.0 verwendet. Das ist eine beobachtete
Quellversion und keine Behauptung, dass diese Version bereits mit OL8 getestet
wurde.

Das ausführende Konto benötigt Zugriff auf den Docker-Daemon. Falls die
Richtlinien Ihres Standorts `sudo docker` vorschreiben, verwenden Sie entweder ein
freigegebenes Konto mit Daemon-Zugriff oder führen Sie den gesamten Verifier
als autorisiertes privilegiertes Konto aus: Der Verifier startet `docker` selbst
und fügt `sudo` nicht ein. Die Mitgliedschaft in der Docker-Gruppe gewährt
faktisch Kontrolle auf Root-Ebene. Ändern Sie sie nicht leichtfertig.

Wie angegeben wird vorausgesetzt, dass SELinux deaktiviert ist. Dieses
Verfahren erfordert weder eine Neuzuordnung von Labels noch Änderungen an
Sicherheitsrichtlinien. Die Ports sind an Loopback gebunden; die Host-Firewall
muss daher für den Fernzugriff auf diese lokale Demonstrationsumgebung nicht
geöffnet werden.

Planen Sie ausreichend Platz für das komprimierte Bundle, die geladenen
Image-Layer, PostgreSQL-Daten, WAL und wachsende Logs ein. Messen Sie die Größe
des erstellten Bundles, statt sich auf eine Schätzung zu verlassen. Mehrere
GiB freier Speicher sind ein sinnvoller Ausgangswert, aber keine
Kapazitätsgarantie. Durch einen Slot zurückgehaltenes WAL kann bei einem
Ausfall deutlich mehr Platz belegen.

## 3. CPU-Architektur abgleichen

Führen Sie auf der **Ubuntu-VM** Folgendes aus:

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
auch der OL8-Host auf x86; prüfen Sie das dennoch, statt es anzunehmen.

Bei unterschiedlichen Architekturen dürfen Sie nicht die Standard-Images der
VM exportieren. Verwenden Sie einen Builder mit passender Architektur oder
richten Sie Cross-Platform-Builds und Emulation bewusst ein. Da das
Receiver-Dockerfile Maven innerhalb des Build-Images ausführt, stellt `--platform`
allein keine Emulation bereit. Jedes fest versionierte Upstream-Image muss
ebenfalls für die Zielarchitektur verfügbar sein. Klären Sie das vor dem
Packen; `exec format error` auf dem Offline-Host zu entdecken, kommt reichlich spät.

## 4. Auf der verbundenen Ubuntu-VM vorbereiten und bauen

Kopieren Sie dieses Projekt auf die **Ubuntu-VM**. Erhalten Sie dabei `.env`
und das Ausführungsrecht von `generator/generate.sh`. Legen Sie es beispielsweise unter
`~/projects/debezium` ab. Verwenden Sie Ihre übliche Methode für die Quellübertragung; ein
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

Prüfen Sie alle drei gemeldeten Architekturen anhand des Ziels. Beim Build des
Receivers werden dessen Unit-Tests mit Maven ausgeführt. Der Schritt
`dependency:go-offline` ist nur eine Best-Effort-Maßnahme. Allein das Kopieren dieses Caches
würde also keinen Offline-Build ermöglichen. Durch die Übertragung des
**fertigen Images** entfällt das gesamte Maven-Problem.

Die obigen Befehle starten oder setzen keine Datenbank zurück. Wenn Sie den
gesamten Ablauf proben möchten, folgen Sie der Neuinstallationssequenz im
Betreiberhandbuch auf einem isolierten Docker-Daemon oder in einer isolierten
VM. Dieses Projekt verwendet feste Container- und Volume-Namen. Zwei Kopien
auf demselben Daemon sind nicht allein dadurch isoliert, dass sie in
verschiedenen Verzeichnissen liegen oder unterschiedliche Compose-Projektnamen
verwenden (`-p`).

Falls sich die Image-Tags in `.env` ändern, aktualisieren Sie auch die drei
expliziten Image-Referenzen in den Befehlen zum Packen und Prüfen. Das
Verfahren hält bewusst die für diese Demonstrationsumgebung verwendeten,
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
    .env compose.yaml Makefile README.md README-de.md README-en.md \
    postgres debezium receiver generator verify docs deploy

(
  cd "$DBZ_BUNDLE"
  sha256sum images.tar.gz project.tar.gz \
    image-manifest.txt build-environment.txt > SHA256SUMS
  ls -lh
)
```

`set -o pipefail` ist wichtig: Ein fehlgeschlagener Image-Export darf nicht durch einen
erfolgreichen gzip-Schritt wie ein gültiges Bundle aussehen. Lassen Sie diese
Shell geöffnet oder notieren Sie den ausgegebenen Pfad; `DBZ_BUNDLE` ist nur eine
Shell-Variable.

Das Projektarchiv enthält die aktuellen Dateien einschließlich nicht
committeter Dokumentation. Es wird nicht stillschweigend ein älteres
`git archive HEAD` verwendet. Die aufgezeichnete Git-Revision allein definiert das Archiv
daher nicht; die Prüfsumme legt den tatsächlich übertragenen Inhalt fest.
Ausgeschlossen werden bewusst `.git`, Host-Ereignislogs, Ausführungsberichte,
lokale Datenbank-Volumes und Maven-Ausgaben des Hosts.

Das aktuelle `.env` enthält Demo-Zugangsdaten (`dbz`/`dbz`);
`debezium/application.properties` enthält dieselben Zugangsdaten. Prüfen Sie beide Dateien vor der
Übertragung. Falls sie später echte Zugangsdaten enthalten, behandeln Sie das
Bundle entsprechend: Versenden Sie es nicht per E-Mail und legen Sie es nicht
in einem gewöhnlichen freigegebenen Verzeichnis ab.

SHA-256-Prüfsummen erkennen Beschädigungen, aber keinen böswilligen Austausch
von Archiv und Prüfsumme zugleich. Verwenden Sie den freigegebenen Weg über
Wechselmedien oder Dateiübertragung.

## 6. Das Verzeichnis übertragen

Übertragen Sie **alle Dateien aus dem ausgegebenen Bundle-Verzeichnis** nach
OL8, zum Beispiel nach:

```text
/home/jon/dbzproof-transfer/
```

Verwenden Sie ein eingehängtes USB-Laufwerk, einen kontrollierten Dateiablageort
oder eine interne Netzwerkkopie. „Kein Internet“ bedeutet nicht zwingend
„kein internes SSH“. Falls internes SSH verfügbar ist, können Sie auf der
Ubuntu-VM beispielsweise Folgendes ausführen:

```bash
scp -r "$DBZ_BUNDLE" jon@ol8-host:/home/jon/dbzproof-transfer-bundle
```

Ersetzen Sie Host und Konto. Verwenden Sie auf OL8 das tatsächliche
Zielverzeichnis, das `SHA256SUMS` enthält, nicht dessen übergeordnetes Verzeichnis.
Keine der beiden Übertragungsmethoden muss von OL8 aus eine öffentliche
Registry kontaktieren.

## 7. Auf dem Offline-OL8 laden und konfigurieren

Prüfen Sie die Übertragung zuerst auf **Oracle Linux**:

```bash
set -euo pipefail
cd /home/jon/dbzproof-transfer
sha256sum -c SHA256SUMS
gzip -t images.tar.gz
tar -tzf project.tar.gz
cat image-manifest.txt
```

Jede Prüfsumme muss mit `OK` bestätigt werden. Passen Sie den Transferpfad
an, falls Sie das SSH-Beispiel verwendet haben. Prüfen Sie die Archivliste,
bevor Sie Dateien extrahieren.

Laden Sie die Images und extrahieren Sie die Anwendung in ein **neues**
Verzeichnis:

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

Extrahieren Sie die Dateien als das Konto, das die Demonstrationsumgebung
betreiben wird. `logs/` und `runs/` müssen für die soeben erfasste UID/GID
beschreibbar sein. Richten Sie die Installation nicht als Root ein, um dann
mittendrin das Konto zu wechseln. Benannte Volumes verwaltet Docker; ändern
Sie den Eigentümer von Docker-internen Volume-Verzeichnissen nicht mit
`chown`.

Der mitgelieferte [Offline-Override](../deploy/compose.offline.yaml) setzt
`pull_policy: never` für **alle vier Dienste**, einschließlich des Generators. Wird er als
`compose.override.yaml` kopiert, erkennen ihn normale Compose-Befehle und der Verifier
automatisch. Die Mounts, benannten Volumes, Netzwerke und Healthchecks der
Basisdatei bleiben erhalten. Die Build-Definition des Receivers wird dadurch
nicht entfernt; der Start muss deshalb zusätzlich `--no-build` verwenden.

Vergleichen Sie die IDs der geladenen Images mit `image-manifest.txt`:

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

Der letzte Befehl gibt aufgelöste Zugangsdaten aus. Prüfen Sie die Ausgabe
lokal und fügen Sie sie nicht in ein Ticket ein, das uneingeschränkt
zugänglich ist. Vergewissern Sie sich bei jedem Dienst, dass
`pull_policy: never` gesetzt ist, die Host-Ports an Loopback gebunden sind und
`logs`/`runs` auf diese Installation verweisen. Die Einrichtung entfernt
`COMPOSE_FILE`, damit die automatische Erkennung des Overrides nicht umgangen
werden kann. Wiederholen Sie das in einer neuen Shell, wenn Sie diese
Variable normalerweise setzen. Lassen Sie kein nicht zugehöriges Override in
diesem Verzeichnis liegen.

## 8. Ohne Build oder Pull starten

Führen Sie den folgenden Befehl auf **Oracle Linux** im Stammverzeichnis der
Installation aus:

```bash
docker compose up -d --wait --no-build --pull never postgres receiver debezium
docker compose ps
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8081/q/health
```

**Verwenden Sie `make up` nicht auf dem Offline-Host.** Dessen Ziel
`up` hängt von `build` ab. Dieses führt `docker compose build receiver` aus und
benötigt möglicherweise Upstream-Images und Maven-Downloads. Für `make build`
gilt dasselbe. Verwenden Sie den expliziten Befehl oben immer dann, wenn
Container erstellt oder neu erstellt werden müssen.
[`docker compose up`](https://docs.docker.com/reference/cli/docker/compose/up/) beschreibt
`--no-build`, die Pull-Richtlinie und das Warten auf Healthchecks.

Beim ersten Start initialisiert PostgreSQL das benannte Volume, erstellt und
befüllt die Schemas und richtet die Publication ein. Debezium wartet, bis
PostgreSQL und der Receiver gesund sind, und erstellt danach Snapshots der
drei erfassten Tabellen. Es sind 15 `r`-Umschläge in `logs/events.jsonl` zu erwarten
(3 Kunden, 4 Bestellungen, 8 Positionen).

Dies ist eine lokale PostgreSQL-Demonstrationsumgebung, die **auf Oracle
Linux gehostet wird**. Es handelt sich nicht um eine Oracle-Database-
Connector-Bereitstellung. Oracle-Client-Bibliotheken kommen nicht zum Einsatz.

## 9. Die Installation verifizieren

### Empfohlen: Python 3.12 auf dem Host

Die Demonstrationsumgebung wurde mit Python 3.12 verifiziert und verwendet
ausschließlich die Standardbibliothek. Ein `pip install`-Schritt ist nicht nötig.
Prüfen Sie den Interpreter ausdrücklich:

```bash
python3.12 --version
python3.12 verify/verify.py all
```

Führen Sie den vollständigen Verifier aus, bevor Sie diese frische
Installation manuell in der Datenbank ändern oder Beispiele generieren. Er
schreibt Nachweise nach `runs/`, erzeugt Szenario-Zeilen, stoppt und startet
den Receiver absichtlich neu und startet den gesamten Stack neu. Dies ist
eine Abnahmeprüfung und kein passiver Monitoring-Befehl.

Für eine kurze Health-Prüfung genügt:

```bash
python3.12 verify/verify.py health
```

`make verify` ruft `python3` auf. Verwenden Sie es nur, wenn dieses Programm der
geeignete Interpreter ist. Ersetzen Sie weder das System-Python von OL8 noch
`/usr/libexec/platform-python`. Verwenden Sie einen versionierten Python-Befehl. Oracle stellt
Python 3.12 auf OL8.10 und Python 3.11 ab OL8.8 bereit. Details stehen in
der [Oracle-Dokumentation zur Python-Installation](https://docs.oracle.com/en/operating-systems/oracle-linux/8/python/python-InstallingPython.html).
Die für dieses Projekt dokumentierte und zuvor getestete Wahl ist Version
3.12.

Falls Python 3.12 fehlt, sollte die Systemadministration es über das
OL8-Paket-Repository des Standorts oder einen freigegebenen Offline-RPM-Prozess
bereitstellen. Bereiten Sie RPMs in einer verbundenen OL8-Umgebung vor, die
hinsichtlich Zielarchitektur, Minor-Release und Repository-Konfiguration
übereinstimmt. Laden Sie dafür **keine Ubuntu-deb-Pakete** herunter.

Auf einem OL8.10-Staging-System mit den passenden Repositories und bereits
konfiguriertem DNF-Download-Plugin kann die Administration die Pakete wie
folgt zusammenstellen:

```bash
mkdir -p python-rpms
dnf download --resolve --alldeps --destdir ./python-rpms python3.12
```

Übertragen Sie dieses Verzeichnis und installieren Sie die Pakete auf dem Ziel
bei deaktivierten Repositories:

```bash
sudo dnf --disablerepo='*' install ./python-rpms/*.rpm
```

Dies sind bedingte Hinweise und keine universelle RPM-Liste. Prüfen Sie die
Vollständigkeit der Abhängigkeiten für das tatsächliche Ziel, behalten Sie die
Herstellersignaturen bei und fügen Sie freigegebene Signaturschlüssel hinzu,
falls sie auf dem Ziel fehlen. Fügen Sie `--nogpgcheck` nicht hinzu. Bei einem
älteren OL8-Minor-Release kann zuerst ein freigegebenes Betriebssystem-Update
erforderlich sein.

### Ohne Python: manueller Smoke-Test

Der Stack kann ohne Python ausgeführt werden; nur die automatische
Verifizierung benötigt Python. Prüfen Sie nach der Health-Prüfung den
Generator mit einer neuen Kennung:

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
Abnahmeprüfungen für Ausfälle und Neustarts. Verwenden Sie jedes Mal eine
neue Ausführungskennung; Kennungen setzen einen Lauf weder zurück noch starten
sie ihn erneut.

## 10. Falls das Compose-Plugin fehlt

Docker Engine und Compose sind getrennte Komponenten. Eine vorhandene
Docker-CE-Installation belegt nicht, dass das Plugin installiert ist. Falls
`docker compose` bereits mit den erforderlichen Optionen funktioniert, überspringen
Sie diesen Abschnitt.

Bevorzugen Sie das freigegebene RPM `docker-compose-plugin` Ihres Standorts samt
vollständigem Abhängigkeitsumfang. Alternativ kann die Administration eine
offizielle Compose-Release-Binärdatei für die **Zielarchitektur** übertragen
und manuell installieren. Docker beschreibt Speicherorte und manuelle
Installation in der [Installationsanleitung für das Compose-Plugin](https://docs.docker.com/compose/install/linux/).

Laden Sie auf dem verbundenen Rechner ein geprüftes Release und dessen
veröffentlichte Prüfsummen aus den [Docker-Compose-Releases](https://github.com/docker/compose/releases)
herunter. Wählen Sie für x86-OL8 `docker-compose-linux-x86_64` und für ARM-OL8
`docker-compose-linux-aarch64`. Nehmen Sie die Datei erst dann in das Transfer-Manifest auf, wenn Sie
die Prüfsumme des Herausgebers geprüft haben. Wählen Sie kein nicht
dokumentiertes „latest“.

Für eine übertragene x86-Binärdatei im aktuellen Verzeichnis kann die
Administration Folgendes ausführen:

```bash
sudo install -d -m 0755 /usr/local/lib/docker/cli-plugins
sudo install -m 0755 docker-compose-linux-x86_64 \
  /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
docker compose up --help
```

Verwenden Sie für ARM den ARM-Dateinamen. Prüfen Sie die Kompatibilität mit
dem Docker-Daemon auf dem tatsächlichen OL8-Host, bevor Sie sich darauf
verlassen. Die manuelle Installation der Binärdatei bietet keine
automatischen Updates; halten Sie ihre Version im Bereitstellungsprotokoll
fest.

## 11. Regelmäßige Arbeiten auf OL8

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

`start` setzt vorhandene Container voraus. Nach `down` müssen Sie den
Befehl zum Erstellen/Neuerstellen verwenden. `restart` übernimmt geänderte
Compose-Umgebungseinstellungen nicht. Verwenden Sie nach Änderungen dieser
Einstellungen den Befehl zum Erstellen/Neuerstellen.

Die erschöpfte Engine kann ihren Container **laufend, aber nicht gesund**
zurücklassen. Auf einem Offline-Host verhält sich das wie auf dem Laptop:
Stellen Sie zuerst den Zustand des Receivers wieder her und starten Sie dann
Debezium ausdrücklich neu. Eine Restart-Policy, die auf den Container-Exit
reagiert, behebt diesen Fehlerfall nicht. Diese Bereitstellung richtet keinen
Autostart nach einem Reboot ein. Prüfen Sie nach Wartungsarbeiten am Host den
Zustand und starten Sie die benötigten Dienste bewusst.

Bewahren Sie die benannten Volumes `dbzproof_pg_data` und `dbzproof_debezium_data` zusammen mit dem
Installationsprotokoll auf. `docker compose down` behält sie bei;
`docker compose down -v` und `make reset` löschen sie. Verwenden Sie Reset nicht, um einen
vorübergehenden Ausfall bei der Zustellung zu beheben.

## 12. Offline-Fehlerbehebung

| Symptom | Wahrscheinliche Ursache und nächster Schritt |
| --- | --- |
| Compose versucht Images abzurufen | Falsches Arbeitsverzeichnis, automatischer Override fehlt, `COMPOSE_FILE` umgeht ihn oder ein expliziter Befehl fordert einen Pull an. Prüfen Sie `docker compose --profile tools config`. |
| Der Receiver-Build versucht Downloads | Es wurde `make up`, `make build` oder `--build` verwendet. Nutzen Sie den expliziten Startbefehl mit `--no-build --pull never`. |
| Image bei deaktivierten Pulls nicht gefunden | Tag stimmt nicht oder Image fehlt im übertragenen Archiv. Vergleichen Sie `.env`, `config --images` und `docker image ls`; korrigieren Sie das Bundle auf der verbundenen VM. |
| `exec format error` | Architektur stimmt nicht überein. Bauen und exportieren Sie auf einer passenden Architektur neu; ein geladenes Image wird dadurch nicht konvertiert. |
| Unbekannte Option oder `pull_policy` wird abgelehnt | Compose ist zu alt oder es wird das falsche Programm verwendet. Stellen Sie über den freigegebenen Offline-Weg ein kompatibles Plugin bereit. |
| Keine Schreibberechtigung für Logs/Runs | Falsche Host-UID/GID, Dateien wurden von einem anderen Konto extrahiert oder das Dateisystem ist schreibgeschützt. Prüfen Sie `id`, `.env` und `ls -ld logs runs`. SELinux ist in dieser Umgebung deaktiviert. |
| Port bereits belegt | Ein vorhandener Dienst verwendet Port 5432, 8080 oder 8081. Prüfen Sie `ss -ltn`; die URLs des Verifiers sind fest codiert und müssen vor einer Portänderung berücksichtigt werden. |
| PostgreSQL startet mit unerwartet alten Daten | Das feste benannte Volume existiert bereits. Halten Sie an und untersuchen Sie den Zustand; ein neues Quellverzeichnis erzeugt keinen neuen Volume-Namen. |
| Snapshot-Verifier schlägt fehl | Kein frischer Seed-/Snapshot-Verlauf, Logs wurden entfernt, während Offsets erhalten blieben, oder der Start ist fehlgeschlagen. Lesen Sie das Betreiberhandbuch, bevor Sie einen destruktiven Reset erwägen. |
| Debezium läuft, ist aber nicht gesund | Prüfen Sie den Zustand des Receivers und die Debezium-Logs. Nach ausgeschöpften Wiederholungsversuchen muss Debezium ausdrücklich neu gestartet werden, sobald der Receiver wiederhergestellt ist. |
| `/var/lib/docker` ist voll | Prüfen Sie durch den PostgreSQL-Slot zurückgehaltenes WAL sowie den Speicherverbrauch von Docker und Logs. Stellen Sie die Erfassung wieder her; löschen Sie WAL-Dateien nicht manuell. |

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

Führen Sie `docker system prune --volumes` nicht als schnelle Fehlerbehebung aus. Dadurch können
Daten dieser Demonstrationsumgebung oder anderer Installationen gelöscht
werden.

## 13. Updates und Protokollierung

Ändern Sie den Receiver, bauen Sie ihn auf Ubuntu neu, exportieren Sie das
neue Receiver-Image, notieren Sie dessen Image-ID, übertragen und laden Sie es
auf OL8 und erstellen Sie den Receiver anschließend mit `--no-build --pull never` neu. Da
`dbzproof/receiver:local` wiederverwendet wird, ist das Tag veränderlich. Notieren Sie
Image-IDs, damit Releases unterscheidbar bleiben, und bewahren Sie das
vorherige Image-Archiv für ein Rollback auf.

Erstellen Sie bei Änderungen der PostgreSQL- oder Debezium-Version ein
separates, geprüftes Bundle und testen Sie es vor der Bereitstellung. Ein
PostgreSQL-Major-Upgrade ist kein gewöhnlicher Image-Tausch mit dem
bestehenden Daten-Volume. Quellkonfiguration, Image-Versionen und persistenter
Zustand müssen zueinander passen; ein Image-Rollback macht Änderungen am
Datenbank- oder Zustandsformat allein nicht rückgängig.

Bewahren Sie die Transfer-Prüfsummendatei, das Image-Manifest, die
Build-Umgebung, die tatsächliche OL8-Version und -Architektur, die
Docker-/Compose-Versionen sowie den abschließenden Bericht `runs/verify-*.json` bei Ihren
Bereitstellungsnotizen auf. Für diese Dokumentationsänderung wurde der
Compose-Override auf dem Entwicklungsrechner geprüft. Das Image-Bundle wurde
auf dem OL8-Host noch nicht erstellt oder bereitgestellt.
