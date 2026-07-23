"""CDO MCP Server — exposes the canonical data model as MCP tools.

Runs in stdio mode (default) for Claude Desktop integration.
MCP (Model Context Protocol) lets Claude call the functions below as tools.
All logging goes to stderr so it does not pollute the stdio message stream.
"""

# ── Imports ───────────────────────────────────────────────────────────────────
import datetime   # for timestamping new records
import logging    # for diagnostic messages to stderr
import sys        # for sys.stderr (log destination)
import uuid       # for generating unique IDs on new records

from mcp.server.fastmcp import FastMCP   # high-level MCP server library

# Imported as a module, aliased to `db` rather than `data` — create_record's
# own `data` parameter below (part of its public tool signature, so it can't
# just be renamed) would otherwise shadow the module name inside that function.
from . import data as db


# ── Logging setup ─────────────────────────────────────────────────────────────
# Writes to stderr so log lines never mix with the MCP stdio message stream.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ── Server constants ──────────────────────────────────────────────────────────
SERVER_NAME = "CDO Data Server"
SERVER_VERSION = "1.0.0"


# ── Create the MCP server instance ────────────────────────────────────────────
mcp = FastMCP(SERVER_NAME)
logger.info("Initialised %s v%s", SERVER_NAME, SERVER_VERSION)


# ── Diagnostic tools ──────────────────────────────────────────────────────────
@mcp.tool()
def echo(message: str) -> str:
    """Echo a message back. Used to verify the MCP server is running correctly.

    Args:
        message: Any string to echo back.

    Returns:
        The same string prefixed with 'CDO MCP echo: '
    """
    logger.info("echo called with: %r", message)
    return f"CDO MCP echo: {message}"


@mcp.tool()
def status() -> dict:
    """Return the server name, version, and list of registered tools.

    Returns:
        A dict with keys 'server', 'version', and 'tools'.
    """
    # _tool_manager._tools is FastMCP's internal registry of all registered tools.
    # The underscore prefix means it's private/internal — no public API exists yet.
    tool_names = list(mcp._tool_manager._tools.keys())
    logger.info("status called — tools: %s", tool_names)
    return {
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "tools": tool_names,
    }


# ── Data tools ────────────────────────────────────────────────────────────────
@mcp.tool()
def list_customers() -> list[dict]:
    """Return all customer records."""
    return db.list_records("customers")


# list_jobs and list_invoices are deliberately just list_customers with the
# table name swapped — same shape, same "-> list[dict]" return type. Keeping
# them this simple/uniform matters: any script that treats one of these as
# an MCP client (see scripts/ops_summary.py) can rely on all three behaving
# identically over the wire (FastMCP wraps list[dict] returns as
# {"result": [...]} in structuredContent, verified by hand against a real
# call — dict-only return types like read_job's don't get that treatment).
@mcp.tool()
def list_jobs() -> list[dict]:
    """Return all job records (without their tasks — see read_job for that)."""
    return db.list_records("jobs")


@mcp.tool()
def list_invoices() -> list[dict]:
    """Return all invoice records."""
    return db.list_records("invoices")


@mcp.tool()
def read_job(job_id: str) -> dict:
    """Return a full job record including its tasks and status.

    Args:
        job_id: The id field of the job to look up.

    Returns:
        The job dict with a 'tasks' key added, or an error dict if not found.
    """
    job = db.get_record("jobs", job_id)
    if job is None:
        return {"error": f"Job {job_id!r} not found"}
    job["tasks"] = db.list_records_by_fk("tasks", job_id)
    return job


# VALID_ENTITIES is defined outside the function so it is only created once,
# not rebuilt on every call. It also documents the supported entity types clearly.
VALID_ENTITIES = {"Customer", "Job", "Invoice", "Task"}


@mcp.tool()
def create_record(entity: str, data: dict) -> dict:
    """Create a new record and persist it to the data store.

    Args:
        entity: One of Customer | Job | Invoice | Task
        data:   Dict of fields for that entity (id and created_at are auto-set).

    Returns:
        A dict with 'ok', 'id', and 'entity' on success, or 'error' on failure.
    """
    if entity not in VALID_ENTITIES:
        return {"error": f"Unknown entity {entity!r}. Must be one of {VALID_ENTITIES}"}

    record_id = str(uuid.uuid4())
    # datetime.timezone.utc produces a timezone-aware timestamp.
    # utcnow() is deprecated in Python 3.12+ so we use now(utc) instead.
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db.insert_record(entity.lower() + "s", record_id, created_at, data)
    return {"ok": True, "id": record_id, "entity": entity}


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    """Console-script entry point (see [project.scripts] in pyproject.toml)."""
    logger.info("Starting server with transport=stdio")
    mcp.run()


if __name__ == "__main__":
    main()
