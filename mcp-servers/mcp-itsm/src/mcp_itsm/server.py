"""FastMCP server definition for mcp-itsm.

Instantiates the FastMCP server, registers all tools, and provides the
entry point for running the server via `python -m mcp_itsm.server`.
"""

import structlog
from mcp.server.fastmcp import FastMCP

from mcp_itsm.tools.change_requests import register_change_request_tools
from mcp_itsm.tools.config_files import register_config_file_tools

# Single FastMCP server instance — all tools are registered on this object
mcp: FastMCP = FastMCP("mcp-itsm")

register_change_request_tools(mcp)
register_config_file_tools(mcp)


def main() -> None:
    """Configure logging, log startup mode, and run the MCP server.

    This is the entry point when executing via:
        python -m mcp_itsm.server
    """
    from mcp_itsm.config import get_settings
    from mcp_itsm.logging import configure_logging

    configure_logging()
    settings = get_settings()
    log = structlog.get_logger(__name__)
    log.info(
        "server_startup",
        server="mcp-itsm",
        mode=settings.firepilot_env,
        github_repo=settings.itsm_github_repo or "(not configured)",
    )
    mcp.run()


if __name__ == "__main__":
    main()
