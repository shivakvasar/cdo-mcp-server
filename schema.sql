-- Schema for cdo-mcp-server's canonical data model.
--
-- Each table has a few well-known, indexed columns — id, created_at, and
-- (where relevant) the foreign key linking it to its parent record — plus a
-- JSONB `data` column holding everything else. This mirrors the shape
-- create_record() has always accepted (an arbitrary dict of fields, with id
-- and created_at auto-set) without forcing a rigid column-per-field schema
-- onto a data model that's still this loose by design.
--
-- Auto-run by the postgres Docker image on first container start (files in
-- /docker-entrypoint-initdb.d/ execute once, against an empty data volume).

CREATE TABLE IF NOT EXISTS customers (
    id         TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    data       JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    data        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_jobs_customer_id ON jobs(customer_id);

CREATE TABLE IF NOT EXISTS tasks (
    id         TEXT PRIMARY KEY,
    job_id     TEXT REFERENCES jobs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    data       JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_tasks_job_id ON tasks(job_id);

CREATE TABLE IF NOT EXISTS invoices (
    id         TEXT PRIMARY KEY,
    job_id     TEXT REFERENCES jobs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    data       JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_invoices_job_id ON invoices(job_id);
