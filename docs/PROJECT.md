# Project map: Debezium Server plumbing proof

Current structure and boundaries. Goal and acceptance live in
[debezium-plumbing-goal.md](debezium-plumbing-goal.md); the active work unit is
[work/2026-10-09-debezium-plumbing-proof.md](work/2026-10-09-debezium-plumbing-proof.md).

## Data flow

```
generator (psql, manual) ──▶ PostgreSQL 18.6 ──pgoutput/dbz_slot──▶ Debezium Server 3.7.0.Final
                              │ schemas: timecritical (captured), bulk (not captured)        │ HTTP sink, 1 event per POST
                              ▼                                                               ▼
                       runs/<RUN_ID>/expected.jsonl                                 Java 25 receiver  POST /events
                                                                                      │ GET /health
                                                                                      ▼
                                                                    logs/events.jsonl  logs/receipts.jsonl  logs/receiver.log
                                                                                      ▲
                                                           verify/verify.py (host, python3 stdlib) reads runs/ + logs/, drives docker compose
```

## Directory ownership

| Path | Owner | Responsibility |
|---|---|---|
| `compose.yaml`, `.env`, `Makefile` | Lead | Service graph, versions, ports, volumes, operator entry points |
| `postgres/init/*.sql`, `postgres/expected_snapshot.json` | DB owner | Schema, seed, replica identity, publication |
| `generator/` | DB owner | Deterministic scenario, `runs/<RUN_ID>/expected.jsonl` + `manifest.json` |
| `debezium/application.properties`, `debezium/README.md` | Debezium owner | Connector, HTTP sink, snapshot, filtering, offsets, retries |
| `receiver/` | Receiver owner | Java HTTP receiver, Dockerfile (Maven build stage), tests |
| `verify/`, `README.md` | Integration owner | Acceptance checks 1-8, outage and restart evidence, operator docs |
| `logs/`, `runs/` | runtime | Bind mounts; ignored by git |
| `docs/` | Lead | Goal, project map, work packet |

## Fixed interfaces

- Compose project name `dbzproof`; services `postgres`, `receiver`, `debezium`, `generator` (profile `tools`).
- Host ports (localhost only): 5432 PostgreSQL, 8080 receiver, 8081 Debezium Quarkus health.
- Credentials: `dbz` / `dbz` / `appdb`. Local development only.
- All tables: primary key `id bigint generated always as identity`. Money as integer cents. No numeric columns.
- Debezium: `topic.prefix=plumbing`, slot `dbz_slot`, publication `dbz_publication`, JSON without schema metadata, tombstones disabled.
- Volumes `dbzproof_pg_data` and `dbzproof_debezium_data` survive `down`; only `make reset` deletes them.

## Forbidden coupling

- Nothing unwraps or aggregates envelopes; the receiver logs exactly what Debezium sent.
- The verifier never computes expectations itself; it reads what the generator recorded.
- No Kafka, no Oracle, no PeopleSoft components.
