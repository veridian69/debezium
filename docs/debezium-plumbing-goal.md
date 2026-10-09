# Debezium Server plumbing proof

Build and run a reproducible local proof of PostgreSQL change capture through Debezium Server into a Java REST receiver. Work in `/home/jclk/projects/debezium`, using native Linux Docker CE and Docker Compose inside WSL. Docker Desktop is not involved.

The design below has been agreed with Jon. Use it as the input to the next Superpowers planning and implementation steps. Resolve routine implementation choices autonomously; ask only when a material ambiguity or constraint prevents progress. The deliverable is a working, tested stack, not just configuration files or a plan.

## Purpose and scope

This models workplace integration: an external system writes changes representing PeopleSoft logical entities into PostgreSQL, and Debezium sends time-critical changes to an Integration Broker REST service for PeopleCode processing.

Production also has a separate bulk strand, where Oracle accesses PostgreSQL through a database link and scheduled App Engine processing handles pending records. Represent the bulk data in PostgreSQL, but exclude it from Debezium capture.

This proof includes no Oracle, database link, App Engine, PeopleSoft, PeopleCode, entity aggregation, or production deployment. The Java receiver stands in for Integration Broker and logs events without business processing.

## Runtime and components

Use compatible current stable PostgreSQL, Debezium Server and Java releases. Verify available versions against official sources during implementation, pin exact versions, and document them. Build the Java application in a container so a host Java or Maven installation is unnecessary.

Provide Docker Compose services for PostgreSQL, Debezium Server and the Java receiver, with health checks and appropriate startup coordination. Provide a manually invoked data generator, either as a one-shot Compose service or a script using the containerised database tooling. No Kafka or additional message broker is required.

Persist PostgreSQL data and Debezium offsets across ordinary restarts. Put receiver logs in a bind-mounted directory at `/home/jclk/projects/debezium/logs`, readable and tail-able from WSL without entering a container. Bind published host ports to localhost. Use documented local development credentials, plain HTTP and no HTTP authentication.

## Database and generator

Create a small relational model with customers, orders and order items, including primary keys, foreign keys and one-to-many relationships. Use a distinct schema for time-critical tables and another for bulk tables. Put representative records in both groups.

Configure PostgreSQL logical replication and the Debezium PostgreSQL connector appropriately, including its publication, replication slot and explicit capture allowlist. Capture only the time-critical tables.

Seed data before Debezium starts so the first start produces an initial snapshot. The manually triggered generator must then execute a deterministic scenario that inserts related rows, updates fields and deletes a child row. Exercise both table groups. Include a transaction changing several related rows to demonstrate separate row events from one transaction.

Make repeated scenario runs safe through identifiable run IDs or another documented approach. Keep expected changes available for automated verification. Seed loading, scenario execution and a complete reset must be distinct operations.

## HTTP and logging contract

Use Debezium Server's native HTTP sink with individual deliveries rather than HTTP batch arrays. Preserve the complete Debezium change-event envelope, including source metadata, operation, before/after values and available timestamps. Do not unwrap events into row-only payloads or assemble related rows into logical entities. Document whether JSON converter schema metadata is enabled.

The receiver exposes `POST /events` and `GET /health`. The POST operation validates JSON, appends the received envelope as one JSON Lines record to `logs/events.jsonl`, and returns a successful HTTP response only after the write succeeds. A failed log write must produce a failing HTTP response. Preserve envelope fields and values; JSON whitespace may be normalised for one-line logging.

Keep receiver diagnostics and receipt timestamps in a separate log or sidecar record so the envelope file remains unchanged in structure. Handle concurrent requests safely. Document the HTTP sink's representation of event keys and table/destination information, including relevant headers.

Preserve delete envelopes. Explicitly configure and document tombstone handling so null tombstones do not unexpectedly break the JSON receiver. No duplicate suppression is required: retain duplicate deliveries and identify them during verification using source position, table, key and operation as applicable.

## Recovery and verification

Use meaningful automated integration checks with bounded waits and explicit failure output. Verify all of the following against actual running containers:

1. A clean start delivers the seeded time-critical rows as initial snapshot events.
2. Generator inserts, updates and deletes appear in the host log with the expected operation, source table, keys and before/after values available under the chosen connector configuration.
3. Related rows changed in one transaction arrive as separate row events.
4. Seeded and subsequently changed bulk rows remain in PostgreSQL and produce no captured events. Establish this after the time-critical stream has caught up, rather than relying only on a short sleep.
5. The receiver health operation works, and the host can read and tail the event file.
6. A brief receiver outage followed by restoration within the configured retry window delivers all expected changes committed during that outage.
7. An outage lasting beyond the configured HTTP retry budget has an observed, documented failure mode. Restore the receiver and recover delivery, using a Debezium/container restart if required. Distinguish built-in sink retries from recovery supplied by Compose or an explicit restart.
8. Ordinary stack restarts retain database contents and offsets and resume capture. Verify against identifiable changes; do not assume exactly-once delivery or absence of replay.

Document the configured HTTP timeout, retry count and retry interval. Built-in HTTP retries are finite; do not claim indefinite retry behaviour. Test recovery rather than infer it from settings. Detect missing expected events and report duplicates. Measure delivery times for representative live changes without presenting this as a production latency benchmark or imposing an unagreed SLA.

## Parallel team

Use four subagents with bounded responsibilities and explicit file ownership:

- Database and generator: schema, seed data, replication prerequisites and deterministic change scenarios.
- Debezium: connector configuration, native HTTP sink, snapshot behaviour, capture filtering, offsets and retry settings.
- Java receiver: REST operations, envelope logging, container build and log-volume permissions.
- Interfaces and integration: contract review, acceptance checks and recovery evidence, coordinating across the components.

The lead fixes schema/table names, endpoint paths, network service names, mounts and payload expectations before parallel implementation. The interface agent may review those contracts early. Keep shared Compose files under one owner to avoid concurrent edits. The lead integrates changes, resolves disagreements, and owns final end-to-end verification. Select model and reasoning effort deliberately for each task; avoid unnecessary nested delegation.

## Deliverables and completion

Deliver all source code, Dockerfiles, Compose configuration, database scripts, Debezium configuration, generator and verification tooling in this project. Provide a concise README with exact commands for building, starting, checking health, generating changes, inspecting the database, tailing logs, running verification, reproducing both outage cases, stopping and resetting the stack.

The reset command must explicitly identify the project data and offsets it deletes. Ordinary stop/restart commands must preserve them. Do not delete unrelated Docker resources or overwrite existing unrelated project files.

Run the stack and checks on the available WSL Docker CE environment. Leave the stack running after successful verification, with the event log available on the host. Report versions, service URLs, log paths, actual verification results and any limitations. If an environmental constraint prevents execution, identify it precisely and distinguish delivered files from unverified runtime behaviour.
