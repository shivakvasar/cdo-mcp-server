"""Weekly Ops Summary — run by .github/workflows/weekly-ops-summary.yml.

Reads jobs, invoices, and customers by calling cdo-mcp-server's own
canonical MCP tools (list_jobs, list_invoices, list_customers) over stdio,
exactly the way Claude Desktop does — rather than reading data/db.json
directly, which would duplicate the server's own data-access logic and
drift out of sync with it over time.

Then asks Claude to turn that data into a short weekly summary, and writes
the result to reports/<date>.md.
"""
import asyncio
import datetime
import json
import os
import pathlib

import anthropic
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
MODEL = "claude-sonnet-5"


def _tool_result_list(result) -> list[dict]:
    """Pull the plain list of records out of a list[dict]-returning tool call.

    `result` here is an mcp.types.CallToolResult — what session.call_tool()
    returns. It carries the tool's output in two possibly-overlapping forms:
      - result.content: a list of content "blocks" (usually TextContent),
        the universal fallback every tool response includes.
      - result.structuredContent: a JSON-shaped dict, only populated when
        FastMCP can infer a schema from the tool's return type annotation.

    Tested this by hand against a running server: for a tool annotated
    `-> list[dict]` (list_customers, and by extension list_jobs/
    list_invoices, which mirror it exactly), FastMCP always sets
    structuredContent to {"result": [...the actual list...]}. Tools
    annotated plain `-> dict` (like read_job) leave structuredContent as
    None instead, and only content has the data — so this helper only
    works for list[dict]-returning tools, which is all we call here.
    """
    if result.isError:
        # Errors still arrive as text content, not an exception — MCP calls
        # don't raise Python exceptions on tool-level failures, only on
        # transport-level ones (e.g. the subprocess dying).
        text = "".join(block.text for block in result.content if block.type == "text")
        raise RuntimeError(f"MCP tool call failed: {text}")
    return result.structuredContent["result"]


async def fetch_ops_data() -> dict:
    """Launch cdo-mcp-server as a subprocess and call its canonical tools.

    This function is `async` because the mcp client library is built on
    asyncio throughout (spawning the subprocess and reading/writing its
    stdio pipes without blocking) — every mcp call in here needs `await`.
    main() bridges into this async world with a single asyncio.run() call,
    so the rest of the script can stay ordinary synchronous code.

    stdio_client() spawns "cdo-mcp-server" (the console script installed by
    `pip install -e .` / `pip install cdo-mcp-server`) as a child process and
    hands back a (read, write) pair of streams connected to its stdin/stdout
    — the same transport Claude Desktop uses. ClientSession wraps those
    streams with the actual MCP protocol (requests, responses, IDs).
    Both are async context managers (`async with`), so the subprocess and
    the session get cleaned up automatically once the `with` block exits,
    even if a call_tool() below raises.

    session.initialize() performs the MCP handshake and must happen before
    any call_tool() — skipping it would fail since the server doesn't know
    the client's capabilities yet.
    """
    params = StdioServerParameters(command="cdo-mcp-server", args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            jobs = _tool_result_list(await session.call_tool("list_jobs", {}))
            invoices = _tool_result_list(await session.call_tool("list_invoices", {}))
            customers = _tool_result_list(await session.call_tool("list_customers", {}))
    return {"jobs": jobs, "invoices": invoices, "customers": customers}


def render_summary(ops_data: dict) -> str:
    """Ask Claude to turn the raw records into a short weekly ops summary.

    We hand Claude the raw JSON and a plain-English instruction rather than
    computing things like "overdue jobs" ourselves in Python — the data
    model here is still loose (e.g. invoices have no fixed schema yet), so
    letting Claude reason over the raw records is more robust than writing
    brittle field-specific logic that breaks the moment the schema changes.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    "Here is this week's raw data from our job-tracking system, "
                    "as JSON (jobs, invoices, and customers):\n\n"
                    f"{json.dumps(ops_data, indent=2)}\n\n"
                    "Write a short weekly ops summary in Markdown: total open "
                    "jobs, any jobs that look stalled or overdue, invoice "
                    "totals/outstanding amounts, and anything else notable. "
                    "Keep it under 300 words."
                ),
            }
        ],
    )
    # message.content is a list of content blocks (Claude can return more
    # than one, e.g. thinking + text); join just the text ones into a
    # single string since that's all a plain-text prompt like this produces.
    return "".join(block.text for block in message.content if block.type == "text")


def main() -> None:
    # asyncio.run() creates an event loop, runs fetch_ops_data() to
    # completion, then tears the loop down — the standard way to call into
    # async code from an otherwise-synchronous script/entry point.
    ops_data = asyncio.run(fetch_ops_data())
    summary = render_summary(ops_data)

    # exist_ok=True: don't error if reports/ is already there from a
    # previous week's run (mkdir alone would raise FileExistsError).
    REPORTS_DIR.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    report_path = REPORTS_DIR / f"{today}.md"
    report_path.write_text(f"# Weekly Ops Summary — {today}\n\n{summary}\n")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
