"""Pytest configuration and shared fixtures for mcp-itsm tests.

Sets FIREPILOT_ENV=demo before any package imports so that Settings() is
initialized with demo mode. All tests in this suite run against demo mode only.
"""

import json
import os

# Must be set before any package imports so lru_cache captures demo mode
os.environ["FIREPILOT_ENV"] = "demo"

import pytest  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from mcp_itsm.fixtures.itsm import reset_fixture_store  # noqa: E402
from mcp_itsm.server import mcp as _mcp  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_store() -> None:
    """Reset the FixtureStore before each test for isolation.

    This ensures that each test starts with a clean store (pre-seeded with
    the fixture entry "42") and that IDs assigned during one test do not
    interfere with assertions in another.
    """
    reset_fixture_store()


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
    result = await server.call_tool(name, arguments)
    content_list = (
        result[0]
        if isinstance(result, (tuple, list)) and isinstance(result[0], list)
        else result
    )
    assert content_list, f"Tool '{name}' returned empty result"
    return json.loads(content_list[0].text)
