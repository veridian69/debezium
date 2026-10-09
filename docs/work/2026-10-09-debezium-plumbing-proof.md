# Work Packet: Debezium Server plumbing proof

- Status: complete
- Owner: Lead (Spike), four Codex workers
- Updated: 2026-10-09

<!-- ROUTE=mixed | WRITE_READY=4 | READ_READY=0 | EXISTING=0 | PLANNED_DISPATCH=4 | LEAD=compose,.env,Makefile,interfaces,stack-run,final-acceptance | REASON=parallel_gain | DETAIL=Four independent file-owned units with Lead-fixed interfaces; workers cannot reach Docker so Lead runs the stack and returns failures for one repair round each. -->

## Spec

End state: `make up` on WSL Docker CE brings up PostgreSQL 18.6, Debezium Server 3.7.0.Final and a Java 25 receiver; `make generate` runs a deterministic scenario; `make verify` passes checks 1-8 of the goal document against the running containers; README has exact commands; stack left running with `logs/events.jsonl` readable on the host.

Acceptance: `python3 verify/verify.py all` exits 0 with a report under `runs/`, and Lead has inspected the report, `logs/events.jsonl`, and `docker compose ps`.

Scope and non-goals: as in [../debezium-plumbing-goal.md](../debezium-plumbing-goal.md). No Oracle, Kafka, PeopleSoft, entity aggregation, auth, TLS, production deployment.

Constraints: Docker socket and network are unavailable inside Codex worker sandboxes. Versions pinned in `.env`. Commit only on Jon's request.

## Decisions

- Debezium 3.7.0.Final (released 2026-09-29; quay `3.8` tag is pre-release). PostgreSQL 18.6 is listed as supported by 3.7.
- JSON converter schema metadata disabled for key and value: envelope is the Debezium payload (`before/after/source/op/ts_ms`). Documented in `debezium/README.md`.
- Tombstones disabled at the source (`tombstones.on.delete=false`) and tolerated by the receiver (empty body -> 204, receipt only). Belt and braces.
- HTTP sink: timeout 5000 ms, 10 retries, 3000 ms interval. Connection-refused fails fast, so the practical budget is about 30 s; worst case with timeouts about 80 s. Short outage test 10 s, long outage test waits for the Debezium container to exit.
- No restart policy on the `debezium` service so exhaustion is observable. Observed (not assumed): the embedded engine stops after 1+10 attempts (~48 s), the container stays running, `/q/health` is 503 DOWN, Compose shows unhealthy. Recovery is `docker compose restart debezium` (`make recover`); backlog delivered from the persisted offset.
- `REPLICA IDENTITY FULL` on captured tables so update and delete envelopes carry full `before`.
- Publication created explicitly in init SQL for the three captured tables; Debezium `publication.autocreate.mode=filtered` reuses it.
- Generator and receiver run as uid 1000 so bind mounts stay owned by the WSL user.
- Expected events are written by the generator (it knows the ids it got back); the verifier only reads them.

## Plan

| Wave | Unit | Owner | Route | Acceptance |
|---|---|---|---|---|
| 0 | compose.yaml, .env, Makefile, docs, contracts | Lead | direct | files present; `docker compose config` valid |
| 1 | postgres/init + generator | Codex Terra (standard__db_generator) | adapter | init on clean start; generator writes expected.jsonl |
| 1 | debezium/application.properties | Codex Luna (fast__debezium_config) | adapter | Debezium starts, snapshot delivered |
| 1 | receiver/ | Codex Terra (standard__java_receiver) | adapter | image builds, unit tests pass, /health UP |
| 1 | verify/verify.py + README.md | Codex Terra (standard__integration_verify) | adapter | `verify.py all` runs end to end |
| 2 | Lead: build, up, run verify; return failures to owners (one repair each) | Lead | direct | verify all exit 0 |
| 3 | Lead: document observed headers/failure mode, final README pass, leave stack running | Lead | direct | report to Jon |

## Status

- 2026-10-09 20:15 Wave 0 done. Dispatching wave 1.
- 2026-10-09 20:25 Wave 1 accepted for db_generator, debezium_config, java_receiver. Stack up, snapshot 15/15.
- 2026-10-09 20:31 verify run 1: health, snapshot, scenario, bulk, outage-short PASS; outage-long FAIL (wrong terminal condition in contract: container does not exit), restart FAIL (consequence). Repair round dispatched to integration owner with observed evidence.

- 2026-10-09 20:39 verify run 2 after owner repair: outage-long/restart FAIL on unhandled `ConnectionResetError` in health probes. Lead took the boundary (no second worker loop): probes now treat `OSError`/`HTTPException` as transient; log scan scoped with `--since`.
- 2026-10-09 20:44 final consolidated `verify.py all`: 8/8 PASS. Complete. Stack left running.

## Evidence

- `docker compose build receiver`: exit 0; explicit `mvn test` run: Tests run 6, Failures 0.
- Clean start: init SQL applied, publication exact, `wal_level=logical`, snapshot 15 envelopes (3/4/8).
- `python3 verify/verify.py all` final run: `runs/verify-20261009T184304Z.json`, all 8 PASS, exit 0. Earlier runs: `verify-20261009T183120Z.json` (6/8, wrong terminal condition), `verify-20261009T183845Z.json` (probe reset), `184041Z`/`184051Z` (targeted reruns PASS).
- Failure mode (observed): 1+10 HTTP attempts over ~39-48 s, `Exceeded maximum number of attempts to publish event`, engine STOPPED, container running, `/q/health` 503 DOWN, Compose unhealthy. Recovery `docker compose restart debezium`, backlog delivered, 0 duplicates.
- HTTP sink representation: no key/destination headers; four `x-debezium-__debezium.context.*` headers (base64 JSON). Documented in `debezium/README.md`.
- Routing: 4 Codex workers (3 Terra, 1 Luna) + 1 Terra repair round. Lead fixed snapshot-value set, probe exception handling, compose comment, `make recover`.
- Not done: no git commit (Jon has not asked); working tree has 15 untracked top-level entries.

## Deferred ideas

- Dedicated replication role instead of superuser `dbz` — more representative of production grants; revisit if the proof is promoted.
- Receiver failure injection endpoint for testing 5xx retries without stopping the container.
