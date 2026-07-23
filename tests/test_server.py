"""Tests for the CDO MCP server tools.

Each @mcp.tool()-decorated function in src/cdo_mcp_server/server.py is just a
normal Python function underneath the decorator (FastMCP registers it but
returns it unchanged), so we can import and call them directly here instead
of having to spin up the real MCP stdio server and talk to it over JSON-RPC.

Requires a running Postgres (see docker-compose.yml: `docker compose up -d`)
— data.py has no in-memory/file fallback anymore, so every test in this file
needs a real database to talk to.

Pytest auto-discovers this file because it's named test_*.py, and it treats
every function named test_* as its own independent test case.
"""
import os
import pathlib
import sys

import psycopg
import pytest

# cdo_mcp_server lives under src/, following the "src layout" convention.
# Adding src/ (not the package itself) to sys.path lets us import it as a
# normal package below without requiring `pip install -e .` first.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from cdo_mcp_server.server import (
    create_record,
    echo,
    list_customers,
    list_invoices,
    list_jobs,
    read_job,
    status,
)

# Two separate databases in the same local Postgres instance (both created
# by docker-compose.yml's init scripts, same schema.sql applied to each):
#   - cdo_test: throwaway, truncated before every test below.
#   - cdo:      the real dev database (seeded via
#               scripts/migrate_json_to_postgres.py) — only the real_db-
#               marked test at the bottom reads from this one, and only
#               ever reads, never writes.
# Overridable via env vars in case CI points its Postgres service elsewhere.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://cdo:cdo@localhost:5432/cdo_test"
)
DEV_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://cdo:cdo@localhost:5432/cdo"
)


@pytest.fixture(autouse=True)
def isolated_db(request, monkeypatch):
    """Point every tool call at the throwaway cdo_test database, emptied
    before each test.

    A pytest fixture is just a function whose return value (or, for
    generator fixtures like this one, whose value up to the `yield`) pytest
    hands to any test that asks for it by naming it as an argument.
    `autouse=True` means every test in this file gets it automatically,
    without needing to list `isolated_db` as an argument themselves.

    Why this exists: data.py reads the DATABASE_URL environment variable
    fresh on every connection (see data._connection_string), so pointing it
    at cdo_test here — instead of the real "cdo" dev database — keeps tests
    from reading or overwriting the real seeded data (Tan Brothers Pte Ltd,
    the Office Rewire job, etc.) that Claude Desktop also uses.

    TRUNCATE ... CASCADE before each test (rather than only once) gives every
    test a guaranteed-empty set of tables to start from, regardless of what
    an earlier test inserted — the Postgres equivalent of the old fixture's
    "fresh temp file per test".

    monkeypatch.setenv undoes itself automatically after each test, so
    DATABASE_URL is restored to whatever it was before this test ran.

    Tests marked `@pytest.mark.real_db` (see
    test_read_job_matches_seeded_dev_database below) skip all of this so
    they can read the real "cdo" database instead.
    """
    if "real_db" in request.keywords:
        # request.keywords holds the markers attached to the current test.
        # If it's marked real_db, point at the dev database and skip
        # truncating anything.
        monkeypatch.setenv("DATABASE_URL", DEV_DATABASE_URL)
        yield
        return

    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE customers, jobs, tasks, invoices CASCADE")
    yield


def test_echo_returns_message_with_prefix():
    # echo() is the simplest tool: no db involved, just string formatting.
    # This just confirms the exact prefix hasn't been changed by accident.
    assert echo("hello") == "CDO MCP echo: hello"


def test_status_lists_all_registered_tools():
    result = status()
    assert result["server"] == "CDO Data Server"
    # We don't assert the full tool list (that would break every time a tool
    # is added), just that a couple of the tools we care about are present.
    assert "list_customers" in result["tools"]
    assert "list_jobs" in result["tools"]
    assert "list_invoices" in result["tools"]
    assert "create_record" in result["tools"]


def test_list_customers_returns_created_customers():
    # Thanks to isolated_db, cdo_test starts completely empty — so we have
    # to seed it ourselves via create_record before list_customers has
    # anything to return.
    create_record("Customer", {"name": "Acme Co", "email": "acme@example.com"})

    customers = list_customers()

    assert len(customers) == 1
    assert customers[0]["name"] == "Acme Co"


def test_list_jobs_returns_created_jobs():
    # Same pattern as test_list_customers_returns_created_customers above:
    # isolated_db means we start from an empty db, so seed one job first.
    # jobs.customer_id is a real foreign key (see schema.sql), so the
    # customer row has to exist before a job can reference its id — unlike
    # the old JSON store, Postgres actually enforces this.
    customer = create_record("Customer", {"name": "Acme Co"})
    create_record(
        "Job", {"customer_id": customer["id"], "title": "Rewire", "status": "Open"}
    )

    jobs = list_jobs()

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Rewire"


def test_list_invoices_returns_created_invoices():
    # invoices.job_id is a real foreign key too, so a job (and the customer
    # it belongs to) has to exist first.
    customer = create_record("Customer", {"name": "Acme Co"})
    job = create_record("Job", {"customer_id": customer["id"], "title": "Rewire"})
    create_record("Invoice", {"job_id": job["id"], "amount": 500, "status": "Unpaid"})

    invoices = list_invoices()

    assert len(invoices) == 1
    assert invoices[0]["amount"] == 500


def test_read_job_returns_job_with_its_tasks():
    # Create a customer, then a job for that customer, then a task attached
    # to that job (via job_id) — each one a real foreign key now — then
    # check read_job() stitches the job and its tasks together correctly.
    customer = create_record("Customer", {"name": "Acme Co"})
    job_result = create_record(
        "Job", {"customer_id": customer["id"], "title": "Rewire", "status": "Open"}
    )
    job_id = job_result["id"]
    create_record("Task", {"job_id": job_id, "title": "Survey", "done": False})

    job = read_job(job_id)

    assert job["title"] == "Rewire"
    # read_job() adds a "tasks" key via data.list_records_by_fk("tasks", ...)
    # (see cdo_mcp_server/server.py's read_job) — confirm that logic worked.
    assert len(job["tasks"]) == 1
    assert job["tasks"][0]["title"] == "Survey"


def test_create_record_persists_and_returns_id():
    result = create_record(
        "Customer", {"name": "Tan Brothers", "email": "tan@example.com"}
    )

    assert result["ok"] is True
    assert result["entity"] == "Customer"
    # The two asserts above only prove create_record's return value looks
    # right. This confirms the record was actually saved to the db (not just
    # echoed back), by looking it up again through a separate tool call.
    customers = list_customers()
    assert any(c["id"] == result["id"] for c in customers)


@pytest.mark.real_db
def test_read_job_matches_seeded_dev_database():
    """Regression check against the real "cdo" dev database.

    Every test above runs against the throwaway cdo_test database so it
    can't touch real data. This one intentionally opts out of that
    isolation (see the `real_db` marker check in the isolated_db fixture
    above) so it reads the actual dev database exactly as Claude Desktop
    would — catching accidental drift in the seed data, e.g. if job-1's
    title or tasks get edited by hand.

    Read-only on purpose: it must never call create_record here, since that
    would permanently write test data into the same database Claude Desktop
    reads from.
    """
    job = read_job("job-1")

    assert job["title"] == "Office Rewire"
    assert job["customer_id"] == "cust-1"
    # List comprehension pulls out just the "title" field from each task
    # dict, so we can compare against a plain list of the expected titles
    # in the expected order (site survey happens before the cable run).
    assert [t["title"] for t in job["tasks"]] == ["Site survey", "Cable run"]

    customers = list_customers()
    # next(... a generator expression ...) grabs the first matching item, or
    # raises StopIteration (failing the test) if cust-1 isn't found at all.
    tan_brothers = next(c for c in customers if c["id"] == "cust-1")
    assert tan_brothers["name"] == "Tan Brothers Pte Ltd"
