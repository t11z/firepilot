"""Shared MCP server connection utility for FirePilot CI scripts.

Provides connect_mcp_server, a reusable async helper that starts an MCP server
as a stdio subprocess and returns an initialised ClientSession. Used by
process-issue.py, gate3-dry-run.py, and gate4-deploy.py.
"""

from __future__ import annotations

import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def connect_mcp_server(
    stack: AsyncExitStack,
    module: str,
    env_overrides: dict[str, str] | None = None,
) -> ClientSession | None:
    """Start an MCP server as a stdio subprocess and return an initialised session.

    The subprocess inherits the current environment plus any overrides supplied
    via env_overrides. Pass SCM and ITSM credentials via env_overrides (or
    ensure they are already present in os.environ) so that the MCP server can
    authenticate without those values ever appearing in script code (ADR-0006).

    Args:
        stack: AsyncExitStack that manages the subprocess and session lifetime.
        module: Python module to run as the server (e.g.
                "mcp_strata_cloud_manager.server").
        env_overrides: Optional dict of additional environment variables to
                       inject into the subprocess environment.

    Returns:
        An initialised ClientSession, or None if the connection or
        initialisation failed (error logged to stderr).
    """
    merged_env = {**os.environ, **(env_overrides or {})}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        env=merged_env,
    )
    try:
        read, write = await stack.enter_async_context(stdio_client(params))
        session: ClientSession = await stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        return session
    except Exception as exc:  # noqa: BLE001 — log and degrade gracefully
        print(
            f"ERROR: Failed to start MCP server '{module}': {exc}",
            file=sys.stderr,
        )
        return None
