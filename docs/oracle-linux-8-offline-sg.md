# Dr Debezium-Versuechsufbau offline uf Oracle Linux 8 bereitstelle

[Deutsch](oracle-linux-8-offline-de.md) | [English](oracle-linux-8-offline-en.md)

So chunnt Jons Versuechsufbau uf dr Offline-Host: uf ere Ubuntu-VM mit
Internetzuegang uf em Laptop baue, es Bundle übertrage und das uf
eme Oracle-Linux-8-Host mit bereits installiertem Docker CE und deaktiviertem
SELinux usfüehre. S Ziel brucht weder Internetzuegang no Maven, es JDK,
Git, e PostgreSQL-Client oder e Container-Registry.

Damit wird e **nöii Kopie vom Versuechsufbau** mit ere eigete,
vorbefüllte Datebank und eme initiale Snapshot bereitgstellt. D aktive
Datebank vom Laptop, dr Replikations-Slot, s Offset-Volume und d
Ereignis-Historie wärde nid migriert. Dr Image-Export enthält
Awändig-Images, aber ke Docker-Volumes. E bestehendi Installation
muess separat blibe.

Datefluss, Ereignisvertrag, Verifizierig und Wiederhärstellig si im
[Operator Guide](operator-guide-sg.md) beschribe. Alli Shell-Bispil bruuche Bash.
D Schritt dr Reihe nach usfüehre; d Rächner mit und ohni
Netzwerkzuegang si entsprechend kennzeichnet.

## 1. Was über d Netzgränze übertrage wird

| Bestandteil vom Bundle | Zwäck |
| --- | --- |
| `images.tar.gz` | PostgreSQL, Debezium Server und dr baute Java-Empfänger |
| `project.tar.gz` | Compose-Dateie, `.env`, Init-SQL, Generator, Verifier, Quellcode und Dokumentation |
| `image-manifest.txt` | Image-IDs, Architektur und verfüegbari Repository-Digests |
| `build-environment.txt` | Quellrevision und Docker-/Compose-Versione vom Build-Host |
| `SHA256SUMS` | Erkennt unvollständigi oder beschädigti Übertragige |
| Optional: Compose-Binärdatei/RPMs | Nume we uf em Ziel Vorussetzige fähle |

Es brucht nume drü Laufzyt-Images:

```text
postgres:18.6-alpine
quay.io/debezium/server:3.7.0.Final
dbzproof/receiver:local
```

Dr Generator brucht s PostgreSQL-Image nomau: Bash und `psql` wärde
us däm Image usgfüehrt. S Maven-Builder-Image und s Java-Basis-Image
vom Empfänger brucht es bim Build uf dr verbundene VM,
si müesse aber nid separat exportiert wärde. S fertige Empfänger-Image enthält
bereits d Laufzytumgäbig und d Abhängigkeiten.

Für dr Export [`docker image save`](https://docs.docker.com/reference/cli/docker/image/save/)
und für dr Import [`docker image load`](https://docs.docker.com/reference/cli/docker/image/load/) bruuche.
Die Befähl erhalte Image-Layer und Tags. `docker export`/`docker import` schaffe mit
Container-Dateisysteme und si für dä Zwäck ungeeignet.

## 2. Zersch s OL8-Ziel prüefe

Vor em Vorbereite vom Bundle uf **Oracle Linux** die folgende Informatione erfasse:

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

We Docker es anders Dateverzeichnis brucht, chasch es so ermittle:

```bash
docker info --format '{{.DockerRootDir}}'
```

D vollständigi Version vom Docker-**Server** und d
Compose-Version notiere. «Docker CE irgendöppis» längt für d Planig; öb d Befähl
funktioniere, hängt vo de tatsächleche Versione ab. S
Compose-Plugin bruuche (`docker compose`), nid s alte Python-Programm `docker-compose`.
Prüefe, öb `up --help` d Optione `--wait`, `--no-build` und
`--pull` enthält und öb `run --help` d Option `--pull` enthält.
Im Quellnachwys isch Compose v5.6.0 bruucht worde. Das isch e beobachteti
Quellversion und ke Behauptig, dass die Version bereits mit OL8 testet
worde isch.

S usfüehrende Konto brucht Zuegriff uf dr Docker-Daemon. We d
Standortrichtlinie `sudo docker` vorschrybe, entweder es freigegebes Konto
mit Daemon-Zuegriff bruuche oder dr ganz Verifier als autorisierts
privilegierts Konto usfüehre: Dr Verifier startet `docker` säuber
und füegt kes `sudo` i. D Mitgliedschaft i dr Docker-Gruppe git
faktisch Kontrolle uf Root-Ebeni. Die Mitgliedschaft nid liechtfertig ändere.

SELinux isch hie wie agäh deaktiviert. Das
Verfahre brucht weder e nöii Zueordnig vo Labels no Änderige a
Sicherheitsrichtlinie. D Ports si a Loopback bunde; d Host-Firewall
muess drum für dr Färnzuegriff uf dä lokale Versuechsufbau nid
ufgmacht wärde.

Gnue Platz für s komprimierte Bundle, d gladenen
Image-Layer, PostgreSQL-Date, WAL und wachsendi Logs iplane. D Grössi
vom erstellte Bundle mässe, statt sech uf e Schätzig z verla.
Mehri GiB freie Speicher si e vernünftige Usgangswärt, aber ke
Kapazitätsgarantie. WAL, wo e Slot zrügghebt, cha bi eme
Usfall düütlech meh Platz bruuche.

## 3. D CPU-Architektur abglyche

Uf dr **Ubuntu-VM** usfüehre:

```bash
uname -m
docker info --format '{{.Architecture}}'
```

| Usgab vo `uname -m` uf em Ziel | Container-Plattform |
| --- | --- |
| `x86_64` | `linux/amd64` |
| `aarch64` | `linux/arm64` |

Am eifachschte isch e VM mit dr glyche Architektur wie OL8. D folgende
Aaleitige setze das vorus. Üblecherwys loufe sowohl d Ubuntu-VM wie
ou dr OL8-Host uf x86; das trotzdem prüefe, statt es aznäh.

Bi unterschiedliche Architekture ke Standard-Images vo dr VM exportiere.
E Builder mit passender Architektur bruuche oder Cross-Platform-Builds
und Emulation bewusst iirichte. Wüu s
Empfänger-Dockerfile Maven innerhalb vom Build-Image usfüehrt, stellt `--platform`
allei ke Emulation bereit. Jedes fescht versionierte Upstream-Image muess
ou für d Zielarchitektur verfüegbar si. Das vor em Packe kläre; `exec format error` uf em Offline-Host z entdecke, chunnt rächt spät.

## 4. Uf dr verbundene Ubuntu-VM vorbereite und baue

S Projekt uf d **Ubuntu-VM** kopiere. Derbi `.env` und s
Usfüehrigsrächt vo `generator/generate.sh` erhalte. Als Ziel eignet sech
zum Bispil `~/projects/debezium`. D üblechi Methode für d Quellübertragig bruuche; es
hostets Repository isch für das Verfahre nid nötig.

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

Alli drü gmäldete Architekture mit em Ziel abglyche. Bim Build vom
Empfänger wärde sini Unit-Tests mit Maven usgfüehrt. Dr Schritt
`dependency:go-offline` wird nach beschtem Bemüehige usgfüehrt. Nume dä Cache z kopiere
würd auso ke Offline-Build ermögliche. Mit dr Übertragig vom
**fertige Image** entfaut s ganze Maven-Problem.

D Befähl obe starte oder setze ke Datebank zrügg. Für e Prob
vom ganze Ablauf d Neuinstallationssequenz im Operator Guide uf eme
isolierte Docker-Daemon oder i ere isolierte VM durefüehre. Das Projekt brucht fescht Container- und Volume-Näme. Zwei Kopie
uf em glyche Daemon si nid scho drum isoliert, wüu si i
verschiedene Verzeichnis lige oder unterschiedlechi Compose-Projektnäme
bruuche (`-p`).

We sech d Image-Tags i `.env` ändere, ou d drü
explizite Image-Referänze i de Befähl fürs Packe und Prüefe aktualisiere. Das
Verfahre hautet bewusst d für dä Versuechsufbau bruuchte,
feschtgleite Versione fescht.

## 5. Es vollständigs Transfer-Bundle erstelle

Witerhin uf dr **Ubuntu-VM**, im Projekt-Stammverzeichnis:

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

`set -o pipefail` isch wichtig: E fehlgschlagene Image-Export darf nid dür e
erfolgriche gzip-Schritt wie es gültigs Bundle usgseh. Die
Shell offe la oder dr usgäh Pfad notiere; `DBZ_BUNDLE` isch nume e
Shell-Variable.

S Projektarchiv enthält d aktuelle Dateie samt nid
committeter Dokumentation. Es wird nid stillschwygend es älters
`git archive HEAD` bruucht. D ufzeichneti Git-Revision allei definiert s Archiv
drum nid; d Prüefsumm legt dr tatsächlech übertragene Inhalt fescht.
Bewusst usgschlosse wärde `.git`, Host-Ereignislogs, Usfüehrigsbricht,
lokali Datebank-Volumes und Maven-Usgabe vom Host.

S aktuelle `.env` enthält Demo-Zuegangsdate (`dbz`/`dbz`);
`debezium/application.properties` enthält die glyche Zuegangsdate. Beidi Dateie vor dr Übertragig
prüefe. We si spöter echti Zuegangsdate enthalte, s Bundle entsprechend
behandle: nid per E-Mail versände oder i eme gewöhnleche freigegebene
Verzeichnis ablege.

SHA-256-Prüefsummen erkenne Beschädigige, aber ke böswillige Ustusch
vo Archiv und Prüefsumm zäme. Dr freigegebene Wäg über
Wechselmedie oder Dateiübertragig bruuche.

## 6. S Verzeichnis übertrage

**Alli Dateie us em usgäh Bundle-Verzeichnis** uf OL8 übertrage,
zum Bispil nach:

```text
/home/jon/dbzproof-transfer/
```

Es iighänktes USB-Loufwärk, e kontrollierte Dateiablageort
oder e interni Netzwerkkopie bruuche. «Kes Internet» heisst nid zwingend
«kes internes SSH». We internes SSH verfüegbar isch, geit das uf dr
Ubuntu-VM zum Bispil so:

```bash
scp -r "$DBZ_BUNDLE" jon@ol8-host:/home/jon/dbzproof-transfer-bundle
```

Host und Konto ersetze. Uf OL8 s tatsächleche Zielverzeichnis mit
`SHA256SUMS` bruuche, nid s übergeordnete Verzeichnis.
Keini vo de beide Übertragigsmethode muess vo OL8 us e öffentlechi
Registry kontaktiere.

## 7. Uf em Offline-OL8 lade und konfiguriere

Uf **Oracle Linux** zersch d Übertragig prüefe:

```bash
set -euo pipefail
cd /home/jon/dbzproof-transfer
sha256sum -c SHA256SUMS
gzip -t images.tar.gz
tar -tzf project.tar.gz
cat image-manifest.txt
```

Jedi Prüefsumm muess mit `OK` bestätigt wärde. We du s SSH-Bispil bruuchsch, dr
Transferpfad apasse. Vor em Extrahiere d Archivlischte prüefe.

D Images lade und d Awändig i es **nöis** Verzeichnis extrahiere:

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

D Dateie mit em Konto extrahiere, wo dr Versuechsufbau wird betrybe. `logs/` und `runs/` müesse für d grad erfassti UID/GID
beschrybbar si. D Installation nid als Root iirichte und de mittendrin s Konto
wächsle. Benannti Volumes verwaltet Docker; dr Bsitzer vo Docker-interne
Volume-Verzeichnis nid mit `chown` ändere.

Dr mitgliferte [Offline-Override](../deploy/compose.offline.yaml) setzt
`pull_policy: never` für **alli vier Dienschte**, inklusive em Generator. Wird er als
`compose.override.yaml` kopiert, erkenne ihn normali Compose-Befähl und dr Verifier
automatisch. D Mounts, benannti Volumes, Netzwerke und Healthchecks vo dr
Basisdatei blibe erhalte. D Build-Definition vom Empfänger wird derdür
nid entfärnt; bim Start muess drum zusätzlech `--no-build` bruucht wärde.

D IDs vo de gladenen Images mit `image-manifest.txt` verglyche:

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

Dr letscht Befähl git ufglösti Zuegangsdate us. D Usgab lokal prüefe
und nid i es uneigschränkt zuegänglechs Ticket kopiere. Bi jedem Dienscht prüefe, dass
`pull_policy: never` gsetzt isch, d Host-Ports a Loopback bunde si und
`logs`/`runs` uf die Installation verwyse. D Iirichtig entfärnt
`COMPOSE_FILE`, damit d automatischi Erkennig vom Override nid umgange
wärde cha. I ere nöie Shell widerhole, we die Variable normalerwys gsetzt
isch. Kes frömds Override i däm Verzeichnis lige la.

## 8. Ohni Build oder Pull starte

Uf **Oracle Linux** im Stammverzeichnis vo dr Installation usfüehre:

```bash
docker compose up -d --wait --no-build --pull never postgres receiver debezium
docker compose ps
curl -fsS "http://$(docker compose port receiver 8080)/health"
curl -fsS "http://$(docker compose port debezium 8080)/q/health"
```

**`make up` nid uf em Offline-Host bruuche.** S Ziel
`up` hängt vo `build` ab. Das füehrt `docker compose build receiver` us und
brucht möglicherwys Upstream-Images und Maven-Downloads. Für `make build`
gilt ds Glyche. Dr explizit Befähl obe bruuche, we
Container erstellt oder nöi erstellt wärde müesse.
[`docker compose up`](https://docs.docker.com/reference/cli/docker/compose/up/) beschrybt
`--no-build`, d Pull-Richtlinie und s Warte uf Healthchecks.

Bim erschte Start initialisiert PostgreSQL s benannte Volume, erstellt und
befüllt d Schemas und richtet d Publication ii. Debezium wartet, bis
PostgreSQL und dr Empfänger gsund si, und erstellt dernach Snapshots vo de
drü erfasste Tabelle. Es si 15 `r`-Umschläg i `logs/events.jsonl` z erwarte
(3 Chunde, 4 Bstellige, 8 Positione).

Das isch e lokale PostgreSQL-Versuechsufbau, wo **uf Oracle
Linux hostet wird**. Es isch ke Oracle-Database-
Connector-Bereitstellig. Oracle-Client-Bibliotheke chöme nid zum Iisatz.

## 9. D Installation verifiziere

### Empfohle: Python 3.12 uf em Host

Dr Versuechsufbau isch mit Python 3.12 verifiziert worde und brucht
ausschliesslech d Standardbibliothek. E `pip install`-Schritt isch nid nötig.
Dr Interpreter ausdrücklich prüefe:

```bash
python3.12 --version
python3.12 verify/verify.py all
```

Uf dere frische Installation zersch dr vollständig Verifier usfüehre,
erscht dernach d Datebank manuell ändere oder Bispil generiere. Er
schrybt Nachwyse nach `runs/`, erzeugt Szenario-Zyle, stoppt und startet
dr Empfänger absichtlech nöi und startet dr ganz Stack nöi. Das isch
e Abnahmprüefig und ke passive Monitoring-Befähl.

Für e churzi Health-Prüefig längt:

```bash
python3.12 verify/verify.py health
```

`make verify` rüeft `python3` uf. Nume bruuche, we das Programm
dr geeigneti Interpreter isch. Weder s System-Python vo OL8 no
`/usr/libexec/platform-python` ersetze. E versionierte Python-Befähl bruuche. Oracle stellt
Python 3.12 uf OL8.10 und Python 3.11 ab OL8.8 bereit. Details stöh i
dr [Oracle-Dokumentation zur Python-Installation](https://docs.oracle.com/en/operating-systems/oracle-linux/8/python/python-InstallingPython.html).
D für das Projekt dokumentierti und früecher testeti Wahl isch Version
3.12.

We Python 3.12 fählt, sött d Systemadministration es über s
OL8-Paket-Repository vom Standort oder e freigegebene Offline-RPM-Prozess
bereitstelle. RPMs i ere verbundene OL8-Umgäbig vorbereite, wo
bi Zielarchitektur, Minor-Release und Repository-Konfiguration
übereinstimmt. Derfür **ke Ubuntu-deb-Pakete** abelade.

Uf eme OL8.10-Staging-System mit de passende Repositories und bereits
konfiguriertem DNF-Download-Plugin cha d Administration d Pakete wie
folgt zämestelle:

```bash
mkdir -p python-rpms
dnf download --resolve --alldeps --destdir ./python-rpms python3.12
```

Das Verzeichnis übertrage und d Pakete uf em Ziel mit deaktivierte
Repositories installiere:

```bash
sudo dnf --disablerepo='*' install ./python-rpms/*.rpm
```

Das si bedingti Hiwyse und ke universelli RPM-Lischte. D Abhängigkeiten
für s tatsächleche Ziel uf Vollständigkeit prüefe, d Härstellersignature
bibehalte und fählendi freigegebene Signaturschlüssle hinzuefüege.
`--nogpgcheck` nid hinzuefüege. Bi eme
ältere OL8-Minor-Release cha zersch es freigegebes Betriebssystem-Update
nötig si.

### Ohni Python: manuelle Smoke-Test

Dr Stack cha ohni Python usgfüehrt wärde; nume d automatischi
Verifizierig brucht Python. Nach dr Health-Prüefig dr
Generator mit ere nöie Kennig usfüehre:

```bash
RUN_ID=ol8-smoke-001 docker compose --profile tools run --rm --pull never generator
tail -n 20 logs/events.jsonl
cat runs/ol8-smoke-001/manifest.json
cat runs/ol8-smoke-001/expected.jsonl
docker compose exec -T postgres psql -U dbz -d appdb \
  -c "select run_id, status from bulk.batch_jobs order by id;"
```

Es sötte sibe erwarteti erfassti Ereignis erschyne. Dr Bulk-Marker
isch i dr Datebank vorhande, ohni dass entsprechendi `bulk`-Ereignis
usgäh wärde. Dä Smoke-Test ersetzt nid d automatisierte
Abnahmprüefige für Usfäll und Neustarts. Jedes Mau e
nöii Usfüehrigskennig bruuche; Kennige setze e Lauf weder zrügg no starte
si ihn nomau.

## 10. We s Compose-Plugin fählt

Docker Engine und Compose si separati Komponente. E vorhandeni
Docker-CE-Installation belegt nid, dass s Plugin installiert isch. We
`docker compose` bereits mit de nötige Optione funktioniert, dä
Abschnitt überspringe.

S am Standort freigegebene RPM `docker-compose-plugin` mit aune
Abhängigkeiten bevorzuge. Alternativ cha d Administration e
offizielli Compose-Release-Binärdatei für d **Zielarchitektur** übertrage
und manuell installiere. Docker beschrybt Speicherort und manuelli
Installation i dr [Installationsaaleitig fürs Compose-Plugin](https://docs.docker.com/compose/install/linux/).

Uf em verbundene Rächner es prüefts Release und sini
veröffentlechte Prüefsummen us de [Docker-Compose-Releases](https://github.com/docker/compose/releases)
abelade. Für x86-OL8 `docker-compose-linux-x86_64` und für ARM-OL8
`docker-compose-linux-aarch64` wähle. D Datei erscht nach em Prüefe vo dr
Härstellerprüefsumm is Transfer-Manifest ufnäh. Kes undokumentierts
«latest» wähle.

Für e übertragene x86-Binärdatei im aktuelle Verzeichnis cha d
Administration ds Folgende usfüehre:

```bash
sudo install -d -m 0755 /usr/local/lib/docker/cli-plugins
sudo install -m 0755 docker-compose-linux-x86_64 \
  /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
docker compose up --help
```

Für ARM dr ARM-Dateiname bruuche. Vor em Iisatz d Kompatibilität
mit em Docker-Daemon uf em tatsächleche OL8-Host prüefe. D manuelli Installation vo dr Binärdatei bietet ke
automatische Updates; ihri Version im Bereitstelligsprotokoll feschthalte.

## 11. Regelmässigi Arbeite uf OL8

| Ufgab | Befähl im Installationsverzeichnis |
| --- | --- |
| Erstelle/nöi erstelle und uf Healthchecks warte | `docker compose up -d --wait --no-build --pull never postgres receiver debezium` |
| Status azeige | `docker compose ps` |
| Diagnosemäldige verfolge | `docker compose logs -f --tail=100` |
| Ereignis verfolge | `tail -f logs/events.jsonl` |
| Ahalte und dr Zuestand erhalte | `docker compose stop` |
| Vorhandeni, aghalteni Container starte | `docker compose start` |
| Vorhandeni Container nöi starte | `docker compose restart` |
| Erschöpfte Debezium-Engine-Prozess wiederhärstelle | `docker compose restart debezium` |
| Es witers Szenario erzeuge | `RUN_ID=ol8-run-002 docker compose --profile tools run --rm --pull never generator` |

`start` setzt vorhandeni Container vorus. Nach `down` dr
Befähl fürs Erstelle/Nöierstelle bruuche. `restart` übernimmt gänderti
Compose-Umgäbigsistellige nid. Nach Änderige vo dene
Iistellige dr Befähl fürs Erstelle/Nöierstelle bruuche.

D erschöpfti Engine cha ihre Container **loufend, aber nid gsund**
zrüggla. Uf eme Offline-Host verhält sech das wie uf em Laptop:
Zersch dr Empfänger wiederhärstelle, dernach Debezium ausdrücklich nöi starte. E Restart-Policy, wo uf dr Container-Exit
reagiert, behebt dä Fählerfall nid. Die Bereitstellig richtet ke
Autostart nach eme Reboot ii. Nach Wartigsarbeite am Host dr Zuestand prüefe
und d nötige Dienschte bewusst starte.

D benannte Volumes `dbzproof_pg_data` und `dbzproof_debezium_data` zäme mit em
Installationsprotokoll ufbehalte. `docker compose down` bhautet si;
`docker compose down -v` und `make reset` lösche si. Reset nid bruuche, um e
vorübergehende Zuestellusfall z behebe.

## 12. Offline-Fähler behebe

| Symptom | Wahrschynlechi Ursach und nächschte Schritt |
| --- | --- |
| Compose versuecht Images abzrüefe | Fauschs Arbeitsverzeichnis, dr automatisch Override fählt, `COMPOSE_FILE` umgeit ihn oder e explizite Befähl fordert e Pull a. `docker compose --profile tools config` prüefe. |
| Dr Empfänger-Build versuecht Downloads | Es isch `make up`, `make build` oder `--build` bruucht worde. Dr explizit Startbefähl mit `--no-build --pull never` bruuche. |
| Image bi deaktivierte Pulls nid gfunde | S Tag stimmt nid oder s Image fählt im übertragene Archiv. `.env`, `config --images` und `docker image ls` verglyche; s Bundle uf dr verbundene VM korrigiere. |
| `exec format error` | D Architektur stimmt nid überein. Uf ere passende Architektur nöi baue und exportiere; es gladenes Image wird derdür nid konvertiert. |
| Unbekannti Option oder `pull_policy` wird abglehnt | Compose isch z alt oder es wird s fausche Programm bruucht. Über dr freigegebene Offline-Wäg es kompatibles Plugin bereitstelle. |
| Ke Schrybberechtigung für Logs/Runs | Fauschi Host-UID/GID, d Dateie si vo mene andere Konto extrahiert worde oder s Dateisystem isch schrybgschützt. `id`, `.env` und `ls -ld logs runs` prüefe. SELinux isch i dere Umgäbig deaktiviert. |
| Port bereits belegt | E konfigurierte Hostport isch belegt. `ss -ltn` prüefe, freii Wärt für `PG_HOST_PORT`, `RECEIVER_HOST_PORT` und `DEBEZIUM_HOST_PORT` i `.env` setze und mit em No-Build/No-Pull-Befähl nöi erstelle. Healthchecks und Verifier folge dene Wärt. |
| PostgreSQL startet mit unerwartet alte Date | S fescht benannte Volume existiert bereits. Ahalte und dr Zuestand untersueche; es nöis Quellverzeichnis erzeugt ke nöie Volume-Name. |
| Dr Snapshot-Verifier schlaht fähl | Ke frische Seed-/Snapshot-Verlauf, Logs si entfärnt worde, während Offsets erhalte blibe si, oder dr Start isch fählgschlage. Vor eme destruktive Reset dr Operator Guide läse. |
| Debezium louft, isch aber nid gsund | Dr Zuestand vom Empfänger und d Debezium-Logs prüefe. Nach usgschöpfte Wiederholigsversuech muess Debezium ausdrücklich nöi gstartet wärde, sobald dr Empfänger wiederhärgstellt isch. |
| `/var/lib/docker` isch vou | S WAL, wo dr PostgreSQL-Slot zrügghebt, sowie dr Speicherverbruch vo Docker und Logs prüefe. D Erfassig wiederhärstelle; WAL-Dateie nid manuell lösche. |

Nützlechi Diagnose, wo ke Internetzuegang bruuche:

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

`docker system prune --volumes` nid als schnälli Fählerbehebig usfüehre. Derdür chöi
Date vo däm Versuechsufbau oder vo andere Installatione glöscht
wärde.

## 13. Updates und Protokollierig

Bi Änderige am Empfänger: uf Ubuntu nöi baue, s nöie Empfänger-Image
exportiere, sini Image-ID notiere, uf OL8 übertrage und lade, de dr
Empfänger mit `--no-build --pull never` nöi erstelle. Wüu
`dbzproof/receiver:local` wiederverwendet wird, isch s Tag veränderlech. Image-IDs notiere,
damit Releases unterscheidbar blibe, und s vorherige Image-Archiv
für es Rollback ufbehalte.

Bi Änderige vo dr PostgreSQL- oder Debezium-Version es separates,
prüefts Bundle erstelle und vor dr Bereitstellig teste. Es
PostgreSQL-Major-Upgrade isch ke gewöhnleche Image-Tusch mit em
bestehende Date-Volume. Quellkonfiguration, Image-Versione und persistente
Zuestand müesse zäme passe; es Image-Rollback macht Änderige am
Datebank- oder Zuestandsformat allei nid rückgängig.

D Transfer-Prüefsummedatei, s Image-Manifest, d
Build-Umgäbig, d tatsächlechi OL8-Version und -Architektur, d
Docker-/Compose-Versione sowie dr abschliessendi Bricht `runs/verify-*.json`
mit de Bereitstelligsnotize ufbehalte. Für die Dokumentationsänderig isch dr
Compose-Override uf em Entwickligsrächner prüeft worde. S Image-Bundle isch
uf em OL8-Host no nid erstellt oder bereitgstellt worde.
