#!/usr/bin/env bash
set -euo pipefail

: "${PGHOST:?PGHOST must be set}"
: "${PGPORT:?PGPORT must be set}"
: "${PGUSER:?PGUSER must be set}"
: "${PGPASSWORD:?PGPASSWORD must be set}"
: "${PGDATABASE:?PGDATABASE must be set}"
: "${RUNS_DIR:?RUNS_DIR must be set}"

RUN_ID="${RUN_ID:-}"
if [[ -z "$RUN_ID" ]]; then
    RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
fi

if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "RUN_ID must contain only letters, digits, dots, underscores, and hyphens" >&2
    exit 2
fi

run_dir="$RUNS_DIR/$RUN_ID"
if [[ -e "$run_dir" ]]; then
    echo "run directory already exists: $run_dir" >&2
    exit 2
fi

mkdir -p "$run_dir"
expected_file="$run_dir/expected.jsonl"
manifest_file="$run_dir/manifest.json"

psql -v ON_ERROR_STOP=1 -X -q -A -t \
    -v run_id="$RUN_ID" \
    -v customer_ref="cust-$RUN_ID" \
    -v customer_name="Run $RUN_ID" \
    -v customer_email="$RUN_ID@example.test" \
    -v customer_email_updated="$RUN_ID-updated@example.test" \
    -v order_ref="ord-$RUN_ID-1" \
    -v item_a_sku="SKU-$RUN_ID-A" \
    -v item_b_sku="SKU-$RUN_ID-B" \
    -v batch_job_name="job-$RUN_ID" \
    -v pending_payload_a="pending-$RUN_ID-a" \
    -v pending_payload_b="pending-$RUN_ID-b" \
    -v expected_file="$expected_file" \
    -v manifest_file="$manifest_file" <<'SQL'
SELECT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at
\gset

BEGIN;
INSERT INTO timecritical.customers (external_ref, name, email)
VALUES (:'customer_ref', :'customer_name', :'customer_email')
RETURNING id AS customer_id
\gset

INSERT INTO timecritical.orders (customer_id, order_ref, status, total_cents)
VALUES (:'customer_id'::bigint, :'order_ref', 'NEW', 4498)
RETURNING id AS order_id
\gset

INSERT INTO timecritical.order_items (order_id, sku, quantity, unit_price_cents)
VALUES (:'order_id'::bigint, :'item_a_sku', 2, 1999)
RETURNING id AS item_a_id
\gset

INSERT INTO timecritical.order_items (order_id, sku, quantity, unit_price_cents)
VALUES (:'order_id'::bigint, :'item_b_sku', 1, 500)
RETURNING id AS item_b_id
\gset
COMMIT;

UPDATE timecritical.customers
SET email = :'customer_email_updated'
WHERE id = :'customer_id'::bigint;

UPDATE timecritical.orders
SET status = 'PAID'
WHERE id = :'order_id'::bigint;

DELETE FROM timecritical.order_items
WHERE id = :'item_b_id'::bigint;

BEGIN;
INSERT INTO bulk.batch_jobs (job_name, status, run_id)
VALUES (:'batch_job_name', 'PENDING', :'run_id')
RETURNING id AS batch_job_id
\gset

INSERT INTO bulk.pending_records (batch_job_id, payload, run_id)
VALUES (:'batch_job_id'::bigint, :'pending_payload_a', :'run_id')
RETURNING id AS pending_a_id
\gset

INSERT INTO bulk.pending_records (batch_job_id, payload, run_id)
VALUES (:'batch_job_id'::bigint, :'pending_payload_b', :'run_id')
RETURNING id AS pending_b_id
\gset

UPDATE bulk.pending_records
SET processed = true
WHERE id = :'pending_a_id'::bigint;
COMMIT;

\o :expected_file
SELECT json_build_object('seq', 1, 'tx', 'T1', 'op', 'c', 'schema', 'timecritical', 'table', 'customers', 'key', json_build_object('id', :'customer_id'::bigint), 'before', NULL, 'after', json_build_object('external_ref', :'customer_ref', 'email', :'customer_email'))::text;
SELECT json_build_object('seq', 2, 'tx', 'T1', 'op', 'c', 'schema', 'timecritical', 'table', 'orders', 'key', json_build_object('id', :'order_id'::bigint), 'before', NULL, 'after', json_build_object('customer_id', :'customer_id'::bigint, 'order_ref', :'order_ref', 'status', 'NEW', 'total_cents', 4498))::text;
SELECT json_build_object('seq', 3, 'tx', 'T1', 'op', 'c', 'schema', 'timecritical', 'table', 'order_items', 'key', json_build_object('id', :'item_a_id'::bigint), 'before', NULL, 'after', json_build_object('order_id', :'order_id'::bigint, 'sku', :'item_a_sku', 'quantity', 2, 'unit_price_cents', 1999))::text;
SELECT json_build_object('seq', 4, 'tx', 'T1', 'op', 'c', 'schema', 'timecritical', 'table', 'order_items', 'key', json_build_object('id', :'item_b_id'::bigint), 'before', NULL, 'after', json_build_object('order_id', :'order_id'::bigint, 'sku', :'item_b_sku', 'quantity', 1, 'unit_price_cents', 500))::text;
SELECT json_build_object('seq', 5, 'tx', 'T2', 'op', 'u', 'schema', 'timecritical', 'table', 'customers', 'key', json_build_object('id', :'customer_id'::bigint), 'before', json_build_object('email', :'customer_email'), 'after', json_build_object('email', :'customer_email_updated'))::text;
SELECT json_build_object('seq', 6, 'tx', 'T3', 'op', 'u', 'schema', 'timecritical', 'table', 'orders', 'key', json_build_object('id', :'order_id'::bigint), 'before', json_build_object('status', 'NEW'), 'after', json_build_object('status', 'PAID'))::text;
SELECT json_build_object('seq', 7, 'tx', 'T4', 'op', 'd', 'schema', 'timecritical', 'table', 'order_items', 'key', json_build_object('id', :'item_b_id'::bigint), 'before', json_build_object('sku', :'item_b_sku'), 'after', NULL)::text;
\o

SELECT to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS finished_at
\gset
\o :manifest_file
SELECT json_build_object('run_id', :'run_id', 'started_at', :'started_at', 'finished_at', :'finished_at', 'timecritical_events_expected', 7, 'bulk_rows_touched', 3, 'bulk_marker', :'run_id')::text;
\o

\echo Run ID: :run_id
\echo Created ids: customer=:customer_id order=:order_id order_item_a=:item_a_id order_item_b=:item_b_id batch_job=:batch_job_id pending_a=:pending_a_id pending_b=:pending_b_id
\echo Counts: timecritical_events_expected=7 bulk_rows_touched=3
\echo Files: expected=:expected_file manifest=:manifest_file
SQL
