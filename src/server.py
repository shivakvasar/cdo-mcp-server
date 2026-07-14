"""CDO MCP Server — exposes the canonical data model as MCP tools.

Runs in stdio mode (default) for Claude Desktop integration.
MCP (Model Context Protocol) lets Claude call the functions below as tools.
All logging goes to stderr so it does not pollute the stdio message stream.
"""

# ── Imports ───────────────────────────────────────────────────────────────────
import datetime   # for timestamping new records
import logging    # for diagnostic messages to stderr
import pathlib    # for resolving the src/ directory path
import sys        # for sys.stderr (log destination) and sys.path
import uuid       # for generating unique IDs on new records

from mcp.server.fastmcp import FastMCP   # high-level MCP server library

# Ensure the src/ directory is on sys.path so `from data import ...` works
# whether this file is run directly (python src/server.py) or imported as a
# package (from src.server import ...) — e.g. in tests.
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from data import get_db, write_db


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
SERVER_VERSION = "0.1.0"


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
    db = get_db()
    return db["customers"]


@mcp.tool()
def read_job(job_id: str) -> dict:
    """Return a full job record including its tasks and status.

    Args:
        job_id: The id field of the job to look up.

    Returns:
        The job dict with a 'tasks' key added, or an error dict if not found.
    """
    db = get_db()
    job = next((j for j in db["jobs"] if j["id"] == job_id), None)
    if job is None:
        return {"error": f"Job {job_id!r} not found"}
    # Copy the dict before adding 'tasks' so we don't mutate the cached record
    # in _db — without this, the tasks key would persist across future calls.
    job = dict(job)
    job["tasks"] = [t for t in db["tasks"] if t["job_id"] == job_id]
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

    db = get_db()
    record = {
        "id": str(uuid.uuid4()),
        # datetime.timezone.utc produces a timezone-aware timestamp.
        # utcnow() is deprecated in Python 3.12+ so we use now(utc) instead.
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **data,   # spread the caller's fields in after the auto-set ones
    }
    db[entity.lower() + "s"].append(record)
    write_db(db)
    return {"ok": True, "id": record["id"], "entity": entity}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Starting server with transport=stdio")
    mcp.run()
