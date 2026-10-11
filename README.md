# Debezium Server plumbing proof

Detailed documentation: [operator guide](docs/operator-guide.md) and
[offline Oracle Linux 8 deployment](docs/oracle-linux-8-offline.md).

## What this is

A local, reproducible proof of PostgreSQL change capture through Debezium Server into a Java HTTP receiver. It models time-critical row changes and a separate, uncaptured bulk strand. It is for local development only.

## Versions

| Component | Version |
|---|---|
| PostgreSQL | 18.6-alpine |
| Debezium Server | 3.7.0.Final |
| Maven build image | 3.10.0-eclipse-temurin-25-alpine |
| Java runtime image | 25.0.4_7-jre-alpine |

## Prerequisites

Docker CE and Docker Compose running natively in WSL. Docker Desktop is not used. Python 3.12 is needed for verification.

## Quick start

```sh
make up
make health
make generate RUN_ID=r1
make verify
```

## Operations

Build the receiver: `make build` (underlying command: `docker compose build receiver`).

Start the stack: `make up` (underlying command: `docker compose up -d --wait postgres receiver debezium`).

Check health: `make health` (underlying commands: `curl -fs http://127.0.0.1:8080/health` and `curl -fs http://127.0.0.1:8081/q/health`).

Generate a deterministic change set: `make generate RUN_ID=r1` (underlying command: `RUN_ID=r1 docker compose run --rm generator`).

Inspect the database with `make psql` (underlying command: `docker compose exec postgres psql -U dbz -d appdb`). For example:

```sql
select * from timecritical.customers order by id;
select run_id, status from bulk.batch_jobs order by id;
```

Tail container diagnostics with `make logs` (underlying command: `docker compose logs -f --tail=100`). Tail envelopes with `make tail` (underlying command: `tail -f logs/events.jsonl`).

Run every verification check: `make verify` (underlying command: `python3 verify/verify.py all`).

Reproduce the short outage: `make outage-short` (underlying command: `python3 verify/verify.py outage-short`).

Reproduce the long outage: `make outage-long` (underlying command: `python3 verify/verify.py outage-long`).

Recover Debezium after retry exhaustion: `make recover` (underlying command: `docker compose restart debezium`).

Stop while preserving data and offsets: `make stop` (underlying command: `docker compose stop`). Restart likewise preserves them: `make restart` (underlying command: `docker compose restart`).

Reset with `make reset` (underlying Compose command: `docker compose --profile tools down -v --remove-orphans`; it then removes the named host log files and the contents of `runs/` except `.gitkeep`). It deletes containers, volumes `dbzproof_pg_data` and `dbzproof_debezium_data`, `logs/events.jsonl`, `logs/receipts.jsonl`, `logs/receiver.log`, and the contents of `runs/` except `.gitkeep`.

## Contract

The receiver exposes `POST /events` and `GET /health`; Debezium health is `GET /q/health` on port 8081. Event posts contain the full Debezium envelope (`before`, `after`, `source`, `transaction`, `op`, and timestamps), not an aggregate or unwrapped row. JSON schema metadata is disabled and delete tombstones are disabled, while delete envelopes themselves are retained. `logs/receipts.jsonl` is a sidecar containing request time, method, path, status, byte count, normalized headers, and an event summary; it does not alter `logs/events.jsonl`.

## Retry settings

The HTTP sink uses a 5000 ms timeout, 10 retries, and a 3000 ms retry interval. Observed after 1 + 10 attempts (about 48 seconds with connection refused and two connect timeouts), the embedded engine stops with `Exceeded maximum number of attempts to publish event`. The container keeps running, `/q/health` returns 503 `DOWN`, and Compose shows `unhealthy`; there is no automatic restart (`restart: "no"`). Recover with `make recover` (`docker compose restart debezium`). On recovery, Debezium resumes from the persisted offset and delivers the backlog (observed: 14 events, 0 duplicates). The 10-second `outage-short` recovered through the sink's own retries in 15.1 seconds, with the engine never stopping.

## Verification

`verify/verify.py` proves receiver and Debezium health, first-start snapshot counts, generator envelope matching and replica identity, same-transaction row events, exclusion of bulk rows, brief-outage retry recovery, long-outage failure and explicit recovery, plus ordinary restart persistence and lack of re-snapshot. It reports duplicate source-position deliveries and local delivery-time observations.

## Limitations

This is a local proof, not a production benchmark. Credentials are local superuser credentials. Delivery is not exactly once, and duplicates may occur during recovery. Delivery time is an observation, not a benchmark or SLA.

## Observed on first run

PostgreSQL 18.6, Debezium Server 3.7.0.Final, Java 25.0.4 runtime, and a receiver built with Maven 3.10.0 were used. The snapshot delivered 15 envelopes: 3 customers, 4 orders, and 8 order_items. Its `source.snapshot` values included `first`, `true`, `last_in_data_collection`, `first_in_data_collection`, and `last`.

The scenario matched 7/7 expected events; four T1 envelopes shared one `source.txId`. `before` was populated on `u` and `d` events because of `REPLICA IDENTITY FULL`. Bulk rows were present in PostgreSQL with no `bulk` envelope. Local delivery-time observation (not a benchmark): min 757 ms, median 786 ms, max 797 ms.

The HTTP representation facts are documented in `debezium/README.md`.

Final consolidated run on 2026-10-09 (`runs/verify-20261009T184304Z.json`): all eight checks PASS. Long outage: the engine stopped after 10 send attempts in 39.0 s, the container stayed running with health DOWN, and an explicit `docker compose restart debezium` delivered the backlog with 0 duplicates. Ordinary `docker compose restart`: rows and offsets retained, snapshot count stayed at 15 (no re-snapshot), 0 duplicates. Delivery time that run: min 589 ms, median 602 ms, max 611 ms (local observation, not a benchmark). Runs are not exactly-once by design; duplicates were simply not observed in these runs.
