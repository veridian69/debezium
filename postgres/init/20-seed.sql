INSERT INTO timecritical.customers (external_ref, name, email)
VALUES
    ('cust-seed-1', 'Ada Lovelace', 'ada@example.test'),
    ('cust-seed-2', 'Grace Hopper', 'grace@example.test'),
    ('cust-seed-3', 'Edsger Dijkstra', 'edsger@example.test')
ON CONFLICT (external_ref) DO NOTHING;

INSERT INTO timecritical.orders (customer_id, order_ref, status, total_cents)
SELECT c.id, v.order_ref, v.status, v.total_cents
FROM (
    VALUES
        ('cust-seed-1', 'ord-seed-1', 'NEW', 2500::bigint),
        ('cust-seed-1', 'ord-seed-2', 'PAID', 1999::bigint),
        ('cust-seed-2', 'ord-seed-3', 'NEW', 7500::bigint),
        ('cust-seed-3', 'ord-seed-4', 'SHIPPED', 1200::bigint)
) AS v(external_ref, order_ref, status, total_cents)
JOIN timecritical.customers AS c ON c.external_ref = v.external_ref
ON CONFLICT (order_ref) DO NOTHING;

INSERT INTO timecritical.order_items (order_id, sku, quantity, unit_price_cents)
SELECT o.id, v.sku, v.quantity, v.unit_price_cents
FROM (
    VALUES
        ('ord-seed-1', 'SEED-A1', 1, 2500::bigint),
        ('ord-seed-2', 'SEED-B1', 1, 999::bigint),
        ('ord-seed-2', 'SEED-B2', 2, 500::bigint),
        ('ord-seed-3', 'SEED-C1', 3, 2000::bigint),
        ('ord-seed-3', 'SEED-C2', 1, 1500::bigint),
        ('ord-seed-4', 'SEED-D1', 1, 400::bigint),
        ('ord-seed-4', 'SEED-D2', 2, 300::bigint),
        ('ord-seed-4', 'SEED-D3', 1, 200::bigint)
) AS v(order_ref, sku, quantity, unit_price_cents)
JOIN timecritical.orders AS o ON o.order_ref = v.order_ref
ON CONFLICT (order_id, sku) DO NOTHING;

INSERT INTO bulk.batch_jobs (job_name, status)
VALUES
    ('seed-batch-1', 'PENDING'),
    ('seed-batch-2', 'COMPLETE')
ON CONFLICT (job_name) DO NOTHING;

INSERT INTO bulk.pending_records (batch_job_id, payload, processed)
SELECT b.id, v.payload, v.processed
FROM (
    VALUES
        ('seed-batch-1', 'seed-payload-1', false),
        ('seed-batch-1', 'seed-payload-2', true),
        ('seed-batch-1', 'seed-payload-3', false),
        ('seed-batch-2', 'seed-payload-4', true),
        ('seed-batch-2', 'seed-payload-5', false)
) AS v(job_name, payload, processed)
JOIN bulk.batch_jobs AS b ON b.job_name = v.job_name
ON CONFLICT (batch_job_id, payload) DO NOTHING;
