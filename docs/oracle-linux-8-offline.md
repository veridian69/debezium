# Moving the Debezium proof to offline Oracle Linux 8

This is the deployment recipe for Jon's setup: build on an internet-connected
Ubuntu VM on the laptop, transfer a bundle, and run on an Oracle Linux 8 host
with Docker CE already installed and SELinux disabled. The target does not need
internet access, Maven, a JDK, Git, a PostgreSQL client or a container registry.

This deploys a **fresh copy of the proof**, with its own seeded database and
initial snapshot. It does not migrate the laptop's live database, replication
slot, offset volume or event history. Image export contains application images;
it does not contain Docker volumes. Keep an existing installation separate.

Read [the operator guide](operator-guide.md) for the data flow, event contract,
verification details and recovery behaviour. All shell examples below use Bash.
Run the steps in order; the connected and disconnected machines are labelled.

## 1. What travels across the gap

| Bundle item | Purpose |
| --- | --- |
| `images.tar.gz` | PostgreSQL, Debezium Server and the built Java receiver |
| `project.tar.gz` | Compose files, `.env`, init SQL, generator, verifier, source and documentation |
| `image-manifest.txt` | Image IDs, architecture and available repository digests |
| `build-environment.txt` | Source revision and build-host Docker/Compose versions |
| `SHA256SUMS` | Detect incomplete or damaged transfers |
| Optional Compose binary/RPMs | Only if target prerequisites are missing |

Only three runtime images are needed:

```text
postgres:18.6-alpine
quay.io/debezium/server:3.7.0.Final
dbzproof/receiver:local
```

The generator reuses the PostgreSQL image: it runs Bash and `psql` from that
image. The receiver's Maven builder and Java base image are needed on the
connected VM during the build, but they need not be exported separately. The
finished receiver image already contains its runtime and dependencies.

Use [`docker image save`](https://docs.docker.com/reference/cli/docker/image/save/)
and [`docker image load`](https://docs.docker.com/reference/cli/docker/image/load/).
They preserve image layers and tags. `docker export`/`docker import` operate on
container filesystems and are the wrong tools for this job.

## 2. Check the OL8 target first

On **Oracle Linux**, collect this information before preparing the bundle:

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

If Docker uses another data directory, find it with:

```bash
docker info --format '{{.DockerRootDir}}'
```

Record the complete Docker **server** version and Compose version. “Docker CE
something” is sufficient for planning; the actual versions decide whether the
commands work. Use the Compose plugin (`docker compose`), not the old Python
`docker-compose` executable. Check that `up --help` includes `--wait`,
`--no-build` and `--pull`, and that `run --help` includes `--pull`.
The source proof used Compose v5.6.0; that is an observed source version,
not a claim that OL8 has already been tested with it.

The account running the commands needs Docker daemon access. If your site's
policy requires `sudo docker`, either use an approved account with daemon
access or run the entire verifier as an authorised privileged account: the
verifier launches `docker` itself and does not insert `sudo`. Docker group
membership effectively grants root-level control; do not change it casually.

Assume SELinux is disabled as stated. No relabelling or security-policy changes
are required by this recipe. Ports are bound to loopback, so there is no need
to open the host firewall for remote access to this local proof.

Allow room for the compressed bundle, the loaded image layers, PostgreSQL data,
WAL and growing logs. Measure the built bundle rather than relying on a guessed
size. At least several GiB of free space is a sensible starting allowance, not
a capacity guarantee. Slot-retained WAL can consume much more during an outage.

## 3. Match CPU architecture

On the **Ubuntu VM**, run:

```bash
uname -m
docker info --format '{{.Architecture}}'
```

| Target `uname -m` | Container platform |
| --- | --- |
| `x86_64` | `linux/amd64` |
| `aarch64` | `linux/arm64` |

The simplest path is a VM with the same architecture as OL8. The instructions
below assume that is true. An x86 Ubuntu VM and x86 OL8 host are the usual case,
but check rather than guessing.

If the architectures differ, do not export the VM's default images. Use a
matching-architecture builder or deliberately configure cross-platform builds
and emulation. The receiver Dockerfile executes Maven inside the build image,
so `--platform` alone does not supply emulation. Each pinned upstream image
must also exist for the target architecture. Resolve that before packaging;
`exec format error` on the offline host is a rather late place to discover it.

## 4. Prepare and build on the connected Ubuntu VM

Copy this project onto the **Ubuntu VM**, preserving `.env` and the executable
bit on `generator/generate.sh`. Put it at, for example, `~/projects/debezium`.
Use your normal source transfer method; this recipe does not require the
repository to be hosted anywhere.

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

Check all three reported architectures against the target. The receiver build
runs the receiver's unit tests through Maven. Its `dependency:go-offline` step
is best effort, so merely copying that cache would not establish an offline
build. Transferring the **finished image** avoids the entire Maven problem.

The commands above do not start or reset a database. If you want a complete
functional rehearsal, follow the fresh-install sequence in the operator guide
on an isolated Docker daemon/VM. This project uses fixed container and volume
names; two copies on the same daemon are not isolated simply by using two
directories or `-p` project names.

If `.env` image tags change, update the three explicit image references in
the packaging and inspection commands too. The recipe intentionally records
the pinned versions used by this proof.

## 5. Produce a self-contained transfer bundle

Still on the **Ubuntu VM**, from the project root:

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
    .env compose.yaml Makefile README.md \
    postgres debezium receiver generator verify docs deploy

(
  cd "$DBZ_BUNDLE"
  sha256sum images.tar.gz project.tar.gz \
    image-manifest.txt build-environment.txt > SHA256SUMS
  ls -lh
)
```

`set -o pipefail` matters: a failed image export must not leave a successful
gzip step masquerading as a valid bundle. Keep this shell open or record the
printed path; `DBZ_BUNDLE` is only a shell variable.

The project archive includes current files, including uncommitted documentation,
rather than silently taking an older `git archive HEAD`. The recorded Git
revision alone therefore does not define the archive; its checksum defines
the actual transferred content. The archive deliberately excludes `.git`,
host event logs, run reports, local database volumes and host Maven output.

The current `.env` contains demonstration credentials (`dbz`/`dbz`), and
`debezium/application.properties` repeats them. Review both before transfer.
If these files later contain real credentials, handle the bundle accordingly;
do not email it or put it in an ordinary shared folder.

SHA-256 checks detect corruption, not malicious replacement of both archive
and checksum. Use your approved removable-media or file-transfer route.

## 6. Transfer the directory

Transfer **all files in the printed bundle directory** to OL8, for example to:

```text
/home/jon/dbzproof-transfer/
```

Use a mounted USB device, a controlled file drop or an internal network copy.
“No internet” does not necessarily mean “no internal SSH”; if internal SSH is
available, an example from the Ubuntu VM is:

```bash
scp -r "$DBZ_BUNDLE" jon@ol8-host:/home/jon/dbzproof-transfer-bundle
```

Replace the host and account. On OL8, use the actual destination directory
containing `SHA256SUMS`, not its parent. Neither transfer method requires
contacting a public registry from OL8.

## 7. Load and configure on offline OL8

On **Oracle Linux**, first verify the transfer:

```bash
set -euo pipefail
cd /home/jon/dbzproof-transfer
sha256sum -c SHA256SUMS
gzip -t images.tar.gz
tar -tzf project.tar.gz
cat image-manifest.txt
```

Every checksum must say `OK`. Adjust the transfer path if you used the SSH
example. Inspect the archive listing before extracting it.

Load the images and extract the application into a **new** directory:

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

Run extraction as the account that will operate the proof; `logs/` and `runs/`
must be writable by the UID/GID you just recorded. Avoid running setup as root
then switching users halfway through. Named volumes are managed by Docker;
do not `chown` Docker's internal volume directories.

The supplied [offline override](../deploy/compose.offline.yaml) sets
`pull_policy: never` for **all four services**, including the generator.
Copying it to `compose.override.yaml` makes ordinary Compose commands and the
verifier discover it automatically. It preserves the base file's mounts,
named volumes, networking and health checks. It does not delete the receiver's
build definition, so startup must also use `--no-build`.

Check the loaded image IDs against `image-manifest.txt`:

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

The final command prints resolved credentials: inspect locally, do not paste
its output into an unrestricted ticket. Confirm each service has
`pull_policy: never`, the host ports are loopback-bound, and `logs`/`runs`
refer to this installation. Setup unsets `COMPOSE_FILE` so it cannot bypass
the automatic override; repeat that in a new shell if you normally set it.
Do not leave an unrelated override file in this directory.

## 8. Start without building or pulling

On **Oracle Linux**, from the installation root:

```bash
docker compose up -d --wait --no-build --pull never postgres receiver debezium
docker compose ps
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8081/q/health
```

**Do not use `make up` on the offline host.** Its `up` target depends on
`build`, which runs `docker compose build receiver` and may need upstream
images and Maven downloads. `make build` has the same issue.
Use the explicit command above whenever containers need creating or recreating.
[`docker compose up`](https://docs.docker.com/reference/cli/docker/compose/up/)
documents `--no-build`, pull policy and health waiting.

On first startup, PostgreSQL initialises the named volume, creates and seeds
the schemas, and creates the publication. Debezium waits for PostgreSQL and
the receiver to be healthy, then snapshots the three captured tables. Expect
15 `r` envelopes in `logs/events.jsonl` (3 customers, 4 orders, 8 items).

This is a local PostgreSQL proof **hosted on Oracle Linux**, not an Oracle
Database connector deployment. No Oracle client libraries are involved.

## 9. Verify the installation

### Preferred: Python 3.12 on the host

The proof was verified with Python 3.12 and uses only the standard library.
There is no `pip install` step. Check the interpreter explicitly:

```bash
python3.12 --version
python3.12 verify/verify.py all
```

Run the full verifier before manual database edits or generated examples on
this fresh installation. It writes evidence under `runs/`, creates scenario
rows, deliberately stops/restarts the receiver, and restarts the stack. This
is an acceptance exercise, not a passive monitoring command.

If you only need a quick health check:

```bash
python3.12 verify/verify.py health
```

`make verify` calls `python3`; only use it when that executable is the suitable
interpreter. Do not replace OL8's system Python or `/usr/libexec/platform-python`.
Use a versioned Python command. Oracle provides Python 3.12 on OL8.10 and
Python 3.11 on OL8.8 or later; see
[Oracle's Python installation documentation](https://docs.oracle.com/en/operating-systems/oracle-linux/8/python/python-InstallingPython.html).
The documented, previously tested choice for this project is 3.12.

If Python 3.12 is missing, have the system administrator supply it through
the site's OL8 package repository or approved offline RPM process. Prepare
RPMs on a connected OL8 environment matching the target's architecture,
minor release and repository configuration, **not by downloading Ubuntu debs**.

For an OL8.10 staging system with the appropriate repositories and DNF
download plugin already configured, an administrator can collect packages:

```bash
mkdir -p python-rpms
dnf download --resolve --alldeps --destdir ./python-rpms python3.12
```

Transfer that directory and install on the target with repositories disabled:

```bash
sudo dnf --disablerepo='*' install ./python-rpms/*.rpm
```

This is conditional guidance, not a universal RPM set: validate dependency
closure against the actual target, retain vendor signatures, and include
approved signing keys if the target lacks them. Do not add `--nogpgcheck`.
An older OL8 minor version may require an approved OS update first.

### Without Python: manual smoke check

The stack can run without Python; only automated verification needs it.
After confirming health, exercise the generator with a new identifier:

```bash
RUN_ID=ol8-smoke-001 docker compose --profile tools run --rm --pull never generator
tail -n 20 logs/events.jsonl
cat runs/ol8-smoke-001/manifest.json
cat runs/ol8-smoke-001/expected.jsonl
docker compose exec -T postgres psql -U dbz -d appdb \
  -c "select run_id, status from bulk.batch_jobs order by id;"
```

Seven expected captured events should appear, while the bulk marker exists
in the database without corresponding `bulk` events. This smoke check does
not replace the automated outage and restart acceptance checks. Use a new
run identifier each time; identifiers are not a rerun/reset mechanism.

## 10. If the Compose plugin is missing

Docker Engine and Compose are separate components. An existing Docker CE
installation does not prove the plugin is installed. If `docker compose`
already works with the required flags, skip this section.

Prefer your site's approved `docker-compose-plugin` RPM and its dependency
closure. Alternatively, the administrator can transfer an official Linux
Compose release binary for the **target architecture** and install it manually.
Docker describes the plugin locations and manual method in
[the Compose plugin installation guide](https://docs.docker.com/compose/install/linux/).

On the connected machine, obtain a reviewed release and its published checksums
from [Docker Compose releases](https://github.com/docker/compose/releases).
Choose `docker-compose-linux-x86_64` for x86 OL8 or
`docker-compose-linux-aarch64` for ARM OL8. Include it in the transfer manifest
after verifying the publisher's checksum. Do not select an unrecorded “latest”.

For a transferred x86 binary in the current directory, an administrator can use:

```bash
sudo install -d -m 0755 /usr/local/lib/docker/cli-plugins
sudo install -m 0755 docker-compose-linux-x86_64 \
  /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
docker compose up --help
```

Use the ARM filename for ARM. Check compatibility with the existing Docker
daemon on the real OL8 host before relying on it. Manual binary installation
does not provide automatic updates; keep its version in the deployment record.

## 11. Routine operations on OL8

| Task | Command from installation root |
| --- | --- |
| Create/recreate and wait for health | `docker compose up -d --wait --no-build --pull never postgres receiver debezium` |
| Show state | `docker compose ps` |
| Follow diagnostics | `docker compose logs -f --tail=100` |
| Follow events | `tail -f logs/events.jsonl` |
| Stop, preserve state | `docker compose stop` |
| Start existing stopped containers | `docker compose start` |
| Restart existing containers | `docker compose restart` |
| Recover exhausted Debezium engine | `docker compose restart debezium` |
| Generate another scenario | `RUN_ID=ol8-run-002 docker compose --profile tools run --rm --pull never generator` |

`start` requires existing containers; after `down`, use the create/recreate
command. `restart` does not apply changed Compose environment settings; use
the create/recreate command after changing those settings.

The exhausted engine can leave its container **running but unhealthy**. An
offline host behaves the same as the laptop: restore receiver health, then
restart Debezium explicitly. A container exit-based restart policy does not
solve that failure mode. No reboot auto-start policy has been added by this
deployment; after host maintenance, inspect state and start deliberately.

Keep the named volumes `dbzproof_pg_data` and `dbzproof_debezium_data` together
with the installation record. `docker compose down` retains them;
`docker compose down -v` and `make reset` destroy them. Do not use reset to
repair a transient delivery outage.

## 12. Offline troubleshooting

| Symptom | Likely cause and next step |
| --- | --- |
| Compose tries to pull | Wrong working directory, missing automatic override, `COMPOSE_FILE` bypassing it, or an explicit command requesting a pull. Inspect `docker compose --profile tools config`. |
| Receiver build attempts downloads | `make up`, `make build` or `--build` was used. Use the explicit `--no-build --pull never` startup command. |
| Image not found with pulls disabled | Tag mismatch or missing image in the transferred archive. Compare `.env`, `config --images` and `docker image ls`; repair the bundle on the connected VM. |
| `exec format error` | Architecture mismatch. Rebuild/export on the appropriate architecture; loading an image does not convert it. |
| Unknown flag or `pull_policy` rejected | Compose is too old or the wrong executable. Supply a compatible plugin through the approved offline route. |
| Permission denied writing logs/runs | Wrong host UID/GID, files extracted by another user, or a read-only filesystem. Check `id`, `.env` and `ls -ld logs runs`. SELinux is disabled in this setup. |
| Port already allocated | An existing service uses 5432, 8080 or 8081. Inspect `ss -ltn`; remember verifier URLs are hardcoded before changing ports. |
| PostgreSQL starts with unexpected old data | The fixed named volume already exists. Stop and investigate; copying a new source directory does not create a new volume name. |
| Snapshot verifier fails | Not a fresh seed/snapshot history, logs were removed while offsets remained, or startup failed. Read the operator guide before considering a destructive reset. |
| Debezium running/unhealthy | Inspect receiver health and Debezium logs; retry exhaustion needs an explicit restart after the receiver is restored. |
| `/var/lib/docker` fills | Inspect PostgreSQL slot-retained WAL and Docker/log disk usage. Restore capture; do not delete WAL files manually. |

Useful diagnostics, none of which need the internet:

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

Do not run `docker system prune --volumes` as a troubleshooting shortcut.
It can destroy state belonging to this proof or other installations.

## 13. Updates and records

For a receiver change, rebuild on Ubuntu, export the new receiver image,
record its image ID, transfer and load it on OL8, then recreate the receiver
with `--no-build --pull never`. Reusing `dbzproof/receiver:local` means the tag
is mutable: record image IDs so you can distinguish releases and keep the
previous image archive for rollback.

For PostgreSQL or Debezium version changes, make a separate reviewed bundle
and test it before deployment. A PostgreSQL major upgrade is not an ordinary
image swap against the existing data volume. Keep source config, image versions
and persistent state compatible; image rollback alone does not undo database
or state-format changes.

Keep the transfer checksum file, image manifest, build environment, actual
OL8 release/architecture, Docker/Compose versions and final `runs/verify-*.json`
report with your deployment notes. For this documentation delivery, the
Compose override has been checked on the development machine; the image
bundle has not been built or deployed on the OL8 host yet.
