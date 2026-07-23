"""One-off migration: load data/db.json's records into Postgres.

Run once after `docker compose up -d` (and with DATABASE_URL set) to carry
over the existing seed data — e.g. the "Tan Brothers Pte Ltd" customer and
"Office Rewire" job used for local dev and the Wednesday Claude Desktop
test — from the old JSON file store into the new schema.sql tables.

Usage:
    docker compose up -d
    DATABASE_URL=postgresql://cdo:cdo@localhost:5432/cdo \\
        python scripts/migrate_json_to_postgres.py
"""
import datetime
import json
import pathlib
import sys

# Import the package the same way tests do, so this also works without
# `pip install -e .` first — see tests/test_server.py for the same trick.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from cdo_mcp_server import data as db  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
JSON_DB_PATH = REPO_ROOT / "data" / "db.json"

# Order matters: jobs/tasks/invoices have foreign keys pointing at rows
# inserted earlier in this list (customers before jobs, jobs before
# tasks/invoices), so inserting out of order would violate the FK
# constraints in schema.sql.
TABLES_IN_FK_ORDER = ["customers", "jobs", "tasks", "invoices"]


def main() -> None:
    old_db = json.loads(JSON_DB_PATH.read_text())

    for table in TABLES_IN_FK_ORDER:
        records = old_db.get(table, [])
        for record in records:
            fields = {k: v for k, v in record.items() if k not in ("id", "created_at")}
            # A handful of the original seed records (cust-1, job-1, task-1,
            # task-2) predate create_record ever setting created_at, so they
            # have no timestamp at all in the JSON — fall back to "now" for
            # those rather than leaving the column null.
            created_at = record.get(
                "created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
            db.insert_record(table, record["id"], created_at, fields)
        print(f"Migrated {len(records)} row(s) into {table}")


if __name__ == "__main__":
    main()
