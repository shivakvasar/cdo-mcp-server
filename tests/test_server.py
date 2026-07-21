"""Tests for the CDO MCP server tools.

Each @mcp.tool()-decorated function in src/server.py is just a normal Python
function underneath the decorator (FastMCP registers it but returns it
unchanged), so we can import and call them directly here instead of having
to spin up the real MCP stdio server and talk to it over JSON-RPC.

Pytest auto-discovers this file because it's named test_*.py, and it treats
every function named test_* as its own independent test case.
"""
import pathlib
import sys

import pytest

# server.py does this same trick so `from data import ...` works no matter
# how it's run. We need it here too since this test file imports from src/.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

# Imported as a module (not `from data import get_db`) so that when a test
# does monkeypatch.setattr(data_module, "DB_PATH", ...), every other piece of
# code that later calls data.get_db() sees the patched value too. If we'd
# imported get_db by name instead, patching data_module wouldn't affect it.
import data as data_module
from server import create_record, echo, list_customers, read_job, status


@pytest.fixture(autouse=True)
def isolated_db(request, tmp_path, monkeypatch):
    """Point the data store at a throwaway file for every test.

    A pytest fixture is just a function whose return value (or, for
    generator fixtures like this one, whose value up to the `yield`) pytest
    hands to any test that asks for it by naming it as an argument.
    `autouse=True` means every test in this file gets it automatically,
    without needing to list `isolated_db` as an argument themselves.

    Why this exists: without it, tests would read and write data/db.json —
    the real database Claude Desktop uses — and would also leak data between
    tests via the module-level `_db` cache in data.py (get_db() only reads
    from disk once and then reuses whatever is already in memory, so one
    test's writes would still be sitting there for the next test).

    Fixture arguments (pytest supplies all three automatically):
      request:    info about the test currently requesting this fixture —
                  used below to check which markers were applied to it.
      tmp_path:   a pathlib.Path to a fresh, empty directory that pytest
                  creates for this test and deletes afterwards. Perfect for
                  a "fake" db.json that won't collide with other tests.
      monkeypatch: lets us temporarily overwrite an attribute (here,
                  data_module.DB_PATH and data_module._db) and have it
                  automatically restored to its original value the moment
                  this test finishes — even if the test fails or raises.

    Because this function contains a `yield`, pytest treats it as a
    "generator fixture": code before `yield` is setup (runs before the
    test), and anything after `yield` would be teardown (runs after the
    test). We don't need teardown code here since monkeypatch handles the
    restoring for us — the bare `yield` just marks "now run the test".

    Tests marked `@pytest.mark.real_db` (see test_read_job_matches_seeded_db_json
    below) skip all of this so they can read the actual data/db.json instead.
    """
    if "real_db" in request.keywords:
        # request.keywords holds the markers attached to the current test.
        # If it's marked real_db, skip straight to running the test without
        # touching DB_PATH or _db at all.
        yield
        return

    fake_db_path = tmp_path / "db.json"
    monkeypatch.setattr(data_module, "DB_PATH", fake_db_path)
    # data.py's get_db() only loads from disk when _db is None (see its
    # "Holds the loaded data after the first read" comment), so resetting it
    # here forces the next get_db() call to load fresh from fake_db_path
    # instead of reusing whatever a previous test already loaded into memory.
    monkeypatch.setattr(data_module, "_db", None)
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
    assert "create_record" in result["tools"]


def test_list_customers_returns_created_customers():
    # Thanks to isolated_db, the fake db starts completely empty — so we
    # have to seed it ourselves via create_record before list_customers has
    # anything to return.
    create_record("Customer", {"name": "Acme Co", "email": "acme@example.com"})

    customers = list_customers()

    assert len(customers) == 1
    assert customers[0]["name"] == "Acme Co"


def test_read_job_returns_job_with_its_tasks():
    # Create a job, then a task attached to that job (via job_id), then
    # check read_job() stitches the two together correctly.
    job_result = create_record(
        "Job", {"customer_id": "cust-1", "title": "Rewire", "status": "Open"}
    )
    job_id = job_result["id"]
    create_record("Task", {"job_id": job_id, "title": "Survey", "done": False})

    job = read_job(job_id)

    assert job["title"] == "Rewire"
    # read_job() adds a "tasks" key by filtering db["tasks"] for matching
    # job_id (see src/server.py's read_job) — confirm that logic worked.
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
def test_read_job_matches_seeded_db_json():
    """Regression check against the real data/db.json shipped with the repo.

    Every test above runs against an isolated temp file so it can't touch the
    real database. This one intentionally opts out of that isolation (see
    the `real_db` marker check in the isolated_db fixture above) so it reads
    data/db.json exactly as Claude Desktop would — catching accidental drift
    in the seed data, e.g. if job-1's title or tasks get edited by hand.

    Read-only on purpose: it must never call create_record here, since that
    would permanently write test data into the real database file that
    Claude Desktop also reads from.
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
