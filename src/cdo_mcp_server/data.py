# src/cdo_mcp_server/data.py — PostgreSQL-backed canonical data store.
#
# Each entity table (customers/jobs/tasks/invoices — see schema.sql) has a
# few well-known columns (id, created_at, and — where relevant — the
# foreign key linking it to its parent, e.g. jobs.customer_id) plus a JSONB
# `data` column holding everything else. This mirrors the shape
# create_record() has always accepted (an arbitrary dict of fields with id
# and created_at auto-set) without forcing a rigid column-per-field schema
# onto a data model that's still this loose by design.
#
# Connects via the DATABASE_URL environment variable (a standard Postgres
# URL, e.g. postgresql://cdo:cdo@localhost:5432/cdo). See docker-compose.yml
# for a local Postgres instance and schema.sql for the table definitions.
import os

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json

# Maps each entity's plural table name to the column (if any) that holds its
# parent record's id. That field gets pulled out of the caller's data dict
# into its own real (indexed, foreign-keyed) column; every other field
# stays in the JSONB blob as-is.
_FK_COLUMN = {
    "customers": None,
    "jobs": "customer_id",
    "tasks": "job_id",
    "invoices": "job_id",
}


def _connection_string() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Run `docker compose up -d` for a local "
            "Postgres instance, then e.g. "
            "DATABASE_URL=postgresql://cdo:cdo@localhost:5432/cdo"
        )
    return url


def _get_connection() -> psycopg.Connection:
    # row_factory=dict_row: fetch results as {column_name: value} dicts
    # instead of plain tuples, so callers don't need to track column order.
    # autocommit=True: each statement commits immediately — this server
    # only ever runs one query per tool call, so there's no multi-statement
    # transaction to coordinate.
    return psycopg.connect(_connection_string(), row_factory=dict_row, autocommit=True)


def _row_to_record(row: dict) -> dict:
    """Flatten a fetched row (fixed columns + a `data` JSONB blob) back into
    the same flat dict shape the rest of the server has always worked with
    — e.g. {"id": ..., "customer_id": ..., "created_at": ..., "title": ...}
    rather than {"id": ..., "customer_id": ..., "data": {"title": ...}}.
    """
    record = {"id": row["id"], "created_at": row["created_at"].isoformat()}
    # Any column besides id/created_at/data is this table's FK column
    # (customer_id or job_id) — include it only if this row actually has
    # one set (customers have no such column at all).
    fk_column = next((c for c in row if c not in ("id", "created_at", "data")), None)
    if fk_column and row[fk_column] is not None:
        record[fk_column] = row[fk_column]
    record.update(row["data"])
    return record


def list_records(table: str) -> list[dict]:
    """Return every row in `table` (customers/jobs/tasks/invoices) as a flat dict."""
    query = sql.SQL("SELECT * FROM {} ORDER BY created_at").format(sql.Identifier(table))
    with _get_connection() as conn:
        rows = conn.execute(query).fetchall()
    return [_row_to_record(r) for r in rows]


def get_record(table: str, record_id: str) -> dict | None:
    """Return a single row from `table` by id, or None if it doesn't exist."""
    query = sql.SQL("SELECT * FROM {} WHERE id = %s").format(sql.Identifier(table))
    with _get_connection() as conn:
        row = conn.execute(query, (record_id,)).fetchone()
    return _row_to_record(row) if row else None


def list_records_by_fk(table: str, fk_value: str) -> list[dict]:
    """Return every row in `table` whose foreign-key column matches fk_value
    (e.g. list_records_by_fk("tasks", job_id) for a job's tasks).
    """
    fk_column = _FK_COLUMN[table]
    query = sql.SQL("SELECT * FROM {} WHERE {} = %s ORDER BY created_at").format(
        sql.Identifier(table), sql.Identifier(fk_column)
    )
    with _get_connection() as conn:
        rows = conn.execute(query, (fk_value,)).fetchall()
    return [_row_to_record(r) for r in rows]


def insert_record(table: str, record_id: str, created_at: str, fields: dict) -> None:
    """Insert a new row into `table`, splitting its FK field (if any, e.g.
    "customer_id" for jobs) out of `fields` into its own column — everything
    else in `fields` is stored as-is in the JSONB `data` column.
    """
    fk_column = _FK_COLUMN[table]
    extra = dict(fields)
    fk_value = extra.pop(fk_column, None) if fk_column else None

    columns = ["id", "created_at", "data"]
    values = [record_id, created_at, Json(extra)]
    if fk_column:
        columns.insert(1, fk_column)
        values.insert(1, fk_value)

    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        sql.SQL(", ").join(sql.Placeholder() * len(values)),
    )
    with _get_connection() as conn:
        conn.execute(query, values)
