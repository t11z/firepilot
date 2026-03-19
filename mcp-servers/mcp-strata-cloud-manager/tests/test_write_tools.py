"""Tests for write tools: create_security_rule.

All tests run against demo mode fixtures set in conftest.py.
"""

import pytest
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool

# A valid rule creation payload for reuse across tests
VALID_RULE_PAYLOAD = {
    "ticket_id": "CHG0012345",
    "folder": "Shared",
    "position": "pre",
    "name": "allow-test-rule",
    "action": "allow",
    "from_zones": ["web-zone"],
    "to_zones": ["app-zone"],
    "source": ["web-subnet-10.1.0.0-24"],
    "source_user": ["any"],
    "destination": ["app-subnet-10.2.0.0-24"],
    "service": ["application-default"],
    "application": ["ssl"],
    "category": ["any"],
    "description": "Test rule created by automated test",
    "tag": ["firepilot-managed"],
    "log_end": True,
}


class TestCreateSecurityRule:
    """Tests for the create_security_rule tool."""

    async def test_create_security_rule_success(self, server: FastMCP) -> None:
        """Valid input with ticket_id returns a rule with an id field assigned."""
        data = await call_tool(server, "create_security_rule", VALID_RULE_PAYLOAD)
        assert "id" in data
        assert data["id"] == "00000000-0000-0000-0005-000000000001"
        assert "error" not in data

    async def test_create_security_rule_missing_ticket_id(self, server: FastMCP) -> None:
        """Empty ticket_id is rejected with MISSING_TICKET_REF error code."""
        payload = {**VALID_RULE_PAYLOAD, "ticket_id": ""}
        data = await call_tool(server, "create_security_rule", payload)
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"

    async def test_create_security_rule_whitespace_ticket_id(
        self, server: FastMCP
    ) -> None:
        """Whitespace-only ticket_id is rejected with MISSING_TICKET_REF."""
        payload = {**VALID_RULE_PAYLOAD, "ticket_id": "   "}
        data = await call_tool(server, "create_security_rule", payload)
        assert "error" in data
        assert data["error"]["code"] == "MISSING_TICKET_REF"

    async def test_create_security_rule_echoes_fields(self, server: FastMCP) -> None:
        """All submitted input fields are reflected correctly in the response."""
        data = await call_tool(server, "create_security_rule", VALID_RULE_PAYLOAD)
        assert data["name"] == VALID_RULE_PAYLOAD["name"]
        assert data["action"] == VALID_RULE_PAYLOAD["action"]
        # SCM API uses 'from' and 'to' — not from_zones/to_zones
        assert data["from"] == VALID_RULE_PAYLOAD["from_zones"]
        assert data["to"] == VALID_RULE_PAYLOAD["to_zones"]
        assert data["source"] == VALID_RULE_PAYLOAD["source"]
        assert data["destination"] == VALID_RULE_PAYLOAD["destination"]
        assert data["application"] == VALID_RULE_PAYLOAD["application"]
        assert data["tag"] == VALID_RULE_PAYLOAD["tag"]
        assert data["description"] == VALID_RULE_PAYLOAD["description"]
        assert data["log_end"] == VALID_RULE_PAYLOAD["log_end"]

    async def test_create_security_rule_from_to_field_names(
        self, server: FastMCP
    ) -> None:
        """Response uses SCM API field names 'from'/'to', not Python names."""
        data = await call_tool(server, "create_security_rule", VALID_RULE_PAYLOAD)
        assert "from" in data
        assert "to" in data
        assert "from_zones" not in data
        assert "to_zones" not in data
