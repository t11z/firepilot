"""FastMCP server definition for mcp-strata-cloud-manager.

Instantiates the FastMCP server, registers all tools, and provides the
entry point for running the server via `python -m mcp_strata_cloud_manager.server`.

Transport modes (controlled by environment variables):
    MCP_TRANSPORT=stdio (default)
        Communicates over stdin/stdout. Used for local development,
        Claude Desktop integration, and the test suite.
    MCP_TRANSPORT=sse
        Starts an HTTP/SSE server on 0.0.0.0:$MCP_PORT (default 8080).
        Used when the server must be reachable via HTTP, e.g. when the
        Claude API mcp_servers parameter references it by URL.
"""

import os

import structlog
from mcp.server.fastmcp import FastMCP

from mcp_strata_cloud_manager.tools.operations import register_operations_tools
from mcp_strata_cloud_manager.tools.read import register_read_tools
from mcp_strata_cloud_manager.tools.write import register_write_tools

# Module-level FastMCP instance with all tools registered.
# Used by the test suite (conftest.py imports this object directly) and
# by the default stdio transport path.  The SSE transport path creates
# a separate instance in main() so it can bind to 0.0.0.0 with the
# caller-specified port without affecting the module-level object.
mcp: FastMCP = FastMCP("mcp-strata-cloud-manager")

register_read_tools(mcp)
register_write_tools(mcp)
register_operations_tools(mcp)


def main() -> None:
    """Configure logging, log startup mode, and run the MCP server.

    This is the entry point when executing via:
        python -m mcp_strata_cloud_manager.server
    """
    from mcp_strata_cloud_manager.config import get_settings
    from mcp_strata_cloud_manager.logging import configure_logging

    configure_logging()
    settings = get_settings()
    log = structlog.get_logger(__name__)

    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    port = int(os.environ.get("MCP_PORT", "8080"))

    log.info(
        "server_startup",
        server="mcp-strata-cloud-manager",
        mode=settings.firepilot_env,
        transport=transport,
        port=port if transport == "sse" else None,
    )

    if transport == "sse":
        # Dedicated instance bound to 0.0.0.0 so the SSE endpoint is
        # reachable from outside the process (e.g. a same-host workflow
        # step or a Docker container).  The module-level `mcp` object is
        # intentionally left unchanged so that tests and stdio callers
        # are unaffected.
        _sse_mcp = FastMCP("mcp-strata-cloud-manager", host="0.0.0.0", port=port)
        register_read_tools(_sse_mcp)
        register_write_tools(_sse_mcp)
        register_operations_tools(_sse_mcp)
        _sse_mcp.run(transport="sse")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
