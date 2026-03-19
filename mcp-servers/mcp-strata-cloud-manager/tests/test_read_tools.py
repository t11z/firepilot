"""Tests for read tools: list_security_rules, list_security_zones,
list_addresses, list_address_groups.

All tests run against demo mode fixtures set in conftest.py.
"""

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


class TestListSecurityRules:
    """Tests for the list_security_rules tool."""

    async def test_list_security_rules_returns_all(self, server: FastMCP) -> None:
        """Calling with folder 'Shared' and position 'pre' returns all 3 pre-rules."""
        data = await call_tool(
            server, "list_security_rules", {"folder": "Shared", "position": "pre"}
        )
        assert data["total"] == 3
        assert len(data["data"]) == 3

    async def test_list_security_rules_filter_by_name(self, server: FastMCP) -> None:
        """Filtering by name 'allow-web-to-app' returns exactly 1 result."""
        data = await call_tool(
            server,
            "list_security_rules",
            {"folder": "Shared", "position": "pre", "name": "allow-web-to-app"},
        )
        assert data["total"] == 1
        assert len(data["data"]) == 1
        assert data["data"][0]["name"] == "allow-web-to-app"

    async def test_list_security_rules_pagination(self, server: FastMCP) -> None:
        """Requesting offset=1 and limit=1 returns 1 result with correct total."""
        data = await call_tool(
            server,
            "list_security_rules",
            {"folder": "Shared", "position": "pre", "offset": 1, "limit": 1},
        )
        assert data["total"] == 3  # Total of all matching rules
        assert len(data["data"]) == 1
        assert data["limit"] == 1
        assert data["offset"] == 1

    async def test_list_security_rules_post_returns_empty(self, server: FastMCP) -> None:
        """Querying post-rules for 'Shared' returns an empty list."""
        data = await call_tool(
            server, "list_security_rules", {"folder": "Shared", "position": "post"}
        )
        assert data["total"] == 0
        assert data["data"] == []

    async def test_list_security_rules_from_to_fields_present(
        self, server: FastMCP
    ) -> None:
        """Security rules include 'from' and 'to' fields (SCM API names, not from_/to_)."""
        data = await call_tool(
            server, "list_security_rules", {"folder": "Shared", "position": "pre"}
        )
        rule = data["data"][0]
        assert "from" in rule
        assert "to" in rule
        # Python reserved word aliases must NOT appear in output
        assert "from_" not in rule
        assert "to_" not in rule


class TestListSecurityZones:
    """Tests for the list_security_zones tool."""

    async def test_list_security_zones_returns_all(self, server: FastMCP) -> None:
        """Calling with folder 'Shared' returns all 4 fixture zones."""
        data = await call_tool(server, "list_security_zones", {"folder": "Shared"})
        assert data["total"] == 4
        assert len(data["data"]) == 4

    async def test_list_security_zones_filter_by_name(self, server: FastMCP) -> None:
        """Filtering by name 'untrust-zone' returns exactly 1 zone."""
        data = await call_tool(
            server, "list_security_zones", {"folder": "Shared", "name": "untrust-zone"}
        )
        assert data["total"] == 1
        assert data["data"][0]["name"] == "untrust-zone"

    async def test_list_security_zones_structure(self, server: FastMCP) -> None:
        """Zone objects include expected fields matching the SCM API schema."""
        data = await call_tool(server, "list_security_zones", {"folder": "Shared"})
        zone = data["data"][0]
        for field in ("id", "name", "folder", "enable_user_identification", "user_acl"):
            assert field in zone, f"Missing field: {field}"


class TestListAddresses:
    """Tests for the list_addresses tool."""

    async def test_list_addresses_returns_all(self, server: FastMCP) -> None:
        """Calling with folder 'Shared' returns all 4 fixture address objects."""
        data = await call_tool(server, "list_addresses", {"folder": "Shared"})
        assert data["total"] == 4
        assert len(data["data"]) == 4

    async def test_list_addresses_filter_by_name(self, server: FastMCP) -> None:
        """Filtering by name returns the correct address object."""
        data = await call_tool(
            server,
            "list_addresses",
            {"folder": "Shared", "name": "web-subnet-10.1.0.0-24"},
        )
        assert data["total"] == 1
        assert data["data"][0]["ip_netmask"] == "10.1.0.0/24"


class TestListAddressGroups:
    """Tests for the list_address_groups tool."""

    async def test_list_address_groups_returns_all(self, server: FastMCP) -> None:
        """Calling with folder 'Shared' returns the 1 fixture address group."""
        data = await call_tool(server, "list_address_groups", {"folder": "Shared"})
        assert data["total"] == 1
        assert len(data["data"]) == 1
        assert data["data"][0]["name"] == "internal-subnets"

    async def test_list_address_groups_static_members(self, server: FastMCP) -> None:
        """The 'internal-subnets' group contains all three tier subnets."""
        data = await call_tool(server, "list_address_groups", {"folder": "Shared"})
        group = data["data"][0]
        assert len(group["static"]) == 3
        assert "web-subnet-10.1.0.0-24" in group["static"]
