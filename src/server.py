"""CDO MCP Server — exposes the canonical data model as MCP tools.

Week 3 scaffold: single echo tool to verify the server starts
and is visible in Claude Desktop before adding real data tools.

What is MCP?
    MCP (Model Context Protocol) is a standard that lets Claude talk to
    external tools and data sources. This server registers 'tools' that
    Claude can call — like functions Claude can invoke on your behalf.

How does the server talk to Claude Desktop?
    Claude Desktop launches this script as a subprocess and communicates
    over stdio (standard input/output). Every message Claude sends comes
    in via stdin; every response goes back via stdout. That's why all our
    logging goes to stderr — we must not pollute stdout with debug text.
"""

# ── Imports ───────────────────────────────────────────────────────────────────
# argparse: Python's built-in library for parsing command-line arguments.
#   e.g. lets us run: python server.py --transport http
import argparse

# logging: Python's built-in library for printing diagnostic messages.
#   Using it instead of print() gives us timestamps, severity levels
#   (INFO, WARNING, ERROR), and easy control over output destination.
import logging

# sys: gives access to sys.stderr (the error output stream) and sys.argv
#   (the list of command-line arguments passed to the script).
import sys

# FastMCP: a high-level Python library that makes it easy to build MCP servers.
#   The @mcp.tool() decorator is how we register a Python function as a tool
#   that Claude can discover and call.
from mcp.server.fastmcp import FastMCP


# ── Logging setup ─────────────────────────────────────────────────────────────
# basicConfig sets up the global logging configuration once at startup.
#
# stream=sys.stderr  → write log lines to stderr, NOT stdout.
#                       MCP uses stdout to send/receive protocol messages,
#                       so mixing logs into stdout would break the connection.
#
# level=logging.INFO → show messages at INFO level and above (INFO, WARNING,
#                       ERROR, CRITICAL). DEBUG messages are hidden by default.
#                       Change to logging.DEBUG while troubleshooting to see
#                       more detail.
#
# format=...         → how each log line looks. %(asctime)s is the timestamp,
#                       %(levelname)s is INFO/WARNING/etc, %(message)s is
#                       the text we pass to logger.info() / logger.warning().
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# getLogger(__name__) creates a logger named after this file/module.
# Using __name__ (which equals "__main__" when run directly, or the module
# name when imported) lets Python's logging system identify where each
# message came from if you later have multiple modules logging.
logger = logging.getLogger(__name__)


# ── Server constants ──────────────────────────────────────────────────────────
# Constants are variables that never change after they're defined.
# By convention, Python names them in ALL_CAPS.
#
# SERVER_NAME appears in Claude Desktop's tool list — it's how the user
# identifies which server a tool belongs to.
#
# SERVER_VERSION follows Semantic Versioning (semver): MAJOR.MINOR.PATCH.
# Bump PATCH for bug fixes, MINOR for new tools, MAJOR for breaking changes.
SERVER_NAME = "CDO Data Server"
SERVER_VERSION = "0.1.0"
DEFAULT_HTTP_PORT = 3001  # matches the port configured in Claude Code / VSCode


# ── Argument parsing (early) ──────────────────────────────────────────────────
# We parse args here — before creating the FastMCP instance — because the
# port must be passed to the FastMCP constructor. It cannot be set later.
#
# argparse normally reads sys.argv[1:], so nothing is consumed here at import
# time; it only runs when the script is executed directly (see __main__ below).
# But we call _parse_args() at module level so @mcp.tool()-decorated functions
# can be defined on the correctly-configured mcp object.
def _parse_args() -> "argparse.Namespace":
    """Parse command-line arguments and return them as a Namespace object.

    A Namespace is just an object whose attributes match the argument names,
    so after parsing you can do args.transport to get the value.
    """
    # ArgumentParser creates the argument parser with a helpful description
    # that shows up when you run: python server.py --help
    parser = argparse.ArgumentParser(description="CDO MCP Server")

    # add_argument defines a single CLI flag.
    #   "--transport"        the flag name (double-dash = optional argument)
    #   choices=[...]        only these values are accepted; anything else
    #                        causes an error with a helpful message
    #   default="stdio"      used if --transport is not provided at all
    #   help=...             shown in --help output
    #
    # Usage examples:
    #   python server.py                     → transport is "stdio" (default)
    #   python server.py --transport http    → transport is "http"
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport to use (default: stdio for Claude Desktop; streamable-http for Claude Code / VSCode)",
    )

    # --port controls which TCP port the HTTP server listens on.
    # Only relevant when --transport http is used.
    # Default matches the port configured in Claude Code / VSCode extension.
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_HTTP_PORT,
        help=f"Port for HTTP transport (default: {DEFAULT_HTTP_PORT})",
    )

    return parser.parse_args()


_args = _parse_args()


# ── Create the MCP server instance ────────────────────────────────────────────
# FastMCP(SERVER_NAME, port=...) creates the server object. The port is set
# here in the constructor — FastMCP.run() does not accept a port argument.
# port= is only used when transport="http"; it is ignored for stdio.
# streamable_http_path="/sse" matches the URL Claude Code / VSCode sends requests to.
# FastMCP defaults to "/mcp" but the extension is hard-coded to POST to "/sse".
mcp = FastMCP(SERVER_NAME, port=_args.port, streamable_http_path="/sse")

# Log a message so we can see in the terminal that this line was reached.
logger.info("Initialised %s v%s", SERVER_NAME, SERVER_VERSION)


# ── Echo tool ─────────────────────────────────────────────────────────────────
# The @mcp.tool() decorator registers the function below as an MCP tool.
# A 'decorator' in Python is a way to wrap a function with extra behaviour —
# here it tells FastMCP "make this function callable by Claude."
#
# Claude reads the function's docstring to understand what the tool does,
# and reads the type hints (message: str) to know what arguments to pass.
@mcp.tool()
def echo(message: str) -> str:
    """Echo a message back. Used to verify the MCP server is running correctly.

    Args:
        message: Any string to echo back.

    Returns:
        The same string prefixed with 'CDO MCP echo: '
    """
    # %r formats the message with quotes around it (repr format), so if
    # message is hello, the log shows: echo called with: 'hello'
    # This makes it easy to spot if the string contains unexpected spaces
    # or special characters.
    logger.info("echo called with: %r", message)

    # f-strings let us embed variables directly inside a string using {}.
    # This returns something like: "CDO MCP echo: hello world"
    return f"CDO MCP echo: {message}"


# ── Status tool ───────────────────────────────────────────────────────────────
# The return type hint `-> dict` means this function returns a Python
# dictionary — a collection of key-value pairs, like a small JSON object.
# FastMCP automatically converts the dict to JSON when sending it to Claude.
@mcp.tool()
def status() -> dict:
    """Return the server name, version, and list of registered tools.

    Returns:
        A dict with keys 'server', 'version', and 'tools'.
    """
    # mcp._tool_manager._tools is an internal dict inside FastMCP where
    # all registered tools are stored, keyed by their function name.
    # The leading underscore (_) on _tool_manager and _tools is a Python
    # convention meaning "this is private / internal — use with care."
    # We use it here because FastMCP doesn't expose a public API for this yet.
    #
    # .keys() returns all the key names from that dict (i.e. tool names).
    # list(...) converts them from a dict_keys view into a plain Python list.
    tool_names = list(mcp._tool_manager._tools.keys())
    logger.info("status called — tools: %s", tool_names)

    # Return a dict that Claude will receive as a JSON object, e.g.:
    # { "server": "CDO Data Server", "version": "0.1.0", "tools": ["echo", "status"] }
    return {
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "tools": tool_names,
    }


# ── Entry point ───────────────────────────────────────────────────────────────
# `if __name__ == "__main__":` is a Python idiom that means:
#   "only run this block if the script was executed directly (e.g.
#    python server.py), NOT if it was imported by another module."
# This prevents the server from starting automatically when the file is
# imported in tests or other scripts.
if __name__ == "__main__":
    logger.info("Starting server with transport=%s port=%s", _args.transport, _args.port)

    # mcp.run() starts the server and blocks until it is shut down.
    # transport="stdio" is required for Claude Desktop integration.
    # transport="http"  is handy for manual testing with curl or a browser.
    mcp.run(transport=_args.transport)
