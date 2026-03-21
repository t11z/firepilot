"""Pytest configuration and shared fixtures for mcp-strata-cloud-manager tests.

Sets FIREPILOT_ENV=demo before any package imports so that Settings() is
initialized with demo mode. All tests in this suite run against demo mode only.
"""

import json
import os

# Must be set before any package imports so lru_cache captures demo mode
os.environ["FIREPILOT_ENV"] = "demo"

import pytest  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from mcp_strata_cloud_manager.server import mcp as _mcp  # noqa: E402


@pytest.fixture(autouse=True)
def reset_fixture_store() -> None:
    """Reset the demo fixture store before each test for isolation.

    This ensures that objects created by write tools in one test do not
    pollute the fixture counts seen by subsequent tests.
    """
    from mcp_strata_cloud_manager.fixtures.store import get_fixture_store

    get_fixture_store().reset()


@pytest.fixture(scope="session")
def server() -> FastMCP:
    """Return the shared FastMCP server instance with all tools registered."""
    return _mcp


async def call_tool(server: FastMCP, name: str, arguments: dict) -> dict:
    """Call a tool on the FastMCP server and return the parsed JSON response.

    Args:
        server: The FastMCP server instance.
        name: Tool name to invoke.
        arguments: Tool argument dict.

    Returns:
        Parsed JSON response as a Python dict.
    """
    # call_tool returns (content_list, is_error) tuple in this mcp SDK version
    result = await server.call_tool(name, arguments)
    content_list = result[0] if isinstance(result, (tuple, list)) and isinstance(result[0], list) else result
    assert content_list, f"Tool '{name}' returned empty result"
    return json.loads(content_list[0].text)
