CREATE SCHEMA timecritical;
CREATE SCHEMA bulk;

CREATE TABLE timecritical.customers (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_ref text NOT NULL UNIQUE,
    name text NOT NULL,
    email text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE timecritical.orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES timecritical.customers(id),
    order_ref text NOT NULL UNIQUE,
    status text NOT NULL,
    total_cents bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE timecritical.order_items (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES timecritical.orders(id),
    sku text NOT NULL,
    quantity integer NOT NULL,
    unit_price_cents bigint NOT NULL,
    UNIQUE (order_id, sku)
);

CREATE TABLE bulk.batch_jobs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_name text NOT NULL UNIQUE,
    status text NOT NULL,
    run_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bulk.pending_records (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_job_id bigint NOT NULL REFERENCES bulk.batch_jobs(id),
    payload text NOT NULL,
    processed boolean NOT NULL DEFAULT false,
    run_id text,
    UNIQUE (batch_job_id, payload)
);

ALTER TABLE timecritical.customers REPLICA IDENTITY FULL;
ALTER TABLE timecritical.orders REPLICA IDENTITY FULL;
ALTER TABLE timecritical.order_items REPLICA IDENTITY FULL;
