"""FastMCP server definition for mcp-strata-cloud-manager.

Instantiates the FastMCP server, registers all tools, and provides the
entry point for running the server via `python -m mcp_strata_cloud_manager.server`.
"""

import structlog
from mcp.server.fastmcp import FastMCP

from mcp_strata_cloud_manager.tools.operations import register_operations_tools
from mcp_strata_cloud_manager.tools.read import register_read_tools
from mcp_strata_cloud_manager.tools.write import register_write_tools

# Single FastMCP server instance — all tools are registered on this object
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
    log.info(
        "server_startup",
        server="mcp-strata-cloud-manager",
        mode=settings.firepilot_env,
    )
    mcp.run()


if __name__ == "__main__":
    main()
