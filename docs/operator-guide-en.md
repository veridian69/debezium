# Operator guide: PostgreSQL → Debezium Server → HTTP receiver

[Deutsche Fassung](operator-guide-de.md) | [Schweizerdeutsch](operator-guide-sg.md)

This guide explains how to run the proof, what it checks and where its limits lie.
Run commands from the repository root; paths below are relative to it.
For the Oracle Linux 8 target with Docker CE and no internet access, use
[the offline deployment guide](oracle-linux-8-offline-en.md) for preparation,
image transfer, installation and host-specific checks. Preparation happens on
the internet-connected Ubuntu VM on the laptop; the OL8 target has no SELinux.
The application behaviour described here applies across host distributions.

## What the proof establishes

An external writer changes relational PostgreSQL rows. Debezium captures the
time-critical strand and sends individual change envelopes to a Java HTTP
receiver. The receiver stands in for an Integration Broker REST service; it
records deliveries rather than running PeopleCode or processing business entities.
The separate `bulk` strand remains in PostgreSQL for hypothetical scheduled
processing. Oracle, database links, App Engine and PeopleSoft are outside this stack.

There is no Kafka, queue service or entity aggregation layer. A customer,
order and two order items inserted in one transaction produce four row events.
They are not turned into one order message. This matters when evaluating the
amount of downstream transaction handling a real integration would need.

The proof tests initial capture, filtering, before/after values, finite HTTP
retry behaviour and restart persistence. It does not establish throughput,
production latency, exactly-once delivery or production availability.

## Components and addresses

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

| Component | Container-side address | Default host address |
|---|---|---|
| PostgreSQL | `postgres:5432` | `127.0.0.1:5432` |
| Receiver | `receiver:8080/events` | `http://127.0.0.1:8080/events` |
| Receiver health | `receiver:8080/health` | `http://127.0.0.1:8080/health` |
| Debezium health | port 8080 in Debezium | `http://127.0.0.1:8081/q/health` |

Compose project name is `dbzproof`. Services are `postgres`, `receiver`,
`debezium` and `generator`; the generator uses profile `tools` and does not
run as part of ordinary startup. Published ports bind only to loopback.
Inside Compose, use service names, not the host's loopback addresses.

The checked-in `.env` pins PostgreSQL `18.6-alpine`, Debezium Server
`3.7.0.Final`, Maven `3.10.0-eclipse-temurin-25-alpine` and the receiver's
Temurin JRE `25.0.4_7-jre-alpine`. The receiver build is containerised;
host Java and Maven are unnecessary. Debezium uses its own image runtime.
Use `.env` as the version source when preparing a deployment bundle.

## Prerequisites and configuration coupling

The host needs Docker CE, the Docker Compose plugin, Bash, Make, curl and
Python 3.12 for the documented verification environment. The verifier uses
Python's standard library only: no pip environment or jq dependency is needed.
It also invokes Docker Compose and `tail`. The generator uses psql from the
PostgreSQL image; host psql is optional.

Credentials are `dbz` / `dbz`, database `appdb`. These are demonstration
superuser credentials, and receiver traffic is plain HTTP without authentication.
Do not expose these services by changing loopback bindings casually.

All published host ports come from `.env`: `PG_HOST_PORT`, `RECEIVER_HOST_PORT` and `DEBEZIUM_HOST_PORT`. `make health` and all verifier health probes use the resolved Compose configuration, including environment overrides. The address table above shows the defaults. Internal service ports stay unchanged.

For example, use free host ports:

```dotenv
PG_HOST_PORT=15432
RECEIVER_HOST_PORT=18080
DEBEZIUM_HOST_PORT=18081
```

After editing `.env`, recreate the services; `restart` does not apply new port mappings:

```sh
docker compose up -d --wait --no-build postgres receiver debezium
```

This preserves database data and offsets. On the offline host, also use `--pull never`.

Credentials remain coupled: `compose.yaml` reads them from `.env`, while `debezium/application.properties`, the verifier's psql wrapper and the Makefile's `psql` and `seed` targets still contain literal `dbz` / `appdb` values. Change those together if changing credentials. Existing PostgreSQL volumes retain their original users and database; changing `POSTGRES_*` does not reinitialise or migrate them.

The receiver and generator run as `HOST_UID:HOST_GID` from `.env` (default
1000:1000). Check `id -u` and `id -g` on the target and set them appropriately
before startup. Host directories `logs/` and `runs/` must be writable by that
identity. Image-directory permissions do not override bind-mount permissions.

## PostgreSQL capture mechanics

PostgreSQL starts with `wal_level=logical`, `max_wal_senders=10` and
`max_replication_slots=10`. WAL records database changes; `pgoutput` provides
the logical replication stream consumed by Debezium.
The named logical slot `dbz_slot` keeps the stream position and retains WAL
needed by its consumer. The named publication `dbz_publication` selects tables.
A publication is a selection rule; it is not a delivery queue.

Initial SQL creates these captured tables:

| Table | Relationship | Seed rows |
|---|---|---:|
| `timecritical.customers` | customer identity and contact fields | 3 |
| `timecritical.orders` | foreign key to customer | 4 |
| `timecritical.order_items` | foreign key to order | 8 |

All have identity-generated bigint primary key `id`. Money uses integer cents.
The separate tables `bulk.batch_jobs` and `bulk.pending_records` have seeded
rows too, but neither is captured. The latter references the former.

`postgres/init/30-replication.sql` creates the publication for exactly the
three time-critical tables. The connector also sets a schema allowlist and
an explicit table allowlist in `debezium/application.properties`. Both layers
should agree. A new table is not captured merely because it exists in the schema.
Publication autocreation is `filtered`, so Debezium can create a filtered
publication if it is absent; the normal first start uses the SQL-created one.

`REPLICA IDENTITY FULL` is set on all three captured tables. It makes old row
values available for updates and deletes, enabling the verifier to check
changed values in `before`. A primary key alone identifies a row but does not
provide the full old row image needed by this proof. FULL adds replication
work and data volume; assess that cost for real tables.

Init scripts run only when PostgreSQL initialises an empty data volume.
Editing schema or replication SQL and restarting an existing database does
not apply those edits. Use deliberate migration SQL for retained data, or a
complete reset for a disposable reproduction.

## Initial snapshot and streaming

`snapshot.mode=initial` means a connector without saved state first reads
existing captured rows, then continues with WAL changes. Seed SQL executes
before Debezium starts, so a clean first start yields 15 `op=r` envelopes.
Expected counts live in `postgres/expected_snapshot.json`.

Snapshot markers are not confined to the string `true`. The verifier accepts
`true`, `first`, `last`, `first_in_data_collection` and
`last_in_data_collection` in `source.snapshot`. Streaming events normally
carry the string `false`. Inspect actual data rather than converting these
strings to boolean by truthiness.

Offsets are stored at `/debezium/data/offsets.dat` in the named volume
`dbzproof_debezium_data`. The configured offset flush interval is 0.
An ordinary restart retains this state and should resume without a new snapshot.
The verifier tests that behaviour; an offset setting alone is not proof.
Deleting offsets while retaining a populated database can produce a new
snapshot of all current captured rows, not the original 15-row seed fixture.

## Reading an envelope

Key/value JSON schema metadata is disabled. An event is the envelope itself,
without an outer `schema`/`payload` wrapper. HTTP batching is disabled.
The receiver compacts JSON whitespace into one line but preserves its fields
and values; it does not strip metadata, unwrap rows or assemble entities.

| Field | Meaning in this proof |
|---|---|
| `op` | `r` snapshot read, `c` create, `u` update, `d` delete |
| `before` | old row for update/delete; null for create/snapshot |
| `after` | new/current row; null for delete |
| `source.schema`, `source.table` | originating relation |
| `source.lsn` | PostgreSQL source position used in duplicate reporting |
| `source.txId` | PostgreSQL transaction ID; shared by the four T1 inserts |
| `source.snapshot` | snapshot marker string |
| `source.ts_ms` | source timestamp used for local timing observations |
| `ts_ms`, `ts_us`, `ts_ns` | available connector processing timestamps |
| `transaction` | nullable transaction metadata; may be null here |

`source.txId` and top-level `transaction` are different fields. The scenario
uses the former to show common transaction membership; it does not require
non-null top-level transaction metadata or prove transaction-atomic HTTP delivery.
A receiver sees separate requests and must not assume all members arrive together.

These abbreviated examples show structure; IDs, timestamps and source
positions vary. Actual envelopes contain more source and row fields.

```json
{"before":null,"after":{"id":1,"external_ref":"cust-seed-1","name":"Ada Lovelace","email":"ada@example.test"},"source":{"schema":"timecritical","table":"customers","snapshot":"first","lsn":1234},"op":"r","transaction":null}
{"before":null,"after":{"id":4,"external_ref":"cust-demo","email":"demo@example.test"},"source":{"schema":"timecritical","table":"customers","snapshot":"false","txId":800,"lsn":2000},"op":"c","transaction":null}
{"before":{"id":4,"email":"demo@example.test"},"after":{"id":4,"email":"demo-updated@example.test"},"source":{"schema":"timecritical","table":"customers","snapshot":"false","txId":801,"lsn":2100},"op":"u","transaction":null}
{"before":{"id":10,"sku":"SKU-demo-B"},"after":null,"source":{"schema":"timecritical","table":"order_items","snapshot":"false","txId":803,"lsn":2300},"op":"d","transaction":null}
```

The observed HTTP representation has no separate record-key or topic header.
Identify a row using `source.schema`, `source.table` and `after.id`, or
`before.id` for a delete. Topic prefix `plumbing` does not imply that the topic
name is sent as a destination header. Receipt headers include HTTP context;
observed `x-debezium-__debezium.context.*` values are base64-encoded JSON,
not row keys. Header presence is recorded rather than asserted by the verifier.

Delete tombstones are disabled by `tombstones.on.delete=false`; delete
**envelopes** remain enabled. The receiver tolerates empty or JSON-null bodies
with HTTP 204 and a tombstone receipt, without adding an event-file line.

## Receiver durability and its three logs

For valid non-null JSON, the receiver appends a complete JSONL line using a
FileChannel and `force(true)`, then attempts a receipt and returns HTTP 200.
An event append failure returns HTTP 500; malformed JSON returns HTTP 400.
Writes are locked to prevent concurrent append interleaving. JSON validation
is not business-schema validation: the endpoint is a logging stand-in.

The event append is the acknowledgement boundary. Receipt writing is best
effort: a receipt failure is logged and does not change successful event delivery
to a failing response. A crash or lost response after the durable append can
therefore cause a retry and another event line. No duplicate suppression exists.

| Host path | Contents | Use |
|---|---|---|
| `logs/events.jsonl` | compact complete envelopes | primary delivery evidence |
| `logs/receipts.jsonl` | request time, status, bytes, lower-case headers, summary | HTTP/timing diagnosis |
| `logs/receiver.log` | receiver diagnostics | write failures and request errors |
| `runs/<RUN_ID>/expected.jsonl` | generator's seven expected changes | independent matching expectations |
| `runs/<RUN_ID>/manifest.json` | scenario identity, times and counts | correlate a run |
| `runs/verify-*.json` | verifier results and observations | retain acceptance evidence |

Receipt `seq` is in-memory and starts again when the receiver restarts.
Do not treat it as a globally unique event ID. Timing currently correlates
ordered event receipts with event-file lines. Missing receipts can impair that
correlation; delivery success and latency evidence are separate conclusions.
Receiver health tests whether the event-file parent directory is writable;
it does not perform a durable trial write or guarantee free disk space.

## Everyday commands

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

`make up` always builds the receiver first. Use it on the connected preparation
host. On the offline target, use the offline guide's no-build/no-pull startup
commands with the transferred images, including after a disposable reset.
`make seed` reapplies the idempotent seed SQL; it is not a clean snapshot reset.
`ON CONFLICT DO NOTHING` prevents duplicate seed inserts, but it does not
restore modified fields in existing rows to their original values.

Each generator run needs a new ID: letters, digits, dots, underscores and
hyphens, beginning with a letter or digit. Existing run directories are rejected.
No ID is required if a UTC timestamp ID is suitable: `make generate`.
The generator commits four inserts in T1, then a customer update in T2, an
order update in T3 and an item delete in T4: seven expected captured events.
It also inserts one bulk job and two pending records and updates one pending
record. Its recorded expected rows use actual generated primary keys.

## Safe acceptance sequence

The full verifier changes the running stack: it writes database rows, stops
the receiver, exhausts the sink retry budget and restarts services. Run it on
this isolated proof, not a shared service needing uninterrupted availability.
Do not run two verifiers or a verifier and a manual scenario concurrently;
run IDs use second-resolution timestamps and shared logs are inspected globally.

The sequence below is for the connected preparation host. On the offline
target replace `make up` with the offline guide's no-build/no-pull startup.
For repeatable first-start acceptance, preserve any wanted logs/reports first,
then explicitly discard this project's disposable state:

```sh
make reset                         # DESTRUCTIVE: see exact scope below
make up
make verify
```

`make reset` runs Compose down with volumes and removes
`dbzproof_pg_data`, `dbzproof_debezium_data`, `logs/events.jsonl`,
`logs/receipts.jsonl`, `logs/receiver.log` and contents of `runs/` except
`.gitkeep`. This is a reset, not a restart. Do not use global Docker prune.

Fresh snapshot verification requires both a fresh database/offset pair and
fresh logs. Reusing old logs can count old snapshot rows; deleting logs alone
while retaining offsets removes evidence without causing a new snapshot.
Reinitialising only one volume creates a different test and can lose continuity.
The full check expects exactly 3/4/8 seed snapshot rows. A resnapshot of a
populated scenario database will not satisfy that fixture.

## Seven CLI checks, eight historical criteria

The original goal lists eight acceptance criteria. The implementation exposes
seven individual checks, plus `all`: `scenario` combines row-envelope matching
with the common-transaction criterion. There is no eighth individual command.
The historical phrase “eight checks” refers to the criteria, not CLI subcommands.

| CLI check | What it actually does |
|---|---|
| `health` | GET both health endpoints; parse the host event file's last line |
| `snapshot` | wait for seed `r` envelopes; check exact 3/4/8 counts and markers |
| `scenario` | generate a new run; match seven rows, before images and four common T1 txIds |
| `bulk` | check that run's bulk rows; update bulk and wait for a captured marker; reject bulk envelopes |
| `outage-short` | stop receiver for 10 seconds; generate; start receiver; await delivery with Debezium running |
| `outage-long` | stop receiver until engine failure; restore receiver; explicitly restart Debezium; await backlog |
| `restart` | generate before/after restart; check retained rows and unchanged snapshot count |

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

`scenario --run-id` **creates** that run; it does not merely read an existing
manual run. `bulk --run-id` reads an existing run's expectations and adds its
own diagnostic updates. `all` creates and passes its scenario ID to `bulk`.
Every invocation writes a timestamped JSON report and exits 0 on success,
1 on failure. Inspect its named report before rerunning a failed check.

Matching uses expected keys and before/after subsets from the generator,
not a reconstructed expectation based on observed delivery. Duplicate reports
use source LSN, schema, table, operation and row ID. They are observations,
not a delivery deduplication service. Some checks report duplicates without
failing; `scenario` additionally requires exactly four T1 event matches.
Do not interpret a PASS as an exactly-once guarantee.

## Outage behaviour and explicit recovery

The HTTP sink timeout is 5000 ms, retry count 10 and retry interval 3000 ms.
The retry budget is finite. Refusals and timeouts consume different amounts
of time, so there is no single guaranteed failure duration from these settings.
Use the verifier's elapsed time, send-attempt count and logs as evidence.

On the pinned observed stack, retry exhaustion stops the embedded engine,
while the container stays running. `/q/health` returns HTTP 503/DOWN and
Compose eventually marks it unhealthy. No restart policy is configured.
A running container is therefore insufficient evidence of capture health.

Restore the receiver and restart Debezium to reopen the engine:

```sh
docker compose start receiver
curl -fs "http://$(docker compose port receiver 8080)/health"
make recover                       # docker compose restart debezium
make health
make ps
docker compose logs --tail=100 debezium
```

`docker compose start debezium` does not restart an already-running unhealthy
container. A short outage can recover via sink retries; recovery after budget
exhaustion above is supplied by an explicit restart. Existing observations
include engine-failure messages containing `Exceeded maximum number of attempts`
and `Engine has failed`. Treat attempt counts and recovery time as run-specific.

## Inspecting logs without jq

Pretty-print the last envelope using Python's standard library:

```sh
tail -n 1 logs/events.jsonl | python3 -m json.tool
```

Count operations and tables, and show the last event receipt:

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

Run these on a quiescent log or retry after a concurrent final-line write;
the verifier itself tolerates an incomplete final JSONL line. Do not POST test
JSON into `/events` during acceptance: arbitrary valid JSON becomes a delivery
line and can invalidate the verifier's assumptions.

## Troubleshooting and retained WAL

| Symptom | First checks and interpretation |
|---|---|
| Port already allocated | inspect host listeners; change paired port literals described above |
| Receiver unhealthy or HTTP 500 | check UID/GID, bind-directory permissions, free space and `logs/receiver.log` |
| Debezium running but unhealthy | inspect Debezium logs and `/q/health`; after sink exhaustion use `make recover` |
| Scenario missing events | inspect report mismatch, receiver writes, connector health and capture allowlists |
| Update/delete lacks old fields | inspect replica identity on the actual retained database |
| Unexpected snapshot count | check volumes, old logs and whether offsets were removed separately |
| Generator rejects ID | use a fresh valid ID; preserve prior run evidence rather than overwriting it |
| Seed/schema edit appears ignored | init scripts only run against an empty PostgreSQL data volume |

Inspect publication membership, replica identity and slot progress with:

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

Replica identity `f` means FULL. While the consumer is down or blocked, the
slot can retain WAL and fill PostgreSQL storage. Monitor retained WAL and disk
space; this proof configures no operational WAL-retention limit or alerting.
Do not drop the slot or delete offsets as routine recovery: that can remove
needed change history and force a resnapshot. Recover delivery first, then
confirm slot progress and backlog catch-up. If storage is full, plan the database recovery.
Repeated blind restarts will not make more space.

## Production implications

This receiver has no authentication, request-size limit, business validation,
rotation policy or deduplication, and reads each request body into memory.
Its append file is evidence, not a business-processing queue. Plan retention,
backups and downstream acknowledgement semantics before treating it as one.
Named volumes and bind mounts are persistent storage, not backups.

Production needs scoped database privileges, transport/authentication,
credential management, WAL/slot monitoring, disk capacity and log retention.
It also needs a considered strategy for duplicate handling, transactions,
schema evolution and outages longer than the finite sink budget.
Local delivery times use source timestamps and best-effort receipt timestamps;
they depend on clocks and receipt alignment. They are observations, not an SLA.
The proof's successful runs inform that design but do not replace it.
