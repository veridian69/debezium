# Debezium Server

This component runs Debezium Server 3.7.0.Final and sends PostgreSQL change
events directly to the Java receiver over the Compose network.

## HTTP sink

The native HTTP sink posts one event at a time to
`http://receiver:8080/events`. Batching is disabled so each POST contains one
change-event envelope. The timeout is 5000 ms, with 10 retries and a 3000 ms
interval between retries. A connection refusal fails fast, so the practical
retry window is about `10 x 3 s = 30 s`. If attempts consume their full
timeouts, the worst case is about `10 x (5 + 3) s = 80 s`.

Retries are finite. Observed on 3.7.0.Final: exhaustion stops the embedded
engine, but the container remains running. `/q/health` returns 503 DOWN and
Compose marks it unhealthy. There is no restart policy by design, and an
exit-based restart policy would not recover a process that has not exited.
Recovery is `docker compose restart debezium` (`make recover`); the verifier
exercises this and checks delivery of the backlog from persisted offsets.

The HTTP sink's runtime headers, including the `X-DEBEZIUM-` prefix and
base64-encoded values, are observed from the runtime logs and are not
asserted.

## JSON formats

The key and value formats are JSON, with schema metadata disabled for both.
The receiver therefore gets the bare payload envelope rather than a
schema-and-payload wrapper.

## PostgreSQL source and capture allowlist

The PostgreSQL connector uses `pgoutput`, the fixed database credentials, the
`plumbing` topic prefix, replication slot `dbz_slot`, and publication
`dbz_publication`. The schema and table allowlists capture only
`timecritical.customers`, `timecritical.orders`, and
`timecritical.order_items`; the `bulk` schema is excluded.

`snapshot.mode=initial` captures rows seeded before Debezium starts as initial
snapshot events. The publication is created by init SQL, so the named
publication is reused; `publication.autocreate.mode=filtered` is retained so
Debezium can create a correctly filtered publication if it is absent.

## Offsets and deletes

Offsets use the file-backed store at `/debezium/data/offsets.dat`. The path is
inside the `dbzproof_debezium_data` named volume, allowing offset state to
survive ordinary stack stops and restarts. The offset flush interval is set to
`0` as specified by the shared configuration.

Tombstones are disabled at the Debezium source. The receiver also tolerates an
empty HTTP body so a tombstone representation cannot break request handling.

## Server settings

Quarkus listens on port 8080 for the Debezium health endpoint and server
traffic. Console JSON is disabled and the console log level is `INFO` so
diagnostics remain readable in the container logs.

## Observed HTTP representation

The first observed request was `POST /events` with `content-type:
application/json` and the envelope payload only (schemas are disabled). It was
HTTP/1.1, offered `upgrade: h2c` from Debezium's Java 21 `HttpClient`
(`user-agent: Java-http-client/21.0.12.1`), and included a W3C `traceparent`
header.

There is no header for the record key or destination/topic
(`plumbing.timecritical.orders`). Read the table and key from
`source.schema`, `source.table`, and `after.id` or `before.id`.

The only `X-DEBEZIUM-` headers are Debezium context headers. Their values are
base64-encoded JSON of the form
`{"schema":{"type":"string","optional":false},"payload":"<value>"}`:
`x-debezium-__debezium.context.connectorlogicalname` is `plumbing`,
`x-debezium-__debezium.context.connectorname` is `postgresql`,
`x-debezium-__debezium.context.runid` is a UUID per Debezium start, and
`x-debezium-__debezium.context.taskid` is `0`.
